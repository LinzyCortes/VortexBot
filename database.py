# ============================================
# VORTEX BOT - DATABASE SYSTEM
# ============================================

import sqlite3
import json
from datetime import datetime
from config import cfg
from logger import logger


class Database:
    def __init__(self):
        self.db_path = cfg.DB_PATH
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Buat semua tabel jika belum ada"""
        with self._connect() as conn:
            cursor = conn.cursor()

            # ─── Tabel Trades ────────────────
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    pair            TEXT NOT NULL,
                    direction       TEXT NOT NULL,
                    entry_price     REAL NOT NULL,
                    sl_price        REAL NOT NULL,
                    tp1_price       REAL,
                    tp2_price       REAL,
                    tp3_price       REAL,
                    size            REAL NOT NULL,
                    leverage        REAL NOT NULL,
                    confluence_score INTEGER,
                    status          TEXT DEFAULT 'OPEN',
                    pnl             REAL DEFAULT 0,
                    rr_achieved     REAL DEFAULT 0,
                    open_time       TEXT NOT NULL,
                    close_time      TEXT,
                    close_reason    TEXT,
                    mode            TEXT,
                    notes           TEXT
                )
            """)

            # ─── Tabel Daily Summary ─────────
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_summary (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    date            TEXT NOT NULL UNIQUE,
                    total_trades    INTEGER DEFAULT 0,
                    win_trades      INTEGER DEFAULT 0,
                    loss_trades     INTEGER DEFAULT 0,
                    winrate         REAL DEFAULT 0,
                    total_pnl       REAL DEFAULT 0,
                    starting_balance REAL DEFAULT 0,
                    ending_balance  REAL DEFAULT 0,
                    max_drawdown    REAL DEFAULT 0,
                    best_trade      REAL DEFAULT 0,
                    worst_trade     REAL DEFAULT 0
                )
            """)

            # ─── Tabel Bot State ─────────────
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    key             TEXT PRIMARY KEY,
                    value           TEXT NOT NULL,
                    updated_at      TEXT NOT NULL
                )
            """)

            # ─── Tabel Signals ───────────────
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    pair            TEXT NOT NULL,
                    direction       TEXT NOT NULL,
                    timeframe       TEXT NOT NULL,
                    confluence_score INTEGER NOT NULL,
                    score_breakdown TEXT,
                    entry_zone      REAL,
                    sl_zone         REAL,
                    tp_zone         REAL,
                    fib_level       TEXT,
                    ob_detected     INTEGER DEFAULT 0,
                    fvg_detected    INTEGER DEFAULT 0,
                    bos_detected    INTEGER DEFAULT 0,
                    killzone        TEXT,
                    detected_at     TEXT NOT NULL,
                    acted_on        INTEGER DEFAULT 0
                )
            """)

            conn.commit()
            logger.info("✅ Database initialized successfully")

    # ─── TRADE METHODS ──────────────────────

    def save_trade(self, trade: dict) -> int:
        """Simpan trade baru ke database"""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trades (
                    pair, direction, entry_price, sl_price,
                    tp1_price, tp2_price, tp3_price,
                    size, leverage, confluence_score,
                    status, open_time, mode, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.get("pair"),
                trade.get("direction"),
                trade.get("entry_price"),
                trade.get("sl_price"),
                trade.get("tp1_price"),
                trade.get("tp2_price"),
                trade.get("tp3_price"),
                trade.get("size"),
                trade.get("leverage"),
                trade.get("confluence_score"),
                "OPEN",
                datetime.now().isoformat(),
                trade.get("mode"),
                trade.get("notes", "")
            ))
            conn.commit()
            trade_id = cursor.lastrowid
            logger.info(f"💾 Trade saved | ID: {trade_id} | {trade.get('pair')} {trade.get('direction')}")
            return trade_id

    def close_trade(self, trade_id: int, close_data: dict):
        """Update trade yang sudah closed"""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE trades SET
                    status       = ?,
                    pnl          = ?,
                    rr_achieved  = ?,
                    close_time   = ?,
                    close_reason = ?
                WHERE id = ?
            """, (
                close_data.get("status", "CLOSED"),
                close_data.get("pnl", 0),
                close_data.get("rr_achieved", 0),
                datetime.now().isoformat(),
                close_data.get("close_reason", ""),
                trade_id
            ))
            conn.commit()
            logger.info(f"💾 Trade closed | ID: {trade_id} | PnL: {close_data.get('pnl', 0):.4f}")

    def get_open_trades(self) -> list:
        """Ambil semua trade yang masih open"""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM trades WHERE status = 'OPEN'
            """)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    def get_today_trades(self) -> list:
        """Ambil semua trade hari ini"""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM trades 
                WHERE open_time LIKE ? 
                ORDER BY open_time DESC
            """, (f"{today}%",))
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    def get_trade_history(self, limit: int = 50) -> list:
        """Ambil history trade terakhir"""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM trades 
                ORDER BY open_time DESC 
                LIMIT ?
            """, (limit,))
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    # ─── DAILY SUMMARY METHODS ──────────────

    def save_daily_summary(self, summary: dict):
        """Simpan atau update daily summary"""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO daily_summary (
                    date, total_trades, win_trades, loss_trades,
                    winrate, total_pnl, starting_balance,
                    ending_balance, max_drawdown, best_trade, worst_trade
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                today,
                summary.get("total_trades", 0),
                summary.get("win_trades", 0),
                summary.get("loss_trades", 0),
                summary.get("winrate", 0),
                summary.get("total_pnl", 0),
                summary.get("starting_balance", 0),
                summary.get("ending_balance", 0),
                summary.get("max_drawdown", 0),
                summary.get("best_trade", 0),
                summary.get("worst_trade", 0)
            ))
            conn.commit()

    def get_overall_stats(self) -> dict:
        """Ambil statistik keseluruhan bot"""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                    SUM(pnl) as total_pnl,
                    AVG(rr_achieved) as avg_rr,
                    MAX(pnl) as best_trade,
                    MIN(pnl) as worst_trade
                FROM trades WHERE status != 'OPEN'
            """)
            row = cursor.fetchone()
            total = row[0] or 0
            wins  = row[1] or 0
            return {
                "total_trades" : total,
                "wins"         : wins,
                "losses"       : row[2] or 0,
                "winrate"      : (wins / total * 100) if total > 0 else 0,
                "total_pnl"    : row[3] or 0,
                "avg_rr"       : row[4] or 0,
                "best_trade"   : row[5] or 0,
                "worst_trade"  : row[6] or 0
            }

    # ─── BOT STATE METHODS ──────────────────

    def set_state(self, key: str, value):
        """Simpan state bot"""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO bot_state (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, json.dumps(value), datetime.now().isoformat()))
            conn.commit()

    def get_state(self, key: str, default=None):
        """Ambil state bot"""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM bot_state WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

    # ─── SIGNAL METHODS ─────────────────────

    def save_signal(self, signal: dict):
        """Simpan signal yang terdeteksi"""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO signals (
                    pair, direction, timeframe, confluence_score,
                    score_breakdown, entry_zone, sl_zone, tp_zone,
                    fib_level, ob_detected, fvg_detected,
                    bos_detected, killzone, detected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal.get("pair"),
                signal.get("direction"),
                signal.get("timeframe"),
                signal.get("confluence_score"),
                json.dumps(signal.get("score_breakdown", {})),
                signal.get("entry_zone"),
                signal.get("sl_zone"),
                signal.get("tp_zone"),
                signal.get("fib_level"),
                int(signal.get("ob_detected", False)),
                int(signal.get("fvg_detected", False)),
                int(signal.get("bos_detected", False)),
                signal.get("killzone"),
                datetime.now().isoformat()
            ))
            conn.commit()


# Instance siap pakai
db = Database()