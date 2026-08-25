"""
Aggressive小本模式——同backtest_engine.py(v1.1)完全共用entry/exit邏輯
(strategy.py、risk.calc_stop_and_tp_decoupled),淨係將部位sizing換成
calc_position_size_fixed_fraction(固定30% equity,見config.py)。

⚠️ 呢個模式係用戶喺明確知道以下前提下自己揀嘅:
- 本金淨係$100-200,目標係「細本滾大」,而唔係v1.1嗰種低波動保守增值
- 接受回撤可以去到-27%(30% fraction實測),亦都接受策略最終蝕清袋嘅機率唔低
- 單一單嘅實際虧損上限=fraction×stop distance%,唔會一鋪清袋,但連續輸會令
  回撤好大,而且假設咗stop真係可以喺預期價位成交(急跌/交易所故障可以令
  實際滑價遠差過backtest假設)
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
    regime_by_close = df_1h.set_index("close_time")[["regime"]].sort_index()
    aligned = pd.merge_asof(
        df_15m.sort_index(), regime_by_close,
        left_index=True, right_index=True, direction="backward",
    )
    return aligned["regime"]


def run_backtest_aggressive(df_1h, df_15m):
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
    pending_entry = None

    for bar in df_15m.itertuples():
        bar_date = bar.Index.date()
        if state.trading_paused and state.current_day is not None and bar_date != state.current_day:
            state.trading_paused = False
            state.consecutive_losses = 0
        state.roll_day_if_needed(bar_date)

        if pending_entry is not None and state.open_position is None:
            fill_price = bar.open * (1 + config.SLIPPAGE_PCT)
            stop_price, tp_price = risk.calc_stop_and_tp_decoupled(
                fill_price, pending_entry["swing_low"], pending_entry["atr"])
            # Aggressive模式:固定equity%注碼,唔理stop幾闊
            size = risk.calc_position_size_fixed_fraction(state.equity, fill_price)
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
