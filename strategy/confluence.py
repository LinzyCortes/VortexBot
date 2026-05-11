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

    UPDATE:
    - Hapus MACD (lagging, redundan dengan EMA)
    - Hapus ADX  (lagging, redundan dengan EMA + SMC)
    - Ganti RSI dengan Stochastic (5,3,3) — lebih responsif
    - Tambah Breakout score (2 poin)
    - Tambah Pullback score (1 poin)
    - Total tetap 16 poin
    """

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
            "bos_confirmed"    : {"points": 2, "desc": "BOS/CHoCH terkonfirmasi"},
            "ob_valid"         : {"points": 2, "desc": "Order Block valid"},
            "fvg_detected"     : {"points": 1, "desc": "FVG terdeteksi"},
            "liquidity_swept"  : {"points": 1, "desc": "Liquidity sudah di-sweep"},
            "premium_discount" : {"points": 1, "desc": "Di area Premium/Discount"},

            # Fibonacci
            "fib_618"          : {"points": 2, "desc": "Fibonacci 0.618 confluence"},
            "fib_50"           : {"points": 1, "desc": "Fibonacci 0.500 confluence"},

            # Filter
            "killzone_ok"      : {"points": 1, "desc": "Dalam Killzone session"},
            "news_clear"       : {"points": 1, "desc": "Tidak ada high-impact news"},
        }

        self.max_score = sum(
            v["points"] for v in self.score_definitions.values()
        )

    # ─── CALCULATE SCORE ────────────────────

    def calculate(self,
                  direction       : str,
                  indicators      : dict,
                  smc_analysis    : dict,
                  fib_analysis    : dict,
                  session_info    : dict,
                  news_status     : dict,
                  breakout_info   : dict = None,
                  pullback_info   : dict = None) -> dict:
        """
        Hitung confluence score berdasarkan
        semua kondisi yang terpenuhi
        """
        try:
            score     = 0
            breakdown = {}
            reasons   = []

            if breakout_info is None:
                breakout_info = {}
            if pullback_info is None:
                pullback_info = {}

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

            # 2. Stochastic (5,3,3) — 2 poin
            #    2 poin: crossover DI zone oversold/overbought
            #    1 poin: soft crossover (< 50 untuk buy, > 50 untuk sell)
            #    0 poin: tidak ada sinyal
            stoch_k    = indicators.get("stoch_k", 50)
            stoch_d    = indicators.get("stoch_d", 50)
            stoch_bull = indicators.get("stoch_bullish",  False)
            stoch_bear = indicators.get("stoch_bearish",  False)
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
                pts = self.score_definitions["stoch_ok"]["points"]  # 2
                score += pts
                breakdown["stoch_ok"] = pts
                zone = "oversold" if direction == "BUY" else "overbought"
                reasons.append(
                    f"✅ Stoch crossover di {zone} zone "
                    f"(%K={stoch_k:.1f} %D={stoch_d:.1f})"
                )
            elif stoch_soft:
                pts = 1  # partial point untuk soft signal
                score += pts
                breakdown["stoch_ok"] = pts
                reasons.append(
                    f"⚠️ Stoch soft signal "
                    f"(%K={stoch_k:.1f} %D={stoch_d:.1f}) "
                    f"— 1 poin"
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
                reasons.append(
                    f"❌ Volume {vol_ratio:.1f}x lemah"
                )

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
                    f"✅ Candle pattern: {', '.join(patterns)}"
                )
            else:
                breakdown["candle_ok"] = 0
                reasons.append("❌ Tidak ada candle pattern")

            # ══════════════════════════════════
            # BREAKOUT & PULLBACK
            # ══════════════════════════════════

            # 5. Breakout (2 poin)
            #    Breakout valid: harga break level key + volume tinggi
            breakout_valid  = breakout_info.get("valid", False)
            breakout_dir    = breakout_info.get("direction")
            breakout_volume = breakout_info.get("volume_confirmed", False)

            if breakout_valid and breakout_dir == direction and breakout_volume:
                pts = self.score_definitions["breakout_ok"]["points"]
                score += pts
                breakdown["breakout_ok"] = pts
                level = breakout_info.get("level", 0)
                btype = breakout_info.get("type", "")
                reasons.append(
                    f"✅ Breakout {btype} di {level:.2f} "
                    f"dengan konfirmasi volume"
                )
            elif breakout_valid and breakout_dir == direction:
                pts = 1  # breakout tanpa volume = partial
                score += pts
                breakdown["breakout_ok"] = pts
                reasons.append(
                    f"⚠️ Breakout valid tapi volume lemah — 1 poin"
                )
            else:
                breakdown["breakout_ok"] = 0
                reasons.append("❌ Tidak ada breakout valid")

            # 6. Pullback (1 poin)
            #    Harga sudah retrace ke area support/resistance
            #    setelah breakout atau dari swing high/low
            pullback_valid = pullback_info.get("valid", False)
            pullback_dir   = pullback_info.get("direction")
            pullback_depth = pullback_info.get("depth_pct", 0)

            if pullback_valid and pullback_dir == direction:
                pts = self.score_definitions["pullback_ok"]["points"]
                score += pts
                breakdown["pullback_ok"] = pts
                zone = pullback_info.get("zone", "")
                reasons.append(
                    f"✅ Pullback {pullback_depth:.1f}% ke {zone}"
                )
            else:
                breakdown["pullback_ok"] = 0
                reasons.append("❌ Tidak ada pullback ke zona valid")

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
                    f"✅ {liq_type} sudah di-sweep → smart money aktif"
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
                pd_data   = smc_analysis.get("premium_discount", {})
                zone_name = pd_data.get("zone", "")
                reasons.append(
                    f"✅ Harga di {zone_name} Zone → area ideal entry"
                )
            else:
                breakdown["premium_discount"] = 0
                reasons.append(
                    "❌ Harga tidak di area Premium/Discount"
                )

            # ══════════════════════════════════
            # FIBONACCI
            # ══════════════════════════════════

            # 12. Fibonacci 0.618 (2 poin)
            fib_level    = fib_analysis.get("fib_level", "")
            fib_at       = fib_analysis.get("at_fib", False)

            if fib_at and fib_level == "0.618":
                pts = self.score_definitions["fib_618"]["points"]
                score += pts
                breakdown["fib_618"] = pts
                reasons.append(
                    "✅ Fibonacci 0.618 (Golden Ratio) → level terkuat!"
                )
            else:
                breakdown["fib_618"] = 0

            # 13. Fibonacci 0.500 (1 poin)
            if fib_at and fib_level == "0.500":
                pts = self.score_definitions["fib_50"]["points"]
                score += pts
                breakdown["fib_50"] = pts
                reasons.append(
                    "✅ Fibonacci 0.500 → midpoint level penting"
                )
            else:
                breakdown["fib_50"] = 0

            if fib_at and fib_level not in ["0.618", "0.500"]:
                reasons.append(
                    f"⚠️ Fibonacci {fib_level} (level minor, no extra points)"
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
                    f"✅ Dalam {session_name} → volume institusi aktif"
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
            # FINAL SCORE
            # ══════════════════════════════════

            min_score = cfg.MIN_CONFLUENCE_SCORE
            is_valid  = score >= min_score
            grade     = self._get_grade(score)

            result = {
                "score"         : score,
                "max_score"     : self.max_score,
                "min_required"  : min_score,
                "is_valid"      : is_valid,
                "grade"         : grade,
                "direction"     : direction,
                "breakdown"     : breakdown,
                "reasons"       : reasons,
                "stoch_k"       : indicators.get("stoch_k", 0),
                "stoch_d"       : indicators.get("stoch_d", 0),
                "candle_pattern": indicators.get("candle_pattern", []),
                "breakout_mode" : breakout_info.get("valid", False),
                "pullback_mode" : pullback_info.get("valid", False),
            }

            status = "✅ VALID" if is_valid else "❌ INVALID"
            logger.info(
                f"📊 Confluence Score: {score}/{self.max_score} "
                f"({grade}) {status} | {direction}"
            )

            if not is_valid:
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
        score     = result.get("score", 0)
        max_score = result.get("max_score", 16)
        grade     = result.get("grade", "F")
        direction = result.get("direction", "")
        is_valid  = result.get("is_valid", False)
        reasons   = result.get("reasons", [])

        status = "🟢 ENTRY VALID" if is_valid else "🔴 SKIP"

        mode_tags = []
        if result.get("breakout_mode"):
            mode_tags.append("BREAKOUT")
        if result.get("pullback_mode"):
            mode_tags.append("PULLBACK")
        mode_str = " | ".join(mode_tags) if mode_tags else "SMC"

        lines = [
            f"\n{'='*45}",
            f"📊 CONFLUENCE SCORE: {score}/{max_score}",
            f"Grade    : {grade}",
            f"Mode     : {mode_str}",
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