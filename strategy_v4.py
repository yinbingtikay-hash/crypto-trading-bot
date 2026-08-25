"""
Strategy V4:忠實跟返用戶MNQ「SMC Sweep+Structure v3.3」嘅實際規則(佢貼咗真code
出嚟先寫得到呢個版本),同Paradigm B/C(strategy_v2/v3)個分別:

1. HTF bias:swing structure(HL/LH,對應v3.3 f_bias非strict模式)——唔係EMA filter。
2. Swing點:真正pivot high/low(兩邊都要確認),唔係rolling N期低位。
3. 入場trigger:破位嗰支bar自己都要係方向燭(close vs open),唔淨止破位。
4. Stop太緊淨係skip呢張單,唔會擴闊。

因為spot-only,淨係做v3.3嘅long側(bias=bull先開倉)。Position sizing繼續用
%equity(v1/v2/v3嗰套),冇跟v3.3嘅fixed-$ risk_per_contract——嗰個係futures
contract特有嘅sizing方式,BTC冇「幾多點值幾多錢」呢個概念,唔係湊唔齊,係
資產類別本身唔啱用嗰套。
"""
import pandas as pd

import indicators as ind

BULL, BEAR, NEUTRAL = "BULL", "BEAR", "NEUTRAL"
NO_SIGNAL = "NO_SIGNAL"
LONG_ENTRY_SIGNAL = "LONG_ENTRY_SIGNAL"


def structural_bias(high: pd.Series, low: pd.Series, piv_left=2, piv_right=2, strict=False) -> pd.Series:
    """對應v3.3 f_bias(strictBias)。非strict(v3.3預設):HL(最新swing low >
    上一個swing low)就係bull,LH就係bear。Strict要HH+HL/LH+LL都成立。"""
    ph = ind.pivot_high(high, piv_left, piv_right)
    pl = ind.pivot_low(low, piv_left, piv_right)
    n = len(high)
    out = [NEUTRAL] * n
    lsh = psh = lsl = psl = float("nan")
    for i in range(n):
        if pd.notna(ph.iloc[i]):
            psh, lsh = lsh, ph.iloc[i]
        if pd.notna(pl.iloc[i]):
            psl, lsl = lsl, pl.iloc[i]
        if strict:
            bull = pd.notna(psh) and pd.notna(psl) and lsh > psh and lsl > psl
            bear = pd.notna(psh) and pd.notna(psl) and lsh < psh and lsl < psl
        else:
            bull = pd.notna(psl) and lsl > psl
            bear = pd.notna(psh) and lsh < psh
        out[i] = BULL if bull else (BEAR if bear else NEUTRAL)
    return pd.Series(out, index=high.index)


def find_long_entries(df: pd.DataFrame, bias: pd.Series, piv_len=3, conf_window=12):
    """df要有open/high/low/close,index已經sort好。bias已經對齊到呢個timeframe
    (只用完全收咗嘅HTF bar,同backtest_engine_v2/v3同一套merge_asof做法)。
    Returns list of dict: {i, swept_low} —— i係trigger確認嗰支bar,下一支bar
    先開倉(執行時機交返backtest engine決定,呢度淨係產生訊號)。"""
    pl = ind.pivot_low(df["low"], piv_len, piv_len)
    opens, highs, lows, closes = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    n = len(df)

    entries = []
    last_sl = float("nan")
    armed, arm_bar, swept_low, swept_high_at_sweep = False, None, float("nan"), float("nan")

    for i in range(n):
        if pd.notna(pl.iloc[i]):
            last_sl = pl.iloc[i]

        sweep_low = pd.notna(last_sl) and lows[i] < last_sl and closes[i] > last_sl
        if sweep_low:
            armed, arm_bar = True, i
            swept_low, swept_high_at_sweep = lows[i], highs[i]

        if armed and (i - arm_bar) > conf_window:
            armed = False

        if armed and bias.iloc[i] == BULL:
            broke = closes[i] > swept_high_at_sweep and closes[i] > opens[i]
            if broke:
                entries.append({"i": i, "swept_low": swept_low})
                armed = False

    return entries
