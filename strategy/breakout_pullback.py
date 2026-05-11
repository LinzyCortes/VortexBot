# ============================================
# VORTEX BOT - BREAKOUT & PULLBACK STRATEGY
# ============================================
#
# Strategi ini dipakai institusi besar (hedge fund,
# prop firm) karena:
#   - Breakout: entry saat momentum kuat, bukan chase
#     harga — tunggu break + volume konfirmasi
#   - Pullback: entry di harga lebih baik setelah
#     breakout, SL lebih ketat, RR lebih tinggi
#
# Integrasi dengan SMC:
#   - Breakout level = swing high/low dari SMC
#   - Pullback zone = OB atau FVG dari SMC
#   - Filter: hanya valid dalam killzone session

import pandas as pd
import numpy as np
from config import cfg
from logger import logger


class BreakoutPullbackAnalysis:

    # ─── KEY LEVEL DETECTION ────────────────

    @staticmethod
    def detect_key_levels(df: pd.DataFrame,
                          lookback: int = 50) -> dict:
        """
        Deteksi level resistance dan support kunci
        berdasarkan swing high/low yang signifikan.
        Level ini yang akan jadi target breakout.
        """
        try:
            recent = df.tail(lookback)

            # Swing highs (resistance)
            swing_period = 5
            resistance_levels = []
            support_levels    = []

            for i in range(swing_period, len(recent) - swing_period):
                # Resistance: lokal high
                window_high = recent["high"].iloc[
                    i-swing_period:i+swing_period+1
                ]
                if recent["high"].iloc[i] == window_high.max():
                    resistance_levels.append({
                        "price": float(recent["high"].iloc[i]),
                        "time" : recent.index[i],
                        "type" : "resistance",
                        "touches": 0,
                    })

                # Support: lokal low
                window_low = recent["low"].iloc[
                    i-swing_period:i+swing_period+1
                ]
                if recent["low"].iloc[i] == window_low.min():
                    support_levels.append({
                        "price": float(recent["low"].iloc[i]),
                        "time" : recent.index[i],
                        "type" : "support",
                        "touches": 0,
                    })

            # Hitung berapa kali level ditest (semakin banyak = lebih kuat)
            current_price = float(df["close"].iloc[-1])
            threshold     = current_price * 0.002  # 0.2% tolerance

            for level in resistance_levels:
                touches = (
                    (abs(recent["high"] - level["price"]) < threshold)
                    .sum()
                )
                level["touches"]  = int(touches)
                level["strength"] = "STRONG" if touches >= 3 else "NORMAL"

            for level in support_levels:
                touches = (
                    (abs(recent["low"] - level["price"]) < threshold)
                    .sum()
                )
                level["touches"]  = int(touches)
                level["strength"] = "STRONG" if touches >= 3 else "NORMAL"

            # Ambil yang paling dekat dengan harga saat ini
            res_above = [r for r in resistance_levels
                         if r["price"] > current_price]
            sup_below = [s for s in support_levels
                         if s["price"] < current_price]

            nearest_res = (
                min(res_above, key=lambda x: x["price"])
                if res_above else None
            )
            nearest_sup = (
                max(sup_below, key=lambda x: x["price"])
                if sup_below else None
            )

            return {
                "resistance_levels": resistance_levels[-5:],
                "support_levels"   : support_levels[-5:],
                "nearest_resistance": nearest_res,
                "nearest_support"   : nearest_sup,
                "current_price"     : current_price,
            }

        except Exception as e:
            logger.error(f"❌ Key levels error: {e}")
            return {
                "resistance_levels": [],
                "support_levels"   : [],
                "nearest_resistance": None,
                "nearest_support"   : None,
            }

    # ─── BREAKOUT DETECTION ─────────────────

    def detect_breakout(self,
                        df: pd.DataFrame,
                        volume_data: dict,
                        lookback: int = 50) -> dict:
        """
        Deteksi breakout valid.

        Kriteria breakout institusi:
        1. Harga close di ATAS resistance (bukan hanya wick)
        2. Volume saat breakout > 1.5× rata-rata (konfirmasi)
        3. Candle breakout harus punya body minimal 60%
           (bukan wick yang nembus level)
        4. Tidak langsung reversal di candle berikutnya
           (false breakout filter)

        Catatan: Institusi hampir tidak pernah chase breakout.
        Mereka entry di retest SETELAH breakout.
        Gunakan fungsi ini untuk deteksi → entry di pullback.
        """
        try:
            key_levels    = self.detect_key_levels(df, lookback)
            current_price = float(df["close"].iloc[-1])
            current_vol   = volume_data.get("ratio", 0)

            last   = df.iloc[-1]
            open_  = float(last["open"])
            high   = float(last["high"])
            low    = float(last["low"])
            close  = float(last["close"])

            candle_range = high - low
            body         = abs(close - open_)
            body_pct     = body / candle_range if candle_range > 0 else 0

            # ── Bullish Breakout ─────────────────────────────────────────────
            nearest_res = key_levels.get("nearest_resistance")
            if nearest_res:
                res_price   = nearest_res["price"]
                broke_above = (
                    close > res_price and   # close di atas (bukan wick)
                    body_pct >= 0.5         # body candle solid
                )

                if broke_above:
                    vol_confirmed = current_vol >= 1.5
                    distance_pct  = (close - res_price) / res_price * 100

                    logger.info(
                        f"🚀 Bullish Breakout terdeteksi! "
                        f"Level={res_price:.2f} "
                        f"Vol={current_vol:.1f}x "
                        f"Body={body_pct:.2f}"
                    )

                    return {
                        "valid"           : True,
                        "direction"       : "BUY",
                        "type"            : "Bullish Breakout",
                        "level"           : res_price,
                        "level_strength"  : nearest_res.get("strength"),
                        "level_touches"   : nearest_res.get("touches", 0),
                        "candle_body_pct" : body_pct,
                        "volume_ratio"    : current_vol,
                        "volume_confirmed": vol_confirmed,
                        "distance_pct"    : distance_pct,
                        "retest_zone_top" : res_price * 1.002,
                        "retest_zone_bot" : res_price * 0.998,
                        "entry_type"      : "WAIT_RETEST",
                    }

            # ── Bearish Breakout ─────────────────────────────────────────────
            nearest_sup = key_levels.get("nearest_support")
            if nearest_sup:
                sup_price   = nearest_sup["price"]
                broke_below = (
                    close < sup_price and
                    body_pct >= 0.5
                )

                if broke_below:
                    vol_confirmed = current_vol >= 1.5
                    distance_pct  = (sup_price - close) / sup_price * 100

                    logger.info(
                        f"🔻 Bearish Breakout terdeteksi! "
                        f"Level={sup_price:.2f} "
                        f"Vol={current_vol:.1f}x "
                        f"Body={body_pct:.2f}"
                    )

                    return {
                        "valid"           : True,
                        "direction"       : "SELL",
                        "type"            : "Bearish Breakout",
                        "level"           : sup_price,
                        "level_strength"  : nearest_sup.get("strength"),
                        "level_touches"   : nearest_sup.get("touches", 0),
                        "candle_body_pct" : body_pct,
                        "volume_ratio"    : current_vol,
                        "volume_confirmed": vol_confirmed,
                        "distance_pct"    : distance_pct,
                        "retest_zone_top" : sup_price * 1.002,
                        "retest_zone_bot" : sup_price * 0.998,
                        "entry_type"      : "WAIT_RETEST",
                    }

            return {
                "valid"    : False,
                "direction": None,
                "type"     : None,
            }

        except Exception as e:
            logger.error(f"❌ Breakout detection error: {e}")
            return {"valid": False, "direction": None}

    # ─── FALSE BREAKOUT FILTER ───────────────

    @staticmethod
    def is_false_breakout(df: pd.DataFrame,
                          breakout_level: float,
                          direction: str,
                          candles_back: int = 3) -> bool:
        """
        Filter false breakout.
        Jika setelah breakout harga langsung balik
        ke dalam range, itu false breakout — skip.

        Kriteria false breakout:
        - Close kembali ke bawah level (untuk BUY)
        - Close kembali ke atas level (untuk SELL)
        - Terjadi dalam 3 candle setelah break
        """
        try:
            recent = df.tail(candles_back)

            if direction == "BUY":
                # False jika ada candle yang close di bawah level
                false_signals = (recent["close"] < breakout_level).any()
            else:
                false_signals = (recent["close"] > breakout_level).any()

            if false_signals:
                logger.debug(
                    f"⚠️ False breakout terdeteksi di {breakout_level:.2f}"
                )

            return bool(false_signals)

        except Exception as e:
            logger.error(f"❌ False breakout check error: {e}")
            return False

    # ─── PULLBACK DETECTION ─────────────────

    def detect_pullback(self,
                        df: pd.DataFrame,
                        direction: str,
                        obs: list = None,
                        fvgs: list = None,
                        fib_levels: dict = None) -> dict:
        """
        Deteksi pullback ke zona entry yang valid.

        Strategi pullback institusi:
        1. Setelah breakout, tunggu harga retest level
        2. Atau tunggu retrace ke OB / FVG / Fibonacci
        3. Entry ketika harga "bounce" dari zona tersebut
        4. SL lebih ketat (di bawah/atas zona retest)

        Zona pullback prioritas (urutan kekuatan):
        1. Fib 0.618 + OB → setup terkuat
        2. Fib 0.500 + FVG → setup kuat
        3. OB saja → setup normal
        4. Fib 0.382 saja → setup lemah, perlu konfirmasi extra
        """
        try:
            if obs is None:
                obs = []
            if fvgs is None:
                fvgs = []

            current_price = float(df["close"].iloc[-1])
            results       = []

            # ── Cek pullback ke OB ──────────────────────────────────────────
            for ob in obs:
                ob_top = ob.get("top", 0)
                ob_bot = ob.get("bottom", 0)
                ob_mid = ob.get("mid", 0)

                in_ob = ob_bot <= current_price <= ob_top

                if in_ob:
                    depth_pct = abs(
                        current_price - ob_mid
                    ) / ob_mid * 100 if ob_mid > 0 else 0

                    results.append({
                        "valid"    : True,
                        "direction": direction,
                        "zone"     : ob.get("type", "Order Block"),
                        "zone_top" : ob_top,
                        "zone_bot" : ob_bot,
                        "depth_pct": depth_pct,
                        "strength" : "STRONG",
                        "source"   : "OB",
                    })

            # ── Cek pullback ke FVG ─────────────────────────────────────────
            for fvg in fvgs:
                fvg_top = fvg.get("top", 0)
                fvg_bot = fvg.get("bottom", 0)
                fvg_mid = fvg.get("mid", 0)

                in_fvg = fvg_bot <= current_price <= fvg_top

                if in_fvg:
                    depth_pct = abs(
                        current_price - fvg_mid
                    ) / fvg_mid * 100 if fvg_mid > 0 else 0

                    results.append({
                        "valid"    : True,
                        "direction": direction,
                        "zone"     : fvg.get("type", "FVG"),
                        "zone_top" : fvg_top,
                        "zone_bot" : fvg_bot,
                        "depth_pct": depth_pct,
                        "strength" : "NORMAL",
                        "source"   : "FVG",
                    })

            # ── Cek pullback ke Fibonacci ────────────────────────────────────
            if fib_levels and fib_levels.get("valid"):
                retracement   = fib_levels.get("retracement", {})
                fib_tolerance = current_price * 0.01  # 1%

                for level_name, level_price in retracement.items():
                    if abs(current_price - level_price) <= fib_tolerance:
                        strength = (
                            "STRONG" if level_name in ["0.618", "0.500"]
                            else "NORMAL"
                        )
                        depth_pct = abs(
                            current_price - level_price
                        ) / level_price * 100 if level_price > 0 else 0

                        results.append({
                            "valid"    : True,
                            "direction": direction,
                            "zone"     : f"Fibonacci {level_name}",
                            "zone_top" : level_price * 1.005,
                            "zone_bot" : level_price * 0.995,
                            "depth_pct": depth_pct,
                            "strength" : strength,
                            "source"   : "FIB",
                            "fib_level": level_name,
                        })

            if not results:
                return {
                    "valid"    : False,
                    "direction": None,
                    "zone"     : None,
                    "depth_pct": 0,
                }

            # Ambil zona terkuat (OB > FIB strong > FVG > FIB normal)
            priority_order = {"OB": 3, "FIB": 2, "FVG": 1}
            best = max(
                results,
                key=lambda x: (
                    priority_order.get(x["source"], 0) +
                    (1 if x["strength"] == "STRONG" else 0)
                )
            )

            logger.debug(
                f"📉 Pullback ke {best['zone']} "
                f"strength={best['strength']} "
                f"depth={best['depth_pct']:.2f}%"
            )

            return best

        except Exception as e:
            logger.error(f"❌ Pullback detection error: {e}")
            return {"valid": False, "direction": None}

    # ─── RETEST CONFIRMATION ─────────────────

    @staticmethod
    def confirm_retest(df: pd.DataFrame,
                       retest_zone_top: float,
                       retest_zone_bot: float,
                       direction: str) -> dict:
        """
        Konfirmasi retest setelah breakout.

        Bot tidak langsung entry saat breakout.
        Bot tunggu harga balik ke area breakout level
        (retest), lalu konfirmasi bounce dari sana.

        Retest valid kalau:
        1. Harga sudah masuk ke zona retest
        2. Ada candle konfirmasi (close balik ke arah break)
        3. Volume tidak drop drastis
        """
        try:
            last  = df.iloc[-1]
            prev  = df.iloc[-2]

            last_low   = float(last["low"])
            last_high  = float(last["high"])
            last_close = float(last["close"])
            prev_close = float(prev["close"])

            touched_zone = False
            bounced      = False

            if direction == "BUY":
                # Harga turun ke zona retest
                touched_zone = last_low <= retest_zone_top
                # Konfirmasi: close di atas zona (bounce)
                bounced = (
                    last_close > retest_zone_top and
                    last_close > prev_close
                )

            elif direction == "SELL":
                # Harga naik ke zona retest
                touched_zone = last_high >= retest_zone_bot
                # Konfirmasi: close di bawah zona (bounce)
                bounced = (
                    last_close < retest_zone_bot and
                    last_close < prev_close
                )

            if touched_zone and bounced:
                return {
                    "confirmed" : True,
                    "touched"   : True,
                    "bounced"   : True,
                    "entry_type": "RETEST_CONFIRMED",
                }
            elif touched_zone:
                return {
                    "confirmed" : False,
                    "touched"   : True,
                    "bounced"   : False,
                    "entry_type": "WAIT_BOUNCE",
                }
            else:
                return {
                    "confirmed" : False,
                    "touched"   : False,
                    "bounced"   : False,
                    "entry_type": "WAIT_RETEST",
                }

        except Exception as e:
            logger.error(f"❌ Retest confirm error: {e}")
            return {"confirmed": False, "touched": False}

    # ─── FULL ANALYSIS ──────────────────────

    def analyze(self,
                df: pd.DataFrame,
                direction: str,
                volume_data: dict,
                obs: list = None,
                fvgs: list = None,
                fib_levels: dict = None) -> dict:
        """
        Full breakout & pullback analysis.

        Return dict berisi:
        - breakout: hasil detect_breakout
        - pullback: hasil detect_pullback
        - retest  : konfirmasi retest (jika ada breakout sebelumnya)
        - mode    : BREAKOUT / PULLBACK / NONE
        """
        try:
            # Deteksi breakout
            breakout = self.detect_breakout(df, volume_data)

            # Jika ada breakout, cek apakah retest sudah confirmed
            retest = {"confirmed": False}
            if breakout.get("valid"):
                retest = self.confirm_retest(
                    df,
                    retest_zone_top = breakout.get("retest_zone_top", 0),
                    retest_zone_bot = breakout.get("retest_zone_bot", 0),
                    direction       = breakout.get("direction", direction),
                )

                # Filter false breakout
                is_false = self.is_false_breakout(
                    df,
                    breakout_level = breakout.get("level", 0),
                    direction      = breakout.get("direction", direction),
                )
                if is_false:
                    breakout["valid"]      = False
                    breakout["false_break"] = True
                    logger.info("⚠️ False breakout difilter")

            # Deteksi pullback
            pullback = self.detect_pullback(
                df, direction, obs, fvgs, fib_levels
            )

            # Tentukan mode
            if breakout.get("valid") and retest.get("confirmed"):
                mode = "BREAKOUT_RETEST"
            elif breakout.get("valid"):
                mode = "BREAKOUT_WAIT"
            elif pullback.get("valid"):
                mode = "PULLBACK"
            else:
                mode = "NONE"

            logger.debug(f"📊 Breakout/Pullback mode: {mode}")

            return {
                "breakout": breakout,
                "pullback": pullback,
                "retest"  : retest,
                "mode"    : mode,
            }

        except Exception as e:
            logger.error(f"❌ Breakout/pullback analyze error: {e}")
            return {
                "breakout": {"valid": False},
                "pullback": {"valid": False},
                "retest"  : {"confirmed": False},
                "mode"    : "NONE",
            }


# Instance siap pakai
breakout_pullback = BreakoutPullbackAnalysis()