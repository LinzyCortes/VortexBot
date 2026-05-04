# ============================================
# VORTEX BOT - TELEGRAM NOTIFICATION SYSTEM
# ============================================

import requests
import threading
from datetime import datetime, timezone, timedelta
from config import cfg
from logger import logger

# ─── WIB Timezone ────────────────────────────────────────────────────────────
WIB = timezone(timedelta(hours=7))

def _wib_now() -> datetime:
    """Waktu sekarang dalam WIB"""
    return datetime.now(WIB)

def _wib_str(fmt: str = "%H:%M:%S WIB") -> str:
    """Timestamp WIB siap pakai untuk notif"""
    return _wib_now().strftime(fmt)


class TelegramNotifier:

    def __init__(self):
        self.token    = cfg.TELEGRAM_TOKEN
        self.chat_id  = cfg.TELEGRAM_CHAT_ID
        self.base_url = (
            f"https://api.telegram.org/bot{self.token}"
        )
        self.enabled      = bool(self.token and self.chat_id)
        self.last_update  = 0
        self.bot_ref      = None
        self._polling     = False

    # ─── SEND ───────────────────────────────

    def send(self, message: str,
             parse_mode: str = "HTML") -> bool:
        """Kirim pesan ke Telegram"""
        if not self.enabled:
            return False
        try:
            if len(message) > 4096:
                message = message[:4090] + "..."

            resp = requests.post(
                f"{self.base_url}/sendMessage",
                data={
                    "chat_id"   : self.chat_id,
                    "text"      : message,
                    "parse_mode": parse_mode,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.debug("📱 Telegram sent ✅")
                return True
            logger.error(
                f"❌ Telegram {resp.status_code}: "
                f"{resp.text[:100]}"
            )
            return False
        except Exception as e:
            logger.error(f"❌ Telegram error: {e}")
            return False

    # ─── COMMAND POLLING ────────────────────

    def start_polling(self, bot_ref=None):
        """Start command listener di background thread"""
        self.bot_ref  = bot_ref
        self._polling = True
        thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="TelegramPoller"
        )
        thread.start()
        logger.info("📱 Telegram command listener started!")

    def stop_polling(self):
        self._polling = False

    def _poll_loop(self):
        while self._polling:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
            except Exception as e:
                logger.debug(f"Poll error: {e}")
            import time
            time.sleep(3)

    def _get_updates(self) -> list:
        try:
            resp = requests.get(
                f"{self.base_url}/getUpdates",
                params={
                    "offset" : self.last_update + 1,
                    "timeout": 2,
                    "limit"  : 10,
                },
                timeout=5,
            )
            if resp.status_code == 200:
                data    = resp.json()
                updates = data.get("result", [])
                if updates:
                    self.last_update = updates[-1]["update_id"]
                return updates
        except Exception:
            pass
        return []

    def _handle_update(self, update: dict):
        try:
            msg  = update.get("message", {})
            text = msg.get("text", "").strip()
            cid  = str(msg.get("chat", {}).get("id", ""))

            if cid != str(self.chat_id):
                return
            if not text.startswith("/"):
                return

            logger.info(f"📱 Command received: {text}")
            response = self._process_command(text)
            if response:
                self.send(response)

        except Exception as e:
            logger.debug(f"Handle update error: {e}")

    def _process_command(self, command: str) -> str:
        cmd = command.lower().split()[0]

        try:
            from database import db
            from risk.management import risk_manager

            if cmd == "/start" or cmd == "/help":
                return (
                    f"🤖 <b>VΦrtex Bot Commands</b>\n"
                    f"{'='*30}\n"
                    f"/status  — Status bot\n"
                    f"/balance — Cek saldo\n"
                    f"/trades  — Open trades\n"
                    f"/stats   — Statistik\n"
                    f"/pause   — Pause bot\n"
                    f"/resume  — Resume bot\n"
                    f"/report  — Laporan hari ini\n"
                    f"/score   — Cek min score\n"
                    f"{'='*30}"
                )

            elif cmd == "/status":
                pause   = risk_manager.is_bot_paused()
                balance = risk_manager.get_virtual_balance() \
                    if (cfg.IS_OKX and cfg.IS_OKX_DEMO) \
                    else 0
                status  = "⛔ PAUSED" if pause["paused"] \
                    else "✅ RUNNING"
                consec  = risk_manager.get_consecutive_losses()
                recover = bool(db.get_state("recovery_mode"))

                return (
                    f"🤖 <b>BOT STATUS</b>\n"
                    f"{'='*30}\n"
                    f"Status     : {status}\n"
                    f"Balance    : ${balance:.4f}\n"
                    f"Mode       : {self._get_mode(balance)}\n"
                    f"Consec Loss: {consec}\n"
                    f"Recovery   : {'ON' if recover else 'OFF'}\n"
                    f"{'='*30}\n"
                    f"⏰ {_wib_str()}"
                )

            elif cmd == "/balance":
                balance = risk_manager.get_virtual_balance() \
                    if (cfg.IS_OKX and cfg.IS_OKX_DEMO) \
                    else 0
                start  = risk_manager.get_starting_balance()
                change = balance - start
                sign   = "+" if change >= 0 else ""

                return (
                    f"💰 <b>BALANCE</b>\n"
                    f"{'='*30}\n"
                    f"Current  : ${balance:.4f}\n"
                    f"Start    : ${start:.4f}\n"
                    f"Change   : {sign}${change:.4f}\n"
                    f"Mode     : {self._get_mode(balance)}\n"
                    f"⏰ {_wib_str()}"
                )

            elif cmd == "/trades":
                open_t = db.get_open_trades()
                if not open_t:
                    return "📊 Tidak ada open trade saat ini."
                text = f"📊 <b>OPEN TRADES ({len(open_t)})</b>\n"
                for t in open_t:
                    text += (
                        f"• #{t['id']} {t['pair']} "
                        f"{t['direction']} "
                        f"@ ${t['entry_price']:.4f}\n"
                    )
                return text

            elif cmd == "/stats":
                stats = db.get_overall_stats()
                return (
                    f"📈 <b>STATISTIK KESELURUHAN</b>\n"
                    f"{'='*30}\n"
                    f"Total Trade : {stats.get('total_trades',0)}\n"
                    f"Win / Loss  : "
                    f"{stats.get('wins',0)} / "
                    f"{stats.get('losses',0)}\n"
                    f"Winrate     : "
                    f"{stats.get('winrate',0):.1f}%\n"
                    f"Total PnL   : "
                    f"${stats.get('total_pnl',0):.4f}\n"
                    f"Avg RR      : "
                    f"1:{stats.get('avg_rr',0):.2f}\n"
                    f"Best Trade  : "
                    f"+${stats.get('best_trade',0):.4f}\n"
                    f"Worst Trade : "
                    f"${stats.get('worst_trade',0):.4f}\n"
                    f"⏰ {_wib_str()}"
                )

            elif cmd == "/pause":
                risk_manager._pause_bot(
                    "Manual pause via Telegram",
                    pause_hours=24
                )
                return (
                    f"⏸️ <b>Bot PAUSED!</b>\n"
                    f"Resume otomatis dalam 24 jam\n"
                    f"Gunakan /resume untuk aktifkan lagi"
                )

            elif cmd == "/resume":
                risk_manager.resume_bot()
                return "▶️ <b>Bot RESUMED!</b>\n🤖 Bot kembali aktif!"

            elif cmd == "/report":
                trades    = db.get_today_trades()
                balance   = risk_manager.get_virtual_balance()
                wins      = sum(
                    1 for t in trades if t.get("pnl", 0) > 0
                )
                losses    = len(trades) - wins
                total_pnl = sum(
                    t.get("pnl", 0) for t in trades
                )
                wr = wins / len(trades) * 100 if trades else 0

                return (
                    f"📊 <b>LAPORAN HARI INI</b>\n"
                    f"{_wib_str('%d %B %Y')}\n"
                    f"{'='*30}\n"
                    f"Total Trade : {len(trades)}\n"
                    f"Win / Loss  : {wins} / {losses}\n"
                    f"Winrate     : {wr:.1f}%\n"
                    f"Total PnL   : "
                    f"{'+' if total_pnl >= 0 else ''}"
                    f"${total_pnl:.4f}\n"
                    f"Balance     : ${balance:.4f}\n"
                    f"⏰ {_wib_str()}"
                )

            elif cmd == "/score":
                return (
                    f"🎯 <b>CONFLUENCE SCORE</b>\n"
                    f"Min required: "
                    f"{cfg.MIN_CONFLUENCE_SCORE}/16\n"
                    f"Ubah di Railway Variables:\n"
                    f"MIN_CONFLUENCE_SCORE=7"
                )

            else:
                return (
                    f"❓ Command tidak dikenal.\n"
                    f"Ketik /help untuk daftar command."
                )

        except Exception as e:
            logger.error(f"❌ Command error: {e}")
            return f"❌ Error: {str(e)[:100]}"

    # ─── BOT NOTIFICATIONS ──────────────────

    def send_bot_started(self, balance: float):
        if cfg.IS_OKX:
            exc = "OKX Demo" if cfg.IS_OKX_DEMO else "OKX Live"
        else:
            exc = "Bybit Testnet" if cfg.IS_TESTNET \
                else "Bybit Live"

        msg = (
            f"🚀 <b>VΦrtex Bot STARTED!</b>\n"
            f"{'='*35}\n"
            f"💰 Balance   : <b>${balance:.4f}</b>\n"
            f"📊 Mode      : <b>{self._get_mode(balance)}</b>\n"
            f"📈 Exchange  : <b>{exc}</b>\n"
            f"📊 Pairs     : <b>{', '.join(cfg.PAIRS)}</b>\n"
            f"⏰ Killzone  : <b>London & New York</b>\n"
            f"🎯 Min Score : <b>{cfg.MIN_CONFLUENCE_SCORE}/16</b>\n"
            f"📉 Max Risk  : <b>1–1.5% per trade</b>\n"
            f"{'='*35}\n"
            f"🤖 Bot monitoring market...\n"
            f"📱 Ketik /help untuk commands!\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    def send_bot_stopped(self, reason: str = "Manual"):
        msg = (
            f"⛔ <b>VΦrtex Bot STOPPED</b>\n"
            f"Reason : {reason}\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    def send_morning_briefing(self, balance: float,
                               upcoming_news: list,
                               market_regime: str):
        """
        Morning briefing — dikirim jam 07:00 WIB.

        Jadwal pantau harian:
          07:00 WIB  Morning Briefing (ini)
          14:45 WIB  Pre-London Buffer
          15:00 WIB  London Killzone MULAI
          17:30 WIB  London Killzone SELESAI
          20:15 WIB  Pre-NY Buffer
          20:30 WIB  New York Killzone MULAI
          23:00 WIB  New York Killzone SELESAI
          22:00 WIB  Daily Summary
        """
        now = _wib_now()

        news_text = ""
        if upcoming_news:
            news_text = "\n📰 <b>High Impact News Hari Ini:</b>\n"
            for n in upcoming_news[:3]:
                t = n.get("time_wib") or f"{n.get('minutes_away','?')} mnt lagi"
                news_text += f"  • {n['title']} ({t})\n"
        else:
            news_text = "\n✅ Tidak ada high-impact news hari ini\n"

        regime_map = {
            "BULL"           : "📈 Bullish",
            "BEAR"           : "📉 Bearish",
            "RANGING"        : "↔️ Ranging",
            "HIGH_VOLATILITY": "⚡ High Volatility",
            "UNKNOWN"        : "❓ Scanning...",
        }
        regime_text = regime_map.get(market_regime, "❓ Unknown")

        msg = (
            f"☀️ <b>SELAMAT PAGI — VΦrtex Bot</b>\n"
            f"{'='*35}\n"
            f"📅 {now.strftime('%A, %d %B %Y')}\n"
            f"⏰ {now.strftime('%H:%M WIB')}\n"
            f"{'='*35}\n"
            f"💰 Balance    : <b>${balance:.4f}</b>\n"
            f"🌍 Market     : <b>{regime_text}</b>\n"
            f"{news_text}"
            f"{'='*35}\n"
            f"📋 <b>Jadwal Hari Ini:</b>\n"
            f"  🟡 Pre-London  : 14:45 WIB\n"
            f"  🟢 London      : 15:00 – 17:30 WIB\n"
            f"  🟡 Pre-NY      : 20:15 WIB\n"
            f"  🟢 New York    : 20:30 – 23:00 WIB\n"
            f"  📊 Daily Sum   : 22:00 WIB\n"
            f"{'='*35}\n"
            f"🎯 Min Score  : <b>{cfg.MIN_CONFLUENCE_SCORE}/16</b>\n"
            f"🤖 Bot aktif & siap hunting setup!\n"
            f"📱 Ketik /help untuk commands"
        )
        self.send(msg)

    def send_signal_detected(self, signal: dict):
        pair      = signal.get("pair", "")
        direction = signal.get("direction", "")
        score     = signal.get("confluence_score", 0)
        grade     = signal.get("grade", "")
        session   = signal.get("session", "")
        fib       = signal.get("fib_level", "N/A")
        dir_emoji = "🟢 LONG" if direction == "BUY" else "🔴 SHORT"

        reasons      = signal.get("top_reasons", [])
        reasons_text = ""
        for r in reasons[:5]:
            if "✅" in str(r) or "❌" in str(r):
                reasons_text += f"  {r}\n"

        msg = (
            f"🎯 <b>SIGNAL DETECTED!</b>\n"
            f"{'='*35}\n"
            f"📊 {pair} — {dir_emoji}\n"
            f"Score    : <b>{score}/16 ({grade})</b>\n"
            f"Session  : <b>{session}</b>\n"
            f"Fibonacci: <b>{fib}</b>\n"
            f"{'='*35}\n"
            f"{reasons_text}"
            f"⏳ Menunggu konfirmasi entry...\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    def send_trade_opened(self, trade: dict):
        pair     = trade.get("pair", "")
        direction= trade.get("direction", "")
        entry    = trade.get("entry_price", 0)
        sl       = trade.get("sl_price", 0)
        tp1      = trade.get("tp1_price", 0)
        tp2      = trade.get("tp2_price", 0)
        tp3      = trade.get("tp3_price", 0)
        size     = trade.get("position_usdt", 0)
        lev      = trade.get("leverage", 1)
        score    = trade.get("confluence_score", 0)
        risk_amt = trade.get("risk_amount", 0)
        mode     = trade.get("mode", "")

        dir_emoji = "🟢 LONG" if direction == "BUY" else "🔴 SHORT"
        risk = abs(entry - sl)
        rr2  = abs(tp2 - entry) / risk if risk > 0 else 0

        msg = (
            f"✅ <b>TRADE OPENED!</b>\n"
            f"{'='*35}\n"
            f"📊 <b>{pair}</b> — {dir_emoji}\n"
            f"{'='*35}\n"
            f"💵 Entry  : <b>${entry:,.4f}</b>\n"
            f"🛡️ SL    : <b>${sl:,.4f}</b>\n"
            f"🎯 TP1   : <b>${tp1:,.4f}</b> (30%)\n"
            f"🎯 TP2   : <b>${tp2:,.4f}</b> (40%)\n"
            f"🎯 TP3   : <b>${tp3:,.4f}</b> (30%)\n"
            f"{'='*35}\n"
            f"📐 Size  : <b>${size:.4f}</b>\n"
            f"⚙️ Lev   : <b>{lev}x</b>\n"
            f"⚠️ Risk  : <b>${risk_amt:.4f}</b>\n"
            f"📊 RR    : <b>1:{rr2:.1f}</b>\n"
            f"🏆 Score : <b>{score}/16</b>\n"
            f"💼 Mode  : <b>{mode}</b>\n"
            f"{'='*35}\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    def send_trade_closed(self, trade: dict, close_data: dict):
        pair     = trade.get("pair", "")
        direction= trade.get("direction", "")
        entry    = trade.get("entry_price", 0)
        pnl      = close_data.get("pnl", 0)
        rr       = close_data.get("rr_achieved", 0)
        reason   = close_data.get("close_reason", "")
        duration = close_data.get("duration_minutes", 0)
        balance  = close_data.get("new_balance", 0)

        hours  = duration // 60
        mins   = duration % 60
        result = "✅ PROFIT" if pnl > 0 else "❌ LOSS"
        sign   = "+" if pnl > 0 else ""

        reason_map = {
            "TP1"          : "🎯 TP1 (Fib 1.272)",
            "TP2"          : "🎯 TP2 (Fib 1.618)",
            "TP3"          : "🚀 TP3 (Fib 2.618)",
            "SL"           : "🛡️ Stop Loss",
            "TRAILING_STOP": "🔄 Trailing Stop",
            "MANUAL"       : "👤 Manual Close",
        }
        reason_text = reason_map.get(reason, reason)

        msg = (
            f"{result} <b>TRADE CLOSED</b>\n"
            f"{'='*35}\n"
            f"📊 <b>{pair}</b> — {direction}\n"
            f"{'='*35}\n"
            f"💵 Entry   : <b>${entry:,.4f}</b>\n"
            f"📤 Close   : {reason_text}\n"
            f"💰 PnL     : <b>{sign}${pnl:.4f}</b>\n"
            f"📊 RR      : <b>1:{rr:.2f}</b>\n"
            f"⏱️ Durasi : <b>{hours}j {mins}m</b>\n"
            f"{'='*35}\n"
            f"💼 Balance : <b>${balance:.4f}</b>\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    def send_partial_close(self, trade: dict,
                           tp_hit    : str,
                           close_pct : int,
                           pnl_partial: float):
        pair = trade.get("pair", "")
        sign = "+" if pnl_partial >= 0 else ""
        msg  = (
            f"🎯 <b>PARTIAL CLOSE — {tp_hit}</b>\n"
            f"{'='*35}\n"
            f"📊 {pair}\n"
            f"Close  : <b>{close_pct}% posisi</b>\n"
            f"PnL    : <b>{sign}${pnl_partial:.4f}</b>\n"
            f"Action : SL → Breakeven ✅\n"
            f"Sisa   : {100-close_pct}% still running\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    def send_drawdown_alert(self, drawdown_pct: float,
                             limit_pct: float,
                             balance: float,
                             paused: bool = False):
        if paused:
            msg = (
                f"⚠️ <b>BOT PAUSED — DRAWDOWN!</b>\n"
                f"📉 Drawdown: <b>{drawdown_pct:.2f}%</b>\n"
                f"🚫 Limit   : <b>{limit_pct}%</b>\n"
                f"💰 Balance : <b>${balance:.4f}</b>\n"
                f"Resume besok otomatis! 🔄\n"
                f"⏰ {_wib_str()}"
            )
        else:
            msg = (
                f"⚠️ <b>DRAWDOWN WARNING</b>\n"
                f"📉 {drawdown_pct:.2f}% / {limit_pct}%\n"
                f"💰 ${balance:.4f}\n"
                f"⏰ {_wib_str()}"
            )
        self.send(msg)

    def send_consecutive_loss_alert(self, count: int,
                                     paused: bool):
        if paused:
            msg = (
                f"⛔ <b>BOT PAUSED — {count}x LOSS!</b>\n"
                f"❌ Consecutive loss: <b>{count}</b>\n"
                f"⏸️ Pause 24 jam — recovery mode ON\n"
                f"💪 Ini perlindungan modal!\n"
                f"⏰ {_wib_str()}"
            )
        else:
            msg = (
                f"⚠️ <b>LOSS WARNING: {count}x</b>\n"
                f"Pantau bot!\n"
                f"⏰ {_wib_str()}"
            )
        self.send(msg)

    def send_weekly_summary(self, stats: dict):
        total  = stats.get("total_trades", 0)
        wins   = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        wr     = stats.get("winrate", 0)
        pnl    = stats.get("total_pnl", 0)
        best   = stats.get("best_trade", 0)
        worst  = stats.get("worst_trade", 0)
        bal    = stats.get("balance", 0)
        sign   = "+" if pnl >= 0 else ""
        result = "📈 PROFIT WEEK" if pnl >= 0 else "📉 LOSS WEEK"

        msg = (
            f"📊 <b>WEEKLY SUMMARY</b>\n"
            f"{_wib_str('%d %B %Y')}\n"
            f"{'='*35}\n"
            f"{result}\n"
            f"{'='*35}\n"
            f"Total    : <b>{total}</b>\n"
            f"Win/Loss : <b>{wins}/{losses}</b>\n"
            f"Winrate  : <b>{wr:.1f}%</b>\n"
            f"PnL      : <b>{sign}${pnl:.4f}</b>\n"
            f"Best     : <b>+${best:.4f}</b>\n"
            f"Worst    : <b>${worst:.4f}</b>\n"
            f"Balance  : <b>${bal:.4f}</b>\n"
            f"{'='*35}\n"
            f"Trading for living — terus semangat! 💪"
        )
        self.send(msg)

    def send_daily_summary(self, stats: dict):
        """Daily summary — dikirim jam 22:00 WIB"""
        total  = stats.get("total_trades", 0)
        wins   = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        pnl    = stats.get("total_pnl", 0)
        bal    = stats.get("balance", 0)
        wr     = (wins / total * 100) if total > 0 else 0
        sign   = "+" if pnl >= 0 else ""
        emoji  = "✅" if pnl >= 0 else "❌"

        msg = (
            f"{emoji} <b>DAILY SUMMARY</b>\n"
            f"{_wib_str('%A, %d %B %Y')}\n"
            f"{'='*35}\n"
            f"Total   : <b>{total}</b>\n"
            f"Win/Loss: <b>{wins}/{losses}</b>\n"
            f"Winrate : <b>{wr:.1f}%</b>\n"
            f"PnL     : <b>{sign}${pnl:.4f}</b>\n"
            f"Balance : <b>${bal:.4f}</b>\n"
            f"{'='*35}\n"
            f"🌙 Istirahat baik!\n"
            f"Bot tetap jaga market.\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    def send_health_check(self, uptime: float,
                           balance: float,
                           open_trades: int):
        msg = (
            f"💚 <b>BOT HEALTH CHECK</b>\n"
            f"{'='*35}\n"
            f"✅ Status  : <b>Running Normal</b>\n"
            f"⏱️ Uptime : <b>{uptime:.1f} jam</b>\n"
            f"💰 Balance : <b>${balance:.4f}</b>\n"
            f"📊 Open    : <b>{open_trades} trade(s)</b>\n"
            f"{'='*35}\n"
            f"🤖 Semua sistem normal!\n"
            f"📱 /help untuk commands\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    def test_connection(self) -> bool:
        try:
            return self.send(
                f"🔧 <b>VΦrtex Bot — Connected!</b>\n"
                f"✅ Telegram OK\n"
                f"📱 Ketik /help untuk commands\n"
                f"⏰ {_wib_str()}"
            )
        except Exception as e:
            logger.error(f"❌ Test error: {e}")
            return False

    @staticmethod
    def _get_mode(balance: float) -> str:
        if balance <= 5:
            return "MICRO ($1-5)"
        elif balance <= 20:
            return "SMALL ($5-20)"
        elif balance <= 100:
            return "MEDIUM ($20-100)"
        return "STANDARD ($100+)"

    def process_command(self, command: str,
                        bot_data: dict) -> str:
        return self._process_command(command)


# Instance siap pakai
telegram = TelegramNotifier()