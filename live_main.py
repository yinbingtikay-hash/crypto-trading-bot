"""主程序：Funding Squeeze Long——輪詢 Binance Futures 嘅 funding rate，
z-score 跌穿門檻就用 Spot 全倉市價買入，持夠 HOLD_PERIODS 個 funding 週期
（每個 8 小時）後市價賣出。冇止損（已經雙 engine 驗證過：加止損反而拖低
表現，見 funding_squeeze_backtest.py / funding_squeeze_v2_independent.py）。

⚠️ 安全提示：USE_TESTNET=true 時只會喺 Spot Testnet 落單，唔涉及真實資金。
⚠️ 倉位大小＝全部可用資金（同已驗證嘅 backtest 一致嘅 sizing），呢個唔係
保守設定——如果將來轉正式帳戶，落地前要重新評估呢個 all-in 單一倉位嘅
sizing 是否合適。
"""

import logging
import os
import signal as os_signal
import sys
import time
from datetime import datetime, timezone

import ccxt

import live_commands as commands
import live_position_state as position_state
import live_trade_log as trade_log
from live_config import ConfigError, get_config
from live_data_fetcher import DataFetcher
from live_notifier import Notifier
from live_strategy import add_zscore, get_latest_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("live_main")

_LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_logs")
TRADE_LOG_PATH = os.path.join(_LOGS_DIR, "trade_history.csv")
POSITION_STATE_PATH = os.path.join(_LOGS_DIR, "position_state.json")

_shutdown_requested = False


def _handle_shutdown_signal(signum, frame):
    global _shutdown_requested
    logger.info("收到終止訊號（%s），將於本輪結束後安全退出...", signum)
    _shutdown_requested = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BotState:
    def __init__(self):
        self.in_position = False
        self.current_position = None  # live_position_state.PersistedPosition
        self.entry_time = None
        self.last_seen_signal_funding_time = None
        self.telegram_update_offset = None


def check_telegram_commands(fetcher: DataFetcher, notifier: Notifier, state: BotState):
    global _shutdown_requested
    updates = notifier.get_updates(offset=state.telegram_update_offset)
    for update in updates:
        state.telegram_update_offset = update["update_id"] + 1
        try:
            message = update.get("message") or {}
            chat_id = str(message.get("chat", {}).get("id", ""))
            text = message.get("text", "")
            if chat_id != str(fetcher.config.telegram_chat_id):
                continue
            reply, should_stop = commands.handle_command(text, fetcher, state, TRADE_LOG_PATH)
            if reply:
                notifier.send(reply)
            if should_stop:
                _shutdown_requested = True
        except Exception as e:
            logger.exception("處理 Telegram 指令時發生錯誤：%s", e)


def try_exit_position(fetcher: DataFetcher, notifier: Notifier, state: BotState):
    pos = state.current_position
    now_ts = int(time.time())
    if now_ts < pos.exit_due_after_funding_ts:
        logger.debug("持倉中，仲未到期（到期時間戳=%d，仲差 %d 秒）", pos.exit_due_after_funding_ts, pos.exit_due_after_funding_ts - now_ts)
        return

    base_currency = fetcher.config.symbol.split("/")[0]
    available = fetcher.fetch_base_position(base_currency)
    qty = min(pos.quantity, available)
    if qty <= 0:
        logger.warning("到期想平倉但查無 %s 持倉數量，重置本地狀態", base_currency)
        state.in_position = False
        state.current_position = None
        position_state.clear_position_state(POSITION_STATE_PATH)
        return

    order = fetcher.create_market_order("sell", qty)
    exit_price = float(order.get("average") or order.get("price") or fetcher.fetch_last_price())

    trade = trade_log.build_closed_trade(
        entry_time=state.entry_time, exit_time=_now_iso(), side="BUY",
        entry_price=pos.entry_price, exit_price=exit_price, quantity=qty, exit_reason="TIME",
    )
    trade_log.record_trade(TRADE_LOG_PATH, trade)
    position_state.clear_position_state(POSITION_STATE_PATH)

    notifier.notify_trade_closed(trade)
    logger.info("已平倉：pnl=%.2f USDT（%.2f%%）", trade.pnl_usdt, trade.pnl_pct)
    state.in_position = False
    state.current_position = None
    state.entry_time = None


def try_enter_position(fetcher: DataFetcher, notifier: Notifier, state: BotState):
    config = fetcher.config
    df = fetcher.fetch_funding_history_df(min_periods=config.z_window + 5)
    df = add_zscore(df, config.z_window)
    signal = get_latest_signal(df, config.z_entry_threshold)

    if signal is None:
        logger.debug("目前 funding z-score 未跌穿門檻")
        return
    if signal.funding_time == state.last_seen_signal_funding_time:
        logger.debug("呢個 funding 訊號（%d）已經處理過，略過", signal.funding_time)
        return

    state.last_seen_signal_funding_time = signal.funding_time
    logger.info("偵測到 Funding Squeeze 訊號：z=%.2f rate=%.4f%%", signal.z_score, signal.funding_rate * 100)
    notifier.notify_signal(config.symbol, signal.z_score, signal.funding_rate)

    try:
        equity = fetcher.fetch_quote_equity("USDT")
    except ccxt.ExchangeError as e:
        logger.warning("無法查詢帳戶餘額，略過本次進場：%s", e)
        return

    entry_price = fetcher.fetch_last_price()
    quantity = (equity * 0.999) / entry_price  # 全倉，留少少buffer畀手續費/精度
    if quantity <= 0:
        logger.warning("計算出的倉位數量為 0，略過本次進場")
        return

    order = fetcher.create_market_order("buy", quantity)
    actual_entry_price = float(order.get("average") or order.get("price") or entry_price)
    exit_due_ts = signal.funding_time + config.hold_periods * 8 * 3600

    state.in_position = True
    state.entry_time = _now_iso()
    state.current_position = position_state.PersistedPosition(
        side="BUY", entry_price=actual_entry_price, quantity=quantity,
        entry_time=state.entry_time, exit_due_after_funding_ts=exit_due_ts,
    )
    position_state.save_position_state(POSITION_STATE_PATH, state.current_position)

    notifier.notify_trade_executed(config.symbol, quantity, actual_entry_price, config.hold_periods)
    logger.info("已進場：數量=%.6f 進場價=%.2f 到期時間戳=%d", quantity, actual_entry_price, exit_due_ts)


def run_once(fetcher: DataFetcher, notifier: Notifier, state: BotState):
    if state.in_position:
        try_exit_position(fetcher, notifier, state)
    else:
        try_enter_position(fetcher, notifier, state)


def reconcile_existing_position(fetcher: DataFetcher, notifier: Notifier, state: BotState):
    """程式啟動時優先信本機記錄檔（同 crypto-trading-bot-ema 個project一樣嘅
    理由：戶口結餘會被 Testnet 派發嘅模擬資金污染，唔可信）。搵唔到記錄檔但
    戶口有結餘嘅話，Funding Squeeze 冇止損/止盈價位可以推斷返「幾時應該平倉」，
    淨係警告用戶自己檢查，唔會亂咁估一個到期時間。"""
    persisted = position_state.load_position_state(POSITION_STATE_PATH)
    base_currency = fetcher.config.symbol.split("/")[0]

    if persisted is not None:
        state.in_position = True
        state.current_position = persisted
        state.entry_time = persisted.entry_time
        logger.warning("啟動時接管本機記錄嘅持倉：數量=%.6f 進場價=%.2f 到期時間戳=%d",
                        persisted.quantity, persisted.entry_price, persisted.exit_due_after_funding_ts)
        notifier.send(
            "⚠️ *啟動時接管持倉監控（本機記錄）*\n"
            f"數量：`{persisted.quantity:.6f}`\n進場價：`{persisted.entry_price:.2f}`\n"
            f"到期時間戳：`{persisted.exit_due_after_funding_ts}`"
        )
        return

    existing_qty = fetcher.fetch_base_position(base_currency)
    if existing_qty > 0:
        logger.warning(
            "啟動時偵測到現有 %.6f %s 持倉，但搵唔到本機記錄檔——Funding Squeeze 冇價位可以推斷到期時間，"
            "呢個持倉暫時唔會被自動監控，請自行檢查戶口",
            existing_qty, base_currency,
        )
        notifier.send(
            f"⚠️ *啟動時偵測到 {existing_qty:.6f} {base_currency} 持倉，但搵唔到本機記錄*\n"
            "呢個持倉暫時唔會被自動平倉，請自行檢查。"
        )


def main():
    try:
        config = get_config()
        config.validate()
    except ConfigError as e:
        logger.error("設定錯誤，無法啟動：\n%s", e)
        sys.exit(1)

    fetcher = DataFetcher(config)
    notifier = Notifier(config)
    state = BotState()

    reconcile_existing_position(fetcher, notifier, state)

    if not config.use_testnet:
        logger.warning("⚠️ USE_TESTNET=false —— 本次啟動將會用真實資金落單！")

    notifier.notify_startup(config.symbol, config.z_entry_threshold, config.hold_periods, config.use_testnet)
    logger.info(
        "Bot 啟動：symbol=%s z<%.1f hold=%d testnet=%s poll=%ds",
        config.symbol, config.z_entry_threshold, config.hold_periods, config.use_testnet, config.poll_interval_seconds,
    )

    os_signal.signal(os_signal.SIGINT, _handle_shutdown_signal)
    os_signal.signal(os_signal.SIGTERM, _handle_shutdown_signal)

    consecutive_failures = 0
    while not _shutdown_requested:
        try:
            run_once(fetcher, notifier, state)
            consecutive_failures = 0
        except ccxt.AuthenticationError as e:
            logger.error("認證失敗，請檢查 API_KEY / API_SECRET，程式終止：%s", e)
            notifier.notify_error("認證失敗", e)
            sys.exit(1)
        except Exception as e:
            consecutive_failures += 1
            logger.exception("執行過程發生未預期錯誤（連續第 %d 次）", consecutive_failures)
            notifier.notify_error("主迴圈執行失敗", e)
            if consecutive_failures >= 10:
                logger.error("連續失敗次數過多，程式終止")
                sys.exit(1)

        for _ in range(config.poll_interval_seconds):
            if _shutdown_requested:
                break
            check_telegram_commands(fetcher, notifier, state)
            time.sleep(5)

    logger.info("Bot 已安全退出")


if __name__ == "__main__":
    main()
