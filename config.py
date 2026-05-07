# ============================================
# VORTEX BOT - CONFIGURATION LOADER
# ============================================
#
# PHASE GUIDE (ubah di Railway Variables):
#
#   DEMO Phase 1  → MIN_CONFLUENCE_SCORE=7  MIN_RR=2.0  ADX_THRESHOLD=20
#   DEMO Phase 2  → MIN_CONFLUENCE_SCORE=9  MIN_RR=2.5  ADX_THRESHOLD=22
#   LIVE          → MIN_CONFLUENCE_SCORE=11 MIN_RR=3.0  ADX_THRESHOLD=25
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
    # Demo Phase 1 : 7  (collect data, bot harus bisa entry)
    # Demo Phase 2 : 9  (setelah konsisten)
    # Live         : 11 (full institutional)
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
    # FIX: Diturunkan dari 3.0 → 2.0 untuk demo
    # Demo Phase 1 : MIN_RR=2.0 (realistis, BTC range normal)
    # Demo Phase 2 : MIN_RR=2.5
    # Live         : MIN_RR=3.0
    #
    # Kenapa 3.0 bermasalah di demo:
    # ATR 15m BTC ~$200, entry ke TP2 (1.618 ext) sering < RR 1:3
    # Bot paksa TP2 manual tapi tetap skip karena check di fibonacci.py
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

    # ─── INDICATORS ─────────────────────────
    EMA_FAST       = int(os.getenv("EMA_FAST", 13))
    EMA_SLOW       = int(os.getenv("EMA_SLOW", 21))
    RSI_PERIOD     = int(os.getenv("RSI_PERIOD", 14))
    RSI_OVERBOUGHT = int(os.getenv("RSI_OVERBOUGHT", 70))
    RSI_OVERSOLD   = int(os.getenv("RSI_OVERSOLD", 30))

    # FIX: Dilebarkan dari 40-60 → 35-65 untuk demo
    # Range 40-60 terlalu sempit — RSI 61 langsung gagal
    # padahal itu kondisi normal uptrend ringan.
    # Demo Phase 1 : 35-65
    # Demo Phase 2 : 38-62
    # Live         : 40-60 (kembali ketat)
    RSI_NEUTRAL_LOW = int(os.getenv("RSI_NEUTRAL_LOW", 35))
    RSI_NEUTRAL_HI  = int(os.getenv("RSI_NEUTRAL_HI",  65))

    MACD_FAST   = int(os.getenv("MACD_FAST",   12))
    MACD_SLOW   = int(os.getenv("MACD_SLOW",   26))
    MACD_SIGNAL = int(os.getenv("MACD_SIGNAL",  9))
    BB_PERIOD   = int(os.getenv("BB_PERIOD",   20))
    BB_STD      = int(os.getenv("BB_STD",       2))
    ATR_PERIOD  = int(os.getenv("ATR_PERIOD",  14))
    VOLUME_MA   = int(os.getenv("VOLUME_MA",   20))

    # FIX: Diturunkan dari 25 → 20 untuk demo
    # ADX > 25 butuh trend yang sudah jalan kuat.
    # Masalahnya: kalau ADX udah 25+ harga sering sudah
    # jauh dari OB — dua kondisi ini jarang bersamaan.
    # Demo Phase 1 : ADX_THRESHOLD=20
    # Demo Phase 2 : ADX_THRESHOLD=22
    # Live         : ADX_THRESHOLD=25
    ADX_PERIOD    = int(os.getenv("ADX_PERIOD",    14))
    ADX_THRESHOLD = int(os.getenv("ADX_THRESHOLD", 20))

    # ─── SMC SETTINGS ───────────────────────
    # FIX: SMC_SWING_LOOKBACK dinaikkan 10 → 15
    # Dengan lookback 10, di market choppy sering tidak
    # cukup swing points untuk detect struktur 4H.
    # 15 candle = 60 jam data di 4H — lebih representatif.
    SMC_SWING_LOOKBACK = int(os.getenv("SMC_SWING_LOOKBACK", 15))

    # FIX: FVG_MIN_SIZE diturunkan 0.1% → 0.05%
    # Di market low volatility BTC, FVG sering < 0.1%
    # tapi tetap valid secara SMC institutional.
    FVG_MIN_SIZE = float(os.getenv("FVG_MIN_SIZE", 0.05))

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