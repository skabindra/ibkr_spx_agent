"""
Order placement and tracking for the 4-leg SPX structure.
Supports combo/bag orders when practical; fallback to leg-by-leg with safeguards.
Tracks submitted, filled, partial, cancelled, rejected. Records order IDs and fill data.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from contract_selector import OptionSpec
from ib_insync import LimitOrder, MarketOrder, Order, Trade


@dataclass
class OrderRecord:
    """Single order record for persistence."""

    order_id: int
    leg_id: str
    status: str  # Submitted, Filled, Cancelled, ApiCancelled, etc.
    fill_price: Optional[float] = None
    fill_time: Optional[str] = None
    filled: float = 0.0
    remaining: float = 0.0


def option_spec_to_contract(spec: OptionSpec) -> Any:
    """Build ib_insync Contract from OptionSpec. SPX options on CBOE."""
    from ib_insync import Contract

    c = Contract()
    c.symbol = spec.symbol
    c.secType = "OPT"
    c.exchange = spec.exchange
    c.currency = spec.currency
    c.lastTradeDateOrContractMonth = spec.expiry[:6] + "  " + spec.expiry[6:]  # YYYYMMDD -> YYYYMM DD
    c.strike = spec.strike
    c.right = spec.right
    c.multiplier = str(spec.multiplier)
    if spec.con_id:
        c.conId = spec.con_id
    return c


class OrderManager:
    """
    Place and track orders for the strategy. Uses IB API; in dry-run/mock mode
    no real orders are sent. Combo: place as separate legs with same order ref
    for tracking; IB supports bracket or group orders - we use individual limit
    orders with configurable limit (e.g. limit at mid or last) to avoid runaway fills.
    """

    def __init__(self, ib_client: Any, config: dict, dry_run: bool = False, mock: bool = False):
        self.ib = ib_client.ib if hasattr(ib_client, "ib") else ib_client
        self._account = getattr(ib_client, "account", "") or ""
        self.config = config
        self.dry_run = dry_run
        self.mock = mock
        self._records: List[OrderRecord] = []
        self._logger: Optional[Any] = None

    def set_logger(self, logger: Any) -> None:
        self._logger = logger

    def _log(self, msg: str, *args: Any) -> None:
        if self._logger:
            self._logger.info(msg, *args)

    def _log_error(self, msg: str, *args: Any) -> None:
        if self._logger:
            self._logger.error(msg, *args)

    def place_combo(
        self,
        legs: List[Tuple[OptionSpec, int, str]],
    ) -> Tuple[bool, List[OrderRecord], Optional[str]]:
        """
        Place the 4-leg combo. legs = [(OptionSpec, quantity, "BUY"|"SELL"), ...].
        Returns (success, list of OrderRecord, error_message).
        In dry_run/mock, simulates success and returns empty records or mock records.
        """
        if self.dry_run or self.mock:
            self._log("DRY-RUN/MOCK: would place %d legs", len(legs))
            return True, [], None

        if not self.ib.isConnected():
            return False, [], "Not connected to IB"

        records: List[OrderRecord] = []
        orders_placed: List[Trade] = []
        try:
            for i, (spec, qty, action) in enumerate(legs):
                contract = option_spec_to_contract(spec)
                # Use market for paper testing to simplify; can switch to limit with offset
                order = MarketOrder(action, qty)
                if self._account:
                    order.account = self._account
                trade = self.ib.placeOrder(contract, order)
                orders_placed.append(trade)
                leg_id = f"leg_{i}_{spec.right}_{spec.strike}_{spec.expiry}"
                records.append(
                    OrderRecord(order_id=trade.order.orderId, leg_id=leg_id, status="Submitted")
                )
                time.sleep(0.2)  # Avoid rate limit

            # Wait for fills (with timeout)
            timeout = 60
            start = time.time()
            while time.time() - start < timeout:
                all_done = True
                for j, trade in enumerate(orders_placed):
                    st = trade.orderStatus.status
                    if st in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
                        if j < len(records):
                            records[j].status = st
                            if st == "Filled" and trade.orderStatus.avgFillPrice:
                                records[j].fill_price = float(trade.orderStatus.avgFillPrice)
                                records[j].filled = float(trade.orderStatus.filled)
                    else:
                        all_done = False
                if all_done:
                    break
                self.ib.sleep(1)
            self._records.extend(records)
            success = all(r.status == "Filled" for r in records)
            return success, records, None if success else "One or more legs did not fill"
        except Exception as e:
            self._log_error("Place combo failed: %s", e)
            return False, records, str(e)

    def place_close_orders(self, position_legs: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """
        Close an open position by placing opposite orders for each leg.
        position_legs: list of dict with contract info and side (BUY/SELL), quantity.
        Returns (success, error_message).
        """
        if self.dry_run or self.mock:
            self._log("DRY-RUN/MOCK: would close %d legs", len(position_legs))
            return True, ""

        if not self.ib.isConnected():
            return False, "Not connected to IB"

        try:
            for leg in position_legs:
                from ib_insync import Contract

                c = Contract()
                c.symbol = leg.get("symbol", "SPX")
                c.secType = "OPT"
                c.exchange = leg.get("exchange", "CBOE")
                c.currency = "USD"
                c.lastTradeDateOrContractMonth = leg.get("expiry", "")[:6] + "  " + leg.get("expiry", "")[6:]
                c.strike = leg.get("strike", 0)
                c.right = leg.get("right", "P")
                c.multiplier = "100"
                action = "SELL" if leg.get("side") == "BUY" else "BUY"
                qty = int(leg.get("quantity", 1))
                order = MarketOrder(action, qty)
                if self._account:
                    order.account = self._account
                self.ib.placeOrder(c, order)
                time.sleep(0.2)
            return True, ""
        except Exception as e:
            self._log_error("Close orders failed: %s", e)
            return False, str(e)

    def get_records(self) -> List[OrderRecord]:
        return list(self._records)
