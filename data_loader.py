"""
攞Binance spot歷史K線(public endpoint,唔使API key),cache做本地JSON,
避免每次backtest都重新打API。跟返 funding_rate_analysis.py 嗰套風格。
"""
import json
import os
import time
import urllib.request

import pandas as pd

BASE_URL = "https://api.binance.com/api/v3/klines"
CACHE_DIR = os.path.dirname(os.path.abspath(__file__))

COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def _cache_path(symbol, interval):
    return os.path.join(CACHE_DIR, f"klines_{symbol}_{interval}.json")


def fetch_klines(symbol, interval, start_time_ms):
    rows = []
    start = start_time_ms
    while True:
        url = f"{BASE_URL}?symbol={symbol}&interval={interval}&startTime={start}&limit=1000"
        with urllib.request.urlopen(url, timeout=15) as resp:
            batch = json.loads(resp.read())
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        start = batch[-1][0] + 1
        time.sleep(0.2)  # be polite to the public endpoint
    return rows


def load_klines(symbol, interval, start_time_ms, force_refresh=False):
    path = _cache_path(symbol, interval)
    if os.path.exists(path) and not force_refresh:
        with open(path) as f:
            return json.load(f)

    rows = fetch_klines(symbol, interval, start_time_ms)
    with open(path, "w") as f:
        json.dump(rows, f)
    return rows


def klines_to_df(rows):
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df = df.set_index("open_time")
    return df[["open", "high", "low", "close", "volume", "close_time"]]


if __name__ == "__main__":
    import datetime
    import config

    start_ms = int(
        datetime.datetime.strptime(config.BACKTEST_START, "%Y-%m-%d")
        .replace(tzinfo=datetime.timezone.utc).timestamp() * 1000
    )
    for interval in (config.REGIME_INTERVAL, config.ENTRY_INTERVAL):
        rows = load_klines(config.SYMBOL, interval, start_ms, force_refresh=True)
        print(f"{config.SYMBOL} {interval}: {len(rows)} bars cached to {_cache_path(config.SYMBOL, interval)}")
