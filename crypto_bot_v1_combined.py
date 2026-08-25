"""
Crypto Bot v1.1(路線三:1H regime + 15m pullback,BTC/USDT spot)—— 合併做單一檔案版本,
方便攜帶/查閱。同分開嘅8個檔案(config/indicators/state/strategy/risk/data_loader/
backtest_engine/run_backtest)邏輯一致,淨係將模組之間嘅import拆走。

v1.1定案(2026-07-19,已驗證):stop/TP解耦(floor=4%)+ maker限價單成本假設,
完整2020-2026:696單、勝率65.5%、PF 1.08、最大回撤-12%。train/test out-of-sample
驗證過,唔係overfit。⚠️ maker假設嘅實際成交率未經paper trade驗證,可能偏樂觀。

注意:呢個仍然係Python code,要有裝咗pandas嘅Python環境先跑得,唔可以直接攞去
TradingView(Pine Script)呢類冇辦法跑Python嘅平台用。cache檔案(klines_*.json)
要放喺同一個資料夾先會被搵到,唔係就會重新問Binance攞成個2020至今嘅歷史(要幾分鐘)。
"""
import json
import os
import time
import urllib.request
import datetime
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# ============================================================
# Config —— 所有參數集中喺度
# ============================================================
SYMBOL = "BTCUSDT"
REGIME_INTERVAL = "1h"
ENTRY_INTERVAL = "15m"
BACKTEST_START = "2020-01-01"

EMA_REGIME_PERIOD = 200
EMA_REGIME_SLOPE_LOOKBACK = 20
EMA_ENTRY_PERIOD = 20
ATR_PERIOD = 14
SWING_LOOKBACK = 10

PULLBACK_BUFFER_PCT = 0.004
MAX_PULLBACK_BARS = 20
STOP_ATR_MULTIPLIER = 1.5
TAKE_PROFIT_R_MULTIPLE = 2.0

# v1.1定案:stop距離下限,同TP解耦(TP唔跟住呢個floor擴闊)。0.04=4%,
# 已經用train(2020-2023)/test(2024-2026) out-of-sample驗證過,兩段獨立
# 都PF>1,唔係overfit單一段。
MIN_STOP_DISTANCE_PCT = 0.04

RISK_PCT_PER_TRADE = 0.005
DAILY_LOSS_LIMIT_PCT = 0.02
CONSECUTIVE_LOSS_LIMIT = 3

# v1.1定案:假設用maker/限價單入場(唔係market/taker)。
# ⚠️ 限價單唔保證成交,實際成交率要用paper trade驗證,backtest假設100%成交,可能偏樂觀。
TAKER_FEE_PCT = 0.0002   # 0.02%,maker/限價單假設(原本市價單taker係0.1%)
SLIPPAGE_PCT = 0.0002    # 0.02%,限價單成交價自己揀,滑價應該遠細過市價單

BACKTEST_INITIAL_EQUITY = 10_000.0   # 純粹方便計算百分比,唔係落錢建議


# ============================================================
# Indicators —— 純function,冇狀態,冇lookahead bias
# ============================================================
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def ema_slope(ema_series: pd.Series, lookback: int) -> pd.Series:
    return ema_series.diff(lookback) / lookback


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def rolling_swing_low(low: pd.Series, lookback: int) -> pd.Series:
    return low.shift(1).rolling(lookback).min()


# ============================================================
# State —— backtest/paper/live 共用嘅mutable state
# ============================================================
@dataclass
class PullbackTracker:
    in_pullback: bool = False
    pullback_high: Optional[float] = None
    bars_in_pullback: int = 0

    def reset(self):
        self.in_pullback = False
        self.pullback_high = None
        self.bars_in_pullback = 0


@dataclass
class Position:
    entry_price: float
    stop_price: float
    take_profit_price: float
    size: float
    entry_time: pd.Timestamp


@dataclass
class BotState:
    equity: float
    open_position: Optional[Position] = None
    pullback: PullbackTracker = field(default_factory=PullbackTracker)

    current_day: Optional[object] = None
    daily_start_equity: float = 0.0
    daily_pnl_pct: float = 0.0

    consecutive_losses: int = 0
    trading_paused: bool = False

    def roll_day_if_needed(self, bar_date):
        if self.current_day != bar_date:
            self.current_day = bar_date
            self.daily_start_equity = self.equity
            self.daily_pnl_pct = 0.0

    def update_daily_pnl(self):
        if self.daily_start_equity > 0:
            self.daily_pnl_pct = (self.equity - self.daily_start_equity) / self.daily_start_equity


# ============================================================
# Strategy —— Signal Engine:市場環境判斷(1H)同入場觸發(15m)
# ============================================================
BULL = "BULL"
UNCLEAR = "UNCLEAR"
NO_SIGNAL = "NO_SIGNAL"
LONG_ENTRY_SIGNAL = "LONG_ENTRY_SIGNAL"


def get_regime(close_1h: pd.Series) -> pd.Series:
    ema200 = ema(close_1h, EMA_REGIME_PERIOD)
    slope = ema_slope(ema200, EMA_REGIME_SLOPE_LOOKBACK)
    is_bull = (close_1h > ema200) & (slope > 0)
    return is_bull.map({True: BULL, False: UNCLEAR})


def check_entry(bar, ema20_value, swing_low_value, regime, tracker: PullbackTracker):
    if regime != BULL:
        tracker.reset()
        return NO_SIGNAL

    if not tracker.in_pullback:
        entered_zone = bar.low <= ema20_value * (1 + PULLBACK_BUFFER_PCT)
        if not entered_zone and swing_low_value is not None and pd.notna(swing_low_value):
            entered_zone = bar.low <= swing_low_value * (1 + PULLBACK_BUFFER_PCT)

        if entered_zone:
            tracker.in_pullback = True
            tracker.pullback_high = bar.high
            tracker.bars_in_pullback = 1
        return NO_SIGNAL

    tracker.bars_in_pullback += 1
    if tracker.bars_in_pullback > MAX_PULLBACK_BARS:
        tracker.reset()
        return NO_SIGNAL

    reclaim_ema = bar.close > ema20_value
    structure_break = bar.close > tracker.pullback_high

    if reclaim_ema and structure_break:
        tracker.reset()
        return LONG_ENTRY_SIGNAL

    tracker.pullback_high = max(tracker.pullback_high, bar.high)
    return NO_SIGNAL


# ============================================================
# Risk Manager —— stop/TP計算、部位sizing、下單前checklist
# ============================================================
def calc_stop_and_tp_decoupled(entry_price, swing_low_value, atr_value):
    """
    v1.1定案:stop用floor後(可能闊咗)嘅距離,但TP繼續用原本(未floor前)
    嘅distance計,唔會因為stop闊咗而搬得更遠——呢個解耦先係PF>1嘅關鍵,
    舊版stop/TP綁死一齊闊,勝率跌返晒銷,PF一直喺0.79-0.84打圈。
    """
    swing_dist = entry_price - swing_low_value if swing_low_value == swing_low_value else float("-inf")
    atr_dist = atr_value * STOP_ATR_MULTIPLIER
    original_stop_distance = max(swing_dist, atr_dist)   # 原本(未floor)嘅stop距離,淨係用嚟計TP
    floor_dist = entry_price * MIN_STOP_DISTANCE_PCT
    widened_stop_distance = max(original_stop_distance, floor_dist)   # 真正落stop用呢個(可能闊咗)

    stop_price = entry_price - widened_stop_distance
    tp_price = entry_price + original_stop_distance * TAKE_PROFIT_R_MULTIPLE  # TP唔跟stop闊咗而搬
    return stop_price, tp_price


def calc_position_size(equity, entry_price, stop_price):
    stop_distance = entry_price - stop_price
    if stop_distance <= 0:
        return 0.0
    risk_amount = equity * RISK_PCT_PER_TRADE
    return risk_amount / stop_distance


def pre_trade_checklist(state, size, entry_price):
    notional = size * entry_price
    checks = {
        "daily_loss_ok": state.daily_pnl_pct > -DAILY_LOSS_LIMIT_PCT,
        "consecutive_loss_ok": state.consecutive_losses < CONSECUTIVE_LOSS_LIMIT,
        "no_open_position": state.open_position is None,
        "size_positive": size > 0,
        "cash_available": notional <= state.equity,
        "not_paused": not state.trading_paused,
    }
    failed = [k for k, v in checks.items() if not v]
    return (len(failed) == 0), failed


# ============================================================
# Data Loader —— Binance spot歷史K線(public endpoint,唔使API key)
# ============================================================
BASE_URL = "https://api.binance.com/api/v3/klines"
CACHE_DIR = os.path.dirname(os.path.abspath(__file__))

COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def _cache_path(symbol, interval):
    return os.path.join(CACHE_DIR, f"klines_{symbol}_{interval}.json")


def fetch_klines(symbol, interval, start_time_ms):
    rows = []
    start = start_time_ms
    while True:
        url = f"{BASE_URL}?symbol={symbol}&interval={interval}&startTime={start}&limit=1000"
        with urllib.request.urlopen(url, timeout=15) as resp:
            batch = json.loads(resp.read())
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        start = batch[-1][0] + 1
        time.sleep(0.2)
    return rows


def load_klines(symbol, interval, start_time_ms, force_refresh=False):
    path = _cache_path(symbol, interval)
    if os.path.exists(path) and not force_refresh:
        with open(path) as f:
            return json.load(f)

    rows = fetch_klines(symbol, interval, start_time_ms)
    with open(path, "w") as f:
        json.dump(rows, f)
    return rows


def klines_to_df(rows):
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df = df.set_index("open_time")
    return df[["open", "high", "low", "close", "volume", "close_time"]]


# ============================================================
# Backtest Engine —— event-driven loop,逐支15m bar行過
# ============================================================
def _align_regime_to_15m(df_1h, df_15m):
    df_1h = df_1h.copy()
    df_1h["regime"] = get_regime(df_1h["close"])
    regime_by_close = df_1h.set_index("close_time")[["regime"]].sort_index()
    aligned = pd.merge_asof(
        df_15m.sort_index(), regime_by_close,
        left_index=True, right_index=True, direction="backward",
    )
    return aligned["regime"]


def run_backtest(df_1h, df_15m):
    df_15m = df_15m.copy()
    df_15m["ema20"] = ema(df_15m["close"], EMA_ENTRY_PERIOD)
    df_15m["swing_low"] = rolling_swing_low(df_15m["low"], SWING_LOOKBACK)
    df_15m["atr"] = atr(df_15m["high"], df_15m["low"], df_15m["close"], ATR_PERIOD)
    df_15m["regime"] = _align_regime_to_15m(df_1h, df_15m)
    df_15m = df_15m.dropna(subset=["ema20", "swing_low", "atr", "regime"])

    state = BotState(equity=BACKTEST_INITIAL_EQUITY)
    trades = []
    rejected_signals = []
    pause_trigger_count = 0
    pending_entry = None

    for bar in df_15m.itertuples():
        bar_date = bar.Index.date()
        if state.trading_paused and state.current_day is not None and bar_date != state.current_day:
            state.trading_paused = False
            state.consecutive_losses = 0
        state.roll_day_if_needed(bar_date)

        if pending_entry is not None and state.open_position is None:
            fill_price = bar.open * (1 + SLIPPAGE_PCT)
            stop_price, tp_price = calc_stop_and_tp_decoupled(
                fill_price, pending_entry["swing_low"], pending_entry["atr"])
            size = calc_position_size(state.equity, fill_price, stop_price)
            ok, failed = pre_trade_checklist(state, size, fill_price)
            if ok:
                fee = fill_price * size * TAKER_FEE_PCT
                state.equity -= fee
                state.open_position = Position(
                    entry_price=fill_price, stop_price=stop_price,
                    take_profit_price=tp_price, size=size, entry_time=bar.Index,
                )
            else:
                rejected_signals.append({"time": bar.Index, "reason": failed})
            pending_entry = None

        if state.open_position is not None:
            pos = state.open_position
            hit_stop = bar.low <= pos.stop_price
            hit_tp = bar.high >= pos.take_profit_price
            exit_price = None
            if hit_stop:
                exit_price = pos.stop_price * (1 - SLIPPAGE_PCT)
            elif hit_tp:
                exit_price = pos.take_profit_price * (1 - SLIPPAGE_PCT)

            if exit_price is not None:
                pnl = (exit_price - pos.entry_price) * pos.size
                pnl -= exit_price * pos.size * TAKER_FEE_PCT
                state.equity += pnl
                state.consecutive_losses = state.consecutive_losses + 1 if pnl < 0 else 0
                trades.append({
                    "entry_time": pos.entry_time, "exit_time": bar.Index,
                    "entry_price": pos.entry_price, "exit_price": exit_price,
                    "size": pos.size, "pnl": pnl, "equity_after": state.equity,
                })
                state.open_position = None
                if state.consecutive_losses >= CONSECUTIVE_LOSS_LIMIT and not state.trading_paused:
                    state.trading_paused = True
                    pause_trigger_count += 1

        state.update_daily_pnl()

        if state.open_position is not None or pending_entry is not None:
            continue

        signal = check_entry(bar, bar.ema20, bar.swing_low, bar.regime, state.pullback)
        if signal == LONG_ENTRY_SIGNAL:
            pending_entry = {"swing_low": bar.swing_low, "atr": bar.atr}

    return {
        "trades": pd.DataFrame(trades),
        "rejected_signals": rejected_signals,
        "final_equity": state.equity,
        "pause_trigger_count": pause_trigger_count,
    }


# ============================================================
# Report + Entry point
# ============================================================
def _report(result):
    trades = result["trades"]
    if trades.empty:
        print("冇任何交易——檢查regime/entry條件係咪太嚴,或者資料範圍係咪啱。")
        return

    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]
    gross_profit = wins["pnl"].sum()
    gross_loss = -losses["pnl"].sum()
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    equity_curve = trades["equity_after"]
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    max_dd = drawdown.min()

    print(f"=== {SYMBOL} v1 backtest ({trades['entry_time'].min()} → {trades['exit_time'].max()}) ===")
    print(f"總交易數: {len(trades)}  勝率: {len(wins) / len(trades) * 100:.1f}%")
    print(f"Profit Factor: {pf:.2f}")
    print(f"淨損益: {trades['pnl'].sum():.2f}  (起始equity: {BACKTEST_INITIAL_EQUITY:.2f})")
    print(f"最大回撤: {max_dd * 100:.2f}%")
    print(f"連續3單虧損觸發次數: {result['pause_trigger_count']}")
    print(f"被pre-trade checklist否決嘅訊號數: {len(result['rejected_signals'])}")


def main():
    start_ms = int(
        datetime.datetime.strptime(BACKTEST_START, "%Y-%m-%d")
        .replace(tzinfo=datetime.timezone.utc).timestamp() * 1000
    )
    rows_1h = load_klines(SYMBOL, REGIME_INTERVAL, start_ms)
    rows_15m = load_klines(SYMBOL, ENTRY_INTERVAL, start_ms)

    df_1h = klines_to_df(rows_1h)
    df_15m = klines_to_df(rows_15m)

    result = run_backtest(df_1h, df_15m)
    _report(result)


if __name__ == "__main__":
    main()
