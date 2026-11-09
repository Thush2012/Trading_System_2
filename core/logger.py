import logging
from logging.handlers import RotatingFileHandler


def setup_system_logger(name: str = "TradingSystem", log_file: str = "trading_system.log") -> logging.Logger:
    """
    Configures a thread-safe logger with console output and a rotating file handler.
    File rolls over when reaching 5MB, keeping up to 3 archive backups.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # Standard format: Timestamp - LogLevel - Module - Message
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] (%(name)s) %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # 1. Console Handler (stdout)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)

        # 2. Rotating File Handler (Max 5MB per file, keeps 3 backups)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)

    return logger