"""
Event-driven backtest loop for V3(HTF bias 1D + sweep反手 4H)。
結構同backtest_engine_v2.py一樣,淨係將bias/entry兩層時間刻度搬咗去1D/4H,
兩層都由已cache嘅1H數據resample出嚟,唔使再問Binance攞新data。
"""
import pandas as pd

import config
import indicators as ind
import strategy_v3
import risk
from state import BotState, Position


def _resample(df_1h, interval):
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    df = df_1h.resample(interval).agg(agg).dropna()
    df["close_time"] = df.index + pd.Timedelta(interval)
    return df


def _align_bias_to_entry_tf(df_1d, df_4h):
    df_1d = df_1d.copy()
    # 用close_time嚟merge:1D bar要完全收咗先算「已知」,避免lookahead
    bias_by_close = df_1d.set_index("close_time")[["bias"]].sort_index()
    bias_by_close.index = bias_by_close.index.astype(df_4h.index.dtype)  # 對齊dtype,避免merge_asof報錯
    aligned = pd.merge_asof(
        df_4h.sort_index(), bias_by_close,
        left_index=True, right_index=True, direction="backward",
    )
    return aligned["bias"]


def run_backtest_v3(df_1h):
    df_1d = _resample(df_1h, config.BIAS_INTERVAL_V3)
    df_4h = _resample(df_1h, config.ENTRY_INTERVAL_V3)

    df_1d["bias"] = strategy_v3.get_bias(df_1d["close"])

    df_4h["swing_low"] = ind.rolling_swing_low(df_4h["low"], config.SWEEP_SWING_LOOKBACK_V3)
    df_4h["bias"] = _align_bias_to_entry_tf(df_1d, df_4h)
    df_4h = df_4h.dropna(subset=["swing_low", "bias"])

    state = BotState(equity=config.BACKTEST_INITIAL_EQUITY)
    trades = []
    rejected_signals = []
    pause_trigger_count = 0
    pending_entry = None  # 訊號bar收咗先記錄,下一支bar開市先真正入場

    for bar in df_4h.itertuples():
        bar_date = bar.Index.date()
        if state.trading_paused and state.current_day is not None and bar_date != state.current_day:
            # backtest代理規則(同v1/v2一致):新一日自動解除暫停,純粹為咗令backtest行得落去。
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

            # +1R移平本(同v2一致);TP唔變,淨係stop移。
            if not pos.breakeven_triggered:
                initial_r = (pos.take_profit_price - pos.entry_price) / config.TAKE_PROFIT_R_MULTIPLE
                breakeven_trigger_price = pos.entry_price + initial_r * config.BREAKEVEN_R_TRIGGER_V3
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

        signal, sweep_low_at_trigger = strategy_v3.check_sweep_entry(bar, bar.swing_low, bar.bias, state.sweep)
        if signal == strategy_v3.LONG_ENTRY_SIGNAL:
            pending_entry = {"sweep_low": sweep_low_at_trigger}

    return {
        "trades": pd.DataFrame(trades),
        "rejected_signals": rejected_signals,
        "final_equity": state.equity,
        "pause_trigger_count": pause_trigger_count,
    }
