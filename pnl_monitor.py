"""
P&L monitoring: poll position value, compute return %, and apply profit-target logic.
Supports two-price confirmation: require two consecutive polls where target is satisfied before exit.
"""

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from utils import load_config


class PnLMonitor:
    """
    Monitors strategy P&L after fill. Computes (current_value - cost_basis) / cost_basis.
    When profit_target_pct is reached and (if required) two consecutive confirmations, triggers exit.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.profit_target_pct = self.config.get("profit_target_pct", 0.20)
        self.require_two = self.config.get("require_two_price_confirmation", True)
        self._confirm_count = 0
        self._cost_basis: Optional[float] = None
        self._on_profit_target_met: Optional[Callable[[], None]] = None
        self._logger: Optional[Any] = None

    def set_logger(self, logger: Any) -> None:
        self._logger = logger

    def set_cost_basis(self, cost: float) -> None:
        self._cost_basis = cost
        self._confirm_count = 0

    def set_on_profit_target_met(self, callback: Callable[[], None]) -> None:
        self._on_profit_target_met = callback

    def _log(self, msg: str, *args: Any) -> None:
        if self._logger:
            self._logger.info(msg, *args)

    def update(self, current_value: float) -> bool:
        """
        Update with current position value (e.g. from broker mark or sum of leg prices).
        Returns True if exit was triggered (two-price confirmed if required).
        """
        if self._cost_basis is None or self._cost_basis <= 0:
            return False

        pnl_pct = (current_value - self._cost_basis) / self._cost_basis
        target_met = pnl_pct >= self.profit_target_pct

        if target_met:
            self._confirm_count += 1
            self._log(
                "Profit target check: met (confirm_count=%d, require_two=%s)",
                self._confirm_count,
                self.require_two,
            )
            if self.require_two:
                if self._confirm_count >= 2:
                    self._log("Profit target confirmed by two consecutive prices; triggering exit")
                    if self._on_profit_target_met:
                        self._on_profit_target_met()
                    return True
            else:
                if self._confirm_count >= 1:
                    self._log("Profit target met; triggering exit")
                    if self._on_profit_target_met:
                        self._on_profit_target_met()
                    return True
        else:
            if self._confirm_count > 0:
                self._log("Profit target no longer met; resetting confirm_count from %d", self._confirm_count)
            self._confirm_count = 0

        return False

    def get_confirm_count(self) -> int:
        return self._confirm_count

    def reset_confirmation(self) -> None:
        self._confirm_count = 0
