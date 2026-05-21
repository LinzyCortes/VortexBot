# ============================================
# VORTEX BOT - RISK MANAGEMENT SYSTEM
# ============================================
#
# FIX v1.3:
#   - Regime-based confluence threshold
#     detect_market_regime() sudah ada tapi belum
#     dipakai untuk adjust threshold secara otomatis.
#     Sekarang get_regime_score_boost() return berapa
#     poin TAMBAHAN yang dibutuhkan sesuai regime:
#
#     BULL / BEAR       → +0  (threshold normal)
#     RANGING           → +2  (market choppy, lebih selektif)
#     HIGH_VOLATILITY   → +3  (market liar, sangat selektif)
#     UNKNOWN           → +1  (tidak yakin, sedikit lebih ketat)
#
#   - Regime-aware position sizing
#     Saat RANGING atau HIGH_VOLATILITY, risk_multiplier
#     dari detect_market_regime() sudah ada (0.7/0.5)
#     tapi belum diapply ke position sizing.
#     Sekarang calculate_position() pakai risk_multiplier
#     dari regime yang tersimpan di DB.
#
#   - Simpan regime ke DB setiap detect supaya
#     main.py bisa ambil tanpa perlu detect ulang.

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
        self.regime_key        = "market_regime"   # NEW

        self._reserved = 0.0

    # ─── VIRTUAL BALANCE ────────────────────

    def get_virtual_balance(self) -> float:
        stored = db.get_state(self.virtual_bal_key)
        if stored:
            return float(stored.get("balance", cfg.CAPITAL))
        self.set_virtual_balance(float(cfg.CAPITAL))
        return float(cfg.CAPITAL)

    def set_virtual_balance(self, balance: float):
        db.set_state(self.virtual_bal_key, {
            "balance"   : balance,
            "updated_at": datetime.now().isoformat(),
        })
        logger.info(f"💰 Virtual balance saved: ${balance:.4f}")

    def update_virtual_balance_after_trade(self, pnl: float):
        current = self.get_virtual_balance()
        new_bal = max(0.0, current + pnl)
        self.set_virtual_balance(new_bal)
        sign = "+" if pnl >= 0 else ""
        logger.info(
            f"💰 Compound: ${current:.4f} → ${new_bal:.4f} "
            f"({sign}{pnl:.4f})"
        )
        return new_bal

    # ─── RESERVE / RELEASE ──────────────────

    def reserve_balance(self, amount: float):
        self._reserved += amount

    def release_balance(self, amount: float):
        self._reserved = max(0.0, self._reserved - amount)

    # ─── BALANCE HELPERS ────────────────────

    def _get_effective_balance(self,
                               raw_balance: float) -> float:
        if cfg.IS_OKX and cfg.IS_OKX_DEMO:
            return self.get_virtual_balance()
        return raw_balance

    def set_starting_balance(self, balance: float):
        today     = datetime.now().strftime("%Y-%m-%d")
        stored    = db.get_state(self.starting_bal_key)
        effective = self._get_effective_balance(balance)

        if not stored or stored.get("date") != today:
            db.set_state(self.starting_bal_key, {
                "date"   : today,
                "balance": effective,
            })
            logger.info(f"💰 Starting balance: ${effective:.4f}")

    def get_starting_balance(self) -> float:
        stored = db.get_state(self.starting_bal_key)
        return stored.get("balance", 0) if stored else 0

    # ─── DRAWDOWN CHECKS ────────────────────

    def check_daily_drawdown(self,
                             current: float) -> dict:
        current  = self._get_effective_balance(current)
        starting = self.get_starting_balance()

        if starting <= 0:
            return {"exceeded": False, "drawdown_pct": 0}

        dd_pct   = (starting - current) / starting * 100
        limit    = cfg.MAX_DAILY_LOSS_PCT
        exceeded = dd_pct >= limit

        if exceeded:
            logger.warning(f"⚠️ DAILY DRAWDOWN: {dd_pct:.2f}%")
            self._pause_bot(
                f"Daily drawdown {limit:.0f}% reached"
            )

        return {
            "exceeded"    : exceeded,
            "drawdown_pct": dd_pct,
            "limit_pct"   : limit,
            "starting_bal": starting,
            "current_bal" : current,
        }

    def check_weekly_drawdown(self,
                              current: float) -> dict:
        current = self._get_effective_balance(current)
        weekly  = db.get_state("weekly_starting_balance")
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
        current = self._get_effective_balance(current)
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
                    db.set_state(self.recovery_mode_key, None)
                    logger.info("✅ Recovery mode OFF!")
        else:
            consec += 1
            db.set_state(self.consec_loss_key, consec)
            logger.warning(f"❌ Loss #{consec}")
            if consec >= 3:
                self._pause_bot(
                    "3 consecutive losses",
                    pause_hours=24
                )
                db.set_state(self.recovery_mode_key, {
                    "active": True, "wins": 0
                })

    def get_consecutive_losses(self) -> int:
        return db.get_state(self.consec_loss_key) or 0

    # ─── BOT PAUSE ──────────────────────────

    def _pause_bot(self, reason: str,
                   pause_hours: int = 24):
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
        data = db.get_state(self.bot_paused_key)
        if not data or not data.get("paused"):
            return {"paused": False}

        resume_at = datetime.fromisoformat(
            data.get("resume_at", "")
        )
        if datetime.now() >= resume_at:
            db.set_state(self.bot_paused_key, {"paused": False})
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
        db.set_state(self.bot_paused_key, {"paused": False})
        logger.info("✅ Bot manually resumed!")

    # ─── RECOVERY MODE ──────────────────────

    def get_risk_in_recovery(self,
                             normal_risk: float) -> float:
        recovery = db.get_state(self.recovery_mode_key)
        if not recovery or not recovery.get("active"):
            return normal_risk

        wins        = recovery.get("wins", 0)
        multipliers = {0: 0.5, 1: 0.75, 2: 0.9}
        mult        = multipliers.get(wins, 1.0)
        adjusted    = normal_risk * mult

        logger.info(
            f"🔄 Recovery risk: {adjusted:.2f}% "
            f"(normal: {normal_risk:.2f}%)"
        )
        return adjusted

    # ─── MARKET REGIME ──────────────────────

    def detect_market_regime(self,
                             df_daily: pd.DataFrame) -> dict:
        """
        Deteksi market regime dari daily candle.
        FIX v1.3: Simpan regime ke DB setelah detect
        supaya main.py bisa ambil tanpa detect ulang.
        """
        try:
            if df_daily is None or df_daily.empty or len(df_daily) < 20:
                return {"regime": "UNKNOWN", "risk_multiplier": 1.0}

            close = df_daily["close"]
            high  = df_daily["high"]
            low   = df_daily["low"]

            ema20 = close.ewm(span=20, adjust=False).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()

            curr_price = float(close.iloc[-1])
            curr_ema20 = float(ema20.iloc[-1])
            curr_ema50 = float(ema50.iloc[-1])

            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low  - close.shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr14   = float(tr.rolling(14).mean().iloc[-1])
            atr_pct = atr14 / curr_price * 100

            price_5d_ago = (
                float(close.iloc[-5])
                if len(close) >= 5
                else curr_price
            )
            momentum_pct = (
                (curr_price - price_5d_ago) /
                price_5d_ago * 100
            )

            if (curr_price > curr_ema20 and
                    curr_ema20 > curr_ema50 and
                    momentum_pct > 0):
                regime    = "BULL"
                risk_mult = 1.0
                emoji     = "📈"
            elif (curr_price < curr_ema20 and
                  curr_ema20 < curr_ema50 and
                  momentum_pct < 0):
                regime    = "BEAR"
                risk_mult = 0.8
                emoji     = "📉"
            elif atr_pct > 3.0:
                regime    = "HIGH_VOLATILITY"
                risk_mult = 0.5
                emoji     = "⚡"
            else:
                regime    = "RANGING"
                risk_mult = 0.7
                emoji     = "↔️"

            result = {
                "regime"          : regime,
                "emoji"           : emoji,
                "risk_multiplier" : risk_mult,
                "ema20"           : curr_ema20,
                "ema50"           : curr_ema50,
                "atr_pct"         : atr_pct,
                "momentum_pct"    : momentum_pct,
                "current_price"   : curr_price,
                "detected_at"     : datetime.now().isoformat(),
            }

            # FIX v1.3: simpan ke DB
            db.set_state(self.regime_key, result)

            logger.info(
                f"🌍 Regime: {emoji} {regime} | "
                f"risk_mult={risk_mult}x | "
                f"ATR={atr_pct:.2f}% | "
                f"momentum={momentum_pct:+.2f}%"
            )
            return result

        except Exception as e:
            logger.error(f"❌ Market regime error: {e}")
            return {"regime": "UNKNOWN", "risk_multiplier": 1.0}

    def get_cached_regime(self) -> dict:
        """
        Ambil regime terakhir dari DB tanpa detect ulang.
        Dipakai main.py saat analyze_pair supaya tidak
        fetch data 1D tiap scan (hemat API call).
        Cache valid 4 jam — regime tidak berubah cepat.
        """
        try:
            stored = db.get_state(self.regime_key)
            if not stored:
                return {"regime": "UNKNOWN", "risk_multiplier": 1.0}

            detected_at = datetime.fromisoformat(
                stored.get("detected_at", "2000-01-01")
            )
            age_hours = (
                datetime.now() - detected_at
            ).total_seconds() / 3600

            if age_hours > 4:
                # Cache expired → return UNKNOWN, main loop
                # akan refresh saat morning briefing
                return {"regime": "UNKNOWN", "risk_multiplier": 1.0}

            return stored

        except Exception as e:
            logger.error(f"❌ Get cached regime error: {e}")
            return {"regime": "UNKNOWN", "risk_multiplier": 1.0}

    # ─── REGIME SCORE BOOST ─────────────────

    def get_regime_score_boost(self) -> int:
        """
        Berapa poin TAMBAHAN yang dibutuhkan untuk entry
        berdasarkan market regime saat ini.

        Logic:
          BULL / BEAR       → +0  threshold normal
          UNKNOWN           → +1  sedikit lebih ketat
          RANGING           → +2  market choppy, banyak false signal
          HIGH_VOLATILITY   → +3  market liar, sangat selektif

        Dipakai di main.py:
          effective_threshold = cfg.MIN_CONFLUENCE_SCORE + boost
          if score >= effective_threshold → entry
        """
        try:
            if not cfg.REGIME_ENABLED:
                return 0

            regime_data = self.get_cached_regime()
            regime      = regime_data.get("regime", "UNKNOWN")

            boost_map = {
                "BULL"            : 0,
                "BEAR"            : 0,
                "RANGING"         : cfg.REGIME_RANGING_SCORE_BOOST,
                "HIGH_VOLATILITY" : cfg.REGIME_RANGING_SCORE_BOOST + 1,
                "UNKNOWN"         : 1,
            }

            boost = boost_map.get(regime, 0)

            if boost > 0:
                logger.debug(
                    f"📊 Regime boost: {regime} → "
                    f"+{boost} poin threshold "
                    f"(min={cfg.MIN_CONFLUENCE_SCORE} → "
                    f"effective={cfg.MIN_CONFLUENCE_SCORE + boost})"
                )

            return boost

        except Exception as e:
            logger.error(f"❌ Regime score boost error: {e}")
            return 0

    # ─── POSITION SIZING ────────────────────

    def calculate_position(self,
                           balance    : float,
                           entry_price: float,
                           sl_price   : float) -> dict:
        """
        Hitung posisi optimal.
        FIX v1.3: Apply regime risk_multiplier ke sizing.
        """
        try:
            balance = self._get_effective_balance(balance)

            cap_mode   = cfg.get_capital_mode(balance)
            mode_name  = cap_mode["mode"]
            max_lev    = cap_mode["max_leverage"]
            base_risk  = cap_mode["risk_percent"]
            max_trades = cap_mode["max_open_trades"]

            # Recovery mode adjustment
            risk_pct = self.get_risk_in_recovery(base_risk)

            # FIX v1.3: Regime risk multiplier
            regime_data  = self.get_cached_regime()
            regime       = regime_data.get("regime", "UNKNOWN")
            risk_mult    = regime_data.get("risk_multiplier", 1.0)

            # Hanya kurangi risk saat regime tidak ideal
            if regime in ("RANGING", "HIGH_VOLATILITY"):
                risk_pct = risk_pct * risk_mult
                logger.debug(
                    f"📐 Regime risk adjust: "
                    f"{regime} | mult={risk_mult} | "
                    f"risk={risk_pct:.2f}%"
                )

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
                "regime"         : regime,
                "regime_mult"    : risk_mult,
            }

            logger.info(
                f"📐 Position: {mode_name} | "
                f"risk={risk_pct:.2f}% | lev={leverage}x | "
                f"qty={quantity} | pos=${pos_usdt:.4f} | "
                f"regime={regime}"
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
                             closed_tp1: bool = False) -> dict:
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

    # ─── FULL RISK CHECK ────────────────────

    def full_risk_check(self,
                        current_balance: float) -> dict:
        current_balance = self._get_effective_balance(
            current_balance
        )

        pause = self.is_bot_paused()
        if pause["paused"]:
            return {
                "safe_to_trade": False,
                "reason"       : (
                    f"Bot paused: {pause['reason']} | "
                    f"Resume: {pause['time_left']}"
                ),
            }

        daily_dd = self.check_daily_drawdown(current_balance)
        if daily_dd["exceeded"]:
            return {
                "safe_to_trade": False,
                "reason"       : (
                    f"Daily drawdown "
                    f"{daily_dd['drawdown_pct']:.1f}% exceeded"
                ),
            }

        weekly_dd = self.check_weekly_drawdown(current_balance)
        if weekly_dd["exceeded"]:
            return {
                "safe_to_trade": False,
                "reason"       : "Weekly drawdown 10% exceeded",
            }

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