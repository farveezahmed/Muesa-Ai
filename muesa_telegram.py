import os
import requests

def send_telegram(message):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram not configured")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def trade_alert(symbol, direction, entry, sl, tp, score):
    emoji = "🟢" if direction == "LONG" else "🔴"
    msg = f"""
🚀 <b>MUESA TRADE ALERT</b>
{emoji} <b>{direction}</b> | {symbol}
💰 Entry: {entry}
🛑 SL: {sl}
🎯 TP: {tp}
⭐ Score: {score}/100
    """
    send_telegram(msg)

def sl_alert(symbol, direction, entry, current):
    msg = f"""
🛑 <b>MUESA SL HIT</b>
📌 {symbol} | {direction}
💰 Entry: {entry}
📉 Closed: {current}
⏳ 24hr Cooldown Applied
    """
    send_telegram(msg)

def tp_alert(symbol, direction, entry, current):
    msg = f"""
🎯 <b>MUESA TP HIT</b>
📌 {symbol} | {direction}
💰 Entry: {entry}
📈 Closed: {current}
✅ Profit Secured!
    """
    send_telegram(msg)

def system_alert(message):
    msg = f"""
⚙️ <b>MUESA SYSTEM</b>
{message}
    """
    send_telegram(msg)
