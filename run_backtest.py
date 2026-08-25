"""Stage 3 entry點:載入歷史K線,跑backtest,印出表現摘要。"""
import datetime

import config
from data_loader import load_klines, klines_to_df
from backtest_engine import run_backtest


def _report(result):
    trades = result["trades"]
    if trades.empty:
        print("冇任何交易——檢查regime/entry條件係咪太嚴,或者資料範圍係咪啱。")
        return

    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]
    gross_profit = wins["pnl"].sum()
    gross_loss = -losses["pnl"].sum()
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    equity_curve = trades["equity_after"]
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    max_dd = drawdown.min()

    print(f"=== {config.SYMBOL} v1 backtest ({trades['entry_time'].min()} → {trades['exit_time'].max()}) ===")
    print(f"總交易數: {len(trades)}  勝率: {len(wins) / len(trades) * 100:.1f}%")
    print(f"Profit Factor: {pf:.2f}")
    print(f"淨損益: {trades['pnl'].sum():.2f}  (起始equity: {config.BACKTEST_INITIAL_EQUITY:.2f})")
    print(f"最大回撤: {max_dd * 100:.2f}%")
    print(f"連續3單虧損觸發次數(backtest代理規則,見Stage 2 Q7討論): {result['pause_trigger_count']}")
    print(f"被pre-trade checklist否決嘅訊號數: {len(result['rejected_signals'])}")


def main():
    start_ms = int(
        datetime.datetime.strptime(config.BACKTEST_START, "%Y-%m-%d")
        .replace(tzinfo=datetime.timezone.utc).timestamp() * 1000
    )
    rows_1h = load_klines(config.SYMBOL, config.REGIME_INTERVAL, start_ms)
    rows_15m = load_klines(config.SYMBOL, config.ENTRY_INTERVAL, start_ms)

    df_1h = klines_to_df(rows_1h)
    df_15m = klines_to_df(rows_15m)

    result = run_backtest(df_1h, df_15m)
    _report(result)


if __name__ == "__main__":
    main()
