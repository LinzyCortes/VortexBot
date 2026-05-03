# ============================================
# VORTEX BOT - OKX EXCHANGE ADAPTER
# ============================================

import ccxt
import requests as req
from config import cfg
from logger import logger


class OKXExchange:

    def __init__(self):
        self._virtual_balance = float(cfg.CAPITAL)
        self._virtual_used    = 0.0
        self.exchange         = self._connect()
        self.name             = "OKX"

    # ─── CONNECTION ─────────────────────────

    def _connect(self):
        """Koneksi ke OKX Demo atau Live"""
        try:
            params = {
                "apiKey"  : cfg.OKX_API_KEY,
                "secret"  : cfg.OKX_API_SECRET,
                "password": cfg.OKX_PASSPHRASE,
                "options" : {
                    "defaultType": "swap",
                    "broker"     : "",
                },
                "enableRateLimit": True,
                "timeout"        : 30000,
            }

            if cfg.IS_OKX_DEMO:
                params["headers"] = {
                    "x-simulated-trading": "1"
                }
                logger.info("🔧 Connected to OKX DEMO")
            else:
                logger.info("🚀 Connected to OKX LIVE")

            return ccxt.okx(params)

        except Exception as e:
            logger.error(f"❌ OKX connection failed: {e}")
            raise

    def is_connected(self) -> bool:
        """Cek koneksi OKX via public endpoint"""
        try:
            # Pakai public endpoint — tidak kena demo limit
            resp = req.get(
                "https://www.okx.com/api/v5/public/time",
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == "0":
                    logger.info("✅ OKX connection OK!")
                    return True
            logger.error("❌ OKX public endpoint error")
            return False
        except Exception as e:
            logger.error(f"❌ OKX connection check: {e}")
            return False

    # ─── MARKET DATA (Public API) ────────────

    def get_ohlcv(self, pair    : str,
                  timeframe: str,
                  limit    : int = 200) -> list:
        """
        Ambil OHLCV via OKX Public API.
        Tidak butuh auth → tidak kena demo limit!
        """
        try:
            # Konversi timeframe ke format OKX
            tf_map = {
                "1m" : "1m",  "3m" : "3m",
                "5m" : "5m",  "15m": "15m",
                "30m": "30m", "1h" : "1H",
                "1H" : "1H",  "2H" : "2H",
                "4h" : "4H",  "4H" : "4H",
                "6H" : "6H",  "12H": "12H",
                "1d" : "1D",  "1D" : "1D",
            }
            bar = tf_map.get(timeframe, timeframe.upper())

            # Konversi pair format kalau perlu
            # BTC/USDT → BTC-USDT-SWAP
            # BTC-USDT-SWAP → BTC-USDT-SWAP (sudah benar)
            inst_id = pair
            if "/" in pair:
                base, quote = pair.split("/")
                inst_id = f"{base}-{quote}-SWAP"

            resp = req.get(
                "https://www.okx.com/api/v5/market/candles",
                params={
                    "instId": inst_id,
                    "bar"   : bar,
                    "limit" : str(min(limit, 300)),
                },
                timeout=15,
            )

            if resp.status_code != 200:
                logger.error(
                    f"❌ OHLCV HTTP {resp.status_code}: "
                    f"{pair} {timeframe}"
                )
                return []

            data = resp.json()
            if data.get("code") != "0":
                logger.error(
                    f"❌ OHLCV API error: "
                    f"{data.get('msg')} | {pair}"
                )
                return []

            candles = data.get("data", [])
            if not candles:
                logger.warning(
                    f"⚠️ No candle data: {pair} {timeframe}"
                )
                return []

            # OKX format: [ts, o, h, l, c, vol, volCcy, ...]
            # ccxt format: [ts, o, h, l, c, vol]
            result = []
            for c in reversed(candles):
                result.append([
                    int(c[0]),    # timestamp ms
                    float(c[1]),  # open
                    float(c[2]),  # high
                    float(c[3]),  # low
                    float(c[4]),  # close
                    float(c[5]),  # volume
                ])

            logger.debug(
                f"📊 OHLCV: {inst_id} {bar} "
                f"({len(result)} candles)"
            )
            return result

        except Exception as e:
            logger.error(
                f"❌ OHLCV error {pair} {timeframe}: {e}"
            )
            return []

    def get_ticker(self, pair: str) -> dict:
        """Ambil harga terkini via Public API"""
        try:
            inst_id = pair
            if "/" in pair:
                base, quote = pair.split("/")
                inst_id = f"{base}-{quote}-SWAP"

            resp = req.get(
                "https://www.okx.com/api/v5/market/ticker",
                params={"instId": inst_id},
                timeout=10,
            )

            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == "0" and data.get("data"):
                    t = data["data"][0]
                    return {
                        "pair"  : pair,
                        "bid"   : float(t.get("bidPx",  0) or 0),
                        "ask"   : float(t.get("askPx",  0) or 0),
                        "last"  : float(t.get("last",   0) or 0),
                        "volume": float(t.get("vol24h", 0) or 0),
                        "change": float(t.get("sodUtc8",0) or 0),
                    }

            # Fallback ke ccxt
            ticker = self.exchange.fetch_ticker(pair)
            return {
                "pair"  : pair,
                "bid"   : float(ticker.get("bid",         0) or 0),
                "ask"   : float(ticker.get("ask",         0) or 0),
                "last"  : float(ticker.get("last",        0) or 0),
                "volume": float(ticker.get("quoteVolume", 0) or 0),
                "change": float(ticker.get("percentage",  0) or 0),
            }

        except Exception as e:
            logger.error(f"❌ Ticker error {pair}: {e}")
            return {}

    def get_orderbook(self, pair : str,
                      limit: int = 20) -> dict:
        """Ambil order book"""
        try:
            inst_id = pair
            if "/" in pair:
                base, quote = pair.split("/")
                inst_id = f"{base}-{quote}-SWAP"

            resp = req.get(
                "https://www.okx.com/api/v5/market/books",
                params={"instId": inst_id, "sz": str(limit)},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == "0" and data.get("data"):
                    ob = data["data"][0]
                    return {
                        "bids": [
                            [float(b[0]), float(b[1])]
                            for b in ob.get("bids", [])
                        ],
                        "asks": [
                            [float(a[0]), float(a[1])]
                            for a in ob.get("asks", [])
                        ],
                    }
            return {}
        except Exception as e:
            logger.error(f"❌ Orderbook error {pair}: {e}")
            return {}

    # ─── ACCOUNT ────────────────────────────

    def get_balance(self) -> dict:
        """
        Ambil saldo.
        Demo → virtual balance (OKX Demo tidak support API)
        Live → fetch dari exchange
        """
        if cfg.IS_OKX_DEMO:
            free   = max(
                0.0, self._virtual_balance - self._virtual_used
            )
            result = {
                "total": self._virtual_balance,
                "free" : free,
                "used" : self._virtual_used,
            }
            logger.debug(
                f"💰 Virtual: total=${self._virtual_balance:.4f} "
                f"free=${free:.4f} used=${self._virtual_used:.4f}"
            )
            return result

        try:
            balance = self.exchange.fetch_balance()
            usdt    = balance.get("USDT", {})
            return {
                "total": float(usdt.get("total", 0) or 0),
                "free" : float(usdt.get("free",  0) or 0),
                "used" : float(usdt.get("used",  0) or 0),
            }
        except Exception as e:
            logger.error(f"❌ Balance error: {e}")
            return {"total": 0, "free": 0, "used": 0}

    def update_virtual_balance(self, pnl: float):
        """Update virtual balance setelah trade (compound!)"""
        if cfg.IS_OKX_DEMO:
            old = self._virtual_balance
            self._virtual_balance = max(
                0.0, self._virtual_balance + pnl
            )
            sign = "+" if pnl >= 0 else ""
            logger.info(
                f"💰 Compound: ${old:.4f} → "
                f"${self._virtual_balance:.4f} "
                f"({sign}{pnl:.4f})"
            )

    def reserve_balance(self, amount: float):
        """Reserve balance saat open trade"""
        if cfg.IS_OKX_DEMO:
            self._virtual_used += amount
            logger.debug(f"💰 Reserved: ${amount:.4f}")

    def release_balance(self, amount: float):
        """Release balance saat close trade"""
        if cfg.IS_OKX_DEMO:
            self._virtual_used = max(
                0.0, self._virtual_used - amount
            )
            logger.debug(f"💰 Released: ${amount:.4f}")

    def get_positions(self) -> list:
        """Ambil posisi terbuka"""
        try:
            positions = self.exchange.fetch_positions()
            return [
                p for p in positions
                if float(p.get("contracts", 0) or 0) > 0
            ]
        except Exception as e:
            logger.error(f"❌ Positions error: {e}")
            return []

    # ─── LEVERAGE ───────────────────────────

    def set_leverage(self, pair    : str,
                     leverage: int) -> bool:
        """Set leverage"""
        try:
            leverage = max(1, min(leverage, cfg.MAX_LEVERAGE))
            self.exchange.set_leverage(
                leverage, pair,
                params={"mgnMode": "cross"}
            )
            logger.info(f"⚙️ Leverage: {pair} = {leverage}x")
            return True
        except Exception as e:
            logger.error(f"❌ Leverage error {pair}: {e}")
            if cfg.IS_OKX_DEMO:
                logger.info(
                    f"📝 Demo leverage noted: {leverage}x"
                )
                return True
            return False

    def calculate_leverage(self,
                           balance : float,
                           entry   : float,
                           sl      : float,
                           risk_pct: float) -> int:
        """Hitung leverage optimal"""
        try:
            risk_amount = balance * (risk_pct / 100)
            sl_dist_pct = abs(entry - sl) / entry * 100
            if sl_dist_pct == 0:
                return 1
            leverage = round(
                risk_amount / (balance * sl_dist_pct / 100)
            )
            return max(1, min(leverage, cfg.MAX_LEVERAGE))
        except Exception as e:
            logger.error(f"❌ Leverage calc error: {e}")
            return 1

    # ─── POSITION SIZING ────────────────────

    def calculate_position_size(self,
                                balance : float,
                                entry   : float,
                                sl      : float,
                                risk_pct: float,
                                leverage: int) -> float:
        """Hitung ukuran posisi"""
        try:
            risk_amount   = balance * (risk_pct / 100)
            sl_dist_pct   = abs(entry - sl) / entry
            if sl_dist_pct == 0:
                return 0
            position_usdt = min(
                risk_amount / sl_dist_pct,
                balance * leverage
            )
            return round(position_usdt / entry, 6)
        except Exception as e:
            logger.error(f"❌ Position size error: {e}")
            return 0

    # ─── ORDERS ─────────────────────────────

    def place_market_order(self, pair    : str,
                           side    : str,
                           quantity: float) -> dict:
        """Place market order"""
        try:
            order = self.exchange.create_market_order(
                pair,
                side.lower(),
                quantity,
                params={"tdMode": "cross"}
            )
            logger.info(
                f"✅ Market order: {side} {pair} "
                f"qty={quantity}"
            )
            return order
        except Exception as e:
            logger.error(f"❌ Market order error: {e}")
            if cfg.IS_OKX_DEMO:
                import time
                mock_id = f"demo_{int(time.time())}"
                logger.info(
                    f"📝 Demo mock order #{mock_id}: "
                    f"{side} {pair}"
                )
                return {
                    "id"    : mock_id,
                    "status": "closed",
                    "side"  : side,
                    "symbol": pair,
                    "amount": quantity,
                }
            return {}

    def place_limit_order(self, pair    : str,
                          side    : str,
                          quantity: float,
                          price   : float) -> dict:
        """Place limit order"""
        try:
            order = self.exchange.create_limit_order(
                pair,
                side.lower(),
                quantity,
                price,
                params={"tdMode": "cross"}
            )
            logger.info(
                f"✅ Limit order: {side} {pair} "
                f"qty={quantity} @ {price}"
            )
            return order
        except Exception as e:
            logger.error(f"❌ Limit order error: {e}")
            return {}

    def place_stop_loss(self, pair    : str,
                        side    : str,
                        quantity: float,
                        sl_price: float) -> dict:
        """Place stop loss"""
        try:
            sl_side = (
                "sell" if side.lower() == "buy" else "buy"
            )
            order = self.exchange.create_order(
                pair, "stop", sl_side, quantity, sl_price,
                params={
                    "stopLossPrice": sl_price,
                    "tdMode"       : "cross",
                    "reduceOnly"   : True,
                }
            )
            logger.info(
                f"🛡️ SL placed: {pair} @ {sl_price}"
            )
            return order
        except Exception as e:
            logger.error(f"❌ SL order error: {e}")
            if cfg.IS_OKX_DEMO:
                logger.info(
                    f"📝 Demo SL noted: {pair} @ {sl_price}"
                )
                return {"id": "demo_sl", "status": "open"}
            return {}

    def place_take_profit(self, pair    : str,
                          side    : str,
                          quantity: float,
                          tp_price: float) -> dict:
        """Place take profit"""
        try:
            tp_side = (
                "sell" if side.lower() == "buy" else "buy"
            )
            order = self.exchange.create_order(
                pair, "stop", tp_side, quantity, tp_price,
                params={
                    "takeProfitPrice": tp_price,
                    "tdMode"         : "cross",
                    "reduceOnly"     : True,
                }
            )
            logger.info(
                f"🎯 TP placed: {pair} @ {tp_price}"
            )
            return order
        except Exception as e:
            logger.error(f"❌ TP order error: {e}")
            if cfg.IS_OKX_DEMO:
                logger.info(
                    f"📝 Demo TP noted: {pair} @ {tp_price}"
                )
                return {"id": "demo_tp", "status": "open"}
            return {}

    def cancel_order(self, pair    : str,
                     order_id: str) -> bool:
        """Cancel order"""
        try:
            if str(order_id).startswith("demo_"):
                return True
            self.exchange.cancel_order(order_id, pair)
            logger.info(f"❌ Cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Cancel order error: {e}")
            return False

    def cancel_all_orders(self, pair: str) -> bool:
        """Cancel semua order"""
        try:
            self.exchange.cancel_all_orders(pair)
            logger.info(
                f"❌ All orders cancelled: {pair}"
            )
            return True
        except Exception as e:
            logger.error(
                f"❌ Cancel all orders error: {e}"
            )
            # Demo → anggap berhasil
            return cfg.IS_OKX_DEMO

    def close_position(self, pair    : str,
                       side    : str,
                       quantity: float) -> dict:
        """Close posisi"""
        try:
            close_side = (
                "sell" if side.lower() == "buy" else "buy"
            )
            order = self.exchange.create_market_order(
                pair, close_side, quantity,
                params={
                    "reduceOnly": True,
                    "tdMode"    : "cross",
                }
            )
            logger.info(
                f"🔒 Closed: {pair} qty={quantity}"
            )
            return order
        except Exception as e:
            logger.error(f"❌ Close position error: {e}")
            if cfg.IS_OKX_DEMO:
                logger.info(
                    f"📝 Demo close: {pair}"
                )
                return {
                    "id"    : "demo_close",
                    "status": "closed",
                }
            return {}

    # ─── MARKET INFO ────────────────────────

    def get_market_info(self, pair: str) -> dict:
        """Ambil info market"""
        try:
            inst_id = pair
            if "/" in pair:
                base, quote = pair.split("/")
                inst_id = f"{base}-{quote}-SWAP"

            resp = req.get(
                "https://www.okx.com/api/v5/public/instruments",
                params={
                    "instType": "SWAP",
                    "instId"  : inst_id,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == "0" and data.get("data"):
                    inst = data["data"][0]
                    return {
                        "min_amount"      : float(
                            inst.get("minSz", 0)
                        ),
                        "min_cost"        : 0,
                        "amount_precision": len(
                            inst.get("lotSz", "1").split(".")[-1]
                        ) if "." in inst.get("lotSz", "1") else 0,
                        "price_precision" : len(
                            inst.get("tickSz", "0.1").split(".")[-1]
                        ) if "." in inst.get("tickSz", "0.1") else 1,
                    }

            # Fallback ke ccxt
            markets   = self.exchange.load_markets()
            market    = markets.get(pair, {})
            limits    = market.get("limits", {})
            precision = market.get("precision", {})
            return {
                "min_amount"      : limits.get(
                    "amount", {}
                ).get("min", 0),
                "min_cost"        : limits.get(
                    "cost", {}
                ).get("min", 0),
                "amount_precision": precision.get("amount", 6),
                "price_precision" : precision.get("price",  2),
            }
        except Exception as e:
            logger.error(f"❌ Market info error: {e}")
            return {}


# Instance siap pakai
okx = OKXExchange()