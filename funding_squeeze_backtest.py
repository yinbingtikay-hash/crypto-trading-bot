"""
Funding Squeeze Long —— spot-only、短期。
概念同路線二(market-neutral套利)唔同源:唔靠賺funding本身,而係將funding
rate當「槓桿擁擠度」訊號——rolling z-score跌到極端負(即係好多人開槓桿造空、
容易軋倉反彈),先開long。訊號用一個8h funding事件嘅rate計,執行擺喺*下一個*
funding事件嗰刻(避免同一時點用未來資訊),持有固定期數後平倉,一次淨係一張倉
(避免overlapping trade逼大個樣本)。

前置exploratory check(見對話):bottom 2% funding事件,平均24h forward return
+1.81%、72h +2.97%,遠超全樣本平均(+0.14%/+0.42%),而且愈極端效應愈強——但
嗰個係overlapping event-study,呢度先係真正quantify做non-overlapping trade
之後仲剩返幾多。
"""
import json

import numpy as np
import pandas as pd

SYMBOL = "BTCUSDT"
INITIAL_CAPITAL = 10_000.0
FEE = 0.001
SLIP = 0.0005

Z_WINDOW = 540          # 180日 * 3(每日3次funding),rolling mean/std嘅回望期
Z_ENTRY_THRESHOLD = -2.0  # funding z-score跌穿呢個先入場
HOLD_PERIODS = 9        # 9 * 8h = 3日,對應exploratory check嗰個72h窗口


def load_data(symbol=None):
    symbol = symbol or SYMBOL
    with open(f"funding_history_{symbol}.json") as f:
        funding = json.load(f)
    with open(f"klines_{symbol}_1h.json") as f:
        klines = json.load(f)
    price_by_hour = {int(k[0]) // 1000: float(k[4]) for k in klines}
    low_by_hour = {int(k[0]) // 1000: float(k[3]) for k in klines}
    return funding, price_by_hour, low_by_hour


def price_at(price_by_hour, ts_seconds):
    h = (ts_seconds // 3600) * 3600
    for offset in range(6):
        if h + offset * 3600 in price_by_hour:
            return price_by_hour[h + offset * 3600]
        if h - offset * 3600 in price_by_hour:
            return price_by_hour[h - offset * 3600]
    return None


def find_stop_hit(low_by_hour, entry_t, exit_t, stop_price):
    """逐個鐘頭check低位有冇跌穿stop_price，由entry_t（唔含）到exit_t（含）。
    搵到就回傳(hit=True, hit_ts)，用第一個觸及嘅鐘做離場時間；冇搵到就
    (False, None)，交返原本嘅時間到期離場。"""
    h = ((entry_t // 3600) + 1) * 3600  # entry之後第一個完整鐘頭
    end_h = (exit_t // 3600) * 3600
    while h <= end_h:
        low = low_by_hour.get(h)
        if low is not None and low <= stop_price:
            return True, h
        h += 3600
    return False, None


def build_frame(funding, price_by_hour):
    rows = []
    for r in funding:
        t = int(r["fundingTime"]) // 1000
        px = price_at(price_by_hour, t)
        if px is not None:
            rows.append({"t": t, "rate": float(r["fundingRate"]), "price": px})
    df = pd.DataFrame(rows).sort_values("t").reset_index(drop=True)
    roll_mean = df["rate"].rolling(Z_WINDOW, min_periods=Z_WINDOW).mean()
    roll_std = df["rate"].rolling(Z_WINDOW, min_periods=Z_WINDOW).std()
    df["z"] = (df["rate"] - roll_mean) / roll_std
    return df


def run_backtest(df, low_by_hour=None, stop_loss_pct=None, hold_periods=None):
    """stop_loss_pct=None即係原本冇止損嘅行為（純粹持固定期數）。
    有嘅話，持倉期間逐個鐘頭check low有冇跌穿 entry_px*(1-stop_loss_pct)，
    跌穿就用stop價（連slippage）即刻離場，唔使等到期。
    hold_periods=None就用返module-level嘅HOLD_PERIODS常數，傳咗就用返嗰個值
    （方便同v2一齊測試唔同hold組合，唔使改module常數）。"""
    hold_periods = HOLD_PERIODS if hold_periods is None else hold_periods
    equity = INITIAL_CAPITAL
    trades = []
    i = 0
    n = len(df)
    while i < n - hold_periods - 1:
        z = df["z"].iloc[i]
        if pd.notna(z) and z < Z_ENTRY_THRESHOLD:
            entry_idx = i + 1                      # 下一個funding事件先執行,唔用同一時點
            exit_idx = entry_idx + hold_periods
            if exit_idx >= n:
                break
            entry_t = df["t"].iloc[entry_idx]
            exit_t = df["t"].iloc[exit_idx]
            entry_px = df["price"].iloc[entry_idx] * (1 + SLIP)

            exit_reason = "TIME"
            actual_exit_t = exit_t
            actual_exit_px = df["price"].iloc[exit_idx] * (1 - SLIP)

            if stop_loss_pct is not None and low_by_hour is not None:
                stop_price = entry_px * (1 - stop_loss_pct)
                hit, hit_ts = find_stop_hit(low_by_hour, entry_t, exit_t, stop_price)
                if hit:
                    exit_reason = "STOP"
                    actual_exit_t = hit_ts
                    actual_exit_px = stop_price * (1 - SLIP)

            entry_equity = equity
            size = (equity * (1 - FEE)) / entry_px
            # Bug fix(2026-08-xx,寫獨立第二個engine cross-check嗰陣重新推導先揪到):
            # 舊版 pnl = size*(exit_px*(1-FEE) - entry_px),而 size*entry_px 代數上
            # 啱啱好等於 equity*(1-FEE),即係話個「起點」用緊已經扣咗入場fee嘅equity,
            # 但 equity += pnl 個base line 用嘅係扣fee*之前*嘅equity——兩者對唔上,
            # 令入場嗰0.1%手續費嘅金額效果喺equity update度俾人靜雞雞加返轉頭,變相
            # 冇真正扣到。改用proceeds直接做替換,唔再用「加減」形式計,先至冇呢個縫。
            proceeds = size * actual_exit_px * (1 - FEE)
            pnl = proceeds - entry_equity
            equity = proceeds
            trades.append({
                "entry_t": entry_t, "exit_t": actual_exit_t,
                "entry_z": z, "pnl": pnl, "pnl_pct": (actual_exit_px - entry_px) / entry_px,
                "equity_after": equity, "exit_reason": exit_reason,
            })
            i = exit_idx + 1                        # 原本嘅exit_idx為準,唔重疊(即使STOP提早走)
        else:
            i += 1
    return pd.DataFrame(trades), equity


def report(trades, final_equity, label=""):
    if trades.empty:
        print(f"{label}: 冇任何交易觸發。")
        return
    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]
    gp = wins["pnl"].sum()
    gl = -losses["pnl"].sum()
    pf = gp / gl if gl > 0 else float("inf")
    eq = trades["equity_after"]
    dd = ((eq - eq.cummax()) / eq.cummax()).min()
    stop_n = (trades["exit_reason"] == "STOP").sum() if "exit_reason" in trades else 0

    print(f"=== {label} ===")
    print(f"總交易數: {len(trades)}  勝率: {len(wins)/len(trades)*100:.1f}%  (止損離場: {stop_n})")
    print(f"Profit Factor: {pf:.2f}")
    print(f"淨損益: {trades['pnl'].sum():.2f}  (起始 {INITIAL_CAPITAL:.0f}, 終 {final_equity:.2f})")
    print(f"最大回撤: {dd*100:.2f}%")
    print(f"平均每單: {trades['pnl_pct'].mean()*100:.3f}%   中位數: {trades['pnl_pct'].median()*100:.3f}%")


def report_full(trades, final_equity):
    """同 report() 一樣，但加埋年度拆解——原本 __main__ 用嘅版本，保留做單次詳細睇。"""
    report(trades, final_equity, label=f"Funding Squeeze Long, {SYMBOL}, z<{Z_ENTRY_THRESHOLD}, 持{HOLD_PERIODS}期(~{HOLD_PERIODS*8}h)")
    if trades.empty:
        return
    trades = trades.copy()
    trades["year"] = pd.to_datetime(trades["entry_t"], unit="s").dt.year
    print("\n年度拆解:")
    for year, grp in trades.groupby("year"):
        g_wins = grp[grp["pnl"] > 0]
        g_gp = g_wins["pnl"].sum()
        g_gl = -grp[grp["pnl"] <= 0]["pnl"].sum()
        g_pf = g_gp / g_gl if g_gl > 0 else float("inf")
        print(f"  {year}: {len(grp):3d}單  PF {g_pf:5.2f}  淨損益 {grp['pnl'].sum():9.2f}")


if __name__ == "__main__":
    funding, price_by_hour, low_by_hour = load_data()
    df = build_frame(funding, price_by_hour)
    print(f"funding事件: {len(df)}, warmup後可用: {df['z'].notna().sum()}")

    print(f"\n--- 冇止損（baseline，hold={HOLD_PERIODS}期） ---")
    trades, final_equity = run_backtest(df)
    report_full(trades, final_equity)

    print(f"\n--- 加止損網格（hold={HOLD_PERIODS}期） ---")
    for sl in [0.02, 0.03, 0.05, 0.08]:
        trades, final_equity = run_backtest(df, low_by_hour, stop_loss_pct=sl)
        report(trades, final_equity, label=f"止損 {sl:.0%}")

    print("\n--- hold=6期（同v2主要測試組合對齊） ---")
    trades, final_equity = run_backtest(df, hold_periods=6)
    report(trades, final_equity, label="冇止損, hold=6期")
    for sl in [0.02, 0.03, 0.05, 0.08]:
        trades, final_equity = run_backtest(df, low_by_hour, stop_loss_pct=sl, hold_periods=6)
        report(trades, final_equity, label=f"止損{sl:.0%}, hold=6期")
