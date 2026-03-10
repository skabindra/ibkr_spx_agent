"""
Persistent state store for restart-safe operation.
Stores trading day status, entry/exit attempts, position details, and profit-target confirmation.
Uses JSON by default; can be extended for SQLite.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils import PROJECT_ROOT


@dataclass
class LegState:
    """State for a single leg (contract key, order id, fill price, etc.)."""

    leg_id: str
    con_id: Optional[int] = None
    order_id: Optional[int] = None
    fill_price: Optional[float] = None
    fill_time: Optional[str] = None
    status: str = "pending"


@dataclass
class PositionState:
    """Active position details for recovery after restart."""

    trading_date: str
    entry_fill_time: Optional[str] = None
    legs: List[Dict[str, Any]] = field(default_factory=list)
    entry_order_ids: List[int] = field(default_factory=list)
    cost_basis: Optional[float] = None
    quantity: int = 1


@dataclass
class DayState:
    """State for a single trading day."""

    date: str
    entry_attempted: bool = False
    entry_filled: bool = False
    position: Optional[Dict[str, Any]] = None  # PositionState as dict
    profit_target_first_confirmation: bool = False
    profit_target_confirmed_count: int = 0
    exit_sent: bool = False
    exit_filled: bool = False
    exit_time: Optional[str] = None
    skip_reason: Optional[str] = None  # e.g. blackout


@dataclass
class AgentState:
    """Full agent state for persistence."""

    current_trading_date: Optional[str] = None
    days: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # date -> DayState as dict
    kill_switch: bool = False
    last_updated: Optional[str] = None

    def get_day(self, date: str) -> DayState:
        d = self.days.get(date)
        if d is None:
            return DayState(date=date)
        return DayState(
            date=d.get("date", date),
            entry_attempted=d.get("entry_attempted", False),
            entry_filled=d.get("entry_filled", False),
            position=d.get("position"),
            profit_target_first_confirmation=d.get("profit_target_first_confirmation", False),
            profit_target_confirmed_count=d.get("profit_target_confirmed_count", 0),
            exit_sent=d.get("exit_sent", False),
            exit_filled=d.get("exit_filled", False),
            exit_time=d.get("exit_time"),
            skip_reason=d.get("skip_reason"),
        )

    def set_day(self, date: str, day: DayState) -> None:
        self.days[date] = asdict(day)


class StateStore:
    """JSON file-based state persistence."""

    def __init__(self, state_path: Optional[Path] = None):
        self._path = state_path or (PROJECT_ROOT / "state.json")
        self._state: Optional[AgentState] = None

    def load(self) -> AgentState:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._state = AgentState(
                    current_trading_date=data.get("current_trading_date"),
                    days=data.get("days", {}),
                    kill_switch=data.get("kill_switch", False),
                    last_updated=data.get("last_updated"),
                )
            except (json.JSONDecodeError, TypeError) as e:
                self._state = AgentState()
        else:
            self._state = AgentState()
        return self._state

    def save(self, state: Optional[AgentState] = None) -> None:
        from datetime import datetime, timezone

        s = state or self._state
        if s is None:
            s = self.load()
        s.last_updated = datetime.now(timezone.utc).isoformat()
        data = {
            "current_trading_date": s.current_trading_date,
            "days": s.days,
            "kill_switch": s.kill_switch,
            "last_updated": s.last_updated,
        }
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get_state(self) -> AgentState:
        if self._state is None:
            self.load()
        return self._state  # type: ignore
