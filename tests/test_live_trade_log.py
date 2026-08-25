"""live_trade_log.py 同 crypto-trading-bot-ema 個project嘅trade_log.py邏輯一樣
（已經測試過），呢度淨係做smoke test確認呢份copy冇手民之誤。"""

import live_trade_log as trade_log


def test_build_closed_trade_computes_pnl():
    trade = trade_log.build_closed_trade("t0", "t1", "BUY", 100.0, 104.0, 2.0, "TIME")
    assert trade.pnl_usdt == 8.0
    assert trade.pnl_pct == 4.0


def test_record_and_summarize_round_trip(tmp_path):
    path = str(tmp_path / "trades.csv")
    trade_log.record_trade(path, trade_log.build_closed_trade("t0", "t1", "BUY", 100.0, 110.0, 1.0, "TIME"))
    trade_log.record_trade(path, trade_log.build_closed_trade("t2", "t3", "BUY", 100.0, 95.0, 1.0, "TIME"))

    summary = trade_log.summarize(path)

    assert summary["total_trades"] == 2
    assert summary["wins"] == 1
    assert summary["losses"] == 1
