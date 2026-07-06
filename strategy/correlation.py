# ============================================
# VORTEX BOT - CORRELATION FILTER
# ============================================
#
# FIX v1.1 (baru):
#   - BTC_STRONG_MOVE_PCT dinaikkan dari 2.0% -> 3.5%.
#     Alasan: BTC bergerak +-2% dalam 12 jam itu VOLATILITAS
#     NORMAL, bukan "kuat". Threshold lama bikin BTC nyaris
#     selalu ke-label STRONG dari noise harian biasa, jadi
#     hampir semua sinyal altcoin yang gak persis searah BTC
#     otomatis diblok (lihat log: -2.01%, -2.06%, mepet di
#     atas threshold lama).
#   - Lookback diperpanjang dari 3 candle 4H (12 jam) jadi
#     6 candle 4H (24 jam) supaya trend yang dibaca lebih
#     representatif, bukan swing jangka pendek.
#   - Klasifikasi STRONG sekarang WAJIB dikonfirmasi EMA di
#     awal (bukan cuma "downgrade belakangan" seperti versi
#     lama). Kalau price move udah >= threshold tapi EMA
#     gak searah, langsung turun ke NORMAL, tidak pernah
#     naik ke STRONG dulu baru diturunkan.
#
# Logika institusi:
#   - BTC adalah market leader crypto
#   - Kalau BTC lagi bearish kuat -> hampir mustahil
#     ETH profit dari LONG
#   - Kalau BTC lagi bullish kuat -> SHORT ETH berisiko
#     karena tide masih naik
#
# Rules:
#   BUY  altcoin -> BTC harus tidak sedang downtrend kuat
#   SELL altcoin -> BTC harus tidak sedang uptrend kuat
#   BTC pair (BTCUSDT) -> skip filter (tidak perlu cek diri sendiri)

import pandas as pd
import numpy as np
from config import cfg
from logger import logger

# FIX: threshold dilonggarkan, lookback diperpanjang
BTC_STRONG_MOVE_PCT = 3.5   # BTC naik/turun >3.5% dalam 24H = kuat
BTC_LOOKBACK_CANDLES = 6    # cek 6 candle 4H terakhir = 24 jam


class CorrelationFilter:

    # ─── BTC TREND DETECTION ────────────────

    @staticmethod
    def get_btc_trend(df_btc_4h: pd.DataFrame) -> dict:
        """
        Deteksi trend BTC dari data 4H.

        FIX: klasifikasi STRONG sekarang butuh price move
        DAN konfirmasi EMA searah dari awal — bukan cuma
        turun kelas belakangan. Ini bikin label STRONG lebih
        jarang muncul tapi lebih valid begitu muncul.

        Return:
          trend     -> BULLISH / BEARISH / NEUTRAL
          strength  -> STRONG / NORMAL / WEAK
          move_pct  -> perubahan harga dalam % (N candle)
          valid     -> apakah data cukup
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

            # FIX: STRONG butuh EMA confirm dari awal, bukan
            # downgrade belakangan.
            if move_pct >= BTC_STRONG_MOVE_PCT and ema_bullish:
                trend    = "BULLISH"
                strength = "STRONG"
            elif move_pct >= 0.5:
                trend    = "BULLISH"
                strength = "NORMAL" if ema_bullish else "WEAK"
            elif move_pct <= -BTC_STRONG_MOVE_PCT and not ema_bullish:
                trend    = "BEARISH"
                strength = "STRONG"
            elif move_pct <= -0.5:
                trend    = "BEARISH"
                strength = "NORMAL" if not ema_bullish else "WEAK"
            else:
                trend    = "NEUTRAL"
                strength = "WEAK"

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
          BTC pair        -> skip (return pass=True)
          BUY  + BTC BEARISH STRONG  -> block
          SELL + BTC BULLISH STRONG  -> block
          Semua lainnya   -> pass (dengan info)
        """
        try:
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

            if direction == "BUY":
                if trend == "BEARISH" and strength == "STRONG":
                    return {**base,
                        "pass"      : False,
                        "score_bonus": 0,
                        "reason"    : (
                            f"❌ Correlation: BUY {pair} tapi BTC "
                            f"BEARISH STRONG ({move_pct:+.2f}%) — "
                            f"counter-market, skip"
                        )}

                elif trend == "BULLISH":
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
                    return {**base,
                        "pass"      : True,
                        "score_bonus": 0,
                        "reason"    : (
                            f"⚠️ Correlation: BTC {trend} "
                            f"({move_pct:+.2f}%) — "
                            f"BUY masih oke"
                        )}

            elif direction == "SELL":
                if trend == "BULLISH" and strength == "STRONG":
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
        """
        return self.check_correlation(pair, direction, df_btc_4h)


# Instance siap pakai
correlation_filter = CorrelationFilter()