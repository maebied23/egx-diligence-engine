from pathlib import Path

import pytest

from efe import config, mapping, pagemap, tables
from efe.pagetext import Word


def line(top, *items):
    """items: (text, x0) pairs; each word gets a width of 6pt per character."""
    return [Word(t, x, x + 6 * len(t), top, top + 9) for t, x in items]


def statement_words():
    w = []
    w += line(100, ("Consolidated", 85), ("statement", 160), ("of", 215), ("Profit", 230), ("or", 270), ("loss", 285))
    w += line(160, ("Note", 338), ("2024", 403), ("2023", 505))
    w += line(175, ("EGP", 402), ("EGP", 504))
    w += line(200, ("Net", 90), ("sales", 112), ("(5)", 343),
              ("6", 387.6), ("644", 396.6), ("687", 417.3), ("614", 438.1),
              ("4", 484.8), ("842", 493.8), ("931", 514.6), ("210", 535.3))
    w += line(215, ("Cost", 90), ("of", 118), ("sales", 132), ("(6)", 343),
              (")", 384.2), ("4", 388.1), ("709", 397.2), ("357", 417.9), ("845(", 438.6),
              (")", 477.8), ("3", 481.7), ("316", 490.8), ("428", 511.6), ("140(", 532.2))
    w += line(230, ("Gross", 90), ("Profit", 125),
              ("1", 383.6), ("935", 393.1), ("329", 415.2), ("769", 437.3),
              ("1", 480.5), ("526", 490.0), ("503", 512.0), ("070", 534.1))
    w += line(245, ("Group", 90), ("share", 125), ("995", 420), ("630", 441), ("-", 515), ("-", 523))
    return w


def test_read_table_columns_notes_and_signs():
    t = tables.read_table(statement_words())
    assert t.years == [2024, 2023]
    rows = {r.label: r for r in t.rows}
    assert rows["Net sales"].note_ref == "(5)"
    assert [c.value for c in rows["Net sales"].cells] == [6644687614, 4842931210]
    assert [c.value for c in rows["Cost of sales"].cells] == [-4709357845, -3316428140]
    assert [c.value for c in rows["Gross Profit"].cells] == [1935329769, 1526503070]
    assert [c.column for c in rows["Group share"].cells] == [0, 1]
    assert rows["Group share"].cells[1].value == 0.0  # "- -" is nil, not missing
    assert "EGP" in t.unit_hint


def test_page_classification_uses_title_line_only():
    numbers = " ".join(["1 234"] * 20)
    oci = "Lecico\nConsolidated Statement of Comprehensive Income\nItems reclassified to profit or loss statement\n" + numbers
    assert pagemap.classify_page(oci)[0] == "oci"
    notes = "Notes to the consolidated financial statements\nStatement of financial position items\n" + numbers
    assert pagemap.classify_page(notes)[0] is None
    assert pagemap.is_notes_page(notes)
    contents = "Contents\nAuditor's Report F-01\nNotes To the Consolidated Financial Statements F-08"
    assert not pagemap.is_notes_page(contents)
    auditor = "Auditor's Report\nWe have audited the statements, and notes to the financial statements"
    assert not pagemap.is_notes_page(auditor)


@pytest.mark.parametrize("statement,label,section,field", [
    ("income_statement", "Net sales", None, "revenue"),
    ("income_statement", "Net profit or the year", None, "net_profit"),
    ("balance_sheet", "Loans", "Non-Current Liabilities", "long_term_borrowings"),
    ("balance_sheet", "Loans", "Current Liabilities", "current_portion_long_term_debt"),
    ("balance_sheet", "Trade and other receivables", None, "trade_and_other_receivables"),
    ("cash_flow", "Dividend paid to employee", None, "employee_profit_share_paid"),
    ("cash_flow", "Foreign currency translation differences", None, "fx_adjustment_cf"),
    ("income_statement", "Earnings per share", None, None),
])
def test_label_mapping(statement, label, section, field):
    assert mapping.map_label(statement, label, section) == field


LECICO_2024_EAS = config.RAW / "LCSW" / "2024_FY_consolidated_EAS_financial_statements_732636.pdf"


@pytest.mark.skipif(not LECICO_2024_EAS.exists(), reason="filing not downloaded (run efe ingest)")
def test_regression_lecico_fy2024_income_statement(tmp_path, monkeypatch):
    """Regression on a real filing: values as printed on PDF page 6 (checked by eye). Text layer only."""
    from efe import db, extract, pagetext
    monkeypatch.setattr(pagetext, "ocr_available", lambda lang="eng": False)  # keep the test fast
    conn = db.connect(tmp_path / "t.sqlite")
    db.init(conn)
    src = db.connect(config.DB_PATH)
    d = src.execute("SELECT * FROM documents WHERE local_path LIKE ?", ("%" + LECICO_2024_EAS.name,)).fetchone()
    if d is None:
        pytest.skip("document not registered")
    conn.execute("INSERT INTO documents SELECT * FROM documents WHERE 0")  # schema only
    cols = d.keys()
    conn.execute(f"INSERT INTO documents ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(d))
    for p in src.execute("SELECT * FROM pages WHERE document_id=?", (d["id"],)):
        conn.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,NULL)", tuple(p)[:6])
    conn.commit()
    pagemap.map_document(conn, d["id"], max_pages=10)
    extract.extract_document(conn, d["id"])
    got = {(f["field"], f["column_period_end"]): f["value"] for f in conn.execute("SELECT * FROM facts")}
    assert got[("revenue", "2024-12-31")] == 6644687614
    assert got[("cost_of_sales", "2024-12-31")] == -4709357845
    assert got[("net_profit", "2023-12-31")] == 510526796
    assert got[("cfo", "2024-12-31")] == 537075827


def test_deskew_keeps_right_hand_numbers_on_their_row():
    from efe.pagetext import deskew
    slope = 0.01  # page tilted: text drifts down 1pt per 100pt to the right
    words = []
    for row, label in enumerate(["Loans", "Lease liabilities"]):
        y = 100 + 20 * row
        words.append(Word(label, 50, 100, y + slope * 50, y + 9 + slope * 50))
        words.append(Word("123", 500, 520, y + slope * 500, y + 9 + slope * 500))
    fixed = deskew(words, [slope] * 6)
    assert abs(fixed[0].top - fixed[1].top) < 0.5 and abs(fixed[2].top - fixed[3].top) < 0.5
