# ============================================
# VORTEX BOT - TECHNICAL INDICATORS
# ============================================

import pandas as pd
import numpy as np
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
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

    # ─── MOMENTUM INDICATORS ────────────────

    @staticmethod
    def stochastic(df: pd.DataFrame,
                   k_period: int = 5,
                   d_smooth: int = 3,
                   k_smooth: int = 3) -> dict:
        """
        Stochastic Oscillator
        Default: %K panjang=5, penghalusan %K=3, penghalusan %D=3
        Sesuai request: Stoch(5,3,3)
        """
        try:
            stoch = StochasticOscillator(
                high   = df["high"],
                low    = df["low"],
                close  = df["close"],
                window = k_period,
                smooth_window = d_smooth,
            )
            k_line = stoch.stoch()
            d_line = stoch.stoch_signal()

            last_k    = float(k_line.iloc[-1])
            last_d    = float(d_line.iloc[-1])
            prev_k    = float(k_line.iloc[-2])
            prev_d    = float(d_line.iloc[-2])

            # Crossover detection
            cross_up   = (last_k > last_d) and (prev_k <= prev_d)
            cross_down = (last_k < last_d) and (prev_k >= prev_d)

            # Zone detection
            oversold   = last_k < 20 and last_d < 20
            overbought = last_k > 80 and last_d > 80

            # Bullish: crossover di oversold zone
            # Bearish: crossover di overbought zone
            bullish_signal = cross_up   and oversold
            bearish_signal = cross_down and overbought

            # Soft signal: crossover meski belum extreme zone
            soft_bullish = cross_up   and last_k < 50
            soft_bearish = cross_down and last_k > 50

            return {
                "k"              : last_k,
                "d"              : last_d,
                "k_line"         : k_line,
                "d_line"         : d_line,
                "cross_up"       : cross_up,
                "cross_down"     : cross_down,
                "oversold"       : oversold,
                "overbought"     : overbought,
                "bullish_signal" : bullish_signal,
                "bearish_signal" : bearish_signal,
                "soft_bullish"   : soft_bullish,
                "soft_bearish"   : soft_bearish,
            }
        except Exception as e:
            logger.error(f"❌ Stochastic error: {e}")
            return {
                "k": 50, "d": 50,
                "cross_up": False, "cross_down": False,
                "oversold": False, "overbought": False,
                "bullish_signal": False, "bearish_signal": False,
                "soft_bullish": False, "soft_bearish": False,
            }

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
            if len(df) < 3:
                return {
                    "patterns" : [],
                    "direction": None,
                    "detected" : False,
                    "body_pct" : 0,
                }

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

            body         = abs(close - open_)
            candle_range = high - low
            body_pct     = (
                body / candle_range
                if candle_range > 0 else 0
            )
            upper_wick = high - max(open_, close)
            lower_wick = min(open_, close) - low

            prev_body  = abs(prev_close - prev_open)
            prev2_body = abs(prev2_close - prev2_open)

            patterns = []

            if (close > open_ and
                    prev_close < prev_open and
                    close > prev_open and
                    open_ < prev_close):
                patterns.append("Bullish Engulfing")

            if (close < open_ and
                    prev_close > prev_open and
                    close < prev_open and
                    open_ > prev_close):
                patterns.append("Bearish Engulfing")

            if (body > 0 and
                    lower_wick > body * 2 and
                    upper_wick < body * 0.5 and
                    body_pct < 0.4):
                patterns.append("Bullish Pin Bar")

            if (body > 0 and
                    upper_wick > body * 2 and
                    lower_wick < body * 0.5 and
                    body_pct < 0.4):
                patterns.append("Bearish Pin Bar")

            if body_pct < 0.1:
                patterns.append("Doji")

            if (prev2_body > 0 and
                    prev2_close < prev2_open and
                    prev_body < prev2_body * 0.3 and
                    close > open_ and
                    close > (prev2_open + prev2_close) / 2):
                patterns.append("Morning Star")

            if (prev2_body > 0 and
                    prev2_close > prev2_open and
                    prev_body < prev2_body * 0.3 and
                    close < open_ and
                    close < (prev2_open + prev2_close) / 2):
                patterns.append("Evening Star")

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

            # ── EMA ──────────────────────────
            ema_fast_series = self.ema(df, cfg.EMA_FAST)
            ema_slow_series = self.ema(df, cfg.EMA_SLOW)

            if ema_fast_series.empty or ema_slow_series.empty:
                return {}

            # ── Stochastic (5,3,3) ───────────
            stoch_data = self.stochastic(df)

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
            last_close    = float(df["close"].iloc[-1])
            last_high     = float(df["high"].iloc[-1])
            last_low      = float(df["low"].iloc[-1])
            last_ema_fast = float(ema_fast_series.iloc[-1])
            last_ema_slow = float(ema_slow_series.iloc[-1])
            last_atr      = float(atr_series.iloc[-1])

            # ── EMA crossover ────────────────
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

                # ── Stochastic (5,3,3)
                "stoch_k"         : stoch_data["k"],
                "stoch_d"         : stoch_data["d"],
                "stoch_cross_up"  : stoch_data["cross_up"],
                "stoch_cross_down": stoch_data["cross_down"],
                "stoch_oversold"  : stoch_data["oversold"],
                "stoch_overbought": stoch_data["overbought"],
                "stoch_bullish"   : stoch_data["bullish_signal"],
                "stoch_bearish"   : stoch_data["bearish_signal"],
                "stoch_soft_bull" : stoch_data["soft_bullish"],
                "stoch_soft_bear" : stoch_data["soft_bearish"],

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
                "volume_above_avg": vol_data.get("above_avg", False),

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