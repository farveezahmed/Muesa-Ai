from flask import Flask, render_template_string, send_file
import sqlite3
import pandas as pd
import os

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MUESA Command Center</title>
    <style>
        body { font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; }
        h2 { color: #38bdf8; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 30px;}
        th, td { padding: 12px; border: 1px solid #334155; text-align: left; }
        th { background: #1e293b; color: #38bdf8; }
        .btn { padding: 10px 20px; background: #38bdf8; color: #0f172a; text-decoration: none; border-radius: 5px; font-weight: bold;}
    </style>
</head>
<body>
    <h2>🛡️ MUESA Live Command Center</h2>
    <a href="/export_ghosts" class="btn">📥 Download Ghost Trades (CSV)</a>
    <a href="/export_trades" class="btn">📥 Download Trade History (CSV)</a>
    
    <h3>🚀 Live Trade History</h3>
    <table>
        <tr><th>Time</th><th>Symbol</th><th>Direction</th><th>Entry</th><th>Score</th><th>RVOL</th></tr>
        {% for row in trades %}
        <tr><td>{{ row[1] }}</td><td>{{ row[2] }}</td><td>{{ row[3] }}</td><td>${{ row[4] }}</td><td>{{ row[5] }}</td><td>{{ row[6]|round(2) }}x</td></tr>
        {% endfor %}
    </table>

    <h3>👻 Ghost Trades (Missed/Skipped)</h3>
    <table>
        <tr><th>Time</th><th>Symbol</th><th>Score</th><th>Reason</th></tr>
        {% for row in ghosts %}
        <tr><td>{{ row[1] }}</td><td>{{ row[2] }}</td><td>{{ row[3] }}</td><td>{{ row[4] }}</td></tr>
        {% endfor %}
    </table>
</body>
</html>
"""

@app.route('/')
def dashboard():
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    c.execute("SELECT * FROM ghost_trades ORDER BY id DESC LIMIT 15")
    ghosts = c.fetchall()
    c.execute("SELECT * FROM trade_history ORDER BY id DESC LIMIT 15")
    trades = c.fetchall()
    conn.close()
    return render_template_string(HTML_TEMPLATE, ghosts=ghosts, trades=trades)

@app.route('/export_ghosts')
def export_ghosts():
    conn = sqlite3.connect('muesa_data.db')
    df = pd.read_sql_query("SELECT * FROM ghost_trades", conn)
    df.to_csv('ghosts.csv', index=False)
    conn.close()
    return send_file('ghosts.csv', as_attachment=True)

@app.route('/export_trades')
def export_trades():
    conn = sqlite3.connect('muesa_data.db')
    df = pd.read_sql_query("SELECT * FROM trade_history", conn)
    df.to_csv('trades.csv', index=False)
    conn.close()
    return send_file('trades.csv', as_attachment=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
