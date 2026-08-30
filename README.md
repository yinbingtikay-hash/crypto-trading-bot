# Crypto Trading Bot — Systematic Strategy Research

Independent research project testing multiple systematic trading approaches on crypto
derivatives (BTC/ETH), built around one rule: **backtest and cross-validate before any
strategy is allowed to touch live capital.** Every strategy below was tested under a
walk-forward, out-of-sample discipline with explicit lookahead-bias controls.

## Headline result: Funding Squeeze Long

The only approach that survived rigorous testing. The idea: treat the perpetual futures
**funding rate** as a leverage-crowding signal rather than trying to predict price directly.
When funding drops to an extreme negative z-score, it means a large share of the market is
crowded into leveraged shorts — a setup prone to short-covering rallies. The strategy goes
long spot at that point and exits after a fixed holding period.

- **Selected config:** `z-score < -2.0`, hold 6 funding periods (~48h)
- **Result:** Profit Factor **1.63–1.74**, confirmed independently across two structurally
  different backtesting engines (see *Methodology* below)
- **Out-of-sample train/test split:** edge holds in both halves, not just in-sample
- **Stop-loss tested and rejected:** a full grid search (2–8% stop levels) showed every
  stop-loss variant *reduced* Profit Factor relative to no stop — the edge depends on
  giving the position time to mean-revert, so cutting losses early removes exactly the
  trades that would have worked. Documented in `funding_squeeze_backtest.py`.
- **Does not generalize to ETH:** the same validated parameters applied to ETHUSDT scored
  PF 0.80 (engine 1) and 0.58 (engine 2) — both losing, and the two engines disagreed more
  than they do on BTC. Read as evidence the edge is BTC-specific market structure, not a
  general crypto effect — the live bot stays BTC-only rather than assuming the result
  transfers.

This is now running as a live **paper-trading** bot on Binance Testnet (`live_main.py`),
with Telegram-based monitoring (`/status /pnl /stop`), persistent position-state tracking,
and a singleton process lock to prevent duplicate/orphaned instances.

## Methodology: independent dual-engine cross-validation

Rather than trusting a single backtest implementation, the funding-squeeze signal was
re-implemented twice, independently:

- `funding_squeeze_backtest.py` — iterative (loop-based)
- `funding_squeeze_v2_independent.py` — vectorised (pandas)

Comparing the two caught two real bugs before any capital (even paper capital) touched the
strategy:

1. A **fee-calculation bug**: the P&L formula was algebraically equivalent to deducting fees
   from equity, but the running equity update used pre-fee equity as its base — so entry
   fees were silently added back. Both engines had to agree on corrected numbers before the
   result was trusted.
2. A **data-alignment bug**: `merge_asof` matching funding events to price bars without a
   tolerance window caused ~365 early funding events to mismatch to prices months later.

Both bugs were invisible from the output of either engine alone — they only surfaced by
building a second, structurally different implementation and diffing the results.

## Other approaches tested (and rejected — documented, not hidden)

A rigorous "no" is still a result. All of the below were backtested to the same standard
and rejected on the evidence, not on intuition:

- **Trend-following pullback (15m/1H)** — Profit Factor 0.84; independently reproduced in
  TradingView Pine Script (1,788 trades, 9 years) with PF 0.81 — high agreement between two
  independent engines, which increases confidence the *negative* result is real.
- **HTF-bias + liquidity-sweep (Smart Money Concepts / ICT), tested across three variants**
  including a version rebuilt line-for-line from a proven MNQ futures ruleset — PF 0.64–0.85
  across every timeframe combination tested. Read together with `market_characteristics.py`
  (Hurst exponent ≈ 0.49–0.54 on BTC intraday — close to a random walk), the conclusion is
  that this class of strategy lacks a session-anchored liquidity structure to exploit in a
  24/7 market, not that the entry rules needed refinement.
- **Funding-rate market-neutral arbitrage** — measured carry too thin to trade (BTC ~1.3%
  annualised, ETH ~0.3%).
- **Simple signal comparison lab** (`btc_strategy_lab.html`) — an interactive tool comparing
  RSI, MACD, moving-average crossover, buy-the-dip, and DCA on 2014–2026 daily BTC data.

## Repository structure

| File(s) | Purpose |
|---|---|
| `funding_squeeze_backtest.py`, `funding_squeeze_v2_independent.py` | The validated strategy — two independent backtest engines |
| `live_*.py` | Live paper-trading system: data fetching, execution, position/PNL tracking, Telegram bot, singleton lock |
| `backtest_engine*.py`, `strategy_v*.py`, `run_backtest_v*.py` | Rejected approaches (trend-following, SMC/ICT variants) — kept for transparency |
| `market_characteristics.py` | Hurst exponent / efficiency-ratio analysis used to explain *why* certain approaches failed |
| `btc_strategy_lab.html` | Standalone interactive comparison of simple long-only strategies |
| `tests/` | pytest suite covering the live execution path (position state, PID locking, trade logging) |

## Tech stack

Python (pandas, NumPy), CCXT (Binance Spot + Futures), Telegram Bot API, pytest,
TradingView Pine Script (for independent cross-validation of the rejected approaches).

## Status & disclaimer

Live component runs in **paper trading only** on Binance Testnet — no real capital is at
risk. This is an independent research project, not investment advice.
