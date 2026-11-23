"""Page triage: does each page have a usable text layer, or does it need OCR?

No model is involved. A page is 'text' if its text layer has at least MIN_TEXT_CHARS
characters, otherwise 'scanned'. Arabic share helps route Arabic pages to the right OCR language.
"""
import sqlite3
from pathlib import Path

import pypdfium2 as pdfium  # much faster than pdfplumber for reading the text layer

from efe import config


def arabic_share(text: str) -> float | None:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None
    arabic = sum(1 for c in letters if "؀" <= c <= "ۿ" or "ݐ" <= c <= "ݿ")
    return round(arabic / len(letters), 3)


def classify(text_chars: int) -> str:
    return "text" if text_chars >= config.MIN_TEXT_CHARS else "scanned"


def triage_document(conn: sqlite3.Connection, doc_id: int, path: Path) -> tuple[int, int]:
    """Returns (pages, scanned_pages)."""
    scanned = 0
    pdf = pdfium.PdfDocument(path)
    try:
        n = len(pdf)
        for i in range(1, n + 1):
            page = pdf[i - 1]
            textpage = page.get_textpage()
            text = textpage.get_text_range() or ""
            textpage.close()
            page.close()
            chars = len(text.strip())
            kind = classify(chars)
            scanned += kind == "scanned"
            conn.execute(
                """INSERT INTO pages (document_id, page_no, text_chars, has_text_layer, arabic_share, kind)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(document_id, page_no) DO UPDATE SET text_chars=excluded.text_chars,
                       has_text_layer=excluded.has_text_layer, arabic_share=excluded.arabic_share, kind=excluded.kind""",
                (doc_id, i, chars, int(chars > 0), arabic_share(text), kind),
            )
    finally:
        pdf.close()
    conn.execute("UPDATE documents SET page_count=? WHERE id=?", (n, doc_id))
    conn.commit()
    return n, scanned


def run(conn: sqlite3.Connection, redo: bool = False) -> list[tuple]:
    sql = "SELECT id, ticker, fiscal_year, period, scope, doc_type, local_path FROM documents WHERE local_path IS NOT NULL"
    if not redo:
        sql += " AND page_count IS NULL"
    results = []
    for d in conn.execute(sql).fetchall():
        n, scanned = triage_document(conn, d["id"], config.ROOT / d["local_path"])
        results.append((d["ticker"], d["fiscal_year"], d["period"], d["scope"], d["doc_type"], n, scanned))
    return results
