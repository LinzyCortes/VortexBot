# ============================================
# VORTEX BOT - TECHNICAL INDICATORS
# ============================================

import pandas as pd
import numpy as np
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from config import cfg
from logger import logger


class Indicators:

    # ─── DATA PREPARATION ───────────────────

    @staticmethod
    def ohlcv_to_df(ohlcv: list) -> pd.DataFrame:
        """Konversi raw OHLCV ke DataFrame"""
        try:
            df = pd.DataFrame(
                ohlcv,
                columns=["timestamp", "open", "high",
                         "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(
                df["timestamp"], unit="ms"
            )
            df.set_index("timestamp", inplace=True)
            df = df.astype(float)
            return df
        except Exception as e:
            logger.error(f"❌ OHLCV to df error: {e}")
            return pd.DataFrame()

    # ─── TREND INDICATORS ───────────────────

    @staticmethod
    def ema(df: pd.DataFrame,
            period: int,
            column: str = "close") -> pd.Series:
        """Exponential Moving Average"""
        try:
            ema = EMAIndicator(
                close=df[column], window=period
            )
            return ema.ema_indicator()
        except Exception as e:
            logger.error(f"❌ EMA error: {e}")
            return pd.Series(dtype=float)

    @staticmethod
    def macd(df: pd.DataFrame) -> dict:
        """MACD Indicator"""
        try:
            macd_ind = MACD(
                close      =df["close"],
                window_fast=cfg.MACD_FAST,
                window_slow=cfg.MACD_SLOW,
                window_sign=cfg.MACD_SIGNAL,
            )
            return {
                "macd"     : macd_ind.macd(),
                "signal"   : macd_ind.macd_signal(),
                "histogram": macd_ind.macd_diff(),
            }
        except Exception as e:
            logger.error(f"❌ MACD error: {e}")
            return {}

    @staticmethod
    def adx(df: pd.DataFrame) -> dict:
        """ADX - Trend Strength"""
        try:
            adx_ind = ADXIndicator(
                high  =df["high"],
                low   =df["low"],
                close =df["close"],
                window=cfg.ADX_PERIOD,
            )
            return {
                "adx"   : adx_ind.adx(),
                "di_pos": adx_ind.adx_pos(),
                "di_neg": adx_ind.adx_neg(),
            }
        except Exception as e:
            logger.error(f"❌ ADX error: {e}")
            return {}

    # ─── MOMENTUM INDICATORS ────────────────

    @staticmethod
    def rsi(df: pd.DataFrame) -> pd.Series:
        """RSI Indicator"""
        try:
            rsi_ind = RSIIndicator(
                close =df["close"],
                window=cfg.RSI_PERIOD,
            )
            return rsi_ind.rsi()
        except Exception as e:
            logger.error(f"❌ RSI error: {e}")
            return pd.Series(dtype=float)

    # ─── VOLATILITY INDICATORS ──────────────

    @staticmethod
    def bollinger_bands(df: pd.DataFrame) -> dict:
        """Bollinger Bands"""
        try:
            bb = BollingerBands(
                close     =df["close"],
                window    =cfg.BB_PERIOD,
                window_dev=cfg.BB_STD,
            )
            return {
                "upper" : bb.bollinger_hband(),
                "middle": bb.bollinger_mavg(),
                "lower" : bb.bollinger_lband(),
                "width" : bb.bollinger_wband(),
                "pband" : bb.bollinger_pband(),
            }
        except Exception as e:
            logger.error(f"❌ BB error: {e}")
            return {}

    @staticmethod
    def atr(df: pd.DataFrame) -> pd.Series:
        """Average True Range"""
        try:
            atr_ind = AverageTrueRange(
                high  =df["high"],
                low   =df["low"],
                close =df["close"],
                window=cfg.ATR_PERIOD,
            )
            return atr_ind.average_true_range()
        except Exception as e:
            logger.error(f"❌ ATR error: {e}")
            return pd.Series(dtype=float)

    # ─── VOLUME INDICATORS ──────────────────

    @staticmethod
    def volume_analysis(df: pd.DataFrame) -> dict:
        """Analisa volume"""
        try:
            vol_ma      = df["volume"].rolling(
                window=cfg.VOLUME_MA
            ).mean()
            current_vol = float(df["volume"].iloc[-1])
            avg_vol     = float(vol_ma.iloc[-1])

            return {
                "current"  : current_vol,
                "average"  : avg_vol,
                "ratio"    : (
                    current_vol / avg_vol
                    if avg_vol > 0 else 0
                ),
                "above_avg": current_vol > avg_vol,
                "volume_ma": vol_ma,
            }
        except Exception as e:
            logger.error(f"❌ Volume error: {e}")
            return {}

    # ─── CANDLE PATTERNS ────────────────────

    @staticmethod
    def detect_candle_pattern(df: pd.DataFrame) -> dict:
        """Deteksi pola candlestick"""
        try:
            # Butuh minimal 3 candle
            if len(df) < 3:
                return {
                    "patterns" : [],
                    "direction": None,
                    "detected" : False,
                    "body_pct" : 0,
                }

            # Ambil nilai sebagai float
            last  = df.iloc[-1]
            prev  = df.iloc[-2]
            prev2 = df.iloc[-3]

            open_  = float(last["open"])
            high   = float(last["high"])
            low    = float(last["low"])
            close  = float(last["close"])

            prev_open  = float(prev["open"])
            prev_close = float(prev["close"])

            prev2_open  = float(prev2["open"])
            prev2_close = float(prev2["close"])

            # Body & wick calculations
            body       = abs(close - open_)
            candle_range = high - low
            body_pct   = (
                body / candle_range
                if candle_range > 0 else 0
            )
            upper_wick = high - max(open_, close)
            lower_wick = min(open_, close) - low

            prev_body  = abs(prev_close - prev_open)
            prev2_body = abs(prev2_close - prev2_open)

            patterns = []

            # ── Bullish Engulfing ────────────
            if (close > open_ and
                    prev_close < prev_open and
                    close > prev_open and
                    open_ < prev_close):
                patterns.append("Bullish Engulfing")

            # ── Bearish Engulfing ────────────
            if (close < open_ and
                    prev_close > prev_open and
                    close < prev_open and
                    open_ > prev_close):
                patterns.append("Bearish Engulfing")

            # ── Bullish Pin Bar (Hammer) ─────
            if (body > 0 and
                    lower_wick > body * 2 and
                    upper_wick < body * 0.5 and
                    body_pct < 0.4):
                patterns.append("Bullish Pin Bar")

            # ── Bearish Pin Bar (Shooting Star)
            if (body > 0 and
                    upper_wick > body * 2 and
                    lower_wick < body * 0.5 and
                    body_pct < 0.4):
                patterns.append("Bearish Pin Bar")

            # ── Doji ─────────────────────────
            if body_pct < 0.1:
                patterns.append("Doji")

            # ── Morning Star ─────────────────
            if (prev2_body > 0 and
                    prev2_close < prev2_open and
                    prev_body < prev2_body * 0.3 and
                    close > open_ and
                    close > (prev2_open + prev2_close) / 2):
                patterns.append("Morning Star")

            # ── Evening Star ─────────────────
            if (prev2_body > 0 and
                    prev2_close > prev2_open and
                    prev_body < prev2_body * 0.3 and
                    close < open_ and
                    close < (prev2_open + prev2_close) / 2):
                patterns.append("Evening Star")

            # ── Tentukan arah ────────────────
            bullish_patterns = [
                "Bullish Engulfing",
                "Bullish Pin Bar",
                "Morning Star",
            ]
            bearish_patterns = [
                "Bearish Engulfing",
                "Bearish Pin Bar",
                "Evening Star",
            ]

            direction = None
            if any(p in bullish_patterns for p in patterns):
                direction = "BUY"
            elif any(p in bearish_patterns for p in patterns):
                direction = "SELL"

            return {
                "patterns" : patterns,
                "direction": direction,
                "detected" : len(patterns) > 0,
                "body_pct" : body_pct,
            }

        except Exception as e:
            logger.error(f"❌ Candle pattern error: {e}")
            return {
                "patterns" : [],
                "direction": None,
                "detected" : False,
                "body_pct" : 0,
            }

    # ─── FULL INDICATOR CALCULATION ─────────

    def calculate_all(self, df: pd.DataFrame) -> dict:
        """Hitung semua indikator sekaligus"""
        try:
            if df.empty or len(df) < 50:
                return {}

            # ── EMA Fibonacci ────────────────
            ema_fast_series = self.ema(df, cfg.EMA_FAST)
            ema_slow_series = self.ema(df, cfg.EMA_SLOW)

            if ema_fast_series.empty or ema_slow_series.empty:
                return {}

            # ── MACD ─────────────────────────
            macd_data = self.macd(df)
            if not macd_data:
                return {}

            # ── RSI ──────────────────────────
            rsi_series = self.rsi(df)
            if rsi_series.empty:
                return {}

            # ── ADX ──────────────────────────
            adx_data = self.adx(df)
            if not adx_data:
                return {}

            # ── Bollinger Bands ──────────────
            bb_data = self.bollinger_bands(df)
            if not bb_data:
                return {}

            # ── ATR ──────────────────────────
            atr_series = self.atr(df)
            if atr_series.empty:
                return {}

            # ── Volume ───────────────────────
            vol_data = self.volume_analysis(df)

            # ── Candle Pattern ───────────────
            candle = self.detect_candle_pattern(df)

            # ── Nilai terkini ─────────────────
            last_close     = float(df["close"].iloc[-1])
            last_high      = float(df["high"].iloc[-1])
            last_low       = float(df["low"].iloc[-1])
            last_ema_fast  = float(ema_fast_series.iloc[-1])
            last_ema_slow  = float(ema_slow_series.iloc[-1])
            last_rsi       = float(rsi_series.iloc[-1])
            last_adx       = float(adx_data["adx"].iloc[-1])
            last_macd_hist = float(
                macd_data["histogram"].iloc[-1]
            )
            last_atr       = float(atr_series.iloc[-1])

            # ── EMA crossover detection ──────
            ema_bullish    = last_ema_fast > last_ema_slow
            prev_ema_fast  = float(ema_fast_series.iloc[-2])
            prev_ema_slow  = float(ema_slow_series.iloc[-2])

            ema_cross_up   = (
                last_ema_fast > last_ema_slow and
                prev_ema_fast <= prev_ema_slow
            )
            ema_cross_down = (
                last_ema_fast < last_ema_slow and
                prev_ema_fast >= prev_ema_slow
            )

            # ── BB values ───────────────────
            bb_upper  = float(bb_data["upper"].iloc[-1])
            bb_middle = float(bb_data["middle"].iloc[-1])
            bb_lower  = float(bb_data["lower"].iloc[-1])
            bb_width  = float(bb_data["width"].iloc[-1])

            return {
                # ── EMA
                "ema_fast"        : last_ema_fast,
                "ema_slow"        : last_ema_slow,
                "ema_bullish"     : ema_bullish,
                "ema_cross_up"    : ema_cross_up,
                "ema_cross_down"  : ema_cross_down,

                # ── RSI
                "rsi"             : last_rsi,
                "rsi_overbought"  : last_rsi > cfg.RSI_OVERBOUGHT,
                "rsi_oversold"    : last_rsi < cfg.RSI_OVERSOLD,
                "rsi_neutral"     : (
                    cfg.RSI_NEUTRAL_LOW
                    <= last_rsi <=
                    cfg.RSI_NEUTRAL_HI
                ),

                # ── MACD
                "macd_histogram"  : last_macd_hist,
                "macd_bullish"    : last_macd_hist > 0,
                "macd_bearish"    : last_macd_hist < 0,

                # ── ADX
                "adx"             : last_adx,
                "trend_strong"    : last_adx > cfg.ADX_THRESHOLD,

                # ── ATR
                "atr"             : last_atr,
                "atr_pct"         : (
                    last_atr / last_close * 100
                    if last_close > 0 else 0
                ),

                # ── Bollinger Bands
                "bb_upper"        : bb_upper,
                "bb_middle"       : bb_middle,
                "bb_lower"        : bb_lower,
                "bb_width"        : bb_width,

                # ── Volume
                "volume_ratio"    : vol_data.get("ratio", 0),
                "volume_above_avg": vol_data.get(
                    "above_avg", False
                ),

                # ── Candle Pattern
                "candle_pattern"  : candle.get("patterns", []),
                "candle_direction": candle.get("direction"),
                "candle_detected" : candle.get("detected", False),

                # ── Price
                "close"           : last_close,
                "high"            : last_high,
                "low"             : last_low,
            }

        except Exception as e:
            logger.error(f"❌ Calculate all error: {e}")
            return {}


# Instance siap pakai
indicators = Indicators()