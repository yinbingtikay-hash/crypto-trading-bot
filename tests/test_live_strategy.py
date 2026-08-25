"""驗證 live_strategy.py：z-score 公式要同 funding_squeeze_v2_independent.py
嘅 add_zscore() 數學上完全一致（避免live/backtest邏輯漂移），同埋訊號判斷邏輯啱唔啱。
"""

import numpy as np
import pandas as pd

import funding_squeeze_v2_independent as v2
from live_strategy import add_zscore, get_latest_signal


def make_df(n=600, seed=1):
    rng = np.random.default_rng(seed)
    rates = rng.normal(0.0001, 0.0003, n)
    t = np.arange(n) * 28800  # 8小時一粒
    return pd.DataFrame({"t": t, "rate": rates})


def test_add_zscore_matches_v2_engine_exactly():
    """數學公式一定要同已驗證嘅v2 engine一致，唔可以自己漂移咗。"""
    df = make_df()

    live_result = add_zscore(df, z_window=540)

    v2_module_window = v2.Z_WINDOW
    v2.Z_WINDOW = 540  # 對齊v2 module常數，確保比較公平
    try:
        v2_result = v2.add_zscore(df)
    finally:
        v2.Z_WINDOW = v2_module_window

    pd.testing.assert_series_equal(live_result["z"], v2_result["z"], check_names=False)


def test_get_latest_signal_returns_none_when_z_above_threshold():
    df = pd.DataFrame({"t": [1, 2, 3], "rate": [0.0001, 0.0001, 0.0001], "z": [np.nan, 0.5, -1.0]})
    assert get_latest_signal(df, z_threshold=-2.0) is None


def test_get_latest_signal_detects_signal_below_threshold():
    df = pd.DataFrame({"t": [1, 2, 3], "rate": [0.0001, 0.0001, -0.0005], "z": [np.nan, 0.5, -2.5]})
    signal = get_latest_signal(df, z_threshold=-2.0)
    assert signal is not None
    assert signal.z_score == -2.5
    assert signal.funding_time == 3


def test_get_latest_signal_ignores_nan_z():
    df = pd.DataFrame({"t": [1], "rate": [0.0001], "z": [np.nan]})
    assert get_latest_signal(df, z_threshold=-2.0) is None


def test_get_latest_signal_returns_none_on_empty_df():
    df = pd.DataFrame({"t": [], "rate": [], "z": []})
    assert get_latest_signal(df, z_threshold=-2.0) is None
