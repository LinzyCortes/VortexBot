# ============================================
# VORTEX BOT - LOGGING SYSTEM
# ============================================

import logging
import os
from datetime import datetime

def setup_logger(name: str = "VortexBot") -> logging.Logger:
    """Setup logger dengan file dan console output"""
    
    # Buat folder logs jika belum ada
    if not os.path.exists("logs"):
        os.makedirs("logs")

    # Format log
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Logger utama
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Hindari duplicate handler
    if logger.handlers:
        return logger

    # ─── Console Handler ────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter(log_format, date_format)
    )

    # ─── File Handler (harian) ──────────────
    log_filename = f"logs/vortex_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(log_format, date_format)
    )

    # ─── Error File Handler ─────────────────
    error_filename = f"logs/vortex_errors.log"
    error_handler = logging.FileHandler(error_filename, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(
        logging.Formatter(log_format, date_format)
    )

    # Tambah semua handler
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)

    return logger


# ─── Trade Logger ───────────────────────────
def log_trade(action: str, pair: str, data: dict):
    """Log khusus untuk setiap trade"""
    trade_logger = logging.getLogger("VortexBot.Trade")
    
    log_filename = f"logs/trades_{datetime.now().strftime('%Y%m')}.log"
    if not any(isinstance(h, logging.FileHandler) 
               and "trades_" in h.baseFilename 
               for h in trade_logger.handlers):
        handler = logging.FileHandler(log_filename, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(message)s", "%Y-%m-%d %H:%M:%S"
        ))
        trade_logger.addHandler(handler)
        trade_logger.setLevel(logging.INFO)

    msg = (
        f"{action.upper()} | {pair} | "
        f"Price: {data.get('price', 'N/A')} | "
        f"Size: {data.get('size', 'N/A')} | "
        f"SL: {data.get('sl', 'N/A')} | "
        f"TP: {data.get('tp', 'N/A')} | "
        f"Score: {data.get('score', 'N/A')} | "
        f"RR: {data.get('rr', 'N/A')} | "
        f"PnL: {data.get('pnl', 'N/A')}"
    )
    trade_logger.info(msg)


# Instance siap pakai
logger = setup_logger("VortexBot")