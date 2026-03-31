import ccxt.async_support as ccxt_async
import asyncio
import os
import pandas as pd
from datetime import datetime
from muesa_logic import init_db, calculate_math_score, call_claude_ai, get_aggressive_targets, log_trade, log_ghost_trade

# --- 🛠️ THE HARD-WIRE SECTION (Replace these with your keys!) ---
API_KEY = "PASTE_YOUR_BINANCE_API_KEY_HERE"
SECRET_KEY = "import ccxt.async_support as ccxt_async
import asyncio
import os
import pandas as pd
from datetime import datetime
from muesa_logic import init_db, calculate_math_score, call_claude_ai, get_aggressive_targets, log_trade, log_ghost_trade

# --- 🛠️ THE HARD-WIRE SECTION (Replace these with your keys!) ---
API_KEY = "PASTE_YOUR_BINANCE_API_KEY_HERE"
SECRET_KEY = "import ccxt.async_support as ccxt_async
import asyncio
import os
import pandas as pd
from datetime import datetime
from muesa_logic import init_db, calculate_math_score, call_claude_ai, get_aggressive_targets, log_trade, log_ghost_trade

# --- 🛠️ THE HARD-WIRE SECTION (Replace these with your keys!) ---
API_KEY = "crLhZfjPUPKtSge5gmnQuU1LWFdTHVqG2ny18X3sslp1CHj6OK9xXVgVk6dzWcxD"
SECRET_KEY = "kueCfUxKeraVLcj6AvCONJLVucBFhM3loPGfqIReLe3GwGAkPBTzkdXbl7RGoz1B"
# ----------------------------------------------------------------

async def scan_market():
    init_db()
    # CONNECT TO BINANCE FUTURES WITH YOUR PRO IP
    exchange = ccxt_async.binance({
        'apiKey': API_KEY, 
        'secret': SECRET_KEY, 
        'options': {'defaultType': 'future'},
        'enableRateLimit': True
    })
    
    print("🚀 MUESA LIVE: PRO HUNTER ONLINE")
    print("🎯 CONFIG: 5X LEVERAGE | 25% MARGIN | STATIC IP ACTIVE")
    
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            active_symbols = [s for s, t in tickers.items() if '/USDT' in s and t['quoteVolume'] > 15000000]
            
            for symbol in active_symbols:
                bars = await exchange.fetch_ohlcv(symbol, '15m', limit=50)
                df = pd.DataFrame(bars, columns=['t','open','high','low','close','volume'])
                
                # Logic Check
                score, side, rvol = calculate_math_score(df)
                
                if score >= 50 and rvol >= 1.5:
                    # AI Analysis
                    final_score = call_claude_ai(symbol, '15m', score)
                    
                    if final_score >= 65:
                        price = df['close'].iloc[-1]
                        sl, tp = get_aggressive_targets(df, side)
                        
                        # LOG TO DASHBOARD
                        log_trade(symbol, side, price, sl, tp, final_score)
                        
                        # LIVE EXECUTION
                        try:
                            # 25% of ₹5,000 ($60) is $15 per trade
                            margin_usd = 15.0 
                            leverage = 5 
                            position_size_usd = margin_usd * leverage
                            qty = position_size_usd / price
                            
                            order_side = 'sell' if side == 'SHORT' else 'buy'
                            
                            # THE ACTION
                            order = await exchange.create_order(
                                symbol=symbol,
                                type='market',
                                side=order_side,
                                amount=qty,
                                params={
                                    'stopLoss': {'stopPrice': sl},
                                    'takeProfit': {'stopPrice': tp}
                                }
                            )
                            print(f"🔥 SUCCESS: {symbol} {side} OPENED ON BINANCE")
                            
                        except Exception as binance_err:
                            print(f"❌ BINANCE ERROR: {binance_err}")
                            log_ghost_trade(symbol, final_score, f"Execution Err: {binance_err}")
                    else:
                        log_ghost_trade(symbol, final_score, "AI Rejected Pattern")

            await asyncio.sleep(60)
            
        except Exception as e:
            print(f"⚠️ Scanner Loop Wait: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(scan_market())"
# ----------------------------------------------------------------

async def scan_market():
    init_db()
    # CONNECT TO BINANCE FUTURES WITH YOUR PRO IP
    exchange = ccxt_async.binance({
        'apiKey': API_KEY, 
        'secret': SECRET_KEY, 
        'options': {'defaultType': 'future'},
        'enableRateLimit': True
    })
    
    print("🚀 MUESA LIVE: PRO HUNTER ONLINE")
    print("🎯 CONFIG: 5X LEVERAGE | 25% MARGIN | STATIC IP ACTIVE")
    
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            active_symbols = [s for s, t in tickers.items() if '/USDT' in s and t['quoteVolume'] > 15000000]
            
            for symbol in active_symbols:
                bars = await exchange.fetch_ohlcv(symbol, '15m', limit=50)
                df = pd.DataFrame(bars, columns=['t','open','high','low','close','volume'])
                
                # Logic Check
                score, side, rvol = calculate_math_score(df)
                
                if score >= 50 and rvol >= 1.5:
                    # AI Analysis
                    final_score = call_claude_ai(symbol, '15m', score)
                    
                    if final_score >= 65:
                        price = df['close'].iloc[-1]
                        sl, tp = get_aggressive_targets(df, side)
                        
                        # LOG TO DASHBOARD
                        log_trade(symbol, side, price, sl, tp, final_score)
                        
                        # LIVE EXECUTION
                        try:
                            # 25% of ₹5,000 ($60) is $15 per trade
                            margin_usd = 15.0 
                            leverage = 5 
                            position_size_usd = margin_usd * leverage
                            qty = position_size_usd / price
                            
                            order_side = 'sell' if side == 'SHORT' else 'buy'
                            
                            # THE ACTION
                            order = await exchange.create_order(
                                symbol=symbol,
                                type='market',
                                side=order_side,
                                amount=qty,
                                params={
                                    'stopLoss': {'stopPrice': sl},
                                    'takeProfit': {'stopPrice': tp}
                                }
                            )
                            print(f"🔥 SUCCESS: {symbol} {side} OPENED ON BINANCE")
                            
                        except Exception as binance_err:
                            print(f"❌ BINANCE ERROR: {binance_err}")
                            log_ghost_trade(symbol, final_score, f"Execution Err: {binance_err}")
                    else:
                        log_ghost_trade(symbol, final_score, "AI Rejected Pattern")

            await asyncio.sleep(60)
            
        except Exception as e:
            print(f"⚠️ Scanner Loop Wait: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(scan_market())"
# ----------------------------------------------------------------

async def scan_market():
    init_db()
    # CONNECT TO BINANCE FUTURES WITH YOUR PRO IP
    exchange = ccxt_async.binance({
        'apiKey': API_KEY, 
        'secret': SECRET_KEY, 
        'options': {'defaultType': 'future'},
        'enableRateLimit': True
    })
    
    print("🚀 MUESA LIVE: PRO HUNTER ONLINE")
    print("🎯 CONFIG: 5X LEVERAGE | 25% MARGIN | STATIC IP ACTIVE")
    
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            active_symbols = [s for s, t in tickers.items() if '/USDT' in s and t['quoteVolume'] > 15000000]
            
            for symbol in active_symbols:
                bars = await exchange.fetch_ohlcv(symbol, '15m', limit=50)
                df = pd.DataFrame(bars, columns=['t','open','high','low','close','volume'])
                
                # Logic Check
                score, side, rvol = calculate_math_score(df)
                
                if score >= 50 and rvol >= 1.5:
                    # AI Analysis
                    final_score = call_claude_ai(symbol, '15m', score)
                    
                    if final_score >= 65:
                        price = df['close'].iloc[-1]
                        sl, tp = get_aggressive_targets(df, side)
                        
                        # LOG TO DASHBOARD
                        log_trade(symbol, side, price, sl, tp, final_score)
                        
                        # LIVE EXECUTION
                        try:
                            # 25% of ₹5,000 ($60) is $15 per trade
                            margin_usd = 15.0 
                            leverage = 5 
                            position_size_usd = margin_usd * leverage
                            qty = position_size_usd / price
                            
                            order_side = 'sell' if side == 'SHORT' else 'buy'
                            
                            # THE ACTION
                            order = await exchange.create_order(
                                symbol=symbol,
                                type='market',
                                side=order_side,
                                amount=qty,
                                params={
                                    'stopLoss': {'stopPrice': sl},
                                    'takeProfit': {'stopPrice': tp}
                                }
                            )
                            print(f"🔥 SUCCESS: {symbol} {side} OPENED ON BINANCE")
                            
                        except Exception as binance_err:
                            print(f"❌ BINANCE ERROR: {binance_err}")
                            log_ghost_trade(symbol, final_score, f"Execution Err: {binance_err}")
                    else:
                        log_ghost_trade(symbol, final_score, "AI Rejected Pattern")

            await asyncio.sleep(60)
            
        except Exception as e:
            print(f"⚠️ Scanner Loop Wait: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(scan_market())
