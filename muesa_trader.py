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
def execute_trade(symbol, direction, entry_price, sl, tp1, tp2, score):
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

        # Split quantity: TP1 gets floor half, TP2 gets the remainder
        from muesa_logic import get_sl_tp
        markets = exchange.load_markets()
        market = markets[symbol]
        step = float(market['filters'][1]['stepSize']) if 'filters' in market else 0.001

        half_raw = qty / 2
        qty_tp1 = round(half_raw - (half_raw % step), 8)
        qty_tp2 = round(qty - qty_tp1, 8)

        sl_final  = sl
        tp1_final = tp1
        tp2_final = tp2

        # Place SL order — full quantity
        exchange.create_order(
            symbol, 'STOP_MARKET', opp_side, qty,
            params={
                'stopPrice': sl_final,
                'reduceOnly': True,
                'timeInForce': 'GTC'
            }
        )
        print(f"🛑 SL placed at {sl_final} (qty: {qty})")

        # Place TP1 order — 50% quantity, fixed price
        exchange.create_order(
            symbol, 'TAKE_PROFIT_MARKET', opp_side, qty_tp1,
            params={
                'stopPrice': tp1_final,
                'reduceOnly': True,
                'timeInForce': 'GTC'
            }
        )
        print(f"🎯 TP1 placed at {tp1_final} (qty: {qty_tp1})")

        # Place TP2 order — remaining 50% quantity, fixed initially (will trail)
        tp2_order = None
        try:
            tp2_order = exchange.create_order(
                symbol, 'TAKE_PROFIT_MARKET', opp_side, qty_tp2,
                params={
                    'stopPrice': tp2_final,
                    'reduceOnly': True,
                    'timeInForce': 'GTC'
                }
            )
            print(f"🎯 TP2 placed at {tp2_final} (qty: {qty_tp2})")
        except Exception as e:
            print(f"⚠️ TP2 order failed: {e} — bodyguard will retry")

        tp2_order_id = tp2_order['id'] if tp2_order else None

        # Log and notify
        log_trade(symbol, direction, actual_entry, sl_final, tp1_final, tp2_final, score)
        increment_trade_count()
        trade_alert(symbol, direction, actual_entry, sl_final, tp1_final, tp2_final, score)

        # Start bodyguard monitor
        import threading
        threading.Thread(
            target=bodyguard_monitor,
            args=(exchange, symbol, direction, actual_entry,
                  sl_final, tp1_final, tp2_final, qty_tp2, tp2_order_id),
            daemon=True
        ).start()

        return True

    except Exception as e:
        print(f"❌ Trade execution failed: {e}")
        return False

# ─── BODYGUARD MONITOR ────────────────────────────────────────────────────────
def bodyguard_monitor(exchange, symbol, direction, entry_price,
                      sl, tp1, tp2, qty_tp2, tp2_order_id):
    """
    Monitors an open position through two take-profit stages:

    Phase 1 — Wait for TP1 (50% close):
        Poll every 30 s. When position contracts drop by ~50%, TP1 has filled.
        Send TP1 alert and transition to Phase 2.

    Phase 2 — Trail TP2 (remaining 50%):
        Every 30 s, fetch current price and ATR. If price has moved
        favourably by more than ATR × 0.1 beyond the current TP2 stop,
        cancel the old TP2 order and place a new one trailing by ATR × 1.0.
        Stop when position is fully closed (TP2 or SL hit).
    """
    print(f"🛡️ Bodyguard active for {symbol} | TP1={tp1} TP2={tp2}")

    # ── helpers ──────────────────────────────────────────────────────────────
    def fetch_contracts():
        try:
            positions = exchange.fetch_positions([symbol])
            pos = next(
                (p for p in positions if float(p.get('contracts', 0)) > 0),
                None
            )
            return float(pos['contracts']) if pos else 0.0
        except Exception as e:
            print(f"Bodyguard fetch_contracts error: {e}")
            return -1.0  # sentinel — keep looping

    def fetch_price():
        try:
            ticker = exchange.fetch_ticker(symbol)
            return float(ticker['last'])
        except Exception as e:
            print(f"Bodyguard fetch_price error: {e}")
            return None

    def fetch_atr():
        """Approximate ATR from recent OHLCV (14-period, 1 h candles)."""
        try:
            import pandas as pd
            ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=20)
            df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            atr = (df['high'] - df['low']).rolling(14).mean().iloc[-1]
            return float(atr)
        except Exception as e:
            print(f"Bodyguard fetch_atr error: {e}")
            return None

    def cancel_order(order_id):
        try:
            exchange.cancel_order(order_id, symbol)
            print(f"🗑️ Cancelled TP2 order {order_id}")
        except Exception as e:
            print(f"⚠️ Cancel TP2 order error (id={order_id}): {e}")

    def place_tp2(price, qty):
        opp_side = 'sell' if direction == 'LONG' else 'buy'
        try:
            order = exchange.create_order(
                symbol, 'TAKE_PROFIT_MARKET', opp_side, qty,
                params={
                    'stopPrice': round(price, 6),
                    'reduceOnly': True,
                    'timeInForce': 'GTC'
                }
            )
            print(f"🎯 TP2 updated → {round(price, 6)} (qty: {qty})")
            return order['id']
        except Exception as e:
            print(f"⚠️ TP2 re-place error: {e}")
            return None

    # ── Phase 1: wait for TP1 ────────────────────────────────────────────────
    initial_contracts = fetch_contracts()
    if initial_contracts <= 0:
        print(f"⚠️ {symbol}: could not read initial contracts — skipping bodyguard")
        return

    tp1_hit = False
    while not tp1_hit:
        time.sleep(30)
        contracts = fetch_contracts()

        if contracts < 0:
            # transient error — keep waiting
            continue

        if contracts == 0:
            # Position fully closed before TP1 — must be SL
            current_price = fetch_price() or entry_price
            print(f"🛑 SL Hit on {symbol} (closed before TP1)")
            set_cooldown(symbol)
            sl_alert(symbol, direction, entry_price, current_price)
            return

        # TP1 filled when contracts drop to roughly half (allow 10% tolerance)
        if contracts <= initial_contracts * 0.6:
            current_price = fetch_price() or tp1
            print(f"🎯 TP1 Hit on {symbol} at ~{current_price}")
            tp_alert(symbol, direction, entry_price, current_price, tp_level="TP1")
            tp1_hit = True

    # ── Phase 2: trail TP2 ───────────────────────────────────────────────────
    current_tp2 = tp2
    current_tp2_id = tp2_order_id

    # If TP2 order was never placed, try once now
    if current_tp2_id is None:
        print(f"⚠️ TP2 order missing — attempting to place now")
        current_tp2_id = place_tp2(current_tp2, qty_tp2)
        if current_tp2_id is None:
            print(f"❌ TP2 order could not be placed — monitoring without trailing")

    while True:
        time.sleep(30)
        contracts = fetch_contracts()

        if contracts < 0:
            continue  # transient error

        if contracts == 0:
            # Position fully closed — TP2 or SL
            current_price = fetch_price() or entry_price
            if direction == 'LONG':
                if current_price < entry_price:
                    print(f"🛑 SL Hit on {symbol} (after TP1)")
                    set_cooldown(symbol)
                    sl_alert(symbol, direction, entry_price, current_price)
                else:
                    print(f"🎯 TP2 Hit on {symbol} at ~{current_price}")
                    tp_alert(symbol, direction, entry_price, current_price, tp_level="TP2")
            else:
                if current_price > entry_price:
                    print(f"🛑 SL Hit on {symbol} (after TP1)")
                    set_cooldown(symbol)
                    sl_alert(symbol, direction, entry_price, current_price)
                else:
                    print(f"🎯 TP2 Hit on {symbol} at ~{current_price}")
                    tp_alert(symbol, direction, entry_price, current_price, tp_level="TP2")
            break

        # Trail TP2 if price has moved favourably
        current_price = fetch_price()
        atr = fetch_atr()
        if current_price is None or atr is None:
            continue

        if direction == 'LONG':
            # Trail up: move TP2 if price is more than ATR×0.1 above current stop
            if current_price > current_tp2 + (atr * 0.1):
                new_tp2 = current_price - (atr * 1.0)
                if new_tp2 > current_tp2:  # only move stop upward
                    if current_tp2_id:
                        cancel_order(current_tp2_id)
                    new_id = place_tp2(new_tp2, qty_tp2)
                    if new_id:
                        current_tp2 = new_tp2
                        current_tp2_id = new_id
        else:
            # Trail down: move TP2 if price is more than ATR×0.1 below current stop
            if current_price < current_tp2 - (atr * 0.1):
                new_tp2 = current_price + (atr * 1.0)
                if new_tp2 < current_tp2:  # only move stop downward
                    if current_tp2_id:
                        cancel_order(current_tp2_id)
                    new_id = place_tp2(new_tp2, qty_tp2)
                    if new_id:
                        current_tp2 = new_tp2
                        current_tp2_id = new_id
