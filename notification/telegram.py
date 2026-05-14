# ============================================
# VORTEX BOT - TELEGRAM NOTIFICATION SYSTEM
# ============================================

import time
import requests
import threading
from datetime import datetime, timezone, timedelta
from config import cfg
from logger import logger

WIB = timezone(timedelta(hours=7))

def _wib_now() -> datetime:
    return datetime.now(WIB)

def _wib_str(fmt: str = "%H:%M:%S WIB") -> str:
    return _wib_now().strftime(fmt)


class TelegramNotifier:

    def __init__(self):
        self.token    = cfg.TELEGRAM_TOKEN
        self.chat_id  = cfg.TELEGRAM_CHAT_ID
        self.base_url = (
            f"https://api.telegram.org/bot{self.token}"
        )
        self.enabled        = bool(self.token and self.chat_id)
        self.last_update    = 0
        self.bot_ref        = None
        self._polling       = False
        self.last_scan_time = None

    # ─── SEND ───────────────────────────────

    def send(self, message: str,
             parse_mode: str = "HTML") -> bool:
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

            if cmd in ("/start", "/help"):
                return (
                    f"🤖 <b>VΦrtex Bot v1.1 Commands</b>\n"
                    f"{'='*32}\n"
                    f"/status   — Status bot\n"
                    f"/balance  — Cek saldo\n"
                    f"/trades   — Open trades\n"
                    f"/stats    — Statistik keseluruhan\n"
                    f"/pause    — Pause bot 24 jam\n"
                    f"/resume   — Resume bot\n"
                    f"/report   — Laporan hari ini\n"
                    f"/score    — Info confluence score\n"
                    f"/strategy — Info strategi aktif\n"
                    f"/session  — Killzone sekarang\n"
                    f"{'='*32}\n"
                    f"⏰ {_wib_str()}"
                )

            elif cmd == "/status":
                pause   = risk_manager.is_bot_paused()
                balance = (
                    risk_manager.get_virtual_balance()
                    if (cfg.IS_OKX and cfg.IS_OKX_DEMO)
                    else 0
                )
                status = "⛔ PAUSED" if pause["paused"] else "✅ RUNNING"
                consec = risk_manager.get_consecutive_losses()
                recover = bool(db.get_state("recovery_mode"))

                if self.last_scan_time:
                    elapsed = time.time() - self.last_scan_time
                    hb_str  = f"{elapsed/60:.1f} menit lalu"
                else:
                    hb_str = "Belum ada scan"

                return (
                    f"🤖 <b>BOT STATUS</b>\n"
                    f"{'='*32}\n"
                    f"Status     : {status}\n"
                    f"Balance    : ${balance:.4f}\n"
                    f"Mode       : {self._get_mode(balance)}\n"
                    f"Consec Loss: {consec}\n"
                    f"Recovery   : {'ON' if recover else 'OFF'}\n"
                    f"Last Scan  : {hb_str}\n"
                    f"{'='*32}\n"
                    f"⏰ {_wib_str()}"
                )

            elif cmd == "/balance":
                balance = (
                    risk_manager.get_virtual_balance()
                    if (cfg.IS_OKX and cfg.IS_OKX_DEMO)
                    else 0
                )
                start  = risk_manager.get_starting_balance()
                change = balance - start
                sign   = "+" if change >= 0 else ""
                pct    = (change / start * 100) if start > 0 else 0
                pct_sign = "+" if pct >= 0 else ""

                return (
                    f"💰 <b>BALANCE</b>\n"
                    f"{'='*32}\n"
                    f"Current : <b>${balance:.4f}</b>\n"
                    f"Start   : ${start:.4f}\n"
                    f"Change  : {sign}${change:.4f} "
                    f"({pct_sign}{pct:.2f}%)\n"
                    f"Mode    : {self._get_mode(balance)}\n"
                    f"{'='*32}\n"
                    f"⏰ {_wib_str()}"
                )

            elif cmd == "/trades":
                open_t = db.get_open_trades()
                if not open_t:
                    return "📊 Tidak ada open trade saat ini."
                text = f"📊 <b>OPEN TRADES ({len(open_t)})</b>\n"
                text += f"{'='*32}\n"
                for t in open_t:
                    entry = t.get("entry_price", 0)
                    sl    = t.get("sl_price", 0)
                    sl_pct = abs(entry - sl) / entry * 100 if entry > 0 else 0
                    text += (
                        f"• #{t['id']} <b>{t['pair']}</b> "
                        f"{t['direction']}\n"
                        f"  Entry: ${entry:.4f} | "
                        f"SL: ${sl:.4f} ({sl_pct:.2f}%)\n"
                    )
                return text

            elif cmd == "/stats":
                stats = db.get_overall_stats()
                return (
                    f"📈 <b>STATISTIK KESELURUHAN</b>\n"
                    f"{'='*32}\n"
                    f"Total Trade : {stats.get('total_trades', 0)}\n"
                    f"Win / Loss  : "
                    f"{stats.get('wins', 0)} / "
                    f"{stats.get('losses', 0)}\n"
                    f"Winrate     : "
                    f"{stats.get('winrate', 0):.1f}%\n"
                    f"Total PnL   : "
                    f"${stats.get('total_pnl', 0):.4f}\n"
                    f"Avg RR      : "
                    f"1:{stats.get('avg_rr', 0):.2f}\n"
                    f"Best Trade  : "
                    f"+${stats.get('best_trade', 0):.4f}\n"
                    f"Worst Trade : "
                    f"${stats.get('worst_trade', 0):.4f}\n"
                    f"{'='*32}\n"
                    f"⏰ {_wib_str()}"
                )

            elif cmd == "/pause":
                risk_manager._pause_bot(
                    "Manual pause via Telegram",
                    pause_hours=24
                )
                return (
                    f"⏸️ <b>Bot PAUSED!</b>\n"
                    f"Resume otomatis dalam 24 jam.\n"
                    f"Gunakan /resume untuk aktifkan lagi.\n"
                    f"⏰ {_wib_str()}"
                )

            elif cmd == "/resume":
                risk_manager.resume_bot()
                return (
                    f"▶️ <b>Bot RESUMED!</b>\n"
                    f"🤖 Bot kembali aktif!\n"
                    f"⏰ {_wib_str()}"
                )

            elif cmd == "/report":
                trades    = db.get_today_trades()
                balance   = risk_manager.get_virtual_balance()
                wins      = sum(
                    1 for t in trades if t.get("pnl", 0) > 0
                )
                losses    = len(trades) - wins
                total_pnl = sum(t.get("pnl", 0) for t in trades)
                wr  = wins / len(trades) * 100 if trades else 0
                sign = "+" if total_pnl >= 0 else ""

                return (
                    f"📊 <b>LAPORAN HARI INI</b>\n"
                    f"{_wib_str('%d %B %Y')}\n"
                    f"{'='*32}\n"
                    f"Total Trade : {len(trades)}\n"
                    f"Win / Loss  : {wins} / {losses}\n"
                    f"Winrate     : {wr:.1f}%\n"
                    f"Total PnL   : {sign}${total_pnl:.4f}\n"
                    f"Balance     : ${balance:.4f}\n"
                    f"{'='*32}\n"
                    f"⏰ {_wib_str()}"
                )

            elif cmd == "/score":
                # FIX: update ke max 23
                min_s  = cfg.MIN_CONFLUENCE_SCORE
                max_s  = 23
                phases = (
                    f"  Demo P1 : 10/{max_s}\n"
                    f"  Demo P2 : 13/{max_s}\n"
                    f"  Live    : 16/{max_s}"
                )
                return (
                    f"🎯 <b>CONFLUENCE SCORE</b>\n"
                    f"{'='*32}\n"
                    f"Min sekarang : <b>{min_s}/{max_s}</b>\n"
                    f"{'='*32}\n"
                    f"<b>Phase guide:</b>\n"
                    f"{phases}\n"
                    f"{'='*32}\n"
                    f"<b>Breakdown 20 poin:</b>\n"
                    f"  EMA align    : 1\n"
                    f"  Stoch(5,3,3) : 2\n"
                    f"  Volume       : 1\n"
                    f"  Candle       : 1\n"
                    f"  Breakout     : 2\n"
                    f"  Pullback     : 1\n"
                    f"  BOS/CHoCH    : 2\n"
                    f"  Order Block  : 2\n"
                    f"  FVG          : 1\n"
                    f"  Liquidity    : 1\n"
                    f"  Premium/Disc : 1\n"
                    f"  Fib 0.618    : 2\n"
                    f"  Fib 0.500    : 1\n"
                    f"  Killzone     : 1\n"
                    f"  News clear   : 1\n"
                    f"{'='*32}\n"
                    f"Ubah di Railway: MIN_CONFLUENCE_SCORE=10"
                )

            elif cmd == "/strategy":
                return (
                    f"📐 <b>STRATEGI AKTIF</b>\n"
                    f"{'='*32}\n"
                    f"<b>Core:</b>\n"
                    f"  • SMC (BOS/CHoCH/OB/FVG)\n"
                    f"  • Fibonacci (0.618 Golden Ratio)\n"
                    f"  • Multi-TF (4H/1H/15M)\n"
                    f"<b>Entry Filter:</b>\n"
                    f"  • Stochastic (5,3,3)\n"
                    f"  • EMA 13/21\n"
                    f"  • Breakout + Retest\n"
                    f"  • Pullback ke OB/FVG/Fib\n"
                    f"<b>Institutional:</b>\n"
                    f"  • VWAP filter\n"
                    f"  • Funding Rate filter\n"
                    f"  • Killzone (London/NY)\n"
                    f"<b>Risk:</b>\n"
                    f"  • SL: 2.0x ATR dynamic\n"
                    f"  • Partial TP (30/40/30%)\n"
                    f"  • Trailing stop after TP1\n"
                    f"  • SL cooldown 2j post-loss\n"
                    f"{'='*32}\n"
                    f"⏰ {_wib_str()}"
                )

            elif cmd == "/session":
                try:
                    from filters.news_filter import session_filter
                    info = session_filter.get_session_info()
                    kz   = "✅ YA" if info.get("in_killzone") else "❌ Tidak"
                    return (
                        f"🕐 <b>SESSION INFO</b>\n"
                        f"{'='*32}\n"
                        f"Waktu    : <b>{info.get('wib_time')}</b>\n"
                        f"Session  : {info.get('active_session')}\n"
                        f"Killzone : {kz}\n"
                        f"{'='*32}\n"
                        f"<b>Jadwal Killzone:</b>\n"
                        f"  London : 15:00–17:30 WIB\n"
                        f"  NY     : 20:30–23:00 WIB\n"
                        f"⏰ {_wib_str()}"
                    )
                except Exception:
                    return "❌ Session info tidak tersedia."

            else:
                return (
                    f"❓ Command tidak dikenal.\n"
                    f"Ketik /help untuk daftar command."
                )

        except Exception as e:
            logger.error(f"❌ Command error: {e}")
            return f"❌ Error: {str(e)[:100]}"

    # ─── HEARTBEAT ──────────────────────────

    def update_last_scan(self):
        self.last_scan_time = time.time()

    def check_heartbeat(self):
        if self.last_scan_time is None:
            return
        elapsed = time.time() - self.last_scan_time
        if elapsed > 300:
            logger.warning(
                f"🚨 Heartbeat missed! "
                f"Last scan {elapsed/60:.1f} menit lalu"
            )
            self.send_heartbeat_alert()
            self.last_scan_time = time.time()

    def send_heartbeat_alert(self):
        msg = (
            f"🚨 <b>HEARTBEAT ALERT!</b>\n"
            f"{'='*32}\n"
            f"⚠️ Bot tidak scan >5 menit!\n"
            f"Cek Railway logs segera!\n"
            f"{'='*32}\n"
            f"📱 /status untuk cek kondisi\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    # ─── BOT LIFECYCLE ──────────────────────

    def send_bot_started(self, balance: float):
        if cfg.IS_OKX:
            exc = "OKX Demo" if cfg.IS_OKX_DEMO else "OKX Live"
        else:
            exc = "Bybit Testnet" if cfg.IS_TESTNET else "Bybit Live"

        vwap_str    = "✅ ON" if cfg.VWAP_ENABLED else "❌ OFF"
        funding_str = "✅ ON" if cfg.FUNDING_RATE_ENABLED else "❌ OFF"

        msg = (
            f"🚀 <b>VΦrtex Bot v1.1 STARTED!</b>\n"
            f"{'='*35}\n"
            f"💰 Balance   : <b>${balance:.4f}</b>\n"
            f"📊 Mode      : <b>{self._get_mode(balance)}</b>\n"
            f"📈 Exchange  : <b>{exc}</b>\n"
            f"📊 Pairs     : <b>{', '.join(cfg.PAIRS)}</b>\n"
            f"{'='*35}\n"
            f"<b>Strategi:</b>\n"
            f"  SMC + Fibonacci + Stoch(5,3,3)\n"
            f"  Breakout/Pullback + ATR 2.0x SL\n"
            f"  VWAP: {vwap_str} | Funding: {funding_str}\n"
            f"{'='*35}\n"
            f"🎯 Min Score : <b>{cfg.MIN_CONFLUENCE_SCORE}/23</b>\n"
            f"⏰ Killzone  : London & New York\n"
            f"{'='*35}\n"
            f"🤖 Bot monitoring market...\n"
            f"📱 /help untuk commands\n"
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

    # ─── NEWS & SESSION NOTIF ───────────────

    def send_news_block(self, pairs: list, news_list: list,
                        safe_resume: str):
        try:
            pairs_str  = " & ".join(pairs) if pairs else "Semua pair"
            news_lines = ""
            for n in news_list:
                title   = n.get("title", "Unknown")
                country = n.get("country", "")
                c_str   = f", {country}" if country else ""
                news_lines += f"  • {title} (High{c_str})\n"

            if not news_lines:
                news_lines = "  • High impact event aktif\n"

            msg = (
                f"⚠️ <b>NEWS BLOCK</b>\n"
                f"{'='*35}\n"
                f"<b>{pairs_str}</b> di-skip\n\n"
                f"📰 <b>News Aktif:</b>\n"
                f"{news_lines}\n"
                f"✅ Aman lagi jam: <b>{safe_resume}</b>\n"
                f"⏰ {_wib_str()}"
            )
            self.send(msg)
        except Exception as e:
            logger.error(f"❌ send_news_block error: {e}")

    def send_killzone_alert(self, event: str, session: str,
                            wib_time: str, minutes_left: int = 0):
        try:
            session_upper = session.upper().replace(" KILLZONE", "")

            if event == "started":
                hours   = minutes_left // 60
                mins    = minutes_left % 60
                dur_str = (
                    f"{hours}j {mins}m" if hours > 0
                    else f"{mins} menit"
                )
                msg = (
                    f"🟢 <b>{session_upper} KILLZONE DIMULAI</b>\n"
                    f"{'='*35}\n"
                    f"Jam    : <b>{wib_time}</b>\n"
                    f"Durasi : ±{dur_str}\n"
                    f"{'='*35}\n"
                    f"🎯 Bot mulai hunting setup...\n"
                    f"⏰ {_wib_str()}"
                )
            elif event == "ended":
                msg = (
                    f"🔴 <b>{session_upper} KILLZONE SELESAI</b>\n"
                    f"{'='*35}\n"
                    f"Jam    : <b>{wib_time}</b>\n"
                    f"{'='*35}\n"
                    f"😴 Bot kembali standby...\n"
                    f"⏰ {_wib_str()}"
                )
            else:
                return

            self.send(msg)
            logger.info(
                f"📱 Killzone notif | "
                f"event={event} session={session} {wib_time}"
            )
        except Exception as e:
            logger.error(f"❌ send_killzone_alert error: {e}")

    # ─── SIGNAL DETECTED ────────────────────

    def send_signal_detected(self, signal: dict):
        """
        Upgrade v1.1:
        - Score tampil /20
        - Tambah Stochastic info
        - Tambah BP mode (Breakout/Pullback)
        - Tambah SL% dan VWAP/Funding info
        """
        pair      = signal.get("pair", "")
        direction = signal.get("direction", "")
        score     = signal.get("confluence_score", 0)
        grade     = signal.get("grade", "")
        session   = signal.get("session", "")
        fib       = signal.get("fib_level", "N/A")
        bp_mode   = signal.get("bp_mode", "NONE")
        sl_pct    = signal.get("sl_pct", 0)
        dir_emoji = "🟢 LONG" if direction == "BUY" else "🔴 SHORT"

        # Stochastic info
        stoch_k    = signal.get("stoch_k", 0)
        stoch_d    = signal.get("stoch_d", 0)
        stoch_zone = signal.get("stoch_zone", "neutral")
        zone_emoji = (
            "📉" if stoch_zone == "oversold" else
            "📈" if stoch_zone == "overbought" else
            "➡️"
        )

        # BP mode display
        bp_map = {
            "BREAKOUT_RETEST": "🚀 Breakout Retest",
            "BREAKOUT_WAIT"  : "⏳ Breakout (wait)",
            "PULLBACK"       : "↩️ Pullback",
            "NONE"           : "—",
        }
        bp_str = bp_map.get(bp_mode, bp_mode)

        # VWAP info
        vwap_side = signal.get("vwap_side", "")
        vwap_str  = ""
        if vwap_side:
            vwap_emoji = "🟢" if vwap_side == "below" else "🔴"
            vwap_str   = (
                f"VWAP     : {vwap_emoji} "
                f"{'Discount' if vwap_side == 'below' else 'Premium'}\n"
            )

        # Funding rate info
        funding_rate = signal.get("funding_rate")
        funding_str  = ""
        if funding_rate is not None:
            f_emoji = "✅" if abs(funding_rate) < 0.03 else "⚠️"
            funding_str = (
                f"Funding  : {f_emoji} {funding_rate:+.4f}%\n"
            )

        # Top reasons (hanya yang ✅)
        reasons      = signal.get("top_reasons", [])
        reasons_text = ""
        ok_reasons   = [r for r in reasons if "✅" in str(r)]
        for r in ok_reasons[:4]:
            reasons_text += f"  {r}\n"

        msg = (
            f"🎯 <b>SIGNAL DETECTED!</b>\n"
            f"{'='*35}\n"
            f"📊 <b>{pair}</b> — {dir_emoji}\n"
            f"{'='*35}\n"
            f"Score    : <b>{score}/20 ({grade})</b>\n"
            f"Session  : <b>{session}</b>\n"
            f"Mode     : <b>{bp_str}</b>\n"
            f"Fib      : <b>{fib}</b>\n"
            f"Stoch    : {zone_emoji} %K={stoch_k:.1f} "
            f"%D={stoch_d:.1f} ({stoch_zone})\n"
            f"{vwap_str}"
            f"{funding_str}"
            f"{'='*35}\n"
            f"<b>✅ Konfirmasi:</b>\n"
            f"{reasons_text}"
            f"{'='*35}\n"
            f"⏳ Menunggu konfirmasi entry...\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    # ─── TRADE OPENED ───────────────────────

    def send_trade_opened(self, trade: dict):
        """
        Upgrade v1.1:
        - Score /20
        - Tampil SL% dari entry
        - Tampil BP mode
        - Tampil sl_type (ATR 2.0x)
        """
        pair      = trade.get("pair", "")
        direction = trade.get("direction", "")
        entry     = trade.get("entry_price", 0)
        sl        = trade.get("sl_price", 0)
        tp1       = trade.get("tp1_price", 0)
        tp2       = trade.get("tp2_price", 0)
        tp3       = trade.get("tp3_price", 0)
        size      = trade.get("position_usdt", 0)
        lev       = trade.get("leverage", 1)
        score     = trade.get("confluence_score", 0)
        risk_amt  = trade.get("risk_amount", 0)
        mode      = trade.get("mode", "")
        bp_mode   = trade.get("bp_mode", "NONE")
        sl_pct    = trade.get("sl_pct", 0)
        sl_type   = trade.get("sl_type", "ATR 2.0x")

        dir_emoji = "🟢 LONG" if direction == "BUY" else "🔴 SHORT"
        risk = abs(entry - sl)
        rr2  = abs(tp2 - entry) / risk if risk > 0 else 0

        bp_map = {
            "BREAKOUT_RETEST": "🚀 Breakout",
            "PULLBACK"       : "↩️ Pullback",
            "NONE"           : "SMC",
        }
        bp_str = bp_map.get(bp_mode, bp_mode)

        msg = (
            f"✅ <b>TRADE OPENED!</b>\n"
            f"{'='*35}\n"
            f"📊 <b>{pair}</b> — {dir_emoji}\n"
            f"Mode     : <b>{bp_str}</b>\n"
            f"{'='*35}\n"
            f"💵 Entry  : <b>${entry:,.4f}</b>\n"
            f"🛡️ SL    : <b>${sl:,.4f}</b> "
            f"(<b>{sl_pct:.2f}%</b> | {sl_type})\n"
            f"🎯 TP1   : <b>${tp1:,.4f}</b> (30%)\n"
            f"🎯 TP2   : <b>${tp2:,.4f}</b> (40%)\n"
            f"🎯 TP3   : <b>${tp3:,.4f}</b> (30%)\n"
            f"{'='*35}\n"
            f"📐 Size  : <b>${size:.4f}</b>\n"
            f"⚙️ Lev   : <b>{lev}x</b>\n"
            f"⚠️ Risk  : <b>${risk_amt:.4f}</b>\n"
            f"📊 RR    : <b>1:{rr2:.1f}</b>\n"
            f"🏆 Score : <b>{score}/20</b>\n"
            f"💼 Mode  : <b>{mode}</b>\n"
            f"{'='*35}\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    # ─── TRADE CLOSED ───────────────────────

    def send_trade_closed(self, trade: dict, close_data: dict):
        pair      = trade.get("pair", "")
        direction = trade.get("direction", "")
        entry     = trade.get("entry_price", 0)
        pnl       = close_data.get("pnl", 0)
        rr        = close_data.get("rr_achieved", 0)
        reason    = close_data.get("close_reason", "")
        duration  = close_data.get("duration_minutes", 0)
        balance   = close_data.get("new_balance", 0)
        score     = trade.get("confluence_score", 0)
        bp_mode   = trade.get("bp_mode", "NONE")

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

        bp_map = {
            "BREAKOUT_RETEST": "🚀 Breakout",
            "PULLBACK"       : "↩️ Pullback",
            "NONE"           : "SMC",
        }
        bp_str = bp_map.get(bp_mode, bp_mode)

        msg = (
            f"{result} <b>TRADE CLOSED</b>\n"
            f"{'='*35}\n"
            f"📊 <b>{pair}</b> — {direction} [{bp_str}]\n"
            f"{'='*35}\n"
            f"💵 Entry   : <b>${entry:,.4f}</b>\n"
            f"📤 Close   : {reason_text}\n"
            f"💰 PnL     : <b>{sign}${pnl:.4f}</b>\n"
            f"📊 RR      : <b>1:{rr:.2f}</b>\n"
            f"⏱️ Durasi : <b>{hours}j {mins}m</b>\n"
            f"🏆 Score  : {score}/20\n"
            f"{'='*35}\n"
            f"💼 Balance : <b>${balance:.4f}</b>\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    # ─── PARTIAL CLOSE ──────────────────────

    def send_partial_close(self, trade: dict, tp_hit: str,
                           close_pct: int, pnl_partial: float):
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

    # ─── VWAP / FUNDING ALERT ───────────────

    def send_vwap_filter_skip(self, pair: str,
                               direction: str,
                               vwap_side: str,
                               price: float,
                               vwap: float):
        """Notif kalau signal di-skip karena VWAP filter"""
        side_str = "di atas" if vwap_side == "above" else "di bawah"
        issue    = (
            "SELL di discount zone"
            if direction == "SELL" and vwap_side == "below"
            else "BUY di premium zone"
        )
        msg = (
            f"⚠️ <b>VWAP FILTER — SKIP</b>\n"
            f"{'='*35}\n"
            f"Pair    : {pair}\n"
            f"Dir     : {direction}\n"
            f"Issue   : {issue}\n"
            f"Price   : ${price:,.4f}\n"
            f"VWAP    : ${vwap:,.4f}\n"
            f"Posisi  : {side_str} VWAP\n"
            f"{'='*35}\n"
            f"Setup valid tapi zona salah.\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    def send_funding_filter_skip(self, pair: str,
                                  direction: str,
                                  funding_rate: float):
        """Notif kalau signal di-skip karena funding rate ekstrem"""
        if funding_rate > 0:
            issue = f"Funding sangat positif ({funding_rate:+.4f}%) — longs overpaying"
        else:
            issue = f"Funding sangat negatif ({funding_rate:+.4f}%) — shorts overpaying"

        msg = (
            f"⚠️ <b>FUNDING RATE FILTER — SKIP</b>\n"
            f"{'='*35}\n"
            f"Pair    : {pair}\n"
            f"Dir     : {direction}\n"
            f"Funding : {funding_rate:+.4f}%\n"
            f"Issue   : {issue}\n"
            f"{'='*35}\n"
            f"Institusi biasanya flush dulu sebelum reversal.\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    # ─── DRAWDOWN & LOSS ALERTS ─────────────

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
                f"Resume besok otomatis!\n"
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

    # ─── SCHEDULED SUMMARIES ────────────────

    def send_morning_briefing(self, balance: float,
                               upcoming_news: list,
                               market_regime: str):
        now = _wib_now()

        news_text = ""
        if upcoming_news:
            news_text = "\n📰 <b>High Impact News:</b>\n"
            for n in upcoming_news[:3]:
                t = (
                    n.get("time_wib") or
                    f"{n.get('minutes_away','?')} mnt lagi"
                )
                news_text += f"  • {n['title']} ({t})\n"
        else:
            news_text = "\n✅ Tidak ada high-impact news\n"

        regime_map = {
            "BULL"           : "📈 Bullish",
            "BEAR"           : "📉 Bearish",
            "RANGING"        : "↔️ Ranging",
            "HIGH_VOLATILITY": "⚡ High Volatility",
            "UNKNOWN"        : "❓ Scanning...",
        }
        regime_text = regime_map.get(market_regime, "❓ Unknown")

        vwap_str    = "✅ ON" if cfg.VWAP_ENABLED else "❌ OFF"
        funding_str = "✅ ON" if cfg.FUNDING_RATE_ENABLED else "❌ OFF"

        msg = (
            f"☀️ <b>SELAMAT PAGI — VΦrtex Bot</b>\n"
            f"{'='*35}\n"
            f"📅 {now.strftime('%A, %d %B %Y')}\n"
            f"⏰ {now.strftime('%H:%M WIB')}\n"
            f"{'='*35}\n"
            f"💰 Balance  : <b>${balance:.4f}</b>\n"
            f"🌍 Market   : <b>{regime_text}</b>\n"
            f"🎯 Min Score: <b>{cfg.MIN_CONFLUENCE_SCORE}/20</b>\n"
            f"VWAP Filter : {vwap_str}\n"
            f"Funding Flt : {funding_str}\n"
            f"{news_text}"
            f"{'='*35}\n"
            f"<b>Killzone Hari Ini:</b>\n"
            f"  🟡 Pre-London : 14:45 WIB\n"
            f"  🟢 London     : 15:00–17:30 WIB\n"
            f"  🟡 Pre-NY     : 20:15 WIB\n"
            f"  🟢 New York   : 20:30–23:00 WIB\n"
            f"{'='*35}\n"
            f"🤖 Bot aktif & siap hunting setup!\n"
            f"📱 /help untuk commands"
        )
        self.send(msg)

    def send_daily_summary(self, stats: dict):
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
            f"🎯 Score   : min {cfg.MIN_CONFLUENCE_SCORE}/23\n"
            f"{'='*35}\n"
            f"🤖 Semua sistem normal!\n"
            f"⏰ {_wib_str()}"
        )
        self.send(msg)

    def test_connection(self) -> bool:
        try:
            return self.send(
                f"🔧 <b>VΦrtex Bot v1.1 — Connected!</b>\n"
                f"✅ Telegram OK\n"
                f"📱 /help untuk commands\n"
                f"⏰ {_wib_str()}"
            )
        except Exception as e:
            logger.error(f"❌ Test error: {e}")
            return False

    # ─── HELPERS ────────────────────────────

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