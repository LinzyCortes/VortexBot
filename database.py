# ============================================
# VORTEX BOT - DATABASE SYSTEM
# PostgreSQL + SQLite fallback
# ============================================

import os
import json
import sqlite3
from datetime import datetime
from logger import logger

# Cek apakah PostgreSQL tersedia
DATABASE_URL = os.getenv("DATABASE_URL", "")
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    try:
        import psycopg2
        import psycopg2.extras
        logger.info("🐘 PostgreSQL mode aktif!")
    except ImportError:
        logger.warning(
            "⚠️ psycopg2 tidak ada → pakai SQLite"
        )
        USE_POSTGRES = False


class Database:
    def __init__(self):
        self.use_postgres = USE_POSTGRES
        self.db_url       = DATABASE_URL
        self.db_path      = "vortexbot.db"
        self._init_db()

    def _connect(self):
        """Connect ke database"""
        if self.use_postgres:
            conn = psycopg2.connect(self.db_url)
            conn.autocommit = False
            return conn
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Buat semua tabel"""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()

                if self.use_postgres:
                    # PostgreSQL syntax
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS trades (
                            id               SERIAL PRIMARY KEY,
                            pair             TEXT NOT NULL,
                            direction        TEXT NOT NULL,
                            entry_price      REAL NOT NULL,
                            sl_price         REAL NOT NULL,
                            tp1_price        REAL,
                            tp2_price        REAL,
                            tp3_price        REAL,
                            size             REAL NOT NULL,
                            leverage         REAL NOT NULL,
                            confluence_score INTEGER,
                            status           TEXT DEFAULT 'OPEN',
                            pnl              REAL DEFAULT 0,
                            rr_achieved      REAL DEFAULT 0,
                            open_time        TEXT NOT NULL,
                            close_time       TEXT,
                            close_reason     TEXT,
                            mode             TEXT,
                            notes            TEXT
                        )
                    """)
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS daily_summary (
                            id               SERIAL PRIMARY KEY,
                            date             TEXT NOT NULL UNIQUE,
                            total_trades     INTEGER DEFAULT 0,
                            win_trades       INTEGER DEFAULT 0,
                            loss_trades      INTEGER DEFAULT 0,
                            winrate          REAL DEFAULT 0,
                            total_pnl        REAL DEFAULT 0,
                            starting_balance REAL DEFAULT 0,
                            ending_balance   REAL DEFAULT 0,
                            max_drawdown     REAL DEFAULT 0,
                            best_trade       REAL DEFAULT 0,
                            worst_trade      REAL DEFAULT 0
                        )
                    """)
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS bot_state (
                            key        TEXT PRIMARY KEY,
                            value      TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                    """)
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS signals (
                            id               SERIAL PRIMARY KEY,
                            pair             TEXT NOT NULL,
                            direction        TEXT NOT NULL,
                            timeframe        TEXT NOT NULL,
                            confluence_score INTEGER NOT NULL,
                            score_breakdown  TEXT,
                            entry_zone       REAL,
                            sl_zone          REAL,
                            tp_zone          REAL,
                            fib_level        TEXT,
                            ob_detected      INTEGER DEFAULT 0,
                            fvg_detected     INTEGER DEFAULT 0,
                            bos_detected     INTEGER DEFAULT 0,
                            killzone         TEXT,
                            detected_at      TEXT NOT NULL,
                            acted_on         INTEGER DEFAULT 0
                        )
                    """)
                else:
                    # SQLite syntax
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS trades (
                            id               INTEGER PRIMARY KEY AUTOINCREMENT,
                            pair             TEXT NOT NULL,
                            direction        TEXT NOT NULL,
                            entry_price      REAL NOT NULL,
                            sl_price         REAL NOT NULL,
                            tp1_price        REAL,
                            tp2_price        REAL,
                            tp3_price        REAL,
                            size             REAL NOT NULL,
                            leverage         REAL NOT NULL,
                            confluence_score INTEGER,
                            status           TEXT DEFAULT 'OPEN',
                            pnl              REAL DEFAULT 0,
                            rr_achieved      REAL DEFAULT 0,
                            open_time        TEXT NOT NULL,
                            close_time       TEXT,
                            close_reason     TEXT,
                            mode             TEXT,
                            notes            TEXT
                        )
                    """)
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS daily_summary (
                            id               INTEGER PRIMARY KEY AUTOINCREMENT,
                            date             TEXT NOT NULL UNIQUE,
                            total_trades     INTEGER DEFAULT 0,
                            win_trades       INTEGER DEFAULT 0,
                            loss_trades      INTEGER DEFAULT 0,
                            winrate          REAL DEFAULT 0,
                            total_pnl        REAL DEFAULT 0,
                            starting_balance REAL DEFAULT 0,
                            ending_balance   REAL DEFAULT 0,
                            max_drawdown     REAL DEFAULT 0,
                            best_trade       REAL DEFAULT 0,
                            worst_trade      REAL DEFAULT 0
                        )
                    """)
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS bot_state (
                            key        TEXT PRIMARY KEY,
                            value      TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                    """)
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS signals (
                            id               INTEGER PRIMARY KEY AUTOINCREMENT,
                            pair             TEXT NOT NULL,
                            direction        TEXT NOT NULL,
                            timeframe        TEXT NOT NULL,
                            confluence_score INTEGER NOT NULL,
                            score_breakdown  TEXT,
                            entry_zone       REAL,
                            sl_zone          REAL,
                            tp_zone          REAL,
                            fib_level        TEXT,
                            ob_detected      INTEGER DEFAULT 0,
                            fvg_detected     INTEGER DEFAULT 0,
                            bos_detected     INTEGER DEFAULT 0,
                            killzone         TEXT,
                            detected_at      TEXT NOT NULL,
                            acted_on         INTEGER DEFAULT 0
                        )
                    """)

                conn.commit()
                db_type = "PostgreSQL" if self.use_postgres else "SQLite"
                logger.info(f"✅ {db_type} database initialized!")

        except Exception as e:
            logger.error(f"❌ DB init error: {e}")
            if self.use_postgres:
                logger.warning("⚠️ Fallback ke SQLite!")
                self.use_postgres = False
                self._init_db()

    # ─── TRADE METHODS ──────────────────────

    def save_trade(self, trade: dict) -> int:
        """Simpan trade baru"""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                if self.use_postgres:
                    cursor.execute("""
                        INSERT INTO trades (
                            pair, direction, entry_price, sl_price,
                            tp1_price, tp2_price, tp3_price,
                            size, leverage, confluence_score,
                            status, open_time, mode, notes
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id
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
                    trade_id = cursor.fetchone()[0]
                else:
                    cursor.execute("""
                        INSERT INTO trades (
                            pair, direction, entry_price, sl_price,
                            tp1_price, tp2_price, tp3_price,
                            size, leverage, confluence_score,
                            status, open_time, mode, notes
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    trade_id = cursor.lastrowid

                conn.commit()
                logger.info(
                    f"💾 Trade saved #{trade_id}: "
                    f"{trade.get('pair')} {trade.get('direction')}"
                )
                return trade_id

        except Exception as e:
            logger.error(f"❌ Save trade error: {e}")
            return 0

    def close_trade(self, trade_id: int,
                    close_data: dict):
        """Update trade yang sudah closed"""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                ph = "%s" if self.use_postgres else "?"
                cursor.execute(f"""
                    UPDATE trades SET
                        status       = {ph},
                        pnl          = {ph},
                        rr_achieved  = {ph},
                        close_time   = {ph},
                        close_reason = {ph}
                    WHERE id = {ph}
                """, (
                    close_data.get("status", "CLOSED"),
                    close_data.get("pnl", 0),
                    close_data.get("rr_achieved", 0),
                    datetime.now().isoformat(),
                    close_data.get("close_reason", ""),
                    trade_id
                ))
                conn.commit()
                logger.info(
                    f"💾 Trade closed #{trade_id} | "
                    f"PnL: {close_data.get('pnl', 0):.4f}"
                )
        except Exception as e:
            logger.error(f"❌ Close trade error: {e}")

    def get_open_trades(self) -> list:
        """Ambil open trades"""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                ph = "%s" if self.use_postgres else "?"
                cursor.execute(
                    f"SELECT * FROM trades WHERE status = {ph}",
                    ("OPEN",)
                )
                cols = [d[0] for d in cursor.description]
                return [dict(zip(cols, r)) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"❌ Get open trades error: {e}")
            return []

    def get_today_trades(self) -> list:
        """Ambil trade hari ini"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            with self._connect() as conn:
                cursor = conn.cursor()
                if self.use_postgres:
                    cursor.execute("""
                        SELECT * FROM trades
                        WHERE open_time LIKE %s
                        ORDER BY open_time DESC
                    """, (f"{today}%",))
                else:
                    cursor.execute("""
                        SELECT * FROM trades
                        WHERE open_time LIKE ?
                        ORDER BY open_time DESC
                    """, (f"{today}%",))
                cols = [d[0] for d in cursor.description]
                return [dict(zip(cols, r)) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"❌ Get today trades error: {e}")
            return []

    def get_trade_history(self, limit: int = 50) -> list:
        """Ambil history trade"""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                ph = "%s" if self.use_postgres else "?"
                cursor.execute(
                    f"SELECT * FROM trades ORDER BY open_time DESC LIMIT {ph}",
                    (limit,)
                )
                cols = [d[0] for d in cursor.description]
                return [dict(zip(cols, r)) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"❌ Get history error: {e}")
            return []

    # ─── DAILY SUMMARY ──────────────────────

    def save_daily_summary(self, summary: dict):
        """Simpan daily summary"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            with self._connect() as conn:
                cursor = conn.cursor()
                if self.use_postgres:
                    cursor.execute("""
                        INSERT INTO daily_summary (
                            date, total_trades, win_trades,
                            loss_trades, winrate, total_pnl,
                            starting_balance, ending_balance,
                            max_drawdown, best_trade, worst_trade
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (date) DO UPDATE SET
                            total_trades     = EXCLUDED.total_trades,
                            win_trades       = EXCLUDED.win_trades,
                            loss_trades      = EXCLUDED.loss_trades,
                            winrate          = EXCLUDED.winrate,
                            total_pnl        = EXCLUDED.total_pnl,
                            ending_balance   = EXCLUDED.ending_balance
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
                        summary.get("worst_trade", 0),
                    ))
                else:
                    cursor.execute("""
                        INSERT OR REPLACE INTO daily_summary (
                            date, total_trades, win_trades,
                            loss_trades, winrate, total_pnl,
                            starting_balance, ending_balance,
                            max_drawdown, best_trade, worst_trade
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
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
                        summary.get("worst_trade", 0),
                    ))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Save daily summary error: {e}")

    def get_overall_stats(self) -> dict:
        """Statistik keseluruhan"""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                ph = "%s" if self.use_postgres else "?"
                cursor.execute(f"""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                        SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                        SUM(pnl) as total_pnl,
                        AVG(rr_achieved) as avg_rr,
                        MAX(pnl) as best,
                        MIN(pnl) as worst
                    FROM trades WHERE status != {ph}
                """, ("OPEN",))
                row   = cursor.fetchone()
                total = row[0] or 0
                wins  = row[1] or 0
                return {
                    "total_trades": total,
                    "wins"        : wins,
                    "losses"      : row[2] or 0,
                    "winrate"     : (wins/total*100) if total > 0 else 0,
                    "total_pnl"   : row[3] or 0,
                    "avg_rr"      : row[4] or 0,
                    "best_trade"  : row[5] or 0,
                    "worst_trade" : row[6] or 0,
                }
        except Exception as e:
            logger.error(f"❌ Get stats error: {e}")
            return {}

    # ─── BOT STATE ──────────────────────────

    def set_state(self, key: str, value):
        """Simpan state bot"""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                ph = "%s" if self.use_postgres else "?"
                if self.use_postgres:
                    cursor.execute("""
                        INSERT INTO bot_state (key, value, updated_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (key) DO UPDATE SET
                            value      = EXCLUDED.value,
                            updated_at = EXCLUDED.updated_at
                    """, (
                        key,
                        json.dumps(value),
                        datetime.now().isoformat()
                    ))
                else:
                    cursor.execute("""
                        INSERT OR REPLACE INTO bot_state
                        (key, value, updated_at)
                        VALUES (?, ?, ?)
                    """, (
                        key,
                        json.dumps(value),
                        datetime.now().isoformat()
                    ))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Set state error {key}: {e}")

    def get_state(self, key: str, default=None):
        """Ambil state bot"""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                ph = "%s" if self.use_postgres else "?"
                cursor.execute(
                    f"SELECT value FROM bot_state WHERE key = {ph}",
                    (key,)
                )
                row = cursor.fetchone()
                if row:
                    return json.loads(row[0])
                return default
        except Exception as e:
            logger.error(f"❌ Get state error {key}: {e}")
            return default

    # ─── SIGNALS ────────────────────────────

    def save_signal(self, signal: dict):
        """Simpan signal"""
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                if self.use_postgres:
                    cursor.execute("""
                        INSERT INTO signals (
                            pair, direction, timeframe,
                            confluence_score, score_breakdown,
                            entry_zone, sl_zone, tp_zone,
                            fib_level, ob_detected,
                            fvg_detected, bos_detected,
                            killzone, detected_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                        signal.get("pair"),
                        signal.get("direction"),
                        signal.get("tf_entry", "15m"),
                        signal.get("confluence_score"),
                        json.dumps(signal.get("score_breakdown", {})),
                        signal.get("entry_price"),
                        signal.get("sl_price"),
                        signal.get("tp2_price"),
                        signal.get("fib_level"),
                        int(signal.get("ob_detected", False)),
                        int(signal.get("fvg_detected", False)),
                        int(signal.get("bos_detected", False)),
                        signal.get("killzone"),
                        datetime.now().isoformat()
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO signals (
                            pair, direction, timeframe,
                            confluence_score, score_breakdown,
                            entry_zone, sl_zone, tp_zone,
                            fib_level, ob_detected,
                            fvg_detected, bos_detected,
                            killzone, detected_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        signal.get("pair"),
                        signal.get("direction"),
                        signal.get("tf_entry", "15m"),
                        signal.get("confluence_score"),
                        json.dumps(signal.get("score_breakdown", {})),
                        signal.get("entry_price"),
                        signal.get("sl_price"),
                        signal.get("tp2_price"),
                        signal.get("fib_level"),
                        int(signal.get("ob_detected", False)),
                        int(signal.get("fvg_detected", False)),
                        int(signal.get("bos_detected", False)),
                        signal.get("killzone"),
                        datetime.now().isoformat()
                    ))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Save signal error: {e}")


# Instance siap pakai
db = Database()