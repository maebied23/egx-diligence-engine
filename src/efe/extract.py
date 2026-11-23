"""Extract primary statements of one document into raw_rows and facts. Free path: no model.

For each statement page from the page map: read the table, map labels, record every row in
raw_rows (mapped or not) and each mapped value in facts with page, line text and method.
If a text-layer page yields too few values (e.g. numbers drawn as graphics), it is re-read with OCR.
"""
import datetime as dt
import json
import re
import sqlite3

from efe import mapping, pagetext, tables

PRIMARY = ["income_statement", "oci", "balance_sheet", "cash_flow"]
MIN_VALUE_ROW_SHARE = 0.5


def detect_unit(texts: list[str]) -> tuple[str, str, str]:
    """(unit, currency, evidence) from header text. 'unknown' when not stated: never assumed."""
    joined = " | ".join(t for t in texts if t)
    low = joined.lower()
    if re.search(r"million|mn\b|بالمليون", low):
        unit = "millions"
    elif re.search(r"thousand|'000|000s|000'|بالألف|بالالف", low):
        unit = "thousands"
    elif re.search(r"\begp\b|l\.e|\busd\b|جنيه", low):
        unit = "units"  # a currency is stated with no scale word
    else:
        unit = "unknown"
    if re.search(r"\busd\b|us dollar|دولار", low):
        currency = "USD"
    elif re.search(r"\begp\b|l\.e|egyptian pound|جنيه", low):
        currency = "EGP"
    else:
        currency = "unknown"
    return unit, currency, joined[:300]


SCALE = {"units": 1, "thousands": 1_000, "millions": 1_000_000}


def column_period_end(statement: str, year: int, doc: sqlite3.Row) -> str:
    mmdd = doc["period_end"][5:]
    if year == doc["fiscal_year"]:
        return doc["period_end"]
    if statement == "balance_sheet" and doc["period"] != "FY":
        return f"{year}-12-31"  # interim balance sheets compare with the last year-end (verify for June filers)
    return f"{year}-{mmdd}"


def read_page(conn, doc_id: int, page_no: int) -> tuple[tables.Table | None, str, dict, tables.Table | None]:
    """Read a statement page; fall back to OCR when the text layer is incomplete.

    OCR'd pages are read a second time (other resolution and image clean-up). Returns
    (table, source, doubts, second reading) where doubts maps (row index, column) to the reason a
    value is uncertain."""
    words, source = pagetext.get_words(conn, doc_id, page_no)
    table = tables.read_table(words)
    # A statement page has more value lines than label-only lines (section headers, wrapped labels).
    weak = table is None or len(table.rows) < 0.5 * table.label_only_lines
    if weak and source == "text_pdf":
        if not pagetext.ocr_available():
            return None, "text_pdf_incomplete", {}, None
        words, source = pagetext.get_words(conn, doc_id, page_no, force_ocr=True)
        table = tables.read_table(words)
    doubts: dict[tuple[int, int], str] = {}
    other = None
    if table and source == "ocr":
        # Untreated image at another resolution: different processing from reading 1 (sharpened, 300 dpi),
        # so the two are less likely to share a mistake. Measured on 4 scanned pages: 21/302 values unconfirmed.
        second, _ = pagetext.ocr(pagetext.doc_path(conn, doc_id), page_no, dpi=pagetext.SECOND_DPI)
        other = tables.read_table(second)
        doubts = cross_check(table, other)
        fill_missing_labels(table, other, doubts)
    return table, source, doubts, other


def same_row(row: tables.Row, other: tables.Table | None) -> tables.Row | None:
    """The second reading's row at the same height carrying the same values."""
    if not other:
        return None
    values = {c.value for c in row.cells if c.value is not None}
    for s in other.rows:
        if s.label and abs(s.top - row.top) < 6 and values and values <= {c.value for c in s.cells}:
            return s
    return None


def fill_missing_labels(first: tables.Table, second: tables.Table | None, doubts: dict) -> None:
    """A row the first reading found without a label takes the label of the second reading's row at
    the same height with the same values. Marked as a doubt so a reviewer sees it."""
    for i, r in enumerate(first.rows):
        if r.label:
            continue
        s = same_row(r, second)
        if s:
            r.label = s.label
            for c in r.cells:
                key = (i, c.column)
                doubts[key] = "; ".join(filter(None, [doubts.get(key), "label taken from second OCR reading"]))


def cross_check(first: tables.Table, second: tables.Table | None) -> dict[tuple[int, int], str]:
    """Values from the first OCR reading that the second reading does not reproduce on the same line and
    column, plus values whose words the OCR engine itself was unsure of.

    One repair between readings: when the first reading lost the leading digit group ('379 466 462') and
    the second has the same digits with more in front ('5 379 466 462'), the second reading's figure is
    used. The value stays marked as a disagreement, so it remains low confidence for review."""
    doubts = {}
    for i, r in enumerate(first.rows):
        for c in r.cells:
            reasons = []
            alts = [] if second is None else [
                x for rr in second.rows if abs(rr.top - r.top) < 8 for x in rr.cells
                if x.column == c.column and x.value is not None]
            if second is None:
                reasons.append("second OCR reading found no table")
            elif c.value is not None and c.value not in {x.value for x in alts}:
                longer = [x for x in alts if dropped_leading_group(c.value, x.value)]
                if len(longer) == 1:
                    reasons.append(f"second OCR reading differs: first read '{c.raw}', which lost the leading "
                                   f"digits; second reading '{longer[0].raw}' used")
                    c.raw, c.value = longer[0].raw, longer[0].value
                else:
                    reasons.append(f"second OCR reading differs ({' / '.join(x.raw for x in alts) or 'no value'})")
            # Vision reports coarse confidences (30/50/100) and 50 is common on correct values,
            # so only the lowest level counts; disagreement between readings is the main signal.
            low = min((w.conf for w in r.words), default=100)
            if low < 50:
                reasons.append(f"OCR confidence {low:.0f}")
            if reasons:
                doubts[(i, c.column)] = "; ".join(reasons)
    return doubts


def dropped_leading_group(short: float, long: float) -> bool:
    a, b = str(int(abs(short))), str(int(abs(long)))
    return (short < 0) == (long < 0) and len(b) > len(a) >= 4 and b.endswith(a)


def extract_document(conn: sqlite3.Connection, doc_id: int, entered_by: str = "efe-rules-v1") -> dict:
    doc = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    conn.execute("DELETE FROM raw_rows WHERE document_id=?", (doc_id,))
    conn.execute("DELETE FROM facts WHERE document_id=? AND method != 'manual'", (doc_id,))
    stats = {"rows": 0, "mapped": 0, "facts": 0, "unmapped_labels": [], "pages": {}, "unit": None}
    for statement in PRIMARY:
        pages = [r["page_no"] for r in conn.execute(
            "SELECT page_no FROM pages WHERE document_id=? AND statement=? ORDER BY page_no", (doc_id, statement))]
        seen: set[tuple[str, int]] = set()
        for page_no in pages:
            table, source, doubts, other = read_page(conn, doc_id, page_no)
            binarised = None
            if not table:
                stats["pages"][page_no] = f"{statement}: no table read ({source})"
                continue
            stats["pages"][page_no] = f"{statement} ({source}, {len(table.rows)} rows, {len(doubts)} doubtful values)"
            head = pagetext.get_text(conn, doc_id, page_no).splitlines()[:12]
            unit, currency, evidence = detect_unit([table.unit_hint or ""] + head)
            stats["unit"] = stats["unit"] or (unit, currency)
            for row_idx, row in enumerate(table.rows):
                field, corrected = (mapping.map_label_ocr(statement, row.label, row.section) if source == "ocr"
                                    else (mapping.map_label(statement, row.label, row.section), None)) if row.label else (None, None)
                if not field and source == "ocr" and row.label:
                    # Another reading may have read the label better; the binarised one only when needed.
                    for name in ("second", "binarised"):
                        if name == "binarised":
                            if binarised is None:
                                binarised = tables.read_table(pagetext.ocr(
                                    pagetext.doc_path(conn, doc_id), page_no, dpi=pagetext.SECOND_DPI, prep="binarize")[0]) or False
                            alt = same_row(row, binarised or None)
                        else:
                            alt = same_row(row, other)
                        if alt:
                            field, corrected = mapping.map_label_ocr(statement, alt.label, row.section)
                            if field:
                                corrected = f"{alt.label} ({name} OCR reading)"
                                break
                if corrected:
                    for c in row.cells:
                        key = (row_idx, c.column)
                        doubts[key] = "; ".join(filter(None, [doubts.get(key), f"label OCR-corrected: {row.label!r} -> {corrected!r}"]))
                values = [{"column": column_period_end(statement, table.years[c.column], doc), "raw": c.raw, "value": c.value,
                           "doubt": doubts.get((row_idx, c.column))} for c in row.cells]
                conn.execute(
                    """INSERT INTO raw_rows (document_id, page_no, statement, line_no, label, note_ref, values_json,
                                             line_text, source, field, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (doc_id, page_no, statement, row.line_no, row.label, row.note_ref, json.dumps(values),
                     row.line_text, source, field, now))
                stats["rows"] += 1
                if not field:
                    if row.label:
                        stats["unmapped_labels"].append(f"{statement}: {row.label}")
                    continue
                stats["mapped"] += 1
                for v in values:
                    key = (field, v["column"])
                    if key in seen:  # e.g. 'Net profit for the year' printed twice; the duplicate check compares them
                        continue
                    seen.add(key)
                    norm = (mapping.normalise_sign(statement, field, v["value"]) * SCALE[unit]
                            if v["value"] is not None and unit in SCALE else None)
                    # Low only when the readings disagree or a label had to be rescued; Vision's coarse
                    # confidence score alone stays a note until the answer key shows whether it predicts errors.
                    strong = v["doubt"] and any(k in v["doubt"] for k in ("differs", "no table", "label"))
                    confidence = "high" if source == "text_pdf" else ("low" if strong else "medium")
                    note = f"label: {row.label}" + (f"; note {row.note_ref}" if row.note_ref else "") + \
                           (f"; DOUBT: {v['doubt']}" if v["doubt"] else "")
                    conn.execute(
                        """INSERT INTO facts (document_id, ticker, fiscal_year, period, period_end, column_period_end, scope,
                               field, value, value_normalised, currency, unit, source_page, source_text, source_language,
                               method, confidence, missing_reason, entered_by, created_at, notes)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (doc_id, doc["ticker"], doc["fiscal_year"], doc["period"], doc["period_end"], v["column"],
                         doc["scope"], field, v["value"], norm, currency, unit, page_no, row.line_text,
                         doc["language"] or "en", source, confidence,
                         None if v["value"] is not None else f"cell not parseable: {v['raw']!r}",
                         entered_by, now, note))
                    stats["facts"] += 1
    conn.commit()
    return stats
