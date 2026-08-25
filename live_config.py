"""Live/paper 執行設定：讀 .env。Funding Squeeze Long 專用——參數已經用
funding_squeeze_backtest.py(v1)/funding_squeeze_v2_independent.py(v2)雙 engine
驗證過(z<-2.0, hold=6, 冇止損, PF 1.63-1.74, train/test都>1)，呢度唔重新驗證
策略，淨係負責照跟已驗證嘅規則落單。
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    pass


def _get_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _get_int(key: str, default: int) -> int:
    val = os.getenv(key)
    return int(val) if val not in (None, "") else default


def _get_float(key: str, default: float) -> float:
    val = os.getenv(key)
    return float(val) if val not in (None, "") else default


@dataclass(frozen=True)
class Config:
    # Spot 交易所連線（真正落單嘅地方）
    api_key: str
    api_secret: str
    use_testnet: bool

    # 監控目標
    symbol: str

    # Funding Squeeze 策略參數（已驗證，唔喺呢度改）
    z_window: int
    z_entry_threshold: float
    hold_periods: int  # 單位：funding事件次數（每次8小時）

    poll_interval_seconds: int

    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str

    def validate(self) -> None:
        errors = []

        if not self.api_key or not self.api_secret:
            errors.append("落單需要 API_KEY / API_SECRET（Testnet 請去 testnet.binance.vision 生成）")

        if self.poll_interval_seconds <= 0:
            errors.append("POLL_INTERVAL_SECONDS 必須大於 0")

        if self.hold_periods <= 0:
            errors.append("HOLD_PERIODS 必須大於 0")

        if not self.telegram_bot_token or not self.telegram_chat_id:
            errors.append("未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")

        if errors:
            raise ConfigError("設定檢查失敗：\n- " + "\n- ".join(errors))


def load_config() -> Config:
    return Config(
        api_key=os.getenv("API_KEY", ""),
        api_secret=os.getenv("API_SECRET", ""),
        use_testnet=_get_bool("USE_TESTNET", True),
        symbol=os.getenv("SYMBOL", "BTC/USDT"),
        z_window=_get_int("Z_WINDOW", 540),
        z_entry_threshold=_get_float("Z_ENTRY_THRESHOLD", -2.0),
        hold_periods=_get_int("HOLD_PERIODS", 6),
        poll_interval_seconds=_get_int("POLL_INTERVAL_SECONDS", 300),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )


_config_instance: Config | None = None


def get_config() -> Config:
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config()
    return _config_instance
