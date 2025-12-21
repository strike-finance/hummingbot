"""
Simple Insurance Fund Test Script
"""
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class TestIFSimple(ScriptStrategyBase):
    """
    Minimal test script to verify Hummingbot can connect to Strike IF account
    """

    markets = {}

    def on_tick(self):
        if self.current_timestamp % 10 == 0:  # Every 10 seconds
            self.logger().info("IF Test Script Running - Checking connection...")

            # List all active markets
            for exchange_name in self.active_markets:
                exchange = self.connectors[exchange_name]
                self.logger().info(f"Connected to: {exchange_name}")

                # Try to get balance
                try:
                    balance = exchange.get_balance("USDT")
                    self.logger().info(f"USDT Balance: {balance}")
                except Exception as e:
                    self.logger().error(f"Error getting balance: {e}")

                # Try to get positions
                try:
                    if hasattr(exchange, 'account_positions'):
                        positions = exchange.account_positions
                        if positions:
                            self.logger().info(f"Active positions: {len(positions)}")
                            for symbol, position in positions.items():
                                self.logger().info(f"  {symbol}: {position.amount}")
                        else:
                            self.logger().info("No active positions")
                except Exception as e:
                    self.logger().error(f"Error getting positions: {e}")
