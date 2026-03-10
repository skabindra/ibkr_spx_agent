"""
Tests for contract selection helper behavior with mocked option chain data.
"""

import unittest
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_selector import (
    ChainContract,
    ContractSelector,
    get_expiration_for_dte,
    select_by_delta,
    select_by_strike_offset,
)


class TestContractSelection(unittest.TestCase):
    def test_get_expiration_for_dte(self) -> None:
        trade_date = date(2024, 3, 15)
        expirations = ["20240321", "20240322", "20240328"]
        self.assertEqual(get_expiration_for_dte(expirations, trade_date, 6), "20240321")
        self.assertEqual(get_expiration_for_dte(expirations, trade_date, 7), "20240322")
        self.assertIsNone(get_expiration_for_dte(expirations, trade_date, 5))

    def test_select_by_delta_put(self) -> None:
        contracts = [
            ChainContract(strike=5700, right="P", expiry="20240321", delta=-0.30),
            ChainContract(strike=5750, right="P", expiry="20240321", delta=-0.22),
            ChainContract(strike=5800, right="P", expiry="20240321", delta=-0.18),
        ]
        c = select_by_delta(contracts, 20, "P")
        self.assertIsNotNone(c)
        self.assertEqual(c.strike, 5750)  # -0.22 closest to -0.20

    def test_select_by_delta_call(self) -> None:
        contracts = [
            ChainContract(strike=5850, right="C", expiry="20240321", delta=0.18),
            ChainContract(strike=5900, right="C", expiry="20240321", delta=0.22),
            ChainContract(strike=5950, right="C", expiry="20240321", delta=0.28),
        ]
        c = select_by_delta(contracts, 20, "C")
        self.assertIsNotNone(c)
        self.assertEqual(c.strike, 5900)

    def test_select_by_strike_offset_zero(self) -> None:
        spot = 5825.0
        contracts = [
            ChainContract(strike=5820, right="P", expiry="20240322"),
            ChainContract(strike=5825, right="P", expiry="20240322"),
            ChainContract(strike=5830, right="P", expiry="20240322"),
        ]
        c = select_by_strike_offset(contracts, spot, 0, "P")
        self.assertIsNotNone(c)
        self.assertEqual(c.strike, 5825)

    def test_selector_select_legs_mock_chain(self) -> None:
        config = {
            "underlying": "SPX",
            "short_put": {"delta_target": 20, "dte": 6},
            "long_put": {"strike_offset": 0, "dte": 7},
            "short_call": {"delta_target": 20, "dte": 6},
            "long_call": {"strike_offset": 0, "dte": 7},
        }
        trade_date = date(2024, 3, 15)
        exp6 = (trade_date + timedelta(days=6)).strftime("%Y%m%d")
        exp7 = (trade_date + timedelta(days=7)).strftime("%Y%m%d")
        spot = 5820.0
        chain = {
            exp6: [
                ChainContract(5820, "P", exp6, delta=-0.20),
                ChainContract(5820, "C", exp6, delta=0.20),
                ChainContract(5825, "P", exp6, delta=-0.25),
                ChainContract(5815, "C", exp6, delta=0.25),
            ],
            exp7: [
                ChainContract(5815, "P", exp7),
                ChainContract(5820, "P", exp7),
                ChainContract(5825, "P", exp7),
                ChainContract(5815, "C", exp7),
                ChainContract(5820, "C", exp7),
                ChainContract(5825, "C", exp7),
            ],
        }
        selector = ContractSelector(config)
        sp, lp, sc, lc = selector.select_legs(trade_date, spot, [exp6, exp7], chain)
        self.assertIsNotNone(sp)
        self.assertIsNotNone(lp)
        self.assertIsNotNone(sc)
        self.assertIsNotNone(lc)
        self.assertEqual(sp.right, "P")
        self.assertEqual(lp.right, "P")
        self.assertEqual(sc.right, "C")
        self.assertEqual(lc.right, "C")
        self.assertEqual(lp.strike, 5820)
        self.assertEqual(lc.strike, 5820)


if __name__ == "__main__":
    unittest.main()
