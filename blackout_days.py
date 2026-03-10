"""
Blackout day logic: skip trading on configured dates.
Supports manual blackout list; structure allows future macro-event blackout support.
"""

from datetime import date
from typing import Optional, Set

from utils import load_config


def parse_blackout_dates(config: dict) -> Set[date]:
    """Parse blackout_dates from config (YYYY-MM-DD strings) into set of date objects."""
    raw = config.get("blackout_dates") or []
    out: Set[date] = set()
    for s in raw:
        if isinstance(s, str):
            try:
                out.add(date.fromisoformat(s.strip()))
            except ValueError:
                pass
    return out


def is_blackout(trade_date: date, config: Optional[dict] = None) -> bool:
    """
    Return True if trade_date is a blackout day (trading should be skipped).
    Uses manual blackout list from config. Future: add macro-event calendar here.
    """
    if not config:
        config = load_config()
    if not config.get("use_blackout_days", True):
        return False
    blackout = parse_blackout_dates(config)
    return trade_date in blackout
