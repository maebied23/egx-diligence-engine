"""SQLite connection and schema setup."""
import sqlite3
from importlib.resources import files
from pathlib import Path

from efe import config


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=120)  # wait for another efe process instead of failing
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(files("efe").joinpath("schema.sql").read_text(encoding="utf-8"))
    conn.commit()
