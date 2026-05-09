# ============================================
# VORTEX BOT - LEARNING & EVALUATION SYSTEM
# ============================================

import os
import json
from datetime import datetime, timedelta
from database import db
from logger import logger


class BotEvaluator:

    def __init__(self):
        for folder in ["learning", "learning/reports",
                       "learning/summaries"]:
            if not os.path.exists(folder):
                os.makedirs(folder)

        self.learning_doc = "learning/bot_knowledge.json"
        self.knowledge    = self._load_knowledge()

    def _load_knowledge(self) -> dict:
        try:
            if os.path.exists(self.learning_doc):
                with open(self.learning_doc, "r") as f:
                    return json.load(f)
        except:
            pass
        return {
            "version"          : "1.0",
            "created_at"       : datetime.now().isoformat(),
            "last_updated"     : datetime.now().isoformat(),
            "total_evaluations": 0,
            "best_setups"      : [],
            "worst_setups"     : [],
            "golden_rules"     : [],
            "by_pair"          : {},
            "by_session"       : {},
            "loss_patterns"    : {},   # ← NEW: simpan pattern loss
            "evolution_log"    : [],
        }

    def _save_knowledge(self):
        self.knowledge["last_updated"] = (
            datetime.now().isoformat()
        )
        with open(self.learning_doc, "w") as f:
            json.dump(self.knowledge, f,
                      indent=2, ensure_ascii=False)

    # ═══════════════════════════════════════════════════════
    # NEW: LOSS PATTERN ANALYSIS
    # ═══════════════════════════════════════════════════════

    def analyze_loss_pattern(self):
        """
        Analisis pattern dari trade loss terbaru.
        Dipanggil otomatis dari main._close_trade() setiap
        kali trade kena loss.

        Yang dilakukan:
        1. Ambil 20 loss trade terbaru dari DB
        2. Hitung berapa kali SL hit per pair
        3. Hitung rata-rata score saat loss
        4. Simpan insight ke knowledge JSON
        5. Kirim insight ke Telegram kalau ada pattern kuat

        Pattern "kuat" = pair yang sama loss >= 3x
        dalam data terbaru → bot perlu lebih selektif
        atau skip pair itu sementara.
        """
        try:
            losses = db.get_recent_loss_patterns(limit=20)
            if not losses:
                return

            # ── Hitung loss per pair ──────────────────────────────────────────
            pair_loss_count = {}
            pair_avg_score  = {}
            pair_scores     = {}

            for t in losses:
                pair  = t.get("pair", "UNKNOWN")
                score = t.get("confluence_score", 0) or 0

                pair_loss_count[pair] = pair_loss_count.get(pair, 0) + 1
                if pair not in pair_scores:
                    pair_scores[pair] = []
                pair_scores[pair].append(score)

            for pair, scores in pair_scores.items():
                pair_avg_score[pair] = (
                    sum(scores) / len(scores) if scores else 0
                )

            # ── Hitung loss per direction ─────────────────────────────────────
            dir_loss = {"BUY": 0, "SELL": 0}
            for t in losses:
                d = t.get("direction", "")
                if d in dir_loss:
                    dir_loss[d] += 1

            # ── Hitung rata-rata durasi sebelum SL ────────────────────────────
            # (tidak semua record punya field ini, pakai default 0)
            total_score = sum(
                (t.get("confluence_score") or 0) for t in losses
            )
            avg_score = total_score / len(losses) if losses else 0

            # ── Update knowledge ──────────────────────────────────────────────
            self.knowledge["loss_patterns"] = {
                "last_analyzed"  : datetime.now().isoformat(),
                "total_analyzed" : len(losses),
                "by_pair"        : pair_loss_count,
                "avg_score_loss" : round(avg_score, 2),
                "by_direction"   : dir_loss,
                "pair_avg_score" : {
                    k: round(v, 2)
                    for k, v in pair_avg_score.items()
                },
            }
            self.knowledge["total_evaluations"] += 1
            self._save_knowledge()

            # ── Cek pair dengan loss >= 3x → kirim insight ke Telegram ───────
            problem_pairs = {
                pair: count
                for pair, count in pair_loss_count.items()
                if count >= 3
            }

            if problem_pairs:
                self._send_loss_insight(
                    problem_pairs  =problem_pairs,
                    pair_avg_score =pair_avg_score,
                    dir_loss       =dir_loss,
                    avg_score      =avg_score,
                    total          =len(losses),
                )

            logger.info(
                f"🧠 Loss pattern analyzed | "
                f"total={len(losses)} | "
                f"avg_score={avg_score:.1f} | "
                f"problem_pairs={list(problem_pairs.keys())}"
            )

        except Exception as e:
            logger.error(f"❌ analyze_loss_pattern error: {e}")

    def _send_loss_insight(self, problem_pairs: dict,
                           pair_avg_score : dict,
                           dir_loss       : dict,
                           avg_score      : float,
                           total          : int):
        """
        Kirim insight pattern loss ke Telegram.
        Hanya dipanggil kalau ada pair dengan loss >= 3x.
        """
        try:
            from notification.telegram import telegram

            pair_lines = ""
            for pair, count in problem_pairs.items():
                avg_sc = pair_avg_score.get(pair, 0)
                pair_lines += (
                    f"  • {pair}: {count}x loss "
                    f"(avg score: {avg_sc:.1f}/16)\n"
                )

            dominant_dir = (
                "SELL" if dir_loss.get("SELL", 0) >
                dir_loss.get("BUY", 0) else "BUY"
            )

            msg = (
                f"🧠 <b>LEARNING INSIGHT</b>\n"
                f"{'='*35}\n"
                f"📊 Analisis {total} loss terbaru:\n\n"
                f"⚠️ <b>Pair bermasalah:</b>\n"
                f"{pair_lines}\n"
                f"📉 Direction dominan loss: "
                f"<b>{dominant_dir}</b>\n"
                f"🎯 Avg score saat loss: "
                f"<b>{avg_score:.1f}/16</b>\n"
                f"{'='*35}\n"
                f"💡 <b>Insight:</b>\n"
                f"Bot sedang struggle di pair ini.\n"
                f"SL cooldown 2j sudah aktif.\n"
                f"Kalau loss terus, pertimbangkan\n"
                f"naikkan MIN_CONFLUENCE_SCORE.\n"
                f"{'='*35}\n"
                f"⏰ {datetime.now().strftime('%H:%M:%S WIB')}"
            )
            telegram.send(msg)

        except Exception as e:
            logger.error(f"❌ _send_loss_insight error: {e}")

    # ═══════════════════════════════════════════════════════
    # SESSION SUMMARY
    # ═══════════════════════════════════════════════════════

    def create_session_summary(self,
                               session_name: str,
                               trades      : list,
                               market_data : dict) -> str:
        try:
            now    = datetime.now()
            closed = [
                t for t in trades
                if t.get("status") != "OPEN"
            ]
            wins      = sum(1 for t in closed if t.get("pnl", 0) > 0)
            losses    = len(closed) - wins
            total_pnl = sum(t.get("pnl", 0) for t in closed)
            wr        = (
                wins / len(closed) * 100 if closed else 0
            )

            content = (
                f"\n{'='*50}\n"
                f"VORTEX BOT — SESSION SUMMARY\n"
                f"{'='*50}\n"
                f"Sesi      : {session_name}\n"
                f"Tanggal   : "
                f"{now.strftime('%d %B %Y %H:%M WIB')}\n"
                f"{'='*50}\n"
                f"Total Trade : {len(closed)}\n"
                f"Win / Loss  : {wins} / {losses}\n"
                f"Win Rate    : {wr:.1f}%\n"
                f"Total PnL   : "
                f"{'+' if total_pnl > 0 else ''}"
                f"{total_pnl:.4f} USDT\n"
                f"Market      : "
                f"{market_data.get('regime', 'N/A')}\n"
                f"{'='*50}\n"
            )

            folder = "learning/summaries"
            if not os.path.exists(folder):
                os.makedirs(folder)

            filename = (
                f"{folder}/session_"
                f"{now.strftime('%Y%m%d_%H%M')}_"
                f"{session_name.replace(' ', '_')}.txt"
            )
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(f"📋 Session summary: {filename}")
            return content

        except Exception as e:
            logger.error(f"❌ Session summary error: {e}")
            return ""

    # ═══════════════════════════════════════════════════════
    # WEEKLY EVALUATION
    # ═══════════════════════════════════════════════════════

    def run_weekly_evaluation(self) -> str:
        try:
            logger.info("🧠 Running weekly evaluation...")

            all_trades = db.get_trade_history(limit=500)
            week_ago   = datetime.now() - timedelta(days=7)

            weekly = [
                t for t in all_trades
                if t.get("status") != "OPEN"
                and datetime.fromisoformat(
                    t.get("open_time", "2020-01-01")
                ) >= week_ago
            ]

            total  = len(weekly)
            wins   = sum(1 for t in weekly if t.get("pnl", 0) > 0)
            losses = total - wins
            pnl    = sum(t.get("pnl", 0) for t in weekly)
            wr     = wins / total * 100 if total > 0 else 0

            # ── Analisis pair terbaik & terburuk ─────────────────────────────
            pair_stats = {}
            for t in weekly:
                pair = t.get("pair", "UNKNOWN")
                if pair not in pair_stats:
                    pair_stats[pair] = {"wins": 0, "losses": 0, "pnl": 0}
                if t.get("pnl", 0) > 0:
                    pair_stats[pair]["wins"] += 1
                else:
                    pair_stats[pair]["losses"] += 1
                pair_stats[pair]["pnl"] += t.get("pnl", 0)

            best_pair  = max(pair_stats, key=lambda p: pair_stats[p]["pnl"]) \
                if pair_stats else "N/A"
            worst_pair = min(pair_stats, key=lambda p: pair_stats[p]["pnl"]) \
                if pair_stats else "N/A"

            # ── Update knowledge ──────────────────────────────────────────────
            self.knowledge["total_evaluations"] += 1
            self.knowledge["evolution_log"].append({
                "date"           : datetime.now().isoformat(),
                "trades_analyzed": total,
                "winrate"        : round(wr, 1),
                "total_pnl"      : round(pnl, 4),
                "best_pair"      : best_pair,
                "worst_pair"     : worst_pair,
            })
            self.knowledge["evolution_log"] = (
                self.knowledge["evolution_log"][-50:]
            )

            # Update by_pair knowledge
            for pair, stats in pair_stats.items():
                self.knowledge["by_pair"][pair] = {
                    "wins"  : stats["wins"],
                    "losses": stats["losses"],
                    "pnl"   : round(stats["pnl"], 4),
                    "wr"    : round(
                        stats["wins"] /
                        (stats["wins"] + stats["losses"]) * 100
                        if (stats["wins"] + stats["losses"]) > 0
                        else 0, 1
                    ),
                }

            self._save_knowledge()

            pair_section = ""
            for pair, stats in pair_stats.items():
                pair_wr = (
                    stats["wins"] /
                    (stats["wins"] + stats["losses"]) * 100
                    if (stats["wins"] + stats["losses"]) > 0
                    else 0
                )
                sign = "+" if stats["pnl"] >= 0 else ""
                pair_section += (
                    f"  {pair}: "
                    f"W{stats['wins']}/L{stats['losses']} "
                    f"WR:{pair_wr:.0f}% "
                    f"PnL:{sign}{stats['pnl']:.4f}\n"
                )

            report = (
                f"\n{'='*50}\n"
                f"🧠 WEEKLY EVALUATION REPORT\n"
                f"{datetime.now().strftime('%d %B %Y')}\n"
                f"{'='*50}\n"
                f"Total Trade : {total}\n"
                f"Win / Loss  : {wins} / {losses}\n"
                f"Win Rate    : {wr:.1f}%\n"
                f"Total PnL   : "
                f"{'+' if pnl > 0 else ''}{pnl:.4f} USDT\n"
                f"{'='*50}\n"
                f"Per Pair:\n"
                f"{pair_section}"
                f"{'='*50}\n"
                f"Best Pair   : {best_pair}\n"
                f"Worst Pair  : {worst_pair}\n"
                f"{'='*50}\n"
            )

            folder = "learning/reports"
            if not os.path.exists(folder):
                os.makedirs(folder)

            filename = (
                f"{folder}/weekly_"
                f"{datetime.now().strftime('%Y%m%d')}.txt"
            )
            with open(filename, "w", encoding="utf-8") as f:
                f.write(report)

            logger.info("✅ Weekly evaluation done!")
            return report

        except Exception as e:
            logger.error(f"❌ Weekly eval error: {e}")
            return f"Error: {e}"

    # ═══════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════

    def read_all_journals(self) -> dict:
        try:
            journal_dir = "journal"
            if not os.path.exists(journal_dir):
                return {"total_files": 0}

            count = 0
            for month in os.listdir(journal_dir):
                month_path = os.path.join(journal_dir, month)
                if os.path.isdir(month_path):
                    count += len([
                        f for f in os.listdir(month_path)
                        if f.endswith(".txt")
                    ])

            return {
                "total_files": count,
                "knowledge"  : self.knowledge,
            }
        except Exception as e:
            logger.error(f"❌ Read journals error: {e}")
            return {"total_files": 0}

    def get_insights(self) -> str:
        k       = self.knowledge
        lp      = k.get("loss_patterns", {})
        by_pair = lp.get("by_pair", {})

        pair_lines = ""
        for pair, count in by_pair.items():
            pair_lines += f"  {pair}: {count}x loss\n"

        return (
            f"\n🧠 VORTEX BOT INSIGHTS\n"
            f"{'='*35}\n"
            f"Total Evaluasi : {k['total_evaluations']}x\n"
            f"Last Update    : {k['last_updated'][:10]}\n"
            f"Avg Score Loss : "
            f"{lp.get('avg_score_loss', 'N/A')}/16\n"
            f"Loss per Pair  :\n"
            f"{pair_lines if pair_lines else '  Belum ada data'}\n"
            f"{'='*35}\n"
        )


# Instance siap pakai
evaluator = BotEvaluator()