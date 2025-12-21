"""
Insurance Fund Monitor

Real-time monitoring and reporting for Insurance Fund health and activity.

Tracks:
- IF balance and utilization
- Active positions and unrealized PnL
- Unwinding progress
- Mode switches and risk events
- Performance metrics

Generates:
- Console dashboard (updated every 10s)
- Detailed logs
- Hourly summary reports
- Alerts for critical conditions
"""
import time
from datetime import datetime
from typing import Dict

from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class IFMonitor(ScriptStrategyBase):
    """
    Insurance Fund monitoring dashboard and alerting system.

    Displays real-time IF metrics and tracks performance over time.
    """

    # Configuration
    refresh_interval = 10  # Update dashboard every 10 seconds
    alert_utilization_threshold = 70  # Alert if utilization > 70%
    alert_loss_threshold = 25000  # Alert if loss > $25K
    report_interval = 3600  # Generate report every hour

    markets = {}

    def __init__(self, connectors):
        super().__init__(connectors)
        self._last_update = 0
        self._last_report = 0
        self._session_start = time.time()

        # Historical tracking
        self._history = {
            'balance': [],
            'utilization': [],
            'unrealized_pnl': [],
            'positions': [],
            'events': []
        }

        # Session metrics
        self._session_metrics = {
            'positions_accepted': 0,
            'positions_unwound': 0,
            'total_pnl_realized': 0,
            'max_utilization': 0,
            'max_loss': 0,
            'mode_switches': 0,
            'alerts_triggered': 0
        }

        # Alert state
        self._active_alerts = set()

    def on_tick(self):
        """Called every second"""
        current_time = self.current_timestamp

        # Update dashboard
        if current_time - self._last_update >= self.refresh_interval:
            self._last_update = current_time
            self._update_dashboard()

        # Generate hourly report
        if current_time - self._last_report >= self.report_interval:
            self._last_report = current_time
            self._generate_report()

    def _update_dashboard(self):
        """Update monitoring dashboard"""
        for exchange_name in self.active_markets:
            try:
                exchange = self.connectors[exchange_name]

                # Collect metrics
                metrics = self._collect_metrics(exchange_name, exchange)

                # Store history
                self._store_metrics(metrics)

                # Check alerts
                self._check_alerts(metrics)

                # Display dashboard
                self._display_dashboard(exchange_name, metrics)

            except Exception as e:
                self.logger().error(f"Error updating dashboard: {e}")

    def _collect_metrics(self, exchange_name, exchange) -> Dict:
        """Collect current IF metrics"""
        metrics = {
            'timestamp': datetime.now(),
            'balance': 0,
            'positions': {},
            'total_position_value': 0,
            'total_unrealized_pnl': 0,
            'utilization_pct': 0,
            'num_positions': 0
        }

        try:
            # Get balance
            balance = exchange.get_balance("USDT")
            metrics['balance'] = float(balance)

            # Get positions
            if hasattr(exchange, 'account_positions'):
                positions = exchange.account_positions

                if positions:
                    for trading_pair, position in positions.items():
                        try:
                            mid_price = exchange.get_mid_price(trading_pair)
                            position_size = float(position.amount)
                            entry_price = float(position.entry_price) if hasattr(position, 'entry_price') else mid_price

                            # Position value
                            position_value = abs(position_size * mid_price)

                            # Unrealized PnL
                            unrealized_pnl = (mid_price - entry_price) * position_size

                            metrics['positions'][trading_pair] = {
                                'size': position_size,
                                'entry_price': entry_price,
                                'current_price': mid_price,
                                'position_value': position_value,
                                'unrealized_pnl': unrealized_pnl,
                                'pnl_pct': ((mid_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
                            }

                            metrics['total_position_value'] += position_value
                            metrics['total_unrealized_pnl'] += unrealized_pnl

                        except Exception as e:
                            self.logger().warning(f"Error processing {trading_pair}: {e}")

                    metrics['num_positions'] = len(positions)

            # Calculate utilization
            if metrics['balance'] > 0:
                metrics['utilization_pct'] = (metrics['total_position_value'] / metrics['balance']) * 100

            # Update session max metrics
            if metrics['utilization_pct'] > self._session_metrics['max_utilization']:
                self._session_metrics['max_utilization'] = metrics['utilization_pct']

            if metrics['total_unrealized_pnl'] < self._session_metrics['max_loss']:
                self._session_metrics['max_loss'] = metrics['total_unrealized_pnl']

        except Exception as e:
            self.logger().error(f"Error collecting metrics: {e}")

        return metrics

    def _store_metrics(self, metrics: Dict):
        """Store metrics in history"""
        self._history['balance'].append((metrics['timestamp'], metrics['balance']))
        self._history['utilization'].append((metrics['timestamp'], metrics['utilization_pct']))
        self._history['unrealized_pnl'].append((metrics['timestamp'], metrics['total_unrealized_pnl']))
        self._history['positions'].append((metrics['timestamp'], metrics['num_positions']))

        # Keep only last hour of data
        cutoff_time = datetime.now().timestamp() - 3600
        for key in ['balance', 'utilization', 'unrealized_pnl', 'positions']:
            self._history[key] = [
                (ts, val) for ts, val in self._history[key]
                if ts.timestamp() > cutoff_time
            ]

    def _check_alerts(self, metrics: Dict):
        """Check for alert conditions"""
        alerts_triggered = []

        # High utilization alert
        if metrics['utilization_pct'] > self.alert_utilization_threshold:
            alert_key = 'high_utilization'
            if alert_key not in self._active_alerts:
                self._active_alerts.add(alert_key)
                alerts_triggered.append(f"⚠️  HIGH UTILIZATION: {metrics['utilization_pct']:.1f}%")
                self._session_metrics['alerts_triggered'] += 1
        else:
            self._active_alerts.discard('high_utilization')

        # Large loss alert
        if metrics['total_unrealized_pnl'] < -self.alert_loss_threshold:
            alert_key = 'large_loss'
            if alert_key not in self._active_alerts:
                self._active_alerts.add(alert_key)
                alerts_triggered.append(
                    f"⚠️  LARGE UNREALIZED LOSS: ${metrics['total_unrealized_pnl']:,.2f}"
                )
                self._session_metrics['alerts_triggered'] += 1
        else:
            self._active_alerts.discard('large_loss')

        # Log alerts
        for alert in alerts_triggered:
            self.logger().warning(alert)
            self._history['events'].append((metrics['timestamp'], alert))

    def _display_dashboard(self, exchange_name: str, metrics: Dict):
        """Display monitoring dashboard"""
        lines = []

        # Header
        lines.append("\n" + "═" * 80)
        lines.append("█" * 80)
        lines.append(f"█  INSURANCE FUND MONITOR - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("█" * 80)
        lines.append("═" * 80)

        # Account Overview
        lines.append(f"\n🏦 ACCOUNT OVERVIEW ({exchange_name})")
        lines.append("─" * 80)
        lines.append(f"  Balance:           ${metrics['balance']:,.2f} USDT")
        lines.append(f"  Position Value:    ${metrics['total_position_value']:,.2f}")
        lines.append(f"  Utilization:       {metrics['utilization_pct']:.1f}%")

        # Utilization bar
        util_bars = int(metrics['utilization_pct'] / 2)  # 50 chars = 100%
        util_color = "🟢" if metrics['utilization_pct'] < 50 else "🟡" if metrics['utilization_pct'] < 80 else "🔴"
        lines.append(f"  {util_color} {'█' * util_bars}{'░' * (50 - util_bars)} {metrics['utilization_pct']:.1f}%")

        lines.append(f"  Unrealized PnL:    ${metrics['total_unrealized_pnl']:,.2f}")
        lines.append(f"  Active Positions:  {metrics['num_positions']}")

        # Active Positions
        if metrics['positions']:
            lines.append(f"\n📊 ACTIVE POSITIONS ({len(metrics['positions'])})")
            lines.append("─" * 80)
            lines.append(f"  {'Symbol':<15} {'Size':>12} {'Entry':>10} {'Current':>10} {'Value':>12} {'PnL':>12} {'%':>8}")
            lines.append("  " + "─" * 78)

            for symbol, pos in sorted(metrics['positions'].items()):
                pnl_indicator = "🟢" if pos['unrealized_pnl'] >= 0 else "🔴"
                lines.append(
                    f"  {symbol:<15} "
                    f"{pos['size']:>12.2f} "
                    f"${pos['entry_price']:>9.4f} "
                    f"${pos['current_price']:>9.4f} "
                    f"${pos['position_value']:>11,.2f} "
                    f"{pnl_indicator}${pos['unrealized_pnl']:>10,.2f} "
                    f"{pos['pnl_pct']:>7.2f}%"
                )

        # Session Statistics
        session_duration = time.time() - self._session_start
        session_hours = session_duration / 3600

        lines.append(f"\n📈 SESSION STATS (Running: {session_hours:.1f}h)")
        lines.append("─" * 80)
        lines.append(f"  Positions Accepted:    {self._session_metrics['positions_accepted']}")
        lines.append(f"  Positions Unwound:     {self._session_metrics['positions_unwound']}")
        lines.append(f"  Realized PnL:          ${self._session_metrics['total_pnl_realized']:,.2f}")
        lines.append(f"  Max Utilization:       {self._session_metrics['max_utilization']:.1f}%")
        lines.append(f"  Max Unrealized Loss:   ${self._session_metrics['max_loss']:,.2f}")
        lines.append(f"  Mode Switches:         {self._session_metrics['mode_switches']}")
        lines.append(f"  Alerts Triggered:      {self._session_metrics['alerts_triggered']}")

        # Active Alerts
        if self._active_alerts:
            lines.append(f"\n🚨 ACTIVE ALERTS ({len(self._active_alerts)})")
            lines.append("─" * 80)
            for alert in self._active_alerts:
                lines.append(f"  {alert.upper()}")

        # Recent Events (last 5)
        if self._history['events']:
            recent_events = self._history['events'][-5:]
            lines.append(f"\n📝 RECENT EVENTS (Last {len(recent_events)})")
            lines.append("─" * 80)
            for ts, event in recent_events:
                lines.append(f"  [{ts.strftime('%H:%M:%S')}] {event}")

        # Footer
        lines.append("\n" + "═" * 80)
        lines.append(f"Next update in {self.refresh_interval} seconds | Report in {int(self.report_interval - (self.current_timestamp - self._last_report))}s")
        lines.append("═" * 80 + "\n")

        # Print dashboard
        dashboard = "\n".join(lines)
        self.logger().info(dashboard)

    def _generate_report(self):
        """Generate hourly summary report"""
        try:
            report_time = datetime.now()

            lines = []
            lines.append("\n" + "=" * 80)
            lines.append(f"INSURANCE FUND HOURLY REPORT - {report_time.strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("=" * 80)

            # Calculate hourly stats from history
            if self._history['balance']:
                start_balance = self._history['balance'][0][1]
                end_balance = self._history['balance'][-1][1]
                balance_change = end_balance - start_balance

                lines.append(f"\nBalance Change: ${start_balance:,.2f} → ${end_balance:,.2f} ({balance_change:+,.2f})")

            if self._history['utilization']:
                avg_util = sum(u for _, u in self._history['utilization']) / len(self._history['utilization'])
                max_util = max(u for _, u in self._history['utilization'])
                lines.append(f"Utilization: Avg {avg_util:.1f}% | Max {max_util:.1f}%")

            if self._history['unrealized_pnl']:
                pnl_values = [p for _, p in self._history['unrealized_pnl']]
                avg_pnl = sum(pnl_values) / len(pnl_values)
                min_pnl = min(pnl_values)
                max_pnl = max(pnl_values)
                lines.append(f"Unrealized PnL: Avg ${avg_pnl:,.2f} | Min ${min_pnl:,.2f} | Max ${max_pnl:,.2f}")

            # Session metrics
            lines.append("\nSession Metrics:")
            lines.append(f"  Positions Handled: {self._session_metrics['positions_accepted']} accepted, {self._session_metrics['positions_unwound']} unwound")
            lines.append(f"  Realized PnL: ${self._session_metrics['total_pnl_realized']:,.2f}")
            lines.append(f"  Alerts: {self._session_metrics['alerts_triggered']} triggered")

            lines.append("=" * 80 + "\n")

            report = "\n".join(lines)
            self.logger().info(report)

            # Log event
            self._history['events'].append((report_time, "Hourly report generated"))

        except Exception as e:
            self.logger().error(f"Error generating report: {e}")

    def on_stop(self):
        """Called when strategy stops"""
        self.logger().info("Insurance Fund Monitor stopped")

        # Generate final report
        self._generate_report()

    def format_status(self) -> str:
        """Display strategy status"""
        return f"IF Monitor running. Check logs for dashboard updates. Active alerts: {len(self._active_alerts)}"
