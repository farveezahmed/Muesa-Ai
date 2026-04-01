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

def trade_alert(symbol, direction, entry, sl, tp1, tp2, score):
    emoji = "🟢" if direction == "LONG" else "🔴"
    msg = f"""
🚀 <b>MUESA TRADE ALERT</b>
{emoji} <b>{direction}</b> | <b>{symbol}</b>
💰 Entry: <code>{entry}</code>
🛑 SL: <code>{sl}</code>
🎯 TP1: <code>{tp1}</code>
🎯 TP2: <code>{tp2}</code>
⭐ Score: <b>{score}/100</b>
⚡ Leverage: 5x | Allocation: 25%
    """
    send_telegram(msg)

def sl_alert(symbol, direction, entry, current):
    msg = f"""
🛑 <b>MUESA SL HIT</b>
📌 <b>{symbol}</b> | {direction}
💰 Entry: <code>{entry}</code>
📉 Closed: <code>{current}</code>
⏳ 24hr Cooldown Applied
    """
    send_telegram(msg)

def tp_alert(symbol, direction, entry, current):
    msg = f"""
🎯 <b>MUESA TP HIT</b>
📌 <b>{symbol}</b> | {direction}
💰 Entry: <code>{entry}</code>
📈 Closed: <code>{current}</code>
✅ Profit Secured!
    """
    send_telegram(msg)

def tp1_hit_alert(symbol, direction, entry, current):
    msg = f"""
🎯 <b>MUESA TP1 HIT</b>
📌 <b>{symbol}</b> | {direction}
💰 Entry: <code>{entry}</code>
📈 TP1 Closed: <code>{current}</code>
🔒 SL Moved to Breakeven
⏳ Waiting for TP2...
    """
    send_telegram(msg)

def breakeven_alert(symbol, entry, current):
    msg = f"""
🔒 <b>MUESA BREAKEVEN SL SET</b>
📌 <b>{symbol}</b>
💰 Entry: <code>{entry}</code>
📊 Current: <code>{current}</code>
✅ Risk Free Trade Now!
    """
    send_telegram(msg)

def timeout_alert(symbol, entry, current, minutes):
    msg = f"""
⏰ <b>MUESA TRADE TIMEOUT</b>
📌 <b>{symbol}</b>
💰 Entry: <code>{entry}</code>
📊 Closed: <code>{current}</code>
⏱ Time: {minutes} minutes
    """
    send_telegram(msg)

def system_alert(message):
    msg = f"""
⚙️ <b>MUESA SYSTEM</b>
{message}
    """
    send_telegram(msg)

def daily_summary(trades_today, total_trades, skipped):
    msg = f"""
📊 <b>MUESA DAILY SUMMARY</b>
✅ Trades Today: {trades_today}/5
📈 Total All Time: {total_trades}
👻 Signals Skipped: {skipped}
🤖 Model: claude-haiku-4-5
    """
    send_telegram(msg)
