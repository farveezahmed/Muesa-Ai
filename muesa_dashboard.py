from flask import Flask, render_template
import sqlite3
import os
from muesa_logic import init_db

app = Flask(__name__)

# Route to display the dashboard
@app.route('/')
def dashboard():
    # Ensure database is initialized
    init_db()
    
    conn = sqlite3.connect('muesa_data.db')
    c = conn.cursor()
    
    try:
        # Fetch last 10 Live Trades
        c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 10")
        trades = c.fetchall()
        
        # Fetch last 15 Ghost Trades (Math 60+ but rejected)
        c.execute("SELECT * FROM ghost_trades ORDER BY id DESC LIMIT 15")
        ghosts = c.fetchall()
    except Exception as e:
        print(f"Dashboard Database Error: {e}")
        trades, ghosts = [], []
    finally:
        conn.close()
        
    return render_template('dashboard.html', trades=trades, ghosts=ghosts)

if __name__ == '__main__':
    # Railway provides the PORT environment variable
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
