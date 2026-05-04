# ============================================
# VORTEX BOT - SMART MONEY CONCEPT (SMC)
# ============================================

import pandas as pd
import numpy as np
from config import cfg
from logger import logger


class SMCAnalysis:

    # ─── SWING HIGH / LOW ───────────────────

    @staticmethod
    def find_swing_points(df: pd.DataFrame,
                          lookback: int = None) -> dict:
        """Deteksi swing high dan swing low"""
        try:
            if lookback is None:
                lookback = cfg.SMC_SWING_LOOKBACK

            highs = []
            lows  = []

            for i in range(lookback, len(df) - lookback):
                # Swing High
                if df["high"].iloc[i] == df["high"].iloc[
                    i-lookback:i+lookback+1
                ].max():
                    highs.append({
                        "index": i,
                        "price": df["high"].iloc[i],
                        "time" : df.index[i],
                    })

                # Swing Low
                if df["low"].iloc[i] == df["low"].iloc[
                    i-lookback:i+lookback+1
                ].min():
                    lows.append({
                        "index": i,
                        "price": df["low"].iloc[i],
                        "time" : df.index[i],
                    })

            return {
                "swing_highs": highs[-5:],  # 5 terakhir
                "swing_lows" : lows[-5:],
                "last_high"  : highs[-1] if highs else None,
                "last_low"   : lows[-1]  if lows  else None,
            }

        except Exception as e:
            logger.error(f"❌ Swing points error: {e}")
            return {"swing_highs": [], "swing_lows": [],
                    "last_high": None, "last_low": None}

    # ─── MARKET STRUCTURE ───────────────────

    def detect_market_structure(self,
                                df: pd.DataFrame) -> dict:
        """Deteksi BOS dan CHoCH"""
        try:
            swings = self.find_swing_points(df)
            highs  = swings["swing_highs"]
            lows   = swings["swing_lows"]

            if len(highs) < 2 or len(lows) < 2:
                return {
                    "structure" : "UNKNOWN",
                    "bos"       : False,
                    "choch"     : False,
                    "direction" : None,
                }

            current_price = df["close"].iloc[-1]

            # Trend berdasarkan Higher High / Higher Low
            hh = highs[-1]["price"] > highs[-2]["price"]
            hl = lows[-1]["price"]  > lows[-2]["price"]
            lh = highs[-1]["price"] < highs[-2]["price"]
            ll = lows[-1]["price"]  < lows[-2]["price"]

            # Tentukan struktur dari SWING sebelumnya
            # (bukan dari current price)
            if hh and hl:
                structure = "UPTREND"
                direction = "BUY"
            elif lh and ll:
                structure = "DOWNTREND"
                direction = "SELL"
            else:
                structure = "RANGING"
                direction = None

            # ── FIX BUG #1: BOS Logic ──────────────────────────
            # BOS = harga break melewati swing high/low terakhir
            # TIDAK perlu cek struktur dulu — BOS adalah konfirmasi
            # bahwa struktur baru sedang terbentuk

            # BOS Bullish: harga close di atas swing high terakhir
            # (valid di struktur apapun — ini yang bikin UPTREND)
            bos_bullish = current_price > highs[-1]["price"]

            # BOS Bearish: harga close di bawah swing low terakhir
            # (valid di struktur apapun)
            bos_bearish = current_price < lows[-1]["price"]

            bos = bos_bullish or bos_bearish

            # CHoCH = struktur sebelumnya berlawanan dgn break terbaru
            # CHoCH Bullish: sebelumnya downtrend (lh+ll),
            # tapi sekarang break above swing high
            choch_bullish = (lh and ll and bos_bullish)

            # CHoCH Bearish: sebelumnya uptrend (hh+hl),
            # tapi sekarang break below swing low
            choch_bearish = (hh and hl and bos_bearish)

            choch = choch_bullish or choch_bearish

            return {
                "structure"       : structure,
                "direction"       : direction,
                "bos"             : bos,
                "bos_bullish"     : bos_bullish,
                "bos_bearish"     : bos_bearish,
                "choch"           : choch,
                "choch_bullish"   : choch_bullish,
                "choch_bearish"   : choch_bearish,
                "last_high"       : highs[-1]["price"],
                "last_low"        : lows[-1]["price"],
                "higher_high"     : hh,
                "higher_low"      : hl,
                "lower_high"      : lh,
                "lower_low"       : ll,
            }

        except Exception as e:
            logger.error(f"❌ Market structure error: {e}")
            return {
                "structure": "UNKNOWN",
                "bos": False,
                "choch": False,
                "direction": None
            }

    # ─── ORDER BLOCKS ───────────────────────

    def detect_order_blocks(self,
                            df: pd.DataFrame,
                            direction: str) -> list:
        """Deteksi Order Block valid"""
        try:
            obs = []
            lookback = cfg.OB_LOOKBACK

            for i in range(1, min(lookback, len(df)-1)):
                idx = -(i+1)  # Dari candle terakhir mundur

                curr   = df.iloc[idx]
                next_c = df.iloc[idx+1]

                # Bullish OB: candle bearish sebelum impulse naik kuat
                if direction == "BUY":
                    is_bearish   = curr["close"] < curr["open"]
                    next_bullish = next_c["close"] > next_c["open"]
                    strong_move  = (
                        (next_c["close"] - next_c["open"]) >
                        (curr["open"] - curr["close"]) * 1.5
                    )

                    if is_bearish and next_bullish and strong_move:
                        obs.append({
                            "type"    : "Bullish OB",
                            "top"     : curr["open"],
                            "bottom"  : curr["close"],
                            "mid"     : (curr["open"] + curr["close"]) / 2,
                            "time"    : df.index[idx],
                            "strength": strong_move,
                            "valid"   : True,
                        })

                # Bearish OB: candle bullish sebelum impulse turun kuat
                elif direction == "SELL":
                    is_bullish   = curr["close"] > curr["open"]
                    next_bearish = next_c["close"] < next_c["open"]
                    strong_move  = (
                        (next_c["open"] - next_c["close"]) >
                        (curr["close"] - curr["open"]) * 1.5
                    )

                    if is_bullish and next_bearish and strong_move:
                        obs.append({
                            "type"    : "Bearish OB",
                            "top"     : curr["close"],
                            "bottom"  : curr["open"],
                            "mid"     : (curr["open"] + curr["close"]) / 2,
                            "time"    : df.index[idx],
                            "strength": strong_move,
                            "valid"   : True,
                        })

            return obs[:3]  # 3 OB terkuat

        except Exception as e:
            logger.error(f"❌ Order block error: {e}")
            return []

    def is_price_in_ob(self, price: float,
                       obs: list) -> dict:
        """Cek apakah harga berada di area OB"""
        for ob in obs:
            if ob["bottom"] <= price <= ob["top"]:
                return {
                    "in_ob"  : True,
                    "ob_type": ob["type"],
                    "ob_mid" : ob["mid"],
                }
        return {"in_ob": False, "ob_type": None}

    # ─── FAIR VALUE GAP ─────────────────────

    def detect_fvg(self, df: pd.DataFrame,
                   direction: str) -> list:
        """Deteksi Fair Value Gap"""
        try:
            fvgs = []

            for i in range(2, min(cfg.OB_LOOKBACK, len(df))):
                idx1 = -(i+1)
                idx2 = -i
                idx3 = -(i-1)

                c1 = df.iloc[idx1]  # Candle 1
                c3 = df.iloc[idx3]  # Candle 3

                # Bullish FVG: low candle 3 > high candle 1
                if direction == "BUY":
                    gap = c3["low"] - c1["high"]
                    if gap > 0:
                        gap_pct = gap / c1["high"] * 100
                        if gap_pct >= cfg.FVG_MIN_SIZE:
                            fvgs.append({
                                "type"   : "Bullish FVG",
                                "top"    : c3["low"],
                                "bottom" : c1["high"],
                                "mid"    : (c3["low"] + c1["high"]) / 2,
                                "size"   : gap_pct,
                                "time"   : df.index[idx2],
                                "filled" : False,
                            })

                # Bearish FVG: high candle 3 < low candle 1
                elif direction == "SELL":
                    gap = c1["low"] - c3["high"]
                    if gap > 0:
                        gap_pct = gap / c1["low"] * 100
                        if gap_pct >= cfg.FVG_MIN_SIZE:
                            fvgs.append({
                                "type"   : "Bearish FVG",
                                "top"    : c1["low"],
                                "bottom" : c3["high"],
                                "mid"    : (c1["low"] + c3["high"]) / 2,
                                "size"   : gap_pct,
                                "time"   : df.index[idx2],
                                "filled" : False,
                            })

            return fvgs[:3]  # 3 FVG terbesar

        except Exception as e:
            logger.error(f"❌ FVG error: {e}")
            return []

    def is_price_in_fvg(self, price: float,
                        fvgs: list) -> dict:
        """Cek apakah harga di dalam FVG"""
        for fvg in fvgs:
            if fvg["bottom"] <= price <= fvg["top"]:
                return {
                    "in_fvg"  : True,
                    "fvg_type": fvg["type"],
                    "fvg_mid" : fvg["mid"],
                    "fvg_size": fvg["size"],
                }
        return {"in_fvg": False, "fvg_type": None}

    # ─── LIQUIDITY ZONES ────────────────────

    def detect_liquidity(self,
                         df: pd.DataFrame) -> dict:
        """Deteksi area liquidity (BSL & SSL)"""
        try:
            lookback = cfg.LIQUIDITY_LOOKBACK
            recent   = df.tail(lookback)

            # Buy Side Liquidity (BSL) = equal highs
            highs      = recent["high"].values
            bsl_levels = []

            for i in range(len(highs)-1):
                for j in range(i+1, len(highs)):
                    diff = abs(highs[i] - highs[j]) / highs[i]
                    if diff < 0.001:  # 0.1% tolerance
                        bsl_levels.append(
                            (highs[i] + highs[j]) / 2
                        )

            # Sell Side Liquidity (SSL) = equal lows
            lows      = recent["low"].values
            ssl_levels = []

            for i in range(len(lows)-1):
                for j in range(i+1, len(lows)):
                    diff = abs(lows[i] - lows[j]) / lows[i]
                    if diff < 0.001:
                        ssl_levels.append(
                            (lows[i] + lows[j]) / 2
                        )

            current_price = df["close"].iloc[-1]

            # BSL terdekat di atas harga
            bsl_above   = [b for b in bsl_levels if b > current_price]
            nearest_bsl = min(bsl_above) if bsl_above else None

            # SSL terdekat di bawah harga
            ssl_below   = [s for s in ssl_levels if s < current_price]
            nearest_ssl = max(ssl_below) if ssl_below else None

            # ── FIX BUG #2: Cek sweep di 5 candle terakhir ────────────────
            # Sebelumnya hanya cek iloc[-1] (1 candle saja)
            # Sekarang cek 5 candle terakhir agar lebih akurat
            recent_highs = df["high"].iloc[-5:]
            recent_lows  = df["low"].iloc[-5:]

            bsl_swept = bool(
                nearest_bsl and
                (recent_highs > nearest_bsl).any()
            )
            ssl_swept = bool(
                nearest_ssl and
                (recent_lows < nearest_ssl).any()
            )

            return {
                "bsl_levels"   : sorted(bsl_levels)[-3:],
                "ssl_levels"   : sorted(ssl_levels)[:3],
                "nearest_bsl"  : nearest_bsl,
                "nearest_ssl"  : nearest_ssl,
                "bsl_swept"    : bsl_swept,
                "ssl_swept"    : ssl_swept,
                "current_price": current_price,
            }

        except Exception as e:
            logger.error(f"❌ Liquidity error: {e}")
            return {}

    # ─── PREMIUM / DISCOUNT ZONE ────────────

    @staticmethod
    def get_premium_discount(df: pd.DataFrame,
                             lookback: int = 50) -> dict:
        """Tentukan Premium & Discount Zone"""
        try:
            recent  = df.tail(lookback)
            high    = recent["high"].max()
            low     = recent["low"].min()
            mid     = (high + low) / 2
            current = df["close"].iloc[-1]

            range_size = high - low
            fib_50     = low + range_size * 0.5
            fib_618    = low + range_size * 0.618

            is_discount = current < mid
            is_premium  = current > mid

            if is_discount:
                depth = (mid - current) / (mid - low) * 100
            else:
                depth = (current - mid) / (high - mid) * 100

            return {
                "high"       : high,
                "low"        : low,
                "mid"        : mid,
                "fib_50"     : fib_50,
                "fib_618"    : fib_618,
                "current"    : current,
                "is_discount": is_discount,
                "is_premium" : is_premium,
                "zone"       : "DISCOUNT" if is_discount else "PREMIUM",
                "depth_pct"  : depth,
                "ideal_buy"  : is_discount,
                "ideal_sell" : is_premium,
            }

        except Exception as e:
            logger.error(f"❌ Premium/Discount error: {e}")
            return {}

    # ─── BREAKER BLOCK ──────────────────────

    def detect_breaker_block(self,
                             df: pd.DataFrame,
                             direction: str) -> list:
        """Deteksi Breaker Block (OB yang gagal)"""
        try:
            breakers = []
            obs      = self.detect_order_blocks(df, direction)

            for ob in obs:
                current = df["close"].iloc[-1]

                if direction == "BUY":
                    if current > ob["top"]:
                        breakers.append({
                            "type" : "Bullish Breaker",
                            "level": ob["top"],
                            "zone" : (ob["bottom"], ob["top"]),
                        })

                elif direction == "SELL":
                    if current < ob["bottom"]:
                        breakers.append({
                            "type" : "Bearish Breaker",
                            "level": ob["bottom"],
                            "zone" : (ob["bottom"], ob["top"]),
                        })

            return breakers

        except Exception as e:
            logger.error(f"❌ Breaker block error: {e}")
            return []

    # ─── INDUCEMENT ─────────────────────────

    def detect_inducement(self,
                          df: pd.DataFrame,
                          direction: str) -> dict:
        """Deteksi Inducement (liquidity trap)"""
        try:
            lookback = 10
            recent   = df.tail(lookback)

            if direction == "BUY":
                lows = recent["low"].values
                for i in range(len(lows)-2):
                    diff = abs(lows[i] - lows[i+1]) / lows[i]
                    if diff < 0.002:
                        return {
                            "detected"   : True,
                            "type"       : "Bullish Inducement",
                            "level"      : (lows[i] + lows[i+1]) / 2,
                            "description": "Equal lows terdeteksi "
                                          "→ potensi liquidity grab",
                        }

            elif direction == "SELL":
                highs = recent["high"].values
                for i in range(len(highs)-2):
                    diff = abs(highs[i] - highs[i+1]) / highs[i]
                    if diff < 0.002:
                        return {
                            "detected"   : True,
                            "type"       : "Bearish Inducement",
                            "level"      : (highs[i] + highs[i+1]) / 2,
                            "description": "Equal highs terdeteksi "
                                          "→ potensi liquidity grab",
                        }

            return {"detected": False, "type": None}

        except Exception as e:
            logger.error(f"❌ Inducement error: {e}")
            return {"detected": False}

    # ─── FULL SMC ANALYSIS ──────────────────

    def analyze(self, df_4h: pd.DataFrame,
                df_1h: pd.DataFrame,
                df_15m: pd.DataFrame) -> dict:
        """Full SMC analysis multi-timeframe"""
        try:
            # 4H — Bias & Structure
            structure_4h = self.detect_market_structure(df_4h)
            prem_disc_4h = self.get_premium_discount(df_4h)
            liquidity_4h = self.detect_liquidity(df_4h)

            # Tentukan direction dari 4H
            direction = structure_4h.get("direction")

            if not direction:
                return {
                    "valid"    : False,
                    "reason"   : "Market structure unclear on 4H",
                    "direction": None,
                }

            # 1H — Setup
            structure_1h = self.detect_market_structure(df_1h)
            obs_1h       = self.detect_order_blocks(df_1h, direction)
            fvgs_1h      = self.detect_fvg(df_1h, direction)
            liquidity_1h = self.detect_liquidity(df_1h)
            breakers_1h  = self.detect_breaker_block(df_1h, direction)

            # 15M — Entry
            current_price = df_15m["close"].iloc[-1]
            in_ob         = self.is_price_in_ob(current_price, obs_1h)
            in_fvg        = self.is_price_in_fvg(current_price, fvgs_1h)
            inducement    = self.detect_inducement(df_15m, direction)

            # Liquidity swept check
            liq_swept = (
                liquidity_1h.get("ssl_swept") if direction == "BUY"
                else liquidity_1h.get("bsl_swept")
            )

            return {
                "valid"          : True,
                "direction"      : direction,

                # 4H Analysis
                "structure_4h"   : structure_4h["structure"],
                "bos_4h"         : structure_4h["bos"],
                "choch_4h"       : structure_4h["choch"],
                "premium_discount": prem_disc_4h,
                "liquidity_4h"   : liquidity_4h,
                "ideal_zone"     : prem_disc_4h.get("ideal_buy")
                                   if direction == "BUY"
                                   else prem_disc_4h.get("ideal_sell"),

                # 1H Analysis
                "structure_1h"   : structure_1h["structure"],
                "bos_1h"         : structure_1h["bos"],
                "choch_1h"       : structure_1h["choch"],
                "order_blocks"   : obs_1h,
                "fvgs"           : fvgs_1h,
                "breaker_blocks" : breakers_1h,
                "liquidity_1h"   : liquidity_1h,

                # 15M Analysis
                "in_ob"          : in_ob["in_ob"],
                "ob_type"        : in_ob.get("ob_type"),
                "in_fvg"         : in_fvg["in_fvg"],
                "fvg_type"       : in_fvg.get("fvg_type"),
                "liquidity_swept": liq_swept,
                "inducement"     : inducement,

                # Current price
                "current_price"  : current_price,
            }

        except Exception as e:
            logger.error(f"❌ SMC analyze error: {e}")
            return {"valid": False, "direction": None}


# Instance siap pakai
smc = SMCAnalysis()