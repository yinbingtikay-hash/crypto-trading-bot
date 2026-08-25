"""驗證 live_main.py：進場/到期平倉/重複訊號去重/啟動對帳/Telegram指令。"""

import time

import pandas as pd
import pytest

import live_main as main_module
import live_position_state as position_state
from live_main import BotState, check_telegram_commands, reconcile_existing_position, run_once


@pytest.fixture(autouse=True)
def isolate_state_files(monkeypatch, tmp_path):
    monkeypatch.setattr("live_main.TRADE_LOG_PATH", str(tmp_path / "trade_history.csv"))
    monkeypatch.setattr("live_main.POSITION_STATE_PATH", str(tmp_path / "position_state.json"))


@pytest.fixture(autouse=True)
def reset_shutdown_flag():
    main_module._shutdown_requested = False
    yield
    main_module._shutdown_requested = False


class FakeConfig:
    symbol = "BTC/USDT"
    telegram_chat_id = "123"
    z_window = 540
    z_entry_threshold = -2.0
    hold_periods = 6


class FakeFetcher:
    def __init__(self, funding_df=None, equity=10_000.0, base_position=0.0, last_price=100.0, last_buy_price=None):
        self.config = FakeConfig()
        self._funding_df = funding_df
        self.equity = equity
        self.base_position = base_position
        self.last_price = last_price
        self.last_buy_price = last_buy_price
        self.orders = []

    def fetch_funding_history_df(self, min_periods):
        return self._funding_df

    def fetch_last_price(self):
        return self.last_price

    def fetch_quote_equity(self, currency):
        return self.equity

    def fetch_base_position(self, currency):
        return self.base_position

    def fetch_last_buy_average_price(self):
        return self.last_buy_price

    def create_market_order(self, side, amount):
        self.orders.append((side, amount))
        self.base_position = self.base_position + amount if side == "buy" else 0.0
        return {"id": "fake-order", "side": side, "amount": amount}


class FakeNotifier:
    def __init__(self, pending_updates=None):
        self.sent = []
        self.signal_calls = []
        self.entered_calls = []
        self.closed_calls = []
        self._pending_updates = pending_updates or []

    def get_updates(self, offset=None):
        updates = self._pending_updates
        self._pending_updates = []
        return updates

    def send(self, message):
        self.sent.append(message)

    def notify_signal(self, symbol, z_score, funding_rate):
        self.signal_calls.append((z_score, funding_rate))

    def notify_trade_executed(self, symbol, quantity, entry_price, hold_periods):
        self.entered_calls.append((quantity, entry_price))

    def notify_trade_closed(self, trade):
        self.closed_calls.append(trade)


def build_funding_df(n=545, signal_at_end=True):
    """製造一段funding rate歷史，最尾一粒觸發z<-2.0（用一個極端負值）。"""
    rates = [0.0001] * n
    if signal_at_end:
        rates[-1] = -0.01  # 遠低過其他值，一定會拉低z-score
    t = list(range(0, n * 28800, 28800))
    df = pd.DataFrame({"t": t, "rate": rates})
    return df


def test_enters_position_on_new_signal():
    df = build_funding_df()
    fetcher = FakeFetcher(funding_df=df, equity=10_000.0, last_price=100.0)
    notifier = FakeNotifier()
    state = BotState()

    run_once(fetcher, notifier, state)

    assert state.in_position is True
    assert len(notifier.entered_calls) == 1
    assert fetcher.orders[0][0] == "buy"


def test_does_not_reenter_for_same_signal():
    df = build_funding_df()
    fetcher = FakeFetcher(funding_df=df, equity=10_000.0, last_price=100.0)
    notifier = FakeNotifier()
    state = BotState()

    run_once(fetcher, notifier, state)
    # 平返手動模擬去返flat，但funding df未變(仲係同一個訊號)
    state.in_position = False
    state.current_position = None
    run_once(fetcher, notifier, state)

    assert len(fetcher.orders) == 1  # 冇再入場


def test_no_entry_when_no_signal():
    df = build_funding_df(signal_at_end=False)
    fetcher = FakeFetcher(funding_df=df)
    notifier = FakeNotifier()
    state = BotState()

    run_once(fetcher, notifier, state)

    assert state.in_position is False
    assert fetcher.orders == []


def test_does_not_exit_before_due_time():
    fetcher = FakeFetcher(base_position=0.5)
    notifier = FakeNotifier()
    state = BotState()
    state.in_position = True
    state.current_position = position_state.PersistedPosition(
        side="BUY", entry_price=100.0, quantity=0.5, entry_time="t0",
        exit_due_after_funding_ts=int(time.time()) + 3600,  # 未來
    )

    run_once(fetcher, notifier, state)

    assert state.in_position is True
    assert fetcher.orders == []


def test_exits_when_due_time_passed():
    fetcher = FakeFetcher(base_position=0.5, last_price=110.0)
    notifier = FakeNotifier()
    state = BotState()
    state.entry_time = "2024-01-01T00:00:00+00:00"
    state.in_position = True
    state.current_position = position_state.PersistedPosition(
        side="BUY", entry_price=100.0, quantity=0.5, entry_time=state.entry_time,
        exit_due_after_funding_ts=int(time.time()) - 10,  # 已過期
    )

    run_once(fetcher, notifier, state)

    assert state.in_position is False
    assert fetcher.orders == [("sell", 0.5)]
    assert len(notifier.closed_calls) == 1
    trade = notifier.closed_calls[0]
    assert trade.pnl_usdt > 0  # 110 > 100，賺錢


def test_reconcile_prefers_persisted_state(tmp_path, monkeypatch):
    monkeypatch.setattr("live_main.POSITION_STATE_PATH", str(tmp_path / "position.json"))
    pos = position_state.PersistedPosition("BUY", 100.0, 0.5, "t0", 999999999)
    position_state.save_position_state(str(tmp_path / "position.json"), pos)

    fetcher = FakeFetcher(base_position=2.0)  # 戶口結餘同記錄檔對唔上都無所謂,以記錄檔為準
    notifier = FakeNotifier()
    state = BotState()

    reconcile_existing_position(fetcher, notifier, state)

    assert state.in_position is True
    assert state.current_position.quantity == 0.5
    assert "本機記錄" in notifier.sent[0]


def test_reconcile_does_nothing_when_flat_and_no_state():
    fetcher = FakeFetcher(base_position=0.0)
    notifier = FakeNotifier()
    state = BotState()

    reconcile_existing_position(fetcher, notifier, state)

    assert state.in_position is False
    assert notifier.sent == []


def test_reconcile_warns_when_balance_exists_but_no_state():
    fetcher = FakeFetcher(base_position=0.3)
    notifier = FakeNotifier()
    state = BotState()

    reconcile_existing_position(fetcher, notifier, state)

    assert state.in_position is False  # 冇辦法推斷到期時間，唔會亂咁接管
    assert len(notifier.sent) == 1


def test_telegram_stop_command_triggers_shutdown():
    fetcher = FakeFetcher()
    notifier = FakeNotifier(pending_updates=[
        {"update_id": 1, "message": {"chat": {"id": 123}, "text": "/stop"}},
    ])
    state = BotState()

    check_telegram_commands(fetcher, notifier, state)

    assert main_module._shutdown_requested is True


def test_telegram_ignores_wrong_chat_id():
    fetcher = FakeFetcher()
    notifier = FakeNotifier(pending_updates=[
        {"update_id": 1, "message": {"chat": {"id": 999}, "text": "/stop"}},
    ])
    state = BotState()

    check_telegram_commands(fetcher, notifier, state)

    assert main_module._shutdown_requested is False
