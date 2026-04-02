import os
import time
import ccxt
from datetime import datetime, timedelta
from muesa_logic import (
    set_cooldown, log_trade, increment_trade_count, is_on_cooldown
)
from muesa_telegram import trade_alert, sl_alert, tp_alert, system_alert

# ─── EXCHANGE SETUP ───────────────────────────────────────────────────────────
def get_exchange():
    return ccxt.binance({
        'apiKey': os.getenv('BINANCE_API_KEY'),
        'secret': os.getenv('BINANCE_SECRET_KEY'),
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })

# ─── GET WALLET BALANCE ───────────────────────────────────────────────────────
def get_wallet_balance(exchange):
    try:
        balance = exchange.fetch_balance({'type': 'future'})
        return float(balance['USDT']['free'])
    except Exception as e:
        print(f"Balance error: {e}")
        return 0.0

# ─── GET QUANTITY ─────────────────────────────────────────────────────────────
def get_quantity(exchange, symbol, price):
    try:
        balance    = get_wallet_balance(exchange)
        allocation = balance * 0.25          # 25% per trade
        raw_qty    = (allocation * 5) / price # 5x leverage

        markets = exchange.load_markets()
        market  = markets[symbol]
        step    = float(market['filters'][1]['stepSize']) if 'filters' in market else 0.001
        qty     = round(raw_qty - (raw_qty % step), 8)
        return qty
    except Exception as e:
        print(f"Quantity error: {e}")
        return 0.0

# ─── EXECUTE TRADE ────────────────────────────────────────────────────────────
def execute_trade(symbol, direction, entry_price, sl, tp1, tp2, sco
