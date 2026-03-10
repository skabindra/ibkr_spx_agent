"""
Contract selection for the 4-leg SPX strategy.
Separates: expiration selection, option chain retrieval, delta filtering, strike offset logic.
Supports both delta-based and offset-based leg selection; config-driven.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

# Assumption: "offset 0" for long put/call means ATM (at-the-money), i.e. strike closest to
# current underlying price. No literal strike "offset" in points; we use reference = spot.


@dataclass
class OptionSpec:
    """Identifies a selected option (for order placement or mock)."""

    symbol: str
    sec_type: str
    exchange: str
    currency: str
    strike: float
    right: str  # "P" or "C"
    expiry: str  # YYYYMMDD
    multiplier: int = 100
    con_id: Optional[int] = None
    local_symbol: Optional[str] = None


@dataclass
class ChainContract:
    """Option contract with greeks for selection (from broker or mock)."""

    strike: float
    right: str
    expiry: str
    delta: Optional[float] = None
    con_id: Optional[int] = None
    local_symbol: Optional[str] = None


def get_expiration_for_dte(expirations: List[str], trade_date: date, dte: int) -> Optional[str]:
    """
    From a list of expiration strings (YYYYMMDD), return the one that is exactly `dte` days
    after trade_date. Uses exact DTE: expiration date = trade_date + dte.
    """
    target = trade_date + timedelta(days=dte)
    target_str = target.strftime("%Y%m%d")
    for ex in expirations:
        norm = ex.replace("-", "")[:8]
        if norm == target_str:
            return ex
    return None


def get_expiration_near_dte(expirations: List[str], trade_date: date, dte: int) -> Optional[str]:
    """
    When exact DTE is not listed (e.g. SPX has Mon/Wed/Fri only), return the expiration
    whose DTE is closest to the target. Helps strategies like SPX-CALL (5 DTE) when 5 DTE is not available.
    """
    if not expirations:
        return None
    best_ex = None
    best_diff = 9999
    for ex in expirations:
        norm = ex.replace("-", "")[:8]
        if len(norm) < 8:
            continue
        try:
            exp_date = date(int(norm[:4]), int(norm[4:6]), int(norm[6:8]))
            actual_dte = (exp_date - trade_date).days
            diff = abs(actual_dte - dte)
            if diff < best_diff:
                best_diff = diff
                best_ex = ex
        except (ValueError, TypeError):
            continue
    return best_ex


def select_by_delta(
    contracts: List[ChainContract],
    target_delta: float,
    right: str,
) -> Optional[ChainContract]:
    """
    From contracts with delta, select the one closest to target_delta for the given right.
    For short put we use put delta (negative); for short call we use call delta (positive).
    We compare absolute distance to target (e.g. 20 delta put ≈ -0.20, 20 delta call ≈ 0.20).
    """
    eligible = [c for c in contracts if c.right == right and c.delta is not None]
    if not eligible:
        return None
    # Target: 20 delta put -> -0.20, 20 delta call -> 0.20
    sign = 1 if right.upper() == "C" else -1
    want = sign * abs(target_delta) / 100.0
    best = min(eligible, key=lambda c: abs((c.delta or 0) - want))
    return best


def select_by_strike_offset(
    contracts: List[ChainContract],
    reference_strike: float,
    offset_strikes: int,
    right: str,
) -> Optional[ChainContract]:
    """
    Select contract by strike offset from reference (e.g. spot).
    offset_strikes = 0 means ATM: choose strike closest to reference_strike.
    SPX typically has 5-point strike spacing; we pick the strike that is closest to
    reference + (offset_strikes * strike_spacing). For offset 0, just closest to reference.
    """
    eligible = [c for c in contracts if c.right == right]
    if not eligible:
        return None
    # Assume 5-point spacing for SPX; offset 0 => target = reference_strike
    spacing = 5.0
    target = reference_strike + offset_strikes * spacing
    best = min(eligible, key=lambda c: abs(c.strike - target))
    return best


def contracts_to_specs(
    contracts: List[ChainContract],
    symbol: str = "SPX",
    exchange: str = "CBOE",
    currency: str = "USD",
    multiplier: int = 100,
) -> List[OptionSpec]:
    """Convert ChainContract list to OptionSpec list for order building."""
    out = []
    for c in contracts:
        out.append(
            OptionSpec(
                symbol=symbol,
                sec_type="OPT",
                exchange=exchange,
                currency=currency,
                strike=c.strike,
                right=c.right,
                expiry=c.expiry,
                multiplier=multiplier,
                con_id=c.con_id,
                local_symbol=c.local_symbol,
            )
        )
    return out


class ContractSelector:
    """
    High-level selector: given config and (mock or live) chain data, returns the four
    OptionSpecs for short put, long put, short call, long call.
    """

    def __init__(self, config: dict):
        self.config = config
        self.underlying = (config.get("underlying") or "SPX").strip().upper()

    def select_legs(
        self,
        trade_date: date,
        spot: float,
        expirations: List[str],
        chain_by_expiry: Dict[str, List[ChainContract]],
    ) -> Tuple[Optional[OptionSpec], Optional[OptionSpec], Optional[OptionSpec], Optional[OptionSpec]]:
        """
        Returns (short_put, long_put, short_call, long_call) OptionSpec or None if selection fails.
        chain_by_expiry: map expiration string -> list of ChainContract with delta.
        """
        short_put_cfg = self.config.get("short_put") or {}
        long_put_cfg = self.config.get("long_put") or {}
        short_call_cfg = self.config.get("short_call") or {}
        long_call_cfg = self.config.get("long_call") or {}

        dte_short = short_put_cfg.get("dte", 6)
        dte_long_put = long_put_cfg.get("dte", 7)
        dte_short_call = short_call_cfg.get("dte", 6)
        dte_long_call = long_call_cfg.get("dte", 7)

        exp_6 = get_expiration_for_dte(expirations, trade_date, dte_short)
        exp_7_put = get_expiration_for_dte(expirations, trade_date, dte_long_put)
        exp_6_call = get_expiration_for_dte(expirations, trade_date, dte_short_call)
        exp_7_call = get_expiration_for_dte(expirations, trade_date, dte_long_call)

        if not exp_6 or not exp_7_put or not exp_7_call:
            return None, None, None, None

        # Short put: 6 DTE, 20 delta
        put_chain_6 = chain_by_expiry.get(exp_6) or []
        sp = select_by_delta(put_chain_6, short_put_cfg.get("delta_target", 20), "P")
        short_put = self._to_spec(sp) if sp else None

        # Long put: 7 DTE, offset 0 (ATM)
        put_chain_7 = chain_by_expiry.get(exp_7_put) or []
        lp = select_by_strike_offset(
            put_chain_7, spot, long_put_cfg.get("strike_offset", 0), "P"
        )
        long_put = self._to_spec(lp) if lp else None

        # Short call: 6 DTE, 20 delta
        call_chain_6 = chain_by_expiry.get(exp_6_call) or []
        sc = select_by_delta(call_chain_6, short_call_cfg.get("delta_target", 20), "C")
        short_call = self._to_spec(sc) if sc else None

        # Long call: 7 DTE, offset 0 (ATM)
        call_chain_7 = chain_by_expiry.get(exp_7_call) or []
        lc = select_by_strike_offset(
            call_chain_7, spot, long_call_cfg.get("strike_offset", 0), "C"
        )
        long_call = self._to_spec(lc) if lc else None

        return short_put, long_put, short_call, long_call

    def _to_spec(self, c: ChainContract) -> OptionSpec:
        return OptionSpec(
            symbol=self.underlying,
            sec_type="OPT",
            exchange="CBOE",
            currency="USD",
            strike=c.strike,
            right=c.right,
            expiry=c.expiry,
            multiplier=100,
            con_id=c.con_id,
            local_symbol=c.local_symbol,
        )

    def select_legs_for_strategy(
        self,
        leg_names: List[str],
        trade_date: date,
        spot: float,
        expirations: List[str],
        chain_by_expiry: Dict[str, List[ChainContract]],
    ) -> List[Optional[OptionSpec]]:
        """
        Select one OptionSpec per leg name. Returns list in same order as leg_names; None if selection fails for that leg.
        """
        result = []
        for name in leg_names:
            leg_cfg = self.config.get(name) or {}
            dte = leg_cfg.get("dte", 5)
            exp = get_expiration_for_dte(expirations, trade_date, dte)
            if not exp:
                exp = get_expiration_near_dte(expirations, trade_date, dte)
            if not exp:
                result.append(None)
                continue
            norm = exp.replace("-", "")[:8]
            chain = chain_by_expiry.get(norm) or []
            right = "C" if (leg_cfg.get("option_type") or "CALL").upper().startswith("C") else "P"
            spec = None
            if "delta_target" in leg_cfg:
                c = select_by_delta(chain, leg_cfg.get("delta_target", 20), right)
                spec = self._to_spec(c) if c else None
            else:
                c = select_by_strike_offset(
                    chain, spot, leg_cfg.get("strike_offset", 0), right
                )
                spec = self._to_spec(c) if c else None
            result.append(spec)
        return result
