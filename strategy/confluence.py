# ============================================
# VORTEX BOT - CONFLUENCE SCORING SYSTEM
# ============================================

import pandas as pd
from config import cfg
from logger import logger


class ConfluenceScorer:
    """
    Sistem scoring 16 poin untuk validasi entry.
    Bot hanya entry jika score >= MIN_CONFLUENCE_SCORE (11)
    """

    def __init__(self):
        # Definisi semua poin confluence
        self.score_definitions = {
            # Teknikal Klasik
            "ema_aligned"       : {"points": 1, "desc": "EMA 13/21 aligned"},
            "rsi_ok"            : {"points": 1, "desc": "RSI zona netral"},
            "macd_ok"           : {"points": 1, "desc": "MACD konfirmasi"},
            "adx_ok"            : {"points": 1, "desc": "ADX > 25 trend kuat"},
            "volume_ok"         : {"points": 1, "desc": "Volume di atas rata-rata"},
            "candle_ok"         : {"points": 1, "desc": "Candle pattern konfirmasi"},

            # SMC
            "bos_confirmed"     : {"points": 2, "desc": "BOS/CHoCH terkonfirmasi"},
            "ob_valid"          : {"points": 2, "desc": "Order Block valid"},
            "fvg_detected"      : {"points": 1, "desc": "FVG terdeteksi"},
            "liquidity_swept"   : {"points": 1, "desc": "Liquidity sudah di-sweep"},
            "premium_discount"  : {"points": 1, "desc": "Di area Premium/Discount"},

            # Fibonacci
            "fib_618"           : {"points": 2, "desc": "Fibonacci 0.618 confluence"},
            "fib_50"            : {"points": 1, "desc": "Fibonacci 0.500 confluence"},

            # Filter
            "killzone_ok"       : {"points": 1, "desc": "Dalam Killzone session"},
            "news_clear"        : {"points": 1, "desc": "Tidak ada high-impact news"},
        }

        self.max_score = sum(
            v["points"] for v in self.score_definitions.values()
        )

    # ─── CALCULATE SCORE ────────────────────

    def calculate(self,
                  direction     : str,
                  indicators    : dict,
                  smc_analysis  : dict,
                  fib_analysis  : dict,
                  session_info  : dict,
                  news_status   : dict) -> dict:
        """
        Hitung confluence score berdasarkan
        semua kondisi yang terpenuhi
        """
        try:
            score     = 0
            breakdown = {}
            reasons   = []

            # ══════════════════════════════════
            # TEKNIKAL KLASIK
            # ══════════════════════════════════

            # 1. EMA Aligned (1 poin)
            ema_bullish = indicators.get("ema_bullish", False)
            ema_bearish = not ema_bullish
            ema_ok = (
                (direction == "BUY"  and ema_bullish) or
                (direction == "SELL" and ema_bearish)
            )
            if ema_ok:
                pts = self.score_definitions["ema_aligned"]["points"]
                score += pts
                breakdown["ema_aligned"] = pts
                reasons.append(
                    f"✅ EMA 13/21 aligned ({direction})"
                )
            else:
                breakdown["ema_aligned"] = 0
                reasons.append("❌ EMA tidak aligned")

            # 2. RSI OK (1 poin)
            rsi      = indicators.get("rsi", 50)
            rsi_ok   = (
                cfg.RSI_NEUTRAL_LOW <= rsi <= cfg.RSI_NEUTRAL_HI
            )
            # Tambahan: oversold untuk buy, overbought untuk sell
            rsi_extreme_ok = (
                (direction == "BUY"  and rsi < 45) or
                (direction == "SELL" and rsi > 55)
            )
            if rsi_ok or rsi_extreme_ok:
                pts = self.score_definitions["rsi_ok"]["points"]
                score += pts
                breakdown["rsi_ok"] = pts
                reasons.append(f"✅ RSI {rsi:.1f} zona ok")
            else:
                breakdown["rsi_ok"] = 0
                reasons.append(f"❌ RSI {rsi:.1f} tidak ideal")

            # 3. MACD OK (1 poin)
            macd_hist = indicators.get("macd_histogram", 0)
            macd_ok   = (
                (direction == "BUY"  and macd_hist > 0) or
                (direction == "SELL" and macd_hist < 0)
            )
            if macd_ok:
                pts = self.score_definitions["macd_ok"]["points"]
                score += pts
                breakdown["macd_ok"] = pts
                reasons.append(
                    f"✅ MACD histogram "
                    f"{'positif' if macd_hist > 0 else 'negatif'}"
                )
            else:
                breakdown["macd_ok"] = 0
                reasons.append("❌ MACD tidak mendukung")

            # 4. ADX OK (1 poin)
            adx    = indicators.get("adx", 0)
            adx_ok = adx > cfg.ADX_THRESHOLD
            if adx_ok:
                pts = self.score_definitions["adx_ok"]["points"]
                score += pts
                breakdown["adx_ok"] = pts
                reasons.append(f"✅ ADX {adx:.1f} > 25 trend kuat")
            else:
                breakdown["adx_ok"] = 0
                reasons.append(f"❌ ADX {adx:.1f} < 25 sideways")

            # 5. Volume OK (1 poin)
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
                reasons.append(
                    f"❌ Volume {vol_ratio:.1f}x di bawah rata-rata"
                )

            # 6. Candle Pattern (1 poin)
            candle_dir = indicators.get("candle_direction")
            candle_det = indicators.get("candle_detected", False)
            candle_ok  = (
                candle_det and candle_dir == direction
            )
            if candle_ok:
                patterns = indicators.get("candle_pattern", [])
                pts = self.score_definitions["candle_ok"]["points"]
                score += pts
                breakdown["candle_ok"] = pts
                reasons.append(
                    f"✅ Candle pattern: {', '.join(patterns)}"
                )
            else:
                breakdown["candle_ok"] = 0
                reasons.append("❌ Tidak ada candle pattern")

            # ══════════════════════════════════
            # SMC ANALYSIS
            # ══════════════════════════════════

            # 7. BOS / CHoCH (2 poin)
            bos_4h   = smc_analysis.get("bos_4h",  False)
            choch_4h = smc_analysis.get("choch_4h", False)
            bos_1h   = smc_analysis.get("bos_1h",  False)
            choch_1h = smc_analysis.get("choch_1h", False)
            bos_ok   = bos_4h or choch_4h or bos_1h or choch_1h

            if bos_ok:
                pts = self.score_definitions["bos_confirmed"]["points"]
                score += pts
                breakdown["bos_confirmed"] = pts
                bos_type = (
                    "BOS 4H" if bos_4h else
                    "CHoCH 4H" if choch_4h else
                    "BOS 1H" if bos_1h else "CHoCH 1H"
                )
                reasons.append(f"✅ {bos_type} terkonfirmasi")
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
                reasons.append(f"✅ {ob_type} valid — harga di OB")
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
                liq_type = (
                    "SSL" if direction == "BUY" else "BSL"
                )
                reasons.append(
                    f"✅ {liq_type} sudah di-sweep "
                    f"→ smart money aktif"
                )
            else:
                breakdown["liquidity_swept"] = 0
                reasons.append("❌ Liquidity belum di-sweep")

            # 11. Premium / Discount Zone (1 poin)
            ideal_zone = smc_analysis.get("ideal_zone", False)
            if ideal_zone:
                pts = self.score_definitions["premium_discount"]["points"]
                score += pts
                breakdown["premium_discount"] = pts
                pd_data  = smc_analysis.get("premium_discount", {})
                zone_name = pd_data.get("zone", "")
                reasons.append(
                    f"✅ Harga di {zone_name} Zone "
                    f"→ area ideal entry"
                )
            else:
                breakdown["premium_discount"] = 0
                reasons.append(
                    "❌ Harga tidak di area ideal "
                    "(Premium/Discount)"
                )

            # ══════════════════════════════════
            # FIBONACCI
            # ══════════════════════════════════

            # 12. Fibonacci 0.618 (2 poin)
            fib_level    = fib_analysis.get("fib_level", "")
            fib_at       = fib_analysis.get("at_fib", False)
            fib_strength = fib_analysis.get("fib_strength", "")

            if fib_at and fib_level == "0.618":
                pts = self.score_definitions["fib_618"]["points"]
                score += pts
                breakdown["fib_618"] = pts
                reasons.append(
                    "✅ Fibonacci 0.618 (Golden Ratio) "
                    "→ level terkuat!"
                )
            else:
                breakdown["fib_618"] = 0

            # 13. Fibonacci 0.500 (1 poin)
            if fib_at and fib_level == "0.500":
                pts = self.score_definitions["fib_50"]["points"]
                score += pts
                breakdown["fib_50"] = pts
                reasons.append(
                    "✅ Fibonacci 0.500 "
                    "→ midpoint level penting"
                )
            else:
                breakdown["fib_50"] = 0

            # Fibonacci lain (0.382, 0.786) = 0 poin
            # tapi tetap dicatat
            if fib_at and fib_level not in ["0.618", "0.500"]:
                reasons.append(
                    f"⚠️ Fibonacci {fib_level} "
                    f"(level minor, no extra points)"
                )

            # ══════════════════════════════════
            # FILTERS
            # ══════════════════════════════════

            # 14. Killzone (1 poin)
            in_killzone  = session_info.get("in_killzone", False)
            session_name = session_info.get("session_name", "")
            avoid        = session_info.get("should_avoid", False)

            if in_killzone and not avoid:
                pts = self.score_definitions["killzone_ok"]["points"]
                score += pts
                breakdown["killzone_ok"] = pts
                reasons.append(
                    f"✅ Dalam {session_name} "
                    f"→ volume institusi aktif"
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

            # 15. News Clear (1 poin)
            is_safe    = news_status.get("is_safe", True)
            news_list  = news_status.get("unsafe_news", [])
            if is_safe:
                pts = self.score_definitions["news_clear"]["points"]
                score += pts
                breakdown["news_clear"] = pts
                reasons.append(
                    "✅ Tidak ada high-impact news"
                )
            else:
                breakdown["news_clear"] = 0
                news_titles = [n["title"] for n in news_list[:2]]
                reasons.append(
                    f"❌ High-impact news: "
                    f"{', '.join(news_titles)}"
                )

            # ══════════════════════════════════
            # FINAL SCORE
            # ══════════════════════════════════

            min_score  = cfg.MIN_CONFLUENCE_SCORE
            is_valid   = score >= min_score
            grade      = self._get_grade(score)

            result = {
                "score"      : score,
                "max_score"  : self.max_score,
                "min_required": min_score,
                "is_valid"   : is_valid,
                "grade"      : grade,
                "direction"  : direction,
                "breakdown"  : breakdown,
                "reasons"    : reasons,
                "rsi_value"  : indicators.get("rsi", 0),
                "adx_value"  : indicators.get("adx", 0),
                "candle_pattern": indicators.get(
                    "candle_pattern", []
                ),
            }

            # Log hasil
            status = "✅ VALID" if is_valid else "❌ INVALID"
            logger.info(
                f"📊 Confluence Score: {score}/{self.max_score} "
                f"({grade}) {status} | {direction}"
            )

            if not is_valid:
                missing = min_score - score
                logger.info(
                    f"   ⚠️ Kurang {missing} poin untuk entry"
                )

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
        """Konversi score ke grade"""
        if score >= 14:
            return "A+ (Perfect Setup)"
        elif score >= 12:
            return "A  (Excellent)"
        elif score >= 11:
            return "B+ (Good)"
        elif score >= 9:
            return "B  (Average)"
        elif score >= 7:
            return "C  (Weak)"
        else:
            return "F  (Skip)"

    # ─── SUMMARY TEXT ───────────────────────

    def get_summary(self, result: dict) -> str:
        """Generate summary text dari confluence result"""
        score     = result.get("score", 0)
        max_score = result.get("max_score", 16)
        grade     = result.get("grade", "F")
        direction = result.get("direction", "")
        is_valid  = result.get("is_valid", False)
        reasons   = result.get("reasons", [])

        status = "🟢 ENTRY VALID" if is_valid else "🔴 SKIP"

        lines = [
            f"\n{'='*45}",
            f"📊 CONFLUENCE SCORE: {score}/{max_score}",
            f"Grade    : {grade}",
            f"Direction: {direction}",
            f"Status   : {status}",
            f"{'='*45}",
            "\n📋 DETAIL SCORE:",
        ]
        lines.extend(reasons)

        if not is_valid:
            missing = result.get("min_required", 11) - score
            lines.append(
                f"\n⚠️ Kurang {missing} poin untuk entry. "
                f"Bot akan skip setup ini."
            )

        return "\n".join(lines)


# Instance siap pakai
confluence_scorer = ConfluenceScorer()