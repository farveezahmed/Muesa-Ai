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

    # ─── SET MARGIN AND LEVERAGE ──────────────────────────────────────────────
    def prep_market_conditions(self, symbol):
        # Set ISOLATED margin
        try:
            self.exchange.fapiPrivate_post_margintype({
                'symbol': self.exchange.market_id(symbol),
                'marginType': 'ISOLATED'
            })
        except:
            pass

        # Set 5x leverage
        try:
            self.exchange.set_leverage(5, symbol)
            print(f"✅ Leverage set to 5x for {symbol}")
        except Exception as e:
            print(f"Leverage error: {e}")

    # ─── GET PRECISION ────────────────────────────────────────────────────────
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

    # ─── GET WALLET BALANCE ───────────────────────────────────────────────────
    def get_balance(self):
        try:
            balance = self.exchange.fetch_balance({'type': 'future'})
            return float(balance['USDT']['free'])
        except Exception as e:
            print(f"Balance error: {e}")
            return 0.0

    # ─── CALCULATE QUANTITY ───────────────────────────────────────────────────
    def calculate_qty(self, symbol, price):
        balance = self.get_balance()
        allocation = balance * 0.25  # 25% of wallet
        notional = allocation * 5    # 5x leverage
        raw_qty = notional / price

        step = self.get_step_size(symbol)
        qty = math.floor(raw_qty / step) * step
