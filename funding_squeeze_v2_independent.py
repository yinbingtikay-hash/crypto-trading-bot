"""
Funding Squeeze Long —— 獨立第二個engine,用嚟cross-check funding_squeeze_backtest.py
(下面叫「v1」)嘅結果係咪真,唔係code啱啱好啱先做出嚟嘅假象。

刻意用同v1唔同嘅寫法(vectorized/pandas為主,唔用v1嗰種逐個bar走嘅while loop),
等兩份code之間冇乜「抄」嘅空間,先至有cross-check嘅意義。策略定義(rolling
z-score、極端負先開long、持固定期數、non-overlapping)同v1一樣——呢個唔係新
策略,係同一個策略嘅第二次獨立實作。
"""
import json

import numpy as np
import pandas as pd

SYMBOL = "BTCUSDT"
INITIAL_CAPITAL = 10_000.0
FEE = 0.001
SLIP = 0.0005
Z_WINDOW = 540


def load_funding_and_price():
    with open(f"funding_history_{SYMBOL}.json") as f:
        funding_raw = json.load(f)
    with open(f"klines_{SYMBOL}_1h.json") as f:
        klines_raw = json.load(f)

    funding = pd.DataFrame(funding_raw)
    funding["t"] = funding["fundingTime"].astype(np.int64) // 1000
    funding["rate"] = funding["fundingRate"].astype(float)
    funding = funding[["t", "rate"]].sort_values("t").reset_index(drop=True)

    hourly_close = pd.Series(
        {int(k[0]) // 1000: float(k[4]) for k in klines_raw}
    ).sort_index()
    hourly_low = pd.Series(
        {int(k[0]) // 1000: float(k[3]) for k in klines_raw}
    ).sort_index()

    # 用merge_asof搵返每個funding event嗰刻(向下取整到嗰個鐘頭)最接近嘅收市價,
    # 同v1嘅price_at()目的一樣,但用pandas內建function做,寫法完全唔同。
    #
    # Bug fix(第一版冇設tolerance,搵到咗):funding數據2019-09就開始,但K線
    # 2020-01先有——冇tolerance嘅merge_asof(nearest)會將啲搵唔到啱價位嘅早期
    # funding event,亂咁配對去最近嘅一個(可以相差成幾個月),整咗~365粒假event
    # 出嚟,搞到v2嘅trade數同v1對唔上。而家加返6小時tolerance,搵唔到就係na,
    # 跟住dropna()掉,行為先同v1嘅price_at()(±6小時窗口搵唔到就skip)一致。
    hourly_df = pd.DataFrame({"hour_ts": hourly_close.index, "price": hourly_close.values})
    funding["hour_ts"] = (funding["t"] // 3600) * 3600
    merged = pd.merge_asof(
        funding.sort_values("hour_ts"), hourly_df.sort_values("hour_ts"),
        on="hour_ts", direction="nearest", tolerance=6 * 3600,
    ).sort_values("t").reset_index(drop=True)

    return merged[["t", "rate", "price"]].dropna().reset_index(drop=True), hourly_low


def add_zscore(df):
    df = df.copy()
    roll = df["rate"].rolling(Z_WINDOW, min_periods=Z_WINDOW)
    df["z"] = (df["rate"] - roll.mean()) / roll.std()
    return df


def select_non_overlapping_trades(df, z_threshold, hold_periods):
    """揀晒符合z<threshold嘅候選bar,再greedy咁揀啱啲唔重疊嘅——同v1「一個大
    while loop逐bar走、觸發就跳去exit_idx之後」嘅寫法唔同,呢度分開做兩步:
    先vectorized搵晒全部候選,再用一個簡單loop淨係做「揀選」(唔負責計錢)。"""
    n = len(df)
    candidates = np.where(df["z"].values < z_threshold)[0]

    selected = []
    next_available_idx = 0
    for sig_idx in candidates:
        entry_idx = sig_idx + 1
        exit_idx = entry_idx + hold_periods
        if entry_idx < next_available_idx:
            continue
        if exit_idx >= n:
            continue
        selected.append((entry_idx, exit_idx))
        next_available_idx = exit_idx + 1

    return selected


def compute_trades(df, entry_exit_pairs):
    """Vectorized計每筆單嘅return——用「proceeds直接算」,唔用加減式pnl,
    刻意避開v1嗰個bug類型(entry fee喺equity update度冇真正扣到)。"""
    cols = ["entry_t", "exit_t", "entry_z", "entry_px", "exit_px", "ret_mult", "pnl_pct"]
    if not entry_exit_pairs:
        return pd.DataFrame(columns=cols)

    entry_idx = np.array([p[0] for p in entry_exit_pairs])
    exit_idx = np.array([p[1] for p in entry_exit_pairs])

    entry_px = df["price"].values[entry_idx] * (1 + SLIP)
    exit_px = df["price"].values[exit_idx] * (1 - SLIP)

    # 一蚊錢買入(1-FEE)嘅倉,賣出再收(1-FEE)——嚟回總共兩次fee,乘埋一齊。
    ret_mult = (1 - FEE) * (exit_px / entry_px) * (1 - FEE)

    trades = pd.DataFrame({
        "entry_t": df["t"].values[entry_idx],
        "exit_t": df["t"].values[exit_idx],
        "entry_z": df["z"].values[entry_idx - 1],  # 訊號嗰粒bar,唔係entry粒
        "entry_px": entry_px,
        "exit_px": exit_px,
        "ret_mult": ret_mult,
        "pnl_pct": ret_mult - 1,
    })
    return trades


def apply_stop_loss(trades, hourly_low, stop_loss_pct):
    """幫每筆trade check持倉期間(entry_t~exit_t)有冇跌穿stop_price。同v1嘅
    「逐個鐘頭while loop」寫法唔同：呢度用pandas range-select(布林篩選)攞返
    低位序列，第一個符合條件嘅index就係第一次觸及嘅時間——冇顯式loop走鐘頭，
    改用per-trade嘅向量化篩選（trade數量本身少，逐筆trade處理反而更清晰）。"""
    trades = trades.copy()
    if stop_loss_pct is None or trades.empty:
        trades["exit_reason"] = "TIME"
        return trades

    exit_reason, new_exit_t, new_exit_px = [], [], []
    for row in trades.itertuples():
        stop_price = row.entry_px * (1 - stop_loss_pct)
        window = hourly_low[(hourly_low.index > row.entry_t) & (hourly_low.index <= row.exit_t)]
        touches = window[window <= stop_price]
        if len(touches) > 0:
            exit_reason.append("STOP")
            new_exit_t.append(touches.index[0])
            new_exit_px.append(stop_price * (1 - SLIP))
        else:
            exit_reason.append("TIME")
            new_exit_t.append(row.exit_t)
            new_exit_px.append(row.exit_px)

    trades["exit_reason"] = exit_reason
    trades["exit_t"] = new_exit_t
    trades["exit_px"] = new_exit_px
    trades["ret_mult"] = (1 - FEE) * (trades["exit_px"] / trades["entry_px"]) * (1 - FEE)
    trades["pnl_pct"] = trades["ret_mult"] - 1
    return trades


def apply_compounding(trades, initial_capital=INITIAL_CAPITAL):
    trades = trades.copy()
    trades["equity_after"] = initial_capital * trades["ret_mult"].cumprod()
    trades["pnl"] = trades["equity_after"] - trades["equity_after"].shift(1).fillna(initial_capital)
    return trades


def run(z_threshold, hold_periods, df=None, hourly_low=None, stop_loss_pct=None):
    if df is None:
        raw_df, hourly_low = load_funding_and_price()
        df = add_zscore(raw_df)
    pairs = select_non_overlapping_trades(df, z_threshold, hold_periods)
    trades = compute_trades(df, pairs)
    trades = apply_stop_loss(trades, hourly_low, stop_loss_pct)
    trades = apply_compounding(trades)
    return trades


def summarize(trades, label=""):
    if trades.empty:
        print(f"{label}: 冇交易")
        return
    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]
    gp = wins["pnl"].sum()
    gl = -losses["pnl"].sum()
    pf = gp / gl if gl > 0 else float("inf")
    eq = trades["equity_after"]
    dd = ((eq - eq.cummax()) / eq.cummax()).min()
    stop_n = (trades["exit_reason"] == "STOP").sum() if "exit_reason" in trades else 0
    print(f"{label}: n={len(trades):3d}  PF={pf:5.2f}  win%={len(wins)/len(trades)*100:5.1f}  "
          f"net={trades['pnl'].sum():9.2f}  maxDD={dd*100:6.2f}%  止損離場={stop_n}")


if __name__ == "__main__":
    raw_df, hourly_low = load_funding_and_price()
    df = add_zscore(raw_df)
    print(f"funding事件: {len(df)}, warmup後可用: {df['z'].notna().sum()}")
    print()
    print("=== 獨立v2 engine 結果（冇止損） ===")
    for z_th, hold in [(-1.5, 6), (-2.0, 6), (-2.0, 9), (-1.5, 9)]:
        trades = run(z_th, hold, df)
        summarize(trades, f"z<{z_th} hold={hold}")

    print()
    print("=== 加止損網格（z<-2.0 hold=6，同v1測嘅組合一致） ===")
    for sl in [0.02, 0.03, 0.05, 0.08]:
        trades = run(-2.0, 6, df, hourly_low=hourly_low, stop_loss_pct=sl)
        summarize(trades, f"止損{sl:.0%}")
