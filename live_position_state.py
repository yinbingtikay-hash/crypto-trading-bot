"""將 bot 自己實際買入嘅倉位（數量、進場價、要持有到幾時）持久化落本機 JSON
檔案，同 crypto-trading-bot-ema 個project一樣嘅原因：交易所帳戶結餘會被
Testnet 派發嘅模擬資金污染，唔可以靠 fetch_base_position() 查「戶口而家
有幾多」嚟決定平倉數量。Funding Squeeze 冇止損/止盈價位（已驗證：加咗
反而拖低表現），淨係持到指定嘅 funding 事件次數後就走，所以呢度存嘅係
「幾時到期」，唔係價位。
"""

import json
import os
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PersistedPosition:
    side: str
    entry_price: float
    quantity: float
    entry_time: str
    exit_due_after_funding_ts: int  # 到咗呢個 funding event 時間戳(秒)或之後就平倉


def save_position_state(path: str, position: PersistedPosition) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(asdict(position), f)


def load_position_state(path: str) -> PersistedPosition | None:
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    return PersistedPosition(**data)


def clear_position_state(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)
