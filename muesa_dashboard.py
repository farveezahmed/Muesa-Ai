from flask import Flask, render_template_string
import sqlite3
import os

app = Flask(__name__)

# Design is built directly into the variable below
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MUESA HQ</title>
    <style>
        body { background: #0d1117; color: #c9d1d9; font-family: sans-serif; padding: 15px; font-size: 18px; }
        .stat { background: #161b22; padding: 10px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #30363d; display: flex; justify-content: space-between; }
        h1 { color: #58a6ff; font-size: 24px; }
        table { width: 100%; border-collapse: collapse; background: #161b22; border-radius: 8px; overflow: hidden; margin-bottom: 30px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #30363d; }
        th { background: #21262d; color: #58a6ff; font-size: 14px; }
        .pill { padding: 4px 8px; border-radius: 6px; font-weight: bold; font-size: 12px; }
        .long { background: #238636; color: white; }
        .short { background: #da3633; color: white; }
        .ghost-reason { color: #8b949e; font-size: 13px; font-style: italic; }
    </style>
</head>
<body>
    <h1>🛡️ MUESA AGGRESSIVE HQ</h1>
    <div class="stat">
        <span>Wallet: <b>₹5,000</b></span>
        <span>Mode: <b>AGGRESSIVE</b></span>
    </div>
    <h3>🚀 Live Trades</h3>
    <table>
        <tr><th>Symbol</th><th>Side</th><th>Score</th></tr>
        {% for trade in trades %}
        <tr>
            <td><b>{{ trade[2] }}</b></td>
            <td><span class="pill {{ trade[3].lower() }}">{{ trade[3] }}</span></td>
            <td>{{ trade[7] }}</td>
        </tr>
        {% else %}
        <tr><td colspan="3" style="text-align:center; padding:20px; color:#8b949e;">Scanning for setups...</td></tr>
        {% endfor %}
    </table>
    <h3>👻 Ghost List (Rejections)</h3>
    <table>
        <tr><th>Symbol</th><th>Score</th><th>Reason</th></tr>
        {% for ghost in ghosts %}
        <tr>
            <td>{{ ghost[2] }}</td>
            <td>{{ ghost[3] }}</td>
            <td class="ghost-reason">{{ ghost[4] }}</td>
        </tr>
        {% else %}
        <tr><td colspan="3" style="text-align:center; padding:20px; color:#8b949e;">No rejections yet.</td></tr>
        {% endfor %}
    </table>
</body>
</html>
"""

@app.route('/')
def dashboard():
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    try:
        c.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, time TEXT, symbol TEXT, side TEXT, entry REAL, sl REAL, tp REAL, score INTEGER)")
        c.execute("CREATE TABLE IF NOT EXISTS ghost_trades (id INTEGER PRIMARY KEY, time TEXT, symbol TEXT, score INTEGER, reason TEXT)")
        c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 10")
        trades = c.fetchall()
        c.execute("SELECT * FROM ghost_trades ORDER BY id DESC LIMIT 15")
        ghosts = c.fetchall()
    except Exception as e:
        trades, ghosts = [], []
    finally:
        conn.close()
    return render_template_string(HTML_TEMPLATE, trades=trades, ghosts=ghosts)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
