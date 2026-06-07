# ============================================
# VORTEX BOT - DATABASE BACKUP
# Backup otomatis ke Google Drive
#
# SETUP (sekali saja):
# 1. Buka https://console.cloud.google.com
# 2. Buat project baru atau pakai yang ada
# 3. Enable "Google Drive API"
# 4. IAM & Admin → Service Accounts → Create
# 5. Download JSON key → simpan sebagai google_creds.json di repo
# 6. Buka Google Drive → buat folder "VortexBot Backup"
# 7. Share folder itu ke email service account (dari JSON key)
# 8. Copy folder ID dari URL Drive → isi GDRIVE_FOLDER_ID di Railway Variables
#
# Railway Variables yang dibutuhkan:
#   GDRIVE_FOLDER_ID = folder ID dari Google Drive
#   GOOGLE_CREDS_JSON = isi file google_creds.json (paste as single line)
#
# Atau simpan google_creds.json di repo (jangan di folder docs/)
# ============================================

import os
import json
import shutil
import argparse
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("VortexBot")

WIB = timezone(timedelta(hours=7))

def now_wib():
    return datetime.now(WIB)

def save_status(success: bool, message: str):
    """Simpan status backup terakhir"""
    try:
        with open("backup_status.json", "w") as f:
            json.dump({
                "last_backup"   : now_wib().strftime("%Y-%m-%d %H:%M WIB"),
                "status"        : "success" if success else "failed",
                "message"       : message,
                "timestamp"     : now_wib().isoformat(),
            }, f)
    except Exception:
        pass

def get_gdrive_service():
    """Setup Google Drive service dari credentials"""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        # Coba ambil dari environment variable dulu
        creds_json = os.getenv("GOOGLE_CREDS_JSON")
        if creds_json:
            creds_dict = json.loads(creds_json)
        elif Path("google_creds.json").exists():
            with open("google_creds.json") as f:
                creds_dict = json.load(f)
        else:
            raise FileNotFoundError(
                "Credentials tidak ditemukan.\n"
                "Set GOOGLE_CREDS_JSON di Railway Variables, atau\n"
                "simpan google_creds.json di root repo."
            )

        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds)

    except ImportError:
        raise ImportError(
            "Library Google tidak terinstall.\n"
            "Tambahkan ke requirements.txt:\n"
            "  google-auth\n"
            "  google-auth-oauthlib\n"
            "  google-api-python-client"
        )

def find_db_file() -> str:
    """Cari file database SQLite"""
    candidates = [
        "bot_data.db",
        "data/bot_data.db",
        "database/bot_data.db",
        "vortex.db",
    ]
    for c in candidates:
        if Path(c).exists():
            return c

    # Cari file .db di direktori saat ini
    for f in Path(".").glob("*.db"):
        return str(f)

    raise FileNotFoundError(
        "Database file tidak ditemukan. "
        "Pastikan bot sudah pernah jalan dan DB sudah dibuat."
    )

def backup_to_gdrive(manual: bool = False):
    """Upload database ke Google Drive"""
    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    if not folder_id:
        msg = "GDRIVE_FOLDER_ID tidak di-set di Railway Variables"
        logger.error(f"❌ Backup gagal: {msg}")
        save_status(False, msg)
        return False

    try:
        db_path = find_db_file()
        logger.info(f"📂 Database ditemukan: {db_path}")
    except FileNotFoundError as e:
        save_status(False, str(e))
        logger.error(f"❌ {e}")
        return False

    try:
        from googleapiclient.http import MediaFileUpload

        service = get_gdrive_service()

        # Buat nama file dengan timestamp
        ts  = now_wib().strftime("%Y%m%d_%H%M")
        tag = "manual" if manual else "auto"
        filename = f"vortexbot_db_{ts}_{tag}.db"

        # Cek apakah sudah ada file dengan nama sama, hapus dulu
        existing = service.files().list(
            q=f"name='{filename}' and '{folder_id}' in parents",
            fields="files(id)"
        ).execute()
        for ef in existing.get("files", []):
            service.files().delete(fileId=ef["id"]).execute()

        # Upload
        file_metadata = {"name": filename, "parents": [folder_id]}
        media = MediaFileUpload(db_path, mimetype="application/x-sqlite3")
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id,name,size",
            supportsAllDrives=True
        ).execute()

        size_kb = int(uploaded.get("size", 0)) // 1024
        msg = f"Backup {filename} ({size_kb}KB) sukses ke Google Drive"
        logger.info(f"✅ {msg}")
        save_status(True, msg)

        # Hapus backup lama — keep 7 terbaru
        cleanup_old_backups(service, folder_id, keep=7)

        return True

    except Exception as e:
        msg = str(e)
        logger.error(f"❌ Backup error: {msg}")
        save_status(False, msg)
        return False

def cleanup_old_backups(service, folder_id: str, keep: int = 7):
    """Hapus backup lama, simpan N terbaru"""
    try:
        results = service.files().list(
            q=f"'{folder_id}' in parents and name contains 'vortexbot_db_'",
            orderBy="createdTime desc",
            fields="files(id,name,createdTime)"
        ).execute()

        files = results.get("files", [])
        to_delete = files[keep:]  # hapus yang lebih dari N terbaru

        for f in to_delete:
            service.files().delete(fileId=f["id"]).execute()
            logger.info(f"🗑️ Hapus backup lama: {f['name']}")

    except Exception as e:
        logger.warning(f"⚠️ Cleanup error: {e}")

# ═════════════════════════════════════════════
# SCHEDULED BACKUP — dipanggil dari main.py
# ═════════════════════════════════════════════

def run_scheduled_backup():
    """Jalankan backup terjadwal"""
    logger.info(f"☁️ Starting scheduled backup... | {now_wib().strftime('%H:%M WIB')}")
    success = backup_to_gdrive(manual=False)
    if success:
        logger.info("✅ Scheduled backup complete!")
    else:
        logger.warning("⚠️ Scheduled backup failed — cek GDRIVE setup")

# ═════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

    parser = argparse.ArgumentParser(description="VortexBot Database Backup")
    parser.add_argument("--manual", action="store_true", help="Manual backup trigger")
    parser.add_argument("--test",   action="store_true", help="Test koneksi Google Drive saja")
    args = parser.parse_args()

    if args.test:
        print("Testing Google Drive connection...")
        try:
            svc = get_gdrive_service()
            about = svc.about().get(fields="user").execute()
            print(f"✅ Connected as: {about['user']['emailAddress']}")
            folder_id = os.getenv("GDRIVE_FOLDER_ID")
            if folder_id:
                folder = svc.files().get(fileId=folder_id, fields="name").execute()
                print(f"✅ Folder: {folder['name']}")
            else:
                print("⚠️ GDRIVE_FOLDER_ID belum di-set")
        except Exception as e:
            print(f"❌ Error: {e}")
    else:
        success = backup_to_gdrive(manual=args.manual)
        exit(0 if success else 1)
