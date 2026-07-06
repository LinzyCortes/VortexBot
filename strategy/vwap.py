# ============================================
# VORTEX BOT - VWAP ANALYSIS
# ============================================
#
# FIX v1.4 (baru):
#   - calculate_vwap_bands sekarang pakai ROLLING window
#     (default 20 candle) untuk hitung std dev, BUKAN
#     cumulative dari awal hari (00:00 UTC).
#
#     KENAPA INI BUG: cumulative variance = rata-rata
#     deviasi SEPANJANG HARI. Begitu market trending
#     searah beberapa jam, deviasi SAAT INI jauh lebih
#     besar dari rata-rata historis hari itu -> flag
#     "overextended" jadi True HAMPIR TERUS-MENERUS di
#     jam-jam belakangan sesi (NY session khususnya),
#     padahal itu trend valid bukan blow-off/exhaustion.
#     Inilah penyebab hard block VWAP nyala nyaris tiap
#     signal.
#
# FIX v1.3 (sebelumnya, tetap dipertahankan):
#   - Session-aware tolerance
#   - Per-session VWAP (London & NY terpisah)
#   - Hard block hanya untuk overextended BERLAWANAN arah

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from config import cfg
from logger import logger

UTC = timezone.utc
WIB = timezone(timedelta(hours=7))


class VWAPAnalysis:

    # ─── SESSION HELPERS ────────────────────

    @staticmethod
    def _get_current_session() -> str:
        """
        Tentukan session aktif berdasarkan jam UTC.
        London : 08:00–11:30 UTC (15:00–18:30 WIB)
        NY     : 13:30–16:00 UTC (20:30–23:00 WIB)
        """
        now_utc = datetime.now(UTC)
        h = now_utc.hour
        m = now_utc.minute
        t = h * 60 + m

        london_open  = 8  * 60
        london_close = 11 * 60 + 30
        ny_open      = 13 * 60 + 30
        ny_close     = 16 * 60

        if london_open <= t <= london_close:
            return "london"
        elif ny_open <= t <= ny_close:
            return "new_york"
        else:
            return "off_session"

    @staticmethod
    def _get_tolerance_for_session(session: str) -> float:
        """
        Tolerance VWAP per session.

        London     : 0.5% — market baru buka, VWAP masih fresh
        NY         : 1.0% — VWAP sudah terbentuk 13+ jam
        Off-session: 0.3% — pakai cfg default (ketat)
        """
        if session == "london":
            return 0.5
        elif session == "new_york":
            return 1.0
        else:
            return cfg.VWAP_TOLERANCE_PCT  # default 0.3

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
                             num_std: float = 1.0,
                             window: int = 20) -> dict:
        """
        VWAP bands ±1 std dev untuk deteksi overextended.

        FIX v1.4: pakai ROLLING window (default 20 candle)
        untuk hitung variance, bukan cumsum dari awal hari.
        Ini bikin band merefleksikan volatilitas TERKINI,
        bukan rata-rata sepanjang hari yang bias saat
        market lagi trending.
        """
        try:
            typical_price = (
                df["high"] + df["low"] + df["close"]
            ) / 3
            deviation_sq = (
                (typical_price - vwap) ** 2 * df["volume"]
            )

            win = min(window, len(df)) if len(df) > 0 else 1
            win = max(win, 1)

            rolling_num = deviation_sq.rolling(
                window=win, min_periods=1
            ).sum()
            rolling_vol = df["volume"].rolling(
                window=win, min_periods=1
            ).sum()

            variance = rolling_num / rolling_vol.replace(0, np.nan)
            variance = variance.fillna(0)

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

        Tolerance dinamis per session (v1.3), band
        overextended pakai rolling window (v1.4).
        """
        try:
            if df_1h.empty or len(df_1h) < 2:
                return {"valid": False}

            now_utc = pd.Timestamp.now(tz="UTC")
            today   = now_utc.normalize()

            idx = df_1h.index
            if idx.tz is not None:
                df_today = df_1h[idx >= today]
            else:
                today_naive = today.tz_localize(None)
                df_today    = df_1h[idx >= today_naive]

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

            upper = float(bands["upper"].iloc[-1]) if bands else 0
            lower = float(bands["lower"].iloc[-1]) if bands else 0
            std   = float(bands["std"].iloc[-1])   if bands else 0

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

            session   = self._get_current_session()
            tolerance = self._get_tolerance_for_session(session)
            near_vwap = abs(diff_pct) <= tolerance

            logger.debug(
                f"📊 VWAP daily: ${current_vwap:.2f} | "
                f"price={current_price:.2f} | "
                f"zone={zone} | diff={diff_pct:+.2f}% | "
                f"session={session} | tol={tolerance}% | "
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
                "session"      : session,
                "tolerance_pct": tolerance,
                "candles_used" : len(df_today),
            }

        except Exception as e:
            logger.error(f"❌ Daily VWAP error: {e}")
            return {"valid": False}

    # ─── SESSION VWAP ───────────────────────

    def get_session_vwap(self, df_1h: pd.DataFrame,
                         session: str) -> dict:
        """
        Hitung VWAP per-session (London atau NY).
        """
        try:
            if df_1h.empty:
                return {"valid": False}

            now_utc = pd.Timestamp.now(tz="UTC")

            if session == "london":
                session_start = now_utc.normalize() + pd.Timedelta(hours=8)
            elif session == "new_york":
                session_start = (
                    now_utc.normalize() +
                    pd.Timedelta(hours=13, minutes=30)
                )
            else:
                return {"valid": False}

            idx = df_1h.index
            if idx.tz is not None:
                df_sess = df_1h[idx >= session_start]
            else:
                start_naive = session_start.tz_localize(None)
                df_sess     = df_1h[idx >= start_naive]

            if len(df_sess) < 1:
                return {"valid": False}

            vwap_series   = self.calculate_vwap(df_sess)
            session_vwap  = float(vwap_series.iloc[-1])
            current_price = float(df_sess["close"].iloc[-1])

            diff_pct = (
                (current_price - session_vwap) /
                session_vwap * 100
            )
            side = "above" if current_price > session_vwap else "below"

            return {
                "valid"        : True,
                "session"      : session,
                "vwap"         : session_vwap,
                "side"         : side,
                "diff_pct"     : diff_pct,
                "candles_used" : len(df_sess),
            }

        except Exception as e:
            logger.error(f"❌ Session VWAP error: {e}")
            return {"valid": False}

    # ─── VWAP FILTER ────────────────────────

    def check_vwap_filter(self,
                          direction: str,
                          vwap_data: dict) -> dict:
        """
        Filter entry berdasarkan posisi harga vs VWAP.

        Hard block HANYA untuk kondisi:
          - BUY  + overextended di atas VWAP
          - SELL + overextended di bawah VWAP
          - DAN sudah jauh > 2x tolerance dari VWAP

        Score bonus:
          +2 → zona ideal + tidak overextended
          +1 → near VWAP (dalam tolerance session)
           0 → zona kurang ideal tapi tidak hard block
        FAIL → overextended berlawanan arah (benar-benar counter)
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
            session      = vwap_data.get("session", "off_session")
            tolerance    = vwap_data.get("tolerance_pct",
                                         cfg.VWAP_TOLERANCE_PCT)

            base = {
                "side"      : side,
                "zone"      : zone,
                "diff_pct"  : diff_pct,
                "vwap_value": vwap_val,
                "near_vwap" : near_vwap,
                "session"   : session,
            }

            hard_block_threshold = tolerance * 2

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
                                f"({diff_pct:+.2f}%) [{session}] "
                                f"— acceptable"
                            )}
                elif (side == "above" and
                      abs(diff_pct) > hard_block_threshold and
                      overextended):
                    return {**base, "pass": False, "score_bonus": 0,
                            "reason": (
                                f"❌ VWAP: BUY overextended "
                                f"({diff_pct:+.2f}% > "
                                f"{hard_block_threshold:.1f}%) — skip"
                            )}
                else:
                    return {**base, "pass": True, "score_bonus": 0,
                            "reason": (
                                f"⚠️ VWAP: BUY di PREMIUM "
                                f"({diff_pct:+.2f}%) [{session}] "
                                f"— tidak ideal tapi boleh"
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
                                f"({diff_pct:+.2f}%) [{session}] "
                                f"— acceptable"
                            )}
                elif (side == "below" and
                      abs(diff_pct) > hard_block_threshold and
                      overextended):
                    return {**base, "pass": False, "score_bonus": 0,
                            "reason": (
                                f"❌ VWAP: SELL overextended bawah "
                                f"({diff_pct:+.2f}% > "
                                f"{hard_block_threshold:.1f}%) — skip"
                            )}
                else:
                    return {**base, "pass": True, "score_bonus": 0,
                            "reason": (
                                f"⚠️ VWAP: SELL di DISCOUNT "
                                f"({diff_pct:+.2f}%) [{session}] "
                                f"— tidak ideal tapi boleh"
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
        Deteksi mean reversion ke VWAP.
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
        Full VWAP analysis dengan session-aware tolerance
        dan rolling-window overextended detection.
        """
        try:
            if not cfg.VWAP_ENABLED:
                return {
                    "valid"        : False,
                    "pass"         : True,
                    "score_bonus"  : 0,
                    "reason"       : "VWAP filter disabled",
                    "vwap"         : None,
                    "side"         : None,
                    "zone"         : None,
                    "session"      : None,
                    "tolerance_pct": cfg.VWAP_TOLERANCE_PCT,
                }

            vwap_data  = self.get_daily_vwap(df_1h)
            filter_res = self.check_vwap_filter(direction, vwap_data)
            reversion  = self.detect_vwap_reversion(df_1h, vwap_data)

            session     = vwap_data.get("session", "off_session")
            session_vwap = {}
            if session in ("london", "new_york"):
                session_vwap = self.get_session_vwap(df_1h, session)

            result = {
                "valid"         : vwap_data.get("valid", False),
                "vwap"          : vwap_data.get("vwap"),
                "upper_band"    : vwap_data.get("upper_band"),
                "lower_band"    : vwap_data.get("lower_band"),
                "side"          : vwap_data.get("side"),
                "zone"          : vwap_data.get("zone"),
                "diff_pct"      : vwap_data.get("diff_pct", 0),
                "near_vwap"     : vwap_data.get("near_vwap", False),
                "overextended"  : vwap_data.get("overextended", False),
                "session"       : session,
                "tolerance_pct" : vwap_data.get(
                    "tolerance_pct", cfg.VWAP_TOLERANCE_PCT
                ),
                "pass"          : filter_res.get("pass", True),
                "reason"        : filter_res.get("reason", ""),
                "score_bonus"   : filter_res.get("score_bonus", 0),
                "reversion"     : reversion,
                "session_vwap"  : session_vwap,
            }

            logger.debug(
                f"📊 VWAP analyze: "
                f"session={session} | "
                f"tol={result['tolerance_pct']}% | "
                f"pass={result['pass']} | "
                f"bonus={result['score_bonus']}"
            )

            return result

        except Exception as e:
            logger.error(f"❌ VWAP analyze error: {e}")
            return {
                "valid"        : False,
                "pass"         : True,
                "score_bonus"  : 0,
                "reason"       : f"VWAP error — bypassed: {e}",
                "vwap"         : None,
                "side"         : None,
                "zone"         : None,
                "session"      : None,
                "tolerance_pct": cfg.VWAP_TOLERANCE_PCT,
            }


# Instance siap pakai
vwap_analyzer = VWAPAnalysis()