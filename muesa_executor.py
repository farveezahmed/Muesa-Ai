import ccxt
import math

class MuesaExecutor:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.exchange = ccxt.binance({
            'apiKey': api_key, 'secret': api_secret, 'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        if testnet: self.exchange.set_sandbox_mode(True)

    def prep_market_conditions(self, symbol: str, leverage: int = 5, margin_type: str = 'cross'):
        try: self.exchange.fapiPrivate_post_margintype({'symbol': self.exchange.market_id(symbol), 'marginType': margin_type.upper()})
        except: pass 
        try: self.exchange.set_leverage(leverage, symbol)
        except Exception as e: print(f"Error setting leverage: {e}")

    def get_precision(self, symbol: str):
        market = self.exchange.load_markets()[symbol]
        return market['precision']['amount'], market['precision']['price']

    def execute_trade(self, setup_data: dict):
        symbol = setup_data['coin'] + "/USDT:USDT"
        side = 'buy' if setup_data.get('trade_type', 'LONG') == 'LONG' else 'sell'
        
        self.prep_market_conditions(symbol, leverage=setup_data['leverage'], margin_type='cross')
        
        notional_value = setup_data['allocation'] * setup_data['leverage']
        raw_quantity = notional_value / setup_data['entry_price']
        
        amount_precision, price_precision = self.get_precision(symbol)
        
        amount_str = f"{raw_quantity:f}"
        if '.' in amount_str:
            decimals = str(amount_precision).count('1') if amount_precision < 1 else 0
            qty = float(amount_str[:amount_str.find('.') + decimals + 1])
        else:
            qty = float(amount_str)

        sl_price = round(setup_data['stop_loss'], int(abs(math.log10(price_precision))))
        tp_price = round(setup_data['target'], int(abs(math.log10(price_precision))))

        print(f"Executing {side.upper()} on {symbol} | Qty: {qty} | SL: {sl_price} | TP: {tp_price}")

        try:
            order = self.exchange.create_order(
                symbol=symbol, type='market', side=side, amount=qty,
                params={'stopLossPrice': sl_price, 'takeProfitPrice': tp_price, 'reduceOnly': False, 'timeInForce': 'GTC'}
            )
            print(f"✅ MUESA EXECUTION SUCCESSFUL! Order ID: {order['id']}")
            return True
        except Exception as e:
            print(f"❌ EXECUTION FAILED: {e}")
            return False
