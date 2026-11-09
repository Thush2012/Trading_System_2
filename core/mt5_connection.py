import os

import MetaTrader5 as mt5
from dotenv import load_dotenv

from core.logger import setup_system_logger

load_dotenv()
log = setup_system_logger("MT5Bridge")

def connect_mt5() -> bool:
    """Thread-safe MT5 connection bridge."""
    # 1. If already linked on this thread, return True immediately
    if mt5.terminal_info() is not None:
        return True

    # 2. Try default attachment first (attaches to any running MT5 process)
    if mt5.initialize():
        log.info("MT5 attached to active running terminal.")
        return True

    # 3. Fallback: launch headlessly via explicit path & credentials
    raw_path = os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
    clean_path = raw_path.strip('"').strip("'").replace("/", "\\")
    
    login = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    if os.path.exists(clean_path):
        if login and password and server:
            initialized = mt5.initialize(
                path=clean_path,
                login=int(login),
                password=password,
                server=server,
                timeout=30000,
                portable=False
            )
        else:
            initialized = mt5.initialize(path=clean_path)
    else:
        initialized = False

    if not initialized:
        log.error(f"MT5 initialization failed: {mt5.last_error()}")
        return False

    log.info("MT5 headless background process started and linked.")
    return True