# ============================================
# VORTEX BOT - BYBIT EXCHANGE ADAPTER
# ============================================

import ccxt
from config import cfg
from logger import logger


class BybitExchange:

    def __init__(self):
        self.exchange = self._connect()
        self.name     = "Bybit"

    def _connect(self):
        """Koneksi ke Bybit"""
        try:
            exchange = ccxt.bybit({
                "apiKey" : cfg.BYBIT_API_KEY,
                "secret" : cfg.BYBIT_API_SECRET,
                "options": {
                    "defaultType": "future",
                },
                "enableRateLimit": True,
                "timeout"        : 30000,
            })

            if cfg.IS_TESTNET:
                exchange.set_sandbox_mode(True)
                logger.info("🔧 Connected to Bybit TESTNET")
            else:
                logger.info("🚀 Connected to Bybit LIVE")

            return exchange

        except Exception as e:
            logger.error(f"❌ Bybit connection failed: {e}")
            raise

    def get_ohlcv(self, pair: str,
                  timeframe: str,
                  limit: int = 200) -> list:
        try:
            ohlcv = self.exchange.fetch_ohlcv(
                pair, timeframe, limit=limit
            )
            return ohlcv
        except Exception as e:
            logger.error(
                f"❌ OHLCV error {pair} {timeframe}: {e}"
            )
            return []

    def get_ticker(self, pair: str) -> dict:
        try:
            ticker = self.exchange.fetch_ticker(pair)
            return {
                "pair"  : pair,
                "bid"   : ticker.get("bid", 0),
                "ask"   : ticker.get("ask", 0),
                "last"  : ticker.get("last", 0),
                "volume": ticker.get("quoteVolume", 0),
                "change": ticker.get("percentage", 0),
            }
        except Exception as e:
            logger.error(f"❌ Ticker error {pair}: {e}")
            return {}

    def get_orderbook(self, pair: str,
                      limit: int = 20) -> dict:
        try:
            ob = self.exchange.fetch_order_book(pair, limit)
            return {
                "bids": ob.get("bids", []),
                "asks": ob.get("asks", []),
            }
        except Exception as e:
            logger.error(f"❌ Orderbook error {pair}: {e}")
            return {}

    def get_balance(self) -> dict:
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

    def get_positions(self) -> list:
        try:
            positions = self.exchange.fetch_positions()
            return [
                p for p in positions
                if float(p.get("contracts", 0) or 0) > 0
            ]
        except Exception as e:
            logger.error(f"❌ Positions error: {e}")
            return []

    def set_leverage(self, pair: str,
                     leverage: int) -> bool:
        try:
            leverage = min(leverage, cfg.MAX_LEVERAGE)
            leverage = max(leverage, 1)
            self.exchange.set_leverage(leverage, pair)
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

    def calculate_position_size(self,
                                balance : float,
                                entry   : float,
                                sl      : float,
                                risk_pct: float,
                                leverage: int) -> float:
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

    def place_market_order(self, pair: str,
                           side    : str,
                           quantity: float) -> dict:
        try:
            order = self.exchange.create_market_order(
                pair, side.lower(), quantity
            )
            logger.info(
                f"✅ Market order: {side} {pair} "
                f"qty={quantity}"
            )
            return order
        except Exception as e:
            logger.error(f"❌ Market order error: {e}")
            return {}

    def place_limit_order(self, pair    : str,
                          side    : str,
                          quantity: float,
                          price   : float) -> dict:
        try:
            order = self.exchange.create_limit_order(
                pair, side.lower(), quantity, price
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
        try:
            sl_side = (
                "sell" if side.lower() == "buy" else "buy"
            )
            order = self.exchange.create_order(
                pair, "stop_market", sl_side,
                quantity, None,
                {"stopPrice": sl_price, "reduceOnly": True}
            )
            logger.info(f"🛡️ SL placed: {pair} @ {sl_price}")
            return order
        except Exception as e:
            logger.error(f"❌ SL order error: {e}")
            return {}

    def place_take_profit(self, pair    : str,
                          side    : str,
                          quantity: float,
                          tp_price: float) -> dict:
        try:
            tp_side = (
                "sell" if side.lower() == "buy" else "buy"
            )
            order = self.exchange.create_order(
                pair, "take_profit_market", tp_side,
                quantity, None,
                {"stopPrice": tp_price, "reduceOnly": True}
            )
            logger.info(f"🎯 TP placed: {pair} @ {tp_price}")
            return order
        except Exception as e:
            logger.error(f"❌ TP order error: {e}")
            return {}

    def cancel_order(self, pair    : str,
                     order_id: str) -> bool:
        try:
            self.exchange.cancel_order(order_id, pair)
            logger.info(f"❌ Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Cancel order error: {e}")
            return False

    def cancel_all_orders(self, pair: str) -> bool:
        try:
            self.exchange.cancel_all_orders(pair)
            logger.info(f"❌ All orders cancelled: {pair}")
            return True
        except Exception as e:
            logger.error(
                f"❌ Cancel all orders error: {e}"
            )
            return False

    def close_position(self, pair    : str,
                       side    : str,
                       quantity: float) -> dict:
        try:
            close_side = (
                "sell" if side.lower() == "buy" else "buy"
            )
            order = self.exchange.create_market_order(
                pair, close_side, quantity,
                {"reduceOnly": True}
            )
            logger.info(
                f"🔒 Position closed: {pair} qty={quantity}"
            )
            return order
        except Exception as e:
            logger.error(f"❌ Close position error: {e}")
            return {}

    def set_trailing_stop(self, pair       : str,
                          trail_value: float) -> bool:
        try:
            self.exchange.set_trading_stop(
                pair, trailingStop=trail_value
            )
            logger.info(
                f"🔄 Trailing stop: {pair} = {trail_value}"
            )
            return True
        except Exception as e:
            logger.error(f"❌ Trailing stop error: {e}")
            return False

    def get_market_info(self, pair: str) -> dict:
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

    def is_connected(self) -> bool:
        try:
            self.exchange.fetch_time()
            return True
        except Exception as e:
            logger.error(f"❌ Connection check: {e}")
            return False


# Instance siap pakai
bybit = BybitExchange()