"""
Strategy V3:HTF bias(1D)+ sweep反手(4H)。
Sweep反手嘅邏輯同v2一模一樣,直接reuse strategy_v2.check_sweep_entry(冇改過
呢個function),淨係將bias、entry兩層時間刻度搬去market_characteristics.py
量到「有輕微trend persistence」嗰兩層(Hurst 1D=0.57、4H=0.54),對比v2嗰套
4H bias + 15m entry(15m Hurst≈0.5,接近random walk)。目的:分辨v2蝕錢係
因為sweep呢個做法本身唔work,定係因為entry嗰層時間刻度根本冇structure可捕捉。
"""
import pandas as pd

import config
import indicators as ind
from strategy_v2 import BULL, BEAR, NO_SIGNAL, LONG_ENTRY_SIGNAL, check_sweep_entry  # noqa: F401


def get_bias(close_1d: pd.Series) -> pd.Series:
    """向量化計算成條1D bias時間序列。"""
    ema = ind.ema(close_1d, config.BIAS_EMA_PERIOD_V3)
    is_bull = close_1d > ema
    return is_bull.map({True: BULL, False: BEAR})
