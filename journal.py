# ============================================
# VORTEX BOT - AUTO TRADING JOURNAL
# ============================================

import json
import os
from datetime import datetime
from database import db
from config import cfg
from logger import logger


class TradingJournal:
    def __init__(self):
        # Buat folder journal
        if not os.path.exists("journal"):
            os.makedirs("journal")
        self.journal_path = "journal"

    # ─── AUTO GENERATE ENTRY REASON ─────────

    def generate_entry_reason(self, signal: dict) -> str:
        """Generate alasan entry dalam bahasa natural"""

        pair      = signal.get("pair", "")
        direction = signal.get("direction", "")
        score     = signal.get("confluence_score", 0)
        breakdown = signal.get("score_breakdown", {})
        tf_bias   = signal.get("tf_bias", "4H")
        tf_setup  = signal.get("tf_setup", "1H")
        tf_entry  = signal.get("tf_entry", "15M")
        killzone  = signal.get("killzone", "")
        fib_level = signal.get("fib_level", "")

        # Arah dalam bahasa natural
        dir_text = "BELI (LONG)" if direction == "BUY" else "JUAL (SHORT)"
        bias_text = "uptrend (bullish)" if direction == "BUY" else "downtrend (bearish)"
        opposite = "support" if direction == "BUY" else "resistance"

        # Build alasan entry
        reasons = []
        reasons.append(
            f"🎯 Bot entry {dir_text} {pair} dengan confluence score {score}/16\n"
        )
        reasons.append("📋 ALASAN ENTRY:\n")

        # Trend bias
        if breakdown.get("ema_aligned"):
            reasons.append(
                f"✅ EMA 13 {'di atas' if direction == 'BUY' else 'di bawah'} "
                f"EMA 21 di {tf_entry} → konfirmasi {bias_text}"
            )

        # Market structure
        if breakdown.get("bos_confirmed"):
            reasons.append(
                f"✅ Break of Structure (BOS) terkonfirmasi di {tf_bias} "
                f"→ trend {bias_text} valid"
            )
        if breakdown.get("choch_detected"):
            reasons.append(
                f"✅ Change of Character (CHoCH) terdeteksi "
                f"→ potensi reversal ke {bias_text}"
            )

        # Premium/Discount
        if breakdown.get("premium_discount"):
            zone = "Discount Zone" if direction == "BUY" else "Premium Zone"
            reasons.append(
                f"✅ Harga berada di {zone} "
                f"→ area ideal untuk {dir_text}"
            )

        # Fibonacci
        if fib_level and breakdown.get("fib_confluence"):
            reasons.append(
                f"✅ Harga retrace ke Fibonacci {fib_level} "
                f"→ area {opposite} kuat berdasarkan Golden Ratio"
            )

        # Order Block
        if breakdown.get("ob_valid"):
            reasons.append(
                f"✅ Order Block {'bullish' if direction == 'BUY' else 'bearish'} "
                f"valid di {tf_setup} → area institusi aktif"
            )

        # FVG
        if breakdown.get("fvg_detected"):
            reasons.append(
                f"✅ Fair Value Gap (FVG) terdeteksi "
                f"→ area imbalance yang menjadi magnet harga"
            )

        # Liquidity
        if breakdown.get("liquidity_swept"):
            liq_type = "SSL (Buy Side)" if direction == "BUY" else "BSL (Sell Side)"
            reasons.append(
                f"✅ Liquidity {liq_type} sudah di-sweep "
                f"→ smart money sudah ambil posisi"
            )

        # RSI
        rsi_val = signal.get("rsi_value", 0)
        if breakdown.get("rsi_ok") and rsi_val:
            reasons.append(
                f"✅ RSI {rsi_val:.1f} berada di zona netral "
                f"→ momentum tidak overbought/oversold"
            )

        # MACD
        if breakdown.get("macd_ok"):
            reasons.append(
                f"✅ MACD histogram "
                f"{'positif' if direction == 'BUY' else 'negatif'} "
                f"→ momentum mendukung arah entry"
            )

        # ADX
        adx_val = signal.get("adx_value", 0)
        if breakdown.get("adx_ok") and adx_val:
            reasons.append(
                f"✅ ADX {adx_val:.1f} > 25 "
                f"→ trend kuat, bukan sideways"
            )

        # Volume
        if breakdown.get("volume_ok"):
            reasons.append(
                f"✅ Volume di atas rata-rata "
                f"→ pergerakan harga didukung partisipasi pasar"
            )

        # Candle pattern
        candle = signal.get("candle_pattern", "")
        if breakdown.get("candle_ok") and candle:
            reasons.append(
                f"✅ Pola candle {candle} terkonfirmasi "
                f"→ rejection jelas di area entry"
            )

        # Killzone
        if breakdown.get("killzone_ok") and killzone:
            reasons.append(
                f"✅ Entry dalam {killzone} Killzone "
                f"→ sesi dengan volume institusi tertinggi"
            )

        # News filter
        if breakdown.get("news_clear"):
            reasons.append(
                "✅ Tidak ada high-impact news "
                "→ market bergerak normal"
            )

        # SL/TP info
        entry  = signal.get("entry_price", 0)
        sl     = signal.get("sl_price", 0)
        tp1    = signal.get("tp1_price", 0)
        tp2    = signal.get("tp2_price", 0)
        tp3    = signal.get("tp3_price", 0)
        rr     = signal.get("rr_ratio", 0)

        reasons.append(f"\n📊 DETAIL TRADE:")
        reasons.append(f"Entry  : ${entry:,.4f}")
        reasons.append(f"SL     : ${sl:,.4f} (bawah area liquidity)")
        reasons.append(f"TP1    : ${tp1:,.4f} (Fib 1.272 - partial 50%)")
        reasons.append(f"TP2    : ${tp2:,.4f} (Fib 1.618 - main target)")
        reasons.append(f"TP3    : ${tp3:,.4f} (Fib 2.618 - extended)")
        reasons.append(f"RR Min : 1:{rr:.1f}")

        return "\n".join(reasons)

    # ─── GENERATE CLOSE REASON ──────────────

    def generate_close_reason(self, trade: dict, close_data: dict) -> str:
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

        hours   = duration // 60
        minutes = duration % 60

        reason_map = {
            "TP1"            : f"Target TP1 (Fibonacci 1.272) tercapai → partial close 50%",
            "TP2"            : f"Target TP2 (Fibonacci 1.618) tercapai → main target hit!",
            "TP3"            : f"Target TP3 (Fibonacci 2.618) tercapai → extended profit!",
            "SL"             : f"Stop Loss terkena → SL di bawah area liquidity",
            "TRAILING_STOP"  : f"Trailing Stop aktif → profit dikunci sebelum reversal",
            "MAX_DAILY_LOSS" : f"Max daily loss 5% tercapai → bot berhenti trading hari ini",
            "MANUAL"         : f"Close manual oleh user",
        }

        close_text = reason_map.get(
            close_reason,
            f"Trade closed: {close_reason}"
        )

        lines = [
            f"\n{'='*45}",
            f"📊 TRADE CLOSED — {result}",
            f"{'='*45}",
            f"Pair      : {pair} {direction}",
            f"Entry     : ${entry:,.4f}",
            f"Close     : ${close_price:,.4f}",
            f"PnL       : {'+'if pnl>0 else ''}{pnl:.4f} USDT",
            f"RR        : 1:{rr:.2f}",
            f"Durasi    : {hours}j {minutes}m",
            f"Alasan    : {close_text}",
        ]

        # Learning note
        lines.append(f"\n🧠 CATATAN PEMBELAJARAN:")
        if pnl > 0:
            lines.append(
                f"Setup ini berhasil! Confluence score tinggi "
                f"terbukti menghasilkan trade berkualitas."
            )
            if rr >= 3:
                lines.append(
                    f"RR 1:{rr:.1f} tercapai → strategi Fibonacci "
                    f"extension bekerja dengan baik."
                )
        else:
            lines.append(
                f"Trade ini loss. Evaluasi: apakah semua "
                f"confluence terpenuhi? Cek kondisi market saat entry."
            )
            lines.append(
                f"SL kena bukan berarti strategi salah — "
                f"ini bagian normal dari trading. "
                f"Yang penting RR tetap 1:3 jangka panjang."
            )

        return "\n".join(lines)

    # ─── SAVE TO FILE ───────────────────────

    def save_trade_journal(self, trade_id: int,
                           entry_reason: str,
                           close_reason: str = None):
        """Simpan jurnal trade ke file"""

        month_path = os.path.join(
            self.journal_path,
            datetime.now().strftime("%Y-%m")
        )
        if not os.path.exists(month_path):
            os.makedirs(month_path)

        filename = os.path.join(
            month_path,
            f"trade_{trade_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
        )

        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"VORTEX BOT — TRADING JOURNAL\n")
            f.write(f"{'='*45}\n")
            f.write(f"Trade ID  : {trade_id}\n")
            f.write(f"Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'='*45}\n\n")
            f.write(entry_reason)
            if close_reason:
                f.write(f"\n\n{close_reason}")

        logger.info(f"📔 Journal saved: {filename}")
        return filename

    # ─── MONTHLY REPORT ─────────────────────

    def generate_monthly_report(self) -> str:
        """Generate laporan bulanan otomatis"""

        stats = db.get_overall_stats()
        trades = db.get_trade_history(limit=200)

        # Filter bulan ini
        this_month = datetime.now().strftime("%Y-%m")
        monthly = [
            t for t in trades
            if t.get("open_time", "").startswith(this_month)
        ]

        total  = len(monthly)
        wins   = sum(1 for t in monthly if t.get("pnl", 0) > 0)
        losses = total - wins
        pnl    = sum(t.get("pnl", 0) for t in monthly)
        wr     = (wins / total * 100) if total > 0 else 0

        best  = max((t.get("pnl", 0) for t in monthly), default=0)
        worst = min((t.get("pnl", 0) for t in monthly), default=0)

        lines = [
            f"\n{'='*45}",
            f"📈 VORTEX BOT — LAPORAN BULANAN",
            f"{datetime.now().strftime('%B %Y')}",
            f"{'='*45}",
            f"Total Trade  : {total}",
            f"Win          : {wins}",
            f"Loss         : {losses}",
            f"Winrate      : {wr:.1f}%",
            f"Total PnL    : {'+'if pnl>0 else ''}{pnl:.4f} USDT",
            f"Trade Terbaik: +{best:.4f} USDT",
            f"Trade Terburuk: {worst:.4f} USDT",
            f"{'='*45}",
            f"{'='*45}",
            f"\n📊 STATISTIK KESELURUHAN:",
            f"Total Trade  : {stats.get('total_trades', 0)}",
            f"Win Rate     : {stats.get('winrate', 0):.1f}%",
            f"Total PnL    : {stats.get('total_pnl', 0):.4f} USDT",
            f"Avg RR       : 1:{stats.get('avg_rr', 0):.2f}",
            f"Best Trade   : +{stats.get('best_trade', 0):.4f} USDT",
            f"Worst Trade  : {stats.get('worst_trade', 0):.4f} USDT",
        ]

        report = "\n".join(lines)

        # Simpan ke file
        report_path = os.path.join(
            self.journal_path,
            f"report_{this_month}.txt"
        )
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)

        logger.info(f"📊 Monthly report saved: {report_path}")
        return report


# Instance siap pakai
journal = TradingJournal()