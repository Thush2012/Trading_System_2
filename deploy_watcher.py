import os
import subprocess
import sys
import time

from dotenv import load_dotenv

load_dotenv()

PROJECT_DIR = r"C:\Users\thush\trading_system"
PYTHON_EXE = os.path.join(PROJECT_DIR, ".venv", "Scripts", "pythonw.exe") # Use pythonw to prevent engine window
MAIN_SCRIPT = os.path.join(PROJECT_DIR, "main.py")

os.chdir(PROJECT_DIR)

from core.config import Config
from core.logger import setup_system_logger
from core.notifier import TelegramNotifier

log = setup_system_logger("DeployWatcher")
notifier = TelegramNotifier(bot_token=Config.TELEGRAM_BOT_TOKEN, chat_id=Config.TELEGRAM_CHAT_ID)

# Windows flag: Strictly suppress any console popup
NO_WINDOW_FLAG = 0x08000000 if sys.platform == "win32" else 0

def get_current_git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            creationflags=NO_WINDOW_FLAG,
            stderr=subprocess.DEVNULL
        ).decode().strip()[:7]
    except Exception:
        return "UNKNOWN"

def check_remote_updates() -> bool:
    try:
        subprocess.check_call(
            ["git", "fetch", "origin", "main"],
            creationflags=NO_WINDOW_FLAG,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        local_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            creationflags=NO_WINDOW_FLAG,
            stderr=subprocess.DEVNULL
        ).decode().strip()
        remote_hash = subprocess.check_output(
            ["git", "rev-parse", "origin/main"],
            creationflags=NO_WINDOW_FLAG,
            stderr=subprocess.DEVNULL
        ).decode().strip()
        return local_hash != remote_hash
    except Exception as e:
        log.error(f"Git check error: {e}")
        return False

def pull_and_rebuild() -> str:
    subprocess.check_call(
        ["git", "pull", "origin", "main"],
        creationflags=NO_WINDOW_FLAG,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    req_file = os.path.join(PROJECT_DIR, "requirements.txt")
    if os.path.exists(req_file):
        pip_exe = os.path.join(PROJECT_DIR, ".venv", "Scripts", "pip.exe")
        subprocess.call(
            [pip_exe, "install", "-r", "requirements.txt"],
            creationflags=NO_WINDOW_FLAG,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    return get_current_git_hash()

def main():
    log.info("Continuous deployment watcher initialized.")
    initial_hash = get_current_git_hash()

    notifier.send_alert(
        f"🖥️ *Windows Background Service Live*\n"
        f"• Git Commit: `{initial_hash}`\n"
        f"• Status: 100% Silent (Zero Popups)\n"
        f"• GitHub Sync: Active"
    )

    # Spawn engine with NO_WINDOW flag
    bot_proc = subprocess.Popen(
        [PYTHON_EXE, MAIN_SCRIPT],
        creationflags=NO_WINDOW_FLAG,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    while True:
        try:
            time.sleep(60)

            # Auto-restart if crashed
            if bot_proc.poll() is not None:
                log.warning("Main engine stopped unexpectedly. Relaunching...")
                notifier.send_alert("⚠️ *Engine Recovering:* Process restarted after unexpected exit.")
                bot_proc = subprocess.Popen(
                    [PYTHON_EXE, MAIN_SCRIPT],
                    creationflags=NO_WINDOW_FLAG,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

            # Check GitHub for updates
            if check_remote_updates():
                log.info("New commit detected! Reloading...")
                notifier.send_alert("📦 *GitHub Push Detected!* Pulling code and reloading engine...")

                bot_proc.terminate()
                try:
                    bot_proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    bot_proc.kill()

                new_hash = pull_and_rebuild()
                bot_proc = subprocess.Popen(
                    [PYTHON_EXE, MAIN_SCRIPT],
                    creationflags=NO_WINDOW_FLAG,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

                notifier.send_alert(f"✅ *Update Applied Successfully!*\n• Version: `{new_hash}`\n• System live.")
        except Exception as e:
            log.error(f"Watcher loop error: {e}")
            time.sleep(15)

if __name__ == "__main__":
    main()