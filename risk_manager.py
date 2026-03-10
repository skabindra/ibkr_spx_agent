"""
Risk controls: paper-trading-only guard, max one entry per day, max open positions,
kill switch, and placeholder for max daily loss. Prevents duplicate entries and conflicting positions.
"""

from typing import Any, Optional, Tuple

from state_store import AgentState, StateStore


class RiskManager:
    def __init__(self, config: dict, state_store: StateStore):
        self.config = config
        self.state_store = state_store
        self._allow_live = False  # Set by main from env; never True for paper bot
        self._logger: Optional[Any] = None

    def set_allow_live(self, allow: bool) -> None:
        self._allow_live = allow

    def set_logger(self, logger: Any) -> None:
        self._logger = logger

    def _log(self, msg: str, *args: Any) -> None:
        if self._logger:
            self._logger.info(msg, *args)

    def is_live_allowed(self) -> bool:
        return self._allow_live

    def is_paper_only_ok(self, port: int) -> bool:
        """Return False if port is live (4001) and live is not allowed."""
        if port == 4001 and not self._allow_live:
            return False
        return True

    def is_kill_switch_active(self) -> bool:
        state = self.state_store.get_state()
        return state.kill_switch

    def set_kill_switch(self, active: bool) -> None:
        state = self.state_store.get_state()
        state.kill_switch = active
        self.state_store.save(state)

    def can_enter_today(self, date_str: str) -> Tuple[bool, Optional[str]]:
        """
        Returns (allowed, reason_if_not).
        Checks: kill switch, already attempted, already filled, max open positions.
        """
        if self.is_kill_switch_active():
            return False, "Kill switch is active"

        state = self.state_store.get_state()
        day = state.get_day(date_str)

        if day.entry_attempted:
            return False, "Entry already attempted for this day"
        if day.entry_filled and not day.exit_filled:
            return False, "Position already open for this day"

        max_open = self.config.get("max_open_positions", 1)
        open_count = sum(
            1
            for d in state.days.values()
            if d.get("entry_filled") and not d.get("exit_filled")
        )
        if open_count >= max_open:
            return False, f"Max open positions ({max_open}) reached"

        return True, None

    def can_exit_today(self, date_str: str) -> Tuple[bool, Optional[str]]:
        """Returns (allowed, reason_if_not). Exit only if we have an open position and have not already sent exit."""
        if self.is_kill_switch_active():
            return False, "Kill switch is active"

        state = self.state_store.get_state()
        day = state.get_day(date_str)

        if not day.entry_filled:
            return False, "No entry filled for this day"
        if day.exit_sent:
            return False, "Exit already sent for this day"
        return True, None
