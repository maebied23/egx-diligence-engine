"""Figures from the notes to the accounts: the foreign-currency position and foreign-currency borrowings.

These feed exposure signals S3 (net foreign-currency position) and S4 (share of borrowings in foreign
currency). Companies print them in different shapes, so each shape has its own reader, and a page is
read by every reader that recognises it:

1. a sentence giving the totals ("foreign currency assets and liabilities ... amounted to the equivalent
   of EGP X and EGP Y respectively"), LCSW;
2. a table with one column per currency and a total column in EGP, with rows for total assets, total
   liabilities and bank facilities, LCSW;
3. a table of liabilities and assets by year, one row per currency, ARCC;
4. a table of borrowings by currency, ARCC.

Only the pages the page map tagged fx_risk, fx_position or borrowings are read. When none of them holds
a figure, the field is stored as missing with the pages that were read, which is itself a finding: some
companies (MCQE) describe their currency risk only in words.
"""
import datetime as dt
import re
import sqlite3

from efe import extract, pagetext, tables
from efe.numbers import looks_numeric, parse_number

FIELDS = ("fx_monetary_assets", "fx_monetary_liabilities", "fx_borrowings")
TAGS = ("fx_risk", "fx_position", "borrowings")
CURRENCY = r"usd|eur|euro|gbp|sterling|zar|rand|chf|jpy|cny|sar|aed|us ?dollars?|u\.s\.? ?dollars?"
CURRENCY_TOKEN = re.compile(rf"^({CURRENCY})$", re.I)
CURRENCY_ROW = re.compile(rf"^(currency[- ]?)?({CURRENCY})\b", re.I)
DATE = re.compile(r"(?:december|june|march|september)\s+\d{1,2},?\s*((?:19|20)\d{2})|\d{1,2}/\d{1,2}/((?:19|20)\d{2})", re.I)
SENTENCE = re.compile(  # 'as of December 31, 2024 ... of EGP X and EGP Y' or 'as of 31 December 2022 ... of X EGP and Y EGP'
    r"foreign currenc(?:y|ies) assets and liabilities as (?:of|at) (?P<date>[a-z]+ \d{1,2},? \d{4}|\d{1,2} [a-z]+,? \d{4})"
    r".{0,40}?amounted to (?:the )?equivalent of (?:EGP )?(?P<a>\d[\d ,.]*\d)(?: EGP)? and (?:EGP )?(?P<l>\d[\d ,.]*\d)",
    re.I | re.S)


def unit_of(text: str) -> tuple[str, int]:
    if re.search(r"EGP\s*('?000|thousands?)|in thousands|بالألف", text, re.I):
        return "thousands", 1_000
    if re.search(r"EGP\s*millions?|in millions", text, re.I):
        return "millions", 1_000_000
    return "units", 1


def figures(line: list[pagetext.Word], left: float) -> list[tuple[str, float, float, tuple]]:
    """(raw, value, x centre, box) for each number right of `left`."""
    words = [w for w in line if w.x0 >= left and looks_numeric(w.text)]
    out = []
    for g in tables.numeric_groups(words):
        raw = " ".join(w.text for w in g)
        v = parse_number(raw)
        if v is not None:
            box = (g[0].x0, min(w.top for w in g), g[-1].x1, max(w.bottom for w in g))
            out.append((raw, v, (g[0].x0 + g[-1].x1) / 2, box))
    return out


def part(raw: str, value: float, box: tuple | None = None) -> dict:
    return dict(raw=raw, value=abs(value), box=box)


def item(field: str, year: int, parts: list[dict], text: str) -> dict:
    return dict(field=field, year=year, parts=parts, text=text[:400])


def figures_in(text: str | None) -> set[float]:
    """Every whole figure in a cell reading, ignoring the marks around it. Used only to confirm a page
    reading; a figure that would replace one must be read cleanly (extract.parse_cell)."""
    return {float(m.replace(" ", "").replace(",", "")) for m in re.findall(r"(?<![\d.])\d{1,3}(?:[ ,]\d{3})+(?![\d.])", text or "")}


def confirm(path, page_no: int, p: dict) -> str | None:
    """Checks one figure read by OCR against the cell alone, at 600 and 450 dpi and two crop heights, as for
    the statements (extract.reread_cells). Returns the doubt, or None when a cell reading agrees. When two
    clean cell readings agree on another figure it replaces the page reading, and the doubt says so.
    Note tables are often printed faint or on shaded rows (ARCC), which is why there are four readings."""
    if p["box"] is None:
        return "figure taken from OCR text, not re-read"
    x0, top, x1, bottom = p["box"]
    texts = [pagetext.read_cell(path, page_no, (x0 - 8, top - pad, x1 + 6, bottom + pad), dpi)
             for pad in (1, 3) for dpi in pagetext.CELL_DPIS]
    if any(p["value"] in figures_in(x) for x in texts):
        return None
    clean = [c for c in map(extract.parse_cell, texts) if c]
    agreed = [c for c in clean if sum(abs(d[1]) == abs(c[1]) for d in clean) >= 2]
    if agreed:
        doubt = f"page OCR read '{p['raw']}'; cell re-reads read '{agreed[0][0]}', used (unconfirmed by the page reading)"
        p["raw"], p["value"] = agreed[0][0], abs(agreed[0][1])
        return doubt
    return f"OCR reading '{p['raw']}' not confirmed by the cell re-reads"


def text_of(line) -> str:
    return " ".join(w.text for w in line)


def read_sentence(text: str) -> list[dict]:
    out = []
    for m in SENTENCE.finditer(" ".join(text.split())):
        year = int(m.group("date")[-4:])
        for field, key in (("fx_monetary_assets", "a"), ("fx_monetary_liabilities", "l")):
            v = parse_number(m.group(key))
            if v is not None:
                out.append(item(field, year, [part(m.group(key), v)], m.group(0)))
    return out


def read_currency_columns(lines: list[list]) -> list[dict]:
    """Header row of currency codes plus a 'Total' column; the date line above names the year."""
    out = []
    for i, line in enumerate(lines):
        codes = [w for w in line if CURRENCY_TOKEN.match(w.text)]
        total = [w for w in line if w.text.lower() == "total"]
        if len(codes) < 2 or not total:
            continue
        year = None
        for prev in reversed(lines[max(0, i - 3):i]):
            if m := DATE.search(text_of(prev)):
                year = int(m.group(1) or m.group(2))
                break
        if year is None:
            continue
        centres = [(w.x0 + w.x1) / 2 for w in codes + total]
        left = min(w.x0 for w in codes) - 0.6 * (centres[1] - centres[0])
        total_x = centres[-1]
        for row in lines[i + 1:i + 16]:
            label = " ".join(w.text for w in row if w.x1 < left).lower()
            if DATE.search(text_of(row)) or label.startswith("item"):
                break
            field = ("fx_monetary_assets" if re.match(r"total assets", label) else
                     "fx_monetary_liabilities" if re.match(r"total liabilities", label) else
                     "fx_borrowings" if re.match(r"(bank )?(credit facilities|loans|borrowings|overdraft)", label) else None)
            if not field:
                continue
            nums = figures(row, left)
            near = [n for n in nums if abs(n[2] - total_x) < 0.5 * (centres[-1] - centres[-2])]
            if near:
                raw, v, _, box = max(near, key=lambda n: n[2])
                out.append(item(field, year, [part(raw, v, box)], text_of(row)))
    return out


def read_assets_liabilities(lines: list[list]) -> list[dict]:
    """A header with 'Liabilities' and 'Assets', a line of years under it, one row per currency."""
    out = []
    for i, line in enumerate(lines):
        heads = {w.text.lower().strip(":"): (w.x0 + w.x1) / 2 for w in line
                 if w.text.lower().strip(":") in ("liabilities", "assets")}
        if len(heads) < 2:
            continue
        for j in range(i + 1, min(i + 3, len(lines))):  # the years may sit under a line of 'December 31,'
            years = [(int(m.group(1)), w.x1 - (w.x1 - w.x0) * 2 / len(w.text)) for w in lines[j]
                     if (m := tables.YEAR.match(w.text))]
            if len(years) >= 2:
                break
        else:
            continue
        cols = [(y, x, min(heads, key=lambda h: abs(heads[h] - x))) for y, x in years]
        gap = min(b[1] - a[1] for a, b in zip(cols, cols[1:])) / 2
        left = cols[0][1] - 1.6 * gap
        sums: dict[tuple[str, int], list] = {}
        for row in lines[j + 1:j + 11]:
            label = " ".join(w.text for w in row if w.x1 < left)
            if not CURRENCY_ROW.match(label):
                if sums:
                    break
                continue
            for raw, v, x, box in figures(row, left):
                y, _, side = min(cols, key=lambda c: abs(c[1] - x))
                sums.setdefault((side, y), []).append((part(raw, v, box), text_of(row)))
        for (side, y), parts in sums.items():
            field = "fx_monetary_assets" if side == "assets" else "fx_monetary_liabilities"
            out.append(item(field, y, [p for p, _ in parts], " | ".join(t for _, t in parts)))
    return out


def read_borrowings_by_currency(lines: list[list]) -> list[dict]:
    """A 'Borrowings' heading, then a line of years and one row per currency (EGP rows left out)."""
    out = []
    for i, line in enumerate(lines):
        if not re.fullmatch(r"(borrowings|loans)( by currency)?:?", text_of(line).strip(), re.I):
            continue
        for j in range(i + 1, min(i + 3, len(lines))):
            years = [(int(m.group(1)), w.x1 - (w.x1 - w.x0) * 2 / len(w.text)) for w in lines[j]
                     if (m := tables.YEAR.match(w.text))]
            if len(years) >= 2:
                break
        else:
            continue
        gap = (years[1][1] - years[0][1]) / 2
        left = years[0][1] - 1.6 * gap
        rows = []
        for row in lines[j + 1:j + 8]:
            label = " ".join(w.text for w in row if w.x1 < left).strip()
            if re.match(r"total", label, re.I):
                break
            if not CURRENCY_ROW.match(label):
                break
            rows.append(row)
        for y, x in years:
            # a currency row with nothing in this year's column is printed blank or '--': nil
            parts = [part(n[0][0], n[0][1], n[0][3]) if (n := [f for f in figures(row, left) if abs(f[2] - x) < gap])
                     else part("--", 0.0) for row in rows]
            if parts:
                out.append(item("fx_borrowings", y, parts, " | ".join(text_of(r) for r in rows)))
    return out


def run(conn: sqlite3.Connection, doc_id: int) -> dict:
    doc = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    pages = sorted({r[0] for r in conn.execute(
        f"SELECT page_no FROM page_tags WHERE document_id=? AND tag IN ({','.join('?' * len(TAGS))})",
        (doc_id, *TAGS))})
    path = pagetext.doc_path(conn, doc_id)
    found: dict[tuple[str, int], tuple[dict, int, str, str]] = {}
    for p in pages:
        kind = conn.execute("SELECT kind FROM pages WHERE document_id=? AND page_no=?", (doc_id, p)).fetchone()[0]
        if kind == "scanned" and not pagetext.ocr_available():
            continue
        words, source = pagetext.get_words(conn, doc_id, p)
        lines = tables.group_lines(words)
        text = "\n".join(text_of(line) for line in lines)
        unit, _ = unit_of(text)
        for reader in (read_sentence, read_currency_columns, read_assets_liabilities, read_borrowings_by_currency):
            items = reader(text) if reader is read_sentence else reader(lines)
            for it in items:
                key = (it["field"], it["year"])
                if key in found:  # the first page and reader that gave it
                    continue
                doubts = [d for x in it["parts"] if x["raw"] != "--" and source != "text_pdf"
                          for d in [confirm(path, p, x)] if d]
                it["doubts"] = doubts
                found[key] = (it, p, source, unit)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    conn.execute(f"DELETE FROM facts WHERE document_id=? AND field IN ({','.join('?' * len(FIELDS))})", (doc_id, *FIELDS))
    scale = {"units": 1, "thousands": 1_000, "millions": 1_000_000}
    years = {y for _, y in found} | {doc["fiscal_year"]}
    for field in FIELDS:
        for y in sorted(years):
            col = extract.column_period_end("balance_sheet", y, doc)
            hit = found.get((field, y))
            if hit:
                it, p, source, unit = hit
                value = sum(x["value"] for x in it["parts"])
                raw = " + ".join(x["raw"] for x in it["parts"])
                confidence = "high" if source == "text_pdf" else ("low" if it["doubts"] else "medium")
                conn.execute(
                    """INSERT INTO facts (document_id, ticker, fiscal_year, period, period_end, column_period_end, scope,
                           field, value, value_normalised, currency, unit, source_page, source_text, source_language,
                           method, confidence, entered_by, created_at, notes)
                       VALUES (?,?,?,?,?,?,?,?,?,?, 'EGP', ?,?,?,?,?,?, 'efe.notes', ?, ?)""",
                    (doc_id, doc["ticker"], doc["fiscal_year"], doc["period"], doc["period_end"], col, doc["scope"],
                     field, value, value * scale[unit], unit, p, it["text"], doc["language"] or "en",
                     source, confidence, now,
                     f"from the notes: {raw} (EGP equivalent, {unit})"
                     + (f"; DOUBT: {'; '.join(it['doubts'])}" if it["doubts"] else "")))
            elif y == doc["fiscal_year"]:
                conn.execute(
                    """INSERT INTO facts (document_id, ticker, fiscal_year, period, period_end, column_period_end, scope,
                           field, value, value_normalised, currency, unit, source_page, source_text, method, confidence,
                           missing_reason, entered_by, created_at)
                       VALUES (?,?,?,?,?,?,?,?, NULL, NULL, 'EGP', '', NULL, NULL, 'rules', 'low', ?, 'efe.notes', ?)""",
                    (doc_id, doc["ticker"], doc["fiscal_year"], doc["period"], doc["period_end"], col, doc["scope"],
                     field, f"no figure found in the notes pages tagged {'/'.join(TAGS)} "
                            f"(pages {', '.join(map(str, pages)) or 'none'})", now))
    conn.commit()
    return {f"{k[0]} {k[1]}": f"{sum(x['value'] for x in v[0]['parts']):,.0f} (p{v[1]})"
                                + (" low" if v[0]["doubts"] else "") for k, v in sorted(found.items())}
