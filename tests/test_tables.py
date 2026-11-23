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


def test_level_puts_figures_back_on_their_labels():
    """A 2% tilt that the whole-line deskew missed: each row's figures print about half a line below its
    label (LCSW FY2022 balance sheet). Measured from neighbouring columns, the tilt is removed."""
    slope, w = 0.02, []
    w += line(100, ("Note", 338), ("2022", 403), ("2021", 485))
    for k, (label, a, b) in enumerate([("Loans", "8 240 932", "24 597 468"), ("Provisions", "21 349 926", "8 371 135"),
                                       ("Deferred", "110 881 391", "13 357 906"), ("Accrued", "41 393 653", "39 950 980"),
                                       ("Trade", "933 175 828", "673 725 980"), ("Other", "48 921 233", "28 057 917")]):
        top = 130 + 11 * k
        w += line(top, (label, 85))
        for text, xx in ((a, 380), (b, 470)):
            for part in text.split():
                w += line(top + slope * xx, (part, xx))
                xx += 6 * len(part) + 3
    assert tables.read_table(w) is not None
    t = tables.read_table(w, levelled=True)
    assert t.slope == pytest.approx(slope, abs=0.002)
    got = {r.label: [c.value for c in r.cells] for r in t.rows}
    assert got["Provisions"] == [21349926, 8371135] and got["Other"] == [48921233, 28057917]


def test_level_leaves_a_straight_page_alone():
    t = tables.read_table(statement_words(), levelled=True)
    assert t.slope == 0.0


@pytest.mark.parametrize("text, expected", [
    ("(213 680 194)", -213680194), ("17 897 417)", -17897417), ("'115 782 865)", -115782865),
    ("61 217 529", 61217529), ("З 242 661", None), ("P15 940 576", None), ("---", None), (None, None)])
def test_cell_reading_must_be_a_whole_number(text, expected):
    from efe.extract import parse_cell
    got = parse_cell(text)
    assert (got[1] if got else None) == expected


def test_subtotal_line_closes_its_section():
    """'Non-Current Liabilities' with figures is a subtotal: the 'Loans' after it are current, even when
    the heading 'Current Liabilities' was not read (LCSW FY2022)."""
    w = line(100, ("Note", 338), ("2022", 403), ("2021", 485))
    w += line(120, ("Total", 85), ("Equity", 115)) + line(120, ("1900", 400)) + line(120, ("1543", 480))
    w += line(132, ("Loans", 85)) + line(132, ("8240", 400)) + line(132, ("2459", 480))
    w += line(144, ("Non-Current", 85), ("Liabilities", 155)) + line(144, ("4776", 400)) + line(144, ("2797", 480))
    w += line(156, ("Loans", 85)) + line(156, ("3033", 400)) + line(156, ("1458", 480))
    rows = tables.read_table(w).rows
    loans = [r for r in rows if r.label == "Loans"]
    assert mapping.map_label("balance_sheet", "Loans", loans[0].section) == "long_term_borrowings"
    assert mapping.map_label("balance_sheet", "Loans", loans[1].section) == "current_portion_long_term_debt"
