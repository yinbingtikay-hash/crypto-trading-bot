"""逐筆交易記錄：平倉果刻計實際賺蝕，寫入 CSV，同提供彙總統計。

刻意唔靠「戶口總餘額前後對比」嚟判斷賺蝕——Testnet 帳戶會被交易所自己
不定時派發嘅隨機模擬資金污染，總餘額變化唔可信（呢個教訓喺
crypto-trading-bot-ema 個project踩過，詳見memory）。呢度淨係計算「呢筆
交易本身」由進場到平倉嘅實際差價，同帳戶其餘資金完全無關。
"""

import csv
import os
from dataclasses import asdict, dataclass

CSV_FIELDS = [
    "entry_time", "exit_time", "side", "entry_price", "exit_price",
    "quantity", "pnl_usdt", "pnl_pct", "exit_reason",
]


@dataclass(frozen=True)
class ClosedTrade:
    entry_time: str
    exit_time: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl_usdt: float
    pnl_pct: float
    exit_reason: str


def build_closed_trade(entry_time, exit_time, side, entry_price, exit_price, quantity, exit_reason) -> ClosedTrade:
    direction = 1 if side == "BUY" else -1
    pnl_usdt = (exit_price - entry_price) * quantity * direction
    pnl_pct = (exit_price - entry_price) / entry_price * 100 * direction if entry_price else 0.0

    return ClosedTrade(
        entry_time=str(entry_time),
        exit_time=str(exit_time),
        side=side,
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        pnl_usdt=pnl_usdt,
        pnl_pct=pnl_pct,
        exit_reason=exit_reason,
    )


def record_trade(log_path: str, trade: ClosedTrade) -> None:
    file_exists = os.path.exists(log_path)
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)

    with open(log_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(asdict(trade))


def read_trades(log_path: str) -> list[dict]:
    if not os.path.exists(log_path):
        return []

    with open(log_path, newline="") as f:
        return list(csv.DictReader(f))


def summarize(log_path: str) -> dict:
    rows = read_trades(log_path)
    total = len(rows)

    if total == 0:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0,
            "total_pnl_usdt": 0.0, "avg_pnl_usdt": 0.0, "profit_factor": None,
        }

    pnls = [float(r["pnl_usdt"]) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": len(wins) / total * 100,
        "total_pnl_usdt": sum(pnls),
        "avg_pnl_usdt": sum(pnls) / total,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else None,
    }
