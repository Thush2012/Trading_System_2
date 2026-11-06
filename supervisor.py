import subprocess
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (Supervisor) %(message)s")
log = logging.getLogger("Supervisor")

def run_supervisor():
    while True:
        log.info("Launching Institutional Executor (03.executor.py)...")
        try:
            process = subprocess.Popen(["python", "03.executor.py"])
            process.wait()
        except Exception as e:
            log.error(f"Executor process crashed with exception: {e}")
        
        log.warning("Executor exited. Restarting in 5 seconds...")
        time.sleep(5)

if __name__ == "__main__":
    run_supervisor()