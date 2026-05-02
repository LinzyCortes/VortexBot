# ============================================
# VORTEX BOT - RISK MANAGEMENT SYSTEM
# ============================================

import json
from datetime import datetime, timedelta
from config import cfg
from database import db
from logger import logger


class RiskManager:

    def __init__(self):
        self.daily_loss_key    = "daily_loss"
        self.weekly_loss_key   = "weekly_loss"
        self.monthly_loss_key  = "monthly_loss"
        self.consec_loss_key   = "consecutive_losses"
        self.bot_paused_key    = "bot_paused"
        self.recovery_mode_key = "recovery_mode"
        self.starting_bal_key  = "starting_balance"

    # ─── BALANCE TRACKING ───────────────────

    def set_starting_balance(self, balance: float):
        """Simpan balance awal hari ini"""
        today = datetime.now().strftime("%Y-%m-%d")
        stored = db.get_state(self.starting_bal_key)

        if not stored or stored.get("date") != today:
            db.set_state(self.starting_bal_key, {
                "date"   : today,
                "balance": balance,
            })
            logger.info(
                f"💰 Starting balance set: ${balance:.4f}"
            )

    def get_starting_balance(self) -> float:
        """Ambil balance awal hari ini"""
        stored = db.get_state(self.starting_bal_key)
        if stored:
            return stored.get("balance", 0)
        return 0

    # ─── DRAWDOWN CHECKS ────────────────────

    def check_daily_drawdown(self,
                             current_balance: float) -> dict:
        """Cek daily drawdown limit (5%)"""
        starting = self.get_starting_balance()
        if starting <= 0:
            return {"exceeded": False, "drawdown_pct": 0}

        drawdown_pct = (
            (starting - current_balance) / starting * 100
        )
        exceeded = drawdown_pct >= cfg.MAX_DAILY_LOSS_PCT

        if exceeded:
            logger.warning(
                f"⚠️ DAILY DRAWDOWN EXCEEDED: "
                f"{drawdown_pct:.2f}% >= {cfg.MAX_DAILY_LOSS_PCT}%"
            )
            self._pause_bot("Daily drawdown limit reached")

        return {
            "exceeded"    : exceeded,
            "drawdown_pct": drawdown_pct,
            "limit_pct"   : cfg.MAX_DAILY_LOSS_PCT,
            "starting_bal": starting,
            "current_bal" : current_balance,
        }

    def check_weekly_drawdown(self,
                              current_balance: float) -> dict:
        """Cek weekly drawdown limit (10%)"""
        weekly_start = db.get_state("weekly_starting_balance")
        if not weekly_start:
            return {"exceeded": False, "drawdown_pct": 0}

        start_bal = weekly_start.get("balance", current_balance)
        drawdown_pct = (
            (start_bal - current_balance) / start_bal * 100
        )
        exceeded = drawdown_pct >= 10.0

        if exceeded:
            logger.warning(
                f"⚠️ WEEKLY DRAWDOWN EXCEEDED: {drawdown_pct:.2f}%"
            )
            self._pause_bot(
                "Weekly drawdown limit (10%) reached",
                pause_hours=168  # 1 minggu
            )

        return {
            "exceeded"    : exceeded,
            "drawdown_pct": drawdown_pct,
            "limit_pct"   : 10.0,
        }

    def check_monthly_drawdown(self,
                               current_balance: float) -> dict:
        """Cek monthly drawdown limit (15%)"""
        monthly_start = db.get_state("monthly_starting_balance")
        if not monthly_start:
            return {"exceeded": False, "drawdown_pct": 0}

        start_bal    = monthly_start.get("balance", current_balance)
        drawdown_pct = (
            (start_bal - current_balance) / start_bal * 100
        )
        exceeded = drawdown_pct >= 15.0

        if exceeded:
            logger.warning(
                f"⚠️ MONTHLY DRAWDOWN EXCEEDED: {drawdown_pct:.2f}%"
            )
            self._pause_bot(
                "Monthly drawdown limit (15%) reached — "
                "MANUAL REVIEW REQUIRED",
                pause_hours=720  # 1 bulan
            )

        return {
            "exceeded"    : exceeded,
            "drawdown_pct": drawdown_pct,
            "limit_pct"   : 15.0,
        }

    # ─── CONSECUTIVE LOSS TRACKER ───────────

    def record_trade_result(self, is_win: bool):
        """Catat hasil trade & update consecutive loss"""
        consec = db.get_state(self.consec_loss_key) or 0

        if is_win:
            # Reset consecutive loss
            db.set_state(self.consec_loss_key, 0)
            logger.info("✅ Win recorded — consecutive loss reset")

            # Check if in recovery mode
            recovery = db.get_state(self.recovery_mode_key)
            if recovery:
                wins_in_recovery = recovery.get("wins", 0) + 1
                db.set_state(self.recovery_mode_key, {
                    "active": True,
                    "wins"  : wins_in_recovery,
                })
                logger.info(
                    f"🔄 Recovery mode: {wins_in_recovery} wins"
                )

                # Exit recovery after 3 consecutive wins
                if wins_in_recovery >= 3:
                    db.set_state(self.recovery_mode_key, None)
                    logger.info(
                        "✅ Recovery mode OFF — "
                        "back to normal risk!"
                    )
        else:
            # Increment consecutive loss
            consec += 1
            db.set_state(self.consec_loss_key, consec)
            logger.warning(
                f"❌ Loss recorded — consecutive: {consec}"
            )

            # 3 consecutive losses = pause 24 jam
            if consec >= 3:
                logger.warning(
                    "⚠️ 3 CONSECUTIVE LOSSES — "
                    "Bot pause 24 jam!"
                )
                self._pause_bot(
                    "3 consecutive losses",
                    pause_hours=24
                )
                # Aktifkan recovery mode
                db.set_state(self.recovery_mode_key, {
                    "active": True,
                    "wins"  : 0,
                })

    def get_consecutive_losses(self) -> int:
        """Ambil jumlah consecutive loss"""
        return db.get_state(self.consec_loss_key) or 0

    # ─── BOT PAUSE SYSTEM ───────────────────

    def _pause_bot(self, reason: str,
                   pause_hours: int = 24):
        """Pause bot untuk durasi tertentu"""
        resume_time = (
            datetime.now() +
            timedelta(hours=pause_hours)
        ).isoformat()

        db.set_state(self.bot_paused_key, {
            "paused"     : True,
            "reason"     : reason,
            "paused_at"  : datetime.now().isoformat(),
            "resume_at"  : resume_time,
            "pause_hours": pause_hours,
        })
        logger.warning(
            f"⛔ BOT PAUSED: {reason} | "
            f"Resume: {resume_time}"
        )

    def is_bot_paused(self) -> dict:
        """Cek apakah bot sedang di-pause"""
        pause_data = db.get_state(self.bot_paused_key)

        if not pause_data or not pause_data.get("paused"):
            return {"paused": False}

        # Cek apakah sudah waktunya resume
        resume_at = datetime.fromisoformat(
            pause_data.get("resume_at", "")
        )

        if datetime.now() >= resume_at:
            # Auto resume
            db.set_state(self.bot_paused_key, {"paused": False})
            logger.info("✅ Bot auto-resumed!")
            return {"paused": False}

        time_left = resume_at - datetime.now()
        hours_left = time_left.seconds // 3600
        mins_left  = (time_left.seconds % 3600) // 60

        return {
            "paused"    : True,
            "reason"    : pause_data.get("reason"),
            "resume_at" : pause_data.get("resume_at"),
            "time_left" : f"{hours_left}j {mins_left}m",
        }

    def resume_bot(self):
        """Manual resume bot"""
        db.set_state(self.bot_paused_key, {"paused": False})
        logger.info("✅ Bot manually resumed!")

    # ─── RECOVERY MODE ──────────────────────

    def get_risk_in_recovery(self,
                             normal_risk: float) -> float:
        """
        Kurangi risk saat recovery mode.
        Risk turun ke 0.5%, naik bertahap setelah profit
        """
        recovery = db.get_state(self.recovery_mode_key)

        if not recovery or not recovery.get("active"):
            return normal_risk

        wins = recovery.get("wins", 0)

        # Bertahap naik sesuai wins dalam recovery
        if wins == 0:
            adjusted = normal_risk * 0.5   # 50% dari normal
        elif wins == 1:
            adjusted = normal_risk * 0.75  # 75% dari normal
        elif wins == 2:
            adjusted = normal_risk * 0.9   # 90% dari normal
        else:
            adjusted = normal_risk         # Kembali normal

        logger.info(
            f"🔄 Recovery mode risk: {adjusted:.2f}% "
            f"(normal: {normal_risk:.2f}%)"
        )
        return adjusted

    # ─── POSITION SIZING ────────────────────

    def calculate_position(self,
                           balance    : float,
                           entry_price: float,
                           sl_price   : float) -> dict:
        """
        Hitung ukuran posisi optimal berdasarkan:
        - Balance saat ini
        - Capital mode (Micro/Small/Medium/Large)
        - Recovery mode (kurangi risk)
        - Dynamic leverage
        """
        try:
            # Ambil capital mode
            cap_mode = cfg.get_capital_mode(balance)
            mode_name   = cap_mode["mode"]
            max_lev     = cap_mode["max_leverage"]
            base_risk   = cap_mode["risk_percent"]
            max_trades  = cap_mode["max_open_trades"]

            # Sesuaikan risk jika recovery mode
            risk_pct = self.get_risk_in_recovery(base_risk)

            # Risk amount dalam USDT
            risk_amount = balance * (risk_pct / 100)

            # Jarak SL
            sl_distance     = abs(entry_price - sl_price)
            sl_distance_pct = sl_distance / entry_price

            if sl_distance_pct <= 0:
                return {}

            # Hitung leverage ideal
            ideal_leverage = round(
                risk_amount / (balance * sl_distance_pct)
            )
            leverage = max(1, min(ideal_leverage, max_lev))

            # Position size
            position_usdt = balance * leverage * (risk_pct / 100) / sl_distance_pct
            position_usdt = min(position_usdt, balance * leverage)

            # Quantity
            quantity = round(position_usdt / entry_price, 6)

            # Minimum check ($1)
            min_position = 1.0
            if position_usdt < min_position:
                logger.warning(
                    f"⚠️ Position terlalu kecil: "
                    f"${position_usdt:.4f} < ${min_position}"
                )
                # Paksa minimum dengan leverage max
                quantity = round(
                    min_position / entry_price, 6
                )
                leverage = max_lev

            result = {
                "mode"          : mode_name,
                "balance"       : balance,
                "risk_pct"      : risk_pct,
                "risk_amount"   : risk_amount,
                "leverage"      : leverage,
                "position_usdt" : position_usdt,
                "quantity"      : quantity,
                "sl_distance_pct": sl_distance_pct * 100,
                "max_open_trades": max_trades,
            }

            logger.info(
                f"📐 Position: mode={mode_name} "
                f"risk={risk_pct}% lev={leverage}x "
                f"qty={quantity} pos=${position_usdt:.4f}"
            )

            return result

        except Exception as e:
            logger.error(f"❌ Position calc error: {e}")
            return {}

    # ─── TRAILING STOP ──────────────────────

    def calculate_trailing_stop(self,
                                entry    : float,
                                current  : float,
                                sl       : float,
                                direction: str,
                                atr      : float) -> dict:
        """
        Hitung trailing stop dinamis.
        Aktif setelah profit mencapai RR 1:1
        """
        try:
            risk = abs(entry - sl)

            if direction == "BUY":
                profit   = current - entry
                rr_curr  = profit / risk if risk > 0 else 0

                # Aktifkan trailing setelah 1:1
                if rr_curr >= 1.0:
                    # Trailing = ATR * 1.5 di bawah harga
                    trail_price = current - (atr * 1.5)

                    # Jangan turunkan SL
                    new_sl = max(trail_price, entry)

                    return {
                        "active"    : True,
                        "new_sl"    : round(new_sl, 4),
                        "trail_dist": atr * 1.5,
                        "rr_current": rr_curr,
                        "at_breakeven": new_sl >= entry,
                    }

            else:  # SELL
                profit  = entry - current
                rr_curr = profit / risk if risk > 0 else 0

                if rr_curr >= 1.0:
                    trail_price = current + (atr * 1.5)
                    new_sl = min(trail_price, entry)

                    return {
                        "active"    : True,
                        "new_sl"    : round(new_sl, 4),
                        "trail_dist": atr * 1.5,
                        "rr_current": rr_curr,
                        "at_breakeven": new_sl <= entry,
                    }

            return {"active": False, "rr_current": 0}

        except Exception as e:
            logger.error(f"❌ Trailing stop error: {e}")
            return {"active": False}

    # ─── PARTIAL CLOSE SYSTEM ───────────────

    def should_partial_close(self,
                             entry    : float,
                             current  : float,
                             tp1      : float,
                             tp2      : float,
                             direction: str,
                             closed_tp1: bool = False
                             ) -> dict:
        """
        Sistem partial close canggih:
        TP1 (1.272) → close 30%, SL ke BE
        TP2 (1.618) → close 40% lagi
        Sisa 30%   → trailing stop
        """
        try:
            if direction == "BUY":
                # Cek TP1
                if not closed_tp1 and current >= tp1:
                    return {
                        "should_close": True,
                        "tp_hit"      : "TP1",
                        "close_pct"   : 30,
                        "action"      : "Close 30% + Move SL to BE",
                        "new_sl"      : entry,  # Breakeven
                    }
                # Cek TP2
                elif closed_tp1 and current >= tp2:
                    return {
                        "should_close": True,
                        "tp_hit"      : "TP2",
                        "close_pct"   : 40,
                        "action"      : "Close 40% + Trailing stop sisa",
                        "new_sl"      : tp1,  # SL ke TP1
                    }

            else:  # SELL
                if not closed_tp1 and current <= tp1:
                    return {
                        "should_close": True,
                        "tp_hit"      : "TP1",
                        "close_pct"   : 30,
                        "action"      : "Close 30% + Move SL to BE",
                        "new_sl"      : entry,
                    }
                elif closed_tp1 and current <= tp2:
                    return {
                        "should_close": True,
                        "tp_hit"      : "TP2",
                        "close_pct"   : 40,
                        "action"      : "Close 40% + Trailing stop sisa",
                        "new_sl"      : tp1,
                    }

            return {"should_close": False}

        except Exception as e:
            logger.error(f"❌ Partial close error: {e}")
            return {"should_close": False}

    # ─── MARKET REGIME ──────────────────────

    def detect_market_regime(self,
                             df_daily) -> dict:
        """
        Deteksi kondisi market global:
        BULL / BEAR / RANGING / HIGH_VOLATILITY
        """
        try:
            import pandas as pd

            close   = df_daily["close"]
            high    = df_daily["high"]
            low     = df_daily["low"]

            # EMA 50 & 200 untuk trend global
            ema50  = close.ewm(span=50).mean()
            ema200 = close.ewm(span=200).mean()

            current_price = close.iloc[-1]
            curr_ema50    = ema50.iloc[-1]
            curr_ema200   = ema200.iloc[-1]

            # Volatility (ATR based)
            tr    = pd.concat([
                high - low,
                abs(high - close.shift(1)),
                abs(low  - close.shift(1))
            ], axis=1).max(axis=1)
            atr14 = tr.rolling(14).mean().iloc[-1]
            atr_pct = atr14 / current_price * 100

            # Determine regime
            if (current_price > curr_ema50 and
                    curr_ema50 > curr_ema200):
                regime = "BULL"
                risk_multiplier    = 1.0
                tp_aggressiveness  = "HIGH"

            elif (current_price < curr_ema50 and
                  curr_ema50 < curr_ema200):
                regime = "BEAR"
                risk_multiplier   = 0.8
                tp_aggressiveness = "MEDIUM"

            elif atr_pct > 3.0:
                regime = "HIGH_VOLATILITY"
                risk_multiplier   = 0.5
                tp_aggressiveness = "LOW"

            else:
                regime = "RANGING"
                risk_multiplier   = 0.7
                tp_aggressiveness = "LOW"

            result = {
                "regime"           : regime,
                "risk_multiplier"  : risk_multiplier,
                "tp_aggressiveness": tp_aggressiveness,
                "ema50"            : curr_ema50,
                "ema200"           : curr_ema200,
                "atr_pct"          : atr_pct,
                "current_price"    : current_price,
            }

            logger.info(
                f"🌍 Market regime: {regime} | "
                f"risk_mult: {risk_multiplier}x | "
                f"ATR: {atr_pct:.2f}%"
            )

            return result

        except Exception as e:
            logger.error(f"❌ Market regime error: {e}")
            return {
                "regime"         : "UNKNOWN",
                "risk_multiplier": 1.0,
            }

    # ─── FULL RISK CHECK ────────────────────

    def full_risk_check(self,
                        current_balance: float) -> dict:
        """
        Cek semua risk sebelum entry trade baru.
        Returns: apakah aman untuk entry
        """
        # 1. Cek bot paused
        pause_status = self.is_bot_paused()
        if pause_status["paused"]:
            return {
                "safe_to_trade": False,
                "reason"       : f"Bot paused: "
                                 f"{pause_status['reason']} | "
                                 f"Resume: {pause_status['time_left']}",
            }

        # 2. Cek daily drawdown
        daily_dd = self.check_daily_drawdown(current_balance)
        if daily_dd["exceeded"]:
            return {
                "safe_to_trade": False,
                "reason"       : f"Daily drawdown "
                                 f"{daily_dd['drawdown_pct']:.1f}% "
                                 f"exceeded limit "
                                 f"{daily_dd['limit_pct']}%",
            }

        # 3. Cek weekly drawdown
        weekly_dd = self.check_weekly_drawdown(current_balance)
        if weekly_dd["exceeded"]:
            return {
                "safe_to_trade": False,
                "reason"       : f"Weekly drawdown exceeded 10%",
            }

        # 4. Cek consecutive losses
        consec = self.get_consecutive_losses()
        if consec >= 3:
            return {
                "safe_to_trade": False,
                "reason"       : f"3 consecutive losses — "
                                 f"cooldown aktif",
            }

        # 5. Semua aman
        return {
            "safe_to_trade" : True,
            "daily_drawdown": daily_dd["drawdown_pct"],
            "consec_losses" : consec,
            "in_recovery"   : bool(
                db.get_state(self.recovery_mode_key)
            ),
        }


# Instance siap pakai
risk_manager = RiskManager()