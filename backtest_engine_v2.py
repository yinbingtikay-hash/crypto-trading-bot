"""
Event-driven backtest loop for V2(HTF bias 4H + sweep反手 15m)。
重用config/indicators/risk/state嘅原有code,淨係entry邏輯換咗做strategy_v2。
4H數據由已cache嘅1H resample出嚟,唔使再問Binance攞。
"""
import pandas as pd

import config
import indicators as ind
import strategy_v2
import risk
from state import BotState, Position


def _resample_4h(df_1h):
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    df_4h = df_1h.resample(config.BIAS_INTERVAL_V2).agg(agg).dropna()
    df_4h["close_time"] = df_4h.index + pd.Timedelta(config.BIAS_INTERVAL_V2)
    return df_4h


def _align_bias_to_15m(df_4h, df_15m):
    df_4h = df_4h.copy()
    df_4h["bias"] = strategy_v2.get_bias(df_4h["close"])
    # 用close_time嚟merge:4H bar要完全收咗先算「已知」,避免lookahead
    bias_by_close = df_4h.set_index("close_time")[["bias"]].sort_index()
    bias_by_close.index = bias_by_close.index.astype(df_15m.index.dtype)  # 對齊dtype,避免merge_asof報錯
    aligned = pd.merge_asof(
        df_15m.sort_index(), bias_by_close,
        left_index=True, right_index=True, direction="backward",
    )
    return aligned["bias"]


def run_backtest_v2(df_1h, df_15m):
    df_4h = _resample_4h(df_1h)

    df_15m = df_15m.copy()
    df_15m["swing_low"] = ind.rolling_swing_low(df_15m["low"], config.SWEEP_SWING_LOOKBACK_V2)
    df_15m["bias"] = _align_bias_to_15m(df_4h, df_15m)
    df_15m = df_15m.dropna(subset=["swing_low", "bias"])

    state = BotState(equity=config.BACKTEST_INITIAL_EQUITY)
    trades = []
    rejected_signals = []
    pause_trigger_count = 0
    pending_entry = None  # 訊號bar收咗先記錄,下一支bar開市先真正入場

    for bar in df_15m.itertuples():
        bar_date = bar.Index.date()
        if state.trading_paused and state.current_day is not None and bar_date != state.current_day:
            # backtest代理規則(同v1一致):新一日自動解除暫停,純粹為咗令backtest行得落去。
            # Live/paper要用戶人手review先解除,唔可以自動重啟。
            state.trading_paused = False
            state.consecutive_losses = 0
        state.roll_day_if_needed(bar_date)

        if pending_entry is not None and state.open_position is None:
            fill_price = bar.open * (1 + config.SLIPPAGE_PCT)
            stop_price, tp_price = risk.calc_stop_and_tp_sweep(fill_price, pending_entry["sweep_low"])
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

            # +1R移平本(對應MNQ策略「+1R移平本」);TP唔變,淨係stop移。
            # 簡化假設:當支bar先觸發breakeven,先至再check停損/止賺,即係假設
            # 「移平本」喺bar入面發生咗先,而唔理intrabar真實次序(冇tick data)。
            if not pos.breakeven_triggered:
                initial_r = (pos.take_profit_price - pos.entry_price) / config.TAKE_PROFIT_R_MULTIPLE
                breakeven_trigger_price = pos.entry_price + initial_r * config.BREAKEVEN_R_TRIGGER_V2
                if bar.high >= breakeven_trigger_price:
                    pos.stop_price = pos.entry_price
                    pos.breakeven_triggered = True

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
                    "breakeven_triggered": pos.breakeven_triggered,
                })
                state.open_position = None
                if state.consecutive_losses >= config.CONSECUTIVE_LOSS_LIMIT and not state.trading_paused:
                    state.trading_paused = True
                    pause_trigger_count += 1

        state.update_daily_pnl()

        if state.open_position is not None or pending_entry is not None:
            continue

        signal, sweep_low_at_trigger = strategy_v2.check_sweep_entry(bar, bar.swing_low, bar.bias, state.sweep)
        if signal == strategy_v2.LONG_ENTRY_SIGNAL:
            pending_entry = {"sweep_low": sweep_low_at_trigger}

    return {
        "trades": pd.DataFrame(trades),
        "rejected_signals": rejected_signals,
        "final_equity": state.equity,
        "pause_trigger_count": pause_trigger_count,
    }
