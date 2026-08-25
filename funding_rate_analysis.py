"""
Pulls full historical funding rate data for Binance USDT-M perpetuals (public
endpoint, no API key needed) and summarizes whether a delta-neutral
long-spot / short-perp carry trade would have been worth running.
"""
import json
import statistics
import time
import urllib.request

BASE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
START_TIME_MS = 1567296000000  # 2019-09-01, before BTCUSDT perp launch


def fetch_all(symbol):
    rows = []
    start = START_TIME_MS
    while True:
        url = f"{BASE_URL}?symbol={symbol}&startTime={start}&limit=1000"
        with urllib.request.urlopen(url, timeout=15) as resp:
            batch = json.loads(resp.read())
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        start = batch[-1]["fundingTime"] + 1
        time.sleep(0.2)  # be polite to the public endpoint
    return rows


def annualized_from_periods(rates, periods_per_year):
    return statistics.mean(rates) * periods_per_year * 100


def longest_negative_streak(rates):
    longest = cur = 0
    for r in rates:
        if r < 0:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 0
    return longest


def year_slice(rows, year):
    return [r for r in rows if time.gmtime(r["fundingTime"] / 1000).tm_year == year]


for symbol in SYMBOLS:
    rows = fetch_all(symbol)
    with open(f"/Users/axly012/crypto-trading-bot/funding_history_{symbol}.json", "w") as f:
        json.dump(rows, f)

    rates = [float(r["fundingRate"]) for r in rows]
    first_date = time.strftime("%Y-%m-%d", time.gmtime(rows[0]["fundingTime"] / 1000))
    last_date = time.strftime("%Y-%m-%d", time.gmtime(rows[-1]["fundingTime"] / 1000))

    print(f"\n=== {symbol} ({first_date} → {last_date}, {len(rows)} funding events, 8h each) ===")
    print(f"Mean funding / 8h period: {statistics.mean(rates)*100:.5f}%")
    print(f"Annualized mean (x3/day x365, no compounding): {annualized_from_periods(rates, 3*365):.2f}%")
    print(f"Median funding / 8h period: {statistics.median(rates)*100:.5f}%")
    pct_negative = sum(1 for r in rates if r < 0) / len(rates) * 100
    print(f"% of periods negative (you'd be paying, not receiving): {pct_negative:.1f}%")
    streak = longest_negative_streak(rates)
    print(f"Longest consecutive negative streak: {streak} periods (~{streak/3:.1f} days)")

    print("Year-by-year annualized funding:")
    years = sorted({time.gmtime(r["fundingTime"] / 1000).tm_year for r in rows})
    for y in years:
        yr_rates = [float(r["fundingRate"]) for r in year_slice(rows, y)]
        if len(yr_rates) < 10:
            continue
        print(f"  {y}: {annualized_from_periods(yr_rates, 3*365):6.2f}%  (n={len(yr_rates)})")
