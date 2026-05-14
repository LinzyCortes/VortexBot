# ============================================
# VORTEX BOT - VWAP ANALYSIS
# ============================================
#
# VWAP (Volume Weighted Average Price) adalah
# benchmark utama yang dipakai institusi besar.
#
# Logika institusi:
#   - Harga di BAWAH VWAP = discount zone → ideal BUY
#   - Harga di ATAS  VWAP = premium zone  → ideal SELL
#   - Entry melawan VWAP  = counter-institutional → skip
#
# Tambahan: VWAP bands (±1 std dev) untuk deteksi
# overextended price → potensi mean reversion ke VWAP.
#
# Data: OHLCV 1H dari exchange (gratis, API publik).

import pandas as pd
import numpy as np
from config import cfg
from logger import logger


class VWAPAnalysis:

    # ─── CALCULATE VWAP ─────────────────────

    @staticmethod
    def calculate_vwap(df: pd.DataFrame) -> pd.Series:
        """
        VWAP = cumsum(typical_price * volume) / cumsum(volume)
        Typical price = (high + low + close) / 3
        """
        try:
            typical_price = (
                df["high"] + df["low"] + df["close"]
            ) / 3
            cum_tp_vol = (typical_price * df["volume"]).cumsum()
            cum_vol    = df["volume"].cumsum()
            vwap       = cum_tp_vol / cum_vol
            return vwap
        except Exception as e:
            logger.error(f"❌ VWAP calc error: {e}")
            return pd.Series(dtype=float)

    @staticmethod
    def calculate_vwap_bands(df: pd.DataFrame,
                             vwap: pd.Series,
                             num_std: float = 1.0) -> dict:
        """
        VWAP bands ±1 std dev.
        Dipakai untuk deteksi overextended price.
        """
        try:
            typical_price = (
                df["high"] + df["low"] + df["close"]
            ) / 3
            variance = (
                (typical_price - vwap) ** 2 * df["volume"]
            ).cumsum() / df["volume"].cumsum()

            std_dev    = np.sqrt(variance)
            upper_band = vwap + (std_dev * num_std)
            lower_band = vwap - (std_dev * num_std)

            return {
                "upper": upper_band,
                "lower": lower_band,
                "std"  : std_dev,
            }
        except Exception as e:
            logger.error(f"❌ VWAP bands error: {e}")
            return {}

    # ─── DAILY VWAP ─────────────────────────

    def get_daily_vwap(self, df_1h: pd.DataFrame) -> dict:
        """
        Hitung VWAP harian dari data 1H.
        Reset tiap 00:00 UTC — standar institusi.
        """
        try:
            if df_1h.empty or len(df_1h) < 2:
                return {"valid": False}

            # Ambil candle hari ini (UTC)
            now_utc  = pd.Timestamp.now(tz="UTC")
            today    = now_utc.normalize()

            # Index mungkin timezone-aware atau naive
            idx = df_1h.index
            if idx.tz is not None:
                df_today = df_1h[idx >= today]
            else:
                today_naive = today.tz_localize(None)
                df_today    = df_1h[idx >= today_naive]

            # Fallback: pakai 24 candle terakhir
            if len(df_today) < 2:
                df_today = df_1h.tail(24)

            if df_today.empty:
                return {"valid": False}

            vwap_series = self.calculate_vwap(df_today)
            bands       = self.calculate_vwap_bands(
                df_today, vwap_series
            )

            current_vwap  = float(vwap_series.iloc[-1])
            current_price = float(df_today["close"].iloc[-1])

            upper  = float(bands["upper"].iloc[-1]) if bands else 0
            lower  = float(bands["lower"].iloc[-1]) if bands else 0
            std    = float(bands["std"].iloc[-1])   if bands else 0

            diff_pct = (
                (current_price - current_vwap) /
                current_vwap * 100
            )

            side = "above" if current_price > current_vwap else "below"
            zone = "PREMIUM" if side == "above" else "DISCOUNT"

            overextended = (
                current_price > upper or
                current_price < lower
            ) if (upper > 0 and lower > 0) else False

            tolerance = cfg.VWAP_TOLERANCE_PCT
            near_vwap = abs(diff_pct) <= tolerance

            logger.debug(
                f"📊 VWAP: ${current_vwap:.2f} | "
                f"price={current_price:.2f} | "
                f"zone={zone} | diff={diff_pct:+.2f}% | "
                f"overext={overextended}"
            )

            return {
                "valid"        : True,
                "vwap"         : current_vwap,
                "upper_band"   : upper,
                "lower_band"   : lower,
                "std_dev"      : std,
                "current_price": current_price,
                "side"         : side,
                "zone"         : zone,
                "diff_pct"     : diff_pct,
                "near_vwap"    : near_vwap,
                "overextended" : overextended,
                "candles_used" : len(df_today),
            }

        except Exception as e:
            logger.error(f"❌ Daily VWAP error: {e}")
            return {"valid": False}

    # ─── VWAP FILTER ────────────────────────

    def check_vwap_filter(self,
                          direction: str,
                          vwap_data: dict) -> dict:
        """
        Filter entry berdasarkan posisi harga vs VWAP.

        Score bonus:
          +2 → harga di zona yang benar & tidak overextended
          +1 → harga near VWAP (dalam tolerance)
           0 → harga di zona yang salah (tetap pass tapi no bonus)
          FAIL → overextended ke arah yang salah
        """
        try:
            if not vwap_data.get("valid"):
                return {
                    "pass"       : True,
                    "reason"     : "VWAP unavailable — bypassed",
                    "score_bonus": 0,
                    "side"       : None,
                    "zone"       : None,
                    "vwap_value" : None,
                }

            side         = vwap_data.get("side")
            zone         = vwap_data.get("zone")
            near_vwap    = vwap_data.get("near_vwap", False)
            overextended = vwap_data.get("overextended", False)
            diff_pct     = vwap_data.get("diff_pct", 0)
            vwap_val     = vwap_data.get("vwap", 0)

            base = {
                "side"      : side,
                "zone"      : zone,
                "diff_pct"  : diff_pct,
                "vwap_value": vwap_val,
                "near_vwap" : near_vwap,
            }

            if direction == "BUY":
                if side == "below" and not overextended:
                    return {**base, "pass": True, "score_bonus": 2,
                            "reason": (
                                f"✅ VWAP: DISCOUNT zone "
                                f"({diff_pct:+.2f}%) — ideal BUY"
                            )}
                elif near_vwap:
                    return {**base, "pass": True, "score_bonus": 1,
                            "reason": (
                                f"⚠️ VWAP: near VWAP "
                                f"({diff_pct:+.2f}%) — acceptable"
                            )}
                elif side == "above" and overextended:
                    return {**base, "pass": False, "score_bonus": 0,
                            "reason": (
                                f"❌ VWAP: BUY di PREMIUM overextended "
                                f"({diff_pct:+.2f}%) — skip"
                            )}
                else:
                    return {**base, "pass": True, "score_bonus": 0,
                            "reason": (
                                f"⚠️ VWAP: BUY di atas VWAP "
                                f"({diff_pct:+.2f}%) — tidak ideal"
                            )}

            elif direction == "SELL":
                if side == "above" and not overextended:
                    return {**base, "pass": True, "score_bonus": 2,
                            "reason": (
                                f"✅ VWAP: PREMIUM zone "
                                f"({diff_pct:+.2f}%) — ideal SELL"
                            )}
                elif near_vwap:
                    return {**base, "pass": True, "score_bonus": 1,
                            "reason": (
                                f"⚠️ VWAP: near VWAP "
                                f"({diff_pct:+.2f}%) — acceptable"
                            )}
                elif side == "below" and overextended:
                    return {**base, "pass": False, "score_bonus": 0,
                            "reason": (
                                f"❌ VWAP: SELL di DISCOUNT overextended "
                                f"({diff_pct:+.2f}%) — skip"
                            )}
                else:
                    return {**base, "pass": True, "score_bonus": 0,
                            "reason": (
                                f"⚠️ VWAP: SELL di bawah VWAP "
                                f"({diff_pct:+.2f}%) — tidak ideal"
                            )}

            return {**base, "pass": True, "score_bonus": 0,
                    "reason": "Direction unknown — bypassed"}

        except Exception as e:
            logger.error(f"❌ VWAP filter error: {e}")
            return {
                "pass": True, "score_bonus": 0,
                "reason": f"VWAP filter error — bypassed: {e}",
                "side": None, "zone": None,
            }

    # ─── VWAP REVERSION ─────────────────────

    def detect_vwap_reversion(self,
                               df: pd.DataFrame,
                               vwap_data: dict) -> dict:
        """
        Deteksi peluang mean reversion ke VWAP.

        Institusi sering entry saat harga overextended
        dan volume mulai exhausted → harga balik ke VWAP.
        Kondisi: overextended + volume exhaustion.
        """
        try:
            if not vwap_data.get("valid"):
                return {"detected": False}

            overextended  = vwap_data.get("overextended", False)
            side          = vwap_data.get("side", "")
            vwap_val      = vwap_data.get("vwap", 0)
            current_price = vwap_data.get("current_price", 0)

            if not overextended:
                return {"detected": False}

            recent_vol  = df["volume"].tail(3).mean()
            avg_vol     = df["volume"].tail(20).mean()
            vol_exhaust = (
                recent_vol < avg_vol * 0.7
                if avg_vol > 0 else False
            )

            reversion_dir = "SELL" if side == "above" else "BUY"
            dist_pct      = (
                abs(current_price - vwap_val) /
                vwap_val * 100
                if vwap_val > 0 else 0
            )

            return {
                "detected"   : True,
                "direction"  : reversion_dir,
                "target"     : vwap_val,
                "dist_pct"   : dist_pct,
                "vol_exhaust": vol_exhaust,
                "confidence" : "HIGH" if vol_exhaust else "NORMAL",
            }

        except Exception as e:
            logger.error(f"❌ VWAP reversion error: {e}")
            return {"detected": False}

    # ─── FULL ANALYSIS ──────────────────────

    def analyze(self, df_1h: pd.DataFrame,
                direction: str) -> dict:
        """
        Full VWAP analysis.
        Dipanggil dari main.py setelah data 1H tersedia.

        Return dict:
          valid        → apakah VWAP berhasil dihitung
          pass         → apakah signal boleh lanjut
          score_bonus  → poin bonus untuk confluence (0/1/2)
          vwap         → nilai VWAP saat ini
          side         → "above" / "below"
          zone         → "PREMIUM" / "DISCOUNT"
          diff_pct     → jarak harga dari VWAP dalam %
          reason       → teks penjelasan untuk log/notif
        """
        try:
            if not cfg.VWAP_ENABLED:
                return {
                    "valid"      : False,
                    "pass"       : True,
                    "score_bonus": 0,
                    "reason"     : "VWAP filter disabled",
                    "vwap"       : None,
                    "side"       : None,
                    "zone"       : None,
                }

            vwap_data  = self.get_daily_vwap(df_1h)
            filter_res = self.check_vwap_filter(direction, vwap_data)
            reversion  = self.detect_vwap_reversion(df_1h, vwap_data)

            return {
                "valid"        : vwap_data.get("valid", False),
                "vwap"         : vwap_data.get("vwap"),
                "upper_band"   : vwap_data.get("upper_band"),
                "lower_band"   : vwap_data.get("lower_band"),
                "side"         : vwap_data.get("side"),
                "zone"         : vwap_data.get("zone"),
                "diff_pct"     : vwap_data.get("diff_pct", 0),
                "near_vwap"    : vwap_data.get("near_vwap", False),
                "overextended" : vwap_data.get("overextended", False),
                "pass"         : filter_res.get("pass", True),
                "reason"       : filter_res.get("reason", ""),
                "score_bonus"  : filter_res.get("score_bonus", 0),
                "reversion"    : reversion,
            }

        except Exception as e:
            logger.error(f"❌ VWAP analyze error: {e}")
            return {
                "valid"      : False,
                "pass"       : True,
                "score_bonus": 0,
                "reason"     : f"VWAP error — bypassed: {e}",
                "vwap"       : None,
                "side"       : None,
                "zone"       : None,
            }


# Instance siap pakai
vwap_analyzer = VWAPAnalysis()