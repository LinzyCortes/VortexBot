# ============================================
# VORTEX BOT - FUNDING RATE FILTER
# ============================================
#
# Funding rate adalah mekanisme di crypto perpetual
# futures yang menyeimbangkan harga futures vs spot.
#
# Logika institusi crypto:
#   Funding sangat POSITIF (>0.05%):
#     → Terlalu banyak longs → institusi akan flush longs
#     → Hindari BUY, potensi squeeze ke bawah
#
#   Funding sangat NEGATIF (<-0.05%):
#     → Terlalu banyak shorts → institusi akan squeeze shorts
#     → Hindari SELL, potensi short squeeze ke atas
#
#   Funding normal (-0.03% ~ +0.03%):
#     → Pasar seimbang → aman untuk entry ke segala arah
#
# Data: gratis dari OKX / Bybit public API.
# Tidak butuh API key untuk baca funding rate.

import requests
from config import cfg
from logger import logger


class FundingRateFilter:

    def __init__(self):
        self._cache      = {}   # pair → {"rate": float, "ts": float}
        self._cache_ttl  = 300  # cache 5 menit (funding rate update tiap 8 jam)

    # ─── FETCH FUNDING RATE ─────────────────

    def _fetch_okx(self, pair: str) -> float | None:
        """
        Fetch funding rate dari OKX public API.
        Endpoint: GET /api/v5/public/funding-rate
        Tidak butuh API key.
        """
        try:
            url  = "https://www.okx.com/api/v5/public/funding-rate"
            resp = requests.get(
                url,
                params={"instId": pair},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", [])
                if items:
                    rate = float(items[0].get("fundingRate", 0))
                    # OKX return dalam desimal (0.0001 = 0.01%)
                    # Konversi ke persen untuk display
                    return rate * 100
        except Exception as e:
            logger.debug(f"OKX funding fetch error: {e}")
        return None

    def _fetch_bybit(self, pair: str) -> float | None:
        """
        Fetch funding rate dari Bybit public API.
        Endpoint: GET /v5/market/tickers
        Tidak butuh API key.
        """
        try:
            # Bybit pair format: BTCUSDT (tanpa dash dan SWAP)
            symbol = pair.replace("-", "").replace("SWAP", "")
            url    = "https://api.bybit.com/v5/market/tickers"
            resp   = requests.get(
                url,
                params={"category": "linear", "symbol": symbol},
                timeout=5,
            )
            if resp.status_code == 200:
                data  = resp.json()
                items = data.get("result", {}).get("list", [])
                if items:
                    rate = float(items[0].get("fundingRate", 0))
                    return rate * 100
        except Exception as e:
            logger.debug(f"Bybit funding fetch error: {e}")
        return None

    def get_funding_rate(self, pair: str) -> dict:
        """
        Ambil funding rate untuk pair tertentu.
        Pakai cache 5 menit untuk hindari spam API.

        Return:
          rate   → funding rate dalam persen
          status → "normal" / "high_positive" / "high_negative"
          valid  → apakah data berhasil di-fetch
        """
        import time

        try:
            # Cek cache
            cached = self._cache.get(pair)
            if cached and (time.time() - cached["ts"]) < self._cache_ttl:
                rate = cached["rate"]
                return self._build_result(pair, rate, from_cache=True)

            # Fetch sesuai exchange
            rate = None
            if cfg.IS_OKX:
                rate = self._fetch_okx(pair)
            else:
                rate = self._fetch_bybit(pair)

            if rate is None:
                # Fallback: coba exchange lain
                logger.debug(
                    f"⚠️ Funding rate fetch failed untuk {pair} "
                    f"— assuming neutral"
                )
                return {
                    "valid" : False,
                    "rate"  : 0.0,
                    "status": "unknown",
                    "pass"  : True,
                    "reason": "Funding rate unavailable — bypassed",
                    "score_bonus": 0,
                }

            # Simpan ke cache
            self._cache[pair] = {
                "rate": rate,
                "ts"  : time.time(),
            }

            return self._build_result(pair, rate, from_cache=False)

        except Exception as e:
            logger.error(f"❌ Funding rate error {pair}: {e}")
            return {
                "valid"      : False,
                "rate"       : 0.0,
                "status"     : "error",
                "pass"       : True,
                "reason"     : f"Funding error — bypassed: {e}",
                "score_bonus": 0,
            }

    def _build_result(self, pair: str, rate: float,
                      from_cache: bool = False) -> dict:
        """Build result dict dari funding rate value"""
        max_long  = cfg.FUNDING_RATE_MAX_LONG
        max_short = cfg.FUNDING_RATE_MAX_SHORT

        if rate > max_long:
            status = "high_positive"
        elif rate < max_short:
            status = "high_negative"
        else:
            status = "normal"

        source = "cache" if from_cache else "live"
        logger.debug(
            f"💰 Funding {pair}: {rate:+.4f}% "
            f"[{status}] ({source})"
        )

        return {
            "valid"      : True,
            "pair"       : pair,
            "rate"       : rate,
            "rate_raw"   : rate / 100,
            "status"     : status,
            "max_long"   : max_long,
            "max_short"  : max_short,
            "from_cache" : from_cache,
        }

    # ─── FUNDING FILTER ─────────────────────

    def check_funding_filter(self,
                              direction: str,
                              funding_data: dict) -> dict:
        """
        Filter entry berdasarkan funding rate.

        Score bonus:
          +1 → funding rate normal (pasar seimbang)
           0 → funding extreme tapi arah masih oke
          FAIL → funding extreme berlawanan arah entry
        """
        try:
            if not funding_data.get("valid"):
                return {
                    "pass"       : True,
                    "reason"     : "Funding unavailable — bypassed",
                    "score_bonus": 0,
                }

            rate   = funding_data.get("rate", 0)
            status = funding_data.get("status", "normal")

            if status == "normal":
                # Funding seimbang → bonus +1
                return {
                    "pass"       : True,
                    "reason"     : (
                        f"✅ Funding rate normal "
                        f"({rate:+.4f}%) — pasar seimbang"
                    ),
                    "score_bonus": 1,
                }

            elif status == "high_positive":
                # Funding sangat positif = longs overpaying
                if direction == "BUY":
                    # BUY saat longs sudah overcrowded → berisiko
                    return {
                        "pass"       : False,
                        "reason"     : (
                            f"❌ Funding {rate:+.4f}% terlalu positif "
                            f"— longs overcrowded, institusi siap flush"
                        ),
                        "score_bonus": 0,
                    }
                else:
                    # SELL saat funding positif → favorable
                    return {
                        "pass"       : True,
                        "reason"     : (
                            f"✅ Funding {rate:+.4f}% positif tinggi "
                            f"— mendukung SELL (long squeeze potential)"
                        ),
                        "score_bonus": 1,
                    }

            elif status == "high_negative":
                # Funding sangat negatif = shorts overpaying
                if direction == "SELL":
                    # SELL saat shorts sudah overcrowded → berisiko
                    return {
                        "pass"       : False,
                        "reason"     : (
                            f"❌ Funding {rate:+.4f}% terlalu negatif "
                            f"— shorts overcrowded, institusi siap squeeze"
                        ),
                        "score_bonus": 0,
                    }
                else:
                    # BUY saat funding negatif → favorable
                    return {
                        "pass"       : True,
                        "reason"     : (
                            f"✅ Funding {rate:+.4f}% negatif tinggi "
                            f"— mendukung BUY (short squeeze potential)"
                        ),
                        "score_bonus": 1,
                    }

            return {
                "pass"       : True,
                "reason"     : f"Funding {rate:+.4f}% — status unknown",
                "score_bonus": 0,
            }

        except Exception as e:
            logger.error(f"❌ Funding filter error: {e}")
            return {
                "pass"       : True,
                "reason"     : f"Funding filter error — bypassed: {e}",
                "score_bonus": 0,
            }

    # ─── FULL ANALYSIS ──────────────────────

    def analyze(self, pair: str, direction: str) -> dict:
        """
        Full funding rate analysis untuk satu pair.
        Dipanggil dari main.py setelah pair ditentukan.

        Return dict:
          valid        → data berhasil di-fetch
          rate         → funding rate dalam persen
          status       → normal / high_positive / high_negative
          pass         → boleh entry atau tidak
          score_bonus  → poin bonus confluence (0/1)
          reason       → teks untuk log/notif Telegram
        """
        try:
            if not cfg.FUNDING_RATE_ENABLED:
                return {
                    "valid"      : False,
                    "rate"       : 0.0,
                    "status"     : "disabled",
                    "pass"       : True,
                    "score_bonus": 0,
                    "reason"     : "Funding rate filter disabled",
                }

            funding_data = self.get_funding_rate(pair)
            filter_res   = self.check_funding_filter(
                direction, funding_data
            )

            return {
                "valid"      : funding_data.get("valid", False),
                "rate"       : funding_data.get("rate", 0.0),
                "status"     : funding_data.get("status", "unknown"),
                "pass"       : filter_res.get("pass", True),
                "score_bonus": filter_res.get("score_bonus", 0),
                "reason"     : filter_res.get("reason", ""),
                "pair"       : pair,
                "direction"  : direction,
            }

        except Exception as e:
            logger.error(f"❌ Funding analyze error {pair}: {e}")
            return {
                "valid"      : False,
                "rate"       : 0.0,
                "status"     : "error",
                "pass"       : True,
                "score_bonus": 0,
                "reason"     : f"Funding analyze error — bypassed: {e}",
            }


# Instance siap pakai
funding_filter = FundingRateFilter()