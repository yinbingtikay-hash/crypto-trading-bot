"""
Event-driven backtest loop——逐支15m bar行過,直接reuse strategy.py/risk.py
嘅function,唔係將策略邏輯另外喺呢度抄多一次(呢個係避免backtest/live邏輯
漂移嘅核心設計)。
"""
import pandas as pd

import config
import indicators as ind
import strategy
import risk
from state import BotState, Position


def _align_regime_to_15m(df_1h, df_15m):
    df_1h = df_1h.copy()
    df_1h["regime"] = strategy.get_regime(df_1h["close"])
    # 用close_time嚟merge:1H bar要完全收咗先算「已知」,避免lookahead
    regime_by_close = df_1h.set_index("close_time")[["regime"]].sort_index()
    aligned = pd.merge_asof(
        df_15m.sort_index(), regime_by_close,
        left_index=True, right_index=True, direction="backward",
    )
    return aligned["regime"]


def run_backtest(df_1h, df_15m):
    df_15m = df_15m.copy()
    df_15m["ema20"] = ind.ema(df_15m["close"], config.EMA_ENTRY_PERIOD)
    df_15m["swing_low"] = ind.rolling_swing_low(df_15m["low"], config.SWING_LOOKBACK)
    df_15m["atr"] = ind.atr(df_15m["high"], df_15m["low"], df_15m["close"], config.ATR_PERIOD)
    df_15m["regime"] = _align_regime_to_15m(df_1h, df_15m)
    df_15m = df_15m.dropna(subset=["ema20", "swing_low", "atr", "regime"])

    state = BotState(equity=config.BACKTEST_INITIAL_EQUITY)
    trades = []
    rejected_signals = []
    pause_trigger_count = 0
    pending_entry = None  # 訊號bar收咗先記錄,下一支bar開市先真正入場

    for bar in df_15m.itertuples():
        bar_date = bar.Index.date()
        if state.trading_paused and state.current_day is not None and bar_date != state.current_day:
            # backtest代理規則:模擬「新一日已經人手review完」先解除暫停。
            # 呢個淨係為咗令backtest可以行落去——live/paper版本Q7嘅真實規則
            # 係要用戶親自確認先解除,唔會自動翻set,詳見live safety checklist(task#5)。
            state.trading_paused = False
            state.consecutive_losses = 0  # 解除暫停=當自己已經reset,唔係就會永久卡死(曾經係bug)
        state.roll_day_if_needed(bar_date)

        if pending_entry is not None and state.open_position is None:
            fill_price = bar.open * (1 + config.SLIPPAGE_PCT)
            # v1.1定案:stop/TP解耦(stop用MIN_STOP_DISTANCE_PCT floor擴闊,
            # TP繼續用原本未floor嘅distance計,唔會跟住stop闊而搬更遠)
            stop_price, tp_price = risk.calc_stop_and_tp_decoupled(
                fill_price, pending_entry["swing_low"], pending_entry["atr"])
            size = risk.calc_position_size(state.equity, fill_price, stop_price)
            ok, failed = risk.pre_trade_checklist(state, size, fill_price)
            if ok:
                fee = fill_price * size * config.TAKER_FEE_PCT
                state.equity -= fee
                state.open_position = Position(
                    entry_price=fill_price, stop_price=stop_price,
                    take_profit_price=tp_price, size=size, entry_time=bar.Index,
                )
            else:
                rejected_signals.append({"time": bar.Index, "reason": failed})
            pending_entry = None

        if state.open_position is not None:
            pos = state.open_position
            hit_stop = bar.low <= pos.stop_price
            hit_tp = bar.high >= pos.take_profit_price
            exit_price = None
            if hit_stop:                      # 同一支bar兩者都中,保守假設stop先中
                exit_price = pos.stop_price * (1 - config.SLIPPAGE_PCT)
            elif hit_tp:
                exit_price = pos.take_profit_price * (1 - config.SLIPPAGE_PCT)

            if exit_price is not None:
                pnl = (exit_price - pos.entry_price) * pos.size
                pnl -= exit_price * pos.size * config.TAKER_FEE_PCT
                state.equity += pnl
                state.consecutive_losses = state.consecutive_losses + 1 if pnl < 0 else 0
                trades.append({
                    "entry_time": pos.entry_time, "exit_time": bar.Index,
                    "entry_price": pos.entry_price, "exit_price": exit_price,
                    "size": pos.size, "pnl": pnl, "equity_after": state.equity,
                })
                state.open_position = None
                if state.consecutive_losses >= config.CONSECUTIVE_LOSS_LIMIT and not state.trading_paused:
                    state.trading_paused = True
                    pause_trigger_count += 1

        state.update_daily_pnl()

        if state.open_position is not None or pending_entry is not None:
            continue

        signal = strategy.check_entry(bar, bar.ema20, bar.swing_low, bar.regime, state.pullback)
        if signal == strategy.LONG_ENTRY_SIGNAL:
            pending_entry = {"swing_low": bar.swing_low, "atr": bar.atr}

    return {
        "trades": pd.DataFrame(trades),
        "rejected_signals": rejected_signals,
        "final_equity": state.equity,
        "pause_trigger_count": pause_trigger_count,
    }
