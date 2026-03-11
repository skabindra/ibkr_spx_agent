"""
One-off script: connect to IBKR and place a market BUY order for a stock.
Usage: python buy_stock.py SYMBOL QUANTITY
  e.g. python buy_stock.py AAPL 10
Set DRY_RUN=1 to simulate (no real order).
"""

import os
import sys

from dotenv import load_dotenv
load_dotenv()

from utils import load_config
from ibkr_client import IBKRClient
from order_manager import OrderManager


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python buy_stock.py SYMBOL QUANTITY")
        print("  e.g. python buy_stock.py AAPL 10")
        print("  Set DRY_RUN=1 to simulate without sending the order.")
        sys.exit(1)

    symbol = sys.argv[1].strip().upper()
    try:
        quantity = int(sys.argv[2])
    except ValueError:
        print("QUANTITY must be an integer")
        sys.exit(1)

    if quantity <= 0:
        print("QUANTITY must be positive")
        sys.exit(1)

    dry_run = os.getenv("DRY_RUN", "0").lower() in ("1", "true", "yes")
    allow_live = os.getenv("IBKR_ALLOW_LIVE", "false").lower() == "true"

    config = load_config()
    client = IBKRClient(allow_live=allow_live)

    print("Connecting to IBKR (paper port 4002)...")
    if not client.connect():
        print("Connection failed. Is TWS or IB Gateway running with API enabled?")
        sys.exit(1)

    try:
        om = OrderManager(client, config, dry_run=dry_run, mock=False)
        success, record, err = om.buy_stock_at_market(symbol, quantity)
        if success:
            if dry_run:
                print(f"DRY-RUN: would buy {quantity} shares of {symbol} at market")
            elif record and record.fill_price is not None:
                print(f"Filled: {record.filled} shares of {symbol} at {record.fill_price}")
            else:
                status = record.status if record else "Submitted"
                print(f"Order placed for {symbol} (status: {status}). Check TWS for fill.")
        else:
            print(f"Failed: {err or 'Unknown error'}")
            sys.exit(1)
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
