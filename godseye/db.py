"""Database access: SQLite locally, PostgreSQL (e.g. Neon on Vercel) when DATABASE_URL is set.

All SQL in the app uses `?` placeholders, ISO-8601 text timestamps and JSON stored as text, so the same
statements run on both. Never put a literal `%` or `?` in SQL text: pass patterns as parameters."""
import json
import sqlite3
import threading
from pathlib import Path

from .config import ROOT, Config

_SCHEMA = (ROOT / "godseye" / "schema.sql").read_text(encoding="utf-8")
_init_lock = threading.Lock()


class Conn:
    def __init__(self, raw, dialect: str):
        self.raw = raw
        self.dialect = dialect

    def _sql(self, sql: str) -> str:
        return sql.replace("%", "%%").replace("?", "%s") if self.dialect == "pg" else sql

    def all(self, sql: str, params=()) -> list[dict]:
        cur = self.raw.cursor()
        cur.execute(self._sql(sql), tuple(params))
        rows = cur.fetchall()
        if self.dialect == "sqlite":
            return [dict(r) for r in rows]
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

    def one(self, sql: str, params=()) -> dict | None:
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params=()):
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None

    def run(self, sql: str, params=()) -> int:
        cur = self.raw.cursor()
        cur.execute(self._sql(sql), tuple(params))
        return cur.rowcount

    def insert(self, table: str, data: dict) -> int:
        cols = list(data)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) RETURNING id"
        return int(self.one(sql, [data[c] for c in cols])["id"])

    def update(self, table: str, row_id: int, data: dict) -> None:
        if data:
            sets = ", ".join(f"{c} = ?" for c in data)
            self.run(f"UPDATE {table} SET {sets} WHERE id = ?", [*data.values(), row_id])

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()


class Database:
    def __init__(self, cfg: Config, db_path: str | None = None):
        self.cfg = cfg
        self.dialect = "pg" if cfg.database_url else "sqlite"
        self.path = db_path or cfg.db_path
        self._initialized = False

    def connect(self) -> Conn:
        if self.dialect == "pg":
            import psycopg  # only needed for PostgreSQL

            raw = psycopg.connect(self.cfg.database_url, connect_timeout=10, prepare_threshold=None)
            conn = Conn(raw, "pg")
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            raw = sqlite3.connect(self.path, timeout=15)
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA busy_timeout = 15000")
            raw.execute("PRAGMA foreign_keys = ON")
            conn = Conn(raw, "sqlite")
        if not self._initialized:
            with _init_lock:
                if not self._initialized:
                    self._init_schema(conn)
                    self._initialized = True
        return conn

    def _init_schema(self, conn: Conn) -> None:
        if self.dialect == "sqlite":
            conn.raw.execute("PRAGMA journal_mode = WAL")
            conn.raw.executescript(_SCHEMA.replace("{PK}", "INTEGER PRIMARY KEY AUTOINCREMENT"))
        else:
            cur = conn.raw.cursor()
            for stmt in _SCHEMA.replace("{PK}", "BIGSERIAL PRIMARY KEY").split(";"):
                body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
                if body:
                    cur.execute(body)
        conn.commit()


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(value, default=None):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
