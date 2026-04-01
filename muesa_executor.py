import os
import math
import ccxt

class MuesaExecutor:
    def __init__(self):
        self.exchange = ccxt.binance({
            'apiKey': os.getenv('BINANCE_API_KEY'),
            'secret': os.getenv('BINANCE_SECRET_KEY'),
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })

    def prep_market_conditions(self, symbol):
        try:
            self.exchange.fapiPrivate_post_margintype({
                'symbol': self.exchange.market_id(symbol),
                'marginType': 'ISOLATED'
            })
        except:
            pass
        try:
            self.exchange.set_leverage(5, symbol)
            print(f"✅ Leverage set to 5x for {symbol}")
        except Exception as e:
            print(f"Leverage error: {e}")

    def get_step_size(self, symbol):
        try:
            markets = self.exchange.load_markets()
            market = markets[symbol]
            for f in market.get('filters', []):
                if f.get('filterType') == 'LOT_SIZE':
                    return float(f['stepSize'])
            return 0.001
        except Exception as e:
            print(f"Precision error: {e}")
            return 0.001

    def get_price_precision(self, symbol):
        try:
            markets = self.exchange.load_markets()
            market = markets[symbol]
            for f in market.get('filters', []):
                if f.get('filterType') == 'PRICE_FILTER':
                    return float(f['tickSize'])
            return 0.0001
        except Exception as e:
            print(f"Price precision error: {e}")
            return 0.0001

    def get_balance(self):
        try:
            balance = self.exchange.fetch_balance({'type': 'future'})
            return float(balance['USDT']['free'])
        except Exception as e:
            print(f"Balance error: {e}")
            return 0.0

    def calculate_qty(self, symbol, price):
        balance = self.get_balance()
        allocation = balance * 0.25  # 25% of wallet
        notional = allocation * 5    # 5x leverage
        raw_qty = notional / price
        step = self.get_step_size(symbol)
        qty = math.floor(raw_qty / step) * step
        return round(qty, 8)

    def execute_trade(self, symbol, direction, entry_price, sl, tp1, tp2):
        try:
            side = 'buy' if direction == 'LONG' else 'sell'
            opp_side = 'sell' if direction == 'LONG' else 'buy'

            self.prep_market_conditions(symbol)

            qty = self.calculate_qty(symbol, entry_price)
            if qty <= 0:
                print(f"❌ Invalid quantity for {symbol}")
                return False

            tick = self.get_price_precision(symbol)
            decimals = max(0, round(-math.log10(tick)))
            sl_price  = round(sl,  decimals)
            tp1_price = round(tp1, decimals)
            tp2_price = round(tp2, decimals)

            step = self.get_step_size(symbol)
            half_qty = math.floor((qty / 2) / step) * step
            tp2_qty  = math.floor((qty - half_qty) / step) * step

            print(f"📤 {direction} | {symbol} | Qty: {qty} | Entry: {entry_price} | SL: {sl_price} | TP1: {tp1_price} | TP2: {tp2_price}")

            order = self.exchange.create_order(
                symbol=symbol,
                type='market',
                side=side,
                amount=qty
            )
            print(f"✅ Entry order placed: {order['id']}")

            # SL — full quantity
            self.exchange.create_order(
                symbol=symbol,
                type='STOP_MARKET',
                side=opp_side,
                amount=qty,
                params={
                    'stopPrice': sl_price,
                    'reduceOnly': True,
                    'timeInForce': 'GTC'
                }
            )
            print(f"🛑 SL placed at {sl_price}")

            # TP1 — 50% quantity
            self.exchange.create_order(
                symbol=symbol,
                type='TAKE_PROFIT_MARKET',
                side=opp_side,
                amount=half_qty,
                params={
                    'stopPrice': tp1_price,
                    'reduceOnly': True,
                    'timeInForce': 'GTC'
                }
            )
            print(f"🎯 TP1 placed at {tp1_price} (qty: {half_qty})")

            # TP2 — remaining 50%
            self.exchange.create_order(
                symbol=symbol,
                type='TAKE_PROFIT_MARKET',
                side=opp_side,
                amount=tp2_qty,
                params={
                    'stopPrice': tp2_price,
                    'reduceOnly': True,
                    'timeInForce': 'GTC'
                }
            )
            print(f"🎯 TP2 placed at {tp2_price} (qty: {tp2_qty})")

            return True

        except Exception as e:
            print(f"❌ Execution failed: {e}")
            try:
                opp_side = 'sell' if direction == 'LONG' else 'buy'
                self.exchange.create_market_order(
                    symbol, opp_side, qty,
                    params={'reduceOnly': True}
                )
                print(f"🚨 Emergency close executed for {symbol}")
            except:
                pass
            return False
