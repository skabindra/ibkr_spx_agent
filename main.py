"""
IBKR SPX Paper-Trading Agent — main entry point.
Connects to IBKR paper trading, runs the strategy loop (entry/exit windows, PnL monitoring),
handles reconnects and persistence. Paper-trading only unless safety override is set.
"""

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from logger import setup_logger
from utils import load_config, PROJECT_ROOT

# Parse CLI
DRY_RUN = os.getenv("DRY_RUN", "0").lower() in ("1", "true", "yes")
MOCK = os.getenv("MOCK", "0").lower() in ("1", "true", "yes")


def main() -> None:
    config = load_config()
    log_dir = config.get("log_dir")
    log_dir = Path(log_dir) if log_dir else PROJECT_ROOT / "logs"
    logger = setup_logger(
        log_dir=log_dir,
        log_level=config.get("log_level", 20),
    )
    logger.info("Starting IBKR SPX paper-trading agent (dry_run=%s, mock=%s)", DRY_RUN, MOCK)

    # Paper-trading safety
    allow_live = os.getenv("IBKR_ALLOW_LIVE", "false").lower() == "true"
    if allow_live:
        logger.warning("IBKR_ALLOW_LIVE is true; ensure you intend to connect to LIVE account")
    else:
        logger.info("Paper-trading only (IBKR_ALLOW_LIVE=false)")

    from ibkr_client import IBKRClient
    from state_store import StateStore
    from strategy_engine import StrategyEngine
    from risk_manager import RiskManager

    state_store = StateStore()
    state_store.load()

    ib_client = IBKRClient(allow_live=allow_live)
    ib_client.set_logger(logger)

    risk = RiskManager(config, state_store)
    risk.set_allow_live(allow_live)
    risk.set_logger(logger)

    engine = StrategyEngine(
        config=config,
        ib_client=ib_client if not MOCK else None,
        state_store=state_store,
        dry_run=DRY_RUN,
        mock=MOCK,
    )
    engine.set_logger(logger)

    if risk.is_kill_switch_active():
        logger.warning("Kill switch is active; no trading until disabled in state")

    # Connect to IB unless mock
    if not MOCK:
        if not ib_client.connect():
            logger.error("Failed to connect to IBKR; exiting")
            sys.exit(1)
        # Log account details so you can verify you are on the right (paper) account
        port = ib_client.port
        account_type = "PAPER" if port == 4002 else ("LIVE" if port == 4001 else "custom")
        logger.info("Session: port=%s (%s trading)", port, account_type)
        configured_account = os.getenv("IBKR_ACCOUNT", "").strip()
        session_accounts = ib_client.get_session_accounts()
        if configured_account:
            logger.info("Configured account (IBKR_ACCOUNT): %s — orders will be sent to this account", configured_account)
        else:
            if session_accounts:
                logger.info("Configured account (IBKR_ACCOUNT): not set — orders will use this session's account: %s (your %s account)",
                            session_accounts[0], account_type.lower())
            else:
                logger.info("Configured account (IBKR_ACCOUNT): not set — orders will use broker default for this %s session", account_type.lower())
        if session_accounts:
            logger.info("Broker session account(s) for this connection: %s", session_accounts)
            # If no IBKR_ACCOUNT set, use this session's (paper) account so orders go there explicitly
            if not os.getenv("IBKR_ACCOUNT", "").strip():
                ib_client.account = session_accounts[0]
                logger.info("Using session account for orders: %s", session_accounts[0])
        # Log current positions on this account
        display_account = configured_account or (session_accounts[0] if session_accounts else "")
        positions = ib_client.get_positions()
        logger.info("Positions for account %s:", display_account or "(default)")
        if positions:
            logger.info("  %d position(s):", len(positions))
            for p in positions:
                logger.info("    position=%s avgCost=%s contract=%s", p.get("position"), p.get("avgCost"), p.get("contract", "").strip() or "(n/a)")
        else:
            logger.info("  (none)")
    else:
        logger.info("MOCK mode: no broker connection")

    poll_interval = config.get("pnl_poll_interval_seconds", 30)
    _entry = os.getenv("ENTRY_TIME", "").strip() or config.get("entry_time", "09:45")
    _offset = config.get("entry_offset_minutes", 2)
    _tz = config.get("timezone", "America/Chicago")
    logger.info("Agent running. Polling every %ds for entry window %s ± %d min (%s). You will see 'Entry check: market time ...' each cycle. Stop with Ctrl+C.",
                poll_interval, _entry, _offset, _tz)
    reconnect_interval = 60
    last_reconnect = 0.0

    try:
        while True:
            now = time.time()
            if not MOCK and not ib_client.is_connected():
                if now - last_reconnect >= reconnect_interval:
                    logger.warning("Disconnected; attempting reconnect")
                    if ib_client.reconnect():
                        last_reconnect = now
                    else:
                        logger.error("Reconnect failed; sleeping 60s")
                        time.sleep(60)
                        continue
                else:
                    time.sleep(5)
                    continue

            # Entry checks (Friday, entry window, blackout, risk)
            engine.run_entry_checks()

            # Exit checks (scheduled exit window)
            engine.run_exit_checks()

            # PnL monitoring for open position (profit target)
            from scheduler import current_market_time
            state = state_store.get_state()
            today = current_market_time(config).date().isoformat()
            day = state.get_day(today)
            if day.entry_filled and not day.exit_sent and day.position and day.position.get("cost_basis"):
                # Get current position value (mock or from broker)
                if MOCK or DRY_RUN:
                    current_value = day.position.get("cost_basis", 0) * 1.25  # mock 25% up
                elif ib_client.is_connected():
                    # Simplified: use cost_basis as placeholder; real impl would sum leg marks
                    current_value = day.position.get("cost_basis", 0) * 1.0
                    try:
                        nl = ib_client.net_liquidation()
                        if nl:
                            # Approximate: use portfolio change or request position mark
                            current_value = day.position.get("cost_basis", 0)  # TODO: request combo mark
                    except Exception:
                        pass
                else:
                    current_value = day.position.get("cost_basis", 0)
                engine.run_pnl_check(current_value)

            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        if not MOCK and ib_client.is_connected():
            ib_client.disconnect()
        logger.info("Agent stopped")


if __name__ == "__main__":
    main()
