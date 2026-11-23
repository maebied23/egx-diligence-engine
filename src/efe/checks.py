"""Arithmetic checks on one document's facts. Failures are flagged for review, never fixed.

Identity checks compare standard fields (e.g. gross profit = revenue + cost of sales, with costs
negative). Segment checks re-add the printed rows between two subtotals, so any misread line in
between is caught even if it has no standard field. Tolerance is rounding: one unit of the stated
scale per term.
"""
import datetime as dt
import json
import sqlite3

# (name, result field, [terms]) using value_normalised (costs negative)
IDENTITIES = [
    ("gross_profit = revenue + cost_of_sales", "gross_profit", ["revenue", "cost_of_sales"]),
    ("net_profit = profit_before_tax + income_tax (+ deferred tax)", "net_profit", ["profit_before_tax", "income_tax", "?deferred_tax_pl"]),
    ("net_profit = parent + non_controlling", "net_profit", ["net_profit_parent", "non_controlling_interest"]),
    ("total_assets = current + non_current", "total_assets", ["total_current_assets", "total_non_current_assets"]),
    ("total_liabilities = current + non_current", "total_liabilities", ["total_current_liabilities", "total_non_current_liabilities"]),
    ("total_equity_and_liabilities = equity + liabilities", "total_equity_and_liabilities", ["total_equity", "total_liabilities"]),
    ("total_assets = total_equity_and_liabilities", "total_assets", ["total_equity_and_liabilities"]),
    ("net_change_in_cash = cfo + cfi + cff", "net_change_in_cash", ["cfo", "cfi", "cff"]),
    ("cash_end = cash_begin + net_change_in_cash (+ fx effect)", "cash_end", ["cash_begin", "net_change_in_cash", "?fx_effect_on_cash"]),
    ("profit_before_tax (cash flow) = profit_before_tax (income statement)", "profit_before_tax_cf", ["profit_before_tax"]),
]
# Cross-statement ties that legitimately differ when overdrafts are part of cash in the cash flow.
WARN_ONLY = {"cash (balance sheet) = cash_end (cash flow)": ("cash", ["cash_end"])}

# Printed-row segments: rows strictly between start and end, plus start, must equal end (signs as printed).
SEGMENTS = [
    ("income_statement", "gross_profit", "operating_profit"),
    ("income_statement", "operating_profit", "profit_before_tax"),
    ("income_statement", "profit_before_tax", "net_profit"),
]
SECTION_TOTALS = [  # balance sheet: rows inside a section add to the section total
    ("balance_sheet", "total_non_current_assets"),
    ("balance_sheet", "total_current_assets"),
    ("balance_sheet", "total_non_current_liabilities"),
    ("balance_sheet", "total_current_liabilities"),
]
CASH_FLOW_SECTIONS = [("cash_flow", "cfi"), ("cash_flow", "cff")]


def _record(conn, doc_id, name, status, detail, fact_ids, now):
    conn.execute("INSERT INTO checks (document_id, check_name, status, detail, fact_ids, created_at) VALUES (?,?,?,?,?,?)",
                 (doc_id, name, status, detail, ",".join(map(str, fact_ids)), now))


def _close(a: float, b: float, terms: int, scale: float) -> bool:
    return abs(a - b) <= terms * scale + 1e-6


def run(conn: sqlite3.Connection, doc_id: int) -> dict:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    conn.execute("DELETE FROM checks WHERE document_id=?", (doc_id,))
    facts = conn.execute("SELECT * FROM facts WHERE document_id=? AND supersedes_id IS NULL OR "
                         "(document_id=? AND id IN (SELECT MAX(id) FROM facts WHERE document_id=? GROUP BY field, column_period_end))",
                         (doc_id, doc_id, doc_id)).fetchall()
    # latest row per (field, column) wins, so reviewer corrections take effect
    by_key: dict[tuple[str, str], sqlite3.Row] = {}
    for f in facts:
        k = (f["field"], f["column_period_end"])
        if k not in by_key or f["id"] > by_key[k]["id"]:
            by_key[k] = f
    columns = sorted({k[1] for k in by_key})
    unit = next((f["unit"] for f in by_key.values()), "units")
    scale = {"units": 1, "thousands": 1_000, "millions": 1_000_000}.get(unit, 1)
    out = {"passed": 0, "failed": 0, "not_checked": 0, "warning": 0}

    def get(field, col):
        f = by_key.get((field, col))
        return f if f is not None and f["value_normalised"] is not None else None

    for col in columns:
        for name, result, all_terms in IDENTITIES:
            # '?term' is optional: used when the company prints it, otherwise left out
            terms = [t.lstrip("?") for t in all_terms if not t.startswith("?") or get(t.lstrip("?"), col) is not None]
            r, ts = get(result, col), [get(t, col) for t in terms]
            if r is None and all(t is None for t in ts):
                continue  # statement not in this document
            if r is None or any(t is None for t in ts):
                missing = [n for n, v in zip([result] + terms, [r] + ts) if v is None]
                _record(conn, doc_id, f"{name} [{col}]", "not_checked", f"missing: {', '.join(missing)}", [], now)
                out["not_checked"] += 1
                continue
            total = sum(t["value_normalised"] for t in ts)
            ok = _close(r["value_normalised"], total, len(terms), scale)
            _record(conn, doc_id, f"{name} [{col}]", "passed" if ok else "failed",
                    f"{result}={r['value_normalised']:,.0f} vs sum={total:,.0f} (diff {r['value_normalised'] - total:,.0f})",
                    [r["id"]] + [t["id"] for t in ts], now)
            out["passed" if ok else "failed"] += 1
        for name, (a, bs) in WARN_ONLY.items():
            fa, fb = get(a, col), get(bs[0], col)
            if fa is not None and fb is not None and not _close(fa["value_normalised"], fb["value_normalised"], 1, scale):
                _record(conn, doc_id, f"{name} [{col}]", "warning",
                        f"{fa['value_normalised']:,.0f} vs {fb['value_normalised']:,.0f}: check overdrafts in cash", [fa["id"], fb["id"]], now)
                out["warning"] += 1

    rows = conn.execute("SELECT * FROM raw_rows WHERE document_id=? ORDER BY page_no, line_no", (doc_id,)).fetchall()

    def values(row):
        return {v["column"]: v["value"] for v in json.loads(row["values_json"])}

    def segment(statement, lo, hi, name):
        nonlocal out
        st = [r for r in rows if r["statement"] == statement]
        idx = {r["field"]: i for i, r in reversed(list(enumerate(st))) if r["field"]}  # first occurrence
        if lo is not None and lo not in idx or hi not in idx:
            return
        start = idx[lo] if lo is not None else None
        end = idx[hi]
        if start is not None and start >= end:
            return
        inner = st[start + 1:end] if start is not None else _section_rows(st, end)
        # A printed sub-total of the lines above it ('Total', unlabelled) would be counted twice.
        inner = [r for r in inner if r["label"].strip().lower() not in ("", "total", "subtotal", "sub-total", "الإجمالي")]
        for col in values(st[end]):
            parts = ([values(st[start]).get(col)] if start is not None else []) + [values(r).get(col) for r in inner]
            target = values(st[end]).get(col)
            if target is None or any(p is None for p in parts):
                _record(conn, doc_id, f"{name} [{col}]", "not_checked", "a printed value in the segment is unreadable", [], now)
                out["not_checked"] += 1
                continue
            ok = _close(abs(target), abs(sum(parts)), len(parts), 1)  # printed values, stated unit
            involved = ([st[start]] if start is not None else []) + inner + [st[end]]
            ids = [f["id"] for r in involved if r["field"] for f in conn.execute(
                "SELECT id FROM facts WHERE document_id=? AND source_page=? AND field=? AND column_period_end=?",
                (doc_id, r["page_no"], r["field"], col))]
            _record(conn, doc_id, f"{name} [{col}]", "passed" if ok else "failed",
                    f"printed {target:,.0f} vs sum of {len(parts)} printed lines {sum(parts):,.0f} "
                    f"(lines: {', '.join(r['label'][:30] for r in inner)})", ids, now)
            out["passed" if ok else "failed"] += 1

    for statement, lo, hi in SEGMENTS:
        segment(statement, lo, hi, f"rows {lo} -> {hi}")
    for statement, total in SECTION_TOTALS + CASH_FLOW_SECTIONS:
        segment(statement, None, total, f"rows in section = {total}")

    # A balance-sheet line with a figure in one period column but not the other: often an OCR reading that
    # dropped a value or moved it to the line above. A warning only, since new lines print a nil mark
    # that OCR can miss.
    n_cols = max((len(values(r)) for r in rows if r["statement"] == "balance_sheet"), default=0)
    for r in rows:
        if r["statement"] == "balance_sheet" and r["field"] and n_cols >= 2 and 0 < len(values(r)) < n_cols:
            ids = [f["id"] for f in conn.execute("SELECT id FROM facts WHERE document_id=? AND source_page=? AND field=?",
                                                 (doc_id, r["page_no"], r["field"]))]
            _record(conn, doc_id, f"line has a value in only some columns: {r['field']}", "warning",
                    f"page {r['page_no']} '{r['label']}': {values(r)}", ids, now)
            out["warning"] += 1

    # The same field printed twice in one statement must carry the same values.
    seen: dict[tuple, tuple] = {}
    for r in rows:
        if not r["field"]:
            continue
        key = (r["statement"], r["field"])
        if key in seen and seen[key][0] != values(r):
            _record(conn, doc_id, f"duplicate line differs: {r['field']}", "failed",
                    f"page {seen[key][1]} vs page {r['page_no']}: {seen[key][0]} vs {values(r)}", [], now)
            out["failed"] += 1
        seen.setdefault(key, (values(r), r["page_no"]))
    conn.commit()
    return out


SUBTOTALS = {"cfo", "cfi", "cff", "net_change_in_cash", "total_equity", "equity_parent"}


def _section_rows(st: list, end: int) -> list:
    """Rows above a section total, back to the previous subtotal or the section header."""
    section = st[end]["label"]
    inner = []
    for r in reversed(st[:end]):
        f = r["field"] or ""
        if f.startswith("total") or f in SUBTOTALS or (r["label"] and r["label"].lower() == section.lower()):
            break
        inner.append(r)
    return list(reversed(inner))
