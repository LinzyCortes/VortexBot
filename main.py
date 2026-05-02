# ============================================
# VORTEX BOT v1.0 - MAIN ENGINE
# Institutional Grade Trading Bot
# ============================================

import time
import schedule
from datetime import datetime
from config import cfg
from logger import logger
from database import db
from journal import journal
from filters.news_filter import news_filter, session_filter
from strategy.indicators import indicators
from strategy.smc import smc
from strategy.fibonacci import fibonacci
from strategy.confluence import confluence_scorer
from risk.management import risk_manager
from notification.telegram import telegram
from learning.evaluator import evaluator

# ─── Dynamic Exchange Import ─────────────────
if cfg.IS_OKX:
    from exchange.okx import okx as exchange
    EXCHANGE_NAME = "OKX Demo" if cfg.IS_OKX_DEMO else "OKX Live"
else:
    from exchange.bybit import bybit as exchange
    EXCHANGE_NAME = (
        "Bybit Testnet" if cfg.IS_TESTNET else "Bybit Live"
    )


class VortexBot:

    def __init__(self):
        self.name        = "VΦrtex Bot"
        self.version     = "1.0"
        self.running     = False
        self.start_time  = None
        self.pairs       = cfg.PAIRS
        self.open_trades = {}
        logger.info(
            f"\n{'='*45}\n"
            f"  {self.name} v{self.version}\n"
            f"  Institutional Grade Trading Bot\n"
            f"  SMC + Fibonacci + Multi-Timeframe\n"
            f"  Exchange: {EXCHANGE_NAME}\n"
            f"{'='*45}"
        )

    # ════════════════════════════════════════
    # STARTUP
    # ════════════════════════════════════════

    def startup(self) -> bool:
        """Inisialisasi bot"""
        logger.info(
            f"🚀 Starting VΦrtex Bot on {EXCHANGE_NAME}..."
        )

        # 1. Test koneksi exchange
        if not exchange.is_connected():
            logger.error(
                f"❌ Cannot connect to {EXCHANGE_NAME}!"
            )
            return False
        logger.info(f"✅ {EXCHANGE_NAME} connected!")

        # 2. Ambil balance
        balance_data = exchange.get_balance()
        balance      = balance_data.get("free", 0)

        if balance <= 0:
            logger.warning(
                f"⚠️ Balance 0 di {EXCHANGE_NAME}\n"
                f"Pastikan akun demo sudah ada saldo!"
            )

        # 3. Set starting balances
        risk_manager.set_starting_balance(balance)
        self._set_period_balances(balance)

        # 4. Test Telegram
        tg_ok = telegram.test_connection()
        if not tg_ok:
            logger.warning(
                "⚠️ Telegram not connected — "
                "cek TOKEN & CHAT_ID di .env"
            )

        # 5. Send startup notification
        telegram.send_bot_started(balance)

        # 6. Set running
        self.running    = True
        self.start_time = datetime.now()

        cap_mode = cfg.get_capital_mode(balance)
        logger.info(
            f"✅ VΦrtex Bot started!\n"
            f"   Exchange : {EXCHANGE_NAME}\n"
            f"   Balance  : ${balance:.4f}\n"
            f"   Mode     : {cap_mode['mode']}\n"
            f"   Pairs    : {', '.join(self.pairs)}\n"
            f"   Capital  : ${cfg.CAPITAL}"
        )
        return True

    def _set_period_balances(self, balance: float):
        if not db.get_state("weekly_starting_balance"):
            db.set_state("weekly_starting_balance", {
                "balance": balance,
                "date"   : datetime.now().isoformat(),
            })
        if not db.get_state("monthly_starting_balance"):
            db.set_state("monthly_starting_balance", {
                "balance": balance,
                "date"   : datetime.now().isoformat(),
            })

    # ════════════════════════════════════════
    # MAIN ANALYSIS ENGINE
    # ════════════════════════════════════════

    def analyze_pair(self, pair: str) -> dict:
        """Full analysis untuk 1 pair"""
        try:
            logger.info(f"🔍 Analyzing {pair}...")

            # ── STEP 1: FILTERS ──────────────
            session_info = session_filter.get_session_info()

            if session_info.get("should_avoid"):
                logger.info(
                    f"⏭️ Skip {pair}: "
                    f"{session_info.get('avoid_reason')}"
                )
                return {}

            killzone = session_filter.is_killzone()
            if not killzone.get("in_killzone"):
                next_s = killzone.get("next_session", {})
                logger.info(
                    f"⏭️ {pair}: Outside killzone | "
                    f"Next: {next_s.get('name', 'N/A')} "
                    f"in {next_s.get('minutes_away', '?')} min"
                )
                return {}

            news_status = news_filter.is_safe_to_trade()
            if not news_status.get("is_safe"):
                logger.warning(
                    f"⚠️ Skip {pair}: High impact news!"
                )
                return {}

            # ── STEP 2: FETCH DATA ────────────
            ohlcv_4h  = exchange.get_ohlcv(
                pair, cfg.TF_BIAS,  limit=200
            )
            ohlcv_1h  = exchange.get_ohlcv(
                pair, cfg.TF_SETUP, limit=200
            )
            ohlcv_15m = exchange.get_ohlcv(
                pair, cfg.TF_ENTRY, limit=200
            )
            ohlcv_1d  = exchange.get_ohlcv(
                pair, "1D", limit=200
            )

            if not all([ohlcv_4h, ohlcv_1h, ohlcv_15m]):
                logger.warning(
                    f"⚠️ Incomplete data for {pair}"
                )
                return {}

            df_4h  = indicators.ohlcv_to_df(ohlcv_4h)
            df_1h  = indicators.ohlcv_to_df(ohlcv_1h)
            df_15m = indicators.ohlcv_to_df(ohlcv_15m)
            df_1d  = indicators.ohlcv_to_df(ohlcv_1d) \
                     if ohlcv_1d else df_4h

            if any(df.empty for df in [df_4h, df_1h, df_15m]):
                logger.warning(
                    f"⚠️ Empty DataFrame for {pair}"
                )
                return {}

            # ── STEP 3: INDICATORS ────────────
            ind_15m = indicators.calculate_all(df_15m)
            ind_1h  = indicators.calculate_all(df_1h)

            if not ind_15m or not ind_1h:
                return {}

            # ── STEP 4: SMC ───────────────────
            smc_result = smc.analyze(df_4h, df_1h, df_15m)

            if not smc_result.get("valid"):
                logger.info(
                    f"⏭️ {pair}: SMC invalid — "
                    f"{smc_result.get('reason', 'unclear')}"
                )
                return {}

            direction = smc_result.get("direction")
            if not direction:
                return {}

            # ── STEP 5: FIBONACCI ─────────────
            current_price = df_15m["close"].iloc[-1]
            atr_val       = ind_15m.get("atr", 0)

            liq_1h    = smc_result.get("liquidity_1h", {})
            liq_level = (
                liq_1h.get("nearest_ssl")
                if direction == "BUY"
                else liq_1h.get("nearest_bsl")
            )

            fib_result = fibonacci.analyze(
                df             =df_1h,
                direction      =direction,
                current_price  =current_price,
                atr            =atr_val,
                liquidity_level=liq_level,
            )

            if not fib_result.get("valid"):
                return {}

            # ── STEP 6: CONFLUENCE ────────────
            score_result = confluence_scorer.calculate(
                direction   =direction,
                indicators  =ind_15m,
                smc_analysis=smc_result,
                fib_analysis=fib_result,
                session_info=session_info,
                news_status =news_status,
            )

            score    = score_result.get("score", 0)
            is_valid = score_result.get("is_valid", False)
            grade    = score_result.get("grade", "F")

            logger.info(
                f"📊 {pair}: {score}/16 ({grade}) | "
                f"Valid: {is_valid}"
            )

            if not is_valid:
                return {}

            # ── STEP 7: BUILD SIGNAL ──────────
            tp_sl = fib_result.get("tp_sl", {})
            if not tp_sl:
                return {}

            rr2 = tp_sl.get("rr2", 0)
            if rr2 < cfg.MIN_RR:
                return {}

            signal = {
                "pair"            : pair,
                "direction"       : direction,
                "confluence_score": score,
                "grade"           : grade,
                "entry_price"     : current_price,
                "sl_price"        : tp_sl.get("sl"),
                "tp1_price"       : tp_sl.get("tp1"),
                "tp2_price"       : tp_sl.get("tp2"),
                "tp3_price"       : tp_sl.get("tp3"),
                "rr_ratio"        : rr2,
                "fib_level"       : fib_result.get("fib_level"),
                "fib_strength"    : fib_result.get("fib_strength"),
                "session"         : session_info.get(
                    "session_name", "Unknown"
                ),
                "killzone"        : killzone.get("session", ""),
                "rsi_value"       : ind_15m.get("rsi", 0),
                "adx_value"       : ind_15m.get("adx", 0),
                "atr_value"       : atr_val,
                "macd_histogram"  : ind_15m.get(
                    "macd_histogram", 0
                ),
                "volume_ratio"    : ind_15m.get(
                    "volume_ratio", 0
                ),
                "candle_pattern"  : ind_15m.get(
                    "candle_pattern", []
                ),
                "candle_direction": ind_15m.get(
                    "candle_direction"
                ),
                "structure_4h"    : smc_result.get(
                    "structure_4h"
                ),
                "bos_detected"    : (
                    smc_result.get("bos_4h") or
                    smc_result.get("bos_1h", False)
                ),
                "choch_detected"  : (
                    smc_result.get("choch_4h") or
                    smc_result.get("choch_1h", False)
                ),
                "ob_detected"     : smc_result.get(
                    "in_ob", False
                ),
                "ob_type"         : smc_result.get("ob_type"),
                "fvg_detected"    : smc_result.get(
                    "in_fvg", False
                ),
                "liquidity_swept" : smc_result.get(
                    "liquidity_swept", False
                ),
                "ideal_zone"      : smc_result.get(
                    "ideal_zone", False
                ),
                "score_breakdown" : score_result.get(
                    "breakdown", {}
                ),
                "top_reasons"     : score_result.get(
                    "reasons", []
                )[:8],
                "tf_bias"         : cfg.TF_BIAS,
                "tf_setup"        : cfg.TF_SETUP,
                "tf_entry"        : cfg.TF_ENTRY,
                "detected_at"     : datetime.now().isoformat(),
                "exchange"        : EXCHANGE_NAME,
            }

            db.save_signal(signal)
            telegram.send_signal_detected(signal)

            logger.info(
                f"🎯 VALID SIGNAL!\n"
                f"   {pair} {direction} "
                f"Score:{score}/16 RR:1:{rr2:.1f}"
            )

            return signal

        except Exception as e:
            logger.error(f"❌ Analyze {pair} error: {e}")
            return {}

    # ════════════════════════════════════════
    # TRADE EXECUTION
    # ════════════════════════════════════════

    def execute_trade(self, signal: dict):
        """Eksekusi trade"""
        try:
            pair      = signal.get("pair")
            direction = signal.get("direction")
            entry     = signal.get("entry_price")
            sl        = signal.get("sl_price")
            tp1       = signal.get("tp1_price")
            tp2       = signal.get("tp2_price")
            tp3       = signal.get("tp3_price")

            # ── Risk check ───────────────────
            balance    = exchange.get_balance().get("free", 0)
            risk_check = risk_manager.full_risk_check(balance)

            if not risk_check.get("safe_to_trade"):
                logger.warning(
                    f"⚠️ Risk check failed: "
                    f"{risk_check.get('reason')}"
                )
                return

            # ── Max trades check ─────────────
            cap_mode   = cfg.get_capital_mode(balance)
            max_trades = cap_mode.get("max_open_trades", 1)
            if len(self.open_trades) >= max_trades:
                logger.info(
                    f"⏭️ Max trades ({max_trades}) reached"
                )
                return

            # ── Position sizing ──────────────
            position = risk_manager.calculate_position(
                balance     =balance,
                entry_price =entry,
                sl_price    =sl,
            )
            if not position:
                return

            leverage = position.get("leverage", 1)
            quantity = position.get("quantity", 0)
            mode     = position.get("mode", "MICRO")
            risk_amt = position.get("risk_amount", 0)

            if quantity <= 0:
                logger.warning("⚠️ Quantity = 0 — skip")
                return

            # ── Set leverage ─────────────────
            exchange.set_leverage(pair, leverage)

            # ── Place order ──────────────────
            side  = "buy" if direction == "BUY" else "sell"
            order = exchange.place_market_order(
                pair, side, quantity
            )
            if not order:
                logger.error(f"❌ Order failed: {pair}")
                return

            # ── Place SL & TP ────────────────
            exchange.place_stop_loss(pair, side, quantity, sl)
            tp_qty = round(quantity * 0.4, 6)
            exchange.place_take_profit(pair, side, tp_qty, tp2)

            # ── Save trade ───────────────────
            trade_data = {
                "pair"            : pair,
                "direction"       : direction,
                "entry_price"     : entry,
                "sl_price"        : sl,
                "tp1_price"       : tp1,
                "tp2_price"       : tp2,
                "tp3_price"       : tp3,
                "size"            : quantity,
                "leverage"        : leverage,
                "confluence_score": signal.get(
                    "confluence_score"
                ),
                "mode"            : mode,
                "position_usdt"   : position.get(
                    "position_usdt", 0
                ),
                "risk_amount"     : risk_amt,
            }
            trade_id = db.save_trade(trade_data)

            self.open_trades[trade_id] = {
                **trade_data,
                "trade_id"          : trade_id,
                "open_time"         : datetime.now(),
                "tp1_closed"        : False,
                "quantity_remaining": quantity,
                "original_qty"      : quantity,
            }

            # ── Auto journal + Kirim ke Telegram ──
            entry_reason = journal.generate_entry_reason({
                **signal,
                "entry_price"    : entry,
                "sl_price"       : sl,
                "tp1_price"      : tp1,
                "tp2_price"      : tp2,
                "tp3_price"      : tp3,
                "rr_ratio"       : signal.get("rr_ratio", 3),
                "score_breakdown": signal.get(
                    "score_breakdown", {}
                ),
            })

            # Simpan ke file (kalau bisa)
            journal.save_trade_journal(trade_id, entry_reason)

            # Kirim jurnal entry ke Telegram ← BARU!
            journal.send_entry_journal_to_telegram(
                trade_id, signal, entry_reason
            )

            # Kirim notif trade opened
            telegram.send_trade_opened({
                **trade_data,
                "confluence_score": signal.get(
                    "confluence_score"
                ),
            })

            logger.info(
                f"✅ TRADE EXECUTED #{trade_id}\n"
                f"   {pair} {direction} | "
                f"qty={quantity} lev={leverage}x | "
                f"entry={entry:.4f} sl={sl:.4f}"
            )

        except Exception as e:
            logger.error(f"❌ Execute trade error: {e}")

    # ════════════════════════════════════════
    # TRADE MONITORING
    # ════════════════════════════════════════

    def monitor_trades(self):
        """Monitor open trades"""
        if not self.open_trades:
            return

        try:
            for trade_id, trade in list(
                self.open_trades.items()
            ):
                pair       = trade.get("pair")
                direction  = trade.get("direction")
                entry      = trade.get("entry_price")
                sl         = trade.get("sl_price")
                tp1        = trade.get("tp1_price")
                tp2        = trade.get("tp2_price")
                tp1_closed = trade.get("tp1_closed", False)
                qty        = trade.get("quantity_remaining")

                ticker  = exchange.get_ticker(pair)
                current = ticker.get("last", 0)
                if not current:
                    continue

                ohlcv_15m = exchange.get_ohlcv(
                    pair, cfg.TF_ENTRY, limit=30
                )
                atr = 0
                if ohlcv_15m:
                    df_15m = indicators.ohlcv_to_df(ohlcv_15m)
                    ind    = indicators.calculate_all(df_15m)
                    atr    = ind.get("atr", 0)

                # Partial close
                partial = risk_manager.should_partial_close(
                    entry     =entry,
                    current   =current,
                    tp1       =tp1,
                    tp2       =tp2,
                    direction =direction,
                    closed_tp1=tp1_closed,
                )
                if partial.get("should_close"):
                    self._handle_partial_close(
                        trade_id, trade, current, partial, qty
                    )
                    continue

                # Trailing stop
                if tp1_closed and atr > 0:
                    self._handle_trailing_stop(
                        trade_id, trade, current, atr
                    )

                # SL check
                sl_hit = (
                    (direction == "BUY"  and current <= sl) or
                    (direction == "SELL" and current >= sl)
                )
                if sl_hit:
                    self._close_trade(
                        trade_id, trade, current, "SL"
                    )

        except Exception as e:
            logger.error(f"❌ Monitor trades error: {e}")

    def _handle_partial_close(self, trade_id, trade,
                               current, partial, qty):
        try:
            pair      = trade.get("pair")
            direction = trade.get("direction")
            entry     = trade.get("entry_price")
            tp_hit    = partial.get("tp_hit")
            close_pct = partial.get("close_pct", 30)
            new_sl    = partial.get("new_sl", entry)
            close_qty = round(qty * close_pct / 100, 6)

            pnl = (
                (current - entry) * close_qty
                if direction == "BUY"
                else (entry - current) * close_qty
            )

            exchange.close_position(pair, direction, close_qty)
            exchange.cancel_all_orders(pair)

            remaining = qty - close_qty
            if remaining > 0:
                exchange.place_stop_loss(
                    pair, direction, remaining, new_sl
                )

            self.open_trades[trade_id]["tp1_closed"]         = True
            self.open_trades[trade_id]["quantity_remaining"] = remaining
            self.open_trades[trade_id]["sl_price"]           = new_sl

            telegram.send_partial_close(
                trade, tp_hit, close_pct, pnl
            )
            logger.info(
                f"🎯 Partial close: {pair} {tp_hit} "
                f"pnl=+{pnl:.4f}"
            )
        except Exception as e:
            logger.error(f"❌ Partial close error: {e}")

    def _handle_trailing_stop(self, trade_id, trade,
                               current, atr):
        try:
            direction = trade.get("direction")
            entry     = trade.get("entry_price")
            sl        = trade.get("sl_price")
            qty       = trade.get("quantity_remaining")
            pair      = trade.get("pair")

            trail = risk_manager.calculate_trailing_stop(
                entry=entry, current=current,
                sl=sl, direction=direction, atr=atr,
            )
            if not trail.get("active"):
                return

            new_sl   = trail.get("new_sl")
            old_sl   = trade.get("sl_price")
            improved = (
                (direction == "BUY"  and new_sl > old_sl) or
                (direction == "SELL" and new_sl < old_sl)
            )

            if improved and new_sl != old_sl:
                exchange.cancel_all_orders(pair)
                exchange.place_stop_loss(
                    pair, direction, qty, new_sl
                )
                self.open_trades[trade_id]["sl_price"] = new_sl
                logger.info(
                    f"🔄 Trailing: {pair} SL "
                    f"{old_sl:.4f}→{new_sl:.4f}"
                )
        except Exception as e:
            logger.error(f"❌ Trailing stop error: {e}")

    def _close_trade(self, trade_id, trade,
                     close_price, reason):
        try:
            pair      = trade.get("pair")
            direction = trade.get("direction")
            entry     = trade.get("entry_price")
            qty       = trade.get("quantity_remaining")
            open_time = trade.get("open_time")

            pnl = (
                (close_price - entry) * qty
                if direction == "BUY"
                else (entry - close_price) * qty
            )

            duration = int(
                (datetime.now() - open_time).seconds / 60
            ) if isinstance(open_time, datetime) else 0

            sl    = trade.get("sl_price", entry)
            risk  = abs(entry - sl)
            rr    = (
                abs(close_price - entry) / risk
                if risk > 0 else 0
            )

            exchange.cancel_all_orders(pair)
            if reason not in ["TP2", "TP3"]:
                exchange.close_position(pair, direction, qty)

            new_balance = exchange.get_balance().get("free", 0)

            close_data = {
                "status"          : "CLOSED",
                "pnl"             : pnl,
                "rr_achieved"     : rr,
                "close_reason"    : reason,
                "close_price"     : close_price,
                "duration_minutes": duration,
                "new_balance"     : new_balance,
            }
            db.close_trade(trade_id, close_data)

            # ── Auto journal close + Kirim ke Telegram ──
            close_text = journal.generate_close_reason(
                trade, close_data
            )
            journal.save_trade_journal(
                trade_id,
                "→ See entry journal",
                close_text
            )

            # Kirim close journal ke Telegram ← BARU!
            journal.send_close_journal_to_telegram(
                trade_id, close_text, pnl
            )

            risk_manager.record_trade_result(pnl > 0)
            telegram.send_trade_closed(
                trade,
                {**close_data, "new_balance": new_balance}
            )

            if trade_id in self.open_trades:
                del self.open_trades[trade_id]

            result = "✅ PROFIT" if pnl > 0 else "❌ LOSS"
            logger.info(
                f"{result} #{trade_id} | {pair} {direction} | "
                f"pnl={'+' if pnl > 0 else ''}{pnl:.4f} | "
                f"rr=1:{rr:.2f} | reason={reason}"
            )

        except Exception as e:
            logger.error(f"❌ Close trade error: {e}")

    # ════════════════════════════════════════
    # SCHEDULED TASKS
    # ════════════════════════════════════════

    def setup_scheduled_tasks(self):
        schedule.every().day.at("00:00").do(
            self._morning_briefing
        )
        schedule.every().day.at("15:00").do(
            self._daily_summary
        )
        schedule.every(6).hours.do(self._health_check)
        schedule.every().sunday.at("14:00").do(
            self._weekly_summary
        )
        schedule.every().sunday.at("15:00").do(
            self._run_weekly_evaluation
        )
        schedule.every().day.at("10:00").do(
            self._london_session_summary
        )
        schedule.every().day.at("16:30").do(
            self._ny_session_summary
        )
        schedule.every().monday.at("00:01").do(
            self._reset_weekly_balance
        )
        schedule.every().day.at("00:01").do(
            self._check_monthly_reset
        )
        logger.info("📅 Scheduled tasks configured!")

    def _morning_briefing(self):
        try:
            balance  = exchange.get_balance().get("free", 0)
            upcoming = news_filter.get_upcoming_news(
                hours_ahead=12
            )
            ohlcv_1d = exchange.get_ohlcv(
                self.pairs[0], "1D", limit=200
            )
            df_1d  = indicators.ohlcv_to_df(ohlcv_1d)
            regime = risk_manager.detect_market_regime(
                df_1d
            ).get("regime", "UNKNOWN")
            telegram.send_morning_briefing(
                balance, upcoming, regime
            )
            logger.info("☀️ Morning briefing sent!")
        except Exception as e:
            logger.error(f"❌ Morning briefing error: {e}")

    def _daily_summary(self):
        try:
            trades    = db.get_today_trades()
            balance   = exchange.get_balance().get("free", 0)
            wins      = sum(
                1 for t in trades if t.get("pnl", 0) > 0
            )
            losses    = sum(
                1 for t in trades if t.get("pnl", 0) < 0
            )
            total_pnl = sum(t.get("pnl", 0) for t in trades)
            db.save_daily_summary({
                "total_trades"  : len(trades),
                "win_trades"    : wins,
                "loss_trades"   : losses,
                "total_pnl"     : total_pnl,
                "ending_balance": balance,
            })
            telegram.send_daily_summary({
                "total_trades": len(trades),
                "wins"        : wins,
                "losses"      : losses,
                "total_pnl"   : total_pnl,
                "balance"     : balance,
            })
            journal.generate_monthly_report()
            logger.info("📊 Daily summary sent!")
        except Exception as e:
            logger.error(f"❌ Daily summary error: {e}")

    def _health_check(self):
        try:
            uptime = (
                (datetime.now() - self.start_time).seconds / 3600
                if self.start_time else 0
            )
            balance = exchange.get_balance().get("free", 0)
            telegram.send_health_check(
                uptime, balance, len(self.open_trades)
            )
            logger.info(
                f"💚 Health check: {uptime:.1f}h"
            )
        except Exception as e:
            logger.error(f"❌ Health check error: {e}")

    def _weekly_summary(self):
        try:
            stats            = db.get_overall_stats()
            stats["balance"] = exchange.get_balance().get(
                "free", 0
            )
            telegram.send_weekly_summary(stats)
            logger.info("📈 Weekly summary sent!")
        except Exception as e:
            logger.error(f"❌ Weekly summary error: {e}")

    def _run_weekly_evaluation(self):
        try:
            logger.info("🧠 Running weekly evaluation...")
            report  = evaluator.run_weekly_evaluation()
            summary = "\n".join(report.split("\n")[:25])
            telegram.send(
                f"🧠 <b>WEEKLY EVALUATION</b>\n"
                f"<pre>{summary[:3500]}</pre>"
            )
            logger.info("✅ Weekly evaluation sent!")
        except Exception as e:
            logger.error(f"❌ Weekly eval error: {e}")

    def _london_session_summary(self):
        try:
            trades  = db.get_today_trades()
            summary = evaluator.create_session_summary(
                "London Killzone", trades,
                {"regime": "N/A", "btc_trend": "N/A",
                 "volatility": "N/A"}
            )
            if summary and trades:
                telegram.send(
                    f"📋 <b>LONDON SESSION DONE</b>\n"
                    f"<pre>{summary[:3500]}</pre>"
                )
            logger.info("📋 London summary sent!")
        except Exception as e:
            logger.error(f"❌ London summary error: {e}")

    def _ny_session_summary(self):
        try:
            trades  = db.get_today_trades()
            summary = evaluator.create_session_summary(
                "New York Killzone", trades,
                {"regime": "N/A", "btc_trend": "N/A",
                 "volatility": "N/A"}
            )
            if summary and trades:
                telegram.send(
                    f"📋 <b>NY SESSION DONE</b>\n"
                    f"<pre>{summary[:3500]}</pre>"
                )
            logger.info("📋 NY summary sent!")
        except Exception as e:
            logger.error(f"❌ NY summary error: {e}")

    def _reset_weekly_balance(self):
        try:
            balance = exchange.get_balance().get("free", 0)
            db.set_state("weekly_starting_balance", {
                "balance": balance,
                "date"   : datetime.now().isoformat(),
            })
            logger.info(
                f"📅 Weekly reset: ${balance:.4f}"
            )
        except Exception as e:
            logger.error(f"❌ Weekly reset error: {e}")

    def _check_monthly_reset(self):
        try:
            if datetime.now().day == 1:
                balance = exchange.get_balance().get("free", 0)
                db.set_state("monthly_starting_balance", {
                    "balance": balance,
                    "date"   : datetime.now().isoformat(),
                })
                logger.info(
                    f"📅 Monthly reset: ${balance:.4f}"
                )
        except Exception as e:
            logger.error(f"❌ Monthly reset error: {e}")

    # ════════════════════════════════════════
    # MAIN LOOP
    # ════════════════════════════════════════

    def run(self):
        """Main loop VΦrtex Bot"""
        if not self.startup():
            logger.error("❌ Startup failed!")
            return

        self.setup_scheduled_tasks()

        logger.info(
            f"🔄 Main loop started!\n"
            f"   Exchange : {EXCHANGE_NAME}\n"
            f"   Pairs    : {', '.join(self.pairs)}\n"
            f"   Interval : 60s\n"
            f"   Min score: {cfg.MIN_CONFLUENCE_SCORE}/16"
        )

        while self.running:
            try:
                schedule.run_pending()

                pause = risk_manager.is_bot_paused()
                if pause.get("paused"):
                    logger.info(
                        f"⏸️ Bot paused | "
                        f"{pause.get('reason')} | "
                        f"Resume: {pause.get('time_left')}"
                    )
                    time.sleep(300)
                    continue

                self.monitor_trades()

                signals_found = 0
                for pair in self.pairs:
                    signal = self.analyze_pair(pair)
                    if signal:
                        signals_found += 1
                        self.execute_trade(signal)
                    time.sleep(2)

                wib_h = (datetime.utcnow().hour + 7) % 24
                wib_m = datetime.utcnow().minute
                logger.info(
                    f"✅ Scan done | "
                    f"{wib_h:02d}:{wib_m:02d} WIB | "
                    f"Signals: {signals_found} | "
                    f"Trades: {len(self.open_trades)}"
                )

                time.sleep(60)

            except KeyboardInterrupt:
                logger.info("🛑 Bot stopped (Ctrl+C)")
                self.running = False
                telegram.send_bot_stopped(
                    "Manual stop (Ctrl+C)"
                )
                break

            except Exception as e:
                logger.error(f"❌ Main loop error: {e}")
                time.sleep(30)

        logger.info("👋 VΦrtex Bot shutdown complete!")


# ════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════╗
║         VΦrtex Bot v1.0                  ║
║   Institutional Grade Trading Bot        ║
║   SMC + Fibonacci + Multi-Timeframe      ║
╚══════════════════════════════════════════╝
    """)
    bot = VortexBot()
    bot.run()