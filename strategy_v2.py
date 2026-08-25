"""
Strategy V2:HTF bias(4H)+ sweep反手(15m)。
跟你MNQ SMC Sweep+Structure嘅邏輯:HTF定方向 → sweep流動性(逆住bias嘅方向) →
break返sweep bar嘅高位(順返bias方向)先入場。因為呢條線spot-only,冧唔到,
所以淨係做bias睇好嗰種setup(sweep低位再反手向上),bias睇淡就淨係唔交易,
唔會開short。
"""
import pandas as pd

import config
import indicators as ind
from state import SweepTracker

BULL = "BULL"
BEAR = "BEAR"

NO_SIGNAL = "NO_SIGNAL"
LONG_ENTRY_SIGNAL = "LONG_ENTRY_SIGNAL"


def get_bias(close_4h: pd.Series) -> pd.Series:
    """向量化計算成條4H bias時間序列。"""
    ema = ind.ema(close_4h, config.BIAS_EMA_PERIOD_V2)
    is_bull = close_4h > ema
    return is_bull.map({True: BULL, False: BEAR})


def check_sweep_entry(bar, swing_low_value, bias, tracker: SweepTracker):
    """
    逐bar調用。bias已經由外面對齊到呢支15m bar嘅時間點(唔可以lookahead)。
    Bias=BEAR就完全唔理(spot冧唔到,冇得做)。

    Returns (signal, sweep_low_at_trigger)——sweep_low要響tracker.reset()之前
    攞出嚟,唔係就俾call嘅嗰邊攞唔返個sweep低位(reset咗就變返None)。
    """
    if bias != BULL:
        tracker.reset()
        return NO_SIGNAL, None

    if not tracker.in_sweep:
        if swing_low_value is not None and pd.notna(swing_low_value) and bar.low < swing_low_value:
            tracker.in_sweep = True
            tracker.sweep_high = bar.high
            tracker.sweep_low = bar.low
            tracker.bars_since_sweep = 1
        return NO_SIGNAL, None

    tracker.bars_since_sweep += 1
    if tracker.bars_since_sweep > config.MAX_SWEEP_BARS_V2:
        tracker.reset()
        return NO_SIGNAL, None

    if bar.close > tracker.sweep_high:
        sweep_low_at_trigger = tracker.sweep_low
        tracker.reset()
        return LONG_ENTRY_SIGNAL, sweep_low_at_trigger

    if bar.low < tracker.sweep_low:
        tracker.sweep_low = bar.low
        tracker.sweep_high = max(tracker.sweep_high, bar.high)

    return NO_SIGNAL, None
