# Options Trade-Idea Alert System

A decision-support tool for trading options on a small (sub-$500) account.
It scans a watchlist, applies a trend + momentum + volatility filter, picks
a real contract (or debit spread) off the live options chain that fits your
budget, and tells you exactly what it would buy and why.

**It does not place trades.** There is no broker integration and no order
execution anywhere in this codebase. You run `scan`, read the output,
and if you like an idea, you go place it yourself in Robinhood.

## Important context before you use this

- **A $500 account cannot do most options strategies.** Covered calls and
  cash-secured puts need 100 shares or full strike collateral, which is
  usually way more than $500. This system is built around **long calls,
  long puts, and debit spreads** -- the strategies where your max loss is
  capped at what you pay, and where a small account can actually
  participate.
- **Options are a leveraged, decaying asset.** A wrong-direction move or
  a name that just sits still can both lose you the entire premium. Sizing
  rules in `config.yaml` cap what any one idea can cost, but they can't cap
  how often you decide to hit "buy."
- **No system guarantees profit.** This one is built to be picky (multiple
  filters must line up) rather than to always produce a trade. Some days
  it will find nothing, and that's the system working as intended, not
  broken.
- **Quotes are delayed/best-effort (Yahoo Finance via `yfinance`).** Always
  check the live bid/ask in Robinhood before entering -- this tool is for
  idea generation, not execution pricing.
- **Pattern Day Trader (PDT) rule**: if your account is a margin account
  under $25k, you're limited to 3 day trades per rolling 5 business days.
  This system's default 25-50 DTE holding period is designed to not bump
  into that, but closing same-day is on you to track.

This is not financial advice. Use at your own risk.

## How it works

1. **Screener** (`src/screener.py` + `src/strategy.py`) walks your
   `watchlist`. For each ticker it:
   - Computes a trend (fast/slow SMA) and RSI off ~1 year of daily prices.
   - Estimates a volatility percentile (a realized-volatility-based proxy
     for "IV rank," since free historical IV data doesn't really exist) and
     skips names where volatility looks already elevated -- you want to buy
     premium when it's cheap-ish, not expensive.
   - If trend + RSI + volatility line up, pulls the **real, current** options
     chain and picks a contract in your target delta band (default: 0.35-0.60
     absolute delta, ~25-50 days to expiration) that's liquid enough to
     actually fill (open interest, volume, bid/ask spread filters).
   - If a single contract costs more than your per-trade budget, it
     automatically converts the idea into a debit spread (buy that contract,
     sell a further-OTM one) to bring the cost down.
2. **Position sizing** (`src/position_sizing.py`) caps each idea at
   `max_risk_per_trade_pct` of your account (or `max_trade_cost_usd`,
   whichever is smaller), and never recommends more than
   `max_open_positions` ideas across a scan.
3. **Alerts** (`src/alerts.py`) print a plain-English trade ticket to your
   terminal, log every idea to `logs/alerts_log.csv`, and write a daily
   `logs/report_YYYY-MM-DD.md`.
4. **Position tracking** (`src/positions.py`) lets you tell the system
   "I took idea #2," and later ask it "should I close this?" -- it re-prices
   your specific contract(s) against the live chain and applies profit
   target / stop loss / time-based exit rules from `config.yaml`.
5. **Backtester** (`src/backtest.py`) replays the *exact* signal logic
   against historical prices, using Black-Scholes with realized volatility
   as a modeled stand-in for option prices (see the caveats in that file's
   docstring -- it's a sanity check on the entry logic, not a promise).

## Setup

```bash
pip install -r requirements.txt
```

Edit `config.yaml`:
- `account.portfolio_value` -- set this to your actual account size.
- `watchlist` -- liquid, optionable tickers you actually want exposure to.
- Everything else has reasonable defaults; tune `strategy.*` and `exits.*`
  once you've read `src/strategy.py` and understand what each knob does.

## Usage

Run a scan (do this once a day, e.g. before market open or after close so
you're reviewing prior-day-close-based signals against the next session's
chain):

```bash
python main.py scan
```

Track a trade after you've actually placed it in Robinhood:

```bash
python main.py positions add 0        # tracks idea #0 from the last scan
python main.py positions list
python main.py positions check        # tells you HOLD / take profit / cut loss / time exit
python main.py positions close <id> --note "closed for +60%"
```

Backtest the strategy logic before trusting it with real money:

```bash
python main.py backtest --years 3
```

## Testing

```bash
python -m unittest discover -s tests -v
```

## Project layout

```
config.yaml            All tunable parameters (account, watchlist, strategy, exits)
main.py                CLI entrypoint
src/
  config.py            YAML -> dataclasses
  data.py               yfinance wrappers (price history, options chains)
  indicators.py         SMA, RSI, realized volatility, volatility-percentile proxy
  options_pricing.py     Black-Scholes price/delta/implied-vol
  strategy.py            Per-ticker signal + contract/spread selection
  position_sizing.py      Risk-based contract sizing for a small account
  screener.py            Runs strategy across the watchlist, applies budget caps
  alerts.py               Console/CSV/markdown output
  positions.py            Manual trade tracking + exit-rule checks
  backtest.py             Historical signal backtest (modeled option prices)
tests/                  Unit tests for indicators, pricing, and sizing
logs/                   CSV log, markdown reports, tracked positions (gitignored)
```
