"""
Risk Manager——stop/TP計算、部位sizing、下單前checklist。
呢個模組對每一張單都有否決權;呢度冇嘅嘢就係唔會執行。
"""
import config


def calc_stop_and_tp(entry_price, swing_low_value, atr_value):
    """
    舊版(已被v1.1取代做config.py預設):stop floor會令stop、TP一齊等比例
    擴闊,實測PF爬唔起(0.79-0.84打圈)。留低純粹做對比參考,backtest_engine.py
    而家call緊嘅係下面個calc_stop_and_tp_decoupled。
    """
    swing_dist = entry_price - swing_low_value if swing_low_value == swing_low_value else float("-inf")  # NaN-safe
    atr_dist = atr_value * config.STOP_ATR_MULTIPLIER
    stop_distance = max(swing_dist, atr_dist)   # 取較遠(較保守)嗰個
    floor_dist = entry_price * config.MIN_STOP_DISTANCE_PCT
    stop_distance = max(stop_distance, floor_dist)
    stop_price = entry_price - stop_distance
    tp_price = entry_price + stop_distance * config.TAKE_PROFIT_R_MULTIPLE
    return stop_price, tp_price


def calc_stop_and_tp_decoupled(entry_price, swing_low_value, atr_value):
    """
    v1.1定案版本(backtest_engine.py實際call緊嘅function):
    將stop floor同TP解耦——之前個MIN_STOP_DISTANCE_PCT floor會令stop、TP
    一齊等比例擴闊(因為TP=stop_distance×R),擴闊咗stop嘅同時都闊埋target,
    勝率跟住跌,冇實際解決到問題。呢個版本stop用闊嗰個(floor後)嘅距離,
    但TP繼續用原本(未floor前)嘅distance計,唔會因為stop闊咗而搬得更遠。
    已用train(2020-2023)/test(2024-2026) out-of-sample驗證過,floor=0.04
    喺兩段獨立都令PF>1,唔係overfit單一段,詳見memory。
    """
    swing_dist = entry_price - swing_low_value if swing_low_value == swing_low_value else float("-inf")
    atr_dist = atr_value * config.STOP_ATR_MULTIPLIER
    original_stop_distance = max(swing_dist, atr_dist)   # 原本(未floor)嘅stop距離,淨係用嚟計TP
    floor_dist = entry_price * config.MIN_STOP_DISTANCE_PCT
    widened_stop_distance = max(original_stop_distance, floor_dist)   # 真正落stop用呢個(可能闊咗)

    stop_price = entry_price - widened_stop_distance
    tp_price = entry_price + original_stop_distance * config.TAKE_PROFIT_R_MULTIPLE  # TP唔跟stop闊咗而搬
    return stop_price, tp_price


def calc_stop_and_tp_sweep(entry_price, sweep_low_value):
    """V2專用:stop擺喺sweep低位(結構性低點),唔加ATR floor——sweep嘅stop意義
    本身就係嗰個被掃嘅極端點,唔應該畀ATR將stop谷到更闊。"""
    stop_distance = entry_price - sweep_low_value
    tp_price = entry_price + stop_distance * config.TAKE_PROFIT_R_MULTIPLE
    return sweep_low_value, tp_price


def calc_stop_and_tp_skip_if_tight(entry_price, swept_low_value, min_stop_pct, buf_pct=0.0002):
    """
    V4專用,忠實跟用戶MNQ v3.3嘅做法:stop擺喺swept low(留一個細buffer,對應
    v3.3嘅bufTicks),但如果stop距離低過min_stop_pct,呢張單直接唔落(skip),
    唔會好似v1嗰種「擴闊stop」——v3.3原文係minStopTicks唔夠就skip,兩者機制
    唔同,v1個「擴闊」試過會連累TP一齊闊冇改善,呢度特登唔用嗰套。
    Returns (stop_price, tp_price) 或者 (None, None) 表示要skip。
    """
    stop_price = swept_low_value * (1 - buf_pct)
    stop_distance = entry_price - stop_price
    if stop_distance <= 0 or stop_distance / entry_price < min_stop_pct:
        return None, None
    tp_price = entry_price + stop_distance * config.TAKE_PROFIT_R_MULTIPLE
    return stop_price, tp_price


def calc_position_size(equity, entry_price, stop_price):
    stop_distance = entry_price - stop_price
    if stop_distance <= 0:
        return 0.0
    risk_amount = equity * config.RISK_PCT_PER_TRADE
    size = risk_amount / stop_distance
    max_pct = getattr(config, "MAX_POSITION_PCT_OF_EQUITY", None)
    if max_pct is not None:
        # 診斷實驗:stop好緊嗰陣cap注碼,寧願呢張單實際風險 < 0.5%,都唔好開到成equity咁大
        max_size = (equity * max_pct) / entry_price
        size = min(size, max_size)
    return size


def calc_position_size_fixed_fraction(equity, entry_price):
    """
    Aggressive小本模式專用:注碼=固定equity%(AGGRESSIVE_MODE_POSITION_FRACTION),
    唔理stop幾闊。同calc_position_size(risk-based)嘅分別:嗰個攞嚟做v1.1
    保守版,呢個先係用戶自己揀嘅、明確接受高回撤嘅細本滾大版。單一單嘅實際
    虧損上限=呢個fraction × stop distance%,唔會一鋪清袋,但連續輸會令回撤
    好大(見memory:30% fraction實測最大回撤-27%)。
    """
    fraction = config.AGGRESSIVE_MODE_POSITION_FRACTION
    return (equity * fraction) / entry_price


def pre_trade_checklist(state, size, entry_price):
    """
    注意:呢度嘅 cash_available 用 state.equity 做近似——因為呢個check發生喺
    無持倉嘅時候(max 1倉已經由no_open_position把關),backtest入面equity等於
    可用現金。Paper/live版本要改成查詢交易所實際free balance,唔可以照抄。
    """
    notional = size * entry_price
    checks = {
        "daily_loss_ok": state.daily_pnl_pct > -config.DAILY_LOSS_LIMIT_PCT,
        "consecutive_loss_ok": state.consecutive_losses < config.CONSECUTIVE_LOSS_LIMIT,
        "no_open_position": state.open_position is None,
        "size_positive": size > 0,
        "cash_available": notional <= state.equity,
        "not_paused": not state.trading_paused,
    }
    failed = [k for k, v in checks.items() if not v]
    return (len(failed) == 0), failed
