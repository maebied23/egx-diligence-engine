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
from efe.numbers import parse_number

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
    table = tables.read_table(words, levelled=source == "ocr")
    # A statement page has more value lines than label-only lines (section headers, wrapped labels).
    weak = table is None or len(table.rows) < 0.5 * table.label_only_lines
    if weak and source == "text_pdf":
        if not pagetext.ocr_available():
            return None, "text_pdf_incomplete", {}, None
        words, source = pagetext.get_words(conn, doc_id, page_no, force_ocr=True)
        table = tables.read_table(words, levelled=True)
    doubts: dict[tuple[int, int], str] = {}
    other = None
    if source == "ocr":
        # Untreated image at another resolution: different processing from reading 1 (sharpened, 300 dpi),
        # so the two are less likely to share a mistake. Measured on 4 scanned pages: 21/302 values unconfirmed.
        path = pagetext.doc_path(conn, doc_id)
        fy = conn.execute("SELECT fiscal_year FROM documents WHERE id=?", (doc_id,)).fetchone()[0]
        other = tables.read_table(pagetext.ocr(path, page_no, dpi=pagetext.SECOND_DPI)[0], levelled=True)
        header_doubt = None
        if not years_ok(table, fy):
            # Reading 1 found no table, or misread the header years (small faint print, ARCC FY2023):
            # the second reading, then 600 dpi, may read them; the other readings stay for the cross-check.
            readings = [x for x in (table, other) if x]
            if not years_ok(other, fy):
                readings.append(tables.read_table(pagetext.ocr(path, page_no, dpi=pagetext.CELL_DPIS[0])[0],
                                                  levelled=True))
            readings = [x for x in readings if x]
            good = next((x for x in readings if years_ok(x, fy)), None)
            if good is None:
                # Two columns, one of them read as the expected year in its place: the header is the current
                # and prior year, misread. Taken by position, and every value on the page says so.
                fits = [x for x in readings if len(x.years) == 2 and (x.years[0] == fy or x.years[1] == fy - 1)]
                if fits:
                    good = max(fits, key=lambda x: len(x.rows))
                    header_doubt = (f"header years read as {good.years}; columns taken as {fy} and {fy - 1} "
                                    f"by position (unconfirmed)")
                    good.years = [fy, fy - 1]
            if good is not None:
                rest = [x for x in readings if x is not good]
                table, other = good, max(rest, key=lambda x: len(x.rows)) if rest else None
        if table:
            doubts = cross_check(table, other)
            fill_missing_labels(table, other, doubts)
            if pagetext.vision_available():
                reread_cells(path, page_no, table, other, doubts)
            if header_doubt:
                for i, r in enumerate(table.rows):
                    for c in r.cells:
                        doubts[(i, c.column)] = "; ".join(filter(None, [doubts.get((i, c.column)), header_doubt]))
    return table, source, doubts, other


def years_ok(table: tables.Table | None, fiscal_year: int) -> bool:
    """The header names the current and prior year, each once."""
    return bool(table) and len(set(table.years)) == len(table.years) and {fiscal_year, fiscal_year - 1} <= set(table.years)


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


CELL_TEXT = re.compile(r"[\s'‘’`\".,]*(\(?-?\s*\d{1,3}(?:[ ,]\d{3})*\s*\)?)[\s'‘’`\".,]*")
READING_DOUBTS = ("second OCR reading differs", "OCR confidence")


def parse_cell(text: str | None) -> tuple[str, float] | None:
    """A cell re-read counts only when it is a whole number and nothing else: stray marks around it are
    dropped, but a letter touching the digits (a misread '3') makes the reading unusable."""
    m = CELL_TEXT.fullmatch(text or "")
    if not m:
        return None
    value = parse_number(m.group(1))
    return (m.group(1), value) if value is not None else None


def page_box(table: tables.Table, box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """A box in the levelled table's coordinates, moved back to where it is printed on the page."""
    x0, top, x1, bottom = box
    shift = table.slope * (x0 + x1) / 2
    return x0, top + shift, x1, bottom + shift


def reread_cells(path, page_no: int, first: tables.Table, second: tables.Table | None, doubts: dict) -> None:
    """More readings for each value the two page readings disagree on (or Vision was unsure of): the cell
    alone, cropped wide enough to hold the whole printed figure, read at 600 and at 450 dpi.

    A page reading confirmed by a cell reading decides the value, and the doubt is rewritten to say which
    readings agreed (medium confidence). When only the two cell readings agree, their value is used but
    stays low confidence. Otherwise the doubt stays, with the cell readings added.
    Measured on ARCC FY2022 cash flow: the cell readings got every bold total the page readings missed."""
    for (i, col), reason in list(doubts.items()):
        parts = reason.split("; ")
        reading = [p for p in parts if p.startswith(READING_DOUBTS)]
        if not reading or i >= len(first.rows) or not first.centres:
            continue
        r = first.rows[i]
        cell = next((c for c in r.cells if c.column == col and c.value is not None), None)
        if cell is None:
            continue
        x, half = first.centres[col], first.half_gap
        near = [w for w in r.words if abs((w.x0 + w.x1) / 2 - x) < half] or r.words
        left = min(x - half, min(w.x0 for w in near)) - 8  # a misread can lose the figure's left end
        if col > 0:
            left = max(left, x - 1.25 * half)  # stay clear of the neighbouring column's figures
        box = page_box(first, (left, min(w.top for w in near) - 1, max(w.x1 for w in near) + 6, max(w.bottom for w in near) + 1))
        texts = [pagetext.read_cell(path, page_no, box, dpi) for dpi in pagetext.CELL_DPIS]
        cells = [parse_cell(x) for x in texts]
        votes = {c[1]: c[0] for c in cells if c}
        others = {} if second is None else {
            o.value: o.raw for rr in second.rows if abs(rr.top - r.top) < 8 for o in rr.cells
            if o.column == col and o.value is not None}
        # The second page reading finding nothing on this line points to a figure on the wrong line, which
        # a cell re-read cannot see (it confirms digits, not position): that doubt stays open.
        placed = [p for p in reading if p.endswith("(no value)")]
        reading = [p for p in reading if p not in placed]
        if not reading:
            continue
        rest = placed + [p for p in parts if p not in reading and p not in placed]
        before = ", ".join(p.replace("differs", "disagreed") for p in reading)  # "differs" marks an open doubt
        shown = " / ".join(repr(c[0] if c else x) for c, x in zip(cells, texts))
        if cell.value in votes:
            note = f"cell re-read confirms '{cell.raw}' (page readings: {before})"
        elif agreed := [v for v in votes if v in others]:
            note = (f"first reading '{cell.raw}' replaced: second page reading and cell re-read both read "
                    f"'{votes[agreed[0]]}' (page readings: {before})")
            cell.raw, cell.value = votes[agreed[0]], agreed[0]
        elif len(cells) == 2 and cells[0] and cells[1] and cells[0][1] == cells[1][1]:
            note = (f"page readings differ from the cell re-reads: first '{cell.raw}'; {'; '.join(reading)}; "
                    f"cell re-reads at {' and '.join(map(str, pagetext.CELL_DPIS))} dpi both read '{cells[0][0]}', used")
            cell.raw, cell.value = cells[0]
        else:
            note = f"{'; '.join(reading)}; cell re-reads differ ({shown or 'nothing read'})"
            cell = None
        if cell is not None:
            # the figure was read whole: other pieces the page reading split it into are fragments of it
            r.cells = [c for c in r.cells if c.column != col or c is cell]
        doubts[(i, col)] = "; ".join([note] + rest)
    if second is None or not first.centres:
        return
    for i, r in enumerate(first.rows):
        # A figure the first page reading missed but the second found: added when a cell reading agrees.
        if not r.label or not r.words:
            continue
        have = {c.column for c in r.cells}
        found = {o.column: o for rr in second.rows if abs(rr.top - r.top) < 8 for o in rr.cells
                 if o.value is not None and o.column not in have}
        # Where Vision struggled on the line (lowest confidence level), an empty column is read too.
        struggled = min(w.conf for w in r.words) < 50
        for col in range(len(first.centres)):
            if col in have or (col not in found and not struggled):
                continue
            x, half = first.centres[col], first.half_gap
            top, bottom = min(w.top for w in r.words) - 1, max(w.bottom for w in r.words) + 1
            box = page_box(first, (x - 1.25 * half, top, x + 0.9 * half, bottom))
            texts = [pagetext.read_cell(path, page_no, box, dpi) for dpi in pagetext.CELL_DPIS]
            cells = [parse_cell(x) for x in texts]
            o = found.get(col)
            if o and any(c and c[1] == o.value for c in cells):
                r.cells.append(tables.Cell(col, o.raw, o.value))
                doubts[(i, col)] = (f"missing from the first page reading; second page reading and cell re-read "
                                    f"both read '{o.raw}'")
            elif not o and cells[0] and cells[1:] and all(c and c[1] == cells[0][1] for c in cells[1:]):
                r.cells.append(tables.Cell(col, cells[0][0], cells[0][1]))
                doubts[(i, col)] = (f"missing from both page readings; cell re-reads at "
                                    f"{' and '.join(map(str, pagetext.CELL_DPIS))} dpi both read '{cells[0][0]}', "
                                    f"unconfirmed by a page reading")
            r.cells.sort(key=lambda c: c.column)


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
                                    pagetext.doc_path(conn, doc_id), page_no, dpi=pagetext.SECOND_DPI, prep="binarize")[0],
                                    levelled=True) or False
                            alt = same_row(row, binarised or None)
                        else:
                            alt = same_row(row, other)
                        if alt:
                            field, corrected = mapping.map_label_ocr(statement, alt.label, row.section)
                            if field:
                                corrected = f"{alt.label} ({name} OCR reading)"
                                break
                    if not field and table.centres:
                        # Last, the label alone at 600 dpi, at the height of the line's figures: a heading
                        # merged into the label ('Carrecre ia baiiies' for 'Current Liabilities' over
                        # 'Banks credit facilities', LCSW FY2022) is left out of the crop.
                        figs = [w for w in row.words if w.x0 >= table.centres[0] - 1.6 * table.half_gap] or row.words
                        words = [w for w in row.words if w.x1 < table.centres[0] - 1.6 * table.half_gap] or row.words
                        box = page_box(table, (min(w.x0 for w in words) - 4, min(w.top for w in figs) - 1,
                                               max(w.x1 for w in words) + 4, max(w.bottom for w in figs) + 1))
                        text = pagetext.read_cell(pagetext.doc_path(conn, doc_id), page_no, box, digits=False)
                        text = re.sub(r"\s*\(?\s*[\d][\d\-,. ]*\)\s*$", "", text or "").strip()
                        if text:
                            field, corrected = mapping.map_label_ocr(statement, text, row.section)
                            if field:
                                corrected = f"{text} (label re-read at 600 dpi)"
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
                    strong = v["doubt"] and any(k in v["doubt"] for k in ("differs", "no table", "label", "unconfirmed"))
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
