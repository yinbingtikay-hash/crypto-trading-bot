"""Backtest/paper/live 共用嘅mutable state。"""
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class PullbackTracker:
    in_pullback: bool = False
    pullback_high: Optional[float] = None
    bars_in_pullback: int = 0

    def reset(self):
        self.in_pullback = False
        self.pullback_high = None
        self.bars_in_pullback = 0


@dataclass
class SweepTracker:
    """V2用:追蹤一支跌穿swing low(sweep)嘅bar,等後續bar break返sweep bar嘅high先確認反手。"""
    in_sweep: bool = False
    sweep_high: Optional[float] = None
    sweep_low: Optional[float] = None
    bars_since_sweep: int = 0

    def reset(self):
        self.in_sweep = False
        self.sweep_high = None
        self.sweep_low = None
        self.bars_since_sweep = 0


@dataclass
class Position:
    entry_price: float
    stop_price: float
    take_profit_price: float
    size: float
    entry_time: pd.Timestamp
    breakeven_triggered: bool = False  # V2用:+1R後stop係咪已經移咗去entry


@dataclass
class BotState:
    equity: float
    open_position: Optional[Position] = None
    pullback: PullbackTracker = field(default_factory=PullbackTracker)
    sweep: SweepTracker = field(default_factory=SweepTracker)

    current_day: Optional[object] = None
    daily_start_equity: float = 0.0
    daily_pnl_pct: float = 0.0

    consecutive_losses: int = 0
    trading_paused: bool = False

    def roll_day_if_needed(self, bar_date):
        if self.current_day != bar_date:
            self.current_day = bar_date
            self.daily_start_equity = self.equity
            self.daily_pnl_pct = 0.0

    def update_daily_pnl(self):
        if self.daily_start_equity > 0:
            self.daily_pnl_pct = (self.equity - self.daily_start_equity) / self.daily_start_equity
