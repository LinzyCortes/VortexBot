# ============================================
# VORTEX BOT - TELEGRAM NOTIFICATION SYSTEM
# ============================================

import asyncio
import requests
from datetime import datetime
from config import cfg
from logger import logger


class TelegramNotifier:

    def __init__(self):
        self.token   = cfg.TELEGRAM_TOKEN
        self.chat_id = cfg.TELEGRAM_CHAT_ID
        self.base_url = (
            f"https://api.telegram.org/bot{self.token}"
        )
        self.enabled = bool(self.token and self.chat_id)

    # ─── SEND MESSAGE ───────────────────────

    def send(self, message: str,
             parse_mode: str = "HTML") -> bool:
        """Kirim pesan ke Telegram"""
        if not self.enabled:
            logger.warning("⚠️ Telegram not configured")
            return False

        try:
            url  = f"{self.base_url}/sendMessage"
            data = {
                "chat_id"   : self.chat_id,
                "text"      : message,
                "parse_mode": parse_mode,
            }
            response = requests.post(
                url, data=data, timeout=10
            )

            if response.status_code == 200:
                logger.debug("📱 Telegram sent ✅")
                return True
            else:
                logger.error(
                    f"❌ Telegram error: "
                    f"{response.status_code} "
                    f"{response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"❌ Telegram send error: {e}")
            return False

    # ─── BOT STATUS ─────────────────────────

    def send_bot_started(self, balance: float):
        """Notif saat bot pertama kali jalan"""

        from config import cfg

        if cfg.IS_OKX:
            exchange_name = "OKX Demo" if cfg.IS_OKX_DEMO else "OKX Live"
        else:
            exchange_name = "Bybit Testnet" if cfg.IS_TESTNET else "Bybit Live"

        msg = (
            f"🚀 <b>Vortex Bot STARTED!</b>\n"
            f"{'='*35}\n"
            f"💰 Balance   : <b>${balance:.4f}</b>\n"
            f"📊 Mode      : <b>{self._get_mode(balance)}</b>\n"
            f"📈 Exchange  : <b>{exchange_name}</b>\n"
            f"📊 Pairs     : <b>{', '.join(cfg.PAIRS)}</b>\n"
            f"⏰ Killzone  : <b>London & New York</b>\n"
            f"🎯 Min Score : <b>{cfg.MIN_CONFLUENCE_SCORE}/16 confluence</b>\n"
            f"📉 Max Risk  : <b>1–1.5% per trade</b>\n"
            f"{'='*35}\n"
            f"🤖 Bot is now monitoring the market...\n"
            f"You'll be notified for every signal!"
        )

        self.send(msg)
    
    def send_bot_stopped(self, reason: str = "Manual"):
        """Notif saat bot berhenti"""
        msg = (
            f"⛔ <b>VΦrtex Bot STOPPED</b>\n"
            f"{'='*35}\n"
            f"Reason: {reason}\n"
            f"Time  : {datetime.now().strftime('%H:%M:%S WIB')}"
        )
        self.send(msg)

    # ─── MORNING BRIEFING ───────────────────

    def send_morning_briefing(self,
                              balance     : float,
                              upcoming_news: list,
                              market_regime: str):
        """Kirim briefing pagi setiap hari"""
        now_wib = (
            datetime.utcnow().hour + 7
        ) % 24

        news_text = ""
        if upcoming_news:
            news_text = "\n📰 <b>High Impact News Hari Ini:</b>\n"
            for n in upcoming_news[:3]:
                news_text += (
                    f"  • {n['title']} "
                    f"({n.get('minutes_away', '?')} mnt lagi)\n"
                )
        else:
            news_text = "\n✅ Tidak ada high-impact news hari ini\n"

        regime_emoji = {
            "BULL"          : "📈 Bullish",
            "BEAR"          : "📉 Bearish",
            "RANGING"       : "↔️ Ranging",
            "HIGH_VOLATILITY": "⚡ High Volatility",
        }.get(market_regime, "❓ Unknown")

        msg = (
            f"☀️ <b>SELAMAT PAGI — VΦrtex Bot</b>\n"
            f"{'='*35}\n"
            f"📅 {datetime.now().strftime('%A, %d %B %Y')}\n"
            f"⏰ {now_wib:02d}:00 WIB\n"
            f"{'='*35}\n"
            f"💰 Balance    : <b>${balance:.4f}</b>\n"
            f"🌍 Market     : <b>{regime_emoji}</b>\n"
            f"{news_text}"
            f"{'='*35}\n"
            f"⏰ Killzone London  : 14:00 WIB\n"
            f"⏰ Killzone New York: 19:30 WIB\n"
            f"🤖 Bot aktif & siap hunting setup!"
        )
        self.send(msg)

    # ─── SIGNAL ALERTS ──────────────────────

    def send_signal_detected(self, signal: dict):
        """Notif saat ada signal terdeteksi"""
        pair      = signal.get("pair", "")
        direction = signal.get("direction", "")
        score     = signal.get("confluence_score", 0)
        grade     = signal.get("grade", "")
        session   = signal.get("session", "")
        fib_level = signal.get("fib_level", "")

        dir_emoji = "🟢 LONG" if direction == "BUY" else "🔴 SHORT"

        # Top reasons
        reasons = signal.get("top_reasons", [])
        reasons_text = ""
        for r in reasons[:5]:
            reasons_text += f"  {r}\n"

        msg = (
            f"🎯 <b>SIGNAL DETECTED!</b>\n"
            f"{'='*35}\n"
            f"📊 Pair      : <b>{pair}</b>\n"
            f"Direction  : <b>{dir_emoji}</b>\n"
            f"Score      : <b>{score}/16 ({grade})</b>\n"
            f"Session    : <b>{session}</b>\n"
            f"Fibonacci  : <b>{fib_level}</b>\n"
            f"{'='*35}\n"
            f"<b>Top Reasons:</b>\n"
            f"{reasons_text}"
            f"{'='*35}\n"
            f"⏳ Menunggu konfirmasi entry..."
        )
        self.send(msg)

    # ─── TRADE NOTIFICATIONS ────────────────

    def send_trade_opened(self, trade: dict):
        """Notif saat trade dibuka"""
        pair      = trade.get("pair", "")
        direction = trade.get("direction", "")
        entry     = trade.get("entry_price", 0)
        sl        = trade.get("sl_price", 0)
        tp1       = trade.get("tp1_price", 0)
        tp2       = trade.get("tp2_price", 0)
        tp3       = trade.get("tp3_price", 0)
        size      = trade.get("position_usdt", 0)
        leverage  = trade.get("leverage", 1)
        score     = trade.get("confluence_score", 0)
        risk_amt  = trade.get("risk_amount", 0)
        mode      = trade.get("mode", "")

        dir_emoji = "🟢 LONG" if direction == "BUY" else "🔴 SHORT"

        # Hitung RR
        risk = abs(entry - sl)
        rr2  = abs(tp2 - entry) / risk if risk > 0 else 0
        rr3  = abs(tp3 - entry) / risk if risk > 0 else 0

        msg = (
            f"✅ <b>TRADE OPENED!</b>\n"
            f"{'='*35}\n"
            f"📊 <b>{pair}</b> — {dir_emoji}\n"
            f"{'='*35}\n"
            f"💵 Entry    : <b>${entry:,.4f}</b>\n"
            f"🛡️ SL       : <b>${sl:,.4f}</b>\n"
            f"🎯 TP1      : <b>${tp1:,.4f}</b> (30%)\n"
            f"🎯 TP2      : <b>${tp2:,.4f}</b> (40%)\n"
            f"🎯 TP3      : <b>${tp3:,.4f}</b> (30%)\n"
            f"{'='*35}\n"
            f"📐 Size     : <b>${size:.4f}</b>\n"
            f"⚙️ Leverage : <b>{leverage}x</b>\n"
            f"⚠️ Risk     : <b>${risk_amt:.4f}</b>\n"
            f"📊 RR       : <b>1:{rr2:.1f} (TP2)</b>\n"
            f"🏆 Score    : <b>{score}/16</b>\n"
            f"💼 Mode     : <b>{mode}</b>\n"
            f"{'='*35}\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S WIB')}\n"
            f"🤖 Bot managing this trade automatically!"
        )
        self.send(msg)

    def send_trade_closed(self, trade: dict,
                          close_data: dict):
        """Notif saat trade ditutup"""
        pair     = trade.get("pair", "")
        direction = trade.get("direction", "")
        entry    = trade.get("entry_price", 0)
        pnl      = close_data.get("pnl", 0)
        rr       = close_data.get("rr_achieved", 0)
        reason   = close_data.get("close_reason", "")
        duration = close_data.get("duration_minutes", 0)
        balance  = close_data.get("new_balance", 0)

        hours = duration // 60
        mins  = duration % 60

        result_emoji = "✅ PROFIT" if pnl > 0 else "❌ LOSS"
        pnl_sign = "+" if pnl > 0 else ""

        reason_map = {
            "TP1"          : "🎯 TP1 Hit (Fibonacci 1.272)",
            "TP2"          : "🎯 TP2 Hit (Fibonacci 1.618)",
            "TP3"          : "🚀 TP3 Hit (Fibonacci 2.618)",
            "SL"           : "🛡️ Stop Loss Hit",
            "TRAILING_STOP": "🔄 Trailing Stop",
            "MANUAL"       : "👤 Manual Close",
        }
        reason_text = reason_map.get(reason, reason)

        msg = (
            f"{result_emoji} <b>TRADE CLOSED</b>\n"
            f"{'='*35}\n"
            f"📊 <b>{pair}</b> — {direction}\n"
            f"{'='*35}\n"
            f"💵 Entry    : <b>${entry:,.4f}</b>\n"
            f"📤 Close    : {reason_text}\n"
            f"💰 PnL      : <b>{pnl_sign}${pnl:.4f}</b>\n"
            f"📊 RR       : <b>1:{rr:.2f}</b>\n"
            f"⏱️ Duration : <b>{hours}j {mins}m</b>\n"
            f"{'='*35}\n"
            f"💼 Balance  : <b>${balance:.4f}</b>\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S WIB')}"
        )
        self.send(msg)

    def send_partial_close(self, trade: dict,
                           tp_hit    : str,
                           close_pct : int,
                           pnl_partial: float):
        """Notif partial close"""
        pair = trade.get("pair", "")
        msg  = (
            f"🎯 <b>PARTIAL CLOSE — {tp_hit}</b>\n"
            f"{'='*35}\n"
            f"📊 {pair}\n"
            f"Close    : <b>{close_pct}% posisi</b>\n"
            f"PnL      : <b>+${pnl_partial:.4f}</b>\n"
            f"Action   : SL moved to breakeven ✅\n"
            f"Sisa     : {100-close_pct}% masih running\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S WIB')}"
        )
        self.send(msg)

    # ─── PRE-KILLZONE ALERT ─────────────────

    def send_pre_killzone_alert(self,
                                session     : str,
                                minutes_away: int,
                                potential_setups: list):
        """Alert 30 menit sebelum killzone"""
        setups_text = ""
        for s in potential_setups[:3]:
            setups_text += (
                f"  • {s.get('pair')} "
                f"{s.get('direction')} "
                f"(Score: {s.get('score')}/16)\n"
            )

        if not setups_text:
            setups_text = "  Scanning...\n"

        msg = (
            f"⏰ <b>KILLZONE ALERT!</b>\n"
            f"{'='*35}\n"
            f"🕐 {session} dalam "
            f"<b>{minutes_away} menit</b>\n"
            f"{'='*35}\n"
            f"<b>Potential Setups:</b>\n"
            f"{setups_text}"
            f"{'='*35}\n"
            f"🤖 Bot siap hunting setup terbaik!"
        )
        self.send(msg)

    # ─── DRAWDOWN ALERTS ────────────────────

    def send_drawdown_alert(self,
                            drawdown_pct: float,
                            limit_pct   : float,
                            balance     : float,
                            paused      : bool = False):
        """Alert saat drawdown mendekati/melewati limit"""
        if paused:
            msg = (
                f"⚠️ <b>BOT PAUSED — DRAWDOWN LIMIT!</b>\n"
                f"{'='*35}\n"
                f"📉 Drawdown  : <b>{drawdown_pct:.2f}%</b>\n"
                f"🚫 Limit     : <b>{limit_pct}%</b>\n"
                f"💰 Balance   : <b>${balance:.4f}</b>\n"
                f"{'='*35}\n"
                f"Bot berhenti trading hari ini.\n"
                f"Resume besok otomatis! 🔄"
            )
        else:
            msg = (
                f"⚠️ <b>DRAWDOWN WARNING!</b>\n"
                f"{'='*35}\n"
                f"📉 Drawdown  : <b>{drawdown_pct:.2f}%</b>\n"
                f"⚠️ Limit     : <b>{limit_pct}%</b>\n"
                f"💰 Balance   : <b>${balance:.4f}</b>\n"
                f"Bot masih aktif — pantau!"
            )
        self.send(msg)

    def send_consecutive_loss_alert(self,
                                    count  : int,
                                    paused : bool):
        """Alert consecutive loss"""
        if paused:
            msg = (
                f"⛔ <b>BOT PAUSED — 3 CONSECUTIVE LOSSES</b>\n"
                f"{'='*35}\n"
                f"❌ Loss berturut-turut: <b>{count}x</b>\n"
                f"⏸️ Bot pause 24 jam\n"
                f"🔄 Recovery mode aktif setelah resume\n"
                f"{'='*35}\n"
                f"Ini bukan kegagalan strategi —\n"
                f"ini adalah perlindungan modal! 💪"
            )
        else:
            msg = (
                f"⚠️ <b>CONSECUTIVE LOSS WARNING</b>\n"
                f"❌ Loss berturut: <b>{count}x</b>\n"
                f"Pantau bot dengan seksama!"
            )
        self.send(msg)

    # ─── WEEKLY SUMMARY ─────────────────────

    def send_weekly_summary(self, stats: dict):
        """Kirim summary mingguan"""
        total  = stats.get("total_trades", 0)
        wins   = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        wr     = stats.get("winrate", 0)
        pnl    = stats.get("total_pnl", 0)
        best   = stats.get("best_trade", 0)
        worst  = stats.get("worst_trade", 0)
        balance= stats.get("balance", 0)

        pnl_sign = "+" if pnl > 0 else ""
        result   = "📈 PROFIT WEEK" if pnl > 0 else "📉 LOSS WEEK"

        msg = (
            f"📊 <b>WEEKLY SUMMARY — VΦrtex Bot</b>\n"
            f"{'='*35}\n"
            f"{result}\n"
            f"{'='*35}\n"
            f"Total Trade  : <b>{total}</b>\n"
            f"✅ Win        : <b>{wins}</b>\n"
            f"❌ Loss       : <b>{losses}</b>\n"
            f"🎯 Winrate    : <b>{wr:.1f}%</b>\n"
            f"{'='*35}\n"
            f"💰 Total PnL  : <b>{pnl_sign}${pnl:.4f}</b>\n"
            f"🏆 Best Trade : <b>+${best:.4f}</b>\n"
            f"💔 Worst Trade: <b>${worst:.4f}</b>\n"
            f"💼 Balance    : <b>${balance:.4f}</b>\n"
            f"{'='*35}\n"
            f"🤖 VΦrtex Bot terus bekerja untukmu!\n"
            f"Trading for living — satu langkah lagi! 💪"
        )
        self.send(msg)

    # ─── DAILY SUMMARY ──────────────────────

    def send_daily_summary(self, stats: dict):
        """Kirim summary harian (malam hari)"""
        total   = stats.get("total_trades", 0)
        wins    = stats.get("wins", 0)
        losses  = stats.get("losses", 0)
        pnl     = stats.get("total_pnl", 0)
        balance = stats.get("balance", 0)
        wr      = (wins/total*100) if total > 0 else 0

        pnl_sign = "+" if pnl > 0 else ""
        emoji    = "✅" if pnl > 0 else "❌"

        msg = (
            f"{emoji} <b>DAILY SUMMARY</b>\n"
            f"{datetime.now().strftime('%d %B %Y')}\n"
            f"{'='*35}\n"
            f"Total Trade : <b>{total}</b>\n"
            f"Win / Loss  : <b>{wins} / {losses}</b>\n"
            f"Winrate     : <b>{wr:.1f}%</b>\n"
            f"PnL Hari Ini: <b>{pnl_sign}${pnl:.4f}</b>\n"
            f"Balance     : <b>${balance:.4f}</b>\n"
            f"{'='*35}\n"
            f"Istirahat yang baik! 🌙\n"
            f"Bot tetap jaga market malam ini."
        )
        self.send(msg)

    # ─── HEALTH CHECK ───────────────────────

    def send_health_check(self, uptime_hours: float,
                          balance: float,
                          open_trades: int):
        """Kirim health check setiap 6 jam"""
        msg = (
            f"💚 <b>BOT HEALTH CHECK</b>\n"
            f"{'='*35}\n"
            f"✅ Status    : <b>Running Normal</b>\n"
            f"⏱️ Uptime   : <b>{uptime_hours:.1f} jam</b>\n"
            f"💰 Balance  : <b>${balance:.4f}</b>\n"
            f"📊 Open     : <b>{open_trades} trade(s)</b>\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S WIB')}\n"
            f"{'='*35}\n"
            f"🤖 Semua sistem berjalan normal!"
        )
        self.send(msg)

    # ─── TELEGRAM COMMANDS ──────────────────

    def process_command(self, command: str,
                        bot_data: dict) -> str:
        """
        Proses command dari user via Telegram.
        Commands: /status /balance /trades
                  /stats /pause /resume
                  /report /risk
        """
        command = command.lower().strip()

        if command == "/status":
            paused  = bot_data.get("paused", False)
            balance = bot_data.get("balance", 0)
            uptime  = bot_data.get("uptime_hours", 0)
            status  = "⛔ PAUSED" if paused else "✅ RUNNING"

            return (
                f"🤖 <b>BOT STATUS</b>\n"
                f"Status  : {status}\n"
                f"Balance : ${balance:.4f}\n"
                f"Uptime  : {uptime:.1f} jam\n"
                f"Mode    : {self._get_mode(balance)}"
            )

        elif command == "/balance":
            balance = bot_data.get("balance", 0)
            start   = bot_data.get("starting_balance", 0)
            change  = balance - start
            change_sign = "+" if change > 0 else ""

            return (
                f"💰 <b>BALANCE</b>\n"
                f"Current : ${balance:.4f}\n"
                f"Start   : ${start:.4f}\n"
                f"Change  : {change_sign}${change:.4f}"
            )

        elif command == "/trades":
            trades = bot_data.get("open_trades", [])
            if not trades:
                return "📊 Tidak ada open trade saat ini."

            text = "📊 <b>OPEN TRADES</b>\n"
            for t in trades:
                text += (
                    f"• {t['pair']} {t['direction']} "
                    f"@ ${t['entry_price']:.4f}\n"
                )
            return text

        elif command == "/stats":
            stats = bot_data.get("stats", {})
            return (
                f"📈 <b>STATISTIK</b>\n"
                f"Total Trade : {stats.get('total_trades', 0)}\n"
                f"Winrate     : {stats.get('winrate', 0):.1f}%\n"
                f"Total PnL   : ${stats.get('total_pnl', 0):.4f}\n"
                f"Avg RR      : 1:{stats.get('avg_rr', 0):.2f}"
            )

        elif command == "/pause":
            return "⏸️ Bot pause command received."

        elif command == "/resume":
            return "▶️ Bot resume command received."

        elif command == "/report":
            return "📊 Generating report..."

        else:
            return (
                f"❓ <b>Available Commands:</b>\n"
                f"/status  — Cek status bot\n"
                f"/balance — Cek saldo\n"
                f"/trades  — Lihat open trades\n"
                f"/stats   — Statistik bot\n"
                f"/pause   — Pause bot\n"
                f"/resume  — Resume bot\n"
                f"/report  — Minta laporan"
            )

    # ─── HELPER ─────────────────────────────

    @staticmethod
    def _get_mode(balance: float) -> str:
        """Get capital mode name"""
        if balance <= 5:
            return "MICRO ($1-5)"
        elif balance <= 20:
            return "SMALL ($5-20)"
        elif balance <= 100:
            return "MEDIUM ($20-100)"
        else:
            return "STANDARD ($100+)"

    def test_connection(self) -> bool:
        """Test koneksi Telegram"""
        try:
            msg = (
                f"🔧 <b>VΦrtex Bot — Connection Test</b>\n"
                f"✅ Telegram terhubung!\n"
                f"⏰ {datetime.now().strftime('%H:%M:%S')}"
            )
            return self.send(msg)
        except Exception as e:
            logger.error(f"❌ Telegram test error: {e}")
            return False


# Instance siap pakai
telegram = TelegramNotifier()