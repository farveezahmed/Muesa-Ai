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
        balance = get_wallet_balance(exchange)
        allocation = balance * 0.05          # 5% per trade (was 25%) — max 5 trades = 25% deployed
        raw_qty = (allocation * 5) / price   # 5x leverage

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
def execute_trade(symbol, direction, entry_price, sl, tp1, tp2, score,
                  support=None, resistance=None, divergence=None, trend=None):
    """
    Open a leveraged futures position with:
      - SL covering the full position
      - TP1 covering 50% of the position (triggers breakeven SL move)
      - TP2 covering the remaining 50% (trailing SL in bodyguard)

    Parameters
    ----------
    sl, tp1, tp2 : dynamic SL and split take-profit levels from get_sl_tp()
    support, resistance, divergence, trend : metadata for logging
    """
    try:
        exchange = get_exchange()
        side     = 'buy'  if direction == 'LONG' else 'sell'
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

        # Get quantity (full position)
        qty = get_quantity(exchange, symbol, entry_price)
        if qty <= 0:
            print(f"❌ Invalid quantity for {symbol}")
            return False

        # Split into two halves for TP1 / TP2
        # Round down to avoid over-reducing
        markets  = exchange.load_markets()
        market   = markets[symbol]
        step     = float(market['filters'][1]['stepSize']) if 'filters' in market else 0.001
        half_qty = round((qty / 2) - ((qty / 2) % step), 8)
        # Remainder goes to TP2 (avoids rounding leaving open dust)
        tp2_qty  = round(qty - half_qty - ((qty - half_qty) % step), 8)

        # Market entry order
        print(f"📤 Placing {direction} order on {symbol} | Qty: {qty} (TP1: {half_qty}, TP2: {tp2_qty})")
        order        = exchange.create_market_order(symbol, side, qty)
        actual_entry = float(order.get('average', entry_price))
        print(f"✅ Entry filled at {actual_entry}")

        sl_final  = sl
        tp1_final = tp1
        tp2_final = tp2

        # Place SL order — full quantity
        sl_order = exchange.create_order(
            symbol, 'STOP_MARKET', opp_side, qty,
            params={
                'stopPrice': sl_final,
                'reduceOnly': True,
                'timeInForce': 'GTC'
            }
        )
        sl_order_id = sl_order.get('id')
        print(f"🛑 SL placed at {sl_final} (order id: {sl_order_id})")

        # Place TP1 order — 50% quantity
        exchange.create_order(
            symbol, 'TAKE_PROFIT_MARKET', opp_side, half_qty,
            params={
                'stopPrice': tp1_final,
                'reduceOnly': True,
                'timeInForce': 'GTC'
            }
        )
        print(f"🎯 TP1 placed at {tp1_final} (qty: {half_qty})")

        # Place TP2 order — remaining 50% quantity
        exchange.create_order(
            symbol, 'TAKE_PROFIT_MARKET', opp_side, tp2_qty,
            params={
                'stopPrice': tp2_final,
                'reduceOnly': True,
                'timeInForce': 'GTC'
            }
        )
        print(f"🎯 TP2 placed at {tp2_final} (qty: {tp2_qty})")

        # Log and notify (enriched metadata)
        log_trade(
            symbol, direction, actual_entry, sl_final, tp1_final, tp2_final, score,
            support=support, resistance=resistance,
            divergence=divergence, trend=trend,
            dynamic_sl=sl_final
        )
        increment_trade_count()
        trade_alert(symbol, direction, actual_entry, sl_final, tp1_final, score)

        # Start bodyguard monitor
        import threading
        entry_time = datetime.utcnow()
        threading.Thread(
            target=bodyguard_monitor,
            args=(exchange, symbol, direction, actual_entry,
                  sl_order_id, sl_final, tp1_final, entry_time),
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
    """
    Two-phase position monitor:

    Phase 1 — Waiting for TP1:
      • Polls position size every 30 s.
      • When position size drops to ~50% (TP1 filled), cancels the original
        full-size SL and places a new breakeven SL at entry_price.
      • Logs and alerts the SL move.

    Phase 2 — Waiting for TP2 / SL / timeout:
      • Continues polling every 30 s.
      • If 4 hours have elapsed since entry and position is still open,
        closes at market and alerts timeout.
      • When position fully closes, determines SL-hit vs TP-hit and alerts.
    """
    print(f"🛡️ Bodyguard active for {symbol} | Entry: {entry_price} | TP1: {tp1_price}")

    if entry_time is None:
        entry_time = datetime.utcnow()

    timeout_hours   = 4
    tp1_hit         = False          # True once Phase 1 completes
    initial_contracts = None         # Recorded on first successful poll

    opp_side = 'sell' if direction == 'LONG' else 'buy'

    while True:
        try:
            positions = exchange.fetch_positions([symbol])
            pos = next(
                (p for p in positions if float(p.get('contracts', 0)) > 0),
                None
            )

            # ── Record initial position size on first poll ────────────────────
            if initial_contracts is None and pos is not None:
                initial_contracts = float(pos.get('contracts', 0))
                print(f"🛡️ Initial position size: {initial_contracts} contracts")

            # ── Phase 1: TP1 detection ────────────────────────────────────────
            if not tp1_hit and pos is not None and initial_contracts:
                current_contracts = float(pos.get('contracts', 0))
                # TP1 filled when position is reduced to ≤55% of original
                if current_contracts <= initial_contracts * 0.55:
                    tp1_hit = True
                    ticker        = exchange.fetch_ticker(symbol)
                    current_price = float(ticker['last'])
                    print(f"🎯 TP1 hit on {symbol} at ~{current_price}")
                    tp_alert(symbol, direction, entry_price, current_price)

                    # Cancel original SL order and replace with breakeven SL
                    if sl_order_id:
                        try:
                            exchange.cancel_order(sl_order_id, symbol)
                            print(f"🗑️ Original SL order {sl_order_id} cancelled")
                        except Exception as cancel_err:
                            print(f"⚠️ Could not cancel SL order: {cancel_err}")

                    # Place new breakeven SL at entry price
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
                        print(f"🔒 SL moved to breakeven after TP1 — new SL: {entry_price}")
                        system_alert(
                            f"🔒 {symbol} SL moved to breakeven after TP1\n"
                            f"Entry: {entry_price} | Current: {current_price}"
                        )
                    except Exception as be_err:
                        print(f"⚠️ Breakeven SL placement failed: {be_err}")

            # ── Phase 2: Position fully closed ───────────────────────────────
            if pos is None:
                print(f"🏁 {symbol} position fully closed")
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

            # ── Phase 2: 4-hour timeout ───────────────────────────────────────
            elapsed = datetime.utcnow() - entry_time
            if tp1_hit and elapsed >= timedelta(hours=timeout_hours):
                print(f"⏰ 4-hour timeout — closing {symbol} position at market")
                try:
                    ticker        = exchange.fetch_ticker(symbol)
                    current_price = float(ticker['last'])
                    remaining_qty = float(pos.get('contracts', 0)) if pos else 0
                    if remaining_qty > 0:
                        exchange.create_market_order(symbol, opp_side, remaining_qty,
                                                     params={'reduceOnly': True})
                    system_alert(
                        f"⏰ {symbol} Trade timeout — closed at {current_price}\n"
                        f"Entry: {entry_price} | Elapsed: {int(elapsed.total_seconds() // 60)} min"
                    )
                    print(f"⏰ {symbol} closed at {current_price} after timeout")
                except Exception as timeout_err:
                    print(f"⚠️ Timeout close failed: {timeout_err}")
                break

        except Exception as e:
            print(f"Bodyguard error: {e}")

        time.sleep(30)
