"""
Orchestrates the SPX 4-leg strategy: entry on eligible Fridays within time window,
position monitoring, profit-target and scheduled exit. Uses config, state, risk, and broker.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from blackout_days import is_blackout
from contract_selector import ChainContract, ContractSelector, OptionSpec, get_expiration_near_dte
from ibkr_client import IBKRClient
from order_manager import OrderManager
from pnl_monitor import PnLMonitor
from risk_manager import RiskManager
from scheduler import current_market_time, in_entry_window, in_exit_window, is_trade_day
from state_store import DayState, PositionState, StateStore
from utils import load_config


class StrategyEngine:
    def __init__(
        self,
        config: Optional[dict] = None,
        ib_client: Optional[IBKRClient] = None,
        state_store: Optional[StateStore] = None,
        dry_run: bool = False,
        mock: bool = False,
        strategy_name: str = "SPX-DC",
    ):
        self.config = config or load_config()
        self.ib_client = ib_client
        self.state_store = state_store or StateStore()
        self.dry_run = dry_run
        self.mock = mock
        self.strategy_name = (strategy_name or self.config.get("default_strategy") or "SPX-DC").strip().upper()

        self.risk = RiskManager(self.config, self.state_store)
        self.selector = ContractSelector(self.config)
        self.pnl_monitor = PnLMonitor(self.config)
        self._order_manager: Optional[OrderManager] = None
        self._logger: Optional[Any] = None

    def set_logger(self, logger: Any) -> None:
        self._logger = logger
        self.risk.set_logger(logger)
        self.pnl_monitor.set_logger(logger)
        if self._order_manager:
            self._order_manager.set_logger(logger)
        if self.ib_client:
            self.ib_client.set_logger(logger)

    def _log(self, msg: str, *args: Any) -> None:
        if self._logger:
            self._logger.info(msg, *args)

    def _ensure_order_manager(self) -> OrderManager:
        if self._order_manager is None and self.ib_client:
            self._order_manager = OrderManager(
                self.ib_client, self.config, dry_run=self.dry_run, mock=self.mock
            )
            if self._logger:
                self._order_manager.set_logger(self._logger)
        return self._order_manager  # type: ignore

    def _today_str(self) -> str:
        return current_market_time(self.config).date().isoformat()

    def _get_leg_names(self) -> List[str]:
        """Return leg names for the current strategy."""
        strategies = self.config.get("strategies") or {}
        s = strategies.get(self.strategy_name) or strategies.get("SPX-DC") or {}
        legs = s.get("legs") or ["short_put", "long_put", "short_call", "long_call"]
        return list(legs)

    def _get_chain_from_broker(
        self,
        trade_date: date,
        expirations: List[str],
        leg_names: Optional[List[str]] = None,
        needed_expirations: Optional[set] = None,
    ) -> Tuple[Dict[str, List[ChainContract]], float]:
        """Fetch option chain and spot from IB. Returns (chain_by_expiry, spot). needed_expirations if set is set of expiry norms to fetch (e.g. from nearest-DTE fallback)."""
        leg_names = leg_names or self._get_leg_names()
        spot = self.ib_client.get_spx_spot() or 0.0
        chain_by_expiry: Dict[str, List[ChainContract]] = {}
        if needed_expirations is not None:
            needed = set(needed_expirations)
        else:
            needed = set()
            for leg_name in leg_names:
                leg_cfg = self.config.get(leg_name) or {}
                dte = leg_cfg.get("dte", 6)
                target_exp = (trade_date + timedelta(days=dte)).strftime("%Y%m%d")
                needed.add(target_exp)
        for exp in expirations:
            norm = exp.replace("-", "")[:8]
            if norm not in needed:
                continue
            raw = self.ib_client.get_spx_option_chain_for_expiry(norm, include_greeks=True)
            chain_by_expiry[norm] = [
                ChainContract(
                    strike=r["strike"],
                    right=r["right"],
                    expiry=norm,
                    delta=r.get("delta"),
                    con_id=r.get("con_id"),
                    local_symbol=r.get("local_symbol"),
                )
                for r in raw
            ]
        return chain_by_expiry, spot

    def _get_mock_chain(self, trade_date: date, spot: float, leg_names: Optional[List[str]] = None) -> Tuple[List[str], Dict[str, List[ChainContract]]]:
        """Mock expirations and chain for testing without broker."""
        leg_names = leg_names or self._get_leg_names()
        dtes = set()
        for name in leg_names:
            leg_cfg = self.config.get(name) or {}
            dtes.add(leg_cfg.get("dte", 5))
        expirations = [(trade_date + timedelta(days=d)).strftime("%Y%m%d") for d in sorted(dtes)]
        import math
        spacing = 5.0
        low = math.floor((spot * 0.98) / spacing) * spacing
        high = math.ceil((spot * 1.02) / spacing) * spacing
        strikes = []
        s = low
        while s <= high:
            strikes.append(s)
            s += spacing
        chain_by_expiry: Dict[str, List[ChainContract]] = {}
        for exp in expirations:
            chain = []
            for st in strikes:
                chain.append(ChainContract(strike=st, right="P", expiry=exp, delta=-0.20 + (spot - st) / 500))
                chain.append(ChainContract(strike=st, right="C", expiry=exp, delta=0.20 + (st - spot) / 500))
            chain_by_expiry[exp] = chain
        return expirations, chain_by_expiry

    def run_entry_checks(self) -> None:
        """Called every loop: if today is trade day, in entry window, not blackout, and risk ok -> try entry once."""
        today = current_market_time(self.config).date()
        date_str = today.isoformat()

        if not is_trade_day(today, self.config):
            return

        state = self.state_store.get_state()
        day = state.get_day(date_str)

        if day.entry_attempted:
            return

        if is_blackout(today, self.config):
            self._log("Friday %s is blackout; skipping trade", date_str)
            day.skip_reason = "blackout"
            day.entry_attempted = True
            state.set_day(date_str, day)
            self.state_store.save(state)
            return

        can, reason = self.risk.can_enter_today(date_str)
        if not can:
            self._log("Cannot enter today: %s", reason)
            return

        if not in_entry_window(self.config):
            return

        # Mark attempted before placing to prevent duplicate
        day.entry_attempted = True
        state.set_day(date_str, day)
        self.state_store.save(state)

        self._log("Entry window active; attempting entry for %s", date_str)
        self._try_entry(today, date_str)

    def _try_entry(self, trade_date: date, date_str: str) -> None:
        """Build legs, size, place order, update state."""
        state = self.state_store.get_state()
        day = state.get_day(date_str)

        leg_names = self._get_leg_names()
        self._log("Strategy %s: legs %s", self.strategy_name, leg_names)

        if self.mock or self.dry_run:
            spot = 5800.0  # mock
            expirations, chain_by_expiry = self._get_mock_chain(trade_date, spot, leg_names)
        else:
            if not self.ib_client or not self.ib_client.is_connected():
                self._log("IB not connected; skipping entry")
                return
            expirations = self.ib_client.get_spx_expirations()
            if not expirations:
                self._log("Contract selection failed: no SPX expirations from broker")
                return
            exp_norm = {ex.replace("-", "")[:8] for ex in expirations}
            needed = set()
            for name in leg_names:
                leg_cfg = self.config.get(name) or {}
                dte = leg_cfg.get("dte", 5)
                need_exp = (trade_date + timedelta(days=dte)).strftime("%Y%m%d")
                if need_exp in exp_norm:
                    needed.add(need_exp)
                else:
                    nearest = get_expiration_near_dte(expirations, trade_date, dte)
                    if nearest:
                        norm = nearest.replace("-", "")[:8]
                        needed.add(norm)
                        self._log("Using nearest expiry %s for leg %s (wanted %d DTE)", norm, name, dte)
                    else:
                        self._log("Contract selection failed: no expiry near %d DTE for leg %s", dte, name)
                        return
            chain_by_expiry, spot = self._get_chain_from_broker(trade_date, expirations, leg_names, needed_expirations=needed)
            for name in leg_names:
                leg_cfg = self.config.get(name) or {}
                dte = leg_cfg.get("dte", 5)
                exp = (trade_date + timedelta(days=dte)).strftime("%Y%m%d")
                n = len(chain_by_expiry.get(exp.replace("-", "")[:8], []))
                self._log("Chain for expiry %s (%s): %d contracts", exp, name, n)
            if spot <= 0:
                self._log("Contract selection failed: no SPX spot price")
                return

        specs = self.selector.select_legs_for_strategy(leg_names, trade_date, spot, expirations, chain_by_expiry)
        if not all(specs):
            for name, spec in zip(leg_names, specs):
                if spec is None:
                    self._log("Contract selection failed: leg %s returned no contract", name)
            self._log("Contract selection failed; aborting entry")
            return

        # Position size: 5% of portfolio, default 1 lot
        size = 1
        if self.ib_client and self.ib_client.is_connected() and not self.mock:
            nl = self.ib_client.net_liquidation()
            if nl and nl > 0:
                alloc_pct = self.config.get("allocate_pct", 0.05)
                size = max(1, int(nl * alloc_pct / 50000) or 1)
                size = min(size, 10)  # safeguard
        self._log("Position size: %d", size)

        legs_config = []
        leg_details = []
        for i, (name, spec) in enumerate(zip(leg_names, specs)):
            if spec is None:
                continue
            leg_cfg = self.config.get(name) or {}
            qty = leg_cfg.get("qty", 1) * size
            side = (leg_cfg.get("side") or "BUY").strip().upper()
            legs_config.append((spec, qty, side))
            leg_details.append({
                "leg_id": name,
                "strike": spec.strike,
                "right": spec.right,
                "expiry": spec.expiry,
                "side": side,
                "quantity": qty,
            })
        self._log("Placing order: %d leg(s)", len(legs_config))
        om = self._ensure_order_manager()
        success, records, err = om.place_combo(legs_config)

        if self.dry_run or self.mock:
            day.entry_filled = True
            day.position = {"trading_date": date_str, "quantity": size, "cost_basis": 1000.0, "legs": leg_details}
            state.set_day(date_str, day)
            self.state_store.save(state)
            self._log("DRY-RUN/MOCK: entry marked filled")
            return

        if success and records:
            cost = sum((r.fill_price or 0) * 100 for r in records)  # rough cost
            for r, ld in zip(records, leg_details):
                ld["fill_price"] = r.fill_price
            day.entry_filled = True
            day.position = {
                "trading_date": date_str,
                "entry_fill_time": datetime.now(timezone.utc).isoformat(),
                "quantity": size,
                "cost_basis": cost,
                "legs": leg_details,
            }
            state.set_day(date_str, day)
            self.state_store.save(state)
            self.pnl_monitor.set_cost_basis(cost)
            self._log("Entry filled; cost_basis=%.2f", cost)
        else:
            self._log("Entry failed: %s", err or "unknown")

    def run_exit_checks(self) -> None:
        """Scheduled exit: if in exit window and position open, close. Also PnL monitor triggers exit."""
        today = current_market_time(self.config).date()
        date_str = today.isoformat()

        state = self.state_store.get_state()
        day = state.get_day(date_str)

        if not day.entry_filled or day.exit_sent:
            return

        # Profit target is handled by pnl_monitor callback
        if in_exit_window(self.config):
            can, reason = self.risk.can_exit_today(date_str)
            if can:
                self._log("Exit window active; sending scheduled exit for %s", date_str)
                self._try_exit(date_str)

    def _try_exit(self, date_str: str) -> None:
        """Close position and update state."""
        state = self.state_store.get_state()
        day = state.get_day(date_str)
        if not day.position or day.exit_sent:
            return

        day.exit_sent = True
        state.set_day(date_str, day)
        self.state_store.save(state)

        om = self._ensure_order_manager()
        legs = day.position.get("legs") or []
        # Build close orders from position legs (inverse side)
        close_legs = []
        for leg in legs:
            side = leg.get("side", "BUY")
            close_legs.append({
                "symbol": "SPX",
                "exchange": "CBOE",
                "strike": leg.get("strike"),
                "right": leg.get("right", "P"),
                "expiry": leg.get("expiry"),
                "side": "SELL" if side == "BUY" else "BUY",
                "quantity": int(leg.get("quantity", 1)),
            })
        if not close_legs and day.position.get("cost_basis"):
            # Minimal: we might not have full leg details stored; in dry-run just mark exit
            if self.dry_run or self.mock:
                day.exit_filled = True
                day.exit_time = datetime.now(timezone.utc).isoformat()
                state.set_day(date_str, day)
                self.state_store.save(state)
                self._log("DRY-RUN/MOCK: exit marked filled")
                return
        success, err = om.place_close_orders(close_legs) if close_legs else (True, "")
        if success or self.dry_run or self.mock:
            day.exit_filled = True
            day.exit_time = datetime.now(timezone.utc).isoformat()
        state.set_day(date_str, day)
        self.state_store.save(state)
        self._log("Exit sent; filled=%s", day.exit_filled)

    def on_profit_target_met(self) -> None:
        """Callback from PnL monitor when profit target is confirmed."""
        date_str = self._today_str()
        state = self.state_store.get_state()
        day = state.get_day(date_str)
        if day.entry_filled and not day.exit_sent:
            self._log("Profit target met; triggering exit")
            self._try_exit(date_str)

    def run_pnl_check(self, current_value: float) -> None:
        """Update PnL monitor; may trigger exit via callback."""
        self.pnl_monitor.set_on_profit_target_met(self.on_profit_target_met)
        self.pnl_monitor.update(current_value)
