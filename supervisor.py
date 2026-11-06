import os
import time
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (Supervisor) %(message)s")
log = logging.getLogger("Supervisor")

# Define the target executor script name (matches your repository structure)
EXECUTOR_SCRIPT = "03.executor.py"

def run_supervisor():
    log.info("Institutional Trading Supervisor initialized.")
    
    while True:
        # Check if the executor script exists in the current working directory
        if not os.path.exists(EXECUTOR_SCRIPT):
            log.error(f"Target script '{EXECUTOR_SCRIPT}' not found in directory: {os.getcwd()}")
            log.error("Please verify your file location or update the EXECUTOR_SCRIPT variable.")
            time.sleep(10)
            continue

        log.info(f"Launching Institutional Executor ({EXECUTOR_SCRIPT})...")
        
        try:
            # Spawn the executor process using the active python interpreter
            process = subprocess.Popen(["python", EXECUTOR_SCRIPT])
            
            # Wait for the process to complete or crash
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