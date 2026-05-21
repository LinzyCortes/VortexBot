# ============================================
# VORTEX BOT - CORRELATION FILTER
# ============================================
#
# Filter ini cek apakah direction signal sejalan
# dengan kondisi BTC sebelum entry altcoin (ETH dll).
#
# Logika institusi:
#   - BTC adalah market leader crypto
#   - Kalau BTC lagi bearish kuat → hampir mustahil
#     ETH profit dari LONG
#   - Kalau BTC lagi bullish kuat → SHORT ETH berisiko
#     karena tide masih naik
#
# Rules:
#   BUY  altcoin → BTC harus tidak sedang downtrend kuat
#   SELL altcoin → BTC harus tidak sedang uptrend kuat
#   BTC pair (BTCUSDT) → skip filter (tidak perlu cek diri sendiri)
#
# Data: OHLCV BTC yang sudah di-fetch di main.py
# Tidak butuh API call tambahan.

import pandas as pd
import numpy as np
from config import cfg
from logger import logger

# Threshold untuk "kuat" — perubahan harga dalam %
BTC_STRONG_MOVE_PCT = 2.0   # BTC naik/turun >2% dalam 4H = kuat
BTC_LOOKBACK_CANDLES = 3    # cek 3 candle 4H terakhir = 12 jam


class CorrelationFilter:

    # ─── BTC TREND DETECTION ────────────────

    @staticmethod
    def get_btc_trend(df_btc_4h: pd.DataFrame) -> dict:
        """
        Deteksi trend BTC dari data 4H.

        Return:
          trend     → BULLISH / BEARISH / NEUTRAL
          strength  → STRONG / NORMAL / WEAK
          move_pct  → perubahan harga dalam % (N candle)
          valid     → apakah data cukup
        """
        try:
            if df_btc_4h is None or df_btc_4h.empty:
                return {
                    "valid"   : False,
                    "trend"   : "NEUTRAL",
                    "strength": "WEAK",
                    "move_pct": 0.0,
                }

            if len(df_btc_4h) < BTC_LOOKBACK_CANDLES + 2:
                return {
                    "valid"   : False,
                    "trend"   : "NEUTRAL",
                    "strength": "WEAK",
                    "move_pct": 0.0,
                }

            # Harga N candle lalu vs sekarang
            recent        = df_btc_4h.tail(BTC_LOOKBACK_CANDLES + 1)
            price_start   = float(recent["close"].iloc[0])
            price_now     = float(recent["close"].iloc[-1])
            move_pct      = (
                (price_now - price_start) / price_start * 100
            )

            # EMA slope untuk konfirmasi trend
            ema_fast = df_btc_4h["close"].ewm(
                span=13, adjust=False
            ).mean()
            ema_slow = df_btc_4h["close"].ewm(
                span=21, adjust=False
            ).mean()

            ema_bullish = float(ema_fast.iloc[-1]) > float(ema_slow.iloc[-1])

            # Klasifikasi
            if move_pct >= BTC_STRONG_MOVE_PCT:
                trend    = "BULLISH"
                strength = "STRONG"
            elif move_pct >= 0.5:
                trend    = "BULLISH"
                strength = "NORMAL"
            elif move_pct <= -BTC_STRONG_MOVE_PCT:
                trend    = "BEARISH"
                strength = "STRONG"
            elif move_pct <= -0.5:
                trend    = "BEARISH"
                strength = "NORMAL"
            else:
                trend    = "NEUTRAL"
                strength = "WEAK"

            # Downgrade strength kalau EMA tidak konfirmasi
            if trend == "BULLISH" and not ema_bullish:
                strength = "NORMAL" if strength == "STRONG" else "WEAK"
            elif trend == "BEARISH" and ema_bullish:
                strength = "NORMAL" if strength == "STRONG" else "WEAK"

            logger.debug(
                f"₿ BTC trend: {trend} ({strength}) | "
                f"move={move_pct:+.2f}% | "
                f"EMA={'bull' if ema_bullish else 'bear'}"
            )

            return {
                "valid"      : True,
                "trend"      : trend,
                "strength"   : strength,
                "move_pct"   : move_pct,
                "ema_bullish": ema_bullish,
                "price_now"  : price_now,
                "price_start": price_start,
            }

        except Exception as e:
            logger.error(f"❌ BTC trend error: {e}")
            return {
                "valid"   : False,
                "trend"   : "NEUTRAL",
                "strength": "WEAK",
                "move_pct": 0.0,
            }

    # ─── CORRELATION CHECK ──────────────────

    def check_correlation(self,
                          pair: str,
                          direction: str,
                          df_btc_4h: pd.DataFrame) -> dict:
        """
        Cek apakah direction signal sejalan dengan BTC.

        Rules:
          BTC pair        → skip (return pass=True)
          BUY  + BTC BEARISH STRONG  → block
          SELL + BTC BULLISH STRONG  → block
          Semua lainnya   → pass (dengan info)

        Score bonus:
          +1 → BTC trend searah dengan signal
           0 → BTC neutral atau tidak ada data
          Tidak ada pengurangan — hanya block kalau berlawanan kuat
        """
        try:
            # BTC pair tidak perlu cek correlation diri sendiri
            pair_upper = pair.upper()
            if "BTC" in pair_upper:
                return {
                    "pass"        : True,
                    "reason"      : "BTC pair — correlation skip",
                    "score_bonus" : 0,
                    "btc_trend"   : "N/A",
                    "btc_strength": "N/A",
                    "is_btc_pair" : True,
                }

            btc_data = self.get_btc_trend(df_btc_4h)

            if not btc_data.get("valid"):
                return {
                    "pass"        : True,
                    "reason"      : "BTC data unavailable — bypassed",
                    "score_bonus" : 0,
                    "btc_trend"   : "UNKNOWN",
                    "btc_strength": "UNKNOWN",
                    "is_btc_pair" : False,
                }

            trend    = btc_data["trend"]
            strength = btc_data["strength"]
            move_pct = btc_data["move_pct"]

            base = {
                "btc_trend"   : trend,
                "btc_strength": strength,
                "btc_move_pct": move_pct,
                "is_btc_pair" : False,
            }

            # ── BUY signal ───────────────────────────────────────────────────
            if direction == "BUY":
                if trend == "BEARISH" and strength == "STRONG":
                    # BTC turun kuat → BUY altcoin sangat berisiko
                    return {**base,
                        "pass"      : False,
                        "score_bonus": 0,
                        "reason"    : (
                            f"❌ Correlation: BUY {pair} tapi BTC "
                            f"BEARISH STRONG ({move_pct:+.2f}%) — "
                            f"counter-market, skip"
                        )}

                elif trend == "BULLISH":
                    # BTC naik → BUY altcoin ideal
                    bonus = 1 if strength == "STRONG" else 0
                    return {**base,
                        "pass"      : True,
                        "score_bonus": bonus,
                        "reason"    : (
                            f"✅ Correlation: BTC BULLISH "
                            f"({move_pct:+.2f}%) — "
                            f"mendukung BUY"
                        )}

                else:
                    # BTC neutral atau BEARISH tapi tidak kuat
                    return {**base,
                        "pass"      : True,
                        "score_bonus": 0,
                        "reason"    : (
                            f"⚠️ Correlation: BTC {trend} "
                            f"({move_pct:+.2f}%) — "
                            f"BUY masih oke"
                        )}

            # ── SELL signal ──────────────────────────────────────────────────
            elif direction == "SELL":
                if trend == "BULLISH" and strength == "STRONG":
                    # BTC naik kuat → SELL altcoin sangat berisiko
                    return {**base,
                        "pass"      : False,
                        "score_bonus": 0,
                        "reason"    : (
                            f"❌ Correlation: SELL {pair} tapi BTC "
                            f"BULLISH STRONG ({move_pct:+.2f}%) — "
                            f"counter-market, skip"
                        )}

                elif trend == "BEARISH":
                    bonus = 1 if strength == "STRONG" else 0
                    return {**base,
                        "pass"      : True,
                        "score_bonus": bonus,
                        "reason"    : (
                            f"✅ Correlation: BTC BEARISH "
                            f"({move_pct:+.2f}%) — "
                            f"mendukung SELL"
                        )}

                else:
                    return {**base,
                        "pass"      : True,
                        "score_bonus": 0,
                        "reason"    : (
                            f"⚠️ Correlation: BTC {trend} "
                            f"({move_pct:+.2f}%) — "
                            f"SELL masih oke"
                        )}

            return {**base,
                "pass"      : True,
                "score_bonus": 0,
                "reason"    : "Direction unknown — bypassed",
            }

        except Exception as e:
            logger.error(f"❌ Correlation check error: {e}")
            return {
                "pass"        : True,
                "score_bonus" : 0,
                "reason"      : f"Correlation error — bypassed: {e}",
                "btc_trend"   : "ERROR",
                "btc_strength": "ERROR",
                "is_btc_pair" : False,
            }

    # ─── FULL ANALYSIS ──────────────────────

    def analyze(self, pair: str,
                direction: str,
                df_btc_4h: pd.DataFrame) -> dict:
        """
        Full correlation analysis.
        Dipanggil dari main.py setelah SMC analysis.

        Return:
          pass         → boleh entry atau tidak
          score_bonus  → 0 atau 1
          btc_trend    → BULLISH / BEARISH / NEUTRAL
          btc_strength → STRONG / NORMAL / WEAK
          reason       → teks untuk log/notif
        """
        return self.check_correlation(pair, direction, df_btc_4h)


# Instance siap pakai
correlation_filter = CorrelationFilter()