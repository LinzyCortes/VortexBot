# ============================================
# VORTEX BOT - RISK MANAGEMENT SYSTEM
# ============================================

import os
import json
import pandas as pd
from datetime import datetime, timedelta
from config import cfg
from database import db
from logger import logger


class RiskManager:

    def __init__(self):
        self.daily_loss_key    = "daily_loss"
        self.consec_loss_key   = "consecutive_losses"
        self.bot_paused_key    = "bot_paused"
        self.recovery_mode_key = "recovery_mode"
        self.starting_bal_key  = "starting_balance"
        self.virtual_bal_key   = "virtual_balance"

    # ─── VIRTUAL BALANCE (Compound) ─────────

    def get_virtual_balance(self) -> float:
        """Ambil virtual balance dari DB (persistent)"""
        stored = db.get_state(self.virtual_bal_key)
        if stored:
            return float(stored.get("balance", cfg.CAPITAL))
        # Pertama kali → set dari CAPITAL config
        self.set_virtual_balance(float(cfg.CAPITAL))
        return float(cfg.CAPITAL)

    def set_virtual_balance(self, balance: float):
        """Simpan virtual balance ke DB"""
        db.set_state(self.virtual_bal_key, {
            "balance"   : balance,
            "updated_at": datetime.now().isoformat(),
        })
        logger.info(f"💰 Virtual balance saved: ${balance:.4f}")

    def update_virtual_balance_after_trade(self,
                                            pnl: float):
        """Update virtual balance setelah trade (compound!)"""
        current = self.get_virtual_balance()
        new_bal = max(0.0, current + pnl)
        self.set_virtual_balance(new_bal)

        change = "+" if pnl >= 0 else ""
        logger.info(
            f"💰 Compound update: "
            f"${current:.4f} → ${new_bal:.4f} "
            f"({change}{pnl:.4f})"
        )
        return new_bal

    # ─── BALANCE TRACKING ───────────────────

    def set_starting_balance(self, balance: float):
        """Simpan balance awal hari ini"""
        today  = datetime.now().strftime("%Y-%m-%d")
        stored = db.get_state(self.starting_bal_key)

        if not stored or stored.get("date") != today:
            # Gunakan virtual balance kalau OKX demo
            if cfg.IS_OKX and cfg.IS_OKX_DEMO:
                balance = self.get_virtual_balance()

            db.set_state(self.starting_bal_key, {
                "date"   : today,
                "balance": balance,
            })
            logger.info(
                f"💰 Starting balance: ${balance:.4f}"
            )

    def get_starting_balance(self) -> float:
        """Ambil balance awal hari ini"""
        stored = db.get_state(self.starting_bal_key)
        if stored:
            return stored.get("balance", 0)
        return 0

    # ─── DRAWDOWN CHECKS ────────────────────

    def check_daily_drawdown(self,
                             current: float) -> dict:
        """Cek daily drawdown (5%)"""
        starting = self.get_starting_balance()
        if starting <= 0:
            return {"exceeded": False, "drawdown_pct": 0}

        dd_pct   = (starting - current) / starting * 100
        exceeded = dd_pct >= cfg.MAX_DAILY_LOSS_PCT

        if exceeded:
            logger.warning(
                f"⚠️ DAILY DRAWDOWN: {dd_pct:.2f}%"
            )
            self._pause_bot("Daily drawdown 5% reached")

        return {
            "exceeded"    : exceeded,
            "drawdown_pct": dd_pct,
            "limit_pct"   : cfg.MAX_DAILY_LOSS_PCT,
            "starting_bal": starting,
            "current_bal" : current,
        }

    def check_weekly_drawdown(self,
                              current: float) -> dict:
        """Cek weekly drawdown (10%)"""
        weekly = db.get_state("weekly_starting_balance")
        if not weekly:
            return {"exceeded": False, "drawdown_pct": 0}

        start    = weekly.get("balance", current)
        dd_pct   = (start - current) / start * 100
        exceeded = dd_pct >= 10.0

        if exceeded:
            self._pause_bot(
                "Weekly drawdown 10% reached",
                pause_hours=168
            )

        return {
            "exceeded"    : exceeded,
            "drawdown_pct": dd_pct,
            "limit_pct"   : 10.0,
        }

    def check_monthly_drawdown(self,
                               current: float) -> dict:
        """Cek monthly drawdown (15%)"""
        monthly = db.get_state("monthly_starting_balance")
        if not monthly:
            return {"exceeded": False, "drawdown_pct": 0}

        start    = monthly.get("balance", current)
        dd_pct   = (start - current) / start * 100
        exceeded = dd_pct >= 15.0

        if exceeded:
            self._pause_bot(
                "Monthly drawdown 15% — REVIEW REQUIRED",
                pause_hours=720
            )

        return {
            "exceeded"    : exceeded,
            "drawdown_pct": dd_pct,
            "limit_pct"   : 15.0,
        }

    # ─── CONSECUTIVE LOSS ───────────────────

    def record_trade_result(self, is_win: bool):
        """Catat hasil trade"""
        consec = db.get_state(self.consec_loss_key) or 0

        if is_win:
            db.set_state(self.consec_loss_key, 0)
            logger.info("✅ Win → consecutive loss reset")

            recovery = db.get_state(self.recovery_mode_key)
            if recovery:
                wins = recovery.get("wins", 0) + 1
                db.set_state(self.recovery_mode_key, {
                    "active": True, "wins": wins
                })
                if wins >= 3:
                    db.set_state(
                        self.recovery_mode_key, None
                    )
                    logger.info("✅ Recovery mode OFF!")
        else:
            consec += 1
            db.set_state(self.consec_loss_key, consec)
            logger.warning(
                f"❌ Loss #{consec}"
            )
            if consec >= 3:
                self._pause_bot(
                    "3 consecutive losses", pause_hours=24
                )
                db.set_state(self.recovery_mode_key, {
                    "active": True, "wins": 0
                })

    def get_consecutive_losses(self) -> int:
        return db.get_state(self.consec_loss_key) or 0

    # ─── BOT PAUSE ──────────────────────────

    def _pause_bot(self, reason: str,
                   pause_hours: int = 24):
        """Pause bot"""
        resume = (
            datetime.now() + timedelta(hours=pause_hours)
        ).isoformat()
        db.set_state(self.bot_paused_key, {
            "paused"     : True,
            "reason"     : reason,
            "paused_at"  : datetime.now().isoformat(),
            "resume_at"  : resume,
            "pause_hours": pause_hours,
        })
        logger.warning(f"⛔ BOT PAUSED: {reason}")

    def is_bot_paused(self) -> dict:
        """Cek apakah bot paused"""
        data = db.get_state(self.bot_paused_key)
        if not data or not data.get("paused"):
            return {"paused": False}

        resume_at = datetime.fromisoformat(
            data.get("resume_at", "")
        )
        if datetime.now() >= resume_at:
            db.set_state(
                self.bot_paused_key, {"paused": False}
            )
            logger.info("✅ Bot auto-resumed!")
            return {"paused": False}

        left       = resume_at - datetime.now()
        hours_left = left.seconds // 3600
        mins_left  = (left.seconds % 3600) // 60

        return {
            "paused"   : True,
            "reason"   : data.get("reason"),
            "resume_at": data.get("resume_at"),
            "time_left": f"{hours_left}j {mins_left}m",
        }

    def resume_bot(self):
        """Manual resume"""
        db.set_state(self.bot_paused_key, {"paused": False})
        logger.info("✅ Bot manually resumed!")

    # ─── RECOVERY MODE ──────────────────────

    def get_risk_in_recovery(self,
                             normal_risk: float) -> float:
        """Kurangi risk di recovery mode"""
        recovery = db.get_state(self.recovery_mode_key)
        if not recovery or not recovery.get("active"):
            return normal_risk

        wins = recovery.get("wins", 0)
        multipliers = {0: 0.5, 1: 0.75, 2: 0.9}
        mult = multipliers.get(wins, 1.0)
        adjusted = normal_risk * mult

        logger.info(
            f"🔄 Recovery risk: {adjusted:.2f}% "
            f"(normal: {normal_risk:.2f}%)"
        )
        return adjusted

    # ─── POSITION SIZING ────────────────────

    def calculate_position(self,
                           balance    : float,
                           entry_price: float,
                           sl_price   : float) -> dict:
        """Hitung posisi optimal"""
        try:
            cap_mode   = cfg.get_capital_mode(balance)
            mode_name  = cap_mode["mode"]
            max_lev    = cap_mode["max_leverage"]
            base_risk  = cap_mode["risk_percent"]
            max_trades = cap_mode["max_open_trades"]

            risk_pct    = self.get_risk_in_recovery(base_risk)
            risk_amount = balance * (risk_pct / 100)

            sl_dist     = abs(entry_price - sl_price)
            sl_dist_pct = sl_dist / entry_price

            if sl_dist_pct <= 0:
                return {}

            ideal_lev = round(
                risk_amount / (balance * sl_dist_pct)
            )
            leverage = max(1, min(ideal_lev, max_lev))

            pos_usdt = min(
                balance * leverage * (risk_pct/100) / sl_dist_pct,
                balance * leverage
            )
            quantity = round(pos_usdt / entry_price, 6)

            # Minimum $1
            if pos_usdt < 1.0:
                quantity = round(1.0 / entry_price, 6)
                leverage = max_lev

            result = {
                "mode"           : mode_name,
                "balance"        : balance,
                "risk_pct"       : risk_pct,
                "risk_amount"    : risk_amount,
                "leverage"       : leverage,
                "position_usdt"  : pos_usdt,
                "quantity"       : quantity,
                "sl_distance_pct": sl_dist_pct * 100,
                "max_open_trades": max_trades,
            }

            logger.info(
                f"📐 Position: {mode_name} | "
                f"risk={risk_pct}% | lev={leverage}x | "
                f"qty={quantity} | pos=${pos_usdt:.4f}"
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
        """Trailing stop dinamis"""
        try:
            risk = abs(entry - sl)

            if direction == "BUY":
                profit  = current - entry
                rr_curr = profit / risk if risk > 0 else 0
                if rr_curr >= 1.0:
                    trail  = current - (atr * 1.5)
                    new_sl = max(trail, entry)
                    return {
                        "active"      : True,
                        "new_sl"      : round(new_sl, 4),
                        "rr_current"  : rr_curr,
                        "at_breakeven": new_sl >= entry,
                    }

            else:
                profit  = entry - current
                rr_curr = profit / risk if risk > 0 else 0
                if rr_curr >= 1.0:
                    trail  = current + (atr * 1.5)
                    new_sl = min(trail, entry)
                    return {
                        "active"      : True,
                        "new_sl"      : round(new_sl, 4),
                        "rr_current"  : rr_curr,
                        "at_breakeven": new_sl <= entry,
                    }

            return {"active": False, "rr_current": 0}

        except Exception as e:
            logger.error(f"❌ Trailing stop error: {e}")
            return {"active": False}

    # ─── PARTIAL CLOSE ──────────────────────

    def should_partial_close(self,
                             entry    : float,
                             current  : float,
                             tp1      : float,
                             tp2      : float,
                             direction: str,
                             closed_tp1: bool = False
                             ) -> dict:
        """Partial close system"""
        try:
            if direction == "BUY":
                if not closed_tp1 and current >= tp1:
                    return {
                        "should_close": True,
                        "tp_hit"      : "TP1",
                        "close_pct"   : 30,
                        "new_sl"      : entry,
                    }
                elif closed_tp1 and current >= tp2:
                    return {
                        "should_close": True,
                        "tp_hit"      : "TP2",
                        "close_pct"   : 40,
                        "new_sl"      : tp1,
                    }
            else:
                if not closed_tp1 and current <= tp1:
                    return {
                        "should_close": True,
                        "tp_hit"      : "TP1",
                        "close_pct"   : 30,
                        "new_sl"      : entry,
                    }
                elif closed_tp1 and current <= tp2:
                    return {
                        "should_close": True,
                        "tp_hit"      : "TP2",
                        "close_pct"   : 40,
                        "new_sl"      : tp1,
                    }

            return {"should_close": False}

        except Exception as e:
            logger.error(f"❌ Partial close error: {e}")
            return {"should_close": False}

    # ─── MARKET REGIME ──────────────────────

    def detect_market_regime(self, df_daily) -> dict:
        """Deteksi market regime — FIXED!"""
        try:
            if df_daily is None or df_daily.empty:
                return {
                    "regime"         : "UNKNOWN",
                    "risk_multiplier": 1.0,
                }

            if len(df_daily) < 20:
                return {
                    "regime"         : "UNKNOWN",
                    "risk_multiplier": 1.0,
                }

            close = df_daily["close"]
            high  = df_daily["high"]
            low   = df_daily["low"]

            # EMA 20 & 50 (lebih cocok untuk data terbatas)
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()

            curr_price = float(close.iloc[-1])
            curr_ema20 = float(ema20.iloc[-1])
            curr_ema50 = float(ema50.iloc[-1])

            # ATR untuk volatility
            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low  - close.shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr14   = float(tr.rolling(14).mean().iloc[-1])
            atr_pct = atr14 / curr_price * 100

            # Price momentum (5 candle)
            price_5d_ago = float(close.iloc[-5]) \
                if len(close) >= 5 else curr_price
            momentum_pct = (
                (curr_price - price_5d_ago) /
                price_5d_ago * 100
            )

            # Determine regime
            if (curr_price > curr_ema20 and
                    curr_ema20 > curr_ema50 and
                    momentum_pct > 0):
                regime = "BULL"
                risk_mult = 1.0
                tp_agg    = "HIGH"
                emoji     = "📈"

            elif (curr_price < curr_ema20 and
                  curr_ema20 < curr_ema50 and
                  momentum_pct < 0):
                regime = "BEAR"
                risk_mult = 0.8
                tp_agg    = "MEDIUM"
                emoji     = "📉"

            elif atr_pct > 3.0:
                regime = "HIGH_VOLATILITY"
                risk_mult = 0.5
                tp_agg    = "LOW"
                emoji     = "⚡"

            else:
                regime = "RANGING"
                risk_mult = 0.7
                tp_agg    = "LOW"
                emoji     = "↔️"

            result = {
                "regime"           : regime,
                "emoji"            : emoji,
                "risk_multiplier"  : risk_mult,
                "tp_aggressiveness": tp_agg,
                "ema20"            : curr_ema20,
                "ema50"            : curr_ema50,
                "atr_pct"          : atr_pct,
                "momentum_pct"     : momentum_pct,
                "current_price"    : curr_price,
            }

            logger.info(
                f"🌍 Market: {emoji} {regime} | "
                f"risk_mult: {risk_mult}x | "
                f"ATR: {atr_pct:.2f}% | "
                f"momentum: {momentum_pct:+.2f}%"
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
        """Cek semua risk sebelum entry"""

        # Pakai virtual balance untuk OKX demo
        if cfg.IS_OKX and cfg.IS_OKX_DEMO:
            current_balance = self.get_virtual_balance()

        # 1. Bot paused?
        pause = self.is_bot_paused()
        if pause["paused"]:
            return {
                "safe_to_trade": False,
                "reason"       : (
                    f"Bot paused: {pause['reason']} | "
                    f"Resume: {pause['time_left']}"
                ),
            }

        # 2. Daily drawdown?
        daily_dd = self.check_daily_drawdown(
            current_balance
        )
        if daily_dd["exceeded"]:
            return {
                "safe_to_trade": False,
                "reason"       : (
                    f"Daily drawdown "
                    f"{daily_dd['drawdown_pct']:.1f}% exceeded"
                ),
            }

        # 3. Weekly drawdown?
        weekly_dd = self.check_weekly_drawdown(
            current_balance
        )
        if weekly_dd["exceeded"]:
            return {
                "safe_to_trade": False,
                "reason"       : "Weekly drawdown 10% exceeded",
            }

        # 4. Consecutive losses?
        consec = self.get_consecutive_losses()
        if consec >= 3:
            return {
                "safe_to_trade": False,
                "reason"       : "3 consecutive losses — cooldown",
            }

        return {
            "safe_to_trade" : True,
            "daily_drawdown": daily_dd["drawdown_pct"],
            "consec_losses" : consec,
            "balance"       : current_balance,
            "in_recovery"   : bool(
                db.get_state(self.recovery_mode_key)
            ),
        }


# Instance siap pakai
risk_manager = RiskManager()