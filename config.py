# ============================================
# VORTEX BOT - CONFIGURATION LOADER
# ============================================

import os
from dotenv import load_dotenv

load_dotenv()

class Config:

    # ─── EXCHANGE SELECTION ─────────────────
    EXCHANGE     = os.getenv("EXCHANGE", "okx").lower()
    IS_OKX       = EXCHANGE == "okx"
    IS_BYBIT     = EXCHANGE == "bybit"

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
    # PENTING: Ubah nilai ini di Railway Variables Panel
    # Jangan ubah default di sini saja!
    # Railway: Settings → Variables → MIN_CONFLUENCE_SCORE = 7
    MIN_CONFLUENCE_SCORE = int(
        os.getenv("MIN_CONFLUENCE_SCORE", 7)
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
    MIN_RR    = 3.0
    TP1_RATIO = 1.272
    TP2_RATIO = 1.618
    TP3_RATIO = 2.618

    # ─── KILLZONE (WIB) ─────────────────────
    # Sinkron dengan SessionFilter di news_filter.py
    # London : 15:00 – 17:30 WIB
    # NY     : 20:30 – 23:00 WIB
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

    # ─── INDICATORS ─────────────────────────
    EMA_FAST        = 13
    EMA_SLOW        = 21
    RSI_PERIOD      = 14
    RSI_OVERBOUGHT  = 70
    RSI_OVERSOLD    = 30
    RSI_NEUTRAL_LOW = 40
    RSI_NEUTRAL_HI  = 60
    MACD_FAST       = 12
    MACD_SLOW       = 26
    MACD_SIGNAL     = 9
    BB_PERIOD       = 20
    BB_STD          = 2
    ATR_PERIOD      = 14
    ADX_PERIOD      = 14
    ADX_THRESHOLD   = 25
    VOLUME_MA       = 20

    # ─── SMC SETTINGS ───────────────────────
    SMC_SWING_LOOKBACK = 10
    FVG_MIN_SIZE       = 0.1
    OB_LOOKBACK        = 20
    LIQUIDITY_LOOKBACK = 30
    STRUCTURE_LOOKBACK = 50

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