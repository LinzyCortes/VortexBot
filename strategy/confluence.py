# ============================================
# VORTEX BOT - CONFLUENCE SCORING SYSTEM
# ============================================
#
# Breakdown 24 poin:
#
#   TEKNIKAL (5)
#     EMA align        : 1
#     Stoch (5,3,3)    : 2
#     Volume           : 1
#     Candle pattern   : 1
#
#   BREAKOUT & PULLBACK (3)
#     Breakout         : 2
#     Pullback         : 1
#
#   SMC (7)
#     BOS/CHoCH fresh  : 2  (stale = 1 poin)
#     Order Block      : 2
#     FVG              : 1
#     Liquidity swept  : 1
#     Premium/Discount : 1
#
#   FIBONACCI (3)
#     Fib 0.618        : 2
#     Fib 0.500        : 1
#
#   INSTITUTIONAL (4)
#     VWAP zone        : 2
#     Funding rate     : 1
#     BTC Correlation  : 1
#
#   FILTER (2)
#     Killzone         : 1
#     News clear       : 1
#
#   TOTAL              : 24
#
# Phase guide (Railway Variables):
#   Demo Phase 1 : MIN_CONFLUENCE_SCORE=11
#   Demo Phase 2 : MIN_CONFLUENCE_SCORE=15
#   Live         : MIN_CONFLUENCE_SCORE=18

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
            "candle_ok"        : {"points": 1, "desc": "Candle pattern konfirmasi"},
            # Breakout & Pullback
            "breakout_ok"      : {"points": 2, "desc": "Breakout valid dengan volume"},
            "pullback_ok"      : {"points": 1, "desc": "Pullback ke zona support/resistance"},
            # SMC
            "bos_confirmed"    : {"points": 2, "desc": "BOS/CHoCH fresh terkonfirmasi"},
            "ob_valid"         : {"points": 2, "desc": "Order Block valid"},
            "fvg_detected"     : {"points": 1, "desc": "FVG terdeteksi"},
            "liquidity_swept"  : {"points": 1, "desc": "Liquidity sudah di-sweep"},
            "premium_discount" : {"points": 1, "desc": "Di area Premium/Discount"},
            # Fibonacci
            "fib_618"          : {"points": 2, "desc": "Fibonacci 0.618 confluence"},
            "fib_50"           : {"points": 1, "desc": "Fibonacci 0.500 confluence"},
            # Institutional
            "vwap_ok"          : {"points": 2, "desc": "VWAP zone sesuai direction"},
            "funding_ok"       : {"points": 1, "desc": "Funding rate kondusif"},
            "correlation_ok"   : {"points": 1, "desc": "BTC correlation searah"},
            # Filter
            "killzone_ok"      : {"points": 1, "desc": "Dalam Killzone session"},
            "news_clear"       : {"points": 1, "desc": "Tidak ada high-impact news"},
        }

        self.max_score = sum(
            v["points"] for v in self.score_definitions.values()
        )  # = 24

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
        """Hitung confluence score 24 poin."""
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

            # 4. Candle Pattern (1 poin)
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

            # 5. Breakout (maks 2 poin)
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

            # 6. Pullback (1 poin)
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

            # 7. BOS / CHoCH (2 poin fresh, 1 poin stale)
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
                # BOS fresh → full 2 poin
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
                # BOS stale → 1 poin
                score += 1
                breakdown["bos_confirmed"] = 1
                reasons.append(
                    "⚠️ BOS/CHoCH stale (>10 candle) — 1 poin"
                )
            else:
                breakdown["bos_confirmed"] = 0
                reasons.append("❌ BOS/CHoCH tidak terkonfirmasi")

            # 8. Order Block (2 poin)
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

            # 9. FVG (1 poin)
            in_fvg   = smc_analysis.get("in_fvg", False)
            fvg_type = smc_analysis.get("fvg_type", "")
            if in_fvg:
                pts = self.score_definitions["fvg_detected"]["points"]
                score += pts
                breakdown["fvg_detected"] = pts
                reasons.append(f"✅ {fvg_type} terdeteksi")
            else:
                breakdown["fvg_detected"] = 0
                reasons.append("❌ Tidak ada FVG")

            # 10. Liquidity Swept (1 poin)
            liq_swept = smc_analysis.get("liquidity_swept", False)
            if liq_swept:
                pts = self.score_definitions["liquidity_swept"]["points"]
                score += pts
                breakdown["liquidity_swept"] = pts
                liq_type = "SSL" if direction == "BUY" else "BSL"
                reasons.append(
                    f"✅ {liq_type} swept → smart money aktif"
                )
            else:
                breakdown["liquidity_swept"] = 0
                reasons.append("❌ Liquidity belum di-sweep")

            # 11. Premium / Discount (1 poin)
            ideal_zone = smc_analysis.get("ideal_zone", False)
            if ideal_zone:
                pts = self.score_definitions["premium_discount"]["points"]
                score += pts
                breakdown["premium_discount"] = pts
                pd_data   = smc_analysis.get("premium_discount", {})
                zone_name = pd_data.get("zone", "")
                reasons.append(
                    f"✅ Harga di {zone_name} Zone — ideal entry"
                )
            else:
                breakdown["premium_discount"] = 0
                reasons.append("❌ Harga tidak di area Premium/Discount")

            # ══════════════════════════════════
            # FIBONACCI
            # ══════════════════════════════════

            # 12. Fib 0.618 (2 poin)
            fib_level = fib_analysis.get("fib_level", "")
            fib_at    = fib_analysis.get("at_fib", False)

            if fib_at and fib_level == "0.618":
                pts = self.score_definitions["fib_618"]["points"]
                score += pts
                breakdown["fib_618"] = pts
                reasons.append(
                    "✅ Fibonacci 0.618 (Golden Ratio) — level terkuat!"
                )
            else:
                breakdown["fib_618"] = 0

            # 13. Fib 0.500 (1 poin)
            if fib_at and fib_level == "0.500":
                pts = self.score_definitions["fib_50"]["points"]
                score += pts
                breakdown["fib_50"] = pts
                reasons.append("✅ Fibonacci 0.500 — midpoint")
            else:
                breakdown["fib_50"] = 0

            if fib_at and fib_level not in ["0.618", "0.500"]:
                reasons.append(
                    f"⚠️ Fibonacci {fib_level} (level minor)"
                )

            # ══════════════════════════════════
            # INSTITUTIONAL
            # ══════════════════════════════════

            # 14. VWAP Zone (maks 2 poin)
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

            # 15. Funding Rate (1 poin)
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

            # 16. BTC Correlation (1 poin)
            corr_bonus  = correlation_result.get("score_bonus", 0)
            corr_pass   = correlation_result.get("pass", True)
            corr_reason = correlation_result.get("reason", "")
            corr_btc    = correlation_result.get("btc_trend", "N/A")
            is_btc_pair = correlation_result.get("is_btc_pair", False)

            if is_btc_pair:
                # BTC pair tidak perlu cek correlation diri sendiri
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

            # 17. Killzone (1 poin)
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

            # 18. News Clear (1 poin)
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
        """Grade berbasis max 24 poin"""
        if score >= 21:
            return "A+ (Perfect Setup)"
        elif score >= 18:
            return "A  (Excellent)"
        elif score >= 15:
            return "B+ (Good)"
        elif score >= 11:
            return "B  (Average)"
        elif score >= 8:
            return "C  (Weak)"
        else:
            return "F  (Skip)"

    # ─── SUMMARY TEXT ───────────────────────

    def get_summary(self, result: dict) -> str:
        score     = result.get("score", 0)
        max_score = result.get("max_score", 24)
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
            missing = result.get("min_required", 11) - score
            lines.append(
                f"\n⚠️ Kurang {missing} poin untuk entry."
            )

        return "\n".join(lines)


# Instance siap pakai
confluence_scorer = ConfluenceScorer()