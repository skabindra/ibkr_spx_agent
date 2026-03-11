"""
One-off script: connect to IBKR and print the current price for a ticker.
Usage: python get_price.py [SYMBOL]
Default symbol: AAPL
"""

import os
import sys

from dotenv import load_dotenv
load_dotenv()

from ibkr_client import IBKRClient


def main() -> None:
    symbol = (sys.argv[1] if len(sys.argv) > 1 else "AAPL").strip().upper()
    allow_live = os.getenv("IBKR_ALLOW_LIVE", "false").lower() == "true"
    client = IBKRClient(allow_live=allow_live)

    print(f"Connecting to IBKR (paper port 4002)...")
    if not client.connect():
        print("Connection failed. Is TWS or IB Gateway running with API enabled?")
        sys.exit(1)

    try:
        price = client.get_ticker_price(symbol)
        if price is not None:
            print(f"{symbol}: {price}")
        else:
            print(f"{symbol}: no price (market closed or no data)")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
