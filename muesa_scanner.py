import ccxt.async_support as ccxt_async
import asyncio
import os
import pandas as pd
from datetime import datetime
from muesa_logic import init_db, calculate_math_score, call_claude_ai, get_aggressive_targets, log_trade, log_ghost_trade

# ================================================================
# 1. THE KEYS (PASTE YOUR BINANCE KEYS INSIDE THE QUOTES "")
# ================================================================
API_KEY = "crLhZfjPUPKtSge5gmnQuU1LWFdTHVqG2ny18X3sslp1CHj6OK9xXVgVk6dzWcxD"
SECRET_KEY = "kueCfUxKeraVLcj6AvCONJLVucBFhM3loPGfqIReLe3GwGAkPBTzkdXbl7RGoz1B"
# ================================================================

async def scan_market():
    init_db()
    
    # 2. THE CONNECTION (FIXED SYNTAX)
    exchange = ccxt_async.binance({
        'apiKey': API_KEY,       
        'secret': SECRET_KEY,    
        'options': {
            'defaultType': 'future',
            'adjustForTimeDifference': True
        },
        'enableRateLimit': True
    })
    
    print("🚀 MUESA LIVE: PRO HUNTER ONLINE")
    print(f"🎯 CONFIG: 5X LEVERAGE | 25% MARGIN | THROTTLE ENABLED")
    
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            # Filter for high volume coins (> $15M)
            active_symbols = [s for s, t in tickers.items() if '/USDT' in s and t['quoteVolume'] > 15000000]
            
            for symbol in active_symbols:
                # --- 🛑 THE THROTTLE (Protects you from IP Bans) ---
                await asyncio.sleep(2) 
                
                try:
                    bars = await exchange.fetch_ohlcv(symbol, '15m', limit=50)
                    df = pd.DataFrame(bars, columns=['t','open','high','low','close','volume'])
                    
                    # Logic Check (Math & RVol)
                    score, side, rvol = calculate_math_score(df)
                    
                    if score >= 50 and rvol >= 1.5:
                        # AI Analysis
                        final_score = call_claude_ai(symbol, '15m', score)
                        
                        if final_score >= 65:
                            price = df['close'].iloc[-1]
                            sl, tp = get_aggressive_targets(df, side)
                            
                            log_trade(symbol, side, price, sl, tp, final_score)
                            
                            # LIVE EXECUTION ON BINANCE
                            try:
                                margin_usd = 15.0 # 25% of ₹5,000
                                leverage = 5 
                                position_size_usd = margin_usd * leverage
                                qty = position_size_usd / price
                                
                                order_side = 'sell' if side == 'SHORT' else 'buy'
                                
                                # OPEN THE TRADE
                                await exchange.create_order(
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
                                print(f"❌ EXECUTION ERROR: {binance_err}")
                                log_ghost_trade(symbol, final_score, f"Execution Err: {binance_err}")
                
                except Exception as inner_e:
                    print(f"⚠️ Skipping {symbol}: {inner_e}")
                    continue

            print("✅ Market Scan Complete. Waiting 2 minutes...")
            await asyncio.sleep(120) 
            
        except Exception as e:
            print(f"⚠️ Global Loop Error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(scan_market())
