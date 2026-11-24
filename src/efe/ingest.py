"""Download the filings listed in data/sources/filings.csv into data/raw/ and register them.

Downloads use curl: some company sites (e.g. misrcementgroup.com) reject Python's HTTP
client but serve the same public files to curl and browsers. Re-running is safe: files
already on disk with a recorded hash are skipped.
"""
import csv
import datetime as dt
import hashlib
import re
import sqlite3
import subprocess
import time
from pathlib import Path

from efe import config

UA = "Mozilla/5.0 (egx-diligence-engine)"
DELAY_S = 1.0


def local_name(row: dict) -> str:
    parts = [row["fiscal_year"], row["period"], row["scope"], row["framework"] or "NA", row["doc_type"]]
    url_tag = hashlib.sha1(row["url"].encode()).hexdigest()[:6]  # keeps names unique per source
    return re.sub(r"[^A-Za-z0-9_.-]", "-", "_".join(parts)) + f"_{url_tag}.pdf"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    subprocess.run(["curl", "-sSfL", "-m", "180", "-A", UA, "-o", str(tmp), url], check=True)
    with open(tmp, "rb") as fh:
        if fh.read(5) != b"%PDF-":
            tmp.unlink()
            raise ValueError("response is not a PDF")
    tmp.rename(dest)


def register(conn: sqlite3.Connection, row: dict, path: Path) -> None:
    conn.execute(
        """INSERT INTO documents (ticker, fiscal_year, period, period_end, scope, framework, language,
                                  doc_type, source, source_url, local_path, sha256, bytes, downloaded_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(source_url) DO UPDATE SET local_path=excluded.local_path, sha256=excluded.sha256,
               bytes=excluded.bytes, downloaded_at=excluded.downloaded_at""",
        (row["ticker"], int(row["fiscal_year"]), row["period"], row["period_end"], row["scope"],
         row["framework"], row["language"], row["doc_type"], row["source"], row["url"],
         str(path.relative_to(config.ROOT)), sha256_of(path), path.stat().st_size,
         dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")),
    )
    conn.commit()


def run(conn: sqlite3.Connection, csv_path: Path = config.FILINGS_CSV, tickers: set[str] | None = None) -> dict:
    stats = {"downloaded": 0, "already_present": 0, "no_url": 0, "failed": 0}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    known = {r["source_url"] for r in conn.execute("SELECT source_url FROM documents WHERE sha256 IS NOT NULL")}
    for row in rows:
        if tickers and row["ticker"] not in tickers:
            continue
        if not row["url"]:
            stats["no_url"] += 1
            continue
        if row["source"] == "lse_rns":  # web page, not a PDF
            continue
        path = config.RAW / row["ticker"] / local_name(row)
        if path.exists() and row["url"] in known:
            stats["already_present"] += 1
            continue
        try:
            if not path.exists():
                download(row["url"], path)
                time.sleep(DELAY_S)
            register(conn, row, path)
            stats["downloaded"] += 1
        except (subprocess.CalledProcessError, ValueError) as e:
            stats["failed"] += 1
            print(f"FAILED {row['ticker']} {row['fiscal_year']} {row['period']}: {e}")
    return stats
