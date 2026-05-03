# ============================================
# VORTEX BOT - LOGGING SYSTEM
# ============================================

import logging
import os
from datetime import datetime, timezone, timedelta

# ─── WIB Timezone ───────────────────────────
WIB = timezone(timedelta(hours=7))


class WIBFormatter(logging.Formatter):
    """
    Custom formatter yang pakai WIB (Asia/Jakarta, UTC+7)
    untuk semua timestamp log — bukan waktu server (UTC).
    """
    def formatTime(self, record, datefmt=None):
        # Konversi timestamp record ke WIB
        dt = datetime.fromtimestamp(record.created, tz=WIB)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S")


def setup_logger(name: str = "VortexBot") -> logging.Logger:
    """Setup logger dengan file dan console output"""

    # Buat folder logs jika belum ada
    if not os.path.exists("logs"):
        os.makedirs("logs")

    # Format log — semua timestamp akan WIB
    log_format  = "%(asctime)s WIB | %(levelname)-8s | %(name)s | %(message)s"
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
        WIBFormatter(log_format, date_format)
    )

    # ─── File Handler (harian, nama file pakai tanggal WIB) ─
    today_wib    = datetime.now(WIB).strftime("%Y%m%d")
    log_filename = f"logs/vortex_{today_wib}.log"
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        WIBFormatter(log_format, date_format)
    )

    # ─── Error File Handler ─────────────────
    error_handler = logging.FileHandler(
        "logs/vortex_errors.log", encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(
        WIBFormatter(log_format, date_format)
    )

    # Tambah semua handler
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)

    return logger


# ─── Trade Logger ───────────────────────────
def log_trade(action: str, pair: str, data: dict):
    """Log khusus untuk setiap trade (timestamp WIB)"""
    trade_logger = logging.getLogger("VortexBot.Trade")

    # Nama file pakai bulan WIB
    month_wib    = datetime.now(WIB).strftime("%Y%m")
    log_filename = f"logs/trades_{month_wib}.log"

    if not any(
        isinstance(h, logging.FileHandler) and
        "trades_" in h.baseFilename
        for h in trade_logger.handlers
    ):
        handler = logging.FileHandler(log_filename, encoding="utf-8")
        handler.setFormatter(
            WIBFormatter("%(asctime)s WIB | %(message)s", "%Y-%m-%d %H:%M:%S")
        )
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