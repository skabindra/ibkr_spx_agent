"""
Time-based scheduling: entry/exit windows with configurable target time and offset.
Timezone-aware; triggers only on configured trade day (e.g. Friday).
"""

from datetime import date, datetime, time, timedelta
from typing import Optional, Tuple
import zoneinfo

from utils import load_config, parse_time_to_minutes, weekday_name_to_number


def get_market_tz(config: Optional[dict] = None):
    tz_name = (config or load_config()).get("timezone", "America/New_York")
    try:
        return zoneinfo.ZoneInfo(tz_name)
    except Exception:
        return zoneinfo.ZoneInfo("America/New_York")


def in_time_window(
    now: datetime,
    target_time_str: str,
    offset_minutes: int,
    tz: Optional[zoneinfo.ZoneInfo] = None,
    config: Optional[dict] = None,
) -> bool:
    """
    Return True if `now` is within [target - offset, target + offset] minutes of midnight.
    now should be timezone-aware in the market timezone.
    """
    if tz is None:
        tz = get_market_tz(config)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    target_mins = parse_time_to_minutes(target_time_str)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    target_dt = day_start + timedelta(minutes=target_mins)
    low = target_dt - timedelta(minutes=offset_minutes)
    high = target_dt + timedelta(minutes=offset_minutes)
    return low <= now <= high


def is_trade_day(day: date, config: Optional[dict] = None) -> bool:
    """Return True if day is the configured trade day (e.g. Friday)."""
    cfg = config or load_config()
    name = cfg.get("trade_day", "Friday")
    want = weekday_name_to_number(name)
    return day.weekday() == want


def next_trade_date(on_or_after: date, config: Optional[dict] = None) -> Optional[date]:
    """Next date that is a trade day on or after on_or_after."""
    d = on_or_after
    for _ in range(8):
        if is_trade_day(d, config):
            return d
        d += timedelta(days=1)
    return None


def current_market_time(config: Optional[dict] = None) -> datetime:
    """Current time in market timezone."""
    tz = get_market_tz(config)
    return datetime.now(tz)


def in_entry_window(config: Optional[dict] = None) -> bool:
    now = current_market_time(config)
    cfg = config or load_config()
    return in_time_window(
        now,
        cfg.get("entry_time", "09:45"),
        cfg.get("entry_offset_minutes", 2),
        config=cfg,
    )


def in_exit_window(config: Optional[dict] = None) -> bool:
    now = current_market_time(config)
    cfg = config or load_config()
    return in_time_window(
        now,
        cfg.get("exit_time", "09:45"),
        cfg.get("exit_offset_minutes", 2),
        config=cfg,
    )
