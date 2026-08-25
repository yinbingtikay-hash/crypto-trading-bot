"""Funding Squeeze 訊號計算。

⚠️ 呢個 z-score 公式必須同 `funding_squeeze_v2_independent.py` 嘅 add_zscore()
保持完全一致（rolling mean/std），唔可以自己另外諗一套——嗰個先係經雙 engine
驗證過嘅版本，呢度淨係將 Z_WINDOW 改做參數化（等 live 版可以用 .env 調），
數學上要同v2一模一樣，否則 live 同 backtest 嘅邏輯會漂移。
"""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SqueezeSignal:
    z_score: float
    funding_rate: float
    funding_time: int  # unix 秒


def add_zscore(df: pd.DataFrame, z_window: int) -> pd.DataFrame:
    df = df.copy()
    roll = df["rate"].rolling(z_window, min_periods=z_window)
    df["z"] = (df["rate"] - roll.mean()) / roll.std()
    return df


def get_latest_signal(df_with_z: pd.DataFrame, z_threshold: float) -> SqueezeSignal | None:
    """睇最新一個 funding 事件嘅 z-score，跌穿 threshold 先算訊號。"""
    if df_with_z.empty:
        return None
    latest = df_with_z.iloc[-1]
    if pd.isna(latest["z"]) or latest["z"] >= z_threshold:
        return None
    return SqueezeSignal(
        z_score=float(latest["z"]), funding_rate=float(latest["rate"]), funding_time=int(latest["t"])
    )
