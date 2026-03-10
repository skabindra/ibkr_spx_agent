"""
Tests for entry/exit time window validation with 1-minute and 2-minute offsets.
"""

import unittest
from datetime import datetime
import zoneinfo

# Import scheduler logic (avoid full config load in test)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scheduler import in_time_window, get_market_tz
from utils import parse_time_to_minutes


class TestTimeWindow(unittest.TestCase):
    def setUp(self) -> None:
        self.tz = zoneinfo.ZoneInfo("America/New_York")

    def test_parse_time(self) -> None:
        self.assertEqual(parse_time_to_minutes("09:45"), 9 * 60 + 45)
        self.assertEqual(parse_time_to_minutes("00:00"), 0)
        self.assertEqual(parse_time_to_minutes("23:59"), 23 * 60 + 59)

    def test_in_time_window_2_minute_offset(self) -> None:
        # 9:45 target, +/- 2 min => 9:43 to 9:47
        target = "09:45"
        offset = 2
        # Inside
        for minute in (43, 44, 45, 46, 47):
            t = datetime(2024, 3, 15, 9, minute, 0, tzinfo=self.tz)
            self.assertTrue(in_time_window(t, target, offset, tz=self.tz),
                            f"9:{minute:02d} should be in window")
        # Outside
        for minute in (42, 48):
            t = datetime(2024, 3, 15, 9, minute, 0, tzinfo=self.tz)
            self.assertFalse(in_time_window(t, target, offset, tz=self.tz),
                             f"9:{minute:02d} should be out of window")

    def test_in_time_window_1_minute_offset(self) -> None:
        # 9:45 target, +/- 1 min => 9:44 to 9:46
        target = "09:45"
        offset = 1
        t_44 = datetime(2024, 3, 15, 9, 44, 0, tzinfo=self.tz)
        t_47 = datetime(2024, 3, 15, 9, 47, 0, tzinfo=self.tz)
        self.assertTrue(in_time_window(t_44, target, offset, tz=self.tz))
        self.assertFalse(in_time_window(t_47, target, offset, tz=self.tz))


if __name__ == "__main__":
    unittest.main()
