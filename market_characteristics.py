"""
拆解BTC/USDT市場特性——喺度用嘅係已經cache咗嘅2020-2026歷史(klines_BTCUSDT_*.json),
唔使重新問Binance攞。目的:喺度身設計entry V2之前,先驗證BTC本身有冇趨勢/mean-reversion
傾向,幾多時間真係「趨勢中」,有冇時段/星期效應——用數據指導策略paradigm嘅選擇,
唔好一開始就套一個聽落合理嘅樣板落去。
"""
import numpy as np
import pandas as pd

from data_loader import load_klines, klines_to_df

SYMBOL = "BTCUSDT"


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1)).dropna()


def variance_ratio(returns: pd.Series, q: int) -> float:
    """簡化版Lo-MacKinlay variance ratio(overlapping estimator,探索用,非嚴謹統計檢定)。
    VR>1=正自相關(趨勢/動量傾向);VR<1=負自相關(mean-reversion傾向);VR≈1=接近random walk。"""
    var_1 = returns.var()
    q_sum = returns.rolling(q).sum().dropna()
    var_q = q_sum.var()
    return var_q / (q * var_1)


def hurst_exponent(returns: pd.Series, min_window=8, max_window=500, n_points=20) -> float:
    """用aggregated variance法估Hurst exponent:Var(n期累積報酬) ~ n^(2H)。
    H>0.5=趨勢/持續性;H<0.5=mean-reversion;H≈0.5=random walk。"""
    windows = np.unique(np.logspace(np.log10(min_window), np.log10(max_window), n_points).astype(int))
    log_n, log_var = [], []
    for n in windows:
        if n < 2 or n * 5 > len(returns):
            continue
        agg = returns.rolling(n).sum().dropna()
        if agg.var() <= 0:
            continue
        log_n.append(np.log(n))
        log_var.append(np.log(agg.var()))
    slope = np.polyfit(log_n, log_var, 1)[0]
    return slope / 2


def kaufman_efficiency_ratio(close: pd.Series, window=20) -> pd.Series:
    """Kaufman's Efficiency Ratio:淨移動距離/總移動距離。近1=有效率咁單向郁(趨勢);
    近0=嚟嚟回回(盤整)。"""
    net_change = (close - close.shift(window)).abs()
    total_change = close.diff().abs().rolling(window).sum()
    return net_change / total_change


def analyze_timeframe(close, label):
    r = log_returns(close)
    print(f"\n--- {label}(n={len(r)}) ---")
    print(f"Lag-1 autocorrelation: {r.autocorr(1):.4f}")
    for q in (2, 4, 8):
        if len(r) > q * 30:
            print(f"Variance Ratio VR({q}): {variance_ratio(r, q):.4f}")
    if len(r) > 200:
        h = hurst_exponent(r)
        print(f"Hurst exponent: {h:.4f}")


def main():
    rows_1h = load_klines(SYMBOL, "1h", 0)
    rows_15m = load_klines(SYMBOL, "15m", 0)
    df_1h = klines_to_df(rows_1h)
    df_15m = klines_to_df(rows_15m)

    close_15m = df_15m["close"]
    close_1h = df_1h["close"]
    close_4h = df_1h["close"].resample("4h").last().dropna()
    close_1d = df_1h["close"].resample("1D").last().dropna()

    print("=" * 60)
    print("1) 唔同時間刻度嘅趨勢/mean-reversion傾向")
    print("=" * 60)
    analyze_timeframe(close_15m, "15m")
    analyze_timeframe(close_1h, "1H")
    analyze_timeframe(close_4h, "4H")
    analyze_timeframe(close_1d, "1D")

    print("\n" + "=" * 60)
    print("2) 幾多時間真係「趨勢中」(Kaufman Efficiency Ratio,20期window,1H)")
    print("=" * 60)
    er = kaufman_efficiency_ratio(df_1h["close"], window=20).dropna()
    print(f"ER 平均值: {er.mean():.3f}")
    print(f"ER 分佈: {er.describe()}")
    print(f"ER > 0.3(相對有效率/趨勢)嘅時間佔比: {(er > 0.3).mean()*100:.1f}%")
    print(f"ER < 0.15(嚟嚟回回/盤整)嘅時間佔比: {(er < 0.15).mean()*100:.1f}%")

    er_by_year = er.groupby(er.index.year).mean()
    print("\n年度ER平均值(睇邊幾年trend-following環境好啲):")
    print(er_by_year)

    print("\n" + "=" * 60)
    print("3) UTC時段效應(1H log return,平均值/標準差)")
    print("=" * 60)
    r_1h = log_returns(df_1h["close"])
    by_hour = r_1h.groupby(r_1h.index.hour).agg(["mean", "std", "count"])
    print(by_hour)

    print("\n" + "=" * 60)
    print("4) 星期效應(1H log return,平均值/標準差)")
    print("=" * 60)
    by_dow = r_1h.groupby(r_1h.index.dayofweek).agg(["mean", "std", "count"])
    by_dow.index = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    print(by_dow)


if __name__ == "__main__":
    main()
