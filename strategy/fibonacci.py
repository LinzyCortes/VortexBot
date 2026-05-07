# ============================================
# VORTEX BOT - FIBONACCI ENGINE
# ============================================

import pandas as pd
import numpy as np
from config import cfg
from logger import logger


class FibonacciEngine:

    # ─── DETECT SWING FOR FIBONACCI ─────────

    @staticmethod
    def find_last_swing(df: pd.DataFrame,
                        direction: str,
                        lookback: int = 50) -> dict:
        """
        Temukan swing high & low terakhir
        untuk gambar fibonacci
        """
        try:
            recent = df.tail(lookback)

            if direction == "BUY":
                # Untuk BUY: cari swing low (start)
                # ke swing high (end) — harga retrace turun
                swing_low_idx  = recent["low"].idxmin()
                swing_high_idx = recent["high"].idxmax()

                swing_low  = recent.loc[swing_low_idx,  "low"]
                swing_high = recent.loc[swing_high_idx, "high"]

                # Pastikan swing low sebelum swing high
                if swing_low_idx < swing_high_idx:
                    return {
                        "valid"      : True,
                        "direction"  : "BUY",
                        "swing_start": swing_low,
                        "swing_end"  : swing_high,
                        "swing_range": swing_high - swing_low,
                    }

            elif direction == "SELL":
                # Untuk SELL: cari swing high (start)
                # ke swing low (end)
                swing_high_idx = recent["high"].idxmax()
                swing_low_idx  = recent["low"].idxmin()

                swing_high = recent.loc[swing_high_idx, "high"]
                swing_low  = recent.loc[swing_low_idx,  "low"]

                # Pastikan swing high sebelum swing low
                if swing_high_idx < swing_low_idx:
                    return {
                        "valid"      : True,
                        "direction"  : "SELL",
                        "swing_start": swing_high,
                        "swing_end"  : swing_low,
                        "swing_range": swing_high - swing_low,
                    }

            return {"valid": False}

        except Exception as e:
            logger.error(f"❌ Find swing error: {e}")
            return {"valid": False}

    # ─── CALCULATE FIBONACCI LEVELS ─────────

    def calculate_levels(self, df: pd.DataFrame,
                         direction: str) -> dict:
        """
        Hitung semua level Fibonacci
        Retracement & Extension
        """
        try:
            swing = self.find_last_swing(df, direction)

            if not swing.get("valid"):
                return {"valid": False}

            start  = swing["swing_start"]
            end    = swing["swing_end"]
            range_ = swing["swing_range"]

            if direction == "BUY":
                # Retracement: dari high ke bawah
                retracement = {
                    "0.0"  : end,
                    "0.236": end - range_ * 0.236,
                    "0.382": end - range_ * 0.382,
                    "0.500": end - range_ * 0.500,  # ⭐ Penting
                    "0.618": end - range_ * 0.618,  # ⭐ Golden Ratio
                    "0.786": end - range_ * 0.786,
                    "1.0"  : start,
                }
                # Extension: target TP di atas swing high
                extension = {
                    "1.272": end + range_ * 0.272,  # TP1
                    "1.618": end + range_ * 0.618,  # TP2 ⭐
                    "2.000": end + range_ * 1.000,
                    "2.618": end + range_ * 1.618,  # TP3 ⭐
                    "3.618": end + range_ * 2.618,
                }

            else:  # SELL
                # Retracement: dari low ke atas
                retracement = {
                    "0.0"  : end,
                    "0.236": end + range_ * 0.236,
                    "0.382": end + range_ * 0.382,
                    "0.500": end + range_ * 0.500,  # ⭐
                    "0.618": end + range_ * 0.618,  # ⭐ Golden Ratio
                    "0.786": end + range_ * 0.786,
                    "1.0"  : start,
                }
                # Extension: target TP di bawah swing low
                extension = {
                    "1.272": end - range_ * 0.272,  # TP1
                    "1.618": end - range_ * 0.618,  # TP2 ⭐
                    "2.000": end - range_ * 1.000,
                    "2.618": end - range_ * 1.618,  # TP3 ⭐
                    "3.618": end - range_ * 2.618,
                }

            return {
                "valid"      : True,
                "direction"  : direction,
                "swing_start": start,
                "swing_end"  : end,
                "range"      : range_,
                "retracement": retracement,
                "extension"  : extension,

                # Level penting langsung
                "fib_50" : retracement["0.500"],
                "fib_618": retracement["0.618"],
                "fib_786": retracement["0.786"],
                "tp1"    : extension["1.272"],
                "tp2"    : extension["1.618"],
                "tp3"    : extension["2.618"],
            }

        except Exception as e:
            logger.error(f"❌ Fibonacci levels error: {e}")
            return {"valid": False}

    # ─── CHECK PRICE AT FIB LEVEL ────────────

    def get_nearest_fib_level(self,
                               price: float,
                               fib_levels: dict,
                               tolerance_pct: float = 1.0
                               ) -> dict:
        """
        Cek level fibonacci terdekat dengan harga.

        FIX: Tolerance dinaikkan dari 0.3% → 1.0%
        Alasan: Dengan 0.3%, BTC di $94k hanya punya
        window $282 — hampir tidak pernah terpenuhi saat
        scan tiap 60 detik. Dengan 1.0% window jadi ~$940,
        realistis untuk timeframe 15m.
        """
        try:
            retracement = fib_levels.get("retracement", {})

            # ── FIX: tolerance 0.3% → 1.0% ──────────────────────────────────
            tolerance = price * (tolerance_pct / 100)

            best_match  = None
            best_dist   = float("inf")

            for level_name, level_price in retracement.items():
                dist = abs(price - level_price)
                if dist <= tolerance and dist < best_dist:
                    best_dist  = dist
                    best_match = level_name

            if best_match:
                level_price = retracement[best_match]

                # Tentukan kekuatan level
                if best_match in ["0.618", "0.500"]:
                    strength = "STRONG"
                    score    = 2
                elif best_match in ["0.382", "0.786"]:
                    strength = "MEDIUM"
                    score    = 1
                else:
                    strength = "WEAK"
                    score    = 0

                logger.debug(
                    f"📐 Fib match: {best_match} | "
                    f"price={price:.2f} level={level_price:.2f} | "
                    f"dist={best_dist:.2f} tol={tolerance:.2f}"
                )

                return {
                    "at_fib"  : True,
                    "level"   : best_match,
                    "price"   : level_price,
                    "strength": strength,
                    "score"   : score,
                }

            return {
                "at_fib"  : False,
                "level"   : None,
                "strength": None,
                "score"   : 0,
            }

        except Exception as e:
            logger.error(f"❌ Nearest fib error: {e}")
            return {"at_fib": False, "score": 0}

    # ─── CALCULATE TP & SL WITH FIB ─────────

    def calculate_tp_sl(self,
                        entry: float,
                        direction: str,
                        atr: float,
                        fib_levels: dict,
                        liquidity_level: float = None
                        ) -> dict:
        """
        Hitung SL & TP berdasarkan:
        - Fibonacci extension untuk TP
        - ATR + Liquidity untuk SL
        """
        try:
            if not fib_levels.get("valid"):
                return {}

            tp1 = fib_levels["tp1"]
            tp2 = fib_levels["tp2"]
            tp3 = fib_levels["tp3"]

            # SL berdasarkan ATR + area liquidity
            atr_multiplier = 1.5

            if direction == "BUY":
                sl_atr = entry - (atr * atr_multiplier)

                if liquidity_level and liquidity_level < entry:
                    sl = min(sl_atr, liquidity_level * 0.999)
                else:
                    sl = sl_atr

                risk = entry - sl
                rr1  = (tp1 - entry) / risk if risk > 0 else 0
                rr2  = (tp2 - entry) / risk if risk > 0 else 0
                rr3  = (tp3 - entry) / risk if risk > 0 else 0

                if rr2 < cfg.MIN_RR:
                    tp2 = entry + (risk * cfg.MIN_RR)
                    rr2 = cfg.MIN_RR

            else:  # SELL
                sl_atr = entry + (atr * atr_multiplier)

                if liquidity_level and liquidity_level > entry:
                    sl = max(sl_atr, liquidity_level * 1.001)
                else:
                    sl = sl_atr

                risk = sl - entry
                rr1  = (entry - tp1) / risk if risk > 0 else 0
                rr2  = (entry - tp2) / risk if risk > 0 else 0
                rr3  = (entry - tp3) / risk if risk > 0 else 0

                if rr2 < cfg.MIN_RR:
                    tp2 = entry - (risk * cfg.MIN_RR)
                    rr2 = cfg.MIN_RR

            return {
                "entry"  : entry,
                "sl"     : round(sl,  4),
                "tp1"    : round(tp1, 4),
                "tp2"    : round(tp2, 4),
                "tp3"    : round(tp3, 4),
                "risk"   : round(risk, 4),
                "rr1"    : round(rr1, 2),
                "rr2"    : round(rr2, 2),
                "rr3"    : round(rr3, 2),
                "sl_type": "Liquidity + ATR",
            }

        except Exception as e:
            logger.error(f"❌ TP/SL calc error: {e}")
            return {}

    # ─── DYNAMIC RR ADJUSTMENT ──────────────

    def adjust_rr_to_market(self,
                             df: pd.DataFrame,
                             tp_sl: dict,
                             direction: str) -> dict:
        """
        Sesuaikan RR dengan kondisi market.
        Bot menyesuaikan TP jika ada momentum kuat.
        """
        try:
            if not tp_sl:
                return tp_sl

            recent_range = (
                df["high"].tail(5).max() -
                df["low"].tail(5).min()
            )
            atr_val  = df["close"].tail(14).std()
            momentum = recent_range / atr_val if atr_val > 0 else 1

            entry = tp_sl["entry"]
            risk  = tp_sl["risk"]

            if direction == "BUY":
                if momentum > 2.0:
                    tp_sl["active_tp"] = tp_sl["tp3"]
                    tp_sl["active_rr"] = tp_sl["rr3"]
                    tp_sl["momentum"]  = "STRONG"
                elif momentum > 1.5:
                    tp_sl["active_tp"] = tp_sl["tp2"]
                    tp_sl["active_rr"] = tp_sl["rr2"]
                    tp_sl["momentum"]  = "NORMAL"
                else:
                    tp_sl["active_tp"] = tp_sl["tp1"]
                    tp_sl["active_rr"] = tp_sl["rr1"]
                    tp_sl["momentum"]  = "WEAK"
            else:
                if momentum > 2.0:
                    tp_sl["active_tp"] = tp_sl["tp3"]
                    tp_sl["active_rr"] = tp_sl["rr3"]
                    tp_sl["momentum"]  = "STRONG"
                elif momentum > 1.5:
                    tp_sl["active_tp"] = tp_sl["tp2"]
                    tp_sl["active_rr"] = tp_sl["rr2"]
                    tp_sl["momentum"]  = "NORMAL"
                else:
                    tp_sl["active_tp"] = tp_sl["tp1"]
                    tp_sl["active_rr"] = tp_sl["rr1"]
                    tp_sl["momentum"]  = "WEAK"

            # Pastikan minimal RR terpenuhi
            if tp_sl.get("active_rr", 0) < cfg.MIN_RR:
                tp_sl["active_rr"] = cfg.MIN_RR
                if direction == "BUY":
                    tp_sl["active_tp"] = entry + (risk * cfg.MIN_RR)
                else:
                    tp_sl["active_tp"] = entry - (risk * cfg.MIN_RR)

            logger.debug(
                f"📐 RR adjusted: momentum={tp_sl['momentum']} "
                f"RR=1:{tp_sl['active_rr']}"
            )

            return tp_sl

        except Exception as e:
            logger.error(f"❌ RR adjustment error: {e}")
            return tp_sl

    # ─── FULL FIBONACCI ANALYSIS ────────────

    def analyze(self, df: pd.DataFrame,
                direction: str,
                current_price: float,
                atr: float,
                liquidity_level: float = None) -> dict:
        """Full fibonacci analysis"""
        try:
            # Hitung levels
            fib_levels = self.calculate_levels(df, direction)

            if not fib_levels.get("valid"):
                return {
                    "valid"    : False,
                    "at_fib"   : False,
                    "fib_score": 0,
                }

            # Cek apakah harga di level fib penting
            nearest = self.get_nearest_fib_level(
                current_price, fib_levels
                # tolerance_pct default sekarang 1.0%
            )

            # Hitung TP & SL
            tp_sl = self.calculate_tp_sl(
                entry           =current_price,
                direction       =direction,
                atr             =atr,
                fib_levels      =fib_levels,
                liquidity_level =liquidity_level,
            )

            # Dynamic RR adjustment
            if tp_sl:
                tp_sl = self.adjust_rr_to_market(
                    df, tp_sl, direction
                )

            return {
                "valid"       : True,
                "fib_levels"  : fib_levels,
                "nearest_fib" : nearest,
                "at_fib"      : nearest.get("at_fib", False),
                "fib_level"   : nearest.get("level"),
                "fib_strength": nearest.get("strength"),
                "fib_score"   : nearest.get("score", 0),
                "tp_sl"       : tp_sl,
                "fib_50"      : fib_levels.get("fib_50"),
                "fib_618"     : fib_levels.get("fib_618"),
                "tp1"         : fib_levels.get("tp1"),
                "tp2"         : fib_levels.get("tp2"),
                "tp3"         : fib_levels.get("tp3"),
            }

        except Exception as e:
            logger.error(f"❌ Fibonacci analyze error: {e}")
            return {"valid": False, "at_fib": False,
                    "fib_score": 0}


# Instance siap pakai
fibonacci = FibonacciEngine()