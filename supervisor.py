import os
import sys
import time
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (Supervisor) %(message)s")
log = logging.getLogger("Supervisor")

EXECUTOR_SCRIPT = "executor.py"

def run_supervisor():
    log.info("Institutional Trading Supervisor initialized.")
    
    while True:
        if not os.path.exists(EXECUTOR_SCRIPT):
            log.error(f"Target script '{EXECUTOR_SCRIPT}' not found in directory: {os.getcwd()}")
            time.sleep(10)
            continue

        log.info(f"Launching Institutional Executor ({EXECUTOR_SCRIPT}) using active environment...")
        
        try:
            # Use sys.executable to ensure it runs inside the active virtual environment (.venv)
            process = subprocess.Popen([sys.executable, EXECUTOR_SCRIPT])
            process.wait()
            
            if process.returncode != 0:
                log.warning(f"Executor process exited with non-zero code: {process.returncode}")
            else:
                log.info("Executor process exited cleanly.")
                
        except Exception as e:
            log.error(f"Executor process crashed with exception: {e}")
        
        log.warning("Restarting executor sequence in 5 seconds...")
        time.sleep(5)

if __name__ == "__main__":
    run_supervisor()