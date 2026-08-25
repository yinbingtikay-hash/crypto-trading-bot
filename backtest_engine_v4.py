"""
Event-driven backtest loop for V4(忠實SMC v3.3 rebuild)。同v2/v3同一個「訊號用
收市價、下一支bar開市價先執行」紀律——呢個比v3.3原本嘅process_orders_on_close=
true保守,即係我哋嘅結果會比直接搬v3.3過嚟再樂觀少少,呢個差異刻意保留,唔追
去同v3.3睇齊,因為次bar開市價先係避免lookahead嘅正確做法。

htf_interval/entry_interval由call嘅嗰邊揀,等同一套邏輯可以試(1h,15m)同
(1d,4h)兩種組合。
"""
import pandas as pd

import config
import indicators as ind
import risk
import strategy_v4
from state import BotState, Position


def _resample(df_1h, interval):
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    df = df_1h.resample(interval).agg(agg).dropna()
    df["close_time"] = df.index + pd.Timedelta(interval)
    return df


def _align_to_entry_tf(df_htf, df_entry, col):
    df_htf = df_htf.copy()
    by_close = df_htf.set_index("close_time")[[col]].sort_index()
    by_close.index = by_close.index.astype(df_entry.index.dtype)
    aligned = pd.merge_asof(
        df_entry.sort_index(), by_close,
        left_index=True, right_index=True, direction="backward",
    )
    return aligned[col]


def run_backtest_v4(df_htf, df_entry):
    """df_htf/df_entry要已經有open/high/low/close/close_time,由call嘅嗰邊
    (run_backtest_v4.py)決定係resample出嚟定係原生load(15m冇得由1h resample
    返嚟,因為1h已經冧咗intra-hour嘅資訊,只能靠原生15m data)。"""
    df_htf = df_htf.copy()
    df_htf["bias"] = strategy_v4.structural_bias(
        df_htf["high"], df_htf["low"], config.PIVOT_LEFT_RIGHT_BIAS_V4, config.PIVOT_LEFT_RIGHT_BIAS_V4)

    df_entry = df_entry.copy()
    df_entry["bias"] = _align_to_entry_tf(df_htf, df_entry, "bias")
    df_entry = df_entry.dropna(subset=["bias"])

    entries = strategy_v4.find_long_entries(
        df_entry, df_entry["bias"], config.PIVOT_LEN_ENTRY_V4, config.MAX_SWEEP_BARS_V4)
    entry_by_i = {e["i"]: e["swept_low"] for e in entries}

    state = BotState(equity=config.BACKTEST_INITIAL_EQUITY)
    trades = []
    skipped_tight_stop = 0
    rejected_signals = []
    pause_trigger_count = 0
    pending_entry = None
    n = len(df_entry)

    for i in range(n):
        bar = df_entry.iloc[i]
        bar_time = df_entry.index[i]
        bar_date = bar_time.date()
        if state.trading_paused and state.current_day is not None and bar_date != state.current_day:
            state.trading_paused = False
            state.consecutive_losses = 0
        state.roll_day_if_needed(bar_date)

        if pending_entry is not None and state.open_position is None:
            fill_price = bar["open"] * (1 + config.SLIPPAGE_PCT)
            stop_price, tp_price = risk.calc_stop_and_tp_skip_if_tight(
                fill_price, pending_entry["swept_low"], config.MIN_STOP_PCT_V4)
            if stop_price is None:
                skipped_tight_stop += 1
            else:
                size = risk.calc_position_size(state.equity, fill_price, stop_price)
                ok, failed = risk.pre_trade_checklist(state, size, fill_price)
                if ok:
                    fee = fill_price * size * config.TAKER_FEE_PCT
                    state.equity -= fee
                    state.open_position = Position(
                        entry_price=fill_price, stop_price=stop_price,
                        take_profit_price=tp_price, size=size, entry_time=bar_time,
                    )
                else:
                    rejected_signals.append({"time": bar_time, "reason": failed})
            pending_entry = None

        if state.open_position is not None:
            pos = state.open_position
            if not pos.breakeven_triggered:
                initial_r = (pos.take_profit_price - pos.entry_price) / config.TAKE_PROFIT_R_MULTIPLE
                be_trigger_price = pos.entry_price + initial_r * config.BREAKEVEN_R_TRIGGER_V4
                if bar["high"] >= be_trigger_price:
                    pos.stop_price = pos.entry_price
                    pos.breakeven_triggered = True

            hit_stop = bar["low"] <= pos.stop_price
            hit_tp = bar["high"] >= pos.take_profit_price
            exit_price = None
            if hit_stop:
                exit_price = pos.stop_price * (1 - config.SLIPPAGE_PCT)
            elif hit_tp:
                exit_price = pos.take_profit_price * (1 - config.SLIPPAGE_PCT)

            if exit_price is not None:
                pnl = (exit_price - pos.entry_price) * pos.size
                pnl -= exit_price * pos.size * config.TAKER_FEE_PCT
                state.equity += pnl
                state.consecutive_losses = state.consecutive_losses + 1 if pnl < 0 else 0
                trades.append({
                    "entry_time": pos.entry_time, "exit_time": bar_time,
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

        if i in entry_by_i:
            pending_entry = {"swept_low": entry_by_i[i]}

    return {
        "trades": pd.DataFrame(trades),
        "rejected_signals": rejected_signals,
        "skipped_tight_stop": skipped_tight_stop,
        "final_equity": state.equity,
        "pause_trigger_count": pause_trigger_count,
    }
