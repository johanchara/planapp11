"""
database.py - PostgreSQL (Render) / SQLite (local) - transparent wrapper
"""
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_POSTGRES = bool(DATABASE_URL)

CODIGOS_DEFAULT = [
    ("WPO", 4, "WPO", "WPO"),
    ("SPO", 2, "SPO", "SPO"),
    ("MPO", 3, "MPO", "MPO"),
    ("LPO", 6, "LPO", "LPO"),
    ("VASE", 1, "VASE", "VASE"),
    ("CD", 1, "CD", "CD"),
]


class _CursorWrapper:
    """Wraps postgres cursor to behave like sqlite3 cursor with dict rows."""
    def __init__(self, cur, pg=False):
        self._cur = cur
        self._pg = pg

    def execute(self, sql, params=()):
        if self._pg:
            sql = sql.replace("?", "%s")
        self._cur.execute(sql, params)
        return self

    def executemany(self, sql, seq):
        if self._pg:
            sql = sql.replace("?", "%s")
        self._cur.executemany(sql, seq)

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        if self._pg:
            cols = [d[0] for d in self._cur.description]
            return dict(zip(cols, row))
        return row  # sqlite Row already supports dict()

    def fetchall(self):
        rows = self._cur.fetchall()
        if self._pg:
            cols = [d[0] for d in self._cur.description]
            return [dict(zip(cols, r)) for r in rows]
        return rows

    @property
    def description(self):
        return self._cur.description


class _ConnWrapper:
    """Wraps a DB connection so execute() returns _CursorWrapper."""
    def __init__(self, conn, pg=False):
        self._conn = conn
        self._pg = pg

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        return _CursorWrapper(cur, self._pg).execute(sql, params)

    def cursor(self):
        return _CursorWrapper(self._conn.cursor(), self._pg)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._conn.close()


def get_conn() -> _ConnWrapper:
    if USE_POSTGRES:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return _ConnWrapper(conn, pg=True)
    else:
        import sqlite3
        DB_PATH = os.environ.get("DB_PATH", "planapp.db")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return _ConnWrapper(conn, pg=False)


def init_db():
    conn = get_conn()

    serial = "SERIAL" if USE_POSTGRES else "INTEGER"
    upsert_codigos = (
        "INSERT INTO codigos (codigo,multiplicador,actividad,categoria) VALUES (?,?,?,?) ON CONFLICT (codigo) DO NOTHING"
        if not USE_POSTGRES else
        "INSERT INTO codigos (codigo,multiplicador,actividad,categoria) VALUES (?,?,?,?) ON CONFLICT (codigo) DO NOTHING"
    )

    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            id {serial} PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS distribucion (
            id {serial} PRIMARY KEY,
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
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS sales (
            id {serial} PRIMARY KEY,
            imported_at TEXT,
            data_json TEXT
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS import_log (
            id {serial} PRIMARY KEY,
            imported_at TEXT,
            imported_by TEXT,
            date_from TEXT,
            date_to TEXT,
            rows_added INTEGER,
            rows_updated INTEGER,
            rows_deleted INTEGER
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS codigos (
            id {serial} PRIMARY KEY,
            codigo TEXT UNIQUE NOT NULL,
            multiplicador REAL DEFAULT 1,
            actividad TEXT,
            categoria TEXT
        )
    """)

    count = conn.execute("SELECT COUNT(*) FROM codigos").fetchone()[0]
    if count == 0:
        for row in CODIGOS_DEFAULT:
            conn.execute(upsert_codigos, row)

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
