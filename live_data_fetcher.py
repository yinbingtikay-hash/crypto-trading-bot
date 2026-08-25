"""負責交易所連線：Spot（落單/查餘額，可以連 Testnet）+ Futures（淨係讀 funding
rate 公開數據，永遠連正式網——因為 Testnet 嘅 funding rate 數據唔完整/唔可靠，
但呢度純粹讀公開歷史數據，唔涉及帳戶，讀正式網冇風險）。

保留同 crypto-trading-bot-ema/data_fetcher.py 一致嘅 retry decorator 設計。
"""

import logging
import time
from functools import wraps

import ccxt
import pandas as pd

from live_config import Config

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 2


def with_retry(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except ccxt.AuthenticationError:
                raise
            except ccxt.InvalidOrder:
                raise
            except ccxt.BadRequest:
                raise
            except ccxt.RateLimitExceeded as e:
                last_error = e
                wait = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning("觸發 Rate Limit（第 %d/%d 次），%d 秒後重試：%s", attempt, MAX_RETRIES, wait, e)
                time.sleep(wait)
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout, ccxt.DDoSProtection) as e:
                last_error = e
                wait = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning("網絡 / 交易所暫時性錯誤（第 %d/%d 次），%d 秒後重試：%s", attempt, MAX_RETRIES, wait, e)
                time.sleep(wait)
            except ccxt.ExchangeError as e:
                last_error = e
                logger.error("交易所回報錯誤：%s", e)
                raise
        logger.error("重試 %d 次後仍然失敗：%s", MAX_RETRIES, last_error)
        raise last_error

    return wrapper


class DataFetcher:
    def __init__(self, config: Config):
        self.config = config
        self.spot = self._build_spot_exchange()
        self.futures = ccxt.binanceusdm({"enableRateLimit": True})  # 淨係讀公開funding rate，冇key

    def _build_spot_exchange(self) -> ccxt.Exchange:
        exchange = ccxt.binance({
            "apiKey": self.config.api_key,
            "secret": self.config.api_secret,
            "enableRateLimit": True,
        })
        if self.config.use_testnet:
            exchange.set_sandbox_mode(True)
            logger.info("已啟用 Binance Spot Testnet（模擬網）模式")
        return exchange

    @with_retry
    def fetch_funding_rate_history(self, since_ms: int | None = None, limit: int = 500) -> list:
        return self.futures.fetch_funding_rate_history(self.config.symbol, since=since_ms, limit=limit)

    def fetch_funding_history_df(self, min_periods: int) -> pd.DataFrame:
        """攞夠 min_periods 個 funding 事件嘅歷史（分頁攞，每個 event 相隔 8 小時）。"""
        all_events = []
        # 由而家計返轉頭，攞夠 min_periods*1.2（留少少buffer）咁多個event
        needed_hours = int(min_periods * 8 * 1.2)
        since_ms = self.futures.milliseconds() - needed_hours * 3600 * 1000

        cursor = since_ms
        while True:
            batch = self.fetch_funding_rate_history(since_ms=cursor, limit=500)
            if not batch:
                break
            all_events.extend(batch)
            last_ts = batch[-1]["timestamp"]
            if last_ts <= cursor:
                break
            cursor = last_ts + 1
            if len(batch) < 500:
                break

        rows = [{"t": e["timestamp"] // 1000, "rate": float(e["fundingRate"])} for e in all_events]
        df = pd.DataFrame(rows).drop_duplicates(subset="t").sort_values("t").reset_index(drop=True)
        return df

    @with_retry
    def fetch_last_price(self) -> float:
        ticker = self.spot.fetch_ticker(self.config.symbol)
        return float(ticker["last"])

    @with_retry
    def fetch_quote_equity(self, quote_currency: str = "USDT") -> float:
        balance = self.spot.fetch_balance()
        free = balance.get("free", {}).get(quote_currency)
        if free is None:
            raise ccxt.ExchangeError(f"無法從帳戶餘額取得 {quote_currency} 資料")
        return float(free)

    @with_retry
    def fetch_base_position(self, base_currency: str) -> float:
        balance = self.spot.fetch_balance()
        return float(balance.get("free", {}).get(base_currency, 0.0))

    @with_retry
    def fetch_last_buy_average_price(self) -> float | None:
        trades = self.spot.fetch_my_trades(self.config.symbol, limit=20)
        buy_trades = [t for t in trades if t.get("side") == "buy"]
        if not buy_trades:
            return None
        return float(buy_trades[-1]["price"])

    @with_retry
    def create_market_order(self, side: str, amount: float):
        return self.spot.create_order(symbol=self.config.symbol, type="market", side=side, amount=amount)
