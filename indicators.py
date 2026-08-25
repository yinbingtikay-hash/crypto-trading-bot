"""純指標function——冇狀態、冇lookahead bias。"""
import pandas as pd


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
    # shift(1) 排除當前bar本身,避免用未收埋嘅bar計自己嘅support
    return low.shift(1).rolling(lookback).min()


def pivot_high(high: pd.Series, left: int, right: int) -> pd.Series:
    """對應Pine嘅ta.pivothigh(left,right)。值擺喺*確認嗰刻*(即係pivot bar之後
    right期),唔係擺喺pivot bar本身——call嘅嗰邊唔使自己再shift,直接用就係
    避免咗lookahead嘅版本。"""
    n = len(high)
    vals = high.values
    raw = pd.Series(float("nan"), index=high.index)
    for i in range(left, n - right):
        window = vals[i - left:i + right + 1]
        center = vals[i]
        if center == window.max() and (window == center).sum() == 1:
            raw.iloc[i] = center
    return raw.shift(right)


def pivot_low(low: pd.Series, left: int, right: int) -> pd.Series:
    """對應Pine嘅ta.pivotlow(left,right)。同pivot_high一樣,值已經擺喺確認嗰刻。"""
    n = len(low)
    vals = low.values
    raw = pd.Series(float("nan"), index=low.index)
    for i in range(left, n - right):
        window = vals[i - left:i + right + 1]
        center = vals[i]
        if center == window.min() and (window == center).sum() == 1:
            raw.iloc[i] = center
    return raw.shift(right)
