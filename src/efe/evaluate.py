"""Score extracted facts against tests/answer_key.csv (hand-checked values).

Each filled answer-key row is one of:
  correct            extracted value equals the key (after unit scaling, rounding tolerance)
  wrong_flagged      extracted value differs, but the fact is on a failed check or low confidence
  wrong_unflagged    extracted value differs and nothing flagged it: the error type that must reach zero
  not_extracted      no extracted value for that field (expected for note fields on the free path)
  text_field         auditor, opinion etc.: compared by a human, not scored here
"""
import csv
import sqlite3
from collections import Counter
from pathlib import Path

from efe import config

ANSWER_KEY = config.ROOT / "tests" / "answer_key.csv"
SCALE = {"units": 1, "thousands": 1_000, "millions": 1_000_000}
TEXT_FIELDS = {"auditor", "audit_opinion", "unit_stated", "special_fx_treatment_used", "fx_sensitivity_disclosed"}


# Key fields the engine stores under another name, or as parts that add up to the key's figure.
ALIASES = {"employee_profit_share": ["employee_profit_share_paid"],
           "lease_liabilities": ["lease_liabilities_current", "lease_liabilities_non_current"]}


def latest_fact(conn, doc_id: int, field: str, column: str):
    parts = [conn.execute(
        "SELECT * FROM facts WHERE document_id=? AND field=? AND column_period_end=? ORDER BY id DESC LIMIT 1",
        (doc_id, f, column)).fetchone() for f in ALIASES.get(field, [field])]
    names = ALIASES.get(field, [field])
    lost = [f for f, p in zip(names, parts) if p is None and conn.execute(
        "SELECT 1 FROM facts WHERE document_id=? AND field=? LIMIT 1", (doc_id, f)).fetchone()]
    if len(parts) > 1 and lost:
        # A part the filing prints (it exists for another year) but this year lacks: the sum is incomplete,
        # so it is scored as not extracted, never as a wrong total.
        return {"value": None, "partial": lost}
    parts = [p for p in parts if p is not None]
    if len(parts) <= 1:
        return parts[0] if parts else None
    # A sum of parts: scored on the total, flagged if any part is (dict mimics a facts row).
    f = dict(parts[0])
    f["value"] = sum((p["value"] or 0) * SCALE.get(p["unit"], 1) for p in parts) / SCALE.get(f["unit"], 1)
    f["parts"] = parts
    return f


def flagged(conn, fact) -> bool:
    if isinstance(fact, dict) and "parts" in fact:
        return any(flagged(conn, p) for p in fact["parts"])
    if fact["confidence"] == "low":
        return True
    for r in conn.execute("SELECT fact_ids FROM checks WHERE document_id=? AND status IN ('failed','warning')",
                          (fact["document_id"],)):
        if str(fact["id"]) in (r["fact_ids"] or "").split(","):
            return True
    return False


def run(conn: sqlite3.Connection, key_path: Path = ANSWER_KEY) -> dict:
    with open(key_path, newline="", encoding="utf-8") as fh:
        key = [r for r in csv.DictReader(fh)
               if r["value_as_reported"].strip() or r["notes"].strip().lower().startswith("not disclosed")]
    results, details = Counter(), []
    for k in key:
        doc = conn.execute("SELECT id FROM documents WHERE source_url=?", (k["source_url"],)).fetchone()
        if k["field"] in TEXT_FIELDS:
            results["text_field"] += 1
            continue
        if not doc:
            results["document_not_ingested"] += 1
            continue
        fact = latest_fact(conn, doc["id"], k["field"], k["period_end"])
        if not k["value_as_reported"].strip():  # key says not disclosed
            outcome = "correct" if fact is None or fact["value"] is None else "wrong_unflagged"
            if outcome != "correct":
                details.append(f"wrong_unflagged: {k['company_id']} {k['fiscal_year']} {k['field']}: key says not disclosed, "
                               f"extracted {fact['value']:,.0f} (page {fact['source_page']}: {fact['source_text']})")
        elif fact is None or fact["value"] is None:
            outcome = "not_extracted"
            details.append(f"not_extracted: {k['company_id']} {k['fiscal_year']} {k['field']} (key {k['value_as_reported']}, page {k['source_page']})")
        else:
            want = float(k["value_as_reported"].replace(",", "")) * SCALE.get(k["unit"].strip(), 1)
            got = fact["value"] * SCALE.get(fact["unit"], 1)
            tol = SCALE.get(k["unit"].strip(), 1) * 0.5
            if abs(want - got) <= tol:  # both signed as printed: brackets become minus
                outcome = "correct"
            else:
                outcome = "wrong_flagged" if flagged(conn, fact) else "wrong_unflagged"
                details.append(f"{outcome}: {k['company_id']} {k['fiscal_year']} {k['field']}: key {want:,.0f} vs "
                               f"extracted {got:,.0f} (page {fact['source_page']}, {fact['method']})")
        results[outcome] += 1
    scored = sum(results[x] for x in ("correct", "wrong_flagged", "wrong_unflagged"))
    checkers = Counter(k["checked_by"].strip() or "unknown" for k in key)
    return {"filled_key_rows": len(key), "checked_by": dict(checkers), "results": dict(results),
            "accuracy_on_extracted": round(results["correct"] / scored, 3) if scored else None, "errors": details}
