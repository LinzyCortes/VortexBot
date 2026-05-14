# ============================================
# VORTEX BOT - CONFIGURATION LOADER
# ============================================
#
# PHASE GUIDE (ubah di Railway Variables):
#
#   DEMO Phase 1  → MIN_CONFLUENCE_SCORE=10  MIN_RR=2.0
#   DEMO Phase 2  → MIN_CONFLUENCE_SCORE=13  MIN_RR=2.5
#   LIVE          → MIN_CONFLUENCE_SCORE=16  MIN_RR=3.0
#
#   Catatan: max score sekarang 20 poin (bukan 16)
#   setelah Stochastic + Breakout/Pullback ditambahkan.
#
#   Breakdown 20 poin:
#   EMA(1) + Stoch(2) + Vol(1) + Candle(1)         = 5
#   Breakout(2) + Pullback(1)                       = 3
#   BOS(2) + OB(2) + FVG(1) + Liq(1) + PD(1)       = 7
#   Fib618(2) + Fib50(1)                            = 3
#   Killzone(1) + News(1)                           = 2
#   TOTAL                                           = 20
#
# ============================================

import os
from dotenv import load_dotenv

load_dotenv()


class Config:

    # ─── EXCHANGE SELECTION ─────────────────
    EXCHANGE  = os.getenv("EXCHANGE", "okx").lower()
    IS_OKX    = EXCHANGE == "okx"
    IS_BYBIT  = EXCHANGE == "bybit"

    # ─── OKX CONFIG ─────────────────────────
    OKX_API_KEY    = os.getenv("OKX_API_KEY")
    OKX_API_SECRET = os.getenv("OKX_API_SECRET")
    OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE")
    OKX_MODE       = os.getenv("OKX_MODE", "demo")
    IS_OKX_DEMO    = OKX_MODE == "demo"

    # ─── BYBIT CONFIG ───────────────────────
    BYBIT_API_KEY    = os.getenv("BYBIT_API_KEY")
    BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET")
    BYBIT_MODE       = os.getenv("BYBIT_MODE", "testnet")
    IS_TESTNET       = BYBIT_MODE == "testnet"

    # ─── TELEGRAM ───────────────────────────
    TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    # ─── TRADING PAIRS ──────────────────────
    PAIRS = os.getenv(
        "PAIRS", "BTC-USDT-SWAP,ETH-USDT-SWAP"
    ).split(",")

    BACKTEST_PAIRS = os.getenv(
        "BACKTEST_PAIRS",
        "BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP"
    ).split(",")

    # ─── CAPITAL & RISK ─────────────────────
    CAPITAL            = float(os.getenv("CAPITAL", 10))
    RISK_PERCENT       = float(os.getenv("RISK_PERCENT", 1.0))
    MAX_LEVERAGE       = int(os.getenv("MAX_LEVERAGE", 5))
    MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PERCENT", 5.0))

    # ─── CAPITAL MODE ───────────────────────
    @staticmethod
    def get_capital_mode(balance: float) -> dict:
        if balance <= 5:
            return {
                "mode"           : "MICRO",
                "max_leverage"   : 3,
                "risk_percent"   : 1.0,
                "max_open_trades": 1,
            }
        elif balance <= 20:
            return {
                "mode"           : "SMALL",
                "max_leverage"   : 4,
                "risk_percent"   : 1.5,
                "max_open_trades": 2,
            }
        elif balance <= 100:
            return {
                "mode"           : "MEDIUM",
                "max_leverage"   : 5,
                "risk_percent"   : 1.5,
                "max_open_trades": 2,
            }
        else:
            return {
                "mode"           : "STANDARD",
                "max_leverage"   : 5,
                "risk_percent"   : 1.5,
                "max_open_trades": 3,
            }

    # ─── TIMEFRAMES ─────────────────────────
    TF_BIAS  = os.getenv("TF_BIAS",  "4H")
    TF_SETUP = os.getenv("TF_SETUP", "1H")
    TF_ENTRY = os.getenv("TF_ENTRY", "15m")

    # ─── CONFLUENCE ─────────────────────────
    # Max score sekarang 20 (naik dari 16)
    # Demo Phase 1 : 10  (bot bisa entry, collect data)
    # Demo Phase 2 : 13  (setelah konsisten profit)
    # Live         : 16  (full institutional)
    MIN_CONFLUENCE_SCORE = int(
        os.getenv("MIN_CONFLUENCE_SCORE", 10)
    )

    # ─── FIBONACCI ──────────────────────────
    FIB_RETRACEMENT = {
        "0.236": 0.236,
        "0.382": 0.382,
        "0.500": 0.500,
        "0.618": 0.618,
        "0.786": 0.786,
    }
    FIB_EXTENSION = {
        "1.272": 1.272,
        "1.618": 1.618,
        "2.618": 2.618,
    }

    # ─── RISK/REWARD ────────────────────────
    # Demo Phase 1 : MIN_RR=2.0
    # Demo Phase 2 : MIN_RR=2.5
    # Live         : MIN_RR=3.0
    MIN_RR    = float(os.getenv("MIN_RR", 2.0))
    TP1_RATIO = 1.272
    TP2_RATIO = 1.618
    TP3_RATIO = 2.618

    # ─── KILLZONE (WIB) ─────────────────────
    KILLZONES = {
        "london": {
            "open" : os.getenv("LONDON_OPEN",  "15:00"),
            "close": os.getenv("LONDON_CLOSE", "17:30"),
        },
        "new_york": {
            "open" : os.getenv("NY_OPEN",  "20:30"),
            "close": os.getenv("NY_CLOSE", "23:00"),
        },
    }

    # ─── EMA ────────────────────────────────
    EMA_FAST = int(os.getenv("EMA_FAST", 13))
    EMA_SLOW = int(os.getenv("EMA_SLOW", 21))

    # ─── STOCHASTIC (5,3,3) ─────────────────
    # Menggantikan RSI, MACD, ADX yang dihapus karena lagging
    # %K period=5 → responsif untuk 15m timeframe
    # smooth %K=3, smooth %D=3 → standard institutional setting
    STOCH_K_PERIOD = int(os.getenv("STOCH_K_PERIOD", 5))
    STOCH_D_SMOOTH = int(os.getenv("STOCH_D_SMOOTH", 3))
    STOCH_K_SMOOTH = int(os.getenv("STOCH_K_SMOOTH", 3))
    # Zone threshold
    STOCH_OVERSOLD   = int(os.getenv("STOCH_OVERSOLD",   20))
    STOCH_OVERBOUGHT = int(os.getenv("STOCH_OVERBOUGHT", 80))

    # ─── BOLLINGER BANDS ────────────────────
    BB_PERIOD = int(os.getenv("BB_PERIOD", 20))
    BB_STD    = int(os.getenv("BB_STD",     2))

    # ─── ATR ────────────────────────────────
    # Dipakai untuk SL dynamic (2.0x ATR)
    ATR_PERIOD    = int(os.getenv("ATR_PERIOD",    14))
    ATR_SL_MULT   = float(os.getenv("ATR_SL_MULT", 2.0))

    # ─── VOLUME ─────────────────────────────
    VOLUME_MA = int(os.getenv("VOLUME_MA", 20))

    # ─── VWAP ───────────────────────────────
    # Dipakai untuk institutional filter
    # Harga di bawah VWAP = discount zone (ideal BUY)
    # Harga di atas VWAP  = premium zone  (ideal SELL)
    VWAP_ENABLED       = os.getenv("VWAP_ENABLED", "true").lower() == "true"
    VWAP_TOLERANCE_PCT = float(os.getenv("VWAP_TOLERANCE_PCT", 0.3))

    # ─── FUNDING RATE ───────────────────────
    # Crypto-specific institutional filter
    # Hindari BUY saat funding rate sangat positif (longs membayar)
    # Hindari SELL saat funding rate sangat negatif (shorts membayar)
    FUNDING_RATE_ENABLED     = os.getenv("FUNDING_RATE_ENABLED", "true").lower() == "true"
    FUNDING_RATE_MAX_LONG    = float(os.getenv("FUNDING_RATE_MAX_LONG",   0.05))
    FUNDING_RATE_MAX_SHORT   = float(os.getenv("FUNDING_RATE_MAX_SHORT", -0.05))

    # ─── MARKET REGIME ──────────────────────
    # Auto-adjust parameter berdasarkan kondisi market
    REGIME_ENABLED = os.getenv("REGIME_ENABLED", "true").lower() == "true"
    # Di regime RANGING, naikkan threshold sedikit untuk skip noise
    REGIME_RANGING_SCORE_BOOST = int(os.getenv("REGIME_RANGING_SCORE_BOOST", 2))

    # ─── SMC SETTINGS ───────────────────────
    SMC_SWING_LOOKBACK = int(os.getenv("SMC_SWING_LOOKBACK", 15))
    FVG_MIN_SIZE       = float(os.getenv("FVG_MIN_SIZE",    0.05))
    OB_LOOKBACK        = int(os.getenv("OB_LOOKBACK",        20))
    LIQUIDITY_LOOKBACK = int(os.getenv("LIQUIDITY_LOOKBACK", 30))
    STRUCTURE_LOOKBACK = int(os.getenv("STRUCTURE_LOOKBACK", 50))

    # ─── BACKTEST ───────────────────────────
    BACKTEST_PHASES = [
        {"phase": 1, "capital": 10,  "weeks": 2},
        {"phase": 2, "capital": 50,  "weeks": 2},
        {"phase": 3, "capital": 100, "weeks": 2},
        {"phase": 4, "capital": 500, "weeks": 2},
    ]
    BACKTEST_HISTORY_YEARS = 2

    # ─── DATABASE & LOGGING ─────────────────
    DB_PATH  = "vortexbot.db"
    LOG_FILE = "vortexbot.log"


cfg = Config()