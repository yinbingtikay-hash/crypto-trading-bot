"""Aggressive小本模式 entry點。"""
import datetime

import config
from data_loader import load_klines, klines_to_df
from backtest_engine_aggressive import run_backtest_aggressive


def _report(result, starting_equity):
    trades = result["trades"]
    if trades.empty:
        print("冇任何交易。")
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
    min_equity = equity_curve.min()
    min_notional = (trades["size"] * trades["entry_price"]).min()

    print(f"=== {config.SYMBOL} Aggressive小本模式 本金${starting_equity:.0f} "
          f"({trades['entry_time'].min()} → {trades['exit_time'].max()}) ===")
    print(f"總交易數: {len(trades)}  勝率: {len(wins) / len(trades) * 100:.1f}%")
    print(f"Profit Factor: {pf:.2f}")
    print(f"最終equity: ${result['final_equity']:.2f}  總回報: {(result['final_equity']-starting_equity)/starting_equity*100:.1f}%")
    print(f"最大回撤: {max_dd * 100:.2f}%  期間最低equity: ${min_equity:.2f}")
    print(f"最細一單notional: ${min_notional:.2f}(參考:Binance spot BTC/USDT一般最低落單額約$5-10)")
    print(f"連續3單虧損觸發次數: {result['pause_trigger_count']}")
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

    for starting_equity in (100.0, 200.0):
        config.BACKTEST_INITIAL_EQUITY = starting_equity
        result = run_backtest_aggressive(df_1h, df_15m)
        _report(result, starting_equity)
        print()


if __name__ == "__main__":
    main()
