"""
Insurance Fund Unwinder - With Monitoring

Complete IF management: unwinding + real-time monitoring + alerts.

Combines:
- Dual-mode unwinding (MAKER + AGGRESSIVE)
- Real-time metrics dashboard
- Automatic alerting
- Performance tracking
- Hourly reports
"""
import time
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict

from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class UnwindingMode(Enum):
    """Unwinding mode"""
    MAKER = "maker"
    AGGRESSIVE = "aggressive"


class IFUnwinderMonitored(ScriptStrategyBase):
    """
    Complete Insurance Fund management with monitoring.
    """

    # === UNWINDING Configuration ===
    maker_spread_bps = 10
    maker_order_size_pct = 10
    maker_refresh_time = 30

    aggressive_spread_bps = 2
    aggressive_order_size_pct = 30
    aggressive_refresh_time = 10

    # === RISK Thresholds ===
    max_utilization_pct = 80
    max_unrealized_loss_usd = 50000
    position_stale_time_sec = 300

    # === MONITORING Configuration ===
    dashboard_refresh = 30  # Show dashboard every 30s
    report_interval = 3600  # Hourly reports

    markets = {}

    def __init__(self, connectors):
        super().__init__(connectors)
        self._last_refresh = 0
        self._last_dashboard = 0
        self._last_report = 0
        self._session_start = time.time()

        self._position_tracking = {}
        self._mode = UnwindingMode.MAKER

        # Monitoring data
        self._metrics_history = []
        self._session_metrics = {
            'positions_handled': 0,
            'orders_placed': 0,
            'orders_filled': 0,
            'mode_switches': 0,
            'alerts_triggered': 0,
            'max_utilization': 0,
            'max_loss': 0
        }
        self._active_alerts = set()

        # CRITICAL FIX: Manually populate markets from connectors
        # This ensures active_markets is populated even if markets class var is empty
        if connectors:
            for exchange_name in connectors:
                if exchange_name not in self.markets:
                    self.markets[exchange_name] = set()
            self.logger().info(f"IF Unwinder initialized with connectors: {list(connectors.keys())}")

    def on_tick(self):
        """Called every second"""
        current_time = self.current_timestamp

        # Determine refresh time based on mode
        refresh_time = (
            self.aggressive_refresh_time
            if self._mode == UnwindingMode.AGGRESSIVE
            else self.maker_refresh_time
        )

        # Process unwinding
        if current_time - self._last_refresh >= refresh_time:
            self._last_refresh = current_time

            # Iterate over all active markets
            for exchange_name in self.active_markets:
                try:
                    self._process_exchange(exchange_name)
                except Exception as e:
                    self.logger().error(f"Error processing {exchange_name}: {e}")

        # Update dashboard
        if current_time - self._last_dashboard >= self.dashboard_refresh:
            self._last_dashboard = current_time
            self._display_dashboard()

        # Generate report
        if current_time - self._last_report >= self.report_interval:
            self._last_report = current_time
            self._generate_report()

    def _process_exchange(self, exchange_name):
        """Process unwinding and collect metrics"""
        exchange = self.connectors[exchange_name]

        if not hasattr(exchange, 'account_positions'):
            return

        positions = exchange.account_positions

        if not positions:
            self._mode = UnwindingMode.MAKER
            return

        # Collect metrics and update mode
        metrics = self._collect_metrics(exchange_name, exchange, positions)
        self._update_mode(metrics)
        self._check_alerts(metrics)

        # Unwind positions
        for trading_pair, position in positions.items():
            try:
                self._unwind_position(exchange_name, trading_pair, position)
            except Exception as e:
                self.logger().error(f"Error unwinding {trading_pair}: {e}")

    def _collect_metrics(self, exchange_name, exchange, positions) -> Dict:
        """Collect current IF metrics"""
        metrics = {
            'timestamp': datetime.now(),
            'balance': 0,
            'total_position_value': 0,
            'total_unrealized_pnl': 0,
            'utilization_pct': 0,
            'num_positions': len(positions),
            'positions': {}
        }

        try:
            balance = exchange.get_balance("USDT")
            metrics['balance'] = float(balance)

            for trading_pair, position in positions.items():
                try:
                    mid_price = exchange.get_mid_price(trading_pair)
                    position_size = float(position.amount)
                    entry_price = float(position.entry_price) if hasattr(position, 'entry_price') else mid_price

                    position_value = abs(position_size * mid_price)
                    unrealized_pnl = (mid_price - entry_price) * position_size

                    metrics['positions'][trading_pair] = {
                        'size': position_size,
                        'entry_price': entry_price,
                        'current_price': mid_price,
                        'value': position_value,
                        'pnl': unrealized_pnl
                    }

                    metrics['total_position_value'] += position_value
                    metrics['total_unrealized_pnl'] += unrealized_pnl

                except Exception:
                    pass

            if metrics['balance'] > 0:
                metrics['utilization_pct'] = (metrics['total_position_value'] / metrics['balance']) * 100

            # Update session metrics
            if metrics['utilization_pct'] > self._session_metrics['max_utilization']:
                self._session_metrics['max_utilization'] = metrics['utilization_pct']

            if metrics['total_unrealized_pnl'] < self._session_metrics['max_loss']:
                self._session_metrics['max_loss'] = metrics['total_unrealized_pnl']

        except Exception as e:
            self.logger().error(f"Error collecting metrics: {e}")

        self._metrics_history.append(metrics)
        if len(self._metrics_history) > 360:  # Keep last hour (360 x 10s)
            self._metrics_history.pop(0)

        return metrics

    def _update_mode(self, metrics: Dict):
        """Update unwinding mode based on metrics"""
        current_time = self.current_timestamp
        position_stale = False

        for trading_pair in metrics['positions']:
            position_key = f"{trading_pair}"
            position_size = abs(metrics['positions'][trading_pair]['size'])

            if position_key in self._position_tracking:
                first_seen_time, first_seen_size = self._position_tracking[position_key]
                time_elapsed = current_time - first_seen_time
                size_reduction_pct = ((first_seen_size - position_size) / first_seen_size) * 100

                if time_elapsed > self.position_stale_time_sec and size_reduction_pct < 10:
                    position_stale = True
            else:
                self._position_tracking[position_key] = (current_time, position_size)

        old_mode = self._mode

        if (
            metrics['utilization_pct'] > self.max_utilization_pct or
            metrics['total_unrealized_pnl'] < -self.max_unrealized_loss_usd or
            position_stale
        ):
            self._mode = UnwindingMode.AGGRESSIVE
        else:
            self._mode = UnwindingMode.MAKER

        if old_mode != self._mode:
            self._session_metrics['mode_switches'] += 1
            self.logger().warning(
                f"🔄 MODE SWITCH: {old_mode.value} → {self._mode.value} | "
                f"Util: {metrics['utilization_pct']:.1f}% | "
                f"PnL: ${metrics['total_unrealized_pnl']:,.2f}"
            )

    def _check_alerts(self, metrics: Dict):
        """Check for alert conditions"""
        # High utilization
        if metrics['utilization_pct'] > 70:
            if 'high_util' not in self._active_alerts:
                self._active_alerts.add('high_util')
                self._session_metrics['alerts_triggered'] += 1
                self.logger().warning(f"⚠️  HIGH UTILIZATION: {metrics['utilization_pct']:.1f}%")
        else:
            self._active_alerts.discard('high_util')

        # Large loss
        if metrics['total_unrealized_pnl'] < -25000:
            if 'large_loss' not in self._active_alerts:
                self._active_alerts.add('large_loss')
                self._session_metrics['alerts_triggered'] += 1
                self.logger().warning(f"⚠️  LARGE LOSS: ${metrics['total_unrealized_pnl']:,.2f}")
        else:
            self._active_alerts.discard('large_loss')

    def _unwind_position(self, exchange_name, trading_pair, position):
        """Unwind a single position"""
        exchange = self.connectors[exchange_name]

        position_size = abs(float(position.amount))
        if position_size < 0.001:
            return

        self._cancel_orders(exchange_name, trading_pair)

        try:
            mid_price = exchange.get_mid_price(trading_pair)
        except Exception as e:
            self.logger().warning(f"Could not get mid price for {trading_pair}: {e}")
            return

        # Mode-specific parameters
        if self._mode == UnwindingMode.AGGRESSIVE:
            spread_bps = self.aggressive_spread_bps
            order_size_pct = self.aggressive_order_size_pct
            use_market = True
        else:
            spread_bps = self.maker_spread_bps
            order_size_pct = self.maker_order_size_pct
            use_market = False

        order_size = position_size * (order_size_pct / 100)
        order_size = max(order_size, 0.001)

        if float(position.amount) > 0:
            side = "sell"
            order_price = mid_price * (1 + spread_bps / 10000)
        else:
            side = "buy"
            order_price = mid_price * (1 - spread_bps / 10000)

        if use_market:
            self.logger().warning(f"🚨 AGGRESSIVE: {side} MARKET {order_size} {trading_pair}")
        else:
            self.logger().info(f"Placing {side} limit: {order_size} {trading_pair} @ {order_price}")

        try:
            if side == "sell":
                if use_market:
                    self.sell(connector_name=exchange_name, trading_pair=trading_pair,
                              amount=Decimal(str(order_size)), order_type="market")
                else:
                    self.sell(connector_name=exchange_name, trading_pair=trading_pair,
                              amount=Decimal(str(order_size)), order_type="limit",
                              price=Decimal(str(order_price)))
            else:
                if use_market:
                    self.buy(connector_name=exchange_name, trading_pair=trading_pair,
                             amount=Decimal(str(order_size)), order_type="market")
                else:
                    self.buy(connector_name=exchange_name, trading_pair=trading_pair,
                             amount=Decimal(str(order_size)), order_type="limit",
                             price=Decimal(str(order_price)))

            self._session_metrics['orders_placed'] += 1

        except Exception as e:
            self.logger().error(f"Failed to place order: {e}")

    def _cancel_orders(self, exchange_name, trading_pair):
        """Cancel existing orders"""
        try:
            active_orders = self.get_active_orders(exchange_name)
            for order in active_orders:
                if order.trading_pair == trading_pair:
                    self.cancel(exchange_name, order.trading_pair, order.client_order_id)
        except Exception:
            pass

    def _display_dashboard(self):
        """Display monitoring dashboard"""
        if not self._metrics_history:
            return

        metrics = self._metrics_history[-1]

        lines = []
        lines.append("\n" + "=" * 70)
        lines.append(f"🏦 IF MONITOR | {datetime.now().strftime('%H:%M:%S')} | Mode: {self._mode.value.upper()}")
        lines.append("=" * 70)

        # Account overview
        lines.append(f"Balance: ${metrics['balance']:,.2f} | Positions: {metrics['num_positions']} | "
                     f"Util: {metrics['utilization_pct']:.1f}% | PnL: ${metrics['total_unrealized_pnl']:,.2f}")

        # Utilization bar
        util_bars = int(metrics['utilization_pct'] / 2)
        color = "🟢" if metrics['utilization_pct'] < 50 else "🟡" if metrics['utilization_pct'] < 80 else "🔴"
        lines.append(f"{color} {'█' * min(util_bars, 35)}{'░' * (35 - min(util_bars, 35))}")

        # Active positions
        if metrics['positions']:
            lines.append("\nPositions:")
            for symbol, pos in metrics['positions'].items():
                pnl_icon = "🟢" if pos['pnl'] >= 0 else "🔴"
                lines.append(f"  {symbol}: {pos['size']:.2f} @ ${pos['current_price']:.4f} "
                             f"{pnl_icon} ${pos['pnl']:,.2f}")

        # Session stats
        session_hours = (time.time() - self._session_start) / 3600
        lines.append(f"\nSession ({session_hours:.1f}h): Orders: {self._session_metrics['orders_placed']} | "
                     f"Switches: {self._session_metrics['mode_switches']} | "
                     f"Alerts: {self._session_metrics['alerts_triggered']}")

        # Alerts
        if self._active_alerts:
            lines.append(f"\n🚨 ALERTS: {', '.join(self._active_alerts)}")

        lines.append("=" * 70 + "\n")

        self.logger().info("\n".join(lines))

    def _generate_report(self):
        """Generate hourly report"""
        if not self._metrics_history:
            return

        lines = []
        lines.append("\n" + "=" * 70)
        lines.append(f"📊 HOURLY REPORT | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("=" * 70)

        # Calculate stats from history
        if len(self._metrics_history) > 0:
            start_balance = self._metrics_history[0]['balance']
            end_balance = self._metrics_history[-1]['balance']
            avg_util = sum(m['utilization_pct'] for m in self._metrics_history) / len(self._metrics_history)

            lines.append(f"Balance: ${start_balance:,.2f} → ${end_balance:,.2f} ({end_balance - start_balance:+,.2f})")
            lines.append(f"Avg Utilization: {avg_util:.1f}% | Max: {self._session_metrics['max_utilization']:.1f}%")
            lines.append(f"Orders Placed: {self._session_metrics['orders_placed']} | Mode Switches: {self._session_metrics['mode_switches']}")

        lines.append("=" * 70 + "\n")

        self.logger().info("\n".join(lines))

    def on_stop(self):
        """Called when strategy stops"""
        self.logger().info("IF Unwinder with Monitoring stopped")

        # Cancel all orders on all active markets
        for exchange_name in self.active_markets:
            try:
                self.cancel_all_orders(exchange_name)
            except Exception:
                pass

        self._generate_report()

    def format_status(self) -> str:
        """Display strategy status"""
        # Show full status once metrics are available
        if self._metrics_history:
            # Show latest metrics
            metrics = self._metrics_history[-1]
            session_hours = (time.time() - self._session_start) / 3600

            status_parts = [
                f"Mode: {self._mode.value.upper()}",
                f"Balance: ${metrics['balance']:,.0f}",
                f"Util: {metrics['utilization_pct']:.1f}%",
                f"Positions: {metrics['num_positions']}",
                f"PnL: ${metrics['total_unrealized_pnl']:,.0f}",
                f"Orders: {self._session_metrics['orders_placed']}",
                f"Switches: {self._session_metrics['mode_switches']}",
                f"Runtime: {session_hours:.1f}h"
            ]

            if self._active_alerts:
                status_parts.append(f"⚠️ Alerts: {len(self._active_alerts)}")

            return " | ".join(status_parts)

        # Before metrics available, show simple status
        # Wait for first tick to collect metrics before showing detailed info
        session_duration = time.time() - self._session_start
        return (
            f"Mode: {self._mode.value.upper()} | "
            f"Initializing... ({session_duration:.0f}s) | "
            f"Waiting for first metrics collection"
        )
