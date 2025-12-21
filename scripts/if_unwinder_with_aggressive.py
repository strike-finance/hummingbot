"""
Insurance Fund Unwinder - With Aggressive Mode

This strategy unwinds Insurance Fund positions with two modes:
- MAKER mode (default): Places limit orders for gradual unwinding
- AGGRESSIVE mode: Uses market orders when risk thresholds are exceeded

Follows Strike's STRIKE_LIQUIDATION_INSURANCE_ADL.md specification:
- Section 6.3: Default behavior (maker) + Aggressive exit path
- Section 6.4: Risk limits and tolerances
"""
from decimal import Decimal
from enum import Enum

from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class UnwindingMode(Enum):
    """Unwinding mode determines how the IF unwinds positions."""
    MAKER = "maker"          # Default: Maker limit orders, profit-focused
    AGGRESSIVE = "aggressive"  # Risk-driven: Market/taker orders, risk reduction


class IFUnwinderAggressive(ScriptStrategyBase):
    """
    Insurance Fund unwinding strategy with risk-based mode switching.

    MAKER MODE (default):
    - Places limit orders at favorable prices (mid ± spread)
    - Unwinds 10% of position per order
    - Refreshes every 30 seconds
    - Aims to profit from position unwinding

    AGGRESSIVE MODE (triggered by risk):
    - Uses market orders for immediate execution
    - Unwinds 30% of position per order
    - Refreshes every 10 seconds
    - Prioritizes risk reduction over profit
    """

    # === MAKER MODE Configuration ===
    maker_spread_bps = 10  # 0.1% spread from mid price
    maker_order_size_pct = 10  # Unwind 10% of position
    maker_refresh_time = 30  # Refresh every 30s

    # === AGGRESSIVE MODE Configuration ===
    aggressive_spread_bps = 2  # 0.02% spread (very tight)
    aggressive_order_size_pct = 30  # Unwind 30% of position
    aggressive_refresh_time = 10  # Refresh every 10s

    # === Risk Thresholds (trigger aggressive mode) ===
    max_utilization_pct = 80  # Switch to aggressive if utilization > 80%
    max_unrealized_loss_usd = 50000  # Switch if loss > $50K
    position_stale_time_sec = 300  # Switch if position not reducing after 5min

    markets = {}

    def __init__(self, connectors):
        super().__init__(connectors)
        self._last_refresh = 0
        self._position_tracking = {}  # Track position sizes over time
        self._mode = UnwindingMode.MAKER

        # Manually populate markets from connectors to ensure active_markets works
        if connectors:
            for exchange_name in connectors:
                if exchange_name not in self.markets:
                    self.markets[exchange_name] = set()
            self.logger().info(f"IF Unwinder initialized with connectors: {list(connectors.keys())}")

    def on_tick(self):
        """Called every second"""
        current_time = self.current_timestamp

        # Determine current refresh time based on mode
        refresh_time = (
            self.aggressive_refresh_time
            if self._mode == UnwindingMode.AGGRESSIVE
            else self.maker_refresh_time
        )

        # Refresh orders every N seconds
        if current_time - self._last_refresh < refresh_time:
            return

        self._last_refresh = current_time

        # Process each connected exchange
        for exchange_name in self.active_markets:
            try:
                self._process_exchange(exchange_name)
            except Exception as e:
                self.logger().error(f"Error processing {exchange_name}: {e}")

    def _process_exchange(self, exchange_name):
        """Process unwinding for one exchange"""
        exchange = self.connectors[exchange_name]

        # Get all positions
        if not hasattr(exchange, 'account_positions'):
            self.logger().info(f"{exchange_name} does not support positions")
            return

        positions = exchange.account_positions

        if not positions:
            self.logger().info("No IF positions to unwind")
            self._mode = UnwindingMode.MAKER  # Reset to maker mode
            return

        # Calculate risk metrics
        self._update_mode(exchange_name, exchange, positions)

        # Process each position
        for trading_pair, position in positions.items():
            try:
                self._unwind_position(exchange_name, trading_pair, position)
            except Exception as e:
                self.logger().error(f"Error unwinding {trading_pair}: {e}")

    def _update_mode(self, exchange_name, exchange, positions):
        """Determine if we should switch to aggressive mode"""
        try:
            # Get IF account balance
            balance = exchange.get_balance("USDT")
            if balance <= 0:
                balance = 1000000  # Fallback if can't get balance

            # Calculate total position value and unrealized PnL
            total_position_value = 0
            total_unrealized_pnl = 0

            for trading_pair, position in positions.items():
                try:
                    mid_price = exchange.get_mid_price(trading_pair)
                    position_size = float(position.amount)
                    entry_price = float(position.entry_price) if hasattr(position, 'entry_price') else mid_price

                    # Position value
                    position_value = abs(position_size * mid_price)
                    total_position_value += position_value

                    # Unrealized PnL
                    unrealized_pnl = (mid_price - entry_price) * position_size
                    total_unrealized_pnl += unrealized_pnl

                except Exception as e:
                    self.logger().warning(f"Error calculating metrics for {trading_pair}: {e}")

            # Calculate utilization
            utilization_pct = (total_position_value / balance) * 100

            # Check for stale positions
            current_time = self.current_timestamp
            position_stale = False

            for trading_pair, position in positions.items():
                position_key = f"{exchange_name}_{trading_pair}"
                position_size = abs(float(position.amount))

                if position_key in self._position_tracking:
                    first_seen_time, first_seen_size = self._position_tracking[position_key]

                    # If position hasn't reduced significantly in X minutes
                    time_elapsed = current_time - first_seen_time
                    size_reduction_pct = ((first_seen_size - position_size) / first_seen_size) * 100

                    if time_elapsed > self.position_stale_time_sec and size_reduction_pct < 10:
                        position_stale = True
                        self.logger().warning(
                            f"Position {trading_pair} stale: {time_elapsed}s elapsed, "
                            f"only {size_reduction_pct:.1f}% reduced"
                        )
                else:
                    # First time seeing this position
                    self._position_tracking[position_key] = (current_time, position_size)

            # Determine mode based on risk metrics
            old_mode = self._mode

            if (
                utilization_pct > self.max_utilization_pct or
                total_unrealized_pnl < -self.max_unrealized_loss_usd or
                position_stale
            ):
                self._mode = UnwindingMode.AGGRESSIVE
            else:
                self._mode = UnwindingMode.MAKER

            # Log mode changes
            if old_mode != self._mode:
                self.logger().warning(
                    f"Mode changed: {old_mode.value} → {self._mode.value} | "
                    f"Utilization: {utilization_pct:.1f}% | "
                    f"Unrealized PnL: ${total_unrealized_pnl:.2f} | "
                    f"Stale: {position_stale}"
                )
            else:
                self.logger().info(
                    f"Mode: {self._mode.value} | "
                    f"Utilization: {utilization_pct:.1f}% | "
                    f"Unrealized PnL: ${total_unrealized_pnl:.2f}"
                )

        except Exception as e:
            self.logger().error(f"Error updating mode: {e}")
            # Default to maker mode on error
            self._mode = UnwindingMode.MAKER

    def _unwind_position(self, exchange_name, trading_pair, position):
        """Unwind a single position using current mode"""
        exchange = self.connectors[exchange_name]

        # Get position size
        position_size = abs(float(position.amount))

        if position_size < 0.001:  # Position too small
            return

        self.logger().info(
            f"IF Position: {trading_pair} size={position.amount} | Mode: {self._mode.value}"
        )

        # Cancel existing orders for this pair
        self._cancel_orders(exchange_name, trading_pair)

        # Get current price
        try:
            mid_price = exchange.get_mid_price(trading_pair)
        except Exception as e:
            self.logger().warning(f"Could not get mid price for {trading_pair}: {e}")
            return

        # Mode-specific parameters
        if self._mode == UnwindingMode.AGGRESSIVE:
            spread_bps = self.aggressive_spread_bps
            order_size_pct = self.aggressive_order_size_pct
            use_market_order = True  # Use market orders in aggressive mode
        else:
            spread_bps = self.maker_spread_bps
            order_size_pct = self.maker_order_size_pct
            use_market_order = False

        # Calculate order size
        order_size = position_size * (order_size_pct / 100)
        order_size = max(order_size, 0.001)  # Min order size

        # Determine side
        if float(position.amount) > 0:  # LONG position
            side = "sell"
            spread_multiplier = 1 + (spread_bps / 10000)
        else:  # SHORT position
            side = "buy"
            spread_multiplier = 1 - (spread_bps / 10000)

        # Calculate order price (only used for limit orders)
        order_price = mid_price * spread_multiplier

        # Place order
        if use_market_order:
            self.logger().warning(
                f"🚨 AGGRESSIVE: Placing {side} MARKET order: "
                f"{order_size} {trading_pair}"
            )
            order_type = "market"
            order_price = None  # Market orders don't need price
        else:
            self.logger().info(
                f"Placing {side} limit order: {order_size} {trading_pair} @ {order_price}"
            )
            order_type = "limit"

        try:
            if side == "sell":
                if order_type == "market":
                    self.sell(
                        connector_name=exchange_name,
                        trading_pair=trading_pair,
                        amount=Decimal(str(order_size)),
                        order_type="market"
                    )
                else:
                    self.sell(
                        connector_name=exchange_name,
                        trading_pair=trading_pair,
                        amount=Decimal(str(order_size)),
                        order_type="limit",
                        price=Decimal(str(order_price))
                    )
            else:
                if order_type == "market":
                    self.buy(
                        connector_name=exchange_name,
                        trading_pair=trading_pair,
                        amount=Decimal(str(order_size)),
                        order_type="market"
                    )
                else:
                    self.buy(
                        connector_name=exchange_name,
                        trading_pair=trading_pair,
                        amount=Decimal(str(order_size)),
                        order_type="limit",
                        price=Decimal(str(order_price))
                    )

            self.logger().info("✓ Order placed successfully")

        except Exception as e:
            self.logger().error(f"Failed to place order: {e}")

    def _cancel_orders(self, exchange_name, trading_pair):
        """Cancel all active orders for a trading pair"""
        try:
            # Get active orders
            active_orders = self.get_active_orders(exchange_name)

            for order in active_orders:
                if order.trading_pair == trading_pair:
                    self.logger().info(f"Canceling old order: {order.client_order_id}")
                    self.cancel(exchange_name, order.trading_pair, order.client_order_id)

        except Exception as e:
            self.logger().error(f"Error canceling orders: {e}")

    def on_stop(self):
        """Called when strategy stops"""
        self.logger().info("Insurance Fund Unwinder stopped")

        # Cancel all orders
        for exchange_name in self.active_markets:
            try:
                self.cancel_all_orders(exchange_name)
            except Exception:
                pass

    def format_status(self) -> str:
        """Display strategy status"""
        lines = []
        lines.append("\n╔══════════════════════════════════════════════╗")
        lines.append("║  Insurance Fund Unwinder (Aggressive Mode)   ║")
        lines.append("╚══════════════════════════════════════════════╝")

        lines.append(f"\nCurrent Mode: {self._mode.value.upper()}")

        for exchange_name in self.active_markets:
            exchange = self.connectors[exchange_name]
            lines.append(f"\nExchange: {exchange_name}")

            # Show balance
            try:
                balance = exchange.get_balance("USDT")
                lines.append(f"  Balance: {balance:.2f} USDT")
            except Exception:
                pass

            # Show positions
            if hasattr(exchange, 'account_positions'):
                positions = exchange.account_positions
                if positions:
                    lines.append(f"  Positions: {len(positions)}")
                    for trading_pair, position in positions.items():
                        lines.append(f"    {trading_pair}: {position.amount}")
                else:
                    lines.append("  Positions: None")

            # Show active orders
            try:
                active_orders = self.get_active_orders(exchange_name)
                lines.append(f"  Active Orders: {len(active_orders)}")
                for order in active_orders:
                    lines.append(
                        f"    {order.trading_pair} {order.trade_type.name} "
                        f"{order.amount} @ {order.price}"
                    )
            except Exception:
                pass

        lines.append("\n═══ MAKER MODE Configuration ═══")
        lines.append(f"  Spread: {self.maker_spread_bps} bps (0.{self.maker_spread_bps}%)")
        lines.append(f"  Order Size: {self.maker_order_size_pct}% of position")
        lines.append(f"  Refresh Time: {self.maker_refresh_time}s")

        lines.append("\n═══ AGGRESSIVE MODE Configuration ═══")
        lines.append(f"  Spread: {self.aggressive_spread_bps} bps (0.{self.aggressive_spread_bps}%)")
        lines.append(f"  Order Size: {self.aggressive_order_size_pct}% of position")
        lines.append(f"  Refresh Time: {self.aggressive_refresh_time}s")
        lines.append("  Order Type: MARKET")

        lines.append("\n═══ Risk Thresholds ═══")
        lines.append(f"  Max Utilization: {self.max_utilization_pct}%")
        lines.append(f"  Max Unrealized Loss: ${self.max_unrealized_loss_usd:,.0f}")
        lines.append(f"  Position Stale Time: {self.position_stale_time_sec}s")

        return "\n".join(lines)

    def __str__(self) -> str:
        """Quick status for inline display"""
        try:
            for exchange_name in list(self.connectors.keys()):
                exchange = self.connectors[exchange_name]
                balance = float(exchange.get_balance("USDT"))

                positions_count = 0
                if hasattr(exchange, 'account_positions') and exchange.account_positions:
                    positions_count = len(exchange.account_positions)

                status = "Active" if positions_count > 0 else "Waiting"
                return (
                    f"Mode: {self._mode.value.upper()} | "
                    f"Balance: ${balance:,.0f} | "
                    f"Positions: {positions_count} | "
                    f"{status}"
                )
        except Exception:
            pass

        return f"Mode: {self._mode.value.upper()} | Initializing..."
