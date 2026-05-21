# ============================================
# VORTEX BOT - SMART MONEY CONCEPT (SMC)
# ============================================
#
# FIX v1.3:
#   - BOS Freshness Check
#     BOS/CHoCH hanya dihitung valid kalau terjadi
#     dalam BOS_FRESHNESS_CANDLES candle terakhir.
#     Sebelumnya: BOS yang terjadi 50 candle lalu
#     masih dihitung = sinyal stale.
#     Sekarang: BOS > 10 candle lalu = stale.
#
#   - Return dict tambah: bos_4h_fresh, choch_4h_fresh,
#     bos_1h_fresh, choch_1h_fresh → dipakai confluence
#     untuk bedakan BOS fresh vs stale.

import pandas as pd
import numpy as np
from config import cfg
from logger import logger

# Maks candle sejak BOS agar masih dianggap "fresh"
# 10 candle di 1H = 10 jam | 10 candle di 4H = 40 jam
BOS_FRESHNESS_CANDLES = 10


class SMCAnalysis:

    # ─── SWING HIGH / LOW ───────────────────

    @staticmethod
    def find_swing_points(df: pd.DataFrame,
                          lookback: int = None) -> dict:
        try:
            if lookback is None:
                lookback = cfg.SMC_SWING_LOOKBACK

            highs = []
            lows  = []

            for i in range(lookback, len(df) - lookback):
                if df["high"].iloc[i] == df["high"].iloc[
                    i-lookback:i+lookback+1
                ].max():
                    highs.append({
                        "index": i,
                        "price": float(df["high"].iloc[i]),
                        "time" : df.index[i],
                    })

                if df["low"].iloc[i] == df["low"].iloc[
                    i-lookback:i+lookback+1
                ].min():
                    lows.append({
                        "index": i,
                        "price": float(df["low"].iloc[i]),
                        "time" : df.index[i],
                    })

            return {
                "swing_highs": highs[-5:],
                "swing_lows" : lows[-5:],
                "last_high"  : highs[-1] if highs else None,
                "last_low"   : lows[-1]  if lows  else None,
            }

        except Exception as e:
            logger.error(f"❌ Swing points error: {e}")
            return {
                "swing_highs": [], "swing_lows": [],
                "last_high": None, "last_low": None,
            }

    # ─── BOS FRESHNESS CHECK ────────────────

    @staticmethod
    def _check_bos_freshness(df: pd.DataFrame,
                              bos: bool,
                              choch: bool,
                              highs: list,
                              lows: list,
                              direction: str) -> dict:
        """
        Cek apakah BOS/CHoCH terjadi dalam N candle terakhir.

        Logic:
        - Ambil swing high/low terakhir sebagai level BOS
        - Scan candle setelah swing tersebut
        - Cari candle pertama yang close melewati level
        - Hitung jarak ke candle terakhir
        - Kalau > BOS_FRESHNESS_CANDLES → stale
        """
        try:
            if not bos and not choch:
                return {
                    "bos_fresh"        : False,
                    "choch_fresh"      : False,
                    "bos_candles_ago"  : None,
                    "choch_candles_ago": None,
                }

            total   = len(df)
            closes  = df["close"].values
            fresh_n = BOS_FRESHNESS_CANDLES

            bos_candles_ago   = None
            choch_candles_ago = None

            # BOS: candle pertama close melewati swing level
            if direction == "BUY" and highs:
                level     = highs[-1]["price"]
                start_idx = highs[-1]["index"] + 1
                for i in range(start_idx, total):
                    if closes[i] > level:
                        bos_candles_ago = total - 1 - i
                        break

            elif direction == "SELL" and lows:
                level     = lows[-1]["price"]
                start_idx = lows[-1]["index"] + 1
                for i in range(start_idx, total):
                    if closes[i] < level:
                        bos_candles_ago = total - 1 - i
                        break

            # CHoCH: pakai swing sebelumnya (index -2)
            if direction == "BUY" and len(highs) >= 2:
                level     = highs[-2]["price"]
                start_idx = highs[-2]["index"] + 1
                for i in range(start_idx, total):
                    if closes[i] > level:
                        choch_candles_ago = total - 1 - i
                        break

            elif direction == "SELL" and len(lows) >= 2:
                level     = lows[-2]["price"]
                start_idx = lows[-2]["index"] + 1
                for i in range(start_idx, total):
                    if closes[i] < level:
                        choch_candles_ago = total - 1 - i
                        break

            bos_fresh = (
                bos_candles_ago is not None and
                bos_candles_ago <= fresh_n
            )
            choch_fresh = (
                choch_candles_ago is not None and
                choch_candles_ago <= fresh_n
            )

            logger.debug(
                f"📊 BOS freshness [{direction}]: "
                f"bos={bos_candles_ago}c (fresh={bos_fresh}) | "
                f"choch={choch_candles_ago}c (fresh={choch_fresh})"
            )

            return {
                "bos_fresh"        : bos_fresh,
                "choch_fresh"      : choch_fresh,
                "bos_candles_ago"  : bos_candles_ago,
                "choch_candles_ago": choch_candles_ago,
            }

        except Exception as e:
            logger.error(f"❌ BOS freshness error: {e}")
            return {
                "bos_fresh"        : bos,
                "choch_fresh"      : choch,
                "bos_candles_ago"  : None,
                "choch_candles_ago": None,
            }

    # ─── MARKET STRUCTURE ───────────────────

    def detect_market_structure(self,
                                df: pd.DataFrame) -> dict:
        """Deteksi BOS dan CHoCH + freshness check."""
        try:
            swings = self.find_swing_points(df)
            highs  = swings["swing_highs"]
            lows   = swings["swing_lows"]

            if len(highs) < 2 or len(lows) < 2:
                logger.debug(
                    f"⚠️ Swing kurang "
                    f"(H={len(highs)},L={len(lows)}) "
                    f"→ fallback"
                )
                return self._price_action_fallback(df)

            current_price = float(df["close"].iloc[-1])

            hh = highs[-1]["price"] > highs[-2]["price"]
            hl = lows[-1]["price"]  > lows[-2]["price"]
            lh = highs[-1]["price"] < highs[-2]["price"]
            ll = lows[-1]["price"]  < lows[-2]["price"]

            if hh and hl:
                structure = "UPTREND";   direction = "BUY"
            elif lh and ll:
                structure = "DOWNTREND"; direction = "SELL"
            else:
                structure = "RANGING"
                direction = self._ranging_bias(
                    highs, lows, current_price
                )
                logger.debug(
                    f"📊 RANGING → bias: {direction}"
                )

            bos_bullish = current_price > highs[-1]["price"]
            bos_bearish = current_price < lows[-1]["price"]
            bos         = bos_bullish or bos_bearish

            choch_bullish = lh and ll and bos_bullish
            choch_bearish = hh and hl and bos_bearish
            choch         = choch_bullish or choch_bearish

            # FIX v1.3: freshness
            freshness = self._check_bos_freshness(
                df=df, bos=bos, choch=choch,
                highs=highs, lows=lows, direction=direction,
            )

            return {
                "structure"        : structure,
                "direction"        : direction,
                "bos"              : bos,
                "bos_bullish"      : bos_bullish,
                "bos_bearish"      : bos_bearish,
                "choch"            : choch,
                "choch_bullish"    : choch_bullish,
                "choch_bearish"    : choch_bearish,
                "last_high"        : highs[-1]["price"],
                "last_low"         : lows[-1]["price"],
                "higher_high"      : hh,
                "higher_low"       : hl,
                "lower_high"       : lh,
                "lower_low"        : ll,
                "bos_fresh"        : freshness["bos_fresh"],
                "choch_fresh"      : freshness["choch_fresh"],
                "bos_candles_ago"  : freshness["bos_candles_ago"],
                "choch_candles_ago": freshness["choch_candles_ago"],
            }

        except Exception as e:
            logger.error(f"❌ Market structure error: {e}")
            return {
                "structure"  : "UNKNOWN",
                "bos"        : False,
                "choch"      : False,
                "direction"  : None,
                "bos_fresh"  : False,
                "choch_fresh": False,
            }

    @staticmethod
    def _ranging_bias(highs, lows, current_price) -> str:
        try:
            mid = (highs[-1]["price"] + lows[-1]["price"]) / 2
            return "BUY" if current_price >= mid else "SELL"
        except Exception:
            return "BUY"

    @staticmethod
    def _price_action_fallback(df: pd.DataFrame) -> dict:
        try:
            recent = df.tail(20)
            fc     = float(recent["close"].iloc[0])
            lc     = float(recent["close"].iloc[-1])

            if lc > fc * 1.001:
                direction = "BUY";  structure = "UPTREND"
            elif lc < fc * 0.999:
                direction = "SELL"; structure = "DOWNTREND"
            else:
                h   = float(recent["high"].max())
                l   = float(recent["low"].min())
                direction = "BUY" if lc >= (h+l)/2 else "SELL"
                structure = "RANGING"

            return {
                "structure"        : structure,
                "direction"        : direction,
                "bos"              : False,
                "bos_bullish"      : False,
                "bos_bearish"      : False,
                "choch"            : False,
                "choch_bullish"    : False,
                "choch_bearish"    : False,
                "last_high"        : float(df["high"].tail(20).max()),
                "last_low"         : float(df["low"].tail(20).min()),
                "higher_high"      : False,
                "higher_low"       : False,
                "lower_high"       : False,
                "lower_low"        : False,
                "bos_fresh"        : False,
                "choch_fresh"      : False,
                "bos_candles_ago"  : None,
                "choch_candles_ago": None,
                "fallback"         : True,
            }
        except Exception as e:
            logger.error(f"❌ Fallback error: {e}")
            return {
                "structure": "UNKNOWN", "direction": None,
                "bos": False, "choch": False,
                "bos_fresh": False, "choch_fresh": False,
            }

    # ─── ORDER BLOCKS ───────────────────────

    def detect_order_blocks(self, df: pd.DataFrame,
                            direction: str) -> list:
        try:
            obs      = []
            lookback = cfg.OB_LOOKBACK

            for i in range(1, min(lookback, len(df)-1)):
                idx    = -(i+1)
                curr   = df.iloc[idx]
                next_c = df.iloc[idx+1]

                if direction == "BUY":
                    is_bearish  = curr["close"] < curr["open"]
                    nxt_bull    = next_c["close"] > next_c["open"]
                    strong      = (
                        (next_c["close"] - next_c["open"]) >
                        (curr["open"] - curr["close"]) * 1.2
                    )
                    if is_bearish and nxt_bull and strong:
                        obs.append({
                            "type"       : "Bullish OB",
                            "top"        : float(curr["open"]),
                            "bottom"     : float(curr["close"]),
                            "mid"        : (float(curr["open"]) + float(curr["close"])) / 2,
                            "time"       : df.index[idx],
                            "strength"   : strong,
                            "valid"      : True,
                            "candles_ago": i,
                        })

                elif direction == "SELL":
                    is_bullish = curr["close"] > curr["open"]
                    nxt_bear   = next_c["close"] < next_c["open"]
                    strong     = (
                        (next_c["open"] - next_c["close"]) >
                        (curr["close"] - curr["open"]) * 1.2
                    )
                    if is_bullish and nxt_bear and strong:
                        obs.append({
                            "type"       : "Bearish OB",
                            "top"        : float(curr["close"]),
                            "bottom"     : float(curr["open"]),
                            "mid"        : (float(curr["open"]) + float(curr["close"])) / 2,
                            "time"       : df.index[idx],
                            "strength"   : strong,
                            "valid"      : True,
                            "candles_ago": i,
                        })

            return obs[:3]

        except Exception as e:
            logger.error(f"❌ Order block error: {e}")
            return []

    def is_price_in_ob(self, price: float, obs: list) -> dict:
        for ob in obs:
            if ob["bottom"] <= price <= ob["top"]:
                return {
                    "in_ob"  : True,
                    "ob_type": ob["type"],
                    "ob_mid" : ob["mid"],
                }
        return {"in_ob": False, "ob_type": None}

    # ─── FAIR VALUE GAP ─────────────────────

    def detect_fvg(self, df: pd.DataFrame,
                   direction: str) -> list:
        try:
            fvgs = []
            for i in range(2, min(cfg.OB_LOOKBACK, len(df))):
                c1 = df.iloc[-(i+1)]
                c3 = df.iloc[-(i-1)]

                if direction == "BUY":
                    gap = float(c3["low"]) - float(c1["high"])
                    if gap > 0:
                        pct = gap / float(c1["high"]) * 100
                        if pct >= cfg.FVG_MIN_SIZE:
                            fvgs.append({
                                "type"  : "Bullish FVG",
                                "top"   : float(c3["low"]),
                                "bottom": float(c1["high"]),
                                "mid"   : (float(c3["low"]) + float(c1["high"])) / 2,
                                "size"  : pct,
                                "time"  : df.index[-i],
                                "filled": False,
                            })

                elif direction == "SELL":
                    gap = float(c1["low"]) - float(c3["high"])
                    if gap > 0:
                        pct = gap / float(c1["low"]) * 100
                        if pct >= cfg.FVG_MIN_SIZE:
                            fvgs.append({
                                "type"  : "Bearish FVG",
                                "top"   : float(c1["low"]),
                                "bottom": float(c3["high"]),
                                "mid"   : (float(c1["low"]) + float(c3["high"])) / 2,
                                "size"  : pct,
                                "time"  : df.index[-i],
                                "filled": False,
                            })

            return fvgs[:3]

        except Exception as e:
            logger.error(f"❌ FVG error: {e}")
            return []

    def is_price_in_fvg(self, price: float,
                        fvgs: list) -> dict:
        for fvg in fvgs:
            if fvg["bottom"] <= price <= fvg["top"]:
                return {
                    "in_fvg"  : True,
                    "fvg_type": fvg["type"],
                    "fvg_mid" : fvg["mid"],
                    "fvg_size": fvg["size"],
                }
        return {"in_fvg": False, "fvg_type": None}

    # ─── LIQUIDITY ZONES ────────────────────

    def detect_liquidity(self, df: pd.DataFrame) -> dict:
        try:
            recent = df.tail(cfg.LIQUIDITY_LOOKBACK)
            highs  = recent["high"].values
            lows   = recent["low"].values

            bsl_levels = []
            for i in range(len(highs)-1):
                for j in range(i+1, len(highs)):
                    if abs(highs[i] - highs[j]) / highs[i] < 0.001:
                        bsl_levels.append((highs[i]+highs[j])/2)

            ssl_levels = []
            for i in range(len(lows)-1):
                for j in range(i+1, len(lows)):
                    if abs(lows[i] - lows[j]) / lows[i] < 0.001:
                        ssl_levels.append((lows[i]+lows[j])/2)

            cp          = float(df["close"].iloc[-1])
            bsl_above   = [b for b in bsl_levels if b > cp]
            ssl_below   = [s for s in ssl_levels if s < cp]
            nearest_bsl = min(bsl_above) if bsl_above else None
            nearest_ssl = max(ssl_below) if ssl_below else None

            bsl_swept = bool(
                nearest_bsl and
                (df["high"].iloc[-5:] > nearest_bsl).any()
            )
            ssl_swept = bool(
                nearest_ssl and
                (df["low"].iloc[-5:] < nearest_ssl).any()
            )

            return {
                "bsl_levels"   : sorted(bsl_levels)[-3:],
                "ssl_levels"   : sorted(ssl_levels)[:3],
                "nearest_bsl"  : nearest_bsl,
                "nearest_ssl"  : nearest_ssl,
                "bsl_swept"    : bsl_swept,
                "ssl_swept"    : ssl_swept,
                "current_price": cp,
            }

        except Exception as e:
            logger.error(f"❌ Liquidity error: {e}")
            return {}

    # ─── PREMIUM / DISCOUNT ZONE ────────────

    @staticmethod
    def get_premium_discount(df: pd.DataFrame,
                             lookback: int = 50) -> dict:
        try:
            recent  = df.tail(lookback)
            high    = float(recent["high"].max())
            low     = float(recent["low"].min())
            mid     = (high + low) / 2
            current = float(df["close"].iloc[-1])
            rng     = high - low

            is_discount = current < mid
            depth = (
                (mid - current) / (mid - low) * 100
                if is_discount and (mid - low) > 0
                else (current - mid) / (high - mid) * 100
                if (high - mid) > 0 else 0
            )

            return {
                "high"       : high,
                "low"        : low,
                "mid"        : mid,
                "fib_50"     : low + rng * 0.5,
                "fib_618"    : low + rng * 0.618,
                "current"    : current,
                "is_discount": is_discount,
                "is_premium" : not is_discount,
                "zone"       : "DISCOUNT" if is_discount else "PREMIUM",
                "depth_pct"  : depth,
                "ideal_buy"  : is_discount,
                "ideal_sell" : not is_discount,
            }

        except Exception as e:
            logger.error(f"❌ Premium/Discount error: {e}")
            return {}

    # ─── BREAKER BLOCK ──────────────────────

    def detect_breaker_block(self, df: pd.DataFrame,
                             direction: str) -> list:
        try:
            breakers = []
            obs      = self.detect_order_blocks(df, direction)
            current  = float(df["close"].iloc[-1])
            for ob in obs:
                if direction == "BUY" and current > ob["top"]:
                    breakers.append({
                        "type" : "Bullish Breaker",
                        "level": ob["top"],
                        "zone" : (ob["bottom"], ob["top"]),
                    })
                elif direction == "SELL" and current < ob["bottom"]:
                    breakers.append({
                        "type" : "Bearish Breaker",
                        "level": ob["bottom"],
                        "zone" : (ob["bottom"], ob["top"]),
                    })
            return breakers
        except Exception as e:
            logger.error(f"❌ Breaker block error: {e}")
            return []

    # ─── INDUCEMENT ─────────────────────────

    def detect_inducement(self, df: pd.DataFrame,
                          direction: str) -> dict:
        try:
            recent = df.tail(10)
            if direction == "BUY":
                lows = recent["low"].values
                for i in range(len(lows)-2):
                    if abs(lows[i] - lows[i+1]) / lows[i] < 0.002:
                        return {
                            "detected"   : True,
                            "type"       : "Bullish Inducement",
                            "level"      : (lows[i]+lows[i+1])/2,
                            "description": "Equal lows → potensi liquidity grab",
                        }
            elif direction == "SELL":
                highs = recent["high"].values
                for i in range(len(highs)-2):
                    if abs(highs[i]-highs[i+1])/highs[i] < 0.002:
                        return {
                            "detected"   : True,
                            "type"       : "Bearish Inducement",
                            "level"      : (highs[i]+highs[i+1])/2,
                            "description": "Equal highs → potensi liquidity grab",
                        }
            return {"detected": False, "type": None}
        except Exception as e:
            logger.error(f"❌ Inducement error: {e}")
            return {"detected": False}

    # ─── FULL SMC ANALYSIS ──────────────────

    def analyze(self, df_4h: pd.DataFrame,
                df_1h: pd.DataFrame,
                df_15m: pd.DataFrame) -> dict:
        """Full SMC analysis multi-timeframe v1.3"""
        try:
            structure_4h = self.detect_market_structure(df_4h)
            prem_disc_4h = self.get_premium_discount(df_4h)
            liquidity_4h = self.detect_liquidity(df_4h)

            direction = structure_4h.get("direction")

            if not direction:
                logger.debug("⚠️ 4H unclear → fallback 1H")
                s1h_bias  = self.detect_market_structure(df_1h)
                direction = s1h_bias.get("direction")
                if not direction:
                    return {
                        "valid"    : False,
                        "reason"   : "Structure unclear 4H & 1H",
                        "direction": None,
                    }

            structure_1h = self.detect_market_structure(df_1h)
            obs_1h       = self.detect_order_blocks(df_1h, direction)
            fvgs_1h      = self.detect_fvg(df_1h, direction)
            liquidity_1h = self.detect_liquidity(df_1h)
            breakers_1h  = self.detect_breaker_block(df_1h, direction)

            current_price = float(df_15m["close"].iloc[-1])
            in_ob         = self.is_price_in_ob(current_price, obs_1h)
            in_fvg        = self.is_price_in_fvg(current_price, fvgs_1h)
            inducement    = self.detect_inducement(df_15m, direction)

            liq_swept = (
                liquidity_1h.get("ssl_swept")
                if direction == "BUY"
                else liquidity_1h.get("bsl_swept")
            )

            # Freshness flags
            bos_4h_fresh   = structure_4h.get("bos_fresh",   False)
            choch_4h_fresh = structure_4h.get("choch_fresh", False)
            bos_1h_fresh   = structure_1h.get("bos_fresh",   False)
            choch_1h_fresh = structure_1h.get("choch_fresh", False)

            bos_4h   = structure_4h.get("bos",   False)
            choch_4h = structure_4h.get("choch", False)
            bos_1h   = structure_1h.get("bos",   False)
            choch_1h = structure_1h.get("choch", False)

            if bos_4h and not bos_4h_fresh:
                logger.debug(
                    f"⚠️ BOS 4H stale "
                    f"({structure_4h.get('bos_candles_ago')}c ago)"
                )
            if bos_1h and not bos_1h_fresh:
                logger.debug(
                    f"⚠️ BOS 1H stale "
                    f"({structure_1h.get('bos_candles_ago')}c ago)"
                )

            return {
                "valid"               : True,
                "direction"           : direction,
                # 4H
                "structure_4h"        : structure_4h["structure"],
                "bos_4h"              : bos_4h,
                "choch_4h"            : choch_4h,
                "bos_4h_fresh"        : bos_4h_fresh,
                "choch_4h_fresh"      : choch_4h_fresh,
                "bos_4h_candles_ago"  : structure_4h.get("bos_candles_ago"),
                "premium_discount"    : prem_disc_4h,
                "liquidity_4h"        : liquidity_4h,
                "ideal_zone"          : (
                    prem_disc_4h.get("ideal_buy")
                    if direction == "BUY"
                    else prem_disc_4h.get("ideal_sell")
                ),
                # 1H
                "structure_1h"        : structure_1h["structure"],
                "bos_1h"              : bos_1h,
                "choch_1h"            : choch_1h,
                "bos_1h_fresh"        : bos_1h_fresh,
                "choch_1h_fresh"      : choch_1h_fresh,
                "bos_1h_candles_ago"  : structure_1h.get("bos_candles_ago"),
                "order_blocks"        : obs_1h,
                "fvgs"                : fvgs_1h,
                "breaker_blocks"      : breakers_1h,
                "liquidity_1h"        : liquidity_1h,
                # 15M
                "in_ob"               : in_ob["in_ob"],
                "ob_type"             : in_ob.get("ob_type"),
                "in_fvg"              : in_fvg["in_fvg"],
                "fvg_type"            : in_fvg.get("fvg_type"),
                "liquidity_swept"     : liq_swept,
                "inducement"          : inducement,
                "current_price"       : current_price,
            }

        except Exception as e:
            logger.error(f"❌ SMC analyze error: {e}")
            return {"valid": False, "direction": None}


# Instance siap pakai
smc = SMCAnalysis()