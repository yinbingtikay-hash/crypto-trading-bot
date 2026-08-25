"""
V4 entry點:忠實SMC v3.3 rebuild,兩個timeframe組合都跑。

注意:1h resample唔到15m(冧咗嘅intra-hour資訊冇得憑空整返出嚟),所以
(1H bias + 15m entry)嗰組要原生load 15m klines(Route三已經cache咗);
(1D bias + 4H entry)兩層都粗過1h,先可以由1h resample埋過去。
"""
import datetime

import pandas as pd

import config
from data_loader import load_klines, klines_to_df
from backtest_engine_v4 import run_backtest_v4, _resample


def _report(label, result):
    trades = result["trades"]
    print(f"\n=== {label} ===")
    print(f"被skip嘅緊stop訊號: {result['skipped_tight_stop']}   被checklist拒絕: {len(result['rejected_signals'])}")
    if trades.empty:
        print("冇任何交易——bias/sweep條件可能太嚴。")
        return
    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]
    gp = wins["pnl"].sum()
    gl = -losses["pnl"].sum()
    pf = gp / gl if gl > 0 else float("inf")
    eq = trades["equity_after"]
    dd = ((eq - eq.cummax()) / eq.cummax()).min()

    print(f"總交易數: {len(trades)}  勝率: {len(wins)/len(trades)*100:.1f}%")
    print(f"Profit Factor: {pf:.2f}")
    print(f"淨損益: {trades['pnl'].sum():.2f}  (起始 {config.BACKTEST_INITIAL_EQUITY:.0f})")
    print(f"最大回撤: {dd*100:.2f}%")
    print(f"移咗去breakeven嘅單數: {trades['breakeven_triggered'].sum()} / {len(trades)}")

    trades = trades.copy()
    trades["year"] = trades["entry_time"].dt.year
    print("年度拆解:")
    for year, grp in trades.groupby("year"):
        g_wins = grp[grp["pnl"] > 0]
        g_gp = g_wins["pnl"].sum()
        g_gl = -grp[grp["pnl"] <= 0]["pnl"].sum()
        g_pf = g_gp / g_gl if g_gl > 0 else float("inf")
        print(f"  {year}: {len(grp):3d}單  PF {g_pf:5.2f}  淨損益 {grp['pnl'].sum():9.2f}")


def main():
    start_ms = int(
        datetime.datetime.strptime(config.BACKTEST_START, "%Y-%m-%d")
        .replace(tzinfo=datetime.timezone.utc).timestamp() * 1000
    )
    rows_1h = load_klines(config.SYMBOL, "1h", start_ms)
    df_1h = klines_to_df(rows_1h)
    df_1h_with_close = df_1h.assign(close_time=df_1h.index + pd.Timedelta("1h"))

    rows_15m = load_klines(config.SYMBOL, "15m", start_ms)
    df_15m = klines_to_df(rows_15m)
    df_15m_with_close = df_15m.assign(close_time=df_15m.index + pd.Timedelta("15min"))

    result_15m = run_backtest_v4(df_1h_with_close, df_15m_with_close)
    _report("V4: 1H bias + 15m entry (同MNQ顆粒度一樣)", result_15m)

    df_1d = _resample(df_1h, "1d")
    df_4h = _resample(df_1h, "4h")
    result_4h = run_backtest_v4(df_1d, df_4h)
    _report("V4: 1D bias + 4H entry (Hurst數據話呢層有信號)", result_4h)


if __name__ == "__main__":
    main()
