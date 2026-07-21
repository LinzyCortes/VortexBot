# ============================================
# VORTEX BOT - CONFLUENCE SCORING SYSTEM
# ============================================
#
# REDESIGN v3.0 (berdasarkan backtest_train_test_split.py -- VALIDASI
# OUT-OF-SAMPLE, metodologi paling ketat sejauh ini):
#
#   v2.1 divalidasi pakai train/test split kronologis (70% data awal
#   buat cari pola, 30% data akhir yang BELUM PERNAH disentuh buat
#   validasi). Hasilnya PENTING:
#
#   TEMUAN KRITIS: expectancy keseluruhan v2.1 di TEST set = -0.044R
#   (PF 0.94), padahal di TRAIN set +0.154R (PF 1.18). Bukti overfitting
#   di level SISTEM, bukan cuma komponen individual -- 3 ronde
#   "konsisten" sebelumnya ternyata masih nguji periode data yang sama,
#   BUKAN validasi asli.
#
#   TERVALIDASI (searah & signifikan di TRAIN dan TEST, paling dipercaya):
#     bos_confirmed : Train +0.493R, Test +0.311R -> naik 1->2
#     candle_ok     : Train +0.727R, Test +0.338R -> naik 1->2
#
#   GAGAL VALIDASI (arah kebalik train vs test -- ternyata cuma noise,
#   TERMASUK liquidity_swept yang sebelumnya kita naikin paling tinggi!):
#     liquidity_swept : Train +0.474R, Test -0.171R -> TURUN dari 3 ke 1
#                        (revert ke bobot awal, boost sebelumnya salah)
#     ema_aligned     : Train -0.066R, Test +0.317R -> tetap 1 (tidak diubah)
#     volume_ok       : Train +0.078R, Test -0.023R -> tetap 1 (tidak diubah)
#
#   BORDERLINE (searah tapi di bawah ambang batas -- perlu data lebih
#   banyak sebelum diputuskan, TIDAK diubah dulu):
#     fib_50   : Train +0.150R, Test +0.320R (searah, tapi train pas di
#                garis batas -- tetap 2, tidak dinaikkan lagi dulu)
#     stoch_ok : Train +0.126R, Test +0.712R (searah, gap test besar,
#                tapi train di bawah ambang -- tetap 2, worth diteliti lagi)
#     vwap_ok  : Train +0.089R, Test +0.232R (searah, kecil -- tetap 2)
#
#   PENTING: total max_score TETAP 21 (candle_ok +1, bos_confirmed +1,
#   liquidity_swept -2 -- saling menutupi).
#
#   WAJIB: bot ini BELUM TERBUKTI profitable out-of-sample (test set
#   masih -0.044R di v2.1). Setelah revisi v3.0 ini, WAJIB backtest
#   ulang dengan train/test split LAGI -- idealnya pakai window waktu
#   yang berbeda dari sebelumnya, supaya benar-benar independen dan
#   tidak ke-"intip" lagi. JANGAN pertimbangkan demo/live sebelum test
#   set menunjukkan expectancy positif yang konsisten.
#
# Phase guide (Railway Variables) -- REKOMENDASI SEMENTARA, validasi dulu:
#   Demo Phase 1 : MIN_CONFLUENCE_SCORE=9   (dari skala baru /21)
#   Demo Phase 2 : MIN_CONFLUENCE_SCORE=13
#   Live         : MIN_CONFLUENCE_SCORE=16

import pandas as pd
from config import cfg
from logger import logger


class ConfluenceScorer:

    def __init__(self):
        self.score_definitions = {
            # Teknikal
            "ema_aligned"      : {"points": 1, "desc": "EMA 13/21 aligned"},
            "stoch_ok"         : {"points": 2, "desc": "Stochastic (5,3,3) crossover di zone"},
            "volume_ok"        : {"points": 1, "desc": "Volume di atas rata-rata"},
            "candle_ok"        : {"points": 2, "desc": "Candle pattern konfirmasi (v3.0: TERVALIDASI out-of-sample, naik 1->2)"},
            # Breakout & Pullback
            "breakout_ok"      : {"points": 2, "desc": "Breakout valid dengan volume"},
            "pullback_ok"      : {"points": 1, "desc": "Pullback ke zona support/resistance"},
            # SMC
            "bos_confirmed"    : {"points": 2, "desc": "BOS/CHoCH fresh terkonfirmasi (v3.0: TERVALIDASI out-of-sample, naik 1->2)"},
            "ob_valid"         : {"points": 1, "desc": "Order Block valid (REDESIGN: 2->1, ExpGap -0.220R)"},
            "fvg_detected"     : {"points": 0, "desc": "FVG terdeteksi (REDESIGN: 1->0, ExpGap -0.195R -- info only)"},
            "liquidity_swept"  : {"points": 1, "desc": "Liquidity sudah di-sweep (v3.0: GAGAL VALIDASI out-of-sample, turun dari 3 balik ke 1 -- boost sebelumnya salah)"},
            "premium_discount" : {"points": 0, "desc": "Di area Premium/Discount (REDESIGN: 1->0, ExpGap -0.253R -- info only)"},
            # Fibonacci
            "fib_618"          : {"points": 0, "desc": "Fibonacci 0.618 confluence (REDESIGN: 2->0, ExpGap -0.488R!! -- info only)"},
            "fib_50"           : {"points": 2, "desc": "Fibonacci 0.500 confluence (REDESIGN: 1->2, ExpGap +0.390R)"},
            # Institutional
            "vwap_ok"          : {"points": 2, "desc": "VWAP zone sesuai direction"},
            "funding_ok"       : {"points": 1, "desc": "Funding rate kondusif"},
            "correlation_ok"   : {"points": 1, "desc": "BTC correlation searah (v2.1: DIBATALKAN dari 2, balik ke 1 -- ExpGap kebalik arah di ronde 2)"},
            # Filter
            "killzone_ok"      : {"points": 1, "desc": "Dalam Killzone session"},
            "news_clear"       : {"points": 1, "desc": "Tidak ada high-impact news"},
        }

        self.max_score = sum(
            v["points"] for v in self.score_definitions.values()
        )  # = 21 (v3.0, lihat REDESIGN v3.0 di atas)

    # ─── CALCULATE SCORE ────────────────────

    def calculate(self,
                  direction          : str,
                  indicators         : dict,
                  smc_analysis       : dict,
                  fib_analysis       : dict,
                  session_info       : dict,
                  news_status        : dict,
                  breakout_info      : dict = None,
                  pullback_info      : dict = None,
                  vwap_result        : dict = None,
                  funding_result     : dict = None,
                  correlation_result : dict = None) -> dict:
        """Hitung confluence score (max 21, lihat REDESIGN v3.0 di atas)."""
        try:
            score     = 0
            breakdown = {}
            reasons   = []

            if breakout_info       is None: breakout_info       = {}
            if pullback_info       is None: pullback_info       = {}
            if vwap_result         is None: vwap_result         = {}
            if funding_result      is None: funding_result      = {}
            if correlation_result  is None: correlation_result  = {}

            # ══════════════════════════════════
            # TEKNIKAL
            # ══════════════════════════════════

            # 1. EMA Aligned (1 poin)
            ema_bullish = indicators.get("ema_bullish", False)
            ema_ok = (
                (direction == "BUY"  and ema_bullish) or
                (direction == "SELL" and not ema_bullish)
            )
            if ema_ok:
                pts = self.score_definitions["ema_aligned"]["points"]
                score += pts
                breakdown["ema_aligned"] = pts
                reasons.append(f"✅ EMA 13/21 aligned ({direction})")
            else:
                breakdown["ema_aligned"] = 0
                reasons.append("❌ EMA tidak aligned")

            # 2. Stochastic (5,3,3) — maks 2 poin
            stoch_k    = indicators.get("stoch_k", 50)
            stoch_d    = indicators.get("stoch_d", 50)
            stoch_bull = indicators.get("stoch_bullish",   False)
            stoch_bear = indicators.get("stoch_bearish",   False)
            soft_bull  = indicators.get("stoch_soft_bull", False)
            soft_bear  = indicators.get("stoch_soft_bear", False)

            stoch_signal = (
                (direction == "BUY"  and stoch_bull) or
                (direction == "SELL" and stoch_bear)
            )
            stoch_soft = (
                (direction == "BUY"  and soft_bull) or
                (direction == "SELL" and soft_bear)
            )

            if stoch_signal:
                pts = self.score_definitions["stoch_ok"]["points"]
                score += pts
                breakdown["stoch_ok"] = pts
                zone = "oversold" if direction == "BUY" else "overbought"
                reasons.append(
                    f"✅ Stoch crossover di {zone} "
                    f"(%K={stoch_k:.1f} %D={stoch_d:.1f})"
                )
            elif stoch_soft:
                score += 1
                breakdown["stoch_ok"] = 1
                reasons.append(
                    f"⚠️ Stoch soft signal "
                    f"(%K={stoch_k:.1f} %D={stoch_d:.1f}) — 1 poin"
                )
            else:
                breakdown["stoch_ok"] = 0
                reasons.append(
                    f"❌ Stoch tidak mendukung "
                    f"(%K={stoch_k:.1f} %D={stoch_d:.1f})"
                )

            # 3. Volume (1 poin)
            vol_above = indicators.get("volume_above_avg", False)
            vol_ratio = indicators.get("volume_ratio", 0)
            if vol_above:
                pts = self.score_definitions["volume_ok"]["points"]
                score += pts
                breakdown["volume_ok"] = pts
                reasons.append(
                    f"✅ Volume {vol_ratio:.1f}x di atas rata-rata"
                )
            else:
                breakdown["volume_ok"] = 0
                reasons.append(f"❌ Volume {vol_ratio:.1f}x lemah")

            # 4. Candle Pattern (REDESIGN: 2 poin, dari 1)
            candle_dir = indicators.get("candle_direction")
            candle_det = indicators.get("candle_detected", False)
            candle_ok  = candle_det and candle_dir == direction
            if candle_ok:
                patterns = indicators.get("candle_pattern", [])
                pts = self.score_definitions["candle_ok"]["points"]
                score += pts
                breakdown["candle_ok"] = pts
                reasons.append(
                    f"✅ Candle: {', '.join(patterns)}"
                )
            else:
                breakdown["candle_ok"] = 0
                reasons.append("❌ Tidak ada candle pattern")

            # ══════════════════════════════════
            # BREAKOUT & PULLBACK
            # ══════════════════════════════════

            # 5. Breakout (maks 2 poin) -- TIDAK DIUBAH, data belum cukup
            bo_valid  = breakout_info.get("valid", False)
            bo_dir    = breakout_info.get("direction")
            bo_volume = breakout_info.get("volume_confirmed", False)

            if bo_valid and bo_dir == direction and bo_volume:
                pts = self.score_definitions["breakout_ok"]["points"]
                score += pts
                breakdown["breakout_ok"] = pts
                level = breakout_info.get("level", 0)
                btype = breakout_info.get("type", "")
                reasons.append(
                    f"✅ Breakout {btype} @ {level:.2f} + volume"
                )
            elif bo_valid and bo_dir == direction:
                score += 1
                breakdown["breakout_ok"] = 1
                reasons.append("⚠️ Breakout valid tapi volume lemah — 1 poin")
            else:
                breakdown["breakout_ok"] = 0
                reasons.append("❌ Tidak ada breakout valid")

            # 6. Pullback (1 poin) -- TIDAK DIUBAH, sample belum reliable
            pb_valid = pullback_info.get("valid", False)
            pb_dir   = pullback_info.get("direction")
            pb_depth = pullback_info.get("depth_pct", 0)

            if pb_valid and pb_dir == direction:
                pts = self.score_definitions["pullback_ok"]["points"]
                score += pts
                breakdown["pullback_ok"] = pts
                zone = pullback_info.get("zone", "")
                reasons.append(
                    f"✅ Pullback {pb_depth:.1f}% ke {zone}"
                )
            else:
                breakdown["pullback_ok"] = 0
                reasons.append("❌ Tidak ada pullback ke zona valid")

            # ══════════════════════════════════
            # SMC
            # ══════════════════════════════════

            # 7. BOS / CHoCH (REDESIGN: maks 1 poin fresh, dari 2; stale tetap dianggap 0)
            bos_4h         = smc_analysis.get("bos_4h",         False)
            choch_4h       = smc_analysis.get("choch_4h",       False)
            bos_1h         = smc_analysis.get("bos_1h",         False)
            choch_1h       = smc_analysis.get("choch_1h",       False)
            bos_4h_fresh   = smc_analysis.get("bos_4h_fresh",   False)
            choch_4h_fresh = smc_analysis.get("choch_4h_fresh", False)
            bos_1h_fresh   = smc_analysis.get("bos_1h_fresh",   False)
            choch_1h_fresh = smc_analysis.get("choch_1h_fresh", False)

            bos_ok    = bos_4h or choch_4h or bos_1h or choch_1h
            bos_fresh = (
                bos_4h_fresh or choch_4h_fresh or
                bos_1h_fresh or choch_1h_fresh
            )

            if bos_ok and bos_fresh:
                pts = self.score_definitions["bos_confirmed"]["points"]
                score += pts
                breakdown["bos_confirmed"] = pts
                bos_type = (
                    "BOS 4H"   if (bos_4h and bos_4h_fresh)    else
                    "CHoCH 4H" if (choch_4h and choch_4h_fresh) else
                    "BOS 1H"   if (bos_1h and bos_1h_fresh)     else
                    "CHoCH 1H"
                )
                reasons.append(f"✅ {bos_type} FRESH terkonfirmasi")
            elif bos_ok and not bos_fresh:
                breakdown["bos_confirmed"] = 0
                reasons.append(
                    "⚠️ BOS/CHoCH stale (>10 candle) — 0 poin (REDESIGN)"
                )
            else:
                breakdown["bos_confirmed"] = 0
                reasons.append("❌ BOS/CHoCH tidak terkonfirmasi")

            # 8. Order Block (REDESIGN: 1 poin, dari 2)
            in_ob   = smc_analysis.get("in_ob", False)
            ob_type = smc_analysis.get("ob_type", "")
            if in_ob:
                pts = self.score_definitions["ob_valid"]["points"]
                score += pts
                breakdown["ob_valid"] = pts
                reasons.append(f"✅ {ob_type} — harga di OB")
            else:
                breakdown["ob_valid"] = 0
                reasons.append("❌ Harga tidak di Order Block")

            # 9. FVG (REDESIGN: 0 poin, dari 1 -- info only, tetap dicatat di reasons)
            in_fvg   = smc_analysis.get("in_fvg", False)
            fvg_type = smc_analysis.get("fvg_type", "")
            if in_fvg:
                pts = self.score_definitions["fvg_detected"]["points"]
                score += pts
                breakdown["fvg_detected"] = pts
                reasons.append(f"ℹ️ {fvg_type} terdeteksi (0 poin — REDESIGN, info only)")
            else:
                breakdown["fvg_detected"] = 0
                reasons.append("❌ Tidak ada FVG")

            # 10. Liquidity Swept (v3.0: 1 poin, turun dari 3 -- GAGAL VALIDASI out-of-sample)
            liq_swept = smc_analysis.get("liquidity_swept", False)
            if liq_swept:
                pts = self.score_definitions["liquidity_swept"]["points"]
                score += pts
                breakdown["liquidity_swept"] = pts
                liq_type = "SSL" if direction == "BUY" else "BSL"
                reasons.append(
                    f"✅ {liq_type} swept → smart money aktif ({pts} poin)"
                )
            else:
                breakdown["liquidity_swept"] = 0
                reasons.append("❌ Liquidity belum di-sweep")

            # 11. Premium / Discount (REDESIGN: 0 poin, dari 1 -- info only)
            ideal_zone = smc_analysis.get("ideal_zone", False)
            if ideal_zone:
                pts = self.score_definitions["premium_discount"]["points"]
                score += pts
                breakdown["premium_discount"] = pts
                pd_data   = smc_analysis.get("premium_discount", {})
                zone_name = pd_data.get("zone", "")
                reasons.append(
                    f"ℹ️ Harga di {zone_name} Zone (0 poin — REDESIGN, info only)"
                )
            else:
                breakdown["premium_discount"] = 0
                reasons.append("❌ Harga tidak di area Premium/Discount")

            # ══════════════════════════════════
            # FIBONACCI
            # ══════════════════════════════════

            # 12. Fib 0.618 (REDESIGN: 0 poin, dari 2 -- ExpGap -0.488R, info only)
            fib_level = fib_analysis.get("fib_level", "")
            fib_at    = fib_analysis.get("at_fib", False)

            if fib_at and fib_level == "0.618":
                pts = self.score_definitions["fib_618"]["points"]
                score += pts
                breakdown["fib_618"] = pts
                reasons.append(
                    "ℹ️ Fibonacci 0.618 (0 poin — REDESIGN, data historis nunjukin ini justru merugi)"
                )
            else:
                breakdown["fib_618"] = 0

            # 13. Fib 0.500 (REDESIGN: 2 poin, dari 1)
            if fib_at and fib_level == "0.500":
                pts = self.score_definitions["fib_50"]["points"]
                score += pts
                breakdown["fib_50"] = pts
                reasons.append("✅ Fibonacci 0.500 — midpoint (REDESIGN: naik jadi 2 poin)")
            else:
                breakdown["fib_50"] = 0

            if fib_at and fib_level not in ["0.618", "0.500"]:
                reasons.append(
                    f"⚠️ Fibonacci {fib_level} (level minor)"
                )

            # ══════════════════════════════════
            # INSTITUTIONAL
            # ══════════════════════════════════

            # 14. VWAP Zone (maks 2 poin) -- TIDAK DIUBAH
            vwap_bonus  = vwap_result.get("score_bonus", 0)
            vwap_pass   = vwap_result.get("pass", True)
            vwap_reason = vwap_result.get("reason", "")

            if vwap_bonus >= 2:
                pts = 2
                score += pts
                breakdown["vwap_ok"] = pts
                reasons.append(vwap_reason or "✅ VWAP zone ideal")
            elif vwap_bonus == 1:
                score += 1
                breakdown["vwap_ok"] = 1
                reasons.append(vwap_reason or "⚠️ VWAP near — 1 poin")
            else:
                breakdown["vwap_ok"] = 0
                if vwap_reason:
                    reasons.append(vwap_reason)
                else:
                    reasons.append("❌ VWAP zone tidak ideal")

            # 15. Funding Rate (1 poin) -- TIDAK DIUBAH, tidak bisa dibacktest historis
            fund_bonus  = funding_result.get("score_bonus", 0)
            fund_pass   = funding_result.get("pass", True)
            fund_reason = funding_result.get("reason", "")
            fund_rate   = funding_result.get("rate", 0.0)

            if fund_bonus >= 1:
                pts = 1
                score += pts
                breakdown["funding_ok"] = pts
                reasons.append(
                    fund_reason or
                    f"✅ Funding rate kondusif ({fund_rate:+.4f}%)"
                )
            else:
                breakdown["funding_ok"] = 0
                reasons.append(
                    fund_reason or
                    f"❌ Funding rate tidak kondusif ({fund_rate:+.4f}%)"
                )

            # 16. BTC Correlation (REDESIGN: 2 poin, dari 1)
            corr_bonus  = correlation_result.get("score_bonus", 0)
            corr_pass   = correlation_result.get("pass", True)
            corr_reason = correlation_result.get("reason", "")
            corr_btc    = correlation_result.get("btc_trend", "N/A")
            is_btc_pair = correlation_result.get("is_btc_pair", False)

            if is_btc_pair:
                breakdown["correlation_ok"] = 0
            elif corr_bonus >= 1:
                pts = self.score_definitions["correlation_ok"]["points"]
                score += pts
                breakdown["correlation_ok"] = pts
                reasons.append(
                    corr_reason or
                    f"✅ BTC correlation mendukung ({corr_btc})"
                )
            else:
                breakdown["correlation_ok"] = 0
                reasons.append(
                    corr_reason or
                    f"⚠️ BTC correlation neutral ({corr_btc})"
                )

            # ══════════════════════════════════
            # FILTER
            # ══════════════════════════════════

            # 17. Killzone (1 poin) -- TIDAK DIUBAH
            in_kz        = session_info.get("in_killzone", False)
            session_name = session_info.get("session_name", "")
            avoid        = session_info.get("should_avoid", False)

            if in_kz and not avoid:
                pts = self.score_definitions["killzone_ok"]["points"]
                score += pts
                breakdown["killzone_ok"] = pts
                reasons.append(
                    f"✅ {session_name} — volume institusi aktif"
                )
            else:
                breakdown["killzone_ok"] = 0
                if avoid:
                    reasons.append(
                        f"❌ Waktu dihindari: "
                        f"{session_info.get('avoid_reason', '')}"
                    )
                else:
                    next_s = session_info.get("next_session", {})
                    reasons.append(
                        f"❌ Di luar Killzone — "
                        f"next: {next_s.get('name', 'N/A')}"
                    )

            # 18. News Clear (1 poin) -- TIDAK DIUBAH
            is_safe   = news_status.get("is_safe", True)
            news_list = news_status.get("unsafe_news", [])
            if is_safe:
                pts = self.score_definitions["news_clear"]["points"]
                score += pts
                breakdown["news_clear"] = pts
                reasons.append("✅ Tidak ada high-impact news")
            else:
                breakdown["news_clear"] = 0
                news_titles = [n["title"] for n in news_list[:2]]
                reasons.append(
                    f"❌ High-impact news: {', '.join(news_titles)}"
                )

            # ══════════════════════════════════
            # HARD BLOCK CHECK
            # ══════════════════════════════════

            vwap_hard_fail = (
                vwap_result.get("valid", False) and
                not vwap_pass and
                cfg.VWAP_ENABLED
            )
            funding_hard_fail = (
                funding_result.get("valid", False) and
                not fund_pass and
                cfg.FUNDING_RATE_ENABLED
            )
            correlation_hard_fail = (
                not corr_pass and
                not is_btc_pair
            )

            hard_fail = (
                vwap_hard_fail or
                funding_hard_fail or
                correlation_hard_fail
            )

            # ══════════════════════════════════
            # FINAL SCORE
            # ══════════════════════════════════

            min_score = cfg.MIN_CONFLUENCE_SCORE
            is_valid  = score >= min_score and not hard_fail
            grade     = self._get_grade(score)

            if hard_fail:
                fail_reason = []
                if vwap_hard_fail:
                    fail_reason.append("VWAP zone salah")
                if funding_hard_fail:
                    fail_reason.append("Funding rate ekstrem")
                if correlation_hard_fail:
                    fail_reason.append("BTC correlation berlawanan")
                reasons.append(
                    f"🚫 HARD BLOCK: {' + '.join(fail_reason)}"
                )

            result = {
                "score"         : score,
                "max_score"     : self.max_score,
                "min_required"  : min_score,
                "is_valid"      : is_valid,
                "hard_fail"     : hard_fail,
                "grade"         : grade,
                "direction"     : direction,
                "breakdown"     : breakdown,
                "reasons"       : reasons,
                "stoch_k"       : indicators.get("stoch_k", 0),
                "stoch_d"       : indicators.get("stoch_d", 0),
                "candle_pattern": indicators.get("candle_pattern", []),
                "breakout_mode" : breakout_info.get("valid", False),
                "pullback_mode" : pullback_info.get("valid", False),
                "vwap_zone"     : vwap_result.get("zone"),
                "funding_rate"  : funding_result.get("rate", 0.0),
                "btc_trend"     : corr_btc,
                "corr_pass"     : corr_pass,
                "bos_fresh"     : bos_fresh,
            }

            status = "✅ VALID" if is_valid else "❌ INVALID"
            logger.info(
                f"📊 Confluence: {score}/{self.max_score} "
                f"({grade}) {status} | {direction}"
                + (" | 🚫 HARD BLOCK" if hard_fail else "")
            )

            if not is_valid and not hard_fail:
                missing = min_score - score
                logger.info(f"   ⚠️ Kurang {missing} poin untuk entry")

            return result

        except Exception as e:
            logger.error(f"❌ Confluence calc error: {e}")
            return {
                "score"   : 0,
                "is_valid": False,
                "grade"   : "F",
                "reasons" : [f"Error: {str(e)}"],
            }

    # ─── GRADE SYSTEM ───────────────────────

    @staticmethod
    def _get_grade(score: int) -> str:
        """Grade berbasis max 21 poin (v2.1, dulu 24 original / 23 di v2.0)"""
        if score >= 18:
            return "A+ (Perfect Setup)"
        elif score >= 15:
            return "A  (Excellent)"
        elif score >= 13:
            return "B+ (Good)"
        elif score >= 9:
            return "B  (Average)"
        elif score >= 6:
            return "C  (Weak)"
        else:
            return "F  (Skip)"

    # ─── SUMMARY TEXT ───────────────────────

    def get_summary(self, result: dict) -> str:
        score     = result.get("score", 0)
        max_score = result.get("max_score", 21)
        grade     = result.get("grade", "F")
        direction = result.get("direction", "")
        is_valid  = result.get("is_valid", False)
        hard_fail = result.get("hard_fail", False)
        reasons   = result.get("reasons", [])

        if hard_fail:
            status = "🚫 HARD BLOCK"
        elif is_valid:
            status = "🟢 ENTRY VALID"
        else:
            status = "🔴 SKIP"

        mode_tags = []
        if result.get("breakout_mode"):
            mode_tags.append("BREAKOUT")
        if result.get("pullback_mode"):
            mode_tags.append("PULLBACK")
        mode_str = " | ".join(mode_tags) if mode_tags else "SMC"

        vwap_zone  = result.get("vwap_zone", "")
        fund_rate  = result.get("funding_rate", 0.0)
        btc_trend  = result.get("btc_trend", "")
        bos_fresh  = result.get("bos_fresh", False)

        lines = [
            f"\n{'='*45}",
            f"📊 CONFLUENCE SCORE: {score}/{max_score}",
            f"Grade    : {grade}",
            f"Mode     : {mode_str}",
            f"Direction: {direction}",
            f"VWAP     : {vwap_zone or 'N/A'}",
            f"Funding  : {fund_rate:+.4f}%",
            f"BTC      : {btc_trend or 'N/A'}",
            f"BOS Fresh: {'✅' if bos_fresh else '❌'}",
            f"Status   : {status}",
            f"{'='*45}",
            "\n📋 DETAIL SCORE:",
        ]
        lines.extend(reasons)

        if not is_valid and not hard_fail:
            missing = result.get("min_required", 10) - score
            lines.append(
                f"\n⚠️ Kurang {missing} poin untuk entry."
            )

        return "\n".join(lines)


# Instance siap pakai
confluence_scorer = ConfluenceScorer()