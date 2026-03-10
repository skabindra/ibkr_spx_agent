"""
Shared utilities: config loading, timezone helpers, and constants.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv

# Load .env from project root if present
load_dotenv()

# Default paths
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load YAML config; override path via CONFIG_PATH env or argument."""
    path = config_path or Path(os.getenv("CONFIG_PATH", DEFAULT_CONFIG_PATH))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get environment variable."""
    return os.getenv(key, default)


def parse_time_to_minutes(time_str: str) -> int:
    """Convert 'HH:MM' or 'H:MM' to minutes since midnight."""
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {time_str}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Invalid time: {time_str}")
    return h * 60 + m


def weekday_name_to_number(name: str) -> int:
    """Monday=0, Friday=4. Case-insensitive."""
    names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    lower = name.strip().lower()
    for i, n in enumerate(names):
        if n.startswith(lower) or lower == n:
            return i
    raise ValueError(f"Unknown weekday: {name}")
