"""獨立 CLI 工具：列印 Funding Squeeze bot 表現總結 + 目前持倉浮動盈虧。

用法：
    python live_stats.py
"""

import os

import live_position_state as position_state
import live_trade_log as trade_log
from live_config import load_config
from live_data_fetcher import DataFetcher

_LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_logs")
TRADE_LOG_PATH = os.path.join(_LOGS_DIR, "trade_history.csv")
POSITION_STATE_PATH = os.path.join(_LOGS_DIR, "position_state.json")


def format_pf(pf):
    return "N/A（未輸過任何一筆）" if pf is None else f"{pf:.2f}"


def print_closed_trades_summary():
    summary = trade_log.summarize(TRADE_LOG_PATH)
    rows = trade_log.read_trades(TRADE_LOG_PATH)

    if summary["total_trades"] == 0:
        print("\n目前仲未有任何已平倉嘅交易紀錄。")
        return

    print(f"\n交易紀錄檔案：{TRADE_LOG_PATH}")
    print(f"總交易次數：{summary['total_trades']}")
    print(f"勝出：{summary['wins']} 場 / 輸出：{summary['losses']} 場")
    print(f"勝率：{summary['win_rate_pct']:.1f}%")
    print(f"總損益：{summary['total_pnl_usdt']:+.2f} USDT")
    print(f"平均每筆：{summary['avg_pnl_usdt']:+.2f} USDT")
    print(f"Profit Factor：{format_pf(summary['profit_factor'])}")

    print("\n最近 5 筆交易：")
    for row in rows[-5:]:
        print(f"  {row['entry_time']} -> {row['exit_time']}  "
              f"{float(row['entry_price']):.2f} -> {float(row['exit_price']):.2f}  "
              f"pnl={float(row['pnl_usdt']):+.2f} USDT ({float(row['pnl_pct']):+.2f}%)")


def print_open_position_section():
    position = position_state.load_position_state(POSITION_STATE_PATH)
    print("\n" + "-" * 50)
    print("目前持倉")
    print("-" * 50)

    if position is None:
        print("目前空手，冇持倉中。")
        return

    print(f"數量：{position.quantity:.6f}")
    print(f"進場價：{position.entry_price:.2f}")
    print(f"進場時間：{position.entry_time}")
    print(f"到期時間戳：{position.exit_due_after_funding_ts}")

    try:
        fetcher = DataFetcher(load_config())
        current_price = fetcher.fetch_last_price()
    except Exception as e:
        print(f"（無法查詢現價計算浮動盈虧：{e}）")
        return

    floating_pnl = (current_price - position.entry_price) * position.quantity
    floating_pct = (current_price - position.entry_price) / position.entry_price * 100
    print(f"現價：{current_price:.2f}")
    print(f"浮動損益：{floating_pnl:+.2f} USDT（{floating_pct:+.2f}%）")


def main():
    print("=" * 50)
    print("Funding Squeeze Bot —— 表現總結")
    print("=" * 50)
    print_closed_trades_summary()
    print_open_position_section()


if __name__ == "__main__":
    main()
