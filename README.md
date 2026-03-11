# IBKR SPX Paper-Trading Agent

A config-driven, modular Python bot that connects to **Interactive Brokers paper trading** via `ib_insync`, implements a 4-leg SPX options strategy, and manages entry/exit using time windows and a two-price profit target. **For paper testing only — not for production or live trading.**

---

## Warning

**This system is intended for paper trading and backtest-style testing only.** Do not use with a live account unless you have explicitly enabled the safety override and accept full responsibility. Options trading involves substantial risk.

---

## How to Install

1. **Python 3.10+** and a virtual environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Copy environment template and set paper-trading connection:**

   ```bash
   cp .env.example .env
   # Edit .env: set IBKR_HOST, IBKR_PORT (e.g. 4002 for paper), IBKR_CLIENT_ID, IBKR_ACCOUNT
   ```

4. **Enable API in TWS or IB Gateway** (see below).

---

## How to Enable API in TWS / IB Gateway

- **TWS:** File → Global Configuration → API → Settings. Enable “Enable ActiveX and Socket Clients”, set “Socket port” (paper usually **4002**). Optionally add “Trusted IPs”.
- **IB Gateway:** Same idea: configure API and set the paper port (typically **4002**). Live is usually **4001**.
- Ensure “Read-Only API” is **off** if the bot will place orders.
- Start TWS or IB Gateway and leave it running before starting the agent.

---

## How to Run in Dry-Run Mode

Dry-run prevents real order submission while still running the strategy logic, scheduling, and state updates:

```bash
DRY_RUN=1 python main.py
```

Or set in `.env`:

```
DRY_RUN=1
```

The bot will connect (unless in mock), evaluate Fridays, entry/exit windows, and blackout days, and **simulate** entry/exit without sending orders.

---

## How to Run in IBKR Paper Mode

1. Start TWS or IB Gateway and log in to your **paper** account.
2. Ensure API is enabled on port **4002** (or the port in your `.env`).
3. Set in `.env`:

   ```
   IBKR_PORT=4002
   IBKR_ALLOW_LIVE=false
   ```

4. Run without `MOCK` and without `DRY_RUN` for real paper orders:

   ```bash
   python main.py
   ```

   Or with dry-run for logic-only:

   ```bash
   DRY_RUN=1 python main.py
   ```

---

## How Blackout Dates Are Configured

- In `config.yaml`, the `blackout_dates` list contains dates (YYYY-MM-DD) on which the bot will **not** open a trade, even if it is an eligible Friday.
- Set `use_blackout_days: true` to enable.
- Example:

  ```yaml
  use_blackout_days: true
  blackout_dates:
    - "2024-01-15"
    - "2024-02-19"
  ```

- If a Friday falls on a blackout date, the bot skips the trade and logs the reason. The structure allows adding macro-event or calendar-based blackouts later.

---

## How Profit Target Confirmation Works

- **Profit target** is set in config (e.g. `profit_target_pct: 0.20` for 20%).
- **Two-price confirmation:** When `require_two_price_confirmation: true`, the bot does **not** exit on the first poll where the target is met. It requires **two consecutive** polls (at the configured `pnl_poll_interval_seconds`) where the profit target is satisfied before sending the exit. This reduces noise from single-tick spikes.
- Each qualifying and non-qualifying check is logged. If the second check fails (e.g. price moves back below target), the confirmation count resets.

---

## How the Bot Handles Entry and Exit Windows

- **Entry:** Only on the configured trade day (e.g. **Friday**). Within that day, entry is allowed only inside the **entry time window**: target time (e.g. **9:45 AM**) ± `entry_offset_minutes` (e.g. 2 minutes), so 9:43–9:47 in market timezone.
- **Exit:** Two ways:
  1. **Scheduled exit:** Same idea: target time (e.g. 9:45 AM) ± `exit_offset_minutes`. If the position is still open at that window, the bot sends the exit.
  2. **Early exit:** When the profit target is reached and (if enabled) confirmed by two consecutive price checks.
- All times use the config `timezone` (e.g. `America/New_York`).
- **Overrides (env):** You can override the entry time with `ENTRY_TIME=14:58` (window then 14:56–15:00 with ±2 min). Use `ALLOW_ANY_DAY=1` to treat any day as a trade day. Use `RESET_ENTRY_TODAY=1` once to clear today’s entry state so the bot can retry entry the same day.

---

## Get Ticker Price

To fetch the current price of a ticker (e.g. for a stock or index) without running the full agent:

```bash
python get_price.py [SYMBOL]
# Default symbol: AAPL
python get_price.py AAPL
python get_price.py MSFT
```

Requires TWS or IB Gateway running with API enabled. The underlying API is `IBKRClient.get_ticker_price(symbol, sec_type="STK", exchange="SMART", currency="USD")`; for indices use e.g. `get_ticker_price("SPX", sec_type="IND", exchange="CBOE")`.

---

## Buy Stock at Market

To place a **market BUY** order for a stock and then disconnect:

```bash
python buy_stock.py SYMBOL QUANTITY
# Examples:
python buy_stock.py AAPL 10
python buy_stock.py MSFT 5
```

- Requires TWS or IB Gateway (paper port, e.g. 4002). Orders use time-in-force **DAY** to match IBKR presets.
- **DRY_RUN:** `DRY_RUN=1 python buy_stock.py AAPL 10` simulates the order without sending it.
- **Success:** The script treats **Filled**, **PreSubmitted**, and **Submitted** as success (order placed). Only **Cancelled** / **ApiCancelled** / **Inactive** are reported as failure. If the order is still pending (PreSubmitted/Submitted), check TWS for fill status.

---

## Dry-Run Example

```bash
# No real orders; state and logs still updated
DRY_RUN=1 python main.py
```

Example log output:

```
2024-03-15 09:44:00 | INFO     | ibkr_spx_agent | Entry window active; attempting entry for 2024-03-15
2024-03-15 09:44:00 | INFO     | ibkr_spx_agent | DRY-RUN/MOCK: would place 4 legs
2024-03-15 09:44:00 | INFO     | ibkr_spx_agent | DRY-RUN/MOCK: entry marked filled
```

---

## Assumptions and Limitations

- **SPX only:** Contract selection and chain logic are built for SPX (CBOE). Other underlyings would require config and code changes.
- **Option chain and greeks:** Delta and ATM selection depend on broker-provided option chain and (where used) model greeks. Behavior may differ by session and data permissions.
- **Combo routing:** Orders are placed as individual legs with market orders in the reference implementation. Combo/bag order support may require broker-specific handling.
- **Position value for PnL:** The current implementation uses a simplified notion of position value for the profit target. A production-grade version would use the actual combo mark or position P&L from the broker.
- **One entry per day:** The bot is designed to enter at most once per eligible Friday and exit once (either by profit target or scheduled window).
- **No guarantee of fill:** The bot does not assume immediate fills; it tracks order status and records fill prices when available.
- **Paper/live safety:** Live connection is blocked unless `IBKR_ALLOW_LIVE` is explicitly set to true.

---

## Future Extensions

- **Other underlyings:** Make underlying and exchange configurable so the same engine can drive SPX, SPXW, or other index/equity options.
- **Delta/offset variations:** Config already supports different deltas and strike offsets per leg; extend contract selection to support more underlyings and expirations.
- **Live-trading safeguards:** Additional checks (e.g. max notional, daily loss cap, separate config file for live) and stricter kill-switch behavior for any future live use.
- **SQLite state:** Option to use SQLite instead of JSON for state persistence and querying.
- **Macro blackout calendar:** Integrate an economic calendar or custom list to auto-add blackout days around events.

---

## Project Layout

- `main.py` — Entry point; connection, loop, reconnect, PnL polling.
- `get_price.py` — One-off script to fetch and print a ticker’s price (e.g. `python get_price.py AAPL`).
- `buy_stock.py` — One-off script to place a market BUY order (e.g. `python buy_stock.py AAPL 10`).
- `config.yaml` — Strategy and risk parameters, leg definitions, blackout list.
- `.env.example` / `.env` — Broker and safety settings.
- `ibkr_client.py` — IB connection, paper check, expirations, option chain, `get_ticker_price()`, `get_spx_spot()`.
- `strategy_engine.py` — Entry/exit orchestration, contract selection, order and state updates.
- `contract_selector.py` — DTE/expiration, delta and strike-offset selection.
- `order_manager.py` — Place combo/legs and stock market orders, track orders and fills (`buy_stock_at_market()`).
- `risk_manager.py` — Paper-only, kill switch, one entry per day, max positions.
- `pnl_monitor.py` — P&L polling and two-price profit target logic.
- `scheduler.py` — Trade day and entry/exit time windows (respects `ENTRY_TIME` env).
- `blackout_days.py` — Blackout date handling.
- `state_store.py` — Persistent state (JSON).
- `logger.py` / `utils.py` — Logging and config helpers.
- `tests/` — Time window, profit target confirmation, contract selection tests.

Run tests:

```bash
python -m pytest tests/ -v
# or
python -m unittest discover -s tests -v
```
