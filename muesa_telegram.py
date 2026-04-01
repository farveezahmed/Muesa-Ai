import sqlite3
from datetime import datetime, timedelta

def weekly_analysis():
    try:
        conn = sqlite3.connect('muesa_data.db')
        c = conn.cursor()
        
        # Get last 7 days date range
        today = datetime.utcnow().date()
        week_ago = today - timedelta(days=7)
        
        # Total trades this week
        c.execute("SELECT COUNT(*) FROM trades WHERE time >= ?", (str(week_ago),))
        total_trades = c.fetchone()[0]
        
        # Long vs Short
        c.execute("SELECT COUNT(*) FROM trades WHERE side='LONG' AND time >= ?", (str(week_ago),))
        total_longs = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM trades WHERE side='LONG' AND time >= ?", (str(week_ago),))
        total_shorts = total_trades - total_longs
        
        # Average score
        c.execute("SELECT AVG(score) FROM trades WHERE time >= ?", (str(week_ago),))
        avg_score = c.fetchone()[0]
        avg_score = round(avg_score, 1) if avg_score else 0
        
        # Best scoring trade
        c.execute("SELECT symbol, score, side FROM trades WHERE time >= ? ORDER BY score DESC LIMIT 1", (str(week_ago),))
        best = c.fetchone()
        best_trade = f"{best[0]} ({best[2]}) — Score: {best[1]}" if best else "None"
        
        # Most traded coin
        c.execute("SELECT symbol, COUNT(*) as cnt FROM trades WHERE time >= ? GROUP BY symbol ORDER BY cnt DESC LIMIT 1", (str(week_ago),))
        most_traded = c.fetchone()
        most_traded_coin = f"{most_traded[0]} ({most_traded[1]} trades)" if most_traded else "None"
        
        # Ghost trades this week
        c.execute("SELECT COUNT(*) FROM ghost_trades WHERE time >= ?", (str(week_ago),))
        total_ghosts = c.fetchone()[0]
        
        # Most common skip reason
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

🔥 <b>MOST TRADED</b>
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
        print("✅ Weekly analysis sent to Telegram!")

    except Exception as e:
        print(f"Weekly analysis error: {e}")
