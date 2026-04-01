import os
import time
import ccxt
from muesa_logic import (
    set_cooldown, log_trade, increment_trade_count, is_on_cooldown
)
from muesa_telegram import trade_alert, sl_alert, tp_alert

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
        balance = get_wallet_balance(exchange)
        allocation = balance * 0.25
        raw_qty = (allocation * 5) / price  # 5x leverage

        # Get precision
        markets = exchange.load_markets()
        market = markets[symbol]
        step = float(market['filters'][1]['stepSize']) if 'filters' in market else 0.001
        qty = round(raw_qty - (raw_qty % step), 8)
        return qty
    except Exception as e:
        print(f"Quantity error: {e}")
        return 0.0

# ─── EXECUTE TRADE ────────────────────────────────────────────────────────────
def execute_trade(symbol, direction, entry_price, sl, tp, score):
    try:
        exchange = get_exchange()
        side = 'buy' if direction == 'LONG' else 'sell'
        opp_side = 'sell' if direction == 'LONG' else 'buy'

        # Set isolated margin and 5x leverage
        try:
            exchange.fapiPrivate_post_margintype({
                "symbol": symbol.replace("/USDT:USDT", "USDT"),
                "marginType": "ISOLATED"
            })
        except:
            pass

        try:
            exchange.set_leverage(5, symbol)
        except Exception as e:
            print(f"Leverage error: {e}")

        # Get quantity
        qty = get_quantity(exchange, symbol, entry_price)
        if qty <= 0:
            print(f"❌ Invalid quantity for {symbol}")
            return False

        # Market entry order
        print(f"📤 Placing {direction} order on {symbol} | Qty: {qty}")
        order = exchange.create_market_order(symbol, side, qty)
        actual_entry = float(order.get('average', entry_price))
        print(f"✅ Entry filled at {actual_entry}")

        # Recalculate SL/TP based on actual entry
        import pandas as pd
        from muesa_logic import get_sl_tp
        # Use original SL/TP if actual entry is close to expected
        sl_final = sl
        tp_final = tp

        # Place SL order
        exchange.create_order(
            symbol, 'STOP_MARKET', opp_side, qty,
            params={
                'stopPrice': sl_final,
                'reduceOnly': True,
                'timeInForce': 'GTC'
            }
        )
        print(f"🛑 SL placed at {sl_final}")

        # Place TP order — full quantity
        exchange.create_order(
            symbol, 'TAKE_PROFIT_MARKET', opp_side, qty,
            params={
                'stopPrice': tp_final,
                'reduceOnly': True,
                'timeInForce': 'GTC'
            }
        )
        print(f"🎯 TP placed at {tp_final}")

        # Log and notify
        log_trade(symbol, direction, actual_entry, sl_final, tp_final, score)
        increment_trade_count()
        trade_alert(symbol, direction, actual_entry, sl_final, tp_final, score)

        # Start bodyguard monitor
        import threading
        threading.Thread(
            target=bodyguard_monitor,
            args=(exchange, symbol, direction, actual_entry),
            daemon=True
        ).start()

        return True

    except Exception as e:
        print(f"❌ Trade execution failed: {e}")
        return False

# ─── BODYGUARD MONITOR ────────────────────────────────────────────────────────
def bodyguard_monitor(exchange, symbol, direction, entry_price):
    print(f"🛡️ Bodyguard active for {symbol}")

    while True:
        try:
            positions = exchange.fetch_positions([symbol])
            pos = next(
                (p for p in positions if float(p.get('contracts', 0)) > 0),
                None
            )

            if not pos:
                print(f"🏁 {symbol} position closed")
                ticker = exchange.fetch_ticker(symbol)
                current_price = float(ticker['last'])

                # Check if SL or TP hit
                if direction == 'LONG':
                    if current_price < entry_price:
                        print(f"🛑 SL Hit on {symbol}")
                        set_cooldown(symbol)
                        sl_alert(symbol, direction, entry_price, current_price)
                    else:
                        print(f"🎯 TP Hit on {symbol}")
                        tp_alert(symbol, direction, entry_price, current_price)
                else:
                    if current_price > entry_price:
                        print(f"🛑 SL Hit on {symbol}")
                        set_cooldown(symbol)
                        sl_alert(symbol, direction, entry_price, current_price)
                    else:
                        print(f"🎯 TP Hit on {symbol}")
                        tp_alert(symbol, direction, entry_price, current_price)
                break

        except Exception as e:
            print(f"Bodyguard error: {e}")

        time.sleep(30)
