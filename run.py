import subprocess
import sys

def main():
    print("Starting MUESA Trading Engine...")
    bot_process = subprocess.Popen([sys.executable, "muesa_scanner.py"])
    
    print("Starting MUESA Web Dashboard...")
    web_process = subprocess.Popen([sys.executable, "muesa_dashboard.py"])
    
    try:
        bot_process.wait()
        web_process.wait()
    except KeyboardInterrupt:
        bot_process.terminate()
        web_process.terminate()

if __name__ == "__main__":
    main()
