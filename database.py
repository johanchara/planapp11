"""
database.py - SQLite setup for Plan de Produccion app
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "planapp.db")

CODIGOS_DEFAULT = [
    ("WPO", 4, "WPO", "WPO"),
    ("SPO", 2, "SPO", "SPO"),
    ("MPO", 3, "MPO", "MPO"),
    ("LPO", 6, "LPO", "LPO"),
    ("VASE", 1, "VASE", "VASE"),
    ("CD", 1, "CD", "CD"),
]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS distribucion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash TEXT UNIQUE,
            day TEXT DEFAULT '',
            po_inbound TEXT DEFAULT '',
            load_col TEXT DEFAULT '',
            prioridad TEXT DEFAULT '',
            customer_group TEXT,
            customer TEXT,
            due_date TEXT,
            po_outbound TEXT,
            product_name TEXT,
            pull_date TEXT,
            box TEXT,
            pack REAL,
            boxes REAL,
            activity TEXT,
            buckets REAL,
            updated_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imported_at TEXT,
            data_json TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS import_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imported_at TEXT,
            imported_by TEXT,
            date_from TEXT,
            date_to TEXT,
            rows_added INTEGER,
            rows_updated INTEGER,
            rows_deleted INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS codigos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            multiplicador REAL DEFAULT 1,
            actividad TEXT,
            categoria TEXT
        )
    """)

    # Insert default codigos if table empty
    count = c.execute("SELECT COUNT(*) FROM codigos").fetchone()[0]
    if count == 0:
        c.executemany(
            "INSERT OR IGNORE INTO codigos (codigo, multiplicador, actividad, categoria) VALUES (?,?,?,?)",
            CODIGOS_DEFAULT
        )

    conn.commit()
    conn.close()


def get_codigos_map():
    conn = get_conn()
    rows = conn.execute("SELECT codigo, multiplicador, actividad, categoria FROM codigos").fetchall()
    conn.close()
    result = {}
    for r in rows:
        result[r["codigo"]] = {
            "multiplicador": r["multiplicador"],
            "actividad": r["actividad"],
            "categoria": r["categoria"],
        }
    return result
