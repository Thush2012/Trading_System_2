import asyncio
from core.scanner import LightweightScanner
from core.logger import setup_system_logger

log = setup_system_logger("StandaloneScanner")

async def main():
    scanner = LightweightScanner()
    log.info("Starting standalone Forex scanner check...")
    results = await scanner.scan_all(bypass_cooldown=True)
    if not results.empty:
        log.info(f"Discovered {len(results)} valid Forex setups:\n{results[['symbol', 'action', 'current_price', 'sl', 'tp1']]}")
    else:
        log.info("No setups met the 200 EMA + ADX >= 20 criteria.")
    await scanner.close()

if __name__ == "__main__":
    asyncio.run(main())