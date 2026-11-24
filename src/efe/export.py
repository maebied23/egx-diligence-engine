"""Excel databook: a screening sheet, one sheet per company, exposure signals, red flags and sources.

Every number carries a cell comment with its formula or source page and text; low-confidence cells are
shaded and missing values say why. Money is shown in EGP millions (USD millions for USD rows).
"""
import csv
import datetime as dt
import json
import sqlite3
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from efe import analysis, config

OUT = config.ROOT / "outputs" / "efe_databook.xlsx"
LOW = PatternFill("solid", fgColor="FCE4D6")
MISSING = PatternFill("solid", fgColor="EDEDED")
HEAD = PatternFill("solid", fgColor="1F3864")
SECTION = PatternFill("solid", fgColor="D9E1F2")
WHITE = Font(color="FFFFFF", bold=True)
BOLD = Font(bold=True)

# (metric, label) grouped as an associate reads a company: P&L, cash, balance sheet, overlay.
LAYOUT = [
    ("Income statement (EGP m)", [
        ("revenue", "Revenue"), ("revenue_growth", "  growth (EGP)"), ("gross_profit", "Gross profit"),
        ("gross_margin", "  gross margin"), ("ebitda", "EBITDA"), ("ebitda_margin", "  EBITDA margin"),
        ("d_and_a", "  of which D&A"), ("net_profit", "Net profit"), ("net_margin", "  net margin")]),
    ("Cash flow (EGP m)", [
        ("cfo", "Operating cash flow"), ("capex", "Capex"), ("fcf", "Free cash flow (CFO + capex)"),
        ("cfo_to_ebitda", "CFO / EBITDA"), ("change_in_nwc", "Change in trade NWC"), ("cash_conversion", "Cash conversion")]),
    ("Balance sheet and debt (EGP m)", [
        ("gross_debt", "Gross debt (borrowings + leases)"), ("cash", "Cash"), ("net_debt", "Net debt"),
        ("leverage", "Net debt / EBITDA"), ("interest_cover", "EBITDA / finance costs"),
        ("debt_like_candidates", "Debt-like candidates (not netted)")]),
    ("Working capital (period end)", [
        ("inventory", "Inventory (EGP m)"), ("trade_receivables_used", "Trade receivables (EGP m)"),
        ("trade_payables_used", "Trade payables (EGP m)"), ("nwc", "Trade NWC (EGP m)"),
        ("dso", "DSO (days)"), ("dio", "DIO (days)"), ("dpo", "DPO (days)")]),
    ("Egypt overlay: FX and real terms", [
        ("fx_gain_loss_pl", "FX result in P&L (EGP m)"), ("fx_items_oci", "FX items in OCI (EGP m)"),
        ("ebitda_before_fx", "EBITDA before FX (EGP m)"), ("ebitda_before_fx_margin", "  margin"),
        ("fx_pl_to_ebitda_before_fx", "FX result / EBITDA before FX"), ("usd_egp_avg", "USD/EGP average rate"),
        ("revenue_usd", "Revenue (USD m)"), ("ebitda_usd", "EBITDA (USD m)"),
        ("revenue_growth_usd", "Revenue growth (USD)"), ("real_revenue_growth", "Real revenue growth (CPI-deflated)")]),
]
SCREEN = [  # (header, metric, kind)
    ("Revenue EGP m", "revenue", "m"), ("Revenue USD m", "revenue_usd", "m"),
    ("Growth EGP", "revenue_growth", "%"), ("Growth USD", "revenue_growth_usd", "%"),
    ("Real growth", "real_revenue_growth", "%"), ("Gross margin", "gross_margin", "%"),
    ("EBITDA margin", "ebitda_margin", "%"), ("EBITDA margin before FX", "ebitda_before_fx_margin", "%"),
    ("FX / EBITDA before FX", "fx_pl_to_ebitda_before_fx", "%"), ("Net debt / EBITDA", "leverage", "x"),
    ("EBITDA / finance costs", "interest_cover", "x"), ("CFO / EBITDA", "cfo_to_ebitda", "%"),
    ("Cash conversion", "cash_conversion", "%"),
]


def kind_of(unit: str) -> str:
    return {"EGP": "m", "USD": "m", "%": "%", "x": "x", "days": "d"}.get(unit, "n")


def put(ws, row, col, m: sqlite3.Row | None, kind: str | None = None):
    c = ws.cell(row=row, column=col)
    if m is None:
        return c
    kind = kind or kind_of(m["unit"])
    if m["value"] is None:
        c.value, c.fill = "n/a", MISSING
        c.alignment = Alignment(horizontal="right")
        c.comment = Comment(f"Missing: {m['missing_reason']}", "efe")
        return c
    v = m["value"]
    c.value = v / 1e6 if kind == "m" else v
    c.number_format = {"m": '#,##0.0;(#,##0.0)', "%": '0.0%;(0.0%)', "x": '0.0"x"', "d": '0'}.get(kind, '#,##0.00')
    text = f"{m['formula']}\nconfidence: {m['confidence']}"
    if m["notes"]:
        text += f"\n{m['notes']}"
    c.comment = Comment(text[:2000], "efe")
    c.comment.width, c.comment.height = 420, 160
    if m["confidence"] == "low":
        c.fill = LOW
    return c


def header(ws, row, values, widths=None):
    for i, v in enumerate(values, 1):
        c = ws.cell(row=row, column=i, value=v)
        c.fill, c.font = HEAD, WHITE
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def companies() -> dict[str, dict]:
    with open(config.SOURCES / "companies.csv", newline="", encoding="utf-8") as fh:
        return {r["ticker"]: r for r in csv.DictReader(fh)}


def build(conn: sqlite3.Connection, path: Path = OUT) -> Path:
    tickers = [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM metrics ORDER BY ticker")]
    names = companies()
    metric = {(r["ticker"], r["fiscal_year"], r["metric"]): r for r in conn.execute("SELECT * FROM metrics")}
    years = {t: sorted({y for (tt, y, _) in metric if tt == t}) for t in tickers}
    sig = {(r["ticker"], r["signal"]): r for r in conn.execute("SELECT * FROM signals")}
    wb = Workbook()

    # ---- Read me
    ws = wb.active
    ws.title = "Read me"
    lines = [
        ("EGX Diligence Engine: databook", BOLD),
        (f"Built {dt.date.today().isoformat()} from the companies' published consolidated annual financial statements.", None),
        ("", None),
        ("How to read it", BOLD),
        ("Hover over any number: the comment shows the formula with the figures used, or the page and printed text it came from.", None),
        ("Orange cells: at least one input is low confidence (OCR disagreement, or on a failed arithmetic check). Check before quoting.", None),
        ("Grey 'n/a': not calculated; the comment says why. Nothing is estimated or filled in.", None),
        ("", None),
        ("Definitions (docs/02, standard PE)", BOLD),
        ("EBITDA = operating profit + depreciation + amortisation (D&A from the cash flow). Where no operating profit is printed, "
         "it is built from profit before tax by removing finance items; this is flagged.", None),
        ("Net debt = borrowings + lease liabilities - cash. Debt-like items (dividends and taxes payable, notes payable, provisions) "
         "are listed separately and never netted in.", None),
        ("Trade NWC = inventory + trade receivables - trade payables, period end. DSO/DIO/DPO on period-end balances.", None),
        ("Cash conversion = (EBITDA + capex - change in trade NWC) / EBITDA; both NWC years from the same filing.", None),
        ("", None),
        ("Egypt overlay (docs/03, docs/04)", BOLD),
        ("EBITDA before FX removes FX differences where the company prints them inside operating profit, so years and companies compare.", None),
        ("USD figures use the World Bank annual average official rate; real growth deflates by Egypt CPI (World Bank). Source and date in each comment.", None),
        ("Exposure profile: 7 signals from docs/04. Signals S3-S5 need note tables the engine does not read yet; "
         "thresholds are provisional and not yet calibrated. Evidence, not a recommendation.", None),
        ("", None),
        ("Limits", BOLD),
        ("Extraction accuracy is checked by arithmetic ties and a second OCR reading, and is being measured against an "
         "independent reading of four filings (tests/). Scanned filings carry more risk than digital ones.", None),
    ]
    for i, (text, font) in enumerate(lines, 1):
        c = ws.cell(row=i, column=1, value=text)
        if font:
            c.font = font
    ws.column_dimensions["A"].width = 140

    # ---- Screen: latest year with EBITDA per company
    ws = wb.create_sheet("Screen")
    heads = ["Company", "Ticker", "Subsector", "Latest FY", "Framework"] + [h for h, _, _ in SCREEN] + \
            ["Exposure profile", "Score (-100 exposed, +100 protected)", "Signals available", "High-severity flags"]
    header(ws, 1, heads, [30, 8, 18, 9, 10] + [12] * len(SCREEN) + [26, 14, 10, 10])
    ws.row_dimensions[1].height = 45
    for r, t in enumerate(tickers, 2):
        ys = [y for y in years[t] if metric.get((t, y, "ebitda")) and metric[(t, y, "ebitda")]["value"] is not None]
        y = ys[-1] if ys else (years[t][-1] if years[t] else None)
        fw = conn.execute("SELECT framework FROM documents WHERE ticker=? AND fiscal_year=? AND scope='consolidated' "
                          "AND doc_type='financial_statements' AND id IN (SELECT document_id FROM facts)", (t, y)).fetchone()
        info = names.get(t, {})
        for c, v in enumerate([info.get("company", t), t, info.get("subsector", ""), f"FY{y}", fw[0] if fw else ""], 1):
            ws.cell(row=r, column=c, value=v)
        for c, (_, key, kind) in enumerate(SCREEN, 6):
            put(ws, r, c, metric.get((t, y, key)), kind)
        p = sig.get((t, "profile"))
        col = 6 + len(SCREEN)
        if p:
            ws.cell(row=r, column=col, value=p["rule"].split(" | ")[0]).comment = Comment(
                f"{p['rule']}\nsignals: {p['evidence']}\nmissing: {p['missing_reason'] or 'none'}"[:2000], "efe")
            ws.cell(row=r, column=col + 1, value=None if p["value"] is None else round(p["value"]))
            n = sum(1 for (tt, s), x in sig.items() if tt == t and s != "profile" and x["points"] is not None)
            ws.cell(row=r, column=col + 2, value=f"{n} of 7")
        ws.cell(row=r, column=col + 3, value=conn.execute(
            "SELECT COUNT(*) FROM flags WHERE ticker=? AND severity='high'", (t,)).fetchone()[0])
    ws.freeze_panes = "C2"

    # ---- One sheet per company
    for t in tickers:
        ws = wb.create_sheet(t)
        ys = years[t]
        ws.cell(row=1, column=1, value=f"{names.get(t, {}).get('company', t)} ({t}): consolidated, "
                                       f"fiscal years ending {conn.execute('SELECT substr(period_end,6) FROM documents WHERE ticker=? LIMIT 1', (t,)).fetchone()[0]}").font = Font(bold=True, size=13)
        header(ws, 2, ["Metric"] + [f"FY{y}" for y in ys], [44] + [13] * len(ys))
        r = 3
        for title, rows in LAYOUT:
            c = ws.cell(row=r, column=1, value=title)
            c.font, c.fill = BOLD, SECTION
            for i in range(2, len(ys) + 2):
                ws.cell(row=r, column=i).fill = SECTION
            r += 1
            for key, label in rows:
                ws.cell(row=r, column=1, value=label)
                for i, y in enumerate(ys, 2):
                    put(ws, r, i, metric.get((t, y, key)))
                r += 1
            r += 1
        # Reported facts behind the metrics, with page references
        c = ws.cell(row=r, column=1, value="Reported figures as extracted (EGP m; comment = page and printed line)")
        c.font, c.fill = BOLD, SECTION
        r += 1
        doc_ids = {d["id"] for d in analysis.Book(conn, t).docs.values()}  # the filings the metrics used
        latest = {}
        for f in conn.execute("SELECT * FROM facts WHERE ticker=? AND value_normalised IS NOT NULL ORDER BY id", (t,)):
            if f["document_id"] in doc_ids and f["column_period_end"][:4] == str(f["fiscal_year"]):
                latest[(f["field"], f["fiscal_year"])] = f
        for fld in sorted({k[0] for k in latest}):
            ws.cell(row=r, column=1, value=fld)
            for i, y in enumerate(ys, 2):
                f = latest.get((fld, y))
                if f is None:
                    continue
                c = ws.cell(row=r, column=i, value=f["value_normalised"] / 1e6)
                c.number_format = '#,##0.0;(#,##0.0)'
                c.comment = Comment(f"p{f['source_page']} ({f['method']}, {f['confidence']}): {f['source_text']}"
                                    + (f"\n{f['notes']}" if f["notes"] else ""), "efe")
                c.comment.width, c.comment.height = 420, 120
                if f["confidence"] == "low":
                    c.fill = LOW
            r += 1
        ws.freeze_panes = "B3"

    # ---- Exposure
    ws = wb.create_sheet("Exposure")
    header(ws, 1, ["Ticker", "Signal", "Value", "Points", "Rule", "Evidence", "Confidence", "Why missing / caveat"],
           [8, 8, 10, 8, 70, 80, 11, 60])
    r = 2
    for t in tickers:
        for code in ["profile", "S1", "S2", "S3", "S4", "S5", "S6", "S7"]:
            s = sig.get((t, code))
            if not s:
                continue
            vals = [t, code, None if s["value"] is None else round(s["value"], 1), s["points"], s["rule"],
                    s["evidence"], s["confidence"], s["missing_reason"]]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=c, value=v)
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                if code == "profile":
                    cell.font = BOLD
            r += 1
        r += 1
    ws.freeze_panes = "C2"

    # ---- Flags
    ws = wb.create_sheet("Flags")
    header(ws, 1, ["Ticker", "FY", "Severity", "Category", "Finding", "Question for management / auditor", "Evidence"],
           [8, 7, 9, 16, 70, 60, 50])
    order = "CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"
    for r, f in enumerate(conn.execute(f"SELECT * FROM flags ORDER BY ticker, {order}, fiscal_year"), 2):
        for c, v in enumerate([f["ticker"], f["fiscal_year"], f["severity"], f["category"], f["finding"], f["question"], f["evidence"]], 1):
            ws.cell(row=r, column=c, value=v).alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"

    # ---- Sources
    ws = wb.create_sheet("Sources")
    header(ws, 1, ["Ticker", "FY", "Scope", "Framework", "Auditor", "Audit opinion", "Pages", "Source URL"],
           [8, 7, 13, 10, 30, 32, 7, 100])
    docs = conn.execute("""SELECT * FROM documents WHERE id IN (SELECT DISTINCT document_id FROM facts)
                           ORDER BY ticker, fiscal_year""").fetchall()
    for r, d in enumerate(docs, 2):
        for c, v in enumerate([d["ticker"], d["fiscal_year"], d["scope"], d["framework"], d["auditor"],
                               d["audit_opinion"], d["page_count"], d["source_url"]], 1):
            ws.cell(row=r, column=c, value=v)
    r = len(docs) + 3
    ws.cell(row=r, column=1, value="Macro data: World Bank WDI (PA.NUS.FCRF official USD/EGP period average; FP.CPI.TOTL), "
                                   "file data/macro/egypt_macro.csv with retrieval date.")

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
