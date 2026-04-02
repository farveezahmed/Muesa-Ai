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
def execute_trade(symbol, direction, entry_price, sl, tp1, tp2, score,
                  support=None, resistance=None, divergence=None,
                  trend=None, entry_reasons=None):
    try:
        exchange = get_exchange()
        side     = 'buy'  if direction == 'LONG' else 'sell'
        opp_side = 'sell' if direction == 'LONG' else 'buy'

        # Set isolated margin
        try:
            exchange.fapiPrivate_post_margintype({
                "symbol": symbol.replace("/USDT:USDT", "USDT"),
                "marginType": "ISOLATED"
            })
        except:
            pass

        # Set 5x leverage
        try:
            exchange.set_leverage(5, symbol)
        except Exception as e:
            print(f"Leverage error: {e}")

        # Get quantity
        qty = get_quantity(exchange, symbol, entry_price)
        if qty <= 0:
            print(f"❌ Invalid quantity for {symbol}")
            return False

        # Split into two halves for TP1 / TP2
        markets  = exchange.load_markets()
        market   = markets[symbol]
        step     = float(market['filters'][1]['stepSize']) if 'filters' in market else 0.001
        half_qty = round((qty / 2) - ((qty / 2) % step), 8)
        tp2_qty  = round((qty - half_qty) - ((qty - half_qty) % step), 8)

        print(f"📤 {direction} | {symbol} | Qty: {qty} | Entry: {entry_price} | SL: {sl} | TP1: {tp1} | TP2: {tp2}")

        # Market entry
        order        = exchange.create_market_order(symbol, side, qty)
        actual_entry = float(order.get('average', entry_price))
        print(f"✅ Entry filled at {actual_entry}")

        # SL — full quantity
        sl_order = exchange.create_order(
            symbol, 'STOP_MARKET', opp_side, qty,
            params={
                'stopPrice': sl,
                'reduceOnly': True,
                'timeInForce': 'GTC'
            }
        )
        sl_order_id = sl_order.get('id')
        print(f"🛑 SL placed at {sl}")

        # TP1 — 50% quantity
        exchange.create_order(
            symbol, 'TAKE_PROFIT_MARKET', opp_side, half_qty,
            params={
                'stopPrice': tp1,
                'reduceOnly': True,
                'timeInForce': 'GTC'
            }
        )
        print(f"🎯 TP1 placed at {tp1}")

        # TP2 — remaining 50%
        exchange.create_order(
            symbol, 'TAKE_PROFIT_MARKET', opp_side, tp2_qty,
            params={
                'stopPrice': tp2,
                'reduceOnly': True,
                'timeInForce': 'GTC'
            }
        )
        print(f"🎯 TP2 placed at {tp2}")

        # Log and notify
        log_trade(
            symbol, direction, actual_entry, sl, tp1, tp2, score,
            support=support, resistance=resistance,
            divergence=divergence, trend=trend,
            dynamic_sl=sl, entry_reasons=entry_reasons
        )
        increment_trade_count()
        trade_alert(symbol, direction, actual_entry, sl, tp1, tp2, score, entry_reasons)

        # Start bodyguard
        import threading
        entry_time = datetime.utcnow()
        threading.Thread(
            target=bodyguard_monitor,
            args=(exchange, symbol, direction, actual_entry,
                  sl_order_id, sl, tp1, entry_time),
            daemon=True
        ).start()

        return True

    except Exception as e:
        print(f"❌ Trade execution failed: {e}")
        return False

# ─── BODYGUARD MONITOR ────────────────────────────────────────────────────────
def bodyguard_monitor(exchange, symbol, direction, entry_price,
                      sl_order_id=None, sl_price=None, tp1_price=None,
                      entry_time=None):
    print(f"🛡️ Bodyguard active for {symbol} | Entry: {entry_price} | TP1: {tp1_price}")

    if entry_time is None:
        entry_time = datetime.utcnow()

    timeout_hours     = 4
    tp1_hit           = False
    initial_contracts = None
    opp_side          = 'sell' if direction == 'LONG' else 'buy'

    while True:
        try:
            positions = exchange.fetch_positions([symbol])
            pos = next(
                (p for p in positions if float(p.get('contracts', 0)) > 0),
                None
            )

            # Record initial size
            if initial_contracts is None and pos is not None:
                initial_contracts = float(pos.get('contracts', 0))
                print(f"🛡️ Initial contracts: {initial_contracts}")

            # Phase 1 — TP1 detection
            if not tp1_hit and pos is not None and initial_contracts:
                current_contracts = float(pos.get('contracts', 0))
                if current_contracts <= initial_contracts * 0.55:
                    tp1_hit       = True
                    ticker        = exchange.fetch_ticker(symbol)
                    current_price = float(ticker['last'])
                    print(f"🎯 TP1 hit on {symbol} at {current_price}")
                    tp_alert(symbol, direction, entry_price, current_price)

                    # Cancel original SL
                    if sl_order_id:
                        try:
                            exchange.cancel_order(sl_order_id, symbol)
                            print(f"🗑️ Original SL cancelled")
                        except Exception as e:
                            print(f"⚠️ Cancel SL error: {e}")

                    # Move SL to breakeven
                    try:
                        remaining_qty = current_contracts
                        exchange.create_order(
                            symbol, 'STOP_MARKET', opp_side, remaining_qty,
                            params={
                                'stopPrice': entry_price,
                                'reduceOnly': True,
                                'timeInForce': 'GTC'
                            }
                        )
                        print(f"🔒 SL moved to breakeven: {entry_price}")
                        system_alert(
                            f"🔒 {symbol} SL moved to breakeven\n"
                            f"Entry: {entry_price} | Current: {current_price}"
                        )
                    except Exception as e:
                        print(f"⚠️ Breakeven SL error: {e}")

            # Phase 2 — Position closed
            if pos is None:
                print(f"🏁 {symbol} position closed")
                ticker        = exchange.fetch_ticker(symbol)
                current_price = float(ticker['last'])

                if direction == 'LONG':
                    if current_price < entry_price:
                        print(f"🛑 SL Hit on {symbol}")
                        set_cooldown(symbol)
                        sl_alert(symbol, direction, entry_price, current_price)
                    else:
                        print(f"🎯 TP2 Hit on {symbol}")
                        tp_alert(symbol, direction, entry_price, current_price)
                else:
                    if current_price > entry_price:
                        print(f"🛑 SL Hit on {symbol}")
                        set_cooldown(symbol)
                        sl_alert(symbol, direction, entry_price, current_price)
                    else:
                        print(f"🎯 TP2 Hit on {symbol}")
                        tp_alert(symbol, direction, entry_price, current_price)
                break

            # Phase 2 — 4 hour timeout
            elapsed = datetime.utcnow() - entry_time
            if tp1_hit and elapsed >= timedelta(hours=timeout_hours):
                print(f"⏰ 4hr timeout — closing {symbol}")
                try:
                    ticker        = exchange.fetch_ticker(symbol)
                    current_price = float(ticker['last'])
                    remaining_qty = float(pos.get('contracts', 0)) if pos else 0
                    if remaining_qty > 0:
                        exchange.create_market_order(
                            symbol, opp_side, remaining_qty,
                            params={'reduceOnly': True}
                        )
                    system_alert(
                        f"⏰ {symbol} timeout close at {current_price}\n"
                        f"Entry: {entry_price} | Time: {int(elapsed.total_seconds()//60)}min"
                    )
                except Exception as e:
                    print(f"⚠️ Timeout close error: {e}")
                break

        except Exception as e:
            print(f"Bodyguard error: {e}")

        time.sleep(30)
