# ============================================
# VORTEX BOT - OKX EXCHANGE ADAPTER
# ============================================

import ccxt
from config import cfg
from logger import logger


class OKXExchange:

    def __init__(self):
        # Virtual balance untuk demo mode
        self._virtual_balance = float(cfg.CAPITAL)
        self._virtual_used    = 0.0
        self.exchange         = self._connect()
        self.name             = "OKX"

    # ─── CONNECTION ─────────────────────────

    def _connect(self):
        """Koneksi ke OKX Demo atau Live"""
        try:
            exchange = ccxt.okx({
                "apiKey"  : cfg.OKX_API_KEY,
                "secret"  : cfg.OKX_API_SECRET,
                "password": cfg.OKX_PASSPHRASE,
                "options" : {
                    "defaultType": "swap",
                    "broker"     : "",
                },
                "enableRateLimit": True,
                "timeout"        : 30000,
            })

            if cfg.IS_OKX_DEMO:
                exchange.headers = {
                    "x-simulated-trading": "1"
                }
                logger.info("🔧 Connected to OKX DEMO")
            else:
                logger.info("🚀 Connected to OKX LIVE")

            return exchange

        except Exception as e:
            logger.error(f"❌ OKX connection failed: {e}")
            raise

    def is_connected(self) -> bool:
        """Cek koneksi OKX"""
        try:
            self.exchange.fetch_time()
            logger.info("✅ OKX connection OK!")
            return True
        except Exception as e:
            logger.error(f"❌ OKX connection check: {e}")
            return False

    # ─── MARKET DATA ────────────────────────

    def get_ohlcv(self, pair     : str,
                  timeframe : str,
                  limit     : int = 200) -> list:
        """Ambil data OHLCV"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(
                pair, timeframe, limit=limit
            )
            logger.debug(
                f"📊 OHLCV: {pair} {timeframe} "
                f"({len(ohlcv)} candles)"
            )
            return ohlcv
        except Exception as e:
            logger.error(
                f"❌ OHLCV error {pair} {timeframe}: {e}"
            )
            return []

    def get_ticker(self, pair: str) -> dict:
        """Ambil harga terkini"""
        try:
            ticker = self.exchange.fetch_ticker(pair)
            return {
                "pair"  : pair,
                "bid"   : float(ticker.get("bid",  0) or 0),
                "ask"   : float(ticker.get("ask",  0) or 0),
                "last"  : float(ticker.get("last", 0) or 0),
                "volume": float(
                    ticker.get("quoteVolume", 0) or 0
                ),
                "change": float(
                    ticker.get("percentage",  0) or 0
                ),
            }
        except Exception as e:
            logger.error(f"❌ Ticker error {pair}: {e}")
            return {}

    def get_orderbook(self, pair : str,
                      limit: int = 20) -> dict:
        """Ambil order book"""
        try:
            ob = self.exchange.fetch_order_book(pair, limit)
            return {
                "bids": ob.get("bids", []),
                "asks": ob.get("asks", []),
            }
        except Exception as e:
            logger.error(f"❌ Orderbook error {pair}: {e}")
            return {}

    # ─── ACCOUNT ────────────────────────────

    def get_balance(self) -> dict:
        """
        Ambil saldo akun USDT.
        OKX Demo tidak support fetch balance via API,
        jadi kita pakai virtual balance dari CAPITAL config.
        """
        # Demo mode → pakai virtual balance
        if cfg.IS_OKX_DEMO:
            free  = max(
                0.0,
                self._virtual_balance - self._virtual_used
            )
            result = {
                "total": self._virtual_balance,
                "free" : free,
                "used" : self._virtual_used,
            }
            logger.debug(
                f"💰 Virtual balance: "
                f"total=${self._virtual_balance:.4f} "
                f"free=${free:.4f} "
                f"used=${self._virtual_used:.4f}"
            )
            return result

        # Live mode → fetch dari exchange
        try:
            balance = self.exchange.fetch_balance()
            usdt    = balance.get("USDT", {})
            result  = {
                "total": float(usdt.get("total", 0) or 0),
                "free" : float(usdt.get("free",  0) or 0),
                "used" : float(usdt.get("used",  0) or 0),
            }
            logger.debug(f"💰 Balance: {result}")
            return result
        except Exception as e:
            logger.error(f"❌ Balance error: {e}")
            return {"total": 0, "free": 0, "used": 0}

    def update_virtual_balance(self, pnl: float):
        """
        Update virtual balance setelah trade close.
        Dipanggil dari main.py saat trade selesai.
        """
        if cfg.IS_OKX_DEMO:
            self._virtual_balance += pnl
            self._virtual_balance  = max(
                0.0, self._virtual_balance
            )
            logger.info(
                f"💰 Virtual balance updated: "
                f"${self._virtual_balance:.4f} "
                f"({'+'if pnl >= 0 else ''}{pnl:.4f})"
            )

    def reserve_balance(self, amount: float):
        """Reserve balance saat open trade"""
        if cfg.IS_OKX_DEMO:
            self._virtual_used += amount
            logger.debug(
                f"💰 Reserved: ${amount:.4f} | "
                f"Used: ${self._virtual_used:.4f}"
            )

    def release_balance(self, amount: float):
        """Release balance saat close trade"""
        if cfg.IS_OKX_DEMO:
            self._virtual_used = max(
                0.0, self._virtual_used - amount
            )
            logger.debug(
                f"💰 Released: ${amount:.4f} | "
                f"Used: ${self._virtual_used:.4f}"
            )

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
        """Set leverage untuk pair"""
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
            # Di demo mode, return mock order
            if cfg.IS_OKX_DEMO:
                logger.info(
                    f"📝 Demo mock order: {side} {pair}"
                )
                return {
                    "id"    : f"demo_{int(__import__('time').time())}",
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
                pair,
                "stop",
                sl_side,
                quantity,
                sl_price,
                params={
                    "stopLossPrice": sl_price,
                    "tdMode"       : "cross",
                    "reduceOnly"   : True,
                }
            )
            logger.info(f"🛡️ SL placed: {pair} @ {sl_price}")
            return order
        except Exception as e:
            logger.error(f"❌ SL order error: {e}")
            # Demo mode → log saja, tidak crash
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
                pair,
                "stop",
                tp_side,
                quantity,
                tp_price,
                params={
                    "takeProfitPrice": tp_price,
                    "tdMode"         : "cross",
                    "reduceOnly"     : True,
                }
            )
            logger.info(f"🎯 TP placed: {pair} @ {tp_price}")
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
            if order_id.startswith("demo_"):
                return True
            self.exchange.cancel_order(order_id, pair)
            logger.info(f"❌ Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Cancel order error: {e}")
            return False

    def cancel_all_orders(self, pair: str) -> bool:
        """Cancel semua order"""
        try:
            self.exchange.cancel_all_orders(pair)
            logger.info(f"❌ All orders cancelled: {pair}")
            return True
        except Exception as e:
            logger.error(
                f"❌ Cancel all orders error: {e}"
            )
            if cfg.IS_OKX_DEMO:
                return True
            return False

    def close_position(self, pair    : str,
                       side    : str,
                       quantity: float) -> dict:
        """Close posisi"""
        try:
            close_side = (
                "sell" if side.lower() == "buy" else "buy"
            )
            order = self.exchange.create_market_order(
                pair,
                close_side,
                quantity,
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
                    f"📝 Demo close noted: {pair}"
                )
                return {
                    "id"    : "demo_close",
                    "status": "closed"
                }
            return {}

    # ─── MARKET INFO ────────────────────────

    def get_market_info(self, pair: str) -> dict:
        """Ambil info market"""
        try:
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
                "price_precision" : precision.get("price", 2),
            }
        except Exception as e:
            logger.error(f"❌ Market info error: {e}")
            return {}


# Instance siap pakai
okx = OKXExchange()