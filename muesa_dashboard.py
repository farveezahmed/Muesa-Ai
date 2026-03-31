from flask import Flask, render_template_string
import sqlite3
import os
from muesa_logic import init_db

app = Flask(__name__)

# This is the "Big Text" Modern Dark Theme
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>MUESA Command Center</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { 
            background-color: #0d1117; 
            color: #c9d1d9; 
            font-family: 'Segoe UI', Arial, sans-serif; 
            margin: 0;
            padding: 20px;
            font-size: 18px; /* High visibility for mobile */
        }
        .container { max-width: 1200px; margin: auto; }
        h1 { color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 10px; font-size: 28px; }
        h2 { color: #f85149; margin-top: 30px; font-size: 22px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; background: #161b22; }
        th, td { padding: 15px; text-align: left; border-bottom: 1px solid #30363d; }
        th { background-color: #21262d; color: #58a6ff; font-weight: bold; }
        .status-pill { padding: 5px 12px; border-radius: 12px; font-size: 14px; font-weight: bold; }
        .long { background: #238636; color: white; }
        .short { background: #da3633; color: white; }
        .no-data { text-align: center; padding: 40px; color: #8b949e; font-style: italic; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🛡️ MUESA Live Command Center</h1>
        
        <div style="display: flex; gap: 10px; margin-bottom: 20px;">
            <div style="background: #21262d; padding: 15px; border-radius: 8px; flex: 1;">
                <small>System Status</small><br><strong>🟢 HUNTING 24/7</strong>
            </div>
            <div style="background: #21262d; padding: 15px; border-radius: 8px; flex: 1;">
                <small>Logic Mode</small><br><strong>75+ CONFLUENCE</strong>
            </div>
        </div>

        <h2>🚀 Live Trade History (Active & Closed)</h2>
        <table>
            <tr>
                <th>Time</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Score</th>
            </tr>
            {% for trade in trades %}
            <tr>
                <td>{{ trade[1] }}</td>
                <td><strong>{{ trade[2] }}</strong></td>
                <td><span class="status-pill {{ trade[3].lower() }}">{{ trade[3] }}</span></td>
                <td>${{ trade[4] }}</td>
                <td>{{ trade[7] }}</td>
            </tr>
            {% else %}
            <tr><td colspan="5" class="no-data">No live trades executed yet. Scanning markets...</td></tr>
            {% endfor %}
        </table>

        <h2>👻 Ghost Trades (Missed/Rejected)</h2>
        <table>
            <tr>
                <th>Time</th>
                <th>Symbol</th>
                <th>Score</th>
                <th>Reason for Rejection</th>
            </tr>
            {% for ghost in ghosts %}
            <tr>
                <td>{{ ghost[1] }}</td>
                <td><strong>{{ ghost[2] }}</strong></td>
                <td>{{ ghost[3] }}</td>
                <td style="color: #8b949e;">{{ ghost[4] }}</td>
            </tr>
            {% else %}
            <tr><td colspan="4" class="no-data">No Ghost Trades captured yet. Waiting for 60+ setups.</td></tr>
            {% endfor %}
        </table>
    </div>
</body>
</html>
'''

@app.route('/')
def dashboard():
    # Ensure database exists before reading
    init_db()
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    
    # Get latest data
    try:
        c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 10")
        trades = c.fetchall()
        c.execute("SELECT * FROM ghost_trades ORDER BY id DESC LIMIT 15")
        ghosts = c.fetchall()
    except:
        trades, ghosts = [], []
        
    conn.close()
    return render_template_string(HTML_TEMPLATE, trades=trades, ghosts=ghosts)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
