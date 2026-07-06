"""
Backtesting Framework — VortexBot (OKX Demo)
Strategi: SMC + Fibonacci + Multi-TF (4H/1H/15M)
Filters: Stoch 5,3,3 · EMA 13/21 · VWAP · Killzone London/NY
Risk: SL 2×ATR · Partial TP 30/40/30 · Trailing stop · SL cooldown 2j

Cara jalankan:
    pip install ccxt pandas numpy matplotlib requests
    python backtest/backtest_smc.py
"""

import os
import sys
import ccxt
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import time
import requests
from dataclasses import dataclass, field
from typing import Optional

# ─────────────────────────────────────────────────────────────
# PAIRS
# ─────────────────────────────────────────────────────────────
PAIRS = [
    'ETH/USDT',
    'BNB/USDT',
    'AAVE/USDT',
    'LINK/USDT',
    'AVAX/USDT',
    'OP/USDT',
]

# ─────────────────────────────────────────────────────────────
# CONFIG EXCHANGE
# ─────────────────────────────────────────────────────────────
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
    }
})

# ─────────────────────────────────────────────────────────────
# CONFIG TELEGRAM
# ─────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

def _tg_send(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [Telegram] Token/Chat ID tidak ditemukan, skip notif.")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id"   : TELEGRAM_CHAT_ID,
                "text"      : message[:4090],
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"  [Telegram] Error kirim pesan: {e}")
        return False

def _tg_send_photo(image_path: str, caption: str = "") -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    if not os.path.exists(image_path):
        print(f"  [Telegram] File chart tidak ditemukan: {image_path}")
        return False
    try:
        with open(image_path, 'rb') as photo:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                data={
                    "chat_id"   : TELEGRAM_CHAT_ID,
                    "caption"   : caption[:1024],
                    "parse_mode": "HTML",
                },
                files={"photo": photo},
                timeout=30,
            )
        return resp.status_code == 200
    except Exception as e:
        print(f"  [Telegram] Error kirim chart: {e}")
        return False

# ─────────────────────────────────────────────────────────────
# CONFIG STRATEGI
# ─────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 100
RISK_PER_TRADE  = 0.01
ATR_SL_MULT     = 2.0
TP_RATIOS       = [0.30, 0.40, 0.30]
TP_RR           = [1.5,  2.5,  4.0]
COOLDOWN_BARS   = 8
EMA_FAST        = 13
EMA_SLOW        = 21
STOCH_K         = 5
STOCH_D         = 3
STOCH_SMOOTH    = 3

LONDON_HOURS = list(range(7, 11))
NY_HOURS     = list(range(12, 16))

# ─────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────
@dataclass
class Trade:
    direction:      str
    entry_price:    float
    sl_price:       float
    tp_prices:      list
    size:           float
    entry_bar:      int
    partial_closed: list         = field(default_factory=lambda: [False, False, False])
    trailing_sl:    Optional[float] = None
    is_open:        bool         = True
    pnl:            float        = 0.0
    exit_reason:    str          = ""

@dataclass
class BacktestResult:
    symbol:        str
    trades:        list
    equity_curve:  list
    win_rate:      float = 0.0
    profit_factor: float = 0.0
    max_drawdown:  float = 0.0
    sharpe_ratio:  float = 0.0
    total_return:  float = 0.0

# ─────────────────────────────────────────────────────────────
# FETCH DATA — multi-batch agar dapat data panjang
# ─────────────────────────────────────────────────────────────
def _tf_to_ms(timeframe: str) -> int:
    """Konversi timeframe string ke milliseconds."""
    units = {'m': 60, 'h': 3600, 'd': 86400, 'w': 604800}
    return int(timeframe[:-1]) * units[timeframe[-1]] * 1000

def fetch_ohlcv(symbol: str, timeframe: str,
                limit: int = 1000) -> pd.DataFrame:
    """Fetch data historis OHLCV — auto multi-batch untuk data panjang."""
    print(f"  Fetching {symbol} {timeframe} ({limit} bars)...")
    try:
        all_bars = []
        per_req  = 1000  # Binance max per request
        # Hitung since awal: mundur dari sekarang
        now_ms   = int(time.time() * 1000)
        tf_ms    = _tf_to_ms(timeframe)
        since    = now_ms - (limit * tf_ms)

        while len(all_bars) < limit:
            fetch_n = min(per_req, limit - len(all_bars))
            bars    = exchange.fetch_ohlcv(
                symbol, timeframe,
                since=since, limit=fetch_n
            )
            if not bars:
                break
            all_bars.extend(bars)
            since = bars[-1][0] + tf_ms  # lanjut dari candle terakhir
            time.sleep(0.4)
            if len(bars) < fetch_n:
                break  # sudah sampai candle terbaru

        if not all_bars:
            return pd.DataFrame()

        df = pd.DataFrame(
            all_bars, columns=['ts', 'open', 'high', 'low', 'close', 'volume']
        )
        df['timestamp'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
        df = df.drop(columns='ts').drop_duplicates('timestamp')
        df = df.sort_values('timestamp').reset_index(drop=True)
        print(f"  → {len(df)} bars berhasil di-fetch")
        return df
    except Exception as e:
        print(f"  ERROR fetch {symbol} {timeframe}: {e}")
        return pd.DataFrame()

# ─────────────────────────────────────────────────────────────
# INDIKATOR
# ─────────────────────────────────────────────────────────────
def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([
        h - l,
        (h - c.shift()).abs(),
        (l - c.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calc_stochastic(df: pd.DataFrame, k=5, d=3, smooth=3):
    low_min  = df['low'].rolling(k).min()
    high_max = df['high'].rolling(k).max()
    stk = 100 * (df['close'] - low_min) / (high_max - low_min + 1e-9)
    stk = stk.rolling(smooth).mean()
    std = stk.rolling(d).mean()
    return stk, std

def calc_vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df['high'] + df['low'] + df['close']) / 3
    return (tp * df['volume']).cumsum() / df['volume'].cumsum()

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['atr']            = calc_atr(df)
    df['ema13']          = calc_ema(df['close'], EMA_FAST)
    df['ema21']          = calc_ema(df['close'], EMA_SLOW)
    df['vwap']           = calc_vwap(df)
    df['stk'], df['std'] = calc_stochastic(df, STOCH_K, STOCH_D, STOCH_SMOOTH)
    return df

# ─────────────────────────────────────────────────────────────
# DETEKSI SMC
# ─────────────────────────────────────────────────────────────
def detect_swing_highs_lows(df: pd.DataFrame, lookback: int = 5):
    sh = pd.Series(False, index=df.index)
    sl = pd.Series(False, index=df.index)
    for i in range(lookback, len(df) - lookback):
        wh = df['high'].iloc[i - lookback: i + lookback + 1]
        wl = df['low'].iloc[i  - lookback: i + lookback + 1]
        if df['high'].iloc[i] == wh.max():
            sh.iloc[i] = True
        if df['low'].iloc[i] == wl.min():
            sl.iloc[i] = True
    return sh, sl

def detect_order_blocks(df, sh, sl, lookback=3):
    obs = []
    for i in range(lookback + 1, len(df)):
        if sh.iloc[i]:
            for j in range(i-1, max(i-lookback-1, 0), -1):
                if df['close'].iloc[j] < df['open'].iloc[j]:
                    obs.append({
                        'type': 'bullish',
                        'high': df['high'].iloc[j],
                        'low' : df['low'].iloc[j],
                        'bar_idx': j
                    })
                    break
        if sl.iloc[i]:
            for j in range(i-1, max(i-lookback-1, 0), -1):
                if df['close'].iloc[j] > df['open'].iloc[j]:
                    obs.append({
                        'type': 'bearish',
                        'high': df['high'].iloc[j],
                        'low' : df['low'].iloc[j],
                        'bar_idx': j
                    })
                    break
    return obs

def detect_fvg(df):
    fvgs = []
    for i in range(2, len(df)):
        if df['low'].iloc[i] > df['high'].iloc[i-2]:
            fvgs.append({
                'type'   : 'bullish',
                'top'    : df['low'].iloc[i],
                'bottom' : df['high'].iloc[i-2],
                'bar_idx': i
            })
        if df['high'].iloc[i] < df['low'].iloc[i-2]:
            fvgs.append({
                'type'   : 'bearish',
                'top'    : df['low'].iloc[i-2],
                'bottom' : df['high'].iloc[i],
                'bar_idx': i
            })
    return fvgs

# ─────────────────────────────────────────────────────────────
# HELPER FILTER
# ─────────────────────────────────────────────────────────────
def is_killzone(ts) -> bool:
    return ts.hour in LONDON_HOURS or ts.hour in NY_HOURS

def get_4h_bias(df_4h, ts):
    mask = df_4h['timestamp'] <= ts
    if mask.sum() == 0:
        return None
    row = df_4h[mask].iloc[-1]
    if row['ema13'] > row['ema21'] and row['close'] > row['vwap']:
        return 'bullish'
    if row['ema13'] < row['ema21'] and row['close'] < row['vwap']:
        return 'bearish'
    return None

def get_ob_nearby(obs, price, direction, bar_limit):
    for ob in obs:
        if ob['bar_idx'] >= bar_limit:
            continue
        if ob['type'] == direction and ob['low'] <= price <= ob['high']:
            return ob
    return None

def get_fvg_nearby(fvgs, price, direction, bar_limit):
    for fvg in fvgs:
        if fvg['bar_idx'] >= bar_limit:
            continue
        if fvg['type'] == direction and fvg['bottom'] <= price <= fvg['top']:
            return fvg
    return None

# ─────────────────────────────────────────────────────────────
# CORE BACKTEST LOOP
# ─────────────────────────────────────────────────────────────
def run_backtest(symbol: str,
                 df_15m: pd.DataFrame,
                 df_1h:  pd.DataFrame,
                 df_4h:  pd.DataFrame) -> BacktestResult:

    df_15m = add_indicators(df_15m)
    df_1h  = add_indicators(df_1h)
    df_4h  = add_indicators(df_4h)

    sh_1h, sl_1h = detect_swing_highs_lows(df_1h)
    obs  = detect_order_blocks(df_1h, sh_1h, sl_1h)
    fvgs = detect_fvg(df_1h)

    capital       = INITIAL_CAPITAL
    equity_curve  = [capital]
    trades        = []
    open_trade: Optional[Trade] = None
    cooldown_bars = 0

    for i in range(50, len(df_15m)):
        row   = df_15m.iloc[i]
        ts    = row['timestamp']
        close = row['close']
        high  = row['high']
        low   = row['low']
        atr   = row['atr']

        if pd.isna(atr) or atr == 0:
            equity_curve.append(capital)
            continue

        # ── Update open trade
        if open_trade and open_trade.is_open:
            t  = open_trade
            sl = t.trailing_sl if t.trailing_sl else t.sl_price

            hit_sl = (t.direction == 'long'  and low  <= sl) or \
                     (t.direction == 'short' and high >= sl)

            if hit_sl:
                remaining = sum(
                    TP_RATIOS[k] for k in range(3)
                    if not t.partial_closed[k]
                ) * t.size
                pnl_move      = (sl - t.entry_price) if t.direction == 'long' \
                                else (t.entry_price - sl)
                t.pnl        += (pnl_move / t.entry_price) * remaining
                t.is_open     = False
                t.exit_reason = 'SL'
                capital      += t.pnl
                trades.append(t)
                open_trade    = None
                cooldown_bars = COOLDOWN_BARS
            else:
                for k, tp in enumerate(t.tp_prices):
                    if t.partial_closed[k]:
                        continue
                    hit_tp = (t.direction == 'long'  and high >= tp) or \
                             (t.direction == 'short' and low  <= tp)
                    if hit_tp:
                        partial_size        = TP_RATIOS[k] * t.size
                        pnl_move            = (tp - t.entry_price) if t.direction == 'long' \
                                              else (t.entry_price - tp)
                        t.pnl              += (pnl_move / t.entry_price) * partial_size
                        t.partial_closed[k] = True
                        if k == 0:
                            t.trailing_sl = t.entry_price
                        elif k == 1:
                            t.trailing_sl = t.tp_prices[0]

                if all(t.partial_closed):
                    t.is_open     = False
                    t.exit_reason = 'TP_ALL'
                    capital      += t.pnl
                    trades.append(t)
                    open_trade    = None

        if cooldown_bars > 0:
            cooldown_bars -= 1
            equity_curve.append(capital)
            continue

        if open_trade:
            equity_curve.append(capital)
            continue

        # ── FILTER 1: Killzone
        if not is_killzone(ts):
            equity_curve.append(capital)
            continue

        # ── FILTER 2: 4H bias
        bias = get_4h_bias(df_4h, ts)
        if bias is None:
            equity_curve.append(capital)
            continue

        # ── FILTER 3: 1H EMA alignment
        mask_1h = df_1h['timestamp'] <= ts
        if mask_1h.sum() == 0:
            equity_curve.append(capital)
            continue
        r1h    = df_1h[mask_1h].iloc[-1]
        ema_ok = (bias == 'bullish' and r1h['ema13'] > r1h['ema21']) or \
                 (bias == 'bearish' and r1h['ema13'] < r1h['ema21'])
        if not ema_ok:
            equity_curve.append(capital)
            continue

        # ── FILTER 4: VWAP 15M
        vwap = row['vwap']
        if pd.isna(vwap):
            equity_curve.append(capital)
            continue
        if bias == 'bullish' and close < vwap:
            equity_curve.append(capital)
            continue
        if bias == 'bearish' and close > vwap:
            equity_curve.append(capital)
            continue

        # ── FILTER 5: Stochastic 15M
        stk, std_ = row['stk'], row['std']
        if pd.isna(stk) or pd.isna(std_):
            equity_curve.append(capital)
            continue

        stk_prev  = df_15m['stk'].iloc[i-1]
        std_prev  = df_15m['std'].iloc[i-1]

        cross_up   = stk > std_ and stk_prev <= std_prev
        cross_down = stk < std_ and stk_prev >= std_prev
        oversold   = stk < 20 and std_ < 20
        overbought = stk > 80 and std_ > 80

        stoch_full = (bias == 'bullish' and cross_up   and oversold) or \
                     (bias == 'bearish' and cross_down and overbought)
        stoch_soft = (bias == 'bullish' and cross_up   and stk < 50) or \
                     (bias == 'bearish' and cross_down and stk > 50)

        stoch_ok = stoch_full 

        if not stoch_ok:
            equity_curve.append(capital)
            continue

        # ── FILTER 6: EMA 13/21 15M
        if bias == 'bullish' and row['ema13'] <= row['ema21']:
            equity_curve.append(capital)
            continue
        if bias == 'bearish' and row['ema13'] >= row['ema21']:
            equity_curve.append(capital)
            continue

        # ── SMC: cek OB atau FVG
        i_1h = int(mask_1h.sum()) - 1
        ob   = get_ob_nearby(obs,  close, bias, i_1h)
        fvg  = get_fvg_nearby(fvgs, close, bias, i_1h)
        if ob is None and fvg is None:
            equity_curve.append(capital)
            continue

        # ── Hitung SL, TP, size
        sl_price = (close - ATR_SL_MULT * atr) if bias == 'bullish' \
                   else (close + ATR_SL_MULT * atr)
        sl_dist  = abs(close - sl_price)
        if sl_dist < 1e-9:
            equity_curve.append(capital)
            continue

        tp_prices = [
            close + rr * sl_dist if bias == 'bullish' else close - rr * sl_dist
            for rr in TP_RR
        ]

        risk_usd   = capital * RISK_PER_TRADE
        size       = risk_usd / (sl_dist / close)
        open_trade = Trade(
            direction   = 'long' if bias == 'bullish' else 'short',
            entry_price = close,
            sl_price    = sl_price,
            tp_prices   = tp_prices,
            size        = size,
            entry_bar   = i,
        )

        equity_curve.append(capital)

    # Close trade yang masih open di akhir data
    if open_trade and open_trade.is_open:
        last                   = df_15m['close'].iloc[-1]
        pm                     = (last - open_trade.entry_price) if open_trade.direction == 'long' \
                                 else (open_trade.entry_price - last)
        open_trade.pnl         = (pm / open_trade.entry_price) * open_trade.size
        open_trade.is_open     = False
        open_trade.exit_reason = 'END_OF_DATA'
        capital               += open_trade.pnl
        trades.append(open_trade)

    return _compute_stats(symbol, trades, equity_curve)

# ─────────────────────────────────────────────────────────────
# STATISTIK
# ─────────────────────────────────────────────────────────────
def _compute_stats(symbol, trades, equity_curve) -> BacktestResult:
    if not trades:
        print(f"  {symbol}: tidak ada trade.")
        return BacktestResult(symbol=symbol, trades=[], equity_curve=equity_curve)

    wins = [t for t in trades if t.pnl > 0]
    loss = [t for t in trades if t.pnl <= 0]
    wr   = len(wins) / len(trades)
    gp   = sum(t.pnl for t in wins)
    gl   = abs(sum(t.pnl for t in loss))
    pf   = gp / gl if gl > 0 else float('inf')

    eq        = pd.Series(equity_curve)
    dd        = (eq - eq.cummax()) / eq.cummax()
    max_dd    = dd.min()
    ret       = eq.pct_change().dropna()
    sharpe    = (ret.mean() / ret.std() * np.sqrt(252 * 96)) if ret.std() > 0 else 0
    total_ret = (equity_curve[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL

    print(f"\n{'─'*50}")
    print(f"  {symbol}")
    print(f"{'─'*50}")
    print(f"  Total trades   : {len(trades)}")
    print(f"  Win rate       : {wr:.1%}")
    print(f"  Profit Factor  : {pf:.2f}")
    print(f"  Max Drawdown   : {max_dd:.2%}")
    print(f"  Sharpe Ratio   : {sharpe:.2f}")
    print(f"  Total Return   : {total_ret:+.2%}")
    print(f"  Final Capital  : ${equity_curve[-1]:.2f}")
    print(f"\n  💡 Diagnosis:")
    if wr < 0.40:
        print("     Win rate < 40% → longgarkan stoch threshold ke 35/65")
    if pf < 1.5:
        print("     Profit Factor < 1.5 → naikkan TP1 R:R ke 2.0")
    if max_dd < -0.20:
        print("     Drawdown > 20% → kurangi RISK_PER_TRADE ke 0.005")
    if wr >= 0.45 and pf >= 1.5 and max_dd > -0.15:
        print("     ✅ Hasil bagus! Siap lanjut optimize.")

    return BacktestResult(
        symbol=symbol, trades=trades, equity_curve=equity_curve,
        win_rate=wr, profit_factor=pf, max_drawdown=max_dd,
        sharpe_ratio=sharpe, total_return=total_ret,
    )

# ─────────────────────────────────────────────────────────────
# PLOT EQUITY CURVE
# ─────────────────────────────────────────────────────────────
def plot_results(results: list) -> str:
    n    = len(results)
    fig, axes = plt.subplots(n, 1, figsize=(12, 5 * n))
    if n == 1:
        axes = [axes]

    for ax, r in zip(axes, results):
        eq = pd.Series(r.equity_curve)
        ax.plot(eq.values, color='#2196F3', linewidth=1.5, label='Equity')
        ax.axhline(INITIAL_CAPITAL, color='gray', linewidth=0.8,
                   linestyle='--', label='Modal awal')
        ax.fill_between(range(len(eq)), INITIAL_CAPITAL, eq.values,
                        where=eq.values >= INITIAL_CAPITAL,
                        alpha=0.15, color='#4CAF50')
        ax.fill_between(range(len(eq)), INITIAL_CAPITAL, eq.values,
                        where=eq.values < INITIAL_CAPITAL,
                        alpha=0.15, color='#F44336')
        ax.set_title(
            f"{r.symbol}  |  WR: {r.win_rate:.1%}  PF: {r.profit_factor:.2f}  "
            f"DD: {r.max_drawdown:.2%}  Return: {r.total_return:+.2%}",
            fontsize=11
        )
        ax.set_xlabel('Bar (15M candle)')
        ax.set_ylabel('Capital (USD)')
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    chart_path = os.path.join(script_dir, 'backtest_result.png')
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\n  Chart disimpan: {chart_path}")
    return chart_path

# ─────────────────────────────────────────────────────────────
# KIRIM KE TELEGRAM
# ─────────────────────────────────────────────────────────────
def send_to_telegram(results: list, chart_path: str):
    if not results:
        _tg_send("⚠️ <b>Backtest selesai</b> — tidak ada hasil.")
        return

    lines  = "📊 <b>BACKTEST RESULT — VortexBot</b>\n"
    lines += "=" * 35 + "\n"

    for r in results:
        ok     = r.win_rate >= 0.45 and r.profit_factor >= 1.5 and r.max_drawdown > -0.20
        status = "✅" if ok else "⚠️"
        sign   = "+" if r.total_return >= 0 else ""
        lines += (
            f"\n{status} <b>{r.symbol}</b>\n"
            f"  Trades   : {len(r.trades)}\n"
            f"  Win Rate : <b>{r.win_rate:.1%}</b>\n"
            f"  PF       : <b>{r.profit_factor:.2f}</b>\n"
            f"  Max DD   : <b>{r.max_drawdown:.2%}</b>\n"
            f"  Sharpe   : {r.sharpe_ratio:.2f}\n"
            f"  Return   : <b>{sign}{r.total_return:.2%}</b>\n"
            f"  Capital  : <b>${r.equity_curve[-1]:.2f}</b>\n"
        )
        diag = []
        if r.win_rate < 0.40:    diag.append("WR rendah → longgarkan stoch")
        if r.profit_factor < 1.5: diag.append("PF rendah → naikkan TP1 RR")
        if r.max_drawdown < -0.20: diag.append("DD tinggi → kurangi risk/trade")
        if not diag:              diag.append("Siap dioptimasi lebih lanjut ✅")
        lines += f"  💡 {' | '.join(diag)}\n"

    lines += f"\n{'='*35}"

    print("\n  Mengirim hasil ke Telegram...")
    if _tg_send(lines):
        print("  ✅ Teks terkirim ke Telegram")
    else:
        print("  ❌ Gagal kirim teks ke Telegram")

    if _tg_send_photo(chart_path, caption="📈 Equity Curve — VortexBot Backtest"):
        print("  ✅ Chart terkirim ke Telegram")
    else:
        print("  ❌ Gagal kirim chart ke Telegram")

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 50)
    print("  VortexBot Backtesting — SMC Multi-TF")
    print("=" * 50)

    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        print(f"  📱 Telegram: aktif (chat_id: {TELEGRAM_CHAT_ID})")
    else:
        print("  📱 Telegram: tidak aktif — set env TELEGRAM_TOKEN & TELEGRAM_CHAT_ID")

    all_results = []

    for symbol in PAIRS:
        print(f"\n⏳ Loading data: {symbol}")
        df_15m = fetch_ohlcv(symbol, '15m', limit=50000)
        df_1h  = fetch_ohlcv(symbol, '1h',  limit=8000)
        df_4h  = fetch_ohlcv(symbol, '4h',  limit=2000)
        
        if df_15m.empty or df_1h.empty or df_4h.empty:
            print(f"  ⚠️  Skip {symbol} — data kosong")
            continue

        result = run_backtest(symbol, df_15m, df_1h, df_4h)
        all_results.append(result)

    if not all_results:
        print("\n  Tidak ada hasil — cek koneksi internet.")
        sys.exit(1)

    print(f"\n{'='*50}")
    print("  SUMMARY SEMUA PAIR")
    print(f"{'='*50}")
    for r in all_results:
        ok     = r.win_rate >= 0.45 and r.profit_factor >= 1.5
        status = "✅" if ok else "⚠️ "
        print(f"  {status} {r.symbol:<20} WR: {r.win_rate:.1%}  "
              f"PF: {r.profit_factor:.2f}  Return: {r.total_return:+.2%}")

    chart_path = plot_results(all_results)
    send_to_telegram(all_results, chart_path)
    print("\n  Selesai! ✅")