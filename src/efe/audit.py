"""Auditor and audit opinion from the auditor's report pages (tagged 'auditor_report' by the page map).

The opinion is the strongest modification found: disclaimer > adverse > qualified > unqualified.
Emphasis-of-matter paragraphs are noted but do not modify the opinion. The matched sentence and page
are stored as a fact (field 'audit_opinion', value NULL) so the call can be checked.
"""
import datetime as dt
import re
import sqlite3

from efe import pagetext

OPINIONS = [  # strongest first
    ("disclaimer", r"disclaimer of opinion|do not express an opinion"),
    ("adverse", r"adverse opinion"),
    ("qualified", r"(?<!un)qualified (audit )?opinion|except for the (possible )?effects?"),
    ("unqualified", r"in our opinion|unqualified opinion|presents? fairly"),
]
EMPHASIS = r"emphasis of (a )?matter"
AUDITORS = [
    ("KPMG Hazem Hassan", r"kpmg|hazem hassan"),
    ("Deloitte", r"deloitte|saleh,? barsoum|wafik,? ramy"),
    ("EY Allied for Accounting & Auditing", r"ernst|\bey\b|allied for accounting"),
    ("PwC Mansour & Co.", r"pricewaterhouse|\bpwc\b|mansour (& |and )?co"),
    ("Grant Thornton", r"grant thornton"),
    ("BDO Khaled & Co.", r"\bbdo\b"),
    ("Baker Tilly", r"baker tilly"),
    ("Mazars", r"mazars|forvis"),
    ("Crowe", r"\bcrowe\b"),
    ("RSM", r"\brsm\b"),
    ("Moore", r"\bmoore\b"),
    ("Kreston Egypt (Tamer Nabarawy & Co.)", r"kreston|nabarawy"),
    ("UHY", r"\buhy\b"),
    ("Nexia", r"\bnexia\b"),
]


def sentence(text: str, m: re.Match) -> str:
    start = max(text.rfind(".", 0, m.start()) + 1, m.start() - 200)
    end = text.find(".", m.end())
    return " ".join(text[start:end + 1 if end != -1 else m.end() + 200].split())[:400]


def read_opinion(conn: sqlite3.Connection, doc_id: int) -> dict:
    # Tagged report pages, plus every page before the first statement: the opinion paragraph often sits
    # alone on a page with no words the page map tags.
    first = conn.execute("SELECT MIN(page_no) FROM pages WHERE document_id=? AND statement IS NOT NULL", (doc_id,)).fetchone()[0]
    pages = sorted({r[0] for r in conn.execute(
        "SELECT page_no FROM page_tags WHERE document_id=? AND tag='auditor_report'", (doc_id,))}
        | set(range(1, first or 1)))
    found: dict[str, tuple[int, str]] = {}
    auditor = emphasis = None
    for p in pages:
        kind = conn.execute("SELECT kind FROM pages WHERE document_id=? AND page_no=?", (doc_id, p)).fetchone()[0]
        if kind == "scanned" and not pagetext.ocr_available():
            continue
        text = pagetext.get_text(conn, doc_id, p, fast=True)
        low = text.lower()
        for name, pat in OPINIONS:
            m = re.search(pat, low)
            if m and name not in found:
                found[name] = (p, sentence(text, m))
        if emphasis is None and (m := re.search(EMPHASIS, low)):
            emphasis = (p, sentence(text, m))
        for name, pat in AUDITORS:
            if auditor is None and re.search(pat, low):
                auditor = name
    opinion = next(((n, found[n]) for n, _ in OPINIONS if n in found), None)
    return {"opinion": opinion[0] if opinion else None, "page": opinion[1][0] if opinion else None,
            "text": opinion[1][1] if opinion else None, "auditor": auditor, "emphasis": emphasis, "pages": pages}


def run(conn: sqlite3.Connection, doc_id: int) -> dict:
    r = read_opinion(conn, doc_id)
    d = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    label = None
    if r["opinion"]:
        label = r["opinion"] + (" with emphasis of matter" if r["emphasis"] else "")
    conn.execute("UPDATE documents SET audit_opinion=?, auditor=? WHERE id=?", (label, r["auditor"], doc_id))
    conn.execute("DELETE FROM facts WHERE document_id=? AND field='audit_opinion'", (doc_id,))
    if r["opinion"]:
        kind = conn.execute("SELECT kind FROM pages WHERE document_id=? AND page_no=?", (doc_id, r["page"])).fetchone()[0]
        notes = f"opinion: {label}; auditor: {r['auditor'] or 'not identified'}"
        if r["emphasis"]:
            notes += f"; emphasis of matter p{r['emphasis'][0]}: {r['emphasis'][1]}"
        conn.execute(
            """INSERT INTO facts (document_id, ticker, fiscal_year, period, period_end, column_period_end, scope, field,
                   value, value_normalised, currency, unit, source_page, source_text, source_language, method,
                   confidence, entered_by, created_at, notes)
               VALUES (?,?,?,?,?,?,?, 'audit_opinion', NULL, NULL, '', '', ?, ?, 'en', ?, 'medium', 'efe.audit', ?, ?)""",
            (doc_id, d["ticker"], d["fiscal_year"], d["period"], d["period_end"], d["period_end"], d["scope"],
             r["page"], r["text"], "text_pdf" if kind == "text" else "ocr",
             dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), notes))
    conn.commit()
    return r
