"""
攞BTC/USD日線歷史數據(2014至今),用Bitstamp public API(唔使key,佢2014年
already有齊OHLC)。Binance得返2017-08後嘅data,唔夠涵蓋2014-2017,所以呢個
explorer工具專門用Bitstamp,同v1/v2/v3(Binance BTCUSDT)嘅data source唔同,
唔互通唔奇怪。
"""
import json
import time
import urllib.request

BASE_URL = "https://www.bitstamp.net/api/v2/ohlc/btcusd/"
START_TS = 1388534400  # 2014-01-01 UTC
OUT_PATH = "/Users/axly012/crypto-trading-bot/btc_daily_2014_2026.json"


def fetch_all():
    rows = {}
    start = START_TS
    while True:
        url = f"{BASE_URL}?step=86400&limit=1000&start={start}"
        with urllib.request.urlopen(url, timeout=15) as resp:
            batch = json.loads(resp.read())["data"]["ohlc"]
        if not batch:
            break
        for r in batch:
            rows[int(r["timestamp"])] = r
        last_ts = int(batch[-1]["timestamp"])
        if len(batch) < 1000 or last_ts <= start:
            break
        start = last_ts + 86400
        time.sleep(0.3)
    return [rows[k] for k in sorted(rows.keys())]


if __name__ == "__main__":
    data = fetch_all()
    with open(OUT_PATH, "w") as f:
        json.dump(data, f)
    print(f"{len(data)} 日 bar,由 {data[0]['timestamp']} 到 {data[-1]['timestamp']}")
    print(f"cached to {OUT_PATH}")
