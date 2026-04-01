import os
import sqlite3
from flask import Flask
from datetime import datetime

app = Flask(__name__)

def get_recent_trades():
    try:
        conn = sqlite3.connect('muesa_data.db')
        c = conn.cursor()
        c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 20")
        trades = c.fetchall()
        conn.close()
        return trades
    except:
        return []

def get_daily_stats():
    try:
        conn = sqlite3.connect('muesa_data.db')
        c = conn.cursor()
        c.execute("SELECT * FROM daily_stats ORDER BY date DESC LIMIT 7")
        stats = c.fetchall()
        conn.close()
        return stats
    except:
        return []

def get_ghost_trades():
    try:
        conn = sqlite3.connect('muesa_data.db')
        c = conn.cursor()
        c.execute("SELECT * FROM ghost_trades ORDER BY id DESC LIMIT 20")
        ghosts = c.fetchall()
        conn.close()
        return ghosts
    except:
        return []

def get_summary():
    try:
        conn = sqlite3.connect('muesa_data.db')
        c = conn.cursor()
        today = datetime.utcnow().date().isoformat()
        c.execute("SELECT count FROM daily_stats WHERE date=?", (today,))
        row = c.fetchone()
        trades_today = row[0] if row else 0
        c.execute("SELECT COUNT(*) FROM trades")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM ghost_trades")
        ghosts = c.fetchone()[0]
        conn.close()
        return trades_today, total, ghosts
    except:
        return 0, 0, 0

@app.route('/')
def dashboard():
    trades = get_recent_trades()
    stats = get_daily_stats()
    ghosts = get_ghost_trades()
    trades_today, total_trades, total_ghosts = get_summary()
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="30">
<title>MUESA — AI Trading System</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@300;400;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #050810;
    --bg2: #080d1a;
    --bg3: #0d1525;
    --accent: #00f5c4;
    --accent2: #0099ff;
    --danger: #ff3b6b;
    --warn: #ffaa00;
    --text: #c8d8f0;
    --muted: #4a6080;
    --border: #1a2a40;
    --glow: 0 0 20px rgba(0,245,196,0.15);
    --glow2: 0 0 20px rgba(0,153,255,0.15);
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Rajdhani', sans-serif;
    min-height: 100vh;
    overflow-x: hidden;
  }}

  body::before {{
    content: '';
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: 
      radial-gradient(ellipse at 20% 20%, rgba(0,245,196,0.03) 0%, transparent 50%),
      radial-gradient(ellipse at 80% 80%, rgba(0,153,255,0.03) 0%, transparent 50%);
    pointer-events: none;
    z-index: 0;
  }}

  .grid-bg {{
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background-image: 
      linear-gradient(rgba(0,245,196,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,245,196,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
  }}

  .container {{
    position: relative;
    z-index: 1;
    max-width: 1400px;
    margin: 0 auto;
    padding: 24px;
  }}

  /* HEADER */
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 32px;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--border);
  }}

  .logo {{
    display: flex;
    align-items: center;
    gap: 16px;
  }}

  .logo-icon {{
    width: 48px;
    height: 48px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    box-shadow: var(--glow);
  }}

  .logo-text {{
    font-size: 28px;
    font-weight: 700;
    letter-spacing: 4px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}

  .logo-sub {{
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    color: var(--muted);
    letter-spacing: 2px;
    margin-top: 2px;
  }}

  .header-right {{
    text-align: right;
  }}

  .status-badge {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: rgba(0,245,196,0.1);
    border: 1px solid rgba(0,245,196,0.3);
    border-radius: 20px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: 600;
    color: var(--accent);
    letter-spacing: 1px;
    margin-bottom: 8px;
  }}

  .status-dot {{
    width: 8px;
    height: 8px;
    background: var(--accent);
    border-radius: 50%;
    animation: pulse 2s infinite;
  }}

  @keyframes pulse {{
    0%, 100% {{ opacity: 1; transform: scale(1); }}
    50% {{ opacity: 0.5; transform: scale(0.8); }}
  }}

  .last-update {{
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    color: var(--muted);
  }}

  /* STAT CARDS */
  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 28px;
  }}

  .stat-card {{
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 20px 24px;
    position: relative;
    overflow: hidden;
    transition: border-color 0.3s;
  }}

  .stat-card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
  }}

  .stat-card.green::before {{ background: linear-gradient(90deg, var(--accent), transparent); }}
  .stat-card.blue::before {{ background: linear-gradient(90deg, var(--accent2), transparent); }}
  .stat-card.warn::before {{ background: linear-gradient(90deg, var(--warn), transparent); }}
  .stat-card.danger::before {{ background: linear-gradient(90deg, var(--danger), transparent); }}

  .stat-label {{
    font-size: 11px;
    letter-spacing: 2px;
    color: var(--muted);
    text-transform: uppercase;
    margin-bottom: 8px;
  }}

  .stat-value {{
    font-size: 36px;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 4px;
  }}

  .stat-card.green .stat-value {{ color: var(--accent); }}
  .stat-card.blue .stat-value {{ color: var(--accent2); }}
  .stat-card.warn .stat-value {{ color: var(--warn); }}
  .stat-card.danger .stat-value {{ color: var(--danger); }}

  .stat-sub {{
    font-size: 12px;
    color: var(--muted);
  }}

  /* SECTIONS */
  .section {{
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 16px;
    margin-bottom: 24px;
    overflow: hidden;
  }}

  .section-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 18px 24px;
    border-bottom: 1px solid var(--border);
    background: var(--bg3);
  }}

  .section-title {{
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    display: flex;
    align-items: center;
    gap: 10px;
  }}

  .section-title .dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }}

  .dot-green {{ background: var(--accent); box-shadow: 0 0 8px var(--accent); }}
  .dot-blue {{ background: var(--accent2); box-shadow: 0 0 8px var(--accent2); }}
  .dot-warn {{ background: var(--warn); box-shadow: 0 0 8px var(--warn); }}

  .badge {{
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    padding: 4px 10px;
    border-radius: 6px;
    letter-spacing: 1px;
  }}

  .badge-green {{ background: rgba(0,245,196,0.1); color: var(--accent); border: 1px solid rgba(0,245,196,0.2); }}
  .badge-blue {{ background: rgba(0,153,255,0.1); color: var(--accent2); border: 1px solid rgba(0,153,255,0.2); }}
  .badge-warn {{ background: rgba(255,170,0,0.1); color: var(--warn); border: 1px solid rgba(255,170,0,0.2); }}

  /* TABLE */
  table {{
    width: 100%;
    border-collapse: collapse;
  }}

  th {{
    font-family: 'Share Tech Mono', monospace;
    font-size: 10px;
    letter-spacing: 2px;
    color: var(--muted);
    text-transform: uppercase;
    padding: 12px 24px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    background: rgba(0,0,0,0.2);
  }}

  td {{
    padding: 12px 24px;
    font-size: 14px;
    border-bottom: 1px solid rgba(26,42,64,0.5);
    font-weight: 500;
  }}

  tr:last-child td {{ border-bottom: none; }}

  tr:hover td {{ background: rgba(0,245,196,0.02); }}

  .long-badge {{
    display: inline-block;
    background: rgba(0,245,196,0.1);
    color: var(--accent);
    border: 1px solid rgba(0,245,196,0.3);
    border-radius: 6px;
    padding: 2px 10px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1px;
  }}

  .short-badge {{
    display: inline-block;
    background: rgba(255,59,107,0.1);
    color: var(--danger);
    border: 1px solid rgba(255,59,107,0.3);
    border-radius: 6px;
    padding: 2px 10px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1px;
  }}

  .score-bar {{
    display: flex;
    align-items: center;
    gap: 10px;
  }}

  .score-track {{
    flex: 1;
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
    max-width: 80px;
  }}

  .score-fill {{
    height: 100%;
    border-radius: 2px;
    background: linear-gradient(90deg, var(--accent2), var(--accent));
  }}

  .score-num {{
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    color: var(--accent);
    min-width: 30px;
  }}

  .mono {{
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
  }}

  .text-muted {{ color: var(--muted); }}
  .text-accent {{ color: var(--accent); }}
  .text-blue {{ color: var(--accent2); }}
  .text-warn {{ color: var(--warn); }}
  .text-danger {{ color: var(--danger); }}

  /* DAILY CHART */
  .daily-grid {{
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 12px;
    padding: 24px;
  }}

  .day-card {{
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px;
    text-align: center;
  }}

  .day-label {{
    font-size: 11px;
    color: var(--muted);
    margin-bottom: 8px;
    letter-spacing: 1px;
  }}

  .day-count {{
    font-size: 28px;
    font-weight: 700;
    color: var(--accent);
  }}

  .day-bar {{
    margin-top: 8px;
    height: 3px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
  }}

  .day-bar-fill {{
    height: 100%;
    background: linear-gradient(90deg, var(--accent2), var(--accent));
    border-radius: 2px;
  }}

  /* EMPTY STATE */
  .empty {{
    padding: 40px;
    text-align: center;
    color: var(--muted);
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    letter-spacing: 1px;
  }}

  /* FOOTER */
  .footer {{
    text-align: center;
    padding: 20px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 11px;
    color: var(--muted);
    letter-spacing: 2px;
    border-top: 1px solid var(--border);
    margin-top: 20px;
  }}

  @media (max-width: 768px) {{
    .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .daily-grid {{ grid-template-columns: repeat(3, 1fr); }}
    td, th {{ padding: 10px 14px; }}
  }}
</style>
</head>
<body>
<div class="grid-bg"></div>
<div class="container">

  <!-- HEADER -->
  <div class="header">
    <div class="logo">
      <div class="logo-icon">🤖</div>
      <div>
        <div class="logo-text">MUESA</div>
        <div class="logo-sub">AI-POWERED CRYPTO TRADING SYSTEM</div>
      </div>
    </div>
    <div class="header-right">
      <div class="status-badge">
        <div class="status-dot"></div>
        SYSTEM ONLINE
      </div>
      <div class="last-update">LAST UPDATE: {now}</div>
    </div>
  </div>

  <!-- STAT CARDS -->
  <div class="stats-grid">
    <div class="stat-card green">
      <div class="stat-label">Trades Today</div>
      <div class="stat-value">{trades_today}</div>
      <div class="stat-sub">Max 5 per day</div>
    </div>
    <div class="stat-card blue">
      <div class="stat-label">Total Trades</div>
      <div class="stat-value">{total_trades}</div>
      <div class="stat-sub">All time</div>
    </div>
    <div class="stat-card warn">
      <div class="stat-label">Signals Skipped</div>
      <div class="stat-value">{total_ghosts}</div>
      <div class="stat-sub">Ghost trades</div>
    </div>
    <div class="stat-card danger">
      <div class="stat-label">Model</div>
      <div class="stat-value" style="font-size:16px; padding-top:8px;">HAIKU</div>
      <div class="stat-sub">claude-haiku-4-5</div>
    </div>
  </div>

  <!-- DAILY STATS -->
  <div class="section">
    <div class="section-header">
      <div class="section-title">
        <div class="dot dot-blue"></div>
        7-Day Trade Activity
      </div>
      <span class="badge badge-blue">WEEKLY VIEW</span>
    </div>
    <div class="daily-grid">"""

    max_count = max([s[1] for s in stats], default=1) if stats else 1
    for stat in stats:
        pct = (stat[1] / max_count) * 100
        html += f"""
      <div class="day-card">
        <div class="day-label">{stat[0][-5:]}</div>
        <div class="day-count">{stat[1]}</div>
        <div class="day-bar"><div class="day-bar-fill" style="width:{pct}%"></div></div>
      </div>"""

    if not stats:
        html += '<div style="padding:20px; color:var(--muted); text-align:center; grid-column:span 7; font-family:monospace;">NO DATA YET</div>'

    html += """
    </div>
  </div>

  <!-- RECENT TRADES -->
  <div class="section">
    <div class="section-header">
      <div class="section-title">
        <div class="dot dot-green"></div>
        Recent Trades
      </div>
      <span class="badge badge-green">LIVE</span>
    </div>"""

    if trades:
        html += """
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Symbol</th>
          <th>Direction</th>
          <th>Entry</th>
          <th>Stop Loss</th>
          <th>Take Profit</th>
          <th>Score</th>
        </tr>
      </thead>
      <tbody>"""
        for trade in trades:
            side_badge = f'<span class="long-badge">LONG</span>' if trade[3] == 'LONG' else f'<span class="short-badge">SHORT</span>'
            score_pct = min(trade[7], 100) if trade[7] else 0
            html += f"""
        <tr>
          <td class="mono text-muted">{trade[1]}</td>
          <td class="text-accent" style="font-weight:700">{trade[2]}</td>
          <td>{side_badge}</td>
          <td class="mono">{trade[4]}</td>
          <td class="mono text-danger">{trade[5]}</td>
          <td class="mono text-accent">{trade[6]}</td>
          <td>
            <div class="score-bar">
              <div class="score-track"><div class="score-fill" style="width:{score_pct}%"></div></div>
              <span class="score-num">{trade[7]}</span>
            </div>
          </td>
        </tr>"""
        html += "</tbody></table>"
    else:
        html += '<div class="empty">// NO TRADES EXECUTED YET —  MUESA IS HUNTING...</div>'

    html += "</div>"

    # GHOST TRADES
    html += """
  <div class="section">
    <div class="section-header">
      <div class="section-title">
        <div class="dot dot-warn"></div>
        Ghost Trades — Skipped Signals
      </div>
      <span class="badge badge-warn">FILTERED</span>
    </div>"""

    if ghosts:
        html += """
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Symbol</th>
          <th>Score</th>
          <th>Reason Skipped</th>
        </tr>
      </thead>
      <tbody>"""
        for ghost in ghosts:
            html += f"""
        <tr>
          <td class="mono text-muted">{ghost[1]}</td>
          <td class="text-warn" style="font-weight:700">{ghost[2]}</td>
          <td class="mono text-blue">{ghost[3]}</td>
          <td class="text-muted">{ghost[4]}</td>
        </tr>"""
        html += "</tbody></table>"
    else:
        html += '<div class="empty">// NO GHOST TRADES YET</div>'

    html += "</div>"

    html += f"""
  <div class="footer">
    MUESA v2.0 &nbsp;|&nbsp; BINANCE PERPETUAL FUTURES &nbsp;|&nbsp; 5X LEVERAGE &nbsp;|&nbsp; AUTO-REFRESH 30s
  </div>

</div>
</body>
</html>"""

    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
