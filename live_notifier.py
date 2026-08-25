"""Telegram 推播通知 + 指令查詢（/status /pnl /stop /help）。網絡錯誤只記錄
警告，唔會令主程式中斷。"""

import logging

import requests

from live_config import Config

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 10


class Notifier:
    def __init__(self, config: Config):
        self.config = config
        self._enabled = bool(config.telegram_bot_token and config.telegram_chat_id)
        if not self._enabled:
            logger.warning("未設定 Telegram Token / Chat ID，通知功能已停用")

    def send(self, message: str) -> bool:
        if not self._enabled:
            logger.info("[通知已停用] %s", message)
            return False

        url = f"{TELEGRAM_API_BASE}/bot{self.config.telegram_bot_token}/sendMessage"
        payload = {"chat_id": self.config.telegram_chat_id, "text": message, "parse_mode": "Markdown"}

        try:
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.warning("Telegram 通知發送失敗，已略過：%s", e)
            return False

    def get_updates(self, offset: int | None = None) -> list:
        if not self._enabled:
            return []
        url = f"{TELEGRAM_API_BASE}/bot{self.config.telegram_bot_token}/getUpdates"
        params = {"timeout": 0}
        if offset is not None:
            params["offset"] = offset
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json().get("result", [])
        except requests.exceptions.RequestException as e:
            logger.warning("查詢 Telegram 新訊息失敗，已略過：%s", e)
            return []

    def notify_startup(self, symbol: str, z_threshold: float, hold_periods: int, testnet: bool) -> None:
        mode = "Testnet 模擬網" if testnet else "⚠️ 正式帳戶（真實資金）"
        self.send(
            "🤖 *Funding Squeeze Bot 已啟動*\n"
            f"交易對：`{symbol}`\n"
            f"訊號：z < `{z_threshold}` 持 `{hold_periods}` 個 funding 週期\n"
            f"模式：*{mode}*"
        )

    def notify_signal(self, symbol: str, z_score: float, funding_rate: float) -> None:
        self.send(
            "🟢 *偵測到 Funding Squeeze 訊號*\n"
            f"交易對：`{symbol}`\n"
            f"Funding rate z-score：`{z_score:.2f}`\n"
            f"Funding rate：`{funding_rate:.4%}`"
        )

    def notify_trade_executed(self, symbol: str, quantity: float, entry_price: float, hold_periods: int) -> None:
        self.send(
            "✅ *已進場*\n"
            f"交易對：`{symbol}`\n"
            f"數量：`{quantity:.6f}`\n"
            f"進場價：`{entry_price:.2f}`\n"
            f"持有：`{hold_periods}` 個 funding 週期（~{hold_periods*8}小時），冇止損"
        )

    def notify_trade_closed(self, trade) -> None:
        emoji = "🟢" if trade.pnl_usdt > 0 else ("🔴" if trade.pnl_usdt < 0 else "⚪")
        self.send(
            f"{emoji} *平倉（{trade.exit_reason}）*\n"
            f"進場價：`{trade.entry_price:.2f}` -> 平倉價：`{trade.exit_price:.2f}`\n"
            f"數量：`{trade.quantity:.6f}`\n"
            f"損益：`{trade.pnl_usdt:+.2f} USDT`（`{trade.pnl_pct:+.2f}%`）"
        )

    def notify_error(self, context: str, error: Exception) -> None:
        self.send(f"⚠️ *發生錯誤*\n情境：`{context}`\n訊息：`{error}`")
