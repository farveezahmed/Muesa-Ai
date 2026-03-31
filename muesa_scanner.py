import ccxt.async_support as ccxt_async
import asyncio
import os
import pandas as pd
from datetime import datetime
from muesa_logic import init_db, calculate_math_score, call_claude_ai, get_aggressive_targets, log_trade, log_ghost_trade

# 1. API KEYS FROM RAILWAY SETTINGS
API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

async def scan_market():
    init_db()
    # 2. CONNECT TO BINANCE FUTURES
    exchange = ccxt_async.binance({
        'apiKey': API_KEY, 
        'secret': SECRET_KEY, 
        'options': {'defaultType': 'future'},
        'enableRateLimit': True
    })
    
    print("🚀 MUESA LIVE AGGRESSIVE HUNTER: ONLINE")
    print("📡 Monitoring Market Cap > $15M | Target: 1:2 RR")
    
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            # AGGRESSIVE FILTER: $15M Volume
            active_symbols = [s for s, t in tickers.items() if '/USDT' in s and t['quoteVolume'] > 15000000]
            
            for symbol in active_symbols:
                # 3. FETCH 15M DATA
                bars = await exchange.fetch_ohlcv(symbol, '15m', limit=50)
                df = pd.DataFrame(bars, columns=['t','open','high','low','close','volume'])
                
                # 4. MATH CHECK (Returns score, side, rvol)
                score, side, rvol = calculate_math_score(df)
                
                # AGGRESSIVE THRESHOLD: 50+ Score
                if score >= 50 and rvol >= 1.5:
                    # 5. AI FINAL BOSS (Claude 4.5 Haiku)
                    final_score = call_claude_ai(symbol, '15m', score)
                    
                    if final_score >= 65:
                        price = df['close'].iloc[-1]
                        sl, tp = get_aggressive_targets(df, side)
                        
                        # A. LOG TO YOUR WEB DASHBOARD
                        log_trade(symbol, side, price, sl, tp, final_score)
                        
                        # B. PLACE THE LIVE ORDER ON BINANCE
                        try:
                            # Setting quantity for ~₹500 ($6) per trade (10% of ₹5,000)
                            # This allows you to run 5-10 trades simultaneously
                            trade_balance = 6.0 
                            qty = trade_balance / price
                            
                            order_side = 'sell' if side == 'SHORT' else 'buy'
                            
                            # EXECUTION COMMAND
                            order = await exchange.create_order(
                                symbol=symbol,
                                type='market', # Market execution for speed in aggressive mode
                                side=order_side,
                                amount=qty,
                                params={
                                    'stopLoss': {'stopPrice': sl},
                                    'takeProfit': {'stopPrice': tp}
                                }
                            )
                            print(f"🔥 LIVE TRADE PLACED: {symbol} {side} at {price}")
                            
                        except Exception as binance_err:
                            print(f"❌ BINANCE EXECUTION ERROR: {binance_err}")
                            log_ghost_trade(symbol, final_score, f"Binance Err: {binance_err}")
                    else:
                        log_ghost_trade(symbol, final_score, "AI Rejected Pattern")

            # SILENT WAIT: No prints during the 60s cooldown
            await asyncio.sleep(60)
            
        except Exception as e:
            # Silent error handling to keep logs clean
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(scan_market())
