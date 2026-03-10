"""
Tests for two-price profit target confirmation behavior.
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pnl_monitor import PnLMonitor


class TestProfitTargetConfirmation(unittest.TestCase):
    def test_require_two_confirmation_triggers_on_second(self) -> None:
        config = {"profit_target_pct": 0.20, "require_two_price_confirmation": True}
        monitor = PnLMonitor(config)
        monitor.set_cost_basis(1000.0)
        triggered = []

        def on_met():
            triggered.append(1)

        monitor.set_on_profit_target_met(on_met)
        # First update at 20% profit -> should not trigger
        monitor.update(1200.0)
        self.assertEqual(len(triggered), 0)
        self.assertEqual(monitor.get_confirm_count(), 1)
        # Second consecutive update at 20%+ -> should trigger
        monitor.update(1210.0)
        self.assertEqual(len(triggered), 1)
        self.assertEqual(monitor.get_confirm_count(), 2)

    def test_require_two_reset_on_non_qualifying(self) -> None:
        config = {"profit_target_pct": 0.20, "require_two_price_confirmation": True}
        monitor = PnLMonitor(config)
        monitor.set_cost_basis(1000.0)
        triggered = []

        def on_met():
            triggered.append(1)

        monitor.set_on_profit_target_met(on_met)
        monitor.update(1200.0)  # first confirm
        self.assertEqual(monitor.get_confirm_count(), 1)
        monitor.update(1150.0)  # below target -> reset
        self.assertEqual(monitor.get_confirm_count(), 0)
        monitor.update(1200.0)  # first again
        monitor.update(1200.0)  # second -> trigger
        self.assertEqual(len(triggered), 1)

    def test_single_price_triggers_immediately(self) -> None:
        config = {"profit_target_pct": 0.20, "require_two_price_confirmation": False}
        monitor = PnLMonitor(config)
        monitor.set_cost_basis(1000.0)
        triggered = []

        def on_met():
            triggered.append(1)

        monitor.set_on_profit_target_met(on_met)
        monitor.update(1200.0)
        self.assertEqual(len(triggered), 1)


if __name__ == "__main__":
    unittest.main()
