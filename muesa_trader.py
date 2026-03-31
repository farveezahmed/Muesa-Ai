import time
from muesa_logic import set_cooldown, log_trade

def get_25_percent_allocation(exchange, price):
    balance = exchange.fetch_balance({'type': 'future'})
    available_usdt = float(balance['USDT']['free'])
    trade_value = available_usdt * 0.25
    quantity = trade_value / price
    return quantity, trade_value

def execute_atomic_trade(exchange, symbol, direction, entry_price, sl_price):
    side = 'buy' if direction == 'long' else 'sell'
    opp_side = 'sell' if direction == 'long' else 'buy'
    
    risk_pct = abs(entry_price - sl_price) / entry_price
    if risk_pct > 0.05: return None, "Risk exceeds 5% cap"

    try: exchange.fapiPrivate_post_margintype({"symbol": symbol.replace("/", ""), "marginType": "ISOLATED"})
    except: pass 

    qty, trade_value = get_25_percent_allocation(exchange, entry_price)
    
    try:
        order = exchange.create_market_order(symbol, side, qty)
        actual_entry = float(order['price'])
        
        exchange.create_order(symbol, 'STOP_MARKET', opp_side, qty, params={'stopPrice': sl_price, 'reduceOnly': True})
        
        tp_price = actual_entry * 1.04 if direction == 'long' else actual_entry * 0.96
        exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', opp_side, qty / 2, params={'stopPrice': tp_price, 'reduceOnly': True})
        
        return order, "Success"
    except Exception as e:
        exchange.create_market_order(symbol, opp_side, qty, params={'reduceOnly': True})
        return None, f"Atomic execution failed, safely aborted: {e}"

def bodyguard_monitor(exchange, symbol, direction, entry_price, final_score, rvol):
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
                
                if (direction == 'long' and current_price < entry_price) or (direction == 'short' and current_price > entry_price):
                    print(f"🛑 SL Hit! Applying 24h Cooldown to {symbol}")
                    set_cooldown(symbol)
                break
        except Exception as e:
            print(f"Bodyguard error: {e}")
        time.sleep(30)
