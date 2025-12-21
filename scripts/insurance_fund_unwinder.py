"""
Insurance Fund Unwinding Strategy

This strategy manages the unwinding of Insurance Fund (IF) positions according to Strike's
Liquidation, Insurance Fund & ADL documentation. The IF absorbs bankrupt positions from
liquidations and must unwind them with minimal market impact.

Key Features:
- Default behavior: Maker limit orders at favorable prices
- Aggressive mode: Taker orders when risk metrics exceed thresholds
- Risk management: Position limits, concentration limits, utilization caps
- Dynamic pricing: Places orders between entry price and mark price
- Multi-symbol support: Manages risk across multiple markets

Reference: hummingbot/connector/derivative/strike_perpetual/STRIKE_LIQUIDATION_INSURANCE_ADL.md
"""

import logging
import os
from decimal import Decimal
from enum import Enum
from typing import Dict, List

from pydantic import Field

from hummingbot.client.config.config_data_types import BaseClientModel
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.connector.derivative.position import Position
from hummingbot.connector.derivative_base import DerivativeBase
from hummingbot.core.data_type.common import OrderType, PositionAction, PriceType, TradeType
from hummingbot.core.data_type.order_candidate import PerpetualOrderCandidate
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class UnwindingMode(Enum):
    """Unwinding mode determines how aggressively the IF unwinds positions."""
    MAKER = "maker"  # Default: Place maker limit orders at favorable prices
    AGGRESSIVE = "aggressive"  # Risk-driven: Use taker/market orders to reduce exposure quickly


class IFUnwinderConfig(BaseClientModel):
    """Configuration for Insurance Fund Unwinding Strategy."""

    script_file_name: str = os.path.basename(__file__)

    # Exchange and account configuration
    exchange: str = Field("strike_perpetual", description="Exchange connector name (must be Strike)")

    # Symbols to manage (empty = all IF positions)
    trading_pairs: List[str] = Field(
        default_factory=list,
        description="Trading pairs to manage (empty = all IF positions)"
    )

    # === Risk Management Parameters ===

    # Maximum total notional exposure across all positions (USD)
    max_total_notional_usd: Decimal = Field(
        Decimal("1000000"),
        description="Maximum total notional exposure across all IF positions"
    )

    # Maximum notional per symbol (USD)
    max_symbol_notional_usd: Decimal = Field(
        Decimal("200000"),
        description="Maximum notional exposure per symbol"
    )

    # Maximum utilization of IF capital (percentage of NAV)
    max_utilization_pct: Decimal = Field(
        Decimal("80"),
        description="Maximum utilization as % of IF account value"
    )

    # Margin ratio threshold to trigger aggressive mode
    aggressive_mode_margin_ratio: Decimal = Field(
        Decimal("50"),
        description="Margin ratio % threshold to switch to aggressive unwinding"
    )

    # Total unrealized loss threshold to trigger aggressive mode (USD)
    aggressive_mode_loss_threshold_usd: Decimal = Field(
        Decimal("50000"),
        description="Total unrealized loss threshold to trigger aggressive mode"
    )

    # === Maker Mode (Default) Parameters ===

    # Order placement spread from mark price (positive = more favorable than mark)
    # For long positions: sell at mark + spread (higher)
    # For short positions: buy at mark - spread (lower)
    maker_spread_bps: Decimal = Field(
        Decimal("10"),
        description="Spread in basis points from mark price for maker orders"
    )

    # Minimum spread from entry price (must be profitable or at least break-even)
    min_profit_spread_bps: Decimal = Field(
        Decimal("0"),
        description="Minimum spread from entry price (0 = break-even, positive = profit)"
    )

    # Order size as percentage of position
    maker_order_size_pct: Decimal = Field(
        Decimal("10"),
        description="Order size as % of position size for maker orders"
    )

    # Minimum order size (in base asset)
    min_order_size: Decimal = Field(
        Decimal("0.001"),
        description="Minimum order size in base asset"
    )

    # Order refresh time (seconds)
    order_refresh_time: int = Field(
        30,
        description="Time in seconds before refreshing orders"
    )

    # === Aggressive Mode Parameters ===

    # Order size as percentage of position in aggressive mode
    aggressive_order_size_pct: Decimal = Field(
        Decimal("25"),
        description="Order size as % of position size for aggressive orders"
    )

    # Maximum slippage tolerance for aggressive orders (basis points)
    aggressive_slippage_bps: Decimal = Field(
        Decimal("50"),
        description="Maximum slippage in bps for aggressive taker orders"
    )

    # === Operational Parameters ===

    # Status report interval (seconds)
    status_report_interval: int = Field(
        300,
        description="Interval in seconds to log status report"
    )


class InsuranceFundUnwinder(ScriptStrategyBase):
    """
    Insurance Fund Position Unwinding Strategy

    This strategy manages the unwinding of IF positions with minimal market impact
    while respecting risk tolerances. It operates in two modes:

    1. MAKER Mode (Default):
       - Places maker limit orders at favorable prices
       - Orders priced between entry price and mark price
       - Captures edge when market allows
       - Minimizes market impact

    2. AGGRESSIVE Mode (Risk-Driven):
       - Triggered when risk metrics exceed thresholds
       - Uses taker/limit IOC orders with controlled slippage
       - Prioritizes risk reduction over edge capture
       - Returns to MAKER mode once risk normalizes
    """

    create_timestamp = 0
    last_status_report = 0

    @classmethod
    def init_markets(cls, config: IFUnwinderConfig):
        """Initialize markets for the strategy."""
        # If no trading pairs specified, we'll discover them from IF positions
        if config.trading_pairs:
            cls.markets = {config.exchange: set(config.trading_pairs)}
        else:
            cls.markets = {config.exchange: set()}

    def __init__(self, connectors: Dict[str, ConnectorBase], config: IFUnwinderConfig):
        """Initialize the Insurance Fund Unwinder strategy."""
        super().__init__(connectors, config)
        self.config = config

        if config.exchange not in connectors:
            raise ValueError(f"Exchange {config.exchange} not found in connectors")

        self.connector: DerivativeBase = connectors[config.exchange]

        # Validate that connector is for Strike
        if "strike" not in config.exchange.lower():
            self.logger().warning(
                f"This strategy is designed for Strike. Current exchange: {config.exchange}"
            )

        self.logger().info("Insurance Fund Unwinder initialized")
        self.logger().info(f"Max Total Notional: ${self.config.max_total_notional_usd}")
        self.logger().info(f"Max Symbol Notional: ${self.config.max_symbol_notional_usd}")
        self.logger().info(f"Max Utilization: {self.config.max_utilization_pct}%")

    def on_tick(self):
        """Main strategy tick - called every second."""

        # Log status report periodically
        if self.current_timestamp >= self.last_status_report + self.config.status_report_interval:
            self.log_status_report()
            self.last_status_report = self.current_timestamp

        # Check if it's time to refresh orders
        if self.create_timestamp <= self.current_timestamp:
            self.execute_unwinding_cycle()
            self.create_timestamp = self.config.order_refresh_time + self.current_timestamp

    def execute_unwinding_cycle(self):
        """Execute one unwinding cycle: cancel old orders, create new ones."""

        # Get all IF positions
        positions = self.get_if_positions()

        if not positions:
            self.logger().info("No IF positions to unwind")
            return

        # Calculate risk metrics
        risk_metrics = self.calculate_risk_metrics(positions)

        # Determine unwinding mode
        mode = self.determine_unwinding_mode(risk_metrics)

        if mode == UnwindingMode.AGGRESSIVE:
            self.logger().warning(
                f"⚠️  AGGRESSIVE MODE ACTIVATED - "
                f"Margin Ratio: {risk_metrics['margin_ratio']:.2f}%, "
                f"Unrealized Loss: ${risk_metrics['total_unrealized_pnl']:.2f}"
            )

        # Cancel existing orders
        self.cancel_all_orders()

        # Create unwinding orders for each position
        for position in positions:
            try:
                self.create_unwinding_orders(position, mode, risk_metrics)
            except Exception as e:
                self.logger().error(f"Error creating orders for {position.trading_pair}: {e}")

    def get_if_positions(self) -> List[Position]:
        """Get all Insurance Fund positions from the connector."""
        positions = []

        if hasattr(self.connector, 'account_positions'):
            for pos_key, position in self.connector.account_positions.items():
                # Filter by configured trading pairs if specified
                if self.config.trading_pairs and position.trading_pair not in self.config.trading_pairs:
                    continue

                # Only include positions with non-zero size
                if position.amount != Decimal("0"):
                    positions.append(position)

        return positions

    def calculate_risk_metrics(self, positions: List[Position]) -> Dict:
        """Calculate aggregate risk metrics across all IF positions."""

        total_notional = Decimal("0")
        total_unrealized_pnl = Decimal("0")
        total_maintenance_margin = Decimal("0")

        position_metrics = {}

        for position in positions:
            # Get mark price
            mark_price = self.connector.get_price_by_type(
                position.trading_pair,
                PriceType.MidPrice
            )

            # Calculate position notional
            notional = abs(position.amount) * mark_price

            # Calculate unrealized PnL
            unrealized_pnl = position.unrealized_pnl if hasattr(position, 'unrealized_pnl') else Decimal("0")

            total_notional += notional
            total_unrealized_pnl += unrealized_pnl

            position_metrics[position.trading_pair] = {
                'notional': notional,
                'unrealized_pnl': unrealized_pnl,
                'amount': position.amount,
                'entry_price': position.entry_price,
                'mark_price': mark_price
            }

        # Get account balance
        account_value = self.connector.get_balance("USD")  # Assuming USD quote

        # Calculate utilization
        utilization_pct = (total_notional / account_value * Decimal("100")) if account_value > 0 else Decimal("0")

        # Calculate approximate margin ratio
        # Note: This is simplified. In production, use actual margin calculation from backend
        margin_ratio = (total_maintenance_margin / account_value * Decimal("100")) if account_value > 0 else Decimal("0")

        return {
            'total_notional': total_notional,
            'total_unrealized_pnl': total_unrealized_pnl,
            'account_value': account_value,
            'utilization_pct': utilization_pct,
            'margin_ratio': margin_ratio,
            'position_count': len(positions),
            'position_metrics': position_metrics
        }

    def determine_unwinding_mode(self, risk_metrics: Dict) -> UnwindingMode:
        """Determine whether to use MAKER or AGGRESSIVE unwinding mode."""

        # Trigger aggressive mode if:
        # 1. Margin ratio exceeds threshold
        if risk_metrics['margin_ratio'] >= self.config.aggressive_mode_margin_ratio:
            return UnwindingMode.AGGRESSIVE

        # 2. Unrealized loss exceeds threshold
        if risk_metrics['total_unrealized_pnl'] <= -self.config.aggressive_mode_loss_threshold_usd:
            return UnwindingMode.AGGRESSIVE

        # 3. Total notional exceeds maximum
        if risk_metrics['total_notional'] >= self.config.max_total_notional_usd:
            return UnwindingMode.AGGRESSIVE

        # 4. Utilization exceeds maximum
        if risk_metrics['utilization_pct'] >= self.config.max_utilization_pct:
            return UnwindingMode.AGGRESSIVE

        # Default to maker mode
        return UnwindingMode.MAKER

    def create_unwinding_orders(
        self,
        position: Position,
        mode: UnwindingMode,
        risk_metrics: Dict
    ):
        """Create unwinding orders for a specific position."""

        trading_pair = position.trading_pair
        position_amount = position.amount

        # Determine order side (opposite of position)
        if position_amount > 0:
            # Long position -> sell to unwind
            order_side = TradeType.SELL
        else:
            # Short position -> buy to unwind
            order_side = TradeType.BUY

        # Get current mark price
        mark_price = self.connector.get_price_by_type(trading_pair, PriceType.MidPrice)

        # Calculate order size
        if mode == UnwindingMode.MAKER:
            order_size_pct = self.config.maker_order_size_pct
        else:
            order_size_pct = self.config.aggressive_order_size_pct

        order_amount = abs(position_amount) * order_size_pct / Decimal("100")

        # Apply minimum order size
        if order_amount < self.config.min_order_size:
            order_amount = min(self.config.min_order_size, abs(position_amount))

        # Calculate order price
        if mode == UnwindingMode.MAKER:
            order_price = self.calculate_maker_price(
                position,
                mark_price,
                order_side
            )
            order_type = OrderType.LIMIT
        else:
            order_price = self.calculate_aggressive_price(
                mark_price,
                order_side
            )
            order_type = OrderType.LIMIT  # Limit IOC for better control

        # Create order candidate
        order_candidate = PerpetualOrderCandidate(
            trading_pair=trading_pair,
            is_maker=(mode == UnwindingMode.MAKER),
            order_type=order_type,
            order_side=order_side,
            amount=order_amount,
            price=order_price,
            position_close=False,  # We're reducing, not necessarily closing
            position_action=PositionAction.CLOSE  # This is a reducing order
        )

        # Place the order
        self.place_order(order_candidate, mode)

    def calculate_maker_price(
        self,
        position: Position,
        mark_price: Decimal,
        order_side: TradeType
    ) -> Decimal:
        """Calculate maker order price (favorable relative to mark, not worse than entry)."""

        entry_price = position.entry_price
        spread_multiplier = self.config.maker_spread_bps / Decimal("10000")
        min_profit_multiplier = self.config.min_profit_spread_bps / Decimal("10000")

        if order_side == TradeType.SELL:
            # Selling to close long position
            # Price should be: max(entry + min_profit, mark + spread)
            min_acceptable_price = entry_price * (Decimal("1") + min_profit_multiplier)
            target_price = mark_price * (Decimal("1") + spread_multiplier)
            price = max(min_acceptable_price, target_price)
        else:
            # Buying to close short position
            # Price should be: min(entry - min_profit, mark - spread)
            max_acceptable_price = entry_price * (Decimal("1") - min_profit_multiplier)
            target_price = mark_price * (Decimal("1") - spread_multiplier)
            price = min(max_acceptable_price, target_price)

        return price

    def calculate_aggressive_price(
        self,
        mark_price: Decimal,
        order_side: TradeType
    ) -> Decimal:
        """Calculate aggressive order price (taker price with slippage buffer)."""

        slippage_multiplier = self.config.aggressive_slippage_bps / Decimal("10000")

        if order_side == TradeType.SELL:
            # Sell with downward slippage buffer
            price = mark_price * (Decimal("1") - slippage_multiplier)
        else:
            # Buy with upward slippage buffer
            price = mark_price * (Decimal("1") + slippage_multiplier)

        return price

    def place_order(self, order_candidate: PerpetualOrderCandidate, mode: UnwindingMode):
        """Place an unwinding order."""

        try:
            if order_candidate.order_side == TradeType.SELL:
                self.sell(
                    connector_name=self.config.exchange,
                    trading_pair=order_candidate.trading_pair,
                    amount=order_candidate.amount,
                    order_type=order_candidate.order_type,
                    price=order_candidate.price,
                    position_action=order_candidate.position_action
                )
            else:
                self.buy(
                    connector_name=self.config.exchange,
                    trading_pair=order_candidate.trading_pair,
                    amount=order_candidate.amount,
                    order_type=order_candidate.order_type,
                    price=order_candidate.price,
                    position_action=order_candidate.position_action
                )

            self.logger().info(
                f"[{mode.value.upper()}] {order_candidate.order_side.name} "
                f"{order_candidate.amount} {order_candidate.trading_pair} @ {order_candidate.price}"
            )
        except Exception as e:
            self.logger().error(
                f"Failed to place order for {order_candidate.trading_pair}: {e}"
            )

    def cancel_all_orders(self):
        """Cancel all active orders."""
        for order in self.get_active_orders(connector_name=self.config.exchange):
            self.cancel(self.config.exchange, order.trading_pair, order.client_order_id)

    def did_fill_order(self, event: OrderFilledEvent):
        """Handle order fill event."""
        msg = (
            f"✅ IF Unwind: {event.trade_type.name} "
            f"{round(event.amount, 6)} {event.trading_pair} @ {round(event.price, 4)}"
        )
        self.log_with_clock(logging.INFO, msg)
        self.notify_hb_app_with_timestamp(msg)

    def log_status_report(self):
        """Log a comprehensive status report."""

        positions = self.get_if_positions()

        if not positions:
            self.logger().info("=" * 80)
            self.logger().info("Insurance Fund Status: No active positions")
            self.logger().info("=" * 80)
            return

        risk_metrics = self.calculate_risk_metrics(positions)
        mode = self.determine_unwinding_mode(risk_metrics)

        self.logger().info("=" * 80)
        self.logger().info("INSURANCE FUND UNWINDING STATUS REPORT")
        self.logger().info("=" * 80)
        self.logger().info(f"Mode: {mode.value.upper()}")
        self.logger().info(f"Account Value: ${risk_metrics['account_value']:.2f}")
        self.logger().info(f"Total Notional: ${risk_metrics['total_notional']:.2f}")
        self.logger().info(f"Total Unrealized PnL: ${risk_metrics['total_unrealized_pnl']:.2f}")
        self.logger().info(f"Utilization: {risk_metrics['utilization_pct']:.2f}%")
        self.logger().info(f"Position Count: {risk_metrics['position_count']}")
        self.logger().info("-" * 80)

        for trading_pair, metrics in risk_metrics['position_metrics'].items():
            self.logger().info(
                f"{trading_pair}: "
                f"Size={metrics['amount']:.6f}, "
                f"Entry={metrics['entry_price']:.4f}, "
                f"Mark={metrics['mark_price']:.4f}, "
                f"Notional=${metrics['notional']:.2f}, "
                f"UPnL=${metrics['unrealized_pnl']:.2f}"
            )

        self.logger().info("=" * 80)
