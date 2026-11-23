"""Analysis layer on a synthetic company: definitions (docs/02), missing values, and the exposure rules."""
import json

import pytest

from efe import analysis, db, export, macro


def add_doc(conn, doc_id, fy):
    conn.execute("""INSERT INTO documents (id, ticker, fiscal_year, period, period_end, scope, framework, language,
                    doc_type, source, source_url, local_path) VALUES (?, 'TEST', ?, 'FY', ?, 'consolidated', 'EAS', 'en',
                    'financial_statements', 'test', ?, 'x.pdf')""", (doc_id, fy, f"{fy}-12-31", f"https://example/{fy}"))


def add_fact(conn, doc_id, fy, field, col, value, conf="high"):
    conn.execute("""INSERT INTO facts (document_id, ticker, fiscal_year, period, period_end, column_period_end, scope,
                    field, value, value_normalised, currency, unit, source_page, source_text, method, confidence, created_at)
                    VALUES (?, 'TEST', ?, 'FY', ?, ?, 'consolidated', ?, ?, ?, 'EGP', 'units', 1, 'line', 'text_pdf', ?, 'now')""",
                 (doc_id, fy, f"{fy}-12-31", f"{col}-12-31", field, value, value, conf))


def add_row(conn, doc_id, line_no, field):
    conn.execute("""INSERT INTO raw_rows (document_id, page_no, statement, line_no, label, values_json, line_text, source,
                    field, created_at) VALUES (?, 1, 'income_statement', ?, ?, '[]', '', 'text_pdf', ?, 'now')""",
                 (doc_id, line_no, field, field))


YEAR = {  # one filing per year; comparatives carry the prior year
    2023: dict(revenue=1000, cost_of_sales=-700, gross_profit=300, operating_profit=150, depreciation=50,
               amortisation=10, fx_gain_loss_pl=-40, finance_costs=-20, profit_before_tax=130, net_profit=100,
               short_term_borrowings=200, long_term_borrowings=100, cash=50, total_assets=2000, inventory=150,
               trade_receivables=120, trade_payables=90, cfo=150, capex=-60),
    2024: dict(revenue=1500, cost_of_sales=-1200, gross_profit=300, operating_profit=100, depreciation=60,
               amortisation=10, fx_gain_loss_pl=-90, finance_costs=-40, profit_before_tax=60, net_profit=40,
               short_term_borrowings=400, long_term_borrowings=100, cash=100, total_assets=2500, inventory=330,
               trade_receivables=150, trade_payables=100, cfo=50, capex=-80),
}


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.sqlite")
    db.init(c)
    for i, fy in enumerate(sorted(YEAR), 1):
        add_doc(c, i, fy)
        for col in (fy, fy - 1):
            for f, v in YEAR.get(col, {}).items():
                add_fact(c, i, fy, f, col, v)
        # FX printed above operating profit, so it sits inside EBITDA
        add_row(c, i, 1, "revenue")
        add_row(c, i, 2, "fx_gain_loss_pl")
        add_row(c, i, 3, "operating_profit")
    c.commit()
    return c


def metric(conn, y, name):
    return conn.execute("SELECT * FROM metrics WHERE ticker='TEST' AND fiscal_year=? AND metric=?", (y, name)).fetchone()


def test_standard_definitions(conn):
    analysis.run(conn, "TEST")
    assert metric(conn, 2024, "ebitda")["value"] == 100 + 60 + 10
    assert metric(conn, 2024, "ebitda_before_fx")["value"] == 170 + 90  # FX inside operating profit removed
    assert metric(conn, 2024, "net_debt")["value"] == 400 + 100 - 100
    assert metric(conn, 2024, "leverage")["value"] == pytest.approx(400 / 170)
    assert metric(conn, 2024, "interest_cover")["value"] == pytest.approx(170 / 40)
    assert metric(conn, 2024, "nwc")["value"] == 330 + 150 - 100
    assert metric(conn, 2024, "dio")["value"] == pytest.approx(330 / 1200 * 365)
    assert metric(conn, 2024, "fcf")["value"] == 50 - 80
    # cash conversion uses both NWC years from the FY2024 filing
    assert metric(conn, 2024, "cash_conversion")["value"] == pytest.approx((170 - 80 - (380 - 180)) / 170)
    assert metric(conn, 2024, "revenue_growth")["value"] == pytest.approx(0.5)
    m = metric(conn, 2024, "ebitda")
    assert m["formula"].startswith("EBIT 100") and json.loads(m["inputs"])  # formula and fact ids kept


def test_missing_is_missing_not_zero(conn):
    analysis.run(conn, "TEST")
    m = metric(conn, 2024, "fx_items_oci")
    assert m["value"] is None and "not extracted" in m["missing_reason"]
    lev = metric(conn, 2022, "leverage")  # FY2022 has no data at all
    assert lev is None or lev["value"] is None


def test_usd_and_real_views_use_named_sources(conn):
    analysis.run(conn, "TEST")
    r = macro.get("usd_egp_avg", 2024)
    m = metric(conn, 2024, "revenue_usd")
    assert m["value"] == pytest.approx(1500 / r.value)
    assert "World Bank" in m["formula"]


def test_exposure_signals_and_flags(conn):
    out = analysis.run(conn, "TEST")
    sig = {r["signal"]: r for r in conn.execute("SELECT * FROM signals WHERE ticker='TEST'")}
    # 2024 is a devaluation year: gross margin 30% -> 20% is -10pp, exposed
    assert sig["S1"]["value"] == pytest.approx(-10) and sig["S1"]["points"] == -1
    assert sig["S3"]["points"] is None and "not read" in sig["S3"]["missing_reason"]
    assert out["profile"] in ("exposed_importer", "exposed (channel not identified)", "insufficient_evidence", "mixed")
    findings = " ".join(r["finding"] for r in conn.execute("SELECT finding FROM flags WHERE ticker='TEST'"))
    assert "FX losses" in findings and "DIO rose" in findings


def test_export_writes_workbook(conn, tmp_path):
    analysis.run(conn, "TEST")
    path = export.build(conn, tmp_path / "book.xlsx")
    from openpyxl import load_workbook
    wb = load_workbook(path)
    assert {"Screen", "TEST", "Exposure", "Flags", "Sources"} <= set(wb.sheetnames)
