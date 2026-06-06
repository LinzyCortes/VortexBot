# ============================================
# VORTEX BOT - API SERVER (api.py)
# Tambahkan file ini ke repo GitHub kamu
# Jalankan bersamaan dengan main.py di Railway
# ============================================

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import threading
import uvicorn
import time

from datetime import datetime, timezone, timedelta
from config import cfg
from database import db
from risk.management import risk_manager
from filters.news_filter import session_filter
from notification.telegram import telegram

# ─── Dynamic Exchange Import ─────────────────
if cfg.IS_OKX:
    from exchange.okx import okx as exchange
    EXCHANGE_NAME = "OKX Demo" if cfg.IS_OKX_DEMO else "OKX Live"
else:
    from exchange.bybit import bybit as exchange
    EXCHANGE_NAME = "Bybit"

WIB = timezone(timedelta(hours=7))
UTC = timezone.utc

def now_wib(): return datetime.now(WIB)
def now_utc(): return datetime.now(UTC)
def wib_str(dt=None):
    if dt is None: dt = now_wib()
    return dt.strftime("%H:%M:%S WIB")

# ─── App ─────────────────────────────────────
app = FastAPI(title="VortexBot API", version="1.3b")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Reference ke VortexBot instance ─────────
# Di-set dari main.py setelah bot start
_bot_ref = None

def set_bot_ref(bot):
    global _bot_ref
    _bot_ref = bot

# ═════════════════════════════════════════════
# SCHEMAS
# ═════════════════════════════════════════════

class OpenTradeRequest(BaseModel):
    pair: str
    direction: str          # "BUY" atau "SELL"
    sl_price: float
    entry_price: Optional[float] = None
    tp1_price: Optional[float] = None
    tp_price: Optional[float] = None   # TP2
    tp3_price: Optional[float] = None

class CloseTradeRequest(BaseModel):
    trade_id: str

class PauseRequest(BaseModel):
    hours: Optional[int] = 24

# ═════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════

def _safe_float(val, default=0.0):
    try: return float(val)
    except: return default

def _uptime_hours():
    if _bot_ref and _bot_ref.start_time:
        delta = now_utc() - _bot_ref.start_time
        return round(delta.total_seconds() / 3600, 2)
    return 0.0

# ═════════════════════════════════════════════
# ENDPOINTS
# ═════════════════════════════════════════════

@app.get("/")
def root():
    return {"status": "ok", "bot": "VΦrtex Bot", "version": "1.3b"}

@app.get("/health")
def health():
    return {
        "status": "running",
        "time_wib": wib_str(),
        "exchange": EXCHANGE_NAME,
    }

# ─── BALANCE ─────────────────────────────────
@app.get("/api/balance")
def get_balance():
    try:
        bal_data = exchange.get_balance()
        balance  = _safe_float(bal_data.get("free", 0))

        # Weekly / monthly starting balance dari DB
        weekly  = db.get_state("weekly_starting_balance") or {}
        monthly = db.get_state("monthly_starting_balance") or {}
        w_start = _safe_float((weekly  or {}).get("balance", balance))
        m_start = _safe_float((monthly or {}).get("balance", balance))

        # Today PnL dari trade hari ini
        today_trades = db.get_today_trades() or []
        today_pnl    = sum(_safe_float(t.get("pnl", 0)) for t in today_trades if t.get("status") == "CLOSED")

        return {
            "balance"       : round(balance, 4),
            "free"          : round(balance, 4),
            "today_pnl"     : round(today_pnl, 4),
            "weekly_pnl"    : round(balance - w_start, 4),
            "monthly_pnl"   : round(balance - m_start, 4),
            "weekly_start"  : round(w_start, 4),
            "monthly_start" : round(m_start, 4),
            "currency"      : "USDT",
            "exchange"      : EXCHANGE_NAME,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── STATUS ──────────────────────────────────
@app.get("/api/status")
def get_status():
    try:
        pause   = risk_manager.is_bot_paused()
        regime  = risk_manager.get_cached_regime() or {}
        running = (_bot_ref.running if _bot_ref else False)
        last_scan = getattr(telegram, '_last_scan_wib', None)

        return {
            "running"         : running,
            "paused"          : pause.get("paused", False),
            "pause_reason"    : pause.get("reason", ""),
            "version"         : "1.3b",
            "exchange"        : EXCHANGE_NAME,
            "is_demo"         : getattr(cfg, "IS_OKX_DEMO", False),
            "pairs"           : list(cfg.PAIRS),
            "uptime_hours"    : _uptime_hours(),
            "open_trades"     : len(_bot_ref.open_trades) if _bot_ref else 0,
            "min_score"       : cfg.MIN_CONFLUENCE_SCORE,
            "regime"          : regime.get("regime", "UNKNOWN"),
            "regime_emoji"    : regime.get("emoji", ""),
            "regime_boost"    : risk_manager.get_regime_score_boost(),
            "vwap_enabled"    : getattr(cfg, "VWAP_ENABLED", True),
            "funding_enabled" : getattr(cfg, "FUNDING_RATE_ENABLED", True),
            "last_scan"       : str(last_scan) if last_scan else "–",
            "tf_bias"         : cfg.TF_BIAS,
            "tf_setup"        : cfg.TF_SETUP,
            "tf_entry"        : cfg.TF_ENTRY,
            "time_wib"        : wib_str(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── SESSION / KILLZONE ──────────────────────
@app.get("/api/session")
def get_session():
    try:
        sess = session_filter.get_session_info()
        kz   = session_filter.is_killzone()
        return {
            "session_name"    : sess.get("session_name", "Unknown"),
            "in_killzone"     : kz.get("in_killzone", False),
            "killzone_session": kz.get("session", ""),
            "in_delay"        : kz.get("in_delay", False),
            "delay_reason"    : kz.get("delay_reason", ""),
            "should_avoid"    : sess.get("should_avoid", False),
            "avoid_reason"    : sess.get("avoid_reason", ""),
            "next_session"    : kz.get("next_session", {}),
            "time_wib"        : wib_str(),
            "schedule": {
                "london": "15:00 – 17:30 WIB",
                "ny"    : "20:30 – 23:00 WIB",
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── REGIME ──────────────────────────────────
@app.get("/api/regime")
def get_regime():
    try:
        regime = risk_manager.get_cached_regime() or {}
        boost  = risk_manager.get_regime_score_boost()
        desc_map = {
            "BULL"    : "Market bullish — regime boost aktif, score min lebih rendah",
            "BEAR"    : "Market bearish — hanya SHORT yang difilter lebih longgar",
            "RANGING" : "Market sideways — filter lebih ketat, hindari breakout palsu",
            "UNKNOWN" : "Regime belum terdeteksi — akan update saat morning briefing",
        }
        r = regime.get("regime", "UNKNOWN")
        return {
            "regime"     : r,
            "emoji"      : regime.get("emoji", ""),
            "score_boost": boost,
            "description": desc_map.get(r, ""),
            "detected_at": regime.get("detected_at", "–"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── OPEN POSITIONS ──────────────────────────
@app.get("/api/positions")
def get_positions():
    try:
        open_trades = {}
        if _bot_ref:
            open_trades = _bot_ref.open_trades or {}

        # Juga ambil dari DB untuk data lengkap
        try:
            db_trades = db.get_open_trades() or []
        except Exception:
            db_trades = []

        result = []
        for trade_id, t in open_trades.items():
            pair      = t.get("pair", "")
            direction = t.get("direction", "")
            entry     = _safe_float(t.get("entry_price", 0))
            size      = _safe_float(t.get("size", 0))

            # Current price
            cur_price = 0.0
            try:
                ticker    = exchange.get_ticker(pair)
                cur_price = _safe_float(ticker.get("last", 0))
            except: pass

            # Unrealized PnL
            if cur_price and entry and size:
                if direction == "BUY":
                    upnl = (cur_price - entry) * size
                else:
                    upnl = (entry - cur_price) * size
            else:
                upnl = 0.0

            # Duration
            open_time = t.get("open_time")
            dur_min = 0
            if open_time and isinstance(open_time, datetime):
                dur_min = int((now_utc() - open_time).total_seconds() / 60)

            result.append({
                "trade_id"        : str(trade_id),
                "pair"            : pair,
                "direction"       : direction,
                "entry_price"     : round(entry, 6),
                "current_price"   : round(cur_price, 6),
                "sl_price"        : round(_safe_float(t.get("sl_price", 0)), 6),
                "tp1_price"       : round(_safe_float(t.get("tp1_price", 0)), 6),
                "tp2_price"       : round(_safe_float(t.get("tp2_price", 0)), 6),
                "tp3_price"       : round(_safe_float(t.get("tp3_price", 0)), 6),
                "size"            : round(size, 6),
                "leverage"        : t.get("leverage", 1),
                "unrealized_pnl"  : round(upnl, 4),
                "confluence_score": t.get("confluence_score", 0),
                "mode"            : t.get("mode", ""),
                "bp_mode"         : t.get("bp_mode", ""),
                "vwap_zone"       : t.get("vwap_zone", ""),
                "funding_rate"    : t.get("funding_rate", 0),
                "btc_trend"       : t.get("btc_trend", ""),
                "regime"          : t.get("regime", ""),
                "regime_boost"    : t.get("regime_boost", 0),
                "risk_amount"     : round(_safe_float(t.get("risk_amount", 0)), 4),
                "position_usdt"   : round(_safe_float(t.get("position_usdt", 0)), 4),
                "sl_pct"          : round(_safe_float(t.get("sl_pct", 0)), 4),
                "tp1_closed"      : t.get("tp1_closed", False),
                "duration_minutes": dur_min,
                "open_time_wib"   : t.get("open_time_wib", now_wib()).strftime("%Y-%m-%d %H:%M") if isinstance(t.get("open_time_wib"), datetime) else "–",
            })

        return {"trades": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── TICKERS (harga semua pair) ──────────────
@app.get("/api/tickers")
def get_tickers():
    try:
        pairs  = list(cfg.PAIRS)
        result = {}
        for pair in pairs:
            try:
                t = exchange.get_ticker(pair)
                funding = 0.0
                try:
                    fr = exchange.get_funding_rate(pair)
                    funding = _safe_float(fr.get("funding_rate", 0))
                except: pass

                result[pair] = {
                    "last"        : round(_safe_float(t.get("last", 0)), 6),
                    "high"        : round(_safe_float(t.get("high", 0)), 6),
                    "low"         : round(_safe_float(t.get("low", 0)), 6),
                    "vol_usdt"    : round(_safe_float(t.get("quoteVolume", t.get("vol_usdt", 0))), 2),
                    "change_pct"  : round(_safe_float(t.get("percentage", t.get("change_pct", 0))), 4),
                    "bid"         : round(_safe_float(t.get("bid", 0)), 6),
                    "ask"         : round(_safe_float(t.get("ask", 0)), 6),
                    "funding_rate": round(funding, 8),
                }
            except Exception as pe:
                result[pair] = {"last": 0, "error": str(pe)}
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── STATS ───────────────────────────────────
@app.get("/api/stats")
def get_stats():
    try:
        overall      = db.get_overall_stats() or {}
        today_trades = db.get_today_trades() or []
        cap_mode     = {}

        try:
            bal      = exchange.get_balance()
            balance  = _safe_float(bal.get("free", 0))
            cap_mode = cfg.get_capital_mode(balance)
        except: pass

        # Today stats
        closed_today  = [t for t in today_trades if t.get("status") == "CLOSED"]
        today_wins    = sum(1 for t in closed_today if _safe_float(t.get("pnl", 0)) > 0)
        today_losses  = len(closed_today) - today_wins
        today_pnl     = sum(_safe_float(t.get("pnl", 0)) for t in closed_today)

        total  = _safe_float(overall.get("total_trades", 0))
        wins   = _safe_float(overall.get("win_trades", overall.get("wins", 0)))
        losses = _safe_float(overall.get("loss_trades", overall.get("losses", 0)))
        wr     = round((wins / total * 100), 1) if total > 0 else 0.0

        regime_boost  = risk_manager.get_regime_score_boost()
        effective_min = cfg.MIN_CONFLUENCE_SCORE + regime_boost

        return {
            "total_trades" : int(total),
            "wins"         : int(wins),
            "losses"       : int(losses),
            "win_rate"     : wr,
            "total_pnl"    : round(_safe_float(overall.get("total_pnl", 0)), 4),
            "best_rr"      : round(_safe_float(overall.get("best_rr", 0)), 2),
            "avg_score"    : round(_safe_float(overall.get("avg_confluence", 0)), 1),
            "today_trades" : len(closed_today),
            "today_wins"   : today_wins,
            "today_losses" : today_losses,
            "today_pnl"    : round(today_pnl, 4),
            "open_trades"  : len(_bot_ref.open_trades) if _bot_ref else 0,
            "cap_mode"     : cap_mode.get("mode", "–"),
            "min_score"    : effective_min,
            "base_score"   : cfg.MIN_CONFLUENCE_SCORE,
            "regime_boost" : regime_boost,
            "phase"        : "Demo P1" if cfg.MIN_CONFLUENCE_SCORE <= 15 else "Live",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── HISTORY ─────────────────────────────────
@app.get("/api/history")
def get_history(limit: int = 30):
    try:
        trades = db.get_trade_history(limit=limit) or []
        result = []
        for t in trades:
            pnl = _safe_float(t.get("pnl", 0))
            result.append({
                "trade_id"        : str(t.get("id", t.get("trade_id", ""))),
                "pair"            : t.get("pair", ""),
                "direction"       : t.get("direction", ""),
                "entry_price"     : round(_safe_float(t.get("entry_price", 0)), 6),
                "close_price"     : round(_safe_float(t.get("close_price", 0)), 6),
                "sl_price"        : round(_safe_float(t.get("sl_price", 0)), 6),
                "tp1_price"       : round(_safe_float(t.get("tp1_price", 0)), 6),
                "tp2_price"       : round(_safe_float(t.get("tp2_price", 0)), 6),
                "pnl"             : round(pnl, 4),
                "rr_achieved"     : round(_safe_float(t.get("rr_achieved", t.get("rr", 0))), 2),
                "confluence_score": t.get("confluence_score", t.get("score", 0)),
                "close_reason"    : t.get("close_reason", t.get("reason", "")),
                "duration_minutes": t.get("duration_minutes", t.get("duration", 0)),
                "bp_mode"         : t.get("bp_mode", ""),
                "vwap_zone"       : t.get("vwap_zone", ""),
                "regime"          : t.get("regime", ""),
                "btc_trend"       : t.get("btc_trend", ""),
                "close_time_wib"  : str(t.get("close_time_wib", t.get("closed_at", "")))[:16] if t.get("close_time_wib") or t.get("closed_at") else "–",
                "status"          : t.get("status", "CLOSED"),
            })
        return {"trades": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── SCORE INFO ───────────────────────────────
@app.get("/api/score_info")
def get_score_info():
    """Breakdown 24 poin confluence score"""
    return {
        "total_max"  : 24,
        "min_score"  : cfg.MIN_CONFLUENCE_SCORE,
        "regime_boost": risk_manager.get_regime_score_boost(),
        "breakdown"  : [
            {"name": "EMA Align (13/21)",       "max": 1},
            {"name": "Stochastic (5,3,3)",       "max": 2},
            {"name": "Volume",                   "max": 1},
            {"name": "Candle Pattern",           "max": 1},
            {"name": "Breakout",                 "max": 2},
            {"name": "Pullback ke OB/FVG/Fib",  "max": 1},
            {"name": "BOS / CHoCH",              "max": 2},
            {"name": "Order Block",              "max": 2},
            {"name": "FVG",                      "max": 1},
            {"name": "Liquidity Swept",          "max": 1},
            {"name": "Premium / Discount",       "max": 1},
            {"name": "Fibonacci 0.618",          "max": 2},
            {"name": "Fibonacci 0.500",          "max": 1},
            {"name": "Killzone",                 "max": 1},
            {"name": "News Clear",               "max": 1},
            {"name": "Upgrade Bonus",            "max": 1},
            {"name": "VWAP Bonus",               "max": 2},
            {"name": "Funding Rate Bonus",       "max": 1},
            {"name": "Correlation BTC",          "max": 1},
            {"name": "Regime Boost (dynamic)",   "max": 1},
        ]
    }

# ─── OPEN TRADE (manual) ─────────────────────
@app.post("/api/open_trade")
def open_trade(req: OpenTradeRequest):
    try:
        direction = req.direction.upper()
        if direction not in ("BUY", "SELL"):
            raise HTTPException(400, "direction harus BUY atau SELL")

        pair = req.pair
        if pair not in cfg.PAIRS:
            raise HTTPException(400, f"Pair {pair} tidak ada di config bot")

        # Risk check
        balance    = _safe_float(exchange.get_balance().get("free", 0))
        risk_check = risk_manager.full_risk_check(balance)
        if not risk_check.get("safe_to_trade"):
            raise HTTPException(400, f"Risk check failed: {risk_check.get('reason')}")

        # Position sizing
        entry = req.entry_price or _safe_float(exchange.get_ticker(pair).get("last", 0))
        if not entry:
            raise HTTPException(400, "Gagal ambil harga entry")

        position = risk_manager.calculate_position(
            balance=balance, entry_price=entry, sl_price=req.sl_price
        )
        if not position or position.get("quantity", 0) <= 0:
            raise HTTPException(400, "Quantity 0 — cek balance dan SL distance")

        leverage = position.get("leverage", 1)
        quantity = position.get("quantity", 0)

        # Hitung TP otomatis kalau tidak diisi
        risk = abs(entry - req.sl_price)
        is_long = direction == "BUY"
        tp1 = req.tp1_price or (entry + risk * 1 if is_long else entry - risk * 1)
        tp2 = req.tp_price  or (entry + risk * 2 if is_long else entry - risk * 2)
        tp3 = req.tp3_price or (entry + risk * 3 if is_long else entry - risk * 3)

        exchange.set_leverage(pair, leverage)
        side  = "buy" if direction == "BUY" else "sell"
        order = exchange.place_market_order(pair, side, quantity)
        if not order:
            raise HTTPException(500, "Order gagal di exchange")

        exchange.place_stop_loss(pair, side, quantity, req.sl_price)
        tp_qty = round(quantity * 0.4, 6)
        exchange.place_take_profit(pair, side, tp_qty, tp2)

        trade_data = {
            "pair"       : pair,
            "direction"  : direction,
            "entry_price": entry,
            "sl_price"   : req.sl_price,
            "tp1_price"  : tp1,
            "tp2_price"  : tp2,
            "tp3_price"  : tp3,
            "size"       : quantity,
            "leverage"   : leverage,
            "mode"       : position.get("mode", "MANUAL"),
            "risk_amount": position.get("risk_amount", 0),
            "confluence_score": 0,
            "bp_mode"    : "MANUAL",
        }
        trade_id = db.save_trade(trade_data)

        if _bot_ref:
            from datetime import datetime
            _bot_ref.open_trades[trade_id] = {
                **trade_data,
                "trade_id"          : trade_id,
                "open_time"         : datetime.now(UTC),
                "open_time_wib"     : datetime.now(WIB),
                "tp1_closed"        : False,
                "quantity_remaining": quantity,
                "original_qty"      : quantity,
            }

        telegram.send(
            f"🤖 <b>MANUAL TRADE OPENED</b>\n"
            f"Pair : {pair}\n"
            f"Dir  : {direction}\n"
            f"Entry: {entry:.4f}\n"
            f"SL   : {req.sl_price:.4f}\n"
            f"TP1  : {tp1:.4f} (RR 1:1)\n"
            f"TP2  : {tp2:.4f} (RR 1:2)\n"
            f"TP3  : {tp3:.4f} (RR 1:3)\n"
            f"Qty  : {quantity}\n"
            f"Lev  : {leverage}x\n"
            f"Via  : Mini App\n"
            f"⏰ {wib_str()}"
        )

        return {
            "success" : True,
            "trade_id": str(trade_id),
            "pair"    : pair,
            "direction": direction,
            "entry"   : entry,
            "quantity": quantity,
            "leverage": leverage,
            "sl"      : req.sl_price,
            "tp1"     : tp1,
            "tp2"     : tp2,
            "tp3"     : tp3,
        }
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── CLOSE TRADE (manual) ────────────────────
@app.post("/api/close_trade")
def close_trade(req: CloseTradeRequest):
    try:
        trade_id = req.trade_id

        if not _bot_ref or trade_id not in _bot_ref.open_trades:
            raise HTTPException(404, f"Trade {trade_id} tidak ditemukan di open trades")

        trade = _bot_ref.open_trades[trade_id]
        pair      = trade.get("pair")
        direction = trade.get("direction")
        qty       = trade.get("quantity_remaining", trade.get("size", 0))

        exchange.cancel_all_orders(pair)
        exchange.close_position(pair, direction, qty)

        # Ambil harga close sekarang
        cur_price = _safe_float(exchange.get_ticker(pair).get("last", 0))
        entry     = _safe_float(trade.get("entry_price", 0))
        pnl       = (cur_price - entry) * qty if direction == "BUY" else (entry - cur_price) * qty

        new_balance = _safe_float(exchange.get_balance().get("free", 0))
        if getattr(cfg, "IS_OKX_DEMO", False):
            new_balance = risk_manager.update_virtual_balance_after_trade(pnl)
            risk_manager.release_balance(trade.get("risk_amount", 0))

        close_data = {
            "status"      : "CLOSED",
            "pnl"         : round(pnl, 4),
            "close_reason": "MANUAL_CLOSE",
            "close_price" : cur_price,
            "new_balance" : new_balance,
            "close_time_wib": now_wib().isoformat(),
            "close_time_utc": now_utc().isoformat(),
        }
        db.close_trade(trade_id, close_data)

        if trade_id in _bot_ref.open_trades:
            del _bot_ref.open_trades[trade_id]

        telegram.send(
            f"{'✅' if pnl >= 0 else '❌'} <b>MANUAL CLOSE</b>\n"
            f"Pair  : {pair}\n"
            f"PnL   : {'+'if pnl>=0 else ''}{pnl:.4f} USDT\n"
            f"Entry : {entry:.4f}\n"
            f"Close : {cur_price:.4f}\n"
            f"Via   : Mini App\n"
            f"⏰ {wib_str()}"
        )

        return {
            "success"    : True,
            "trade_id"   : trade_id,
            "pnl"        : round(pnl, 4),
            "close_price": cur_price,
            "new_balance": round(new_balance, 4),
        }
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── PAUSE BOT ───────────────────────────────
@app.post("/api/pause")
def pause_bot(req: PauseRequest):
    try:
        hours = req.hours or 24
        risk_manager.pause_bot(hours)
        telegram.send(f"⏸️ Bot di-pause via Mini App selama {hours} jam | {wib_str()}")
        return {"success": True, "paused_hours": hours}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/resume")
def resume_bot():
    try:
        risk_manager.resume_bot()
        telegram.send(f"▶️ Bot di-resume via Mini App | {wib_str()}")
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── RECENT SIGNALS ──────────────────────────
@app.get("/api/signals")
def get_signals(limit: int = 10):
    try:
        # Ambil dari history trade sebagai proxy signals
        trades = db.get_trade_history(limit=limit) or []
        signals = [t for t in trades if t.get("confluence_score", 0) > 0]
        return {"signals": signals, "count": len(signals)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ═════════════════════════════════════════════
# SERVER RUNNER
# ═════════════════════════════════════════════

def start_api_server(bot_ref=None, host="0.0.0.0", port=8080):
    """
    Panggil fungsi ini dari main.py setelah bot.startup()
    Jalankan di thread terpisah supaya bot tetap bisa loop

    Contoh di main.py:
        from api import start_api_server, set_bot_ref
        ...
        if bot.startup():
            set_bot_ref(bot)
            threading.Thread(
                target=start_api_server,
                args=(bot,),
                daemon=True
            ).start()
            bot.run()
    """
    if bot_ref:
        set_bot_ref(bot_ref)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    # Test standalone: python api.py
    print("Starting VortexBot API standalone (no bot ref)...")
    uvicorn.run(app, host="0.0.0.0", port=8080, reload=False)
