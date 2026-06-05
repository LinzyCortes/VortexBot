# ============================================
# VORTEX BOT v1.3b - MAIN ENGINE
# FIX v1.3b:
#   - Regime di-detect saat startup() supaya tidak
#     UNKNOWN setelah redeploy. Sebelumnya hanya
#     refresh di morning_briefing jam 00:00 WIB.
#   - analyze_pair() tidak lagi terganggu oleh
#     in_delay dari get_session_info() — delay
#     sudah dipisah dari should_avoid di news_filter.
#   - Log Regime di scan done sekarang akurat.
# UPDATE:
#   - Mini App API server (FastAPI) jalan di thread
#     terpisah di port 8080, tidak ganggu bot loop.
# ============================================

import time
import threading
import schedule
from datetime import datetime, timezone, timedelta
from config import cfg
from logger import logger
from database import db
from journal import journal
from filters.news_filter import news_filter, session_filter
from strategy.indicators import indicators
from strategy.smc import smc
from strategy.fibonacci import fibonacci
from strategy.confluence import confluence_scorer
from strategy.breakout_pullback import breakout_pullback
from strategy.vwap import vwap_analyzer
from strategy.funding_rate import funding_filter
from strategy.correlation import correlation_filter
from risk.management import risk_manager
from notification.telegram import telegram
from learning.evaluator import evaluator
from api import start_api_server, set_bot_ref

# ─── Timezone Helpers ────────────────────────────────────────────────────────
WIB = timezone(timedelta(hours=7))
UTC = timezone.utc

def now_wib() -> datetime:
    return datetime.now(WIB)

def now_utc() -> datetime:
    return datetime.now(UTC)

def wib_str(dt: datetime = None) -> str:
    if dt is None:
        dt = now_wib()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC).astimezone(WIB)
    else:
        dt = dt.astimezone(WIB)
    return dt.strftime("%H:%M:%S WIB")

def utc_str(dt: datetime = None) -> str:
    if dt is None:
        dt = now_utc()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.strftime("%H:%M:%S UTC")

# ─── Dynamic Exchange Import ─────────────────────────────────────────────────
if cfg.IS_OKX:
    from exchange.okx import okx as exchange
    EXCHANGE_NAME = "OKX Demo" if cfg.IS_OKX_DEMO else "OKX Live"
else:
    from exchange.bybit import bybit as exchange
    EXCHANGE_NAME = "Bybit Testnet" if cfg.IS_TESTNET else "Bybit Live"


class VortexBot:

    def __init__(self):
        self.name        = "VΦrtex Bot"
        self.version     = "1.3b"
        self.running     = False
        self.start_time  = None
        self.pairs       = cfg.PAIRS
        self.open_trades = {}

        self._news_block_notified = False
        self._news_block_key      = None

        self._vwap_skip_notified = {}
        self._corr_skip_notified = {}

        logger.info(
            f"\n{'='*45}\n"
            f"  {self.name} v{self.version}\n"
            f"  Institutional Grade Trading Bot\n"
            f"  SMC + Fibonacci + BP + VWAP + Funding\n"
            f"  Correlation + Regime + BOS Freshness\n"
            f"  Exchange: {EXCHANGE_NAME}\n"
            f"{'='*45}"
        )

    # ═════════════════════════════════════════════════════════════════════════
    # STARTUP
    # ═════════════════════════════════════════════════════════════════════════

    def startup(self) -> bool:
        logger.info(
            f"🚀 Starting {self.name} v{self.version} "
            f"on {EXCHANGE_NAME}...\n"
            f"   WIB : {wib_str()} | UTC : {utc_str()}"
        )

        if not exchange.is_connected():
            logger.error(f"❌ Cannot connect to {EXCHANGE_NAME}!")
            return False
        logger.info(f"✅ {EXCHANGE_NAME} connected!")

        balance_data = exchange.get_balance()
        balance      = balance_data.get("free", 0)

        if balance <= 0:
            logger.warning(
                f"⚠️ Balance 0 di {EXCHANGE_NAME} — "
                f"pastikan akun demo ada saldo!"
            )

        risk_manager.set_starting_balance(balance)
        self._set_period_balances(balance)

        if cfg.IS_OKX and cfg.IS_OKX_DEMO:
            vb = risk_manager.get_virtual_balance()
            from exchange.okx import okx as _okx
            _okx._virtual_balance = vb
            logger.info(f"💰 Virtual balance synced: ${vb:.4f}")

        # FIX v1.3b: Detect regime saat startup supaya tidak UNKNOWN
        # setelah redeploy — sebelumnya hanya refresh di morning_briefing
        try:
            logger.info("🌍 Detecting market regime on startup...")
            ohlcv_1d = exchange.get_ohlcv(
                self.pairs[0], "1D", limit=200
            )
            if ohlcv_1d:
                df_1d  = indicators.ohlcv_to_df(ohlcv_1d)
                regime = risk_manager.detect_market_regime(df_1d)
                logger.info(
                    f"🌍 Startup regime: "
                    f"{regime.get('emoji','')} "
                    f"{regime.get('regime','?')} | "
                    f"boost=+{risk_manager.get_regime_score_boost()}"
                )
            else:
                logger.warning(
                    "⚠️ Tidak bisa fetch 1D data untuk regime — "
                    "akan coba lagi di morning briefing"
                )
        except Exception as e:
            logger.warning(f"⚠️ Startup regime detect error: {e}")

        tg_ok = telegram.test_connection()
        if not tg_ok:
            logger.warning(
                "⚠️ Telegram not connected — "
                "cek TOKEN & CHAT_ID di .env"
            )

        telegram.send_bot_started(balance)
        telegram.start_polling(bot_ref=self)
        logger.info("📱 Telegram commands active!")

        self.running    = True
        self.start_time = now_utc()

        cap_mode = cfg.get_capital_mode(balance)
        regime_d = risk_manager.get_cached_regime()
        logger.info(
            f"✅ {self.name} v{self.version} started!\n"
            f"   Exchange : {EXCHANGE_NAME}\n"
            f"   Balance  : ${balance:.4f}\n"
            f"   Mode     : {cap_mode['mode']}\n"
            f"   Pairs    : {', '.join(self.pairs)}\n"
            f"   Strategy : SMC+Stoch+BP+VWAP+Funding+Corr\n"
            f"   SL       : 2.0x ATR Dynamic\n"
            f"   Score    : min {cfg.MIN_CONFLUENCE_SCORE}/24\n"
            f"   Regime   : {regime_d.get('emoji','')} "
            f"{regime_d.get('regime','?')} "
            f"+{risk_manager.get_regime_score_boost()}\n"
            f"   VWAP     : {'ON' if cfg.VWAP_ENABLED else 'OFF'}\n"
            f"   Funding  : {'ON' if cfg.FUNDING_RATE_ENABLED else 'OFF'}\n"
            f"   London delay : 15 mnt | NY delay : 5 mnt\n"
            f"   Time WIB : {wib_str()}\n"
            f"   Time UTC : {utc_str()}"
        )
        return True

    def _set_period_balances(self, balance: float):
        if not db.get_state("weekly_starting_balance"):
            db.set_state("weekly_starting_balance", {
                "balance" : balance,
                "date_wib": now_wib().isoformat(),
                "date_utc": now_utc().isoformat(),
            })
        if not db.get_state("monthly_starting_balance"):
            db.set_state("monthly_starting_balance", {
                "balance" : balance,
                "date_wib": now_wib().isoformat(),
                "date_utc": now_utc().isoformat(),
            })

    # ═════════════════════════════════════════════════════════════════════════
    # NEWS BLOCK HELPER
    # ═════════════════════════════════════════════════════════════════════════

    def _check_and_notify_news_block(self) -> bool:
        try:
            block_info = news_filter.get_blocking_news()

            if block_info["is_blocking"]:
                current_key = frozenset(
                    n.get("title", "")
                    for n in block_info["news_list"]
                )
                if not self._news_block_notified or \
                        current_key != self._news_block_key:
                    telegram.send_news_block(
                        pairs      =self.pairs,
                        news_list  =block_info["news_list"],
                        safe_resume=block_info["safe_resume"],
                    )
                    self._news_block_notified = True
                    self._news_block_key      = current_key
                    logger.warning(
                        f"⚠️ NEWS BLOCK | "
                        f"resume: {block_info['safe_resume']} | "
                        f"{wib_str()}"
                    )
                return True
            else:
                if self._news_block_notified:
                    logger.info(
                        f"✅ News block selesai — "
                        f"trading aman | {wib_str()}"
                    )
                self._news_block_notified = False
                self._news_block_key      = None
                return False

        except Exception as e:
            logger.error(f"❌ News block check error: {e}")
            return False

    # ═════════════════════════════════════════════════════════════════════════
    # SCORE LOG HELPER
    # ═════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _build_score_log(pair: str,
                         ind: dict,
                         smc_result: dict,
                         bp_result: dict,
                         vwap_result: dict,
                         funding_result: dict,
                         corr_result: dict,
                         score: int,
                         effective_min: int) -> str:
        try:
            ema_ok   = "✅" if ind.get("ema_bullish") is not None else "❌"
            stoch_k  = ind.get("stoch_k", 50)
            stoch_d  = ind.get("stoch_d", 50)
            stoch_ok = (
                "✅" if (
                    ind.get("stoch_bullish") or
                    ind.get("stoch_bearish")
                ) else "⚠️" if (
                    ind.get("stoch_soft_bull") or
                    ind.get("stoch_soft_bear")
                ) else "❌"
            )
            vol_ok = "✅" if ind.get("volume_above_avg") else "❌"

            bos_exists = (
                smc_result.get("bos_4h") or
                smc_result.get("bos_1h")
            )
            bos_fresh = (
                smc_result.get("bos_4h_fresh") or
                smc_result.get("bos_1h_fresh") or
                smc_result.get("choch_4h_fresh") or
                smc_result.get("choch_1h_fresh")
            )
            bos_ok = (
                ("✅🔥" if bos_fresh else "✅⏳")
                if bos_exists else "❌"
            )

            ob_ok  = "✅" if smc_result.get("in_ob")  else "❌"
            fvg_ok = "✅" if smc_result.get("in_fvg") else "❌"

            mode_tag = {
                "BREAKOUT_RETEST": "🚀BO",
                "BREAKOUT_WAIT"  : "⏳BO",
                "PULLBACK"       : "↩️PB",
                "NONE"           : "—",
            }.get(bp_result.get("mode", "NONE"), "—")

            vwap_zone = vwap_result.get("zone", "?")
            vwap_sess = vwap_result.get("session", "?")
            vwap_ok   = (
                "✅" if vwap_result.get("score_bonus", 0) >= 2 else
                "⚠️" if vwap_result.get("score_bonus", 0) == 1 else
                "❌"
            )

            fund_rate = funding_result.get("rate", 0.0)
            fund_ok   = (
                "✅" if funding_result.get("score_bonus", 0) >= 1
                else "❌"
            )

            corr_trend  = corr_result.get("btc_trend", "?")
            corr_pass   = corr_result.get("pass", True)
            is_btc_pair = corr_result.get("is_btc_pair", False)
            corr_ok     = (
                "—"  if is_btc_pair else
                "✅" if corr_pass   else "❌"
            )

            return (
                f"{pair} | "
                f"EMA{ema_ok} "
                f"Stoch{stoch_ok}({stoch_k:.0f}/{stoch_d:.0f}) "
                f"Vol{vol_ok} | "
                f"BOS{bos_ok} OB{ob_ok} FVG{fvg_ok} | "
                f"Mode:{mode_tag} | "
                f"VWAP{vwap_ok}({vwap_zone}/{vwap_sess}) "
                f"Fund{fund_ok}({fund_rate:+.3f}%) "
                f"Corr{corr_ok}({corr_trend}) | "
                f"Score:{score}/{effective_min}"
            )

        except Exception as e:
            return f"{pair} | Score log error: {e}"

    # ═════════════════════════════════════════════════════════════════════════
    # MAIN ANALYSIS ENGINE
    # ═════════════════════════════════════════════════════════════════════════

    def analyze_pair(self, pair: str) -> dict:
        """Full analysis untuk 1 pair — 10 steps"""
        try:
            logger.info(f"🔍 Analyzing {pair}...")

            # ── STEP 1: SESSION FILTERS ──────────────────────────────────────
            session_info = session_filter.get_session_info()

            # FIX v1.3b: should_avoid tidak lagi mencakup in_delay
            # in_delay dihandle terpisah — bot tetap analisis pair
            if session_info.get("should_avoid"):
                reason = session_info.get("avoid_reason", "")
                logger.info(f"⏭️ Skip {pair}: {reason}")
                return {}

            killzone = session_filter.is_killzone()
            if not killzone.get("in_killzone"):
                if killzone.get("in_delay"):
                    logger.info(
                        f"⏳ {pair}: {killzone.get('delay_reason')} "
                        f"— analisis tetap, entry tunggu delay selesai"
                    )
                else:
                    next_s = killzone.get("next_session", {})
                    logger.info(
                        f"⏭️ {pair}: Outside killzone | "
                        f"Next: {next_s.get('name', 'N/A')} "
                        f"in {next_s.get('minutes_away', '?')} min"
                    )
                    return {}

            news_blocked = self._check_and_notify_news_block()
            if news_blocked:
                logger.warning(f"⚠️ Skip {pair}: News block aktif")
                return {}

            news_status = news_filter.is_safe_to_trade()

            # ── STEP 2: FETCH DATA ───────────────────────────────────────────
            ohlcv_4h  = exchange.get_ohlcv(pair, cfg.TF_BIAS,  limit=200)
            ohlcv_1h  = exchange.get_ohlcv(pair, cfg.TF_SETUP, limit=200)
            ohlcv_15m = exchange.get_ohlcv(pair, cfg.TF_ENTRY, limit=200)
            ohlcv_1d  = exchange.get_ohlcv(pair, "1D",         limit=200)

            if not all([ohlcv_4h, ohlcv_1h, ohlcv_15m]):
                logger.warning(f"⚠️ Incomplete data for {pair}")
                return {}

            df_4h  = indicators.ohlcv_to_df(ohlcv_4h)
            df_1h  = indicators.ohlcv_to_df(ohlcv_1h)
            df_15m = indicators.ohlcv_to_df(ohlcv_15m)
            df_1d  = (
                indicators.ohlcv_to_df(ohlcv_1d)
                if ohlcv_1d else df_4h
            )

            if any(df.empty for df in [df_4h, df_1h, df_15m]):
                logger.warning(f"⚠️ Empty DataFrame for {pair}")
                return {}

            # ── STEP 3: INDICATORS ───────────────────────────────────────────
            ind_15m = indicators.calculate_all(df_15m)
            ind_1h  = indicators.calculate_all(df_1h)

            if not ind_15m or not ind_1h:
                return {}

            # ── STEP 4: SMC ──────────────────────────────────────────────────
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

            # ── STEP 5: FIBONACCI ────────────────────────────────────────────
            current_price = float(df_15m["close"].iloc[-1])
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

            # ── STEP 6: BREAKOUT & PULLBACK ──────────────────────────────────
            vol_data_15m = {
                "ratio"    : ind_15m.get("volume_ratio", 0),
                "above_avg": ind_15m.get("volume_above_avg", False),
            }

            bp_result = breakout_pullback.analyze(
                df         =df_15m,
                direction  =direction,
                volume_data=vol_data_15m,
                obs        =smc_result.get("order_blocks", []),
                fvgs       =smc_result.get("fvgs", []),
                fib_levels =fib_result.get("fib_levels"),
            )

            bp_mode     = bp_result.get("mode", "NONE")
            bp_breakout = bp_result.get("breakout", {})
            bp_pullback = bp_result.get("pullback", {})

            if bp_mode != "NONE":
                logger.info(
                    f"📐 {pair} BP: {bp_mode} | dir={direction}"
                )

            # ── STEP 7: VWAP ANALYSIS ────────────────────────────────────────
            vwap_result = vwap_analyzer.analyze(df_1h, direction)

            if not vwap_result.get("pass", True):
                logger.info(
                    f"⏭️ {pair}: VWAP block — "
                    f"{vwap_result.get('reason')}"
                )
                now_ts     = time.time()
                last_notif = self._vwap_skip_notified.get(pair, 0)
                if (vwap_result.get("valid") and
                        now_ts - last_notif > 1800):
                    telegram.send_vwap_filter_skip(
                        pair      =pair,
                        direction =direction,
                        vwap_side =vwap_result.get("side", ""),
                        price     =current_price,
                        vwap      =vwap_result.get("vwap", 0),
                    )
                    self._vwap_skip_notified[pair] = now_ts
                return {}

            # ── STEP 8: FUNDING RATE ─────────────────────────────────────────
            funding_result = funding_filter.analyze(pair, direction)

            if not funding_result.get("pass", True):
                logger.info(
                    f"⏭️ {pair}: Funding block — "
                    f"{funding_result.get('reason')}"
                )
                telegram.send_funding_filter_skip(
                    pair        =pair,
                    direction   =direction,
                    funding_rate=funding_result.get("rate", 0),
                )
                return {}

            # ── STEP 9: CORRELATION FILTER ───────────────────────────────────
            df_btc_corr = None
            if "BTC" not in pair.upper():
                try:
                    ohlcv_btc = exchange.get_ohlcv(
                        "BTC-USDT-SWAP", cfg.TF_BIAS, limit=50
                    )
                    if ohlcv_btc:
                        df_btc_corr = indicators.ohlcv_to_df(ohlcv_btc)
                except Exception:
                    pass

            corr_result = correlation_filter.analyze(
                pair      =pair,
                direction =direction,
                df_btc_4h =(
                    df_btc_corr
                    if df_btc_corr is not None
                    else df_4h
                ),
            )

            if not corr_result.get("pass", True):
                logger.info(
                    f"⏭️ {pair}: Correlation block — "
                    f"{corr_result.get('reason')}"
                )
                now_ts     = time.time()
                last_notif = self._corr_skip_notified.get(pair, 0)
                if now_ts - last_notif > 1800:
                    telegram.send(
                        f"⚠️ <b>CORRELATION BLOCK</b>\n"
                        f"Pair : {pair}\n"
                        f"Dir  : {direction}\n"
                        f"BTC  : "
                        f"{corr_result.get('btc_trend')} "
                        f"{corr_result.get('btc_strength', '')}\n"
                        f"{corr_result.get('reason', '')}"
                    )
                    self._corr_skip_notified[pair] = now_ts
                return {}

            # ── STEP 10: CONFLUENCE SCORING ──────────────────────────────────
            score_result = confluence_scorer.calculate(
                direction          =direction,
                indicators         =ind_15m,
                smc_analysis       =smc_result,
                fib_analysis       =fib_result,
                session_info       =session_info,
                news_status        =news_status,
                breakout_info      =bp_breakout,
                pullback_info      =bp_pullback,
                vwap_result        =vwap_result,
                funding_result     =funding_result,
                correlation_result =corr_result,
            )

            score     = score_result.get("score", 0)
            is_valid  = score_result.get("is_valid", False)
            grade     = score_result.get("grade", "F")
            hard_fail = score_result.get("hard_fail", False)

            regime_boost  = risk_manager.get_regime_score_boost()
            effective_min = cfg.MIN_CONFLUENCE_SCORE + regime_boost
            regime_valid  = score >= effective_min and not hard_fail

            score_log = self._build_score_log(
                pair           =pair,
                ind            =ind_15m,
                smc_result     =smc_result,
                bp_result      =bp_result,
                vwap_result    =vwap_result,
                funding_result =funding_result,
                corr_result    =corr_result,
                score          =score,
                effective_min  =effective_min,
            )
            logger.info(f"📊 {score_log}")

            if not regime_valid:
                if hard_fail:
                    reason = "HARD BLOCK"
                elif regime_boost > 0 and is_valid and not regime_valid:
                    regime_data = risk_manager.get_cached_regime()
                    reason = (
                        f"Regime boost: "
                        f"{regime_data.get('regime')} "
                        f"+{regime_boost} → "
                        f"need {effective_min}, got {score}"
                    )
                else:
                    reason = (
                        f"score {score}/{effective_min} "
                        f"below threshold"
                    )
                logger.info(
                    f"⏭️ {pair}: {reason} ({grade}) "
                    f"(F (Skip))"
                )
                return {}

            # ── BUILD SIGNAL ─────────────────────────────────────────────────
            tp_sl = fib_result.get("tp_sl", {})
            if not tp_sl:
                return {}

            rr2 = tp_sl.get("rr2", 0)
            if rr2 < cfg.MIN_RR:
                return {}

            signal = {
                "pair"             : pair,
                "direction"        : direction,
                "confluence_score" : score,
                "grade"            : grade,
                "entry_price"      : current_price,
                "sl_price"         : tp_sl.get("sl"),
                "tp1_price"        : tp_sl.get("tp1"),
                "tp2_price"        : tp_sl.get("tp2"),
                "tp3_price"        : tp_sl.get("tp3"),
                "sl_pct"           : tp_sl.get("sl_pct", 0),
                "rr_ratio"         : rr2,
                "fib_level"        : fib_result.get("fib_level"),
                "fib_strength"     : fib_result.get("fib_strength"),
                "session"          : session_info.get(
                    "session_name", "Unknown"
                ),
                "killzone"         : killzone.get("session", ""),
                "stoch_k"          : ind_15m.get("stoch_k", 0),
                "stoch_d"          : ind_15m.get("stoch_d", 0),
                "stoch_zone"       : (
                    "oversold"   if ind_15m.get("stoch_oversold")   else
                    "overbought" if ind_15m.get("stoch_overbought")  else
                    "neutral"
                ),
                "atr_value"        : atr_val,
                "sl_type"          : tp_sl.get("sl_type", "ATR 2.0x"),
                "volume_ratio"     : ind_15m.get("volume_ratio", 0),
                "candle_pattern"   : ind_15m.get("candle_pattern", []),
                "candle_direction" : ind_15m.get("candle_direction"),
                "structure_4h"     : smc_result.get("structure_4h"),
                "bos_detected"     : (
                    smc_result.get("bos_4h") or
                    smc_result.get("bos_1h", False)
                ),
                "bos_fresh"        : score_result.get("bos_fresh", False),
                "choch_detected"   : (
                    smc_result.get("choch_4h") or
                    smc_result.get("choch_1h", False)
                ),
                "ob_detected"      : smc_result.get("in_ob", False),
                "ob_type"          : smc_result.get("ob_type"),
                "fvg_detected"     : smc_result.get("in_fvg", False),
                "liquidity_swept"  : smc_result.get(
                    "liquidity_swept", False
                ),
                "ideal_zone"       : smc_result.get("ideal_zone", False),
                "bp_mode"          : bp_mode,
                "breakout_type"    : bp_breakout.get("type"),
                "breakout_level"   : bp_breakout.get("level"),
                "pullback_zone"    : bp_pullback.get("zone"),
                "pullback_strength": bp_pullback.get("strength"),
                "vwap_value"       : vwap_result.get("vwap"),
                "vwap_side"        : vwap_result.get("side"),
                "vwap_zone"        : vwap_result.get("zone"),
                "vwap_diff_pct"    : vwap_result.get("diff_pct", 0),
                "vwap_session"     : vwap_result.get("session"),
                "funding_rate"     : funding_result.get("rate", 0.0),
                "funding_status"   : funding_result.get("status"),
                "btc_trend"        : corr_result.get("btc_trend"),
                "btc_strength"     : corr_result.get("btc_strength"),
                "regime"           : risk_manager.get_cached_regime().get(
                    "regime"
                ),
                "regime_boost"     : regime_boost,
                "effective_min_score": effective_min,
                "score_breakdown"  : score_result.get("breakdown", {}),
                "top_reasons"      : score_result.get("reasons", [])[:8],
                "tf_bias"          : cfg.TF_BIAS,
                "tf_setup"         : cfg.TF_SETUP,
                "tf_entry"         : cfg.TF_ENTRY,
                "detected_at_wib"  : now_wib().isoformat(),
                "detected_at_utc"  : now_utc().isoformat(),
                "detected_at"      : now_wib().isoformat(),
                "exchange"         : EXCHANGE_NAME,
            }

            db.save_signal(signal)

            if not db.is_signal_recent(pair, direction):
                telegram.send_signal_detected(signal)
                db.mark_signal_notified(pair, direction)

            logger.info(
                f"🎯 VALID SIGNAL!\n"
                f"   {pair} {direction} "
                f"Score:{score}/{effective_min} ({grade}) "
                f"RR:1:{rr2:.1f} "
                f"SL:{tp_sl.get('sl_pct', 0):.2f}% "
                f"BP:{bp_mode} "
                f"VWAP:{vwap_result.get('zone','?')}/"
                f"{vwap_result.get('session','?')} "
                f"BTC:{corr_result.get('btc_trend','?')} "
                f"Regime:+{regime_boost} | "
                f"{wib_str()}"
            )

            return signal

        except Exception as e:
            logger.error(f"❌ Analyze {pair} error: {e}")
            return {}

    # ═════════════════════════════════════════════════════════════════════════
    # TRADE EXECUTION
    # ═════════════════════════════════════════════════════════════════════════

    def execute_trade(self, signal: dict):
        try:
            pair      = signal.get("pair")
            direction = signal.get("direction")
            entry     = signal.get("entry_price")
            sl        = signal.get("sl_price")
            tp1       = signal.get("tp1_price")
            tp2       = signal.get("tp2_price")
            tp3       = signal.get("tp3_price")
            bp_mode   = signal.get("bp_mode", "NONE")

            if bp_mode == "BREAKOUT_WAIT":
                logger.info(
                    f"⏳ {pair}: Breakout detected — "
                    f"waiting for retest confirmation"
                )
                return

            # FIX v1.3b: skip execute jika masih dalam delay window
            killzone = session_filter.is_killzone()
            if not killzone.get("in_killzone") and killzone.get("in_delay"):
                logger.info(
                    f"⏳ {pair}: {killzone.get('delay_reason')} "
                    f"— skip execute, analisis sudah selesai"
                )
                return

            cooldown = db.is_pair_in_cooldown(pair, direction)
            if cooldown.get("in_cooldown"):
                logger.info(
                    f"⏭️ {pair} {direction} SL cooldown | "
                    f"Sisa: {cooldown.get('minutes_left')} mnt"
                )
                return

            balance    = exchange.get_balance().get("free", 0)
            risk_check = risk_manager.full_risk_check(balance)

            if not risk_check.get("safe_to_trade"):
                logger.warning(
                    f"⚠️ Risk check failed: "
                    f"{risk_check.get('reason')}"
                )
                return

            cap_mode   = cfg.get_capital_mode(balance)
            max_trades = cap_mode.get("max_open_trades", 1)
            if len(self.open_trades) >= max_trades:
                logger.info(
                    f"⏭️ Max trades ({max_trades}) reached"
                )
                return

            position = risk_manager.calculate_position(
                balance    =balance,
                entry_price=entry,
                sl_price   =sl,
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

            exchange.set_leverage(pair, leverage)
            side  = "buy" if direction == "BUY" else "sell"
            order = exchange.place_market_order(pair, side, quantity)
            if not order:
                logger.error(f"❌ Order failed: {pair}")
                return

            exchange.place_stop_loss(pair, side, quantity, sl)
            tp_qty = round(quantity * 0.4, 6)
            exchange.place_take_profit(pair, side, tp_qty, tp2)

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
                "confluence_score": signal.get("confluence_score"),
                "mode"            : mode,
                "position_usdt"   : position.get("position_usdt", 0),
                "risk_amount"     : risk_amt,
                "bp_mode"         : bp_mode,
                "sl_pct"          : signal.get("sl_pct", 0),
                "vwap_zone"       : signal.get("vwap_zone"),
                "funding_rate"    : signal.get("funding_rate", 0),
                "btc_trend"       : signal.get("btc_trend"),
                "regime"          : signal.get("regime"),
                "regime_boost"    : signal.get("regime_boost", 0),
            }
            trade_id = db.save_trade(trade_data)

            self.open_trades[trade_id] = {
                **trade_data,
                "trade_id"          : trade_id,
                "open_time"         : now_utc(),
                "open_time_wib"     : now_wib(),
                "tp1_closed"        : False,
                "quantity_remaining": quantity,
                "original_qty"      : quantity,
            }

            entry_reason = journal.generate_entry_reason({
                **signal,
                "entry_price"    : entry,
                "sl_price"       : sl,
                "tp1_price"      : tp1,
                "tp2_price"      : tp2,
                "tp3_price"      : tp3,
                "rr_ratio"       : signal.get("rr_ratio", 3),
                "score_breakdown": signal.get("score_breakdown", {}),
            })
            journal.save_trade_journal(trade_id, entry_reason)

            if cfg.IS_OKX and cfg.IS_OKX_DEMO:
                risk_manager.reserve_balance(
                    position.get("risk_amount", 0)
                )

            journal.send_entry_journal_to_telegram(
                trade_id, signal, entry_reason
            )
            telegram.send_trade_opened({
                **trade_data,
                "confluence_score": signal.get("confluence_score"),
            })

            logger.info(
                f"✅ TRADE #{trade_id} | "
                f"{pair} {direction} | "
                f"qty={quantity} lev={leverage}x | "
                f"entry={entry:.4f} sl={sl:.4f} "
                f"({signal.get('sl_pct', 0):.2f}%) | "
                f"BP:{bp_mode} VWAP:{signal.get('vwap_zone','?')} "
                f"BTC:{signal.get('btc_trend','?')} "
                f"Regime:+{signal.get('regime_boost', 0)} | "
                f"{wib_str()}"
            )

        except Exception as e:
            logger.error(f"❌ Execute trade error: {e}")

    # ═════════════════════════════════════════════════════════════════════════
    # TRADE MONITORING
    # ═════════════════════════════════════════════════════════════════════════

    def monitor_trades(self):
        if not self.open_trades:
            return

        try:
            for trade_id, trade in list(self.open_trades.items()):
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

                if tp1_closed and atr > 0:
                    self._handle_trailing_stop(
                        trade_id, trade, current, atr
                    )

                sl_hit = (
                    (direction == "BUY"  and current <= sl) or
                    (direction == "SELL" and current >= sl)
                )
                if sl_hit:
                    self._close_trade(trade_id, trade, current, "SL")

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

            telegram.send_partial_close(trade, tp_hit, close_pct, pnl)
            logger.info(
                f"🎯 Partial: {pair} {tp_hit} "
                f"pnl=+{pnl:.4f} | {wib_str()}"
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
                entry    =entry,
                current  =current,
                sl       =sl,
                direction=direction,
                atr      =atr,
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
                    f"🔄 Trail {pair}: "
                    f"SL {old_sl:.4f}→{new_sl:.4f} | {wib_str()}"
                )
        except Exception as e:
            logger.error(f"❌ Trailing stop error: {e}")

    def _close_trade(self, trade_id, trade, close_price, reason):
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
                (now_utc() - open_time).seconds / 60
            ) if isinstance(open_time, datetime) else 0

            sl   = trade.get("sl_price", entry)
            risk = abs(entry - sl)
            rr   = (
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
                "close_time_wib"  : now_wib().isoformat(),
                "close_time_utc"  : now_utc().isoformat(),
            }
            db.close_trade(trade_id, close_data)

            if cfg.IS_OKX and cfg.IS_OKX_DEMO:
                new_bal = risk_manager\
                    .update_virtual_balance_after_trade(pnl)
                risk_manager.release_balance(
                    trade.get("risk_amount", 0)
                )
                from exchange.okx import okx as _okx
                _okx._virtual_balance     = new_bal
                close_data["new_balance"] = new_bal
                new_balance               = new_bal
                logger.info(
                    f"💰 Virtual balance: ${new_bal:.4f} "
                    f"(pnl={'+' if pnl>=0 else ''}{pnl:.4f})"
                )

            if reason == "SL":
                db.set_sl_cooldown(pair, direction, cooldown_hours=2)
                logger.warning(
                    f"🚫 SL cooldown 2j: {pair} {direction}"
                )

            close_text = journal.generate_close_reason(
                trade, close_data
            )
            journal.save_trade_journal(
                trade_id, "→ See entry journal", close_text
            )
            journal.send_close_journal_to_telegram(
                trade_id, close_text, pnl
            )

            risk_manager.record_trade_result(pnl > 0)
            telegram.send_trade_closed(
                trade,
                {**close_data, "new_balance": new_balance}
            )

            if pnl < 0:
                try:
                    evaluator.analyze_loss_pattern()
                except Exception as le:
                    logger.debug(f"Learning trigger: {le}")

            if trade_id in self.open_trades:
                del self.open_trades[trade_id]

            result = "✅ PROFIT" if pnl > 0 else "❌ LOSS"
            logger.info(
                f"{result} #{trade_id} | {pair} {direction} | "
                f"pnl={'+' if pnl>0 else ''}{pnl:.4f} | "
                f"rr=1:{rr:.2f} | {reason} | {wib_str()}"
            )

        except Exception as e:
            logger.error(f"❌ Close trade error: {e}")

    # ═════════════════════════════════════════════════════════════════════════
    # SCHEDULED TASKS
    # ═════════════════════════════════════════════════════════════════════════

    def setup_scheduled_tasks(self):
        schedule.every().day.at("00:00").do(self._morning_briefing)
        schedule.every().day.at("10:00").do(self._london_session_summary)
        schedule.every().day.at("15:00").do(self._daily_summary)
        schedule.every().day.at("16:00").do(self._ny_session_summary)
        schedule.every(6).hours.do(self._health_check)
        schedule.every().sunday.at("07:00").do(self._weekly_summary)
        schedule.every().sunday.at("08:00").do(self._run_weekly_evaluation)
        schedule.every().sunday.at("17:01").do(self._reset_weekly_balance)
        schedule.every().day.at("17:01").do(self._check_monthly_reset)

        logger.info(
            "📅 Scheduled tasks configured!\n"
            "   Morning   : 00:00 WIB\n"
            "   London    : 10:00 WIB\n"
            "   Daily sum : 15:00 WIB\n"
            "   NY sum    : 16:00 WIB\n"
            "   Weekly    : Minggu 07:00 WIB"
        )

    def _morning_briefing(self):
        try:
            balance  = exchange.get_balance().get("free", 0)
            upcoming = news_filter.get_upcoming_news(hours_ahead=12)
            ohlcv_1d = exchange.get_ohlcv(
                self.pairs[0], "1D", limit=200
            )
            df_1d  = indicators.ohlcv_to_df(ohlcv_1d)
            regime = risk_manager.detect_market_regime(df_1d)
            telegram.send_morning_briefing(
                balance, upcoming, regime.get("regime", "UNKNOWN")
            )
            logger.info(f"☀️ Morning briefing | {wib_str()}")
        except Exception as e:
            logger.error(f"❌ Morning briefing error: {e}")

    def _daily_summary(self):
        try:
            trades    = db.get_today_trades()
            balance   = exchange.get_balance().get("free", 0)
            wins      = sum(1 for t in trades if t.get("pnl", 0) > 0)
            losses    = len(trades) - wins
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
            logger.info(f"📊 Daily summary | {wib_str()}")
        except Exception as e:
            logger.error(f"❌ Daily summary error: {e}")

    def _health_check(self):
        try:
            uptime = (
                (now_utc() - self.start_time).seconds / 3600
                if self.start_time else 0
            )
            balance = exchange.get_balance().get("free", 0)
            telegram.send_health_check(
                uptime, balance, len(self.open_trades)
            )
            logger.info(
                f"💚 Health: {uptime:.1f}h | "
                f"{wib_str()} | {utc_str()}"
            )
        except Exception as e:
            logger.error(f"❌ Health check error: {e}")

    def _weekly_summary(self):
        try:
            stats            = db.get_overall_stats()
            stats["balance"] = exchange.get_balance().get("free", 0)
            telegram.send_weekly_summary(stats)
            logger.info(f"📈 Weekly summary | {wib_str()}")
        except Exception as e:
            logger.error(f"❌ Weekly summary error: {e}")

    def _run_weekly_evaluation(self):
        try:
            logger.info(f"🧠 Running weekly evaluation... | {wib_str()}")
            report  = evaluator.run_weekly_evaluation()
            summary = "\n".join(report.split("\n")[:25])
            telegram.send(
                f"🧠 <b>WEEKLY EVALUATION</b>\n"
                f"<pre>{summary[:3500]}</pre>"
            )
            logger.info(f"✅ Weekly eval sent | {wib_str()}")
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
            logger.info(f"📋 London summary | {wib_str()}")
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
            logger.info(f"📋 NY summary | {wib_str()}")
        except Exception as e:
            logger.error(f"❌ NY summary error: {e}")

    def _reset_weekly_balance(self):
        try:
            balance = exchange.get_balance().get("free", 0)
            db.set_state("weekly_starting_balance", {
                "balance" : balance,
                "date_wib": now_wib().isoformat(),
                "date_utc": now_utc().isoformat(),
            })
            logger.info(
                f"📅 Weekly reset: ${balance:.4f} | {wib_str()}"
            )
        except Exception as e:
            logger.error(f"❌ Weekly reset error: {e}")

    def _check_monthly_reset(self):
        try:
            if now_wib().day == 1:
                balance = exchange.get_balance().get("free", 0)
                db.set_state("monthly_starting_balance", {
                    "balance" : balance,
                    "date_wib": now_wib().isoformat(),
                    "date_utc": now_utc().isoformat(),
                })
                logger.info(
                    f"📅 Monthly reset: "
                    f"${balance:.4f} | {wib_str()}"
                )
        except Exception as e:
            logger.error(f"❌ Monthly reset error: {e}")

    # ═════════════════════════════════════════════════════════════════════════
    # MAIN LOOP
    # ═════════════════════════════════════════════════════════════════════════

    def run(self):
        self.setup_scheduled_tasks()

        logger.info(
            f"🔄 Main loop started!\n"
            f"   Exchange : {EXCHANGE_NAME}\n"
            f"   Pairs    : {', '.join(self.pairs)}\n"
            f"   Interval : 60s\n"
            f"   Strategy : SMC+Stoch+BP+VWAP+Fund+Corr\n"
            f"   Score    : min {cfg.MIN_CONFLUENCE_SCORE}/24\n"
            f"   SL       : 2.0x ATR Dynamic\n"
            f"   Delays   : London+15m NY+5m Asia skip\n"
            f"   API      : port 8080\n"
            f"   Time WIB : {wib_str()}\n"
            f"   Time UTC : {utc_str()}"
        )

        while self.running:
            try:
                schedule.run_pending()
                telegram.check_heartbeat()

                pause = risk_manager.is_bot_paused()
                if pause.get("paused"):
                    logger.info(
                        f"⏸️ Bot paused | "
                        f"{pause.get('reason')} | "
                        f"Resume: {pause.get('time_left')} | "
                        f"{wib_str()}"
                    )
                    time.sleep(300)
                    continue

                try:
                    kz_event = session_filter.check_killzone_transition()
                    if kz_event.get("event"):
                        delay = kz_event.get("entry_delay", 0)
                        telegram.send_killzone_alert(
                            event       =kz_event["event"],
                            session     =kz_event["session"],
                            wib_time    =kz_event["wib_time"],
                            minutes_left=kz_event.get("minutes_left", 0),
                        )
                        if delay > 0 and kz_event["event"] == "started":
                            logger.info(
                                f"⏳ {kz_event['session']} started "
                                f"— entry delay {delay} mnt | "
                                f"{kz_event['wib_time']}"
                            )
                        else:
                            logger.info(
                                f"🔔 Killzone {kz_event['event']}: "
                                f"{kz_event['session']} | "
                                f"{kz_event['wib_time']}"
                            )
                except Exception as e:
                    logger.error(f"❌ Killzone transition error: {e}")

                self.monitor_trades()

                signals_found = 0
                for pair in self.pairs:
                    signal = self.analyze_pair(pair)
                    if signal:
                        signals_found += 1
                        self.execute_trade(signal)
                    time.sleep(2)

                telegram.update_last_scan()

                regime_data  = risk_manager.get_cached_regime()
                regime_boost = risk_manager.get_regime_score_boost()
                regime_str   = (
                    f"{regime_data.get('emoji', '')} "
                    f"{regime_data.get('regime', 'UNK')} "
                    f"+{regime_boost}"
                    if regime_data.get("regime") not in ("UNKNOWN", None)
                    else "?"
                )

                logger.info(
                    f"✅ Scan done | "
                    f"{now_wib().strftime('%H:%M')} WIB | "
                    f"{now_utc().strftime('%H:%M')} UTC | "
                    f"Signals:{signals_found} | "
                    f"Trades:{len(self.open_trades)} | "
                    f"Regime:{regime_str}"
                )

                time.sleep(60)

            except KeyboardInterrupt:
                logger.info("🛑 Bot stopped (Ctrl+C)")
                self.running = False
                telegram.send_bot_stopped("Manual stop (Ctrl+C)")
                break

            except Exception as e:
                logger.error(f"❌ Main loop error: {e}")
                time.sleep(30)

        logger.info("👋 VΦrtex Bot shutdown complete!")


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════╗
║         VΦrtex Bot v1.3b                 ║
║   Institutional Grade Trading Bot        ║
║   SMC + Fibonacci + BP + VWAP            ║
║   Funding + Correlation + Regime         ║
║   BOS Freshness | ATR 2.0x | Score /24  ║
║   Mini App API  : port 8080              ║
╚══════════════════════════════════════════╝
    """)

    bot = VortexBot()

    # Startup bot (connect exchange, detect regime, init telegram)
    if not bot.startup():
        logger.error("❌ Startup failed!")
        exit(1)

    # Hubungkan bot ke API server supaya bisa akses open_trades, dll
    set_bot_ref(bot)

    # Jalankan API server di background thread (tidak ganggu bot loop)
    api_thread = threading.Thread(
        target=start_api_server,
        kwargs={"bot_ref": bot, "host": "0.0.0.0", "port": 8080},
        daemon=True,
        name="VortexAPI"
    )
    api_thread.start()
    logger.info("🌐 Mini App API server started on port 8080")

    # Bot main loop — blocking sampai bot.running = False
    bot.run()
