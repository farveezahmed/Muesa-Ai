import os
import threading
import subprocess
import sys
from flask import Flask

app = Flask(__name__)

@app.route('/')
def health():
    return "MUESA ONLINE ✅", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # Start single Flask health check
    threading.Thread(target=run_flask, daemon=True).start()
    print("✅ MUESA Health Check Online")
    
    # Start scanner only
    print("🚀 Starting MUESA Scanner...")
    subprocess.Popen([sys.executable, "muesa_scanner.py"]).wait()
