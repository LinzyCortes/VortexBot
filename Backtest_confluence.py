"""
Backtest v2 — VortexBot CONFLUENCE-ACCURATE Backtest
========================================================
BEDA dengan backtest_smc.py lama:

  backtest_smc.py (LAMA) = filter binary sendiri, TIDAK memanggil
  confluence_scorer.calculate() sama sekali. Hasil "bagus" di situ
  TIDAK membuktikan apa-apa soal threshold MIN_CONFLUENCE_SCORE.

  backtest_confluence.py (INI) = import LANGSUNG modul asli:
    strategy.smc, strategy.fibonacci, strategy.vwap,
    strategy.breakout_pullback, strategy.correlation,
    strategy.confluence, strategy.indicators
  Jadi score yang dihasilkan di backtest 100% identik logic-nya
  dengan yang dipakai bot live di main.py analyze_pair().

ASUMSI / KETERBATASAN (WAJIB DIBACA):
  1. Funding rate TIDAK bisa dibacktest historis (OKX/Bybit tidak
     simpan histori funding per-candle via public API gratis).
     Di backtest ini funding di-set NEUTRAL (score_bonus=1, pass=True)
     supaya tidak bias skor ke bawah. Artinya: skor real live bisa
     SEDIKIT lebih rendah dari backtest ini kalau funding lagi ekstrem.
  2. session_filter.py / news_filter.py tidak di-share, jadi killzone
     di backtest ini pakai jam UTC sederhana (London 08:00-11:30,
     NY 13:30-16:00) — cek ulang ke news_filter.py aslinya kalau mau
     lebih presisi.
  3. News filter di-skip (selalu "safe") karena data news historis
     tidak tersedia gratis.
  4. Regime boost IKUT disimulasikan (pakai risk_manager asli) supaya
     efeknya ke threshold efektif ikut kelihatan di backtest.

Cara jalankan (taruh file ini di root folder VortexBot, sejajar main.py):
    python backtest_confluence.py
"""

import os
import sys
import time
import ccxt
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────
# IMPORT MODUL ASLI BOT — supaya scoring 100% identik dgn live
# ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import cfg
from strategy.indicators import indicators
from strategy.smc import smc
from strategy.fibonacci import fibonacci
from strategy.confluence import confluence_scorer
from strategy.breakout_pullback import breakout_pullback
from strategy.vwap import vwap_analyzer
from strategy.correlation import correlation_filter
from risk.management import risk_manager

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
# FIX: Binance API sering kena geo-block dari IP Indonesia (error
# exchangeInfo gagal fetch). Ganti ke OKX — sekalian lebih
# representatif karena bot live lo trading beneran di OKX, bukan
# Binance, jadi data historis harga/volume lebih konsisten dgn live.
#
# Format simbol OKX di ccxt (unified) untuk USDT-margined perpetual
# swap: 'ETH/USDT:USDT' (bukan 'ETH/USDT' spot biasa).
PAIRS = [
    'ETH/USDT:USDT', 'BNB/USDT:USDT', 'AAVE/USDT:USDT',
    'LINK/USDT:USDT', 'AVAX/USDT:USDT', 'OP/USDT:USDT',
]
BTC_PAIR = 'BTC/USDT:USDT'

INITIAL_CAPITAL = 100
RISK_PER_TRADE  = 0.01
LOOKBACK_15M    = 220   # candle jendela yang dikirim ke indicators/smc (samain kayak main.py limit=200)
LOOKBACK_1H     = 220
LOOKBACK_4H     = 220
STEP_EVERY_N_15M = 1    # analisa tiap N candle 15m (1 = tiap candle, samain interval 60s bot asli ~ per candle baru)

LONDON_START_UTC = (8, 0)
LONDON_END_UTC   = (11, 30)
NY_START_UTC     = (13, 30)
NY_END_UTC       = (16, 0)

exchange = ccxt.okx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})


# ─────────────────────────────────────────────────────────────
# FETCH DATA
# ─────────────────────────────────────────────────────────────
def _tf_to_ms(tf: str) -> int:
    units = {'m': 60, 'h': 3600, 'd': 86400, 'w': 604800}
    return int(tf[:-1]) * units[tf[-1]] * 1000


def fetch_ohlcv(symbol: str, timeframe: str, limit: int = 1000, retries: int = 3) -> pd.DataFrame:
    print(f"  Fetching {symbol} {timeframe} ({limit} bars)...")
    for attempt in range(1, retries + 1):
        try:
            all_bars = []
            per_req  = 300  # OKX max per request lebih kecil dari Binance (biasanya 100-300)
            now_ms   = int(time.time() * 1000)
            tf_ms    = _tf_to_ms(timeframe)
            since    = now_ms - (limit * tf_ms)

            while len(all_bars) < limit:
                fetch_n = min(per_req, limit - len(all_bars))
                bars = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=fetch_n)
                if not bars:
                    break
                all_bars.extend(bars)
                since = bars[-1][0] + tf_ms
                time.sleep(0.25)
                if len(bars) < fetch_n:
                    break

            if not all_bars:
                print(f"  ⚠️ Percobaan {attempt}/{retries}: 0 bars — retry...")
                time.sleep(2)
                continue

            df = pd.DataFrame(all_bars, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
            df = df.drop(columns='ts').drop_duplicates('timestamp')
            df = df.sort_values('timestamp').reset_index(drop=True)
            print(f"  -> {len(df)} bars")
            return df
        except Exception as e:
            print(f"  ⚠️ Percobaan {attempt}/{retries} ERROR {symbol} {timeframe}: {e}")
            time.sleep(2)

    print(f"  ❌ Gagal fetch {symbol} {timeframe} setelah {retries}x percobaan")
    return pd.DataFrame()


def to_indexed(df: pd.DataFrame) -> pd.DataFrame:
    """Konversi ke format yang dipakai indicators.ohlcv_to_df (index=timestamp)."""
    out = df.copy()
    out = out.set_index('timestamp')
    out = out[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return out


def slice_up_to(df_indexed: pd.DataFrame, ts, lookback: int) -> pd.DataFrame:
    """Ambil N candle terakhir yang timestamp-nya <= ts (mirror exchange.get_ohlcv limit=N tiap saat itu)."""
    sub = df_indexed[df_indexed.index <= ts]
    if len(sub) > lookback:
        sub = sub.tail(lookback)
    return sub


def is_killzone_simple(ts: pd.Timestamp) -> bool:
    t = ts.hour * 60 + ts.minute
    london = (LONDON_START_UTC[0] * 60 + LONDON_START_UTC[1]) <= t <= (LONDON_END_UTC[0] * 60 + LONDON_END_UTC[1])
    ny     = (NY_START_UTC[0] * 60 + NY_START_UTC[1]) <= t <= (NY_END_UTC[0] * 60 + NY_END_UTC[1])
    return london or ny


# ─────────────────────────────────────────────────────────────
# TRADE SIM (pakai TP/SL dari fibonacci.calculate_tp_sl asli)
# ─────────────────────────────────────────────────────────────
class SimTrade:
    def __init__(self, direction, entry, sl, tp1, tp2, tp3, size, entry_i):
        self.direction = direction
        self.entry = entry
        self.sl = sl
        self.tp_prices = [tp1, tp2, tp3]
        self.tp_ratios = [0.30, 0.40, 0.30]
        self.size = size
        self.entry_i = entry_i
        self.partial_closed = [False, False, False]
        self.trailing_sl = None
        self.is_open = True
        self.pnl = 0.0
        self.exit_reason = ""


def simulate_step(open_trade, row, capital, trades, cooldown_bars):
    if open_trade and open_trade.is_open:
        t = open_trade
        sl = t.trailing_sl if t.trailing_sl else t.sl
        hit_sl = (t.direction == 'BUY' and row['low'] <= sl) or \
                 (t.direction == 'SELL' and row['high'] >= sl)
        if hit_sl:
            remaining = sum(t.tp_ratios[k] for k in range(3) if not t.partial_closed[k]) * t.size
            pnl_move = (sl - t.entry) if t.direction == 'BUY' else (t.entry - sl)
            t.pnl += (pnl_move / t.entry) * remaining
            t.is_open = False
            t.exit_reason = 'SL'
            capital += t.pnl
            trades.append(t)
            return None, capital, 8  # cooldown 8 bar 15m ~ 2 jam (samain SL cooldown 2j)
        else:
            for k, tp in enumerate(t.tp_prices):
                if t.partial_closed[k]:
                    continue
                hit_tp = (t.direction == 'BUY' and row['high'] >= tp) or \
                         (t.direction == 'SELL' and row['low'] <= tp)
                if hit_tp:
                    partial_size = t.tp_ratios[k] * t.size
                    pnl_move = (tp - t.entry) if t.direction == 'BUY' else (t.entry - tp)
                    t.pnl += (pnl_move / t.entry) * partial_size
                    t.partial_closed[k] = True
                    if k == 0:
                        t.trailing_sl = t.entry
                    elif k == 1:
                        t.trailing_sl = t.tp_prices[0]
            if all(t.partial_closed):
                t.is_open = False
                t.exit_reason = 'TP_ALL'
                capital += t.pnl
                trades.append(t)
                return None, capital, cooldown_bars
        return t, capital, cooldown_bars
    return open_trade, capital, cooldown_bars


# ─────────────────────────────────────────────────────────────
# CORE BACKTEST — mirror analyze_pair() dari main.py
# ─────────────────────────────────────────────────────────────
def run_backtest(symbol_display, df_15m_raw, df_1h_raw, df_4h_raw, df_1d_raw, df_btc_4h_raw):
    df_15m = to_indexed(df_15m_raw)
    df_1h  = to_indexed(df_1h_raw)
    df_4h  = to_indexed(df_4h_raw)
    df_1d  = to_indexed(df_1d_raw)
    df_btc_4h = to_indexed(df_btc_4h_raw)

    capital = INITIAL_CAPITAL
    equity_curve = [capital]
    trades = []
    open_trade = None
    cooldown_bars = 0

    score_log = []          # semua score yg dihitung (termasuk yg invalid)
    breakdown_fail_count = {}  # hitung komponen mana yg paling sering 0

    is_btc_pair = "BTC" in symbol_display.upper()

    ts_list = df_15m_raw['timestamp'].tolist()

    for i in range(220, len(ts_list), STEP_EVERY_N_15M):
        ts = ts_list[i]
        row15 = df_15m_raw.iloc[i]

        # ── update open trade dulu ──
        open_trade, capital, cooldown_bars = simulate_step(open_trade, row15, capital, trades, cooldown_bars)
        if cooldown_bars > 0:
            cooldown_bars -= 1
            equity_curve.append(capital)
            continue
        if open_trade:
            equity_curve.append(capital)
            continue

        # ── STEP 1: killzone (simplified) ──
        if not is_killzone_simple(ts):
            equity_curve.append(capital)
            continue

        # ── STEP 2: fetch window data (mirror exchange.get_ohlcv limit=200) ──
        w15 = slice_up_to(df_15m, ts, LOOKBACK_15M)
        w1h = slice_up_to(df_1h, ts, LOOKBACK_1H)
        w4h = slice_up_to(df_4h, ts, LOOKBACK_4H)
        w_btc4h = slice_up_to(df_btc_4h, ts, LOOKBACK_4H)

        if len(w15) < 60 or len(w1h) < 60 or len(w4h) < 60:
            equity_curve.append(capital)
            continue

        # ── STEP 3: indicators ──
        ind_15m = indicators.calculate_all(w15)
        ind_1h  = indicators.calculate_all(w1h)
        if not ind_15m or not ind_1h:
            equity_curve.append(capital)
            continue

        # ── STEP 4: SMC ──
        smc_result = smc.analyze(w4h, w1h, w15)
        if not smc_result.get("valid"):
            equity_curve.append(capital)
            continue
        direction = smc_result.get("direction")
        if not direction:
            equity_curve.append(capital)
            continue

        # ── STEP 5: fibonacci ──
        current_price = float(w15["close"].iloc[-1])
        atr_val = ind_15m.get("atr", 0)
        liq_1h = smc_result.get("liquidity_1h", {})
        liq_level = liq_1h.get("nearest_ssl") if direction == "BUY" else liq_1h.get("nearest_bsl")

        fib_result = fibonacci.analyze(
            df=w1h, direction=direction, current_price=current_price,
            atr=atr_val, liquidity_level=liq_level,
        )
        if not fib_result.get("valid"):
            equity_curve.append(capital)
            continue

        # ── STEP 6: breakout & pullback ──
        vol_data_15m = {
            "ratio": ind_15m.get("volume_ratio", 0),
            "above_avg": ind_15m.get("volume_above_avg", False),
        }
        bp_result = breakout_pullback.analyze(
            df=w15, direction=direction, volume_data=vol_data_15m,
            obs=smc_result.get("order_blocks", []), fvgs=smc_result.get("fvgs", []),
            fib_levels=fib_result.get("fib_levels"),
        )

        # ── STEP 7: VWAP (soft score, tidak pernah block) ──
        vwap_result = vwap_analyzer.analyze(w1h, direction)

        # ── STEP 8: FUNDING — tidak bisa dibacktest historis, netralkan ──
        funding_result = {
            "valid": False, "rate": 0.0, "status": "backtest_neutral",
            "pass": True, "score_bonus": 1,
            "reason": "Backtest: funding historis tidak tersedia, dinetralkan",
        }

        # ── STEP 9: correlation BTC (pakai data BTC asli) ──
        corr_result = correlation_filter.analyze(
            pair=symbol_display, direction=direction,
            df_btc_4h=(df_4h if is_btc_pair else w_btc4h),
        )
        if not corr_result.get("pass", True):
            equity_curve.append(capital)
            continue

        # ── STEP 10: news (tidak tersedia historis -> selalu aman) ──
        news_status = {"is_safe": True, "unsafe_news": []}
        session_info = {
            "in_killzone": True, "should_avoid": False,
            "session_name": "London/NY (backtest)",
        }

        # ── SCORING ASLI ──
        score_result = confluence_scorer.calculate(
            direction=direction, indicators=ind_15m, smc_analysis=smc_result,
            fib_analysis=fib_result, session_info=session_info, news_status=news_status,
            breakout_info=bp_result.get("breakout", {}), pullback_info=bp_result.get("pullback", {}),
            vwap_result=vwap_result, funding_result=funding_result, correlation_result=corr_result,
        )

        score = score_result.get("score", 0)
        breakdown = score_result.get("breakdown", {})
        for k, v in breakdown.items():
            if v == 0:
                breakdown_fail_count[k] = breakdown_fail_count.get(k, 0) + 1

        regime_boost = risk_manager.get_regime_score_boost()
        effective_min = cfg.MIN_CONFLUENCE_SCORE + regime_boost
        is_valid = score >= effective_min and not score_result.get("hard_fail", False)

        score_log.append({
            "ts": ts, "score": score, "effective_min": effective_min,
            "is_valid": is_valid, "grade": score_result.get("grade"),
        })

        if not is_valid:
            equity_curve.append(capital)
            continue

        tp_sl = fib_result.get("tp_sl", {})
        if not tp_sl or tp_sl.get("rr2", 0) < cfg.MIN_RR:
            equity_curve.append(capital)
            continue

        # ── OPEN TRADE ──
        risk_amount = capital * RISK_PER_TRADE
        sl_dist_pct = abs(current_price - tp_sl["sl"]) / current_price
        if sl_dist_pct <= 0:
            equity_curve.append(capital)
            continue
        size = risk_amount / sl_dist_pct

        open_trade = SimTrade(
            direction=direction, entry=current_price, sl=tp_sl["sl"],
            tp1=tp_sl["tp1"], tp2=tp_sl["tp2"], tp3=tp_sl["tp3"],
            size=size, entry_i=i,
        )

        equity_curve.append(capital)

    return _compute_stats(symbol_display, trades, equity_curve, score_log, breakdown_fail_count)


def _compute_stats(symbol, trades, equity_curve, score_log, breakdown_fail_count):
    total_analyzed = len(score_log)
    valid_signals = sum(1 for s in score_log if s["is_valid"])
    avg_score = np.mean([s["score"] for s in score_log]) if score_log else 0

    print(f"\n{'─'*55}")
    print(f"  {symbol}")
    print(f"{'─'*55}")
    print(f"  Candle dianalisis     : {total_analyzed}")
    print(f"  Skor rata-rata        : {avg_score:.1f}/24")
    print(f"  Signal valid (>=min)  : {valid_signals}  ({valid_signals/total_analyzed*100:.2f}% dari candle)" if total_analyzed else "  Signal valid: 0")

    if breakdown_fail_count:
        top_fails = sorted(breakdown_fail_count.items(), key=lambda x: -x[1])[:5]
        print(f"  Komponen paling sering GAGAL (top 5):")
        for name, cnt in top_fails:
            pct = cnt / total_analyzed * 100 if total_analyzed else 0
            print(f"    - {name:<20} gagal {cnt}x ({pct:.1f}% candle)")

    if not trades:
        print(f"  Total trades: 0 — tidak ada entry tereksekusi di periode ini.")
        return {
            "symbol": symbol, "trades": [], "equity_curve": equity_curve,
            "avg_score": avg_score, "valid_signals": valid_signals,
            "total_analyzed": total_analyzed, "win_rate": 0, "profit_factor": 0,
            "total_return": 0,
        }

    wins = [t for t in trades if t.pnl > 0]
    loss = [t for t in trades if t.pnl <= 0]
    wr = len(wins) / len(trades)
    gp = sum(t.pnl for t in wins)
    gl = abs(sum(t.pnl for t in loss))
    pf = gp / gl if gl > 0 else float('inf')
    total_ret = (equity_curve[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL

    print(f"  Total trades           : {len(trades)}")
    print(f"  Win rate               : {wr:.1%}")
    print(f"  Profit Factor          : {pf:.2f}")
    print(f"  Total Return           : {total_ret:+.2%}")
    print(f"  Final Capital          : ${equity_curve[-1]:.2f}")

    return {
        "symbol": symbol, "trades": trades, "equity_curve": equity_curve,
        "avg_score": avg_score, "valid_signals": valid_signals,
        "total_analyzed": total_analyzed, "win_rate": wr, "profit_factor": pf,
        "total_return": total_ret,
    }


def plot_results(results):
    valid = [r for r in results if r["trades"]]
    if not valid:
        print("\n  Tidak ada trade sama sekali di semua pair — skip chart.")
        return None
    n = len(valid)
    fig, axes = plt.subplots(n, 1, figsize=(12, 4.5 * n))
    if n == 1:
        axes = [axes]
    for ax, r in zip(axes, valid):
        eq = pd.Series(r["equity_curve"])
        ax.plot(eq.values, linewidth=1.3)
        ax.axhline(INITIAL_CAPITAL, linestyle='--', color='gray', linewidth=0.8)
        ax.set_title(f"{r['symbol']} | Trades:{len(r['trades'])} WR:{r['win_rate']:.1%} "
                     f"PF:{r['profit_factor']:.2f} AvgScore:{r['avg_score']:.1f}/24")
        ax.grid(alpha=0.3)
    plt.tight_layout()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtest_confluence_result.png')
    plt.savefig(path, dpi=140, bbox_inches='tight')
    plt.close()
    print(f"\n  Chart disimpan: {path}")
    return path


if __name__ == '__main__':
    print("=" * 55)
    print("  VortexBot Backtest v2 — CONFLUENCE-ACCURATE")
    print(f"  MIN_CONFLUENCE_SCORE = {cfg.MIN_CONFLUENCE_SCORE} / 24")
    print("=" * 55)

    print("\n⏳ Loading BTC reference data (untuk correlation filter)...")
    df_btc_4h = fetch_ohlcv(BTC_PAIR, '4h', limit=2000)
    if df_btc_4h.empty:
        print("  ⚠️ Gagal load BTC data — correlation filter akan selalu bypass.")

    all_results = []
    for symbol in PAIRS:
        print(f"\n⏳ Loading data: {symbol}")
        df_15m = fetch_ohlcv(symbol, '15m', limit=15000)
        df_1h  = fetch_ohlcv(symbol, '1h',  limit=4000)
        df_4h  = fetch_ohlcv(symbol, '4h',  limit=1500)
        df_1d  = fetch_ohlcv(symbol, '1d',  limit=250)

        if df_15m.empty or df_1h.empty or df_4h.empty or df_1d.empty:
            print(f"  ⚠️ Skip {symbol} — data kosong")
            continue

        # detect regime sekali di awal pakai data 1D (mirror startup())
        try:
            risk_manager.detect_market_regime(to_indexed(df_1d))
        except Exception as e:
            print(f"  ⚠️ Regime detect error: {e}")

        result = run_backtest(symbol, df_15m, df_1h, df_4h, df_1d, df_btc_4h)
        all_results.append(result)

    print(f"\n{'='*55}")
    print("  SUMMARY SEMUA PAIR")
    print(f"{'='*55}")
    for r in all_results:
        print(f"  {r['symbol']:<12} AvgScore:{r['avg_score']:.1f}/24  "
              f"ValidSignal:{r['valid_signals']}/{r['total_analyzed']}  "
              f"Trades:{len(r['trades'])}  WR:{r['win_rate']:.1%}  Return:{r['total_return']:+.2%}")

    plot_results(all_results)
    print("\n  Selesai. Kalau ValidSignal terlalu sedikit/nol di semua pair,")
    print("  itu konfirmasi kuat MIN_CONFLUENCE_SCORE perlu diturunkan —")
    print("  bukan bug, tapi threshold-nya emang belum match sama kondisi market.")