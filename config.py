"""
Central config for Crypto Bot v1 (路線三:1H regime + 15m pullback, BTC/USDT spot).
所有參數集中喺度——其他模組唔應該有硬編碼嘅數字。
"""

SYMBOL = "BTCUSDT"
REGIME_INTERVAL = "1h"
ENTRY_INTERVAL = "15m"
BACKTEST_START = "2020-01-01"

EMA_REGIME_PERIOD = 200
EMA_REGIME_SLOPE_LOOKBACK = 20
EMA_ENTRY_PERIOD = 20
ATR_PERIOD = 14
SWING_LOOKBACK = 10

PULLBACK_BUFFER_PCT = 0.004
MAX_PULLBACK_BARS = 20
STOP_ATR_MULTIPLIER = 1.5
TAKE_PROFIT_R_MULTIPLE = 2.0

# v1.1定案(2026-07-19):stop距離下限,同TP解耦(TP唔跟住呢個floor擴闊,
# 淨係stop擴闊——見risk.calc_stop_and_tp_decoupled)。0.04=4%,已經用
# train(2020-2023)/test(2024-2026) out-of-sample驗證過,兩段獨立都PF>1,
# 唔係overfit單一段。詳見memory crypto-trading-bot-status.md。
MIN_STOP_DISTANCE_PCT = 0.04

RISK_PCT_PER_TRADE = 0.005
DAILY_LOSS_LIMIT_PCT = 0.02
CONSECUTIVE_LOSS_LIMIT = 3

# v1.1定案:假設用maker/限價單入場(唔係market/taker),手續費同滑價都平好多。
# ⚠️ 呢個假設要留意:限價單唔保證成交,實際可以成交嘅比例要用paper trade驗證,
# 呢個backtest假設咗100%都成交,可能偏樂觀。
TAKER_FEE_PCT = 0.0002   # 0.02%,maker/限價單假設(原本市價單taker係0.1%)
SLIPPAGE_PCT = 0.0002    # 0.02%,限價單成交價自己揀,滑價應該遠細過市價單

# Backtest 用嚟計算部位大小百分比嘅假設本金,純粹方便計數,唔係任何落錢建議。
# Paper/live 版本會改用交易所帳戶實際查詢返嚟嘅餘額。
BACKTEST_INITIAL_EQUITY = 10_000.0

# ============================================================
# V2:HTF bias(4H)+ sweep反手(15m)—— 路線三嘅新paradigm
# ============================================================
BIAS_INTERVAL_V2 = "4h"
BIAS_EMA_PERIOD_V2 = 50       # 50期*4H=200小時,同v1嘅EMA200(1H)=200小時同一個lookback horizon
SWEEP_SWING_LOOKBACK_V2 = 10  # 同v1 SWING_LOOKBACK概念一致
MAX_SWEEP_BARS_V2 = 20        # 同v1 MAX_PULLBACK_BARS概念一致
BREAKEVEN_R_TRIGGER_V2 = 1.0  # 對應你MNQ策略「+1R移平本」

# ============================================================
# V3:HTF bias(1D)+ sweep反手(4H)—— 路線三第3個paradigm
# market_characteristics.py量到15m/1H嘅Hurst exponent≈0.49-0.51(近乎random
# walk),4H/1D先輕微高過0.5(0.54/0.57)。v2用4H bias夾15m entry,entry嗰層
# 本身就冇structure;v3將bias、entry兩層都搬去Hurst較高嗰兩層,用嚟分辨
# v2蝕錢係因為sweep呢個做法本身唔work,定係entry timeframe本身冇edge可捕捉。
# ============================================================
BIAS_INTERVAL_V3 = "1d"
ENTRY_INTERVAL_V3 = "4h"
BIAS_EMA_PERIOD_V3 = 50       # 50日EMA,daily trend filter常見標準lookback
SWEEP_SWING_LOOKBACK_V3 = 10  # 同v2概念一致(10支entry-timeframe bar)
MAX_SWEEP_BARS_V3 = 20        # 同v2概念一致
BREAKEVEN_R_TRIGGER_V3 = 1.0  # 同v2一致,對應MNQ「+1R移平本」

# ============================================================
# Aggressive小本模式(2026-07-19):用戶明確話本金淨係$100-200,想「細本滾大」,
# 接受高機率蝕清袋。同v1.1嘅risk-based sizing唔同,呢度用「固定equity%」做
# 注碼(唔理stop幾闊)——entry/exit邏輯完全冇變,淨係sizing換咗。
# ⚠️ 呢個模式已經同用戶講清楚:回撤可以去到-40%以上,唔係v1.1嗰種保守設定,
# 用戶自己揀咗接受呢個風險,唔好之後再幫佢調鬆呢個門檻扮保守。
# ============================================================
AGGRESSIVE_MODE_POSITION_FRACTION = 0.90  # 每單用返成90% equity做注碼(用戶2026-07-19由30%改90%,已知會有-64%回撤)

# ============================================================
# V4:忠實跟返用戶MNQ「SMC Sweep+Structure v3.3」實際規則嘅BTC版
# 用戶貼咗真Pine code出嚟先寫得到呢個版本。同v2/v3嘅分別:HTF bias改用
# swing structure(HL/LH,唔係EMA);entry-timeframe swing改用真pivot(唔係
# rolling低位);entry trigger加咗「破位嗰支bar自己要係方向燭」;stop太緊
# 淨係skip(唔擴闊)。兩個timeframe組合都試:(1H bias/15m entry,同MNQ原版
# 顆粒度一樣)、(1D bias/4H entry,Hurst數據話呢層先有信號)。
# ============================================================
PIVOT_LEFT_RIGHT_BIAS_V4 = 2   # 對應v3.3 f_bias寫死嘅pivothigh/pivotlow(2,2)
PIVOT_LEN_ENTRY_V4 = 3         # 對應v3.3 pivLen預設3
MAX_SWEEP_BARS_V4 = 12         # 對應v3.3 confWindow預設12
BREAKEVEN_R_TRIGGER_V4 = 1.0   # 對應v3.3 beAtR預設1.0
MIN_STOP_PCT_V4 = 0.003        # BTC版嘅「避免stop太貼近零」下限,對應v3.3
                                # minStopTicks(20 tick,對MNQ嚟講都係好細嘅下限,
                                # 唔係好似Paradigm A個4%實驗咁做risk floor)——
                                # 純粹sanity check,唔係overfit揀出嚟嘅數。
