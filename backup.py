# ============================================
# VORTEX BOT - DATABASE BACKUP
# Backup database ke Telegram (primary) dan Google Drive (optional)
#
# Cara kerja:
# - Setiap hari jam 07:00 WIB, bot kirim file .db ke Telegram kamu
# - Tidak perlu setup apapun selain bot Telegram yang sudah ada
# - Optional: setup Google Drive untuk backup kedua
# ============================================

import os
import json
import shutil
import argparse
import logging
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("VortexBot")

WIB = timezone(timedelta(hours=7))

def now_wib():
    return datetime.now(WIB)

def save_status(success: bool, message: str):
    try:
        with open("backup_status.json", "w") as f:
            json.dump({
                "last_backup" : now_wib().strftime("%Y-%m-%d %H:%M WIB"),
                "status"      : "success" if success else "failed",
                "message"     : message,
                "timestamp"   : now_wib().isoformat(),
            }, f)
    except Exception:
        pass

def find_db_file() -> str:
    candidates = [
        "bot_data.db", "data/bot_data.db",
        "database/bot_data.db", "vortex.db",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    for f in Path(".").glob("*.db"):
        return str(f)
    raise FileNotFoundError("Database file tidak ditemukan.")

# ═════════════════════════════════════════════
# PRIMARY: TELEGRAM BACKUP
# ═════════════════════════════════════════════

def backup_to_telegram(manual: bool = False) -> bool:
    """Kirim file database ke Telegram — tidak perlu setup tambahan"""
    token   = os.getenv("TELEGRAM_BOT_TOKEN", os.getenv("BOT_TOKEN", ""))
    chat_id = os.getenv("TELEGRAM_CHAT_ID",   os.getenv("CHAT_ID",   ""))

    if not token or not chat_id:
        logger.warning("⚠️ TELEGRAM_BOT_TOKEN atau CHAT_ID tidak ada — skip Telegram backup")
        return False

    try:
        db_path = find_db_file()
    except FileNotFoundError as e:
        save_status(False, str(e))
        logger.error(f"❌ {e}")
        return False

    try:
        ts       = now_wib().strftime("%Y-%m-%d %H:%M WIB")
        tag      = "MANUAL" if manual else "AUTO"
        caption  = (
            f"💾 <b>VORTEX BOT — DATABASE BACKUP</b>\n"
            f"=====================================\n"
            f"⏰ {ts}\n"
            f"🏷️ Type  : {tag}\n"
            f"📁 File  : {Path(db_path).name}\n"
            f"📦 Size  : {Path(db_path).stat().st_size // 1024} KB\n"
            f"=====================================\n"
            f"Simpan file ini untuk restore jika Railway reset."
        )

        url  = f"https://api.telegram.org/bot{token}/sendDocument"
        with open(db_path, "rb") as f:
            resp = requests.post(url, data={
                "chat_id"   : chat_id,
                "caption"   : caption,
                "parse_mode": "HTML",
            }, files={"document": (f"vortexbot_db_{now_wib().strftime('%Y%m%d_%H%M')}.db", f)},
            timeout=60)

        if resp.status_code == 200 and resp.json().get("ok"):
            msg = f"Backup via Telegram sukses ({tag})"
            logger.info(f"✅ {msg}")
            save_status(True, msg)
            return True
        else:
            err = resp.json().get("description", "Unknown error")
            raise Exception(f"Telegram API error: {err}")

    except Exception as e:
        msg = str(e)
        logger.error(f"❌ Telegram backup error: {msg}")
        save_status(False, msg)
        return False

# ═════════════════════════════════════════════
# SECONDARY: GOOGLE DRIVE BACKUP (optional)
# ═════════════════════════════════════════════

def backup_to_gdrive(manual: bool = False) -> bool:
    """Upload database ke Google Drive — perlu setup Service Account"""
    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    if not folder_id:
        logger.info("ℹ️ GDRIVE_FOLDER_ID tidak di-set — skip Google Drive backup")
        return False

    try:
        db_path = find_db_file()
    except FileNotFoundError as e:
        logger.error(f"❌ {e}")
        return False

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        creds_json = os.getenv("GOOGLE_CREDS_JSON")
        if creds_json:
            creds_dict = json.loads(creds_json)
        elif Path("google_creds.json").exists():
            with open("google_creds.json") as f:
                creds_dict = json.load(f)
        else:
            logger.warning("⚠️ Google credentials tidak ditemukan — skip GDrive backup")
            return False

        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        service = build("drive", "v3", credentials=creds)

        ts       = now_wib().strftime("%Y%m%d_%H%M")
        tag      = "manual" if manual else "auto"
        filename = f"vortexbot_db_{ts}_{tag}.db"

        file_metadata = {"name": filename, "parents": [folder_id]}
        media = MediaFileUpload(db_path, mimetype="application/octet-stream", resumable=True)
        request = service.files().create(body=file_metadata, media_body=media, fields="id,name,size")

        uploaded = None
        while uploaded is None:
            _, uploaded = request.next_chunk()

        size_kb = int((uploaded or {}).get("size", 0)) // 1024
        msg = f"GDrive backup {filename} ({size_kb}KB) sukses"
        logger.info(f"✅ {msg}")

        # Hapus backup lama — keep 7 terbaru
        try:
            results = service.files().list(
                q=f"\'{folder_id}\' in parents and name contains \'vortexbot_db_\'",
                orderBy="createdTime desc",
                fields="files(id,name)"
            ).execute()
            files = results.get("files", [])
            for old_file in files[7:]:
                service.files().delete(fileId=old_file["id"]).execute()
        except Exception:
            pass

        return True

    except Exception as e:
        logger.warning(f"⚠️ GDrive backup error: {e}")
        return False

# ═════════════════════════════════════════════
# MAIN BACKUP — jalankan keduanya
# ═════════════════════════════════════════════

def run_scheduled_backup():
    logger.info(f"💾 Starting backup... | {now_wib().strftime('%H:%M WIB')}")

    # Primary: Telegram (selalu jalan kalau bot token ada)
    tg_ok = backup_to_telegram(manual=False)

    # Secondary: Google Drive (opsional)
    gd_ok = backup_to_gdrive(manual=False)

    if tg_ok or gd_ok:
        logger.info(f"✅ Backup done | TG:{'✅' if tg_ok else '❌'} GDrive:{'✅' if gd_ok else '❌'}")
    else:
        logger.error("❌ Semua backup gagal!")

# ═════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--test",   action="store_true")
    args = parser.parse_args()

    if args.test:
        print("Testing backup connections...")
        token   = os.getenv("TELEGRAM_BOT_TOKEN", os.getenv("BOT_TOKEN",""))
        chat_id = os.getenv("TELEGRAM_CHAT_ID",   os.getenv("CHAT_ID",""))
        print(f"Telegram token: {'✅ ada' if token else '❌ tidak ada'}")
        print(f"Telegram chat_id: {'✅ ada' if chat_id else '❌ tidak ada'}")
        folder = os.getenv("GDRIVE_FOLDER_ID","")
        print(f"GDrive folder: {'✅ '+folder if folder else 'ℹ️ tidak di-set (optional)'}")
    else:
        tg = backup_to_telegram(manual=args.manual)
        gd = backup_to_gdrive(manual=args.manual)
        print(f"Telegram: {'✅' if tg else '❌'} | GDrive: {'✅' if gd else '❌'}")
        exit(0 if (tg or gd) else 1)
