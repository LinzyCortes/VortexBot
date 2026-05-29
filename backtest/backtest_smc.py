"""
Backtesting Framework — VortexBot (OKX Demo)
Strategi: SMC + Fibonacci + Multi-TF (4H/1H/15M)
Filters: Stoch 5,3,3 · EMA 13/21 · VWAP · Killzone London/NY
Risk: SL 2×ATR · Partial TP 30/40/30 · Trailing stop · SL cooldown 2j

Cara jalankan:
    pip install ccxt pandas numpy matplotlib
    python backtest/backtest_smc.py
"""

import ccxt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import time
from dataclasses import dataclass, field
from typing import Optional

# ─────────────────────────────────────────────────────────────
# PAIRS — tambah/hapus di sini, tidak perlu ubah file lain
# ─────────────────────────────────────────────────────────────
PAIRS = [
    'BTC/USDT:USDT',
    'ETH/USDT:USDT',
]

# ─────────────────────────────────────────────────────────────
# CONFIG EXCHANGE — tidak butuh API key untuk backtest
# ─────────────────────────────────────────────────────────────
exchange = ccxt.okx({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',   # perpetual futures
    }
})

# ─────────────────────────────────────────────────────────────
# CONFIG STRATEGI
# ─────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 100        # USD — modal awal demo
RISK_PER_TRADE  = 0.01       # 1% risk per trade
ATR_SL_MULT     = 2.0        # SL = 2x ATR
TP_RATIOS       = [0.30, 0.40, 0.30]   # partial close 30/40/30
TP_RR           = [1.5,  2.5,  4.0]   # R:R tiap TP
COOLDOWN_BARS   = 8          # ~2 jam di 15M setelah SL hit
EMA_FAST        = 13
EMA_SLOW        = 21
STOCH_K         = 5
STOCH_D         = 3
STOCH_SMOOTH    = 3

# Killzone UTC (London 07-10, NY 12-15)
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
    partial_closed: list  = field(default_factory=lambda: [False, False, False])
    trailing_sl:    Optional[float] = None
    is_open:        bool  = True
    pnl:            float = 0.0
    exit_reason:    str   = ""

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
# FETCH DATA
# ─────────────────────────────────────────────────────────────
def fetch_ohlcv(symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
    """Fetch data historis OHLCV dari OKX (public, tanpa API key)."""
    print(f"  Fetching {symbol} {timeframe} ({limit} bars)...")
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
        df = df.drop(columns='ts').reset_index(drop=True)
        time.sleep(0.3)   # hindari rate limit
        return df
    except Exception as e:
        print(f"  ERROR fetch {symbol} {timeframe}: {e}")
        return pd.DataFrame()

# ─────────────────────────────────────────────────────────────
# INDIKATOR
# ─────────────────────────────────────────────────────────────
def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
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
    typical = (df['high'] + df['low'] + df['close']) / 3
    return (typical * df['volume']).cumsum() / df['volume'].cumsum()

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['atr']        = calc_atr(df)
    df['ema13']      = calc_ema(df['close'], EMA_FAST)
    df['ema21']      = calc_ema(df['close'], EMA_SLOW)
    df['vwap']       = calc_vwap(df)
    df['stk'], df['std'] = calc_stochastic(df, STOCH_K, STOCH_D, STOCH_SMOOTH)
    return df

# ─────────────────────────────────────────────────────────────
# DETEKSI SMC
# ─────────────────────────────────────────────────────────────
def detect_swing_highs_lows(df: pd.DataFrame, lookback: int = 5):
    sh = pd.Series(False, index=df.index)
    sl = pd.Series(False, index=df.index)
    for i in range(lookback, len(df) - lookback):
        window_h = df['high'].iloc[i - lookback: i + lookback + 1]
        window_l = df['low'].iloc[i  - lookback: i + lookback + 1]
        if df['high'].iloc[i] == window_h.max():
            sh.iloc[i] = True
        if df['low'].iloc[i] == window_l.min():
            sl.iloc[i] = True
    return sh, sl

def detect_bos_choch(df, sh, sl):
    n = len(df)
    bull_bos  = pd.Series(False, index=df.index)
    bear_bos  = pd.Series(False, index=df.index)
    choch_b   = pd.Series(False, index=df.index)
    choch_s   = pd.Series(False, index=df.index)
    last_sh, last_sl, trend = None, None, None

    for i in range(1, n):
        if sh.iloc[i-1]: last_sh = df['high'].iloc[i-1]
        if sl.iloc[i-1]: last_sl = df['low'].iloc[i-1]
        c = df['close'].iloc[i]
        if last_sh and c > last_sh:
            (choch_b if trend == 'down' else bull_bos).iloc[i] = True
            trend = 'up'
        if last_sl and c < last_sl:
            (choch_s if trend == 'up' else bear_bos).iloc[i] = True
            trend = 'down'

    return bull_bos, bear_bos, choch_b, choch_s

def detect_order_blocks(df, sh, sl, lookback=3):
    obs = []
    for i in range(lookback + 1, len(df)):
        if sh.iloc[i]:
            for j in range(i-1, max(i-lookback-1, 0), -1):
                if df['close'].iloc[j] < df['open'].iloc[j]:
                    obs.append({'type':'bullish','high':df['high'].iloc[j],'low':df['low'].iloc[j],'bar_idx':j})
                    break
        if sl.iloc[i]:
            for j in range(i-1, max(i-lookback-1, 0), -1):
                if df['close'].iloc[j] > df['open'].iloc[j]:
                    obs.append({'type':'bearish','high':df['high'].iloc[j],'low':df['low'].iloc[j],'bar_idx':j})
                    break
    return obs

def detect_fvg(df):
    fvgs = []
    for i in range(2, len(df)):
        if df['low'].iloc[i] > df['high'].iloc[i-2]:
            fvgs.append({'type':'bullish','top':df['low'].iloc[i],'bottom':df['high'].iloc[i-2],'bar_idx':i})
        if df['high'].iloc[i] < df['low'].iloc[i-2]:
            fvgs.append({'type':'bearish','top':df['low'].iloc[i-2],'bottom':df['high'].iloc[i],'bar_idx':i})
    return fvgs

# ─────────────────────────────────────────────────────────────
# HELPER FILTER
# ─────────────────────────────────────────────────────────────
def is_killzone(ts) -> bool:
    h = ts.hour
    return h in LONDON_HOURS or h in NY_HOURS

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

    # Tambah indikator semua TF
    df_15m = add_indicators(df_15m)
    df_1h  = add_indicators(df_1h)
    df_4h  = add_indicators(df_4h)

    # SMC detection di 1H
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

        # ── Update open trade (SL/TP check)
        if open_trade and open_trade.is_open:
            t   = open_trade
            sl  = t.trailing_sl if t.trailing_sl else t.sl_price
            hit_sl = (t.direction == 'long'  and low  <= sl) or \
                     (t.direction == 'short' and high >= sl)

            if hit_sl:
                remaining = sum(
                    TP_RATIOS[k] for k in range(3) if not t.partial_closed[k]
                ) * t.size
                pnl_move = (sl - t.entry_price) if t.direction == 'long' \
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
                        partial_size = TP_RATIOS[k] * t.size
                        pnl_move     = (tp - t.entry_price) if t.direction == 'long' \
                                       else (t.entry_price - tp)
                        t.pnl             += (pnl_move / t.entry_price) * partial_size
                        t.partial_closed[k] = True
                        if k == 0:
                            t.trailing_sl = t.entry_price       # BE setelah TP1
                        elif k == 1:
                            t.trailing_sl = t.tp_prices[0]      # lock TP1 setelah TP2

                if all(t.partial_closed):
                    t.is_open     = False
                    t.exit_reason = 'TP_ALL'
                    capital      += t.pnl
                    trades.append(t)
                    open_trade    = None

        # ── Skip jika cooldown / ada trade terbuka
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
        r1h = df_1h[mask_1h].iloc[-1]
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
        stoch_ok = (bias == 'bullish' and stk < 30 and stk > std_) or \
                   (bias == 'bearish' and stk > 70 and stk < std_)
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
        i_1h   = int(mask_1h.sum()) - 1
        ob     = get_ob_nearby(obs,  close, bias, i_1h)
        fvg    = get_fvg_nearby(fvgs, close, bias, i_1h)
        if ob is None and fvg is None:
            equity_curve.append(capital)
            continue

        # ── Hitung SL, TP, size
        if bias == 'bullish':
            sl_price = close - ATR_SL_MULT * atr
        else:
            sl_price = close + ATR_SL_MULT * atr

        sl_dist = abs(close - sl_price)
        if sl_dist < 1e-9:
            equity_curve.append(capital)
            continue

        tp_prices = [
            close + rr * sl_dist if bias == 'bullish' else close - rr * sl_dist
            for rr in TP_RR
        ]

        risk_usd = capital * RISK_PER_TRADE
        size     = risk_usd / (sl_dist / close)

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
        last = df_15m['close'].iloc[-1]
        pm   = (last - open_trade.entry_price) if open_trade.direction == 'long' \
               else (open_trade.entry_price - last)
        open_trade.pnl        = (pm / open_trade.entry_price) * open_trade.size
        open_trade.is_open    = False
        open_trade.exit_reason = 'END_OF_DATA'
        capital += open_trade.pnl
        trades.append(open_trade)

    return _compute_stats(symbol, trades, equity_curve)

# ─────────────────────────────────────────────────────────────
# STATISTIK & PRINT
# ─────────────────────────────────────────────────────────────
def _compute_stats(symbol, trades, equity_curve) -> BacktestResult:
    if not trades:
        print(f"  {symbol}: tidak ada trade yang terjadi.")
        return BacktestResult(symbol=symbol, trades=[], equity_curve=equity_curve)

    wins  = [t for t in trades if t.pnl > 0]
    loss  = [t for t in trades if t.pnl <= 0]
    wr    = len(wins) / len(trades)
    gp    = sum(t.pnl for t in wins)
    gl    = abs(sum(t.pnl for t in loss))
    pf    = gp / gl if gl > 0 else float('inf')

    eq         = pd.Series(equity_curve)
    dd         = (eq - eq.cummax()) / eq.cummax()
    max_dd     = dd.min()
    ret        = eq.pct_change().dropna()
    sharpe     = (ret.mean() / ret.std() * np.sqrt(252 * 96)) if ret.std() > 0 else 0
    total_ret  = (equity_curve[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL

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

    # Saran otomatis berdasarkan hasil
    print(f"\n  💡 Diagnosis:")
    if wr < 0.40:
        print("     Win rate < 40% → coba longgarkan stoch threshold ke 35/65")
    if pf < 1.5:
        print("     Profit Factor < 1.5 → pertimbangkan naikkan TP1 R:R ke 2.0")
    if max_dd < -0.20:
        print("     Drawdown > 20% → kurangi RISK_PER_TRADE ke 0.005 (0.5%)")
    if wr >= 0.45 and pf >= 1.5 and max_dd > -0.15:
        print("     ✅ Hasil bagus! Siap lanjut optimize atau naikkan modal sedikit.")

    return BacktestResult(
        symbol        = symbol,
        trades        = trades,
        equity_curve  = equity_curve,
        win_rate      = wr,
        profit_factor = pf,
        max_drawdown  = max_dd,
        sharpe_ratio  = sharpe,
        total_return  = total_ret,
    )

# ─────────────────────────────────────────────────────────────
# PLOT EQUITY CURVE
# ─────────────────────────────────────────────────────────────
def plot_results(results: list):
    n = len(results)
    fig, axes = plt.subplots(n, 1, figsize=(12, 5 * n))
    if n == 1:
        axes = [axes]

    for ax, r in zip(axes, results):
        eq = pd.Series(r.equity_curve)
        ax.plot(eq.values, color='#2196F3', linewidth=1.5, label='Equity')
        ax.axhline(INITIAL_CAPITAL, color='gray', linewidth=0.8, linestyle='--', label='Modal awal')
        ax.fill_between(range(len(eq)), INITIAL_CAPITAL, eq.values,
                        where=eq.values >= INITIAL_CAPITAL, alpha=0.15, color='#4CAF50')
        ax.fill_between(range(len(eq)), INITIAL_CAPITAL, eq.values,
                        where=eq.values <  INITIAL_CAPITAL, alpha=0.15, color='#F44336')
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
    plt.savefig('backtest_result.png', dpi=150, bbox_inches='tight')
    print("\n  Chart disimpan: backtest_result.png")
    plt.show()

# ─────────────────────────────────────────────────────────────
# MAIN — jalankan semua pair
# ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 50)
    print("  VortexBot Backtesting — SMC Multi-TF")
    print("=" * 50)

    all_results = []

    for symbol in PAIRS:
        print(f"\n⏳ Loading data: {symbol}")

        df_15m = fetch_ohlcv(symbol, '15m', limit=2000)
        df_1h  = fetch_ohlcv(symbol, '1h',  limit=1000)
        df_4h  = fetch_ohlcv(symbol, '4h',  limit=500)

        if df_15m.empty or df_1h.empty or df_4h.empty:
            print(f"  ⚠️  Skip {symbol} — data kosong")
            continue

        result = run_backtest(symbol, df_15m, df_1h, df_4h)
        all_results.append(result)

    if all_results:
        print(f"\n{'='*50}")
        print("  SUMMARY SEMUA PAIR")
        print(f"{'='*50}")
        for r in all_results:
            status = "✅" if r.win_rate >= 0.45 and r.profit_factor >= 1.5 else "⚠️ "
            print(f"  {status} {r.symbol:<20} WR: {r.win_rate:.1%}  PF: {r.profit_factor:.2f}  "
                  f"Return: {r.total_return:+.2%}")

        plot_results(all_results)
    else:
        print("\n  Tidak ada hasil — cek koneksi internet atau symbol.")
