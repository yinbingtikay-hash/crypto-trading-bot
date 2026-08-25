"""
Signal Engine:市場環境判斷(1H)同入場觸發(15m)。
純訊號邏輯,唔負責部位大小/風控——嗰啲交俾 risk.py。
"""
import pandas as pd

import config
import indicators as ind
from state import PullbackTracker

BULL = "BULL"
UNCLEAR = "UNCLEAR"

NO_SIGNAL = "NO_SIGNAL"
LONG_ENTRY_SIGNAL = "LONG_ENTRY_SIGNAL"


def get_regime(close_1h: pd.Series) -> pd.Series:
    """向量化計算成條1H regime時間序列。"""
    ema200 = ind.ema(close_1h, config.EMA_REGIME_PERIOD)
    slope = ind.ema_slope(ema200, config.EMA_REGIME_SLOPE_LOOKBACK)
    is_bull = (close_1h > ema200) & (slope > 0)
    return is_bull.map({True: BULL, False: UNCLEAR})


def check_entry(bar, ema20_value, swing_low_value, regime, tracker: PullbackTracker):
    """逐bar調用。regime 已經由外面對齊到呢支15m bar嘅時間點(唔可以lookahead)。"""
    if regime != BULL:
        tracker.reset()
        return NO_SIGNAL

    if not tracker.in_pullback:
        entered_zone = bar.low <= ema20_value * (1 + config.PULLBACK_BUFFER_PCT)
        if not entered_zone and swing_low_value is not None and pd.notna(swing_low_value):
            entered_zone = bar.low <= swing_low_value * (1 + config.PULLBACK_BUFFER_PCT)

        if entered_zone:
            tracker.in_pullback = True
            tracker.pullback_high = bar.high
            tracker.bars_in_pullback = 1
        return NO_SIGNAL

    tracker.bars_in_pullback += 1
    if tracker.bars_in_pullback > config.MAX_PULLBACK_BARS:
        tracker.reset()
        return NO_SIGNAL

    reclaim_ema = bar.close > ema20_value
    structure_break = bar.close > tracker.pullback_high   # 用觸發前已記錄嘅high,唔包括今支bar

    if reclaim_ema and structure_break:
        tracker.reset()
        return LONG_ENTRY_SIGNAL

    tracker.pullback_high = max(tracker.pullback_high, bar.high)
    return NO_SIGNAL
