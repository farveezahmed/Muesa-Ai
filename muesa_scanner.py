import ccxt.async_support as ccxt_async
import asyncio
import os
import pandas as pd
from datetime import datetime
from muesa_logic import init_db, calculate_math_score, call_claude_ai, get_aggressive_targets, log_trade, log_ghost_trade

# API KEYS FROM RAILWAY
API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

async def scan_market():
    init_db()
    exchange = ccxt_async.binance({
        'apiKey': API_KEY, 
        'secret': SECRET_KEY, 
        'options': {'defaultType': 'future'},
        'enableRateLimit': True
    })
    
    print("🚀 MUESA LIVE: 5X LEVERAGE | 25% MARGIN ACTIVE")
    
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            # Aggressive $15M Volume Filter
            active_symbols = [s for s, t in tickers.items() if '/USDT' in s and t['quoteVolume'] > 15000000]
            
            for symbol in active_symbols:
                bars = await exchange.fetch_ohlcv(symbol, '15m', limit=50)
                df = pd.DataFrame(bars, columns=['t','open','high','low','close','volume'])
                
                # Logic Check
                score, side, rvol = calculate_math_score(df)
                
                if score >= 50 and rvol >= 1.5:
                    final_score = call_claude_ai(symbol, '15m', score)
                    
                    if final_score >= 65:
                        price = df['close'].iloc[-1]
                        sl, tp = get_aggressive_targets(df, side)
                        
                        # LOG TO WEB DASHBOARD
                        log_trade(symbol, side, price, sl, tp, final_score)
                        
                        # LIVE EXECUTION ON BINANCE (5x Leverage / 25% Margin)
                        try:
                            # 25% of your ₹5,000 ($60) is $15 per trade
                            margin_usd = 15.0 
                            leverage = 5 
                            
                            # Total position size = $75.00
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
                            print(f"🔥 LIVE 5X TRADE: {symbol} {side} at {price}")
                            
                        except Exception as binance_err:
                            log_ghost_trade(symbol, final_score, f"Binance Err: {binance_err}")
                    else:
                        log_ghost_trade(symbol, final_score, "AI Rejected Pattern")

            # SILENT WAIT
            await asyncio.sleep(60)
            
        except Exception:
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(scan_market())
