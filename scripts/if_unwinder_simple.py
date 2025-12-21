"""
Insurance Fund Unwinder - Simplified Version

This strategy unwinds Insurance Fund positions by placing limit orders.
"""
from decimal import Decimal

from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class IFUnwinderSimple(ScriptStrategyBase):
    """
    Simple Insurance Fund unwinding strategy

    Places limit orders to gradually unwind IF positions with minimal market impact.
    """

    # Configuration
    maker_spread_bps = 10  # 0.1% spread from mark price
    order_size_pct = 10    # Unwind 10% of position at a time
    refresh_time = 30      # Refresh orders every 30 seconds

    markets = {}

    def __init__(self, connectors):
        super().__init__(connectors)
        self._last_refresh = 0
        self._active_orders = {}

    def on_tick(self):
        """Called every second"""
        current_time = self.current_timestamp

        # Refresh orders every N seconds
        if current_time - self._last_refresh < self.refresh_time:
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
            return

        # Process each position
        for trading_pair, position in positions.items():
            try:
                self._unwind_position(exchange_name, trading_pair, position)
            except Exception as e:
                self.logger().error(f"Error unwinding {trading_pair}: {e}")

    def _unwind_position(self, exchange_name, trading_pair, position):
        """Unwind a single position"""
        exchange = self.connectors[exchange_name]

        # Get position size
        position_size = abs(float(position.amount))

        if position_size < 0.001:  # Position too small
            return

        self.logger().info(f"IF Position: {trading_pair} size={position.amount}")

        # Cancel existing orders for this pair
        self._cancel_orders(exchange_name, trading_pair)

        # Calculate order size (10% of position)
        order_size = position_size * (self.order_size_pct / 100)
        order_size = max(order_size, 0.001)  # Min order size

        # Get current price
        try:
            mid_price = exchange.get_mid_price(trading_pair)
        except Exception as e:
            self.logger().warning(f"Could not get mid price for {trading_pair}: {e}")
            return

        # Calculate order price with spread
        spread_decimal = Decimal(str(self.maker_spread_bps)) / Decimal("10000")

        # If IF is LONG, we SELL (close position)
        # If IF is SHORT, we BUY (close position)
        if float(position.amount) > 0:  # LONG position
            # Sell at mark price + spread (higher price)
            order_price = mid_price * (1 + float(spread_decimal))
            side = "sell"
        else:  # SHORT position
            # Buy at mark price - spread (lower price)
            order_price = mid_price * (1 - float(spread_decimal))
            side = "buy"

        # Place order
        self.logger().info(f"Placing {side} order: {order_size} {trading_pair} @ {order_price}")

        try:
            if side == "sell":
                self.sell(
                    connector_name=exchange_name,
                    trading_pair=trading_pair,
                    amount=Decimal(str(order_size)),
                    order_type="limit",
                    price=Decimal(str(order_price))
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
        lines.append("║  Insurance Fund Unwinder Status              ║")
        lines.append("╚══════════════════════════════════════════════╝")

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
                    lines.append(f"    {order.trading_pair} {order.trade_type.name} {order.amount} @ {order.price}")
            except Exception:
                pass

        lines.append("\nConfiguration:")
        lines.append(f"  Maker Spread: {self.maker_spread_bps} bps (0.{self.maker_spread_bps}%)")
        lines.append(f"  Order Size: {self.order_size_pct}% of position")
        lines.append(f"  Refresh Time: {self.refresh_time}s")

        return "\n".join(lines)
