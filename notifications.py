"""
Optional notifications when a trade is placed or filled.
Set NOTIFY_ON_TRADE=1 to enable desktop notifications (macOS/Linux).
"""

import os
import subprocess
import sys
from typing import Optional


def notify_trade_placed(dry_run: bool = False, details: str = "") -> None:
    """Send a visible notification that an order was placed (or simulated)."""
    if dry_run:
        title = "IBKR SPX Agent (dry-run)"
        body = "Simulated order placed at 9:20 AM." + (" " + details if details else "")
    else:
        title = "IBKR SPX Agent"
        body = "Order placed." + (" " + details if details else "")
    _desktop_notify(title, body)


def notify_trade_filled(dry_run: bool = False, details: str = "") -> None:
    """Send a visible notification that the order was filled (or simulated)."""
    if dry_run:
        title = "IBKR SPX Agent (dry-run)"
        body = "Simulated fill recorded." + (" " + details if details else "")
    else:
        title = "IBKR SPX Agent"
        body = "Order filled." + (" " + details if details else "")
    _desktop_notify(title, body)


def _desktop_notify(title: str, body: str) -> None:
    if os.getenv("NOTIFY_ON_TRADE", "").strip().lower() not in ("1", "true", "yes"):
        return
    try:
        if sys.platform == "darwin":
            subprocess.run(
                [
                    "osascript", "-e",
                    f'display notification "{body}" with title "{title}"',
                ],
                check=False,
                timeout=5,
                capture_output=True,
            )
        elif sys.platform == "linux":
            subprocess.run(
                ["notify-send", title, body],
                check=False,
                timeout=5,
                capture_output=True,
            )
    except Exception:
        pass
