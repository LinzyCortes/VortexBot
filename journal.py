# ============================================
# VORTEX BOT - AUTO TRADING JOURNAL
# ============================================

import os
from datetime import datetime
from config import cfg
from logger import logger


class TradingJournal:
    def __init__(self):
        # Buat folder journal kalau ada
        try:
            if not os.path.exists("journal"):
                os.makedirs("journal")
        except:
            pass

    # ─── AUTO GENERATE ENTRY REASON ─────────

    def generate_entry_reason(self, signal: dict) -> str:
        """Generate alasan entry dalam bahasa natural"""

        pair      = signal.get("pair", "")
        direction = signal.get("direction", "")
        score     = signal.get("confluence_score", 0)
        breakdown = signal.get("score_breakdown", {})
        fib_level = signal.get("fib_level", "")
        killzone  = signal.get("killzone", "")
        session   = signal.get("session", "")

        dir_text  = "BELI (LONG)" if direction == "BUY" else "JUAL (SHORT)"
        bias_text = "uptrend (bullish)" if direction == "BUY" else "downtrend (bearish)"
        opposite  = "support" if direction == "BUY" else "resistance"

        reasons = []
        reasons.append(
            f"🎯 Bot entry {dir_text} {pair}\n"
            f"Confluence Score: {score}/16\n"
        )
        reasons.append("📋 ALASAN ENTRY:\n")

        # EMA
        if breakdown.get("ema_aligned"):
            reasons.append(
                f"✅ EMA 13/21 "
                f"{'di atas' if direction == 'BUY' else 'di bawah'} "
                f"→ konfirmasi {bias_text}"
            )

        # Market structure
        if breakdown.get("bos_confirmed"):
            reasons.append(
                f"✅ Break of Structure (BOS) confirmed "
                f"→ trend {bias_text} valid"
            )
        if breakdown.get("choch_detected"):
            reasons.append(
                f"✅ Change of Character (CHoCH) "
                f"→ potensi reversal"
            )

        # Premium/Discount
        if breakdown.get("premium_discount"):
            zone = (
                "Discount Zone" if direction == "BUY"
                else "Premium Zone"
            )
            reasons.append(
                f"✅ Harga di {zone} → area ideal entry"
            )

        # Fibonacci
        if fib_level and breakdown.get("fib_618"):
            reasons.append(
                f"✅ Fibonacci {fib_level} (Golden Ratio) "
                f"→ {opposite} terkuat"
            )
        elif fib_level and breakdown.get("fib_50"):
            reasons.append(
                f"✅ Fibonacci {fib_level} (Midpoint) "
                f"→ area {opposite} penting"
            )

        # Order Block
        if breakdown.get("ob_valid"):
            ob_type = signal.get("ob_type", "OB")
            reasons.append(
                f"✅ {ob_type} valid "
                f"→ area institusi aktif"
            )

        # FVG
        if breakdown.get("fvg_detected"):
            reasons.append(
                f"✅ Fair Value Gap (FVG) terdeteksi "
                f"→ area imbalance/magnet harga"
            )

        # Liquidity
        if breakdown.get("liquidity_swept"):
            liq = "SSL" if direction == "BUY" else "BSL"
            reasons.append(
                f"✅ {liq} sudah di-sweep "
                f"→ smart money aktif"
            )

        # RSI
        rsi = signal.get("rsi_value", 0)
        if breakdown.get("rsi_ok") and rsi:
            reasons.append(
                f"✅ RSI {rsi:.1f} zona netral "
                f"→ tidak overbought/oversold"
            )

        # MACD
        if breakdown.get("macd_ok"):
            hist = signal.get("macd_histogram", 0)
            reasons.append(
                f"✅ MACD histogram "
                f"{'positif' if hist > 0 else 'negatif'} "
                f"→ momentum mendukung"
            )

        # ADX
        adx = signal.get("adx_value", 0)
        if breakdown.get("adx_ok") and adx:
            reasons.append(
                f"✅ ADX {adx:.1f} > 25 → trend kuat"
            )

        # Volume
        if breakdown.get("volume_ok"):
            vol = signal.get("volume_ratio", 0)
            reasons.append(
                f"✅ Volume {vol:.1f}x rata-rata "
                f"→ partisipasi pasar kuat"
            )

        # Candle
        patterns = signal.get("candle_pattern", [])
        if breakdown.get("candle_ok") and patterns:
            reasons.append(
                f"✅ Pola candle: {', '.join(patterns)} "
                f"→ konfirmasi rejection"
            )

        # Killzone
        if breakdown.get("killzone_ok"):
            reasons.append(
                f"✅ Dalam {session or killzone} Killzone "
                f"→ volume institusi aktif"
            )

        # News
        if breakdown.get("news_clear"):
            reasons.append(
                f"✅ Tidak ada high-impact news"
            )

        # Trade levels
        entry = signal.get("entry_price", 0)
        sl    = signal.get("sl_price", 0)
        tp1   = signal.get("tp1_price", 0)
        tp2   = signal.get("tp2_price", 0)
        tp3   = signal.get("tp3_price", 0)
        rr    = signal.get("rr_ratio", 0)

        reasons.append(f"\n📊 DETAIL TRADE:")
        reasons.append(f"Entry  : ${entry:,.4f}")
        reasons.append(f"SL     : ${sl:,.4f}")
        reasons.append(f"TP1    : ${tp1:,.4f} (30%)")
        reasons.append(f"TP2    : ${tp2:,.4f} (40%)")
        reasons.append(f"TP3    : ${tp3:,.4f} (30%)")
        reasons.append(f"RR Min : 1:{rr:.1f}")

        return "\n".join(reasons)

    # ─── GENERATE CLOSE REASON ──────────────

    def generate_close_reason(self,
                               trade     : dict,
                               close_data: dict) -> str:
        """Generate alasan close trade"""

        pair         = trade.get("pair", "")
        direction    = trade.get("direction", "")
        entry        = trade.get("entry_price", 0)
        close_price  = close_data.get("close_price", 0)
        pnl          = close_data.get("pnl", 0)
        rr           = close_data.get("rr_achieved", 0)
        close_reason = close_data.get("close_reason", "")
        duration     = close_data.get("duration_minutes", 0)

        result = "✅ PROFIT" if pnl > 0 else "❌ LOSS"
        hours  = duration // 60
        mins   = duration % 60

        reason_map = {
            "TP1"          : "🎯 TP1 (Fibonacci 1.272) tercapai → partial close 30%",
            "TP2"          : "🎯 TP2 (Fibonacci 1.618) tercapai → main target hit!",
            "TP3"          : "🚀 TP3 (Fibonacci 2.618) tercapai → extended profit!",
            "SL"           : "🛡️ Stop Loss terkena → SL di bawah area liquidity",
            "TRAILING_STOP": "🔄 Trailing Stop aktif → profit dikunci",
            "MANUAL"       : "👤 Close manual oleh user",
        }
        close_text = reason_map.get(close_reason, close_reason)

        lines = [
            f"\n{'='*40}",
            f"📊 TRADE CLOSED — {result}",
            f"{'='*40}",
            f"Pair      : {pair} {direction}",
            f"Entry     : ${entry:,.4f}",
            f"Close     : ${close_price:,.4f}",
            f"PnL       : {'+' if pnl > 0 else ''}{pnl:.4f} USDT",
            f"RR        : 1:{rr:.2f}",
            f"Durasi    : {hours}j {mins}m",
            f"Alasan    : {close_text}",
            f"\n🧠 EVALUASI:",
        ]

        if pnl > 0:
            lines.append(
                f"Setup berhasil! Score tinggi terbukti menghasilkan "
                f"trade berkualitas."
            )
            if rr >= 3:
                lines.append(
                    f"RR 1:{rr:.1f} tercapai → "
                    f"Fibonacci extension bekerja optimal!"
                )
        else:
            lines.append(
                f"Trade ini loss. Evaluasi: cek apakah semua "
                f"confluence terpenuhi saat entry."
            )
            lines.append(
                f"SL kena = sistem bekerja dengan benar. "
                f"Yang penting RR 1:3 konsisten jangka panjang."
            )

        return "\n".join(lines)

    # ─── SAVE TO FILE (opsional) ─────────────

    def save_trade_journal(self,
                           trade_id    : int,
                           entry_reason: str,
                           close_reason: str = None):
        """Simpan jurnal ke file (jika bisa)"""
        try:
            month_path = os.path.join(
                "journal",
                datetime.now().strftime("%Y-%m")
            )
            os.makedirs(month_path, exist_ok=True)

            filename = os.path.join(
                month_path,
                f"trade_{trade_id}_"
                f"{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
            )

            with open(filename, "w", encoding="utf-8") as f:
                f.write(
                    f"VORTEX BOT — TRADING JOURNAL\n"
                    f"{'='*40}\n"
                    f"Trade ID  : {trade_id}\n"
                    f"Timestamp : "
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"{'='*40}\n\n"
                    f"{entry_reason}"
                )
                if close_reason:
                    f.write(f"\n\n{close_reason}")

            logger.info(f"📔 Journal saved: {filename}")
            return filename

        except Exception as e:
            # Di Railway file system ephemeral
            # tidak masalah kalau gagal save
            logger.debug(f"Journal file skip: {e}")
            return None

    # ─── SEND JOURNAL TO TELEGRAM ───────────

    def send_entry_journal_to_telegram(self,
                                        trade_id    : int,
                                        signal      : dict,
                                        entry_reason: str):
        """Kirim jurnal entry ke Telegram"""
        try:
            # Import di sini untuk hindari circular import
            from notification.telegram import telegram

            pair      = signal.get("pair", "")
            direction = signal.get("direction", "")
            score     = signal.get("confluence_score", 0)
            grade     = signal.get("grade", "")
            dir_emoji = "🟢" if direction == "BUY" else "🔴"

            msg = (
                f"📔 <b>TRADE JOURNAL #{trade_id}</b>\n"
                f"{'='*35}\n"
                f"{dir_emoji} <b>{pair} — {direction}</b>\n"
                f"Score: <b>{score}/16 ({grade})</b>\n"
                f"{'='*35}\n"
                f"<pre>{entry_reason[:3000]}</pre>"
            )
            telegram.send(msg)
            logger.info(
                f"📔 Entry journal sent to Telegram: #{trade_id}"
            )

        except Exception as e:
            logger.error(
                f"❌ Send entry journal error: {e}"
            )

    def send_close_journal_to_telegram(self,
                                        trade_id    : int,
                                        close_reason: str,
                                        pnl         : float):
        """Kirim jurnal close ke Telegram"""
        try:
            from notification.telegram import telegram

            result = "✅ PROFIT" if pnl > 0 else "❌ LOSS"
            msg = (
                f"📔 <b>CLOSE JOURNAL #{trade_id}</b>\n"
                f"{result}\n"
                f"{'='*35}\n"
                f"<pre>{close_reason[:3000]}</pre>"
            )
            telegram.send(msg)
            logger.info(
                f"📔 Close journal sent to Telegram: #{trade_id}"
            )

        except Exception as e:
            logger.error(
                f"❌ Send close journal error: {e}"
            )

    # ─── MONTHLY REPORT ─────────────────────

    def generate_monthly_report(self) -> str:
        """Generate laporan bulanan"""
        try:
            from database import db
            from notification.telegram import telegram

            stats  = db.get_overall_stats()
            trades = db.get_trade_history(limit=200)

            this_month = datetime.now().strftime("%Y-%m")
            monthly = [
                t for t in trades
                if t.get("open_time", "").startswith(this_month)
            ]

            total  = len(monthly)
            wins   = sum(
                1 for t in monthly if t.get("pnl", 0) > 0
            )
            losses = total - wins
            pnl    = sum(t.get("pnl", 0) for t in monthly)
            wr     = (wins / total * 100) if total > 0 else 0
            best   = max(
                (t.get("pnl", 0) for t in monthly), default=0
            )
            worst  = min(
                (t.get("pnl", 0) for t in monthly), default=0
            )

            report = (
                f"\n{'='*40}\n"
                f"📈 VORTEX BOT — LAPORAN BULANAN\n"
                f"{datetime.now().strftime('%B %Y')}\n"
                f"{'='*40}\n"
                f"Total Trade   : {total}\n"
                f"Win / Loss    : {wins} / {losses}\n"
                f"Winrate       : {wr:.1f}%\n"
                f"Total PnL     : "
                f"{'+' if pnl > 0 else ''}{pnl:.4f} USDT\n"
                f"Trade Terbaik : +{best:.4f} USDT\n"
                f"Trade Terburuk: {worst:.4f} USDT\n"
                f"{'='*40}\n"
                f"📊 STATISTIK KESELURUHAN:\n"
                f"Total Trade   : {stats.get('total_trades', 0)}\n"
                f"Win Rate      : {stats.get('winrate', 0):.1f}%\n"
                f"Total PnL     : "
                f"{stats.get('total_pnl', 0):.4f} USDT\n"
                f"Avg RR        : "
                f"1:{stats.get('avg_rr', 0):.2f}\n"
            )

            # Kirim ke Telegram
            telegram.send(
                f"📊 <b>MONTHLY REPORT</b>\n"
                f"<pre>{report[:3500]}</pre>"
            )

            logger.info("📊 Monthly report sent!")
            return report

        except Exception as e:
            logger.error(f"❌ Monthly report error: {e}")
            return ""


# Instance siap pakai
journal = TradingJournal()