import os
import sqlite3
import requests
from datetime import datetime, timedelta

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

def weekly_analysis():
    try:
        conn = sqlite3.connect('muesa_data.db')
        c = conn.cursor()
        today = datetime.utcnow().date()
        week_ago = today - timedelta(days=7)

        # Total trades
        c.execute("SELECT COUNT(*) FROM trades WHERE time >= ?", (str(week_ago),))
        total_trades = c.fetchone()[0]

        # Longs vs Shorts
        c.execute("SELECT COUNT(*) FROM trades WHERE side='LONG' AND time >= ?", (str(week_ago),))
        total_longs = c.fetchone()[0]
        total_shorts = total_trades - total_longs

        # Average score
        c.execute("SELECT AVG(score) FROM trades WHERE time >= ?", (str(week_ago),))
        avg_score = c.fetchone()[0]
        avg_score = round(avg_score, 1) if avg_score else 0

        # Best trade
        c.execute("SELECT symbol, score, side FROM trades WHERE time >= ? ORDER BY score DESC LIMIT 1", (str(week_ago),))
        best = c.fetchone()
        best_trade = f"{best[0]} ({best[2]}) — Score: {best[1]}" if best else "None"

        # Most traded coin
        c.execute("SELECT symbol, COUNT(*) as cnt FROM trades WHERE time >= ? GROUP BY symbol ORDER BY cnt DESC LIMIT 1", (str(week_ago),))
        most_traded = c.fetchone()
        most_traded_coin = f"{most_traded[0]} ({most_traded[1]} trades)" if most_traded else "None"

        # Ghost trades
        c.execute("SELECT COUNT(*) FROM ghost_trades WHERE time >= ?", (str(week_ago),))
        total_ghosts = c.fetchone()[0]

        # Top skip reason
        c.execute("SELECT reason, COUNT(*) as cnt FROM ghost_trades WHERE time >= ? GROUP BY reason ORDER BY cnt DESC LIMIT 1", (str(week_ago),))
        top_reason = c.fetchone()
        skip_reason = f"{top_reason[0]} ({top_reason[1]}x)" if top_reason else "None"

        # Trend distribution
        c.execute("SELECT trend, COUNT(*) FROM trades WHERE time >= ? GROUP BY trend", (str(week_ago),))
        trends = c.fetchall()
        trend_text = " | ".join([f"{t[0]}: {t[1]}" for t in trends]) if trends else "No data"

        # Divergence hits
        c.execute("SELECT divergence, COUNT(*) FROM trades WHERE time >= ? AND divergence IS NOT NULL GROUP BY divergence", (str(week_ago),))
        divs = c.fetchall()
        div_text = " | ".join([f"{d[0]}: {d[1]}" for d in divs]) if divs else "None"

        conn.close()

        msg = f"""
📊 <b>MUESA WEEKLY REPORT</b>
📅 {str(week_ago)} → {str(today)}
━━━━━━━━━━━━━━━━━━━━

📈 <b>TRADE SUMMARY</b>
✅ Total Trades: {total_trades}
🟢 Longs: {total_longs}
🔴 Shorts: {total_shorts}
⭐ Avg Score: {avg_score}/100

🏆 <b>BEST TRADE</b>
{best_trade}

🔥 <b>MOST TRADED COIN</b>
{most_traded_coin}

👻 <b>GHOST TRADES</b>
Total Skipped: {total_ghosts}
Top Skip Reason: {skip_reason}

📉 <b>TREND ANALYSIS</b>
{trend_text}

🔀 <b>DIVERGENCE HITS</b>
{div_text}

━━━━━━━━━━━━━━━━━━━━
🤖 MUESA v2.0 | Haiku Model
        """
        send_telegram(msg)
        print("✅ Weekly analysis sent!")

    except Exception as e:
        print(f"Weekly analysis error: {e}")
