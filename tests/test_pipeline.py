import csv

from efe import config, db, ingest, triage


def test_schema_creates_tables(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    db.init(conn)
    db.init(conn)  # idempotent
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"documents", "pages", "facts", "checks"} <= names


def test_classify_threshold():
    assert triage.classify(0) == "scanned"
    assert triage.classify(config.MIN_TEXT_CHARS - 1) == "scanned"
    assert triage.classify(config.MIN_TEXT_CHARS) == "text"


def test_arabic_share():
    assert triage.arabic_share("") is None
    assert triage.arabic_share("12,345 (678)") is None
    assert triage.arabic_share("Revenue") == 0.0
    assert triage.arabic_share("صافي المبيعات") == 1.0


def test_local_names_unique_for_register():
    with open(config.FILINGS_CSV, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["url"]]
    names = [(r["ticker"], ingest.local_name(r)) for r in rows]
    assert len(names) == len(set(names))
    assert all(n.endswith(".pdf") and "/" not in n for _, n in names)
