import ccxt, time, os, pandas as pd, requests
from datetime import datetime
from threading import Thread
from flask import Flask

# --- 1. Keep-Alive Web Server (Starts First) ---
app = Flask(__name__)
@app.route('/')
def home(): return "MUESA IS WATCHFUL"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    print(f"--- Web Server Starting on Port {port} ---")
    app.run(host="0.0.0.0", port=port)

# --- 2. Telegram Notification with Error Logging ---
def send_muesa_alert(message):
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        print("⚠️ Telegram Keys Missing in Variables!")
        return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(url, data={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"})
        if response.status_code != 200:
            print(f"⚠️ Telegram Error: {response.text}")
        else:
            print("📩 Telegram Message Sent Successfully!")
    except Exception as e:
        print(f"⚠️ Telegram Connection Failed: {e}")

# --- 3. The Scanner Logic ---
from muesa_logic import validate_trade_setup

def get_live_indicators(exchange, symbol):
    bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
    df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    delta = df['close'].diff()
    gain, loss = (delta.where(delta > 0, 0)).rolling(14).mean(), (-delta.where(delta < 0, 0)).rolling(14).mean()
    rsi = 100 - (100 / (1 + (gain / loss)))
    vol_spike = df['volume'].iloc[-1] > (df['volume'].rolling(10).mean().iloc[-1] * 3)
    ema9, ema21 = df['close'].ewm(span=9).mean().iloc[-1], df['close'].ewm(span=21).mean().iloc[-1]
    return {"rsi": rsi.iloc[-1], "volume_spike": vol_spike, "ema_cross": ema9 > ema21, "current_price": df['close'].iloc[-1]}

def scan_markets():
    API_KEY = os.environ.get('BINANCE_API_KEY')
    API_SECRET = os.environ.get('BINANCE_SECRET_KEY')
    exchange = ccxt.binance({'apiKey': API_KEY, 'secret': API_SECRET, 'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    
    WATCHLIST = ["BTC/USDT", "ETH/USDT", "VANRY/USDT", "SOL/USDT"]
    print(f"\n[{datetime.now()}] 🔍 MUESA Scanning Watchlist...")
    
    for symbol in WATCHLIST:
        try:
            tech = get_live_indicators(exchange, symbol)
            # Shortened logic for the scan
            print(f"📊 {symbol} | Price: {tech['current_price']} | RSI: {tech['rsi']:.2f}")
            
            if tech['rsi'] < 30:
                send_muesa_alert(f"⚠️ *OVERSOLD ALERT:* {symbol}\nPrice: {tech['current_price']}\nRSI: {tech['rsi']:.2f}")
        except Exception as e:
            print(f"⚠️ Error scanning {symbol}: {e}")

if __name__ == "__main__":
    # Start Web Server in a separate thread IMMEDIATELY
    t = Thread(target=run_web)
    t.daemon = True
    t.start()
    
    # Small delay to let server boot
    time.sleep(5)
    
    send_muesa_alert("🚀 *MUESA System Online and Watchful in Chennai!*")
    
    while True:
        scan_markets()
        print("Scan complete. MUESA is resting for 15 minutes...")
        for i in range(15):
            time.sleep(60)
            print(f"Heartbeat: MUESA is watchful... ({14-i} mins left)")
