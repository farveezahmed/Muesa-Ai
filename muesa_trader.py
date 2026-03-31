import time
from muesa_logic import set_cooldown, log_trade

def get_25_percent_allocation(exchange, price):
    """Calculates exactly 25% of Available USDT."""
    balance = exchange.fetch_balance({'type': 'future'})
    available_usdt = float(balance['USDT']['free'])
    trade_value = available_usdt * 0.25
    quantity = trade_value / price
    return quantity, trade_value

def execute_atomic_trade(exchange, symbol, direction, entry_price, sl_price):
    """Places Entry, SL, and 50% TP simultaneously."""
    side = 'buy' if direction == 'long' else 'sell'
    opp_side = 'sell' if direction == 'long' else 'buy'
    
    # 5% Hard Cap Risk Check
    risk_pct = abs(entry_price - sl_price) / entry_price
    if risk_pct > 0.05:
        return None, "Risk exceeds 5% cap"

    try:
        # Set Isolated Margin (Safety)
        exchange.fapiPrivate_post_margintype({"symbol": symbol.replace("/", ""), "marginType": "ISOLATED"})
    except: pass 

    qty, trade_value = get_25_percent_allocation(exchange, entry_price)
    
    try:
        # 1. Market Entry
        order = exchange.create_market_order(symbol, side, qty)
        actual_entry = float(order['price'])
        
        # 2. Stop Loss Order
        exchange.create_order(symbol, 'STOP_MARKET', opp_side, qty, 
                              params={'stopPrice': sl_price, 'reduceOnly': True})
        
        # 3. Partial TP (50% at 4%)
        tp_price = actual_entry * 1.04 if direction == 'long' else actual_entry * 0.96
        exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', opp_side, qty / 2, 
                              params={'stopPrice': tp_price, 'reduceOnly': True})
        
        return order, "Success"
    except Exception as e:
        # Emergency Exit if SL fails
        exchange.create_market_order(symbol, opp_side, qty, params={'reduceOnly': True})
        return None, f"Atomic execution failed, safely aborted: {e}"

def bodyguard_monitor(exchange, symbol, direction, entry_price, final_score, rvol):
    """24/7 continuous monitor for the open trade."""
    print(f"\n🛡️ BODYGUARD ACTIVE for {symbol} | Entry: {entry_price}")
    log_trade(symbol, direction, entry_price, final_score, rvol)
    
    while True:
        try:
            positions = exchange.fetch_positions([symbol])
            pos = next((p for p in positions if float(p['contracts']) > 0), None)
            
            if not pos:
                print(f"🏁 Trade {symbol} closed.")
                ticker = exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                
                # Check if SL was hit to trigger 24h Cooldown
                if (direction == 'long' and current_price < entry_price) or \
                   (direction == 'short' and current_price > entry_price):
                    print(f"🛑 SL Hit! Applying 24h Cooldown to {symbol}")
                    set_cooldown(symbol)
                break
                
        except Exception as e:
            print(f"Bodyguard error: {e}")
            
        time.sleep(30) # Monitor every 30 seconds
