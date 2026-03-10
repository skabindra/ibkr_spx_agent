"""
Centralized logging for the IBKR SPX paper-trading agent.
Logs to both file and console with configurable levels.
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str = "ibkr_spx_agent",
    log_dir: Optional[Path] = None,
    log_level: int = logging.INFO,
    console_level: Optional[int] = None,
) -> logging.Logger:
    """
    Configure and return the application logger.
    Writes to file (if log_dir provided) and console.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(log_level)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(console_level or log_level)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # File handler (optional)
    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "ibkr_spx_agent.log", encoding="utf-8")
        fh.setLevel(log_level)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return the application logger (after setup_logger has been called)."""
    return logging.getLogger(name or "ibkr_spx_agent")
