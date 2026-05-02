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
            "evolution_log"    : [],
        }

    def _save_knowledge(self):
        self.knowledge["last_updated"] = (
            datetime.now().isoformat()
        )
        with open(self.learning_doc, "w") as f:
            json.dump(self.knowledge, f,
                      indent=2, ensure_ascii=False)

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

            # Simpan ke file
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

            # Update knowledge
            self.knowledge["total_evaluations"] += 1
            self.knowledge["evolution_log"].append({
                "date"           : datetime.now().isoformat(),
                "trades_analyzed": total,
            })
            self.knowledge["evolution_log"] = (
                self.knowledge["evolution_log"][-50:]
            )
            self._save_knowledge()

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
            )

            # Simpan report
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
        k = self.knowledge
        return (
            f"\n🧠 VORTEX BOT INSIGHTS\n"
            f"{'='*35}\n"
            f"Total Evaluasi : {k['total_evaluations']}x\n"
            f"Last Update    : {k['last_updated'][:10]}\n"
            f"{'='*35}\n"
        )


# Instance siap pakai
evaluator = BotEvaluator()