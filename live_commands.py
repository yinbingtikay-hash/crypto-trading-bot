"""處理用戶直接喺 Telegram 發俾 bot 嘅查詢指令：/status /pnl /stop /help。"""

import live_trade_log as trade_log
from live_data_fetcher import DataFetcher

HELP_TEXT = (
    "可用指令：\n"
    "/status — 查詢目前持倉同浮動盈虧\n"
    "/pnl — 查詢已平倉交易表現總結\n"
    "/stop — 安全停止 bot（唔會自動平倉，請自行檢查）"
)


def format_status(state, fetcher: DataFetcher) -> str:
    if not state.in_position or state.current_position is None:
        return "📭 目前空手，未持倉。"

    pos = state.current_position
    try:
        current_price = fetcher.fetch_last_price()
    except Exception as e:
        return (
            f"📊 *持倉中*（無法查詢現價）\n數量：`{pos.quantity:.6f}`\n"
            f"進場價：`{pos.entry_price:.2f}`\n錯誤：`{e}`"
        )

    floating_pnl = (current_price - pos.entry_price) * pos.quantity
    floating_pct = (current_price - pos.entry_price) / pos.entry_price * 100

    return (
        "📊 *持倉中*\n"
        f"數量：`{pos.quantity:.6f}`\n"
        f"進場價：`{pos.entry_price:.2f}` 現價：`{current_price:.2f}`\n"
        f"浮動損益：`{floating_pnl:+.2f} USDT`（`{floating_pct:+.2f}%`）\n"
        f"預計平倉時間戳：`{pos.exit_due_after_funding_ts}`"
    )


def format_pnl_summary(trade_log_path: str) -> str:
    summary = trade_log.summarize(trade_log_path)
    if summary["total_trades"] == 0:
        return "📈 仲未有已平倉嘅交易紀錄。"

    pf = "N/A（未輸過）" if summary["profit_factor"] is None else f"{summary['profit_factor']:.2f}"
    return (
        "📈 *交易表現總結*\n"
        f"總交易次數：{summary['total_trades']}\n"
        f"勝率：{summary['win_rate_pct']:.1f}%（{summary['wins']} 勝 {summary['losses']} 負）\n"
        f"總損益：`{summary['total_pnl_usdt']:+.2f} USDT`\n"
        f"平均每筆：`{summary['avg_pnl_usdt']:+.2f} USDT`\n"
        f"Profit Factor：{pf}"
    )


def handle_command(text: str, fetcher: DataFetcher, state, trade_log_path: str) -> tuple:
    if not text:
        return None, False

    command = text.strip().split()[0].lower()

    if command == "/status":
        return format_status(state, fetcher), False
    if command == "/pnl":
        return format_pnl_summary(trade_log_path), False
    if command == "/stop":
        return "🛑 收到停止指令，將於本輪結束後安全退出。如有持倉將唔會自動平倉，請自行檢查。", True
    if command in ("/start", "/help"):
        return HELP_TEXT, False

    return f"未知指令：`{command}`\n\n{HELP_TEXT}", False
