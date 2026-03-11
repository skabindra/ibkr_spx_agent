"""
IBKR connection via ib_insync. Paper trading only unless safety override is set.
Handles connect, disconnect, and reconnect with validation.
"""

import os
import time
from typing import Any, Callable, List, Optional

from ib_insync import IB, Contract, Ticker, util

from utils import get_env


class IBKRClient:
    """
    Wrapper around ib_insync IB() for paper trading.
    Validates that connection is not to live account unless IBKR_ALLOW_LIVE=true.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: Optional[int] = None,
        account: Optional[str] = None,
        allow_live: bool = False,
    ):
        self.host = host or get_env("IBKR_HOST", "127.0.0.1")
        self.port = int(port or get_env("IBKR_PORT", "4002"))
        self.client_id = int(client_id or get_env("IBKR_CLIENT_ID", "1"))
        self.account = account or get_env("IBKR_ACCOUNT", "")
        self.allow_live = allow_live or (os.getenv("IBKR_ALLOW_LIVE", "false").lower() == "true")
        self._ib = IB()
        self._logger: Optional[Any] = None

    def set_logger(self, logger: Any) -> None:
        self._logger = logger

    def _log_info(self, msg: str, *args: Any) -> None:
        if self._logger:
            self._logger.info(msg, *args)
        else:
            print("[IBKR]", msg % args if args else msg)

    def _log_error(self, msg: str, *args: Any) -> None:
        if self._logger:
            self._logger.error(msg, *args)
        else:
            print("[IBKR ERROR]", msg % args if args else msg)

    def is_connected(self) -> bool:
        return self._ib.isConnected()

    def connect(self) -> bool:
        """
        Connect to TWS/IB Gateway. If port is live (typically 4001), fail unless allow_live.
        Paper trading typically uses port 4002.
        """
        if self.port == 4001 and not self.allow_live:
            self._log_error("Refusing to connect to port 4001 (live) without IBKR_ALLOW_LIVE=true")
            return False
        try:
            self._ib.connect(self.host, self.port, clientId=self.client_id)
            self._log_info("Connected to IBKR host=%s port=%s", self.host, self.port)
            return True
        except Exception as e:
            self._log_error("Connect failed: %s", e)
            return False

    def get_session_accounts(self) -> List[str]:
        """Return list of account IDs available in this session (from TWS/Gateway)."""
        if not self._ib.isConnected():
            return []
        try:
            # ib_insync: managedAccounts is set after connect (comma-separated string or list)
            accounts = getattr(self._ib, "managedAccounts", None)
            if accounts is None:
                return []
            if isinstance(accounts, str):
                return [a.strip() for a in accounts.split(",") if a.strip()]
            return list(accounts) if accounts else []
        except Exception:
            return []

    def disconnect(self) -> None:
        self._ib.disconnect()
        self._log_info("Disconnected from IBKR")

    def reconnect(self, max_attempts: int = 5, delay_sec: float = 2.0) -> bool:
        """Disconnect if connected, then connect with retries."""
        if self._ib.isConnected():
            try:
                self._ib.disconnect()
            except Exception:
                pass
        for attempt in range(max_attempts):
            if self.connect():
                return True
            if attempt < max_attempts - 1:
                time.sleep(delay_sec)
        return False

    @property
    def ib(self) -> IB:
        return self._ib

    def get_account_values(self) -> List[Any]:
        """Request and return account summary (e.g. NetLiquidation)."""
        if not self._ib.isConnected():
            return []
        self._ib.reqAccountSummary(self.client_id, "All", "NetLiquidation")
        time.sleep(0.5)
        values = self._ib.accountSummary(self.client_id)
        self._ib.cancelAccountSummary(self.client_id, "All", "NetLiquidation")
        return list(values)

    def get_positions(self) -> List[dict]:
        """Return current positions for the configured account. Each item: symbol, secType, position, avgCost, contract description."""
        if not self._ib.isConnected():
            return []
        try:
            self._ib.reqPositions()
            self._ib.sleep(2)
            out = []
            for p in self._ib.positions():
                acct = (getattr(p, "account", "") or "").strip()
                if self.account and acct.upper() != (self.account or "").strip().upper():
                    continue
                c = getattr(p, "contract", None)
                pos = getattr(p, "position", 0) or 0
                avg = getattr(p, "avgCost", 0) or 0
                desc = ""
                if c:
                    sym = getattr(c, "symbol", "") or ""
                    sec = getattr(c, "secType", "") or ""
                    strike = getattr(c, "strike", "") or ""
                    right = getattr(c, "right", "") or ""
                    exp = getattr(c, "lastTradeDateOrContractMonth", "") or ""
                    desc = f"{sym} {sec} {strike} {right} {exp}".strip()
                out.append({"account": acct, "position": pos, "avgCost": avg, "contract": desc})
            return out
        except Exception as e:
            self._log_error("Get positions failed: %s", e)
            return []

    def net_liquidation(self) -> Optional[float]:
        """Current net liquidation value for configured account."""
        for v in self.get_account_values():
            if getattr(v, "account", None) == self.account or not self.account:
                if getattr(v, "tag", None) == "NetLiquidation":
                    try:
                        return float(v.value)
                    except (TypeError, ValueError):
                        pass
        # Fallback: first account's NetLiquidation
        for v in self.get_account_values():
            if getattr(v, "tag", None) == "NetLiquidation":
                try:
                    return float(v.value)
                except (TypeError, ValueError):
                    pass
        return None

    def get_spx_spot(self) -> Optional[float]:
        """Request SPX index quote; return last price."""
        return self.get_ticker_price("SPX", sec_type="IND", exchange="CBOE")

    def get_ticker_price(
        self,
        symbol: str,
        sec_type: str = "STK",
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> Optional[float]:
        """
        Request market data for the given ticker; return last price (or close).

        Args:
            symbol: Ticker symbol (e.g. AAPL, SPX).
            sec_type: Security type: STK (stock), IND (index), etc.
            exchange: Exchange (SMART for stocks, CBOE for SPX, etc.).
            currency: Currency code (default USD).

        Returns:
            Last price, or close if last unavailable; None on error or no data.
        """
        if not self._ib.isConnected():
            self._log_error("Not connected; cannot get quote for %s", symbol)
            return None
        c = Contract()
        c.symbol = symbol
        c.secType = sec_type
        c.exchange = exchange
        c.currency = currency
        try:
            ticker = self._ib.reqMktData(c, "", False, False)
            self._ib.sleep(2)
            price = ticker.last if ticker.last and ticker.last > 0 else ticker.close
            self._ib.cancelMktData(c)
            return float(price) if price is not None else None
        except Exception as e:
            self._log_error("Quote failed for %s: %s", symbol, e)
            return None

    def get_spx_expirations(self) -> List[str]:
        """Return list of SPX option expiration dates (YYYYMMDD)."""
        if not self._ib.isConnected():
            return []
        c = Contract()
        c.symbol = "SPX"
        c.secType = "OPT"
        c.exchange = "CBOE"
        c.currency = "USD"
        try:
            details = self._ib.reqContractDetails(c)
            expirations = set()
            for d in details:
                if d.contract.lastTradeDateOrContractMonth:
                    exp = d.contract.lastTradeDateOrContractMonth.replace(" ", "")[:8]
                    if len(exp) == 8:
                        expirations.add(exp)
            return sorted(expirations)
        except Exception as e:
            self._log_error("SPX expirations failed: %s", e)
            return []

    def get_spx_option_chain_for_expiry(
        self, expiry: str, include_greeks: bool = True
    ) -> List[dict]:
        """
        Return list of option contracts for given expiry. Each item: strike, right, conId, delta (if requested).
        expiry: YYYYMMDD. For delta we request market data (model greeks).
        """
        if not self._ib.isConnected():
            return []
        from ib_insync import Contract

        c = Contract()
        c.symbol = "SPX"
        c.secType = "OPT"
        c.exchange = "CBOE"
        c.currency = "USD"
        c.lastTradeDateOrContractMonth = expiry[:6] + "  " + expiry[6:]
        try:
            details = self._ib.reqContractDetails(c)
            contracts = [d.contract for d in details]
            out = []
            tickers = []
            for con in contracts:
                t = self._ib.reqMktData(con, "", False, False)
                tickers.append((con, t))
            self._ib.sleep(3)
            for con, t in tickers:
                delta = None
                if include_greeks and hasattr(t, "modelGreeks") and t.modelGreeks:
                    delta = getattr(t.modelGreeks, "delta", None)
                if delta is None and include_greeks and hasattr(t, "delta"):
                    delta = getattr(t, "delta", None)
                out.append({
                    "strike": con.strike,
                    "right": con.right,
                    "expiry": expiry,
                    "con_id": con.conId,
                    "local_symbol": getattr(con, "localSymbol", None),
                    "delta": float(delta) if delta is not None else None,
                })
            for con, _ in tickers:
                self._ib.cancelMktData(con)
            return out
        except Exception as e:
            self._log_error("SPX option chain failed for %s: %s", expiry, e)
            return []
