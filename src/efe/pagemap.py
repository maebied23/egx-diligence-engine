"""Page map: which page holds which primary statement, and which note topics appear where.

Rule-based and explainable. A primary statement page must (1) carry the statement title in its
first lines, (2) not be a notes or contents page, (3) contain enough numbers to be a table.
Patterns cover English and Arabic titles (docs/06_arabic_glossary.md).
"""
import difflib
import re
import sqlite3

from efe import pagetext
from efe.numbers import looks_numeric

TITLE_LINES = 10
MIN_NUMBERS = 15

STATEMENTS = {
    "balance_sheet": r"statement of financial position|balance sheet|المركز المالي",
    "income_statement": r"statement of (profit|income)|income statement|profit (or|and) loss statement|قائمة الدخل|الأرباح أو الخسائر",
    "oci": r"comprehensive income|الدخل الشامل",
    "equity": r"changes in (the )?(shareholders.? )?equity|التغير(ات)? في حقوق الملكية",
    "cash_flow": r"cash flows?|التدفقات النقدية",
}
# Checked in this order: a combined "profit or loss and other comprehensive income" title is an income statement.
ORDER = ["equity", "cash_flow", "balance_sheet", "income_statement", "oci"]

NOT_A_STATEMENT = r"notes to|contents?\b|المحتويات|الإيضاحات المتممة|auditor|مراقب الحسابات"

NOTE_TOPICS = {
    "fx_risk": r"foreign currenc(y|ies) risk|currency risk|exchange rate risk|مخاطر العملات|خطر تقلبات أسعار صرف",
    "fx_position": r"(balances|positions|denominated) in foreign currenc|foreign currency (balances|positions)|الأرصدة بالعملات الأجنبية|المراكز بالعملات",
    "borrowings": r"\bloans\b|borrowings|credit facilities|bank overdraft|القروض|تسهيلات ائتمانية",
    "commitments": r"letters? of credit|letters? of guarantee|capital commitments|contingent liabilit|الاعتمادات المستندية|خطابات الضمان|الارتباطات الرأسمالية|الالتزامات المحتملة",
    "special_fx_treatment": r"annex\s*\(?c\)?|appendix\s*\(?c\)?|special accounting (treatment|treatement)|exceptional accounting|الملحق \(?ج\)?|المعالجة المحاسبية الخاصة",
    "segments": r"operating segments|segment (information|reporting)|القطاعات التشغيلية",
    "related_parties": r"related part(y|ies)|الأطراف ذات العلاقة",
    "auditor_report": r"auditor.?s report|we have audited|basis for (qualified )?opinion|تقرير مراقب الحسابات",
}


def is_notes_page(text: str) -> bool:
    """A notes page carries a heading line that starts with 'Notes to ...'. The phrase inside a
    sentence (an auditor's report: '...and notes to the financial statements') does not count,
    and neither does a contents page, which lists 'Notes to ...' as one of its entries."""
    head = text.splitlines()[:TITLE_LINES]
    if any(re.search(r"\bcontents?\b|المحتويات|الفهرس", ln, re.I) for ln in head):
        return False
    return any(re.match(r"\W*(notes to (the )?((consolidated|separate|standalone) )?financial statements|الإيضاحات المتممة)",
                        ln.strip(), re.I) for ln in head)


TITLE_VOCAB = ["statement", "statements", "consolidated", "financial", "position", "profit", "loss", "comprehensive",
               "income", "cash", "flows", "changes", "equity", "balance", "sheet", "separate"]


def correct_title(line: str) -> str:
    """OCR slips in title words ('Staterent of Financial Position') corrected against a short list."""
    out = []
    for token in re.split(r"(\W+)", line.lower()):
        if len(token) >= 5 and token.isalpha() and token not in TITLE_VOCAB:
            m = difflib.get_close_matches(token, TITLE_VOCAB, n=1, cutoff=0.8)
            token = m[0] if m else token
        out.append(token)
    return "".join(out)


def statement_title(lines: list[str]) -> str | None:
    """The statement named by the first title line, judged line by line so body text
    like 'reclassified to profit or loss statement' cannot win."""
    for line in lines[:TITLE_LINES]:
        low = correct_title(line)
        if not re.search(r"statement|balance sheet|قائمة", low):
            continue
        for name in ORDER:
            if re.search(STATEMENTS[name], low):
                return name
    return None


# Fallback when no title can be read (poor scans): a statement recognised by the lines it must contain.
BODY_SIGNS = {
    # 'total equity and liabilities' as well: a poor scan can lose the assets total (LCSW FY2024 IFRS)
    "balance_sheet": [r"total (non[- ]?current |current )?assets|total equity and liabilities|total liabilities and equity",
                      r"total (equity|liabilities)"],
    "cash_flow": [r"operating activities", r"investing activities"],
    "income_statement": [r"gross profit|net sales|revenue", r"before (income )?tax"],
}


def classify_by_body(text: str) -> str | None:
    from efe.mapping import ocr_correct
    body = " ".join(ocr_correct(ln) for ln in text.splitlines())
    hits = [name for name, pats in BODY_SIGNS.items() if all(re.search(p, body, re.I) for p in pats)]
    return hits[0] if len(hits) == 1 else None


def classify_page(text: str) -> tuple[str | None, list[tuple[str, str]]]:
    """Returns (primary statement or None, [(note topic, evidence), ...])."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    head = " ".join(lines[:TITLE_LINES]).lower()
    full = text.lower()
    statement = None
    numbers = sum(1 for tok in text.split() if looks_numeric(tok))
    if numbers >= MIN_NUMBERS and not re.search(NOT_A_STATEMENT, head):
        statement = statement_title(lines)
    topics = []
    for tag, pattern in NOTE_TOPICS.items():
        m = re.search(pattern, full)
        if m:
            topics.append((tag, m.group(0)))
    return statement, topics


def map_document(conn: sqlite3.Connection, doc_id: int, ocr_lang: str = "eng", max_pages: int | None = None) -> dict:
    n = conn.execute("SELECT page_count FROM documents WHERE id=?", (doc_id,)).fetchone()["page_count"]
    kinds = {r["page_no"]: r["kind"] for r in conn.execute("SELECT page_no, kind FROM pages WHERE document_id=?", (doc_id,))}
    can_ocr = pagetext.ocr_available(ocr_lang)
    found: dict[str, list[int]] = {"_skipped_no_ocr": []}  # so len(found) > 1 once a statement is found
    conn.execute("DELETE FROM page_tags WHERE document_id=?", (doc_id,))
    conn.execute("UPDATE pages SET statement=NULL WHERE document_id=?", (doc_id,))
    in_notes, since_last = False, 0
    for page_no in range(1, (min(n, max_pages) if max_pages else n) + 1):
        if kinds[page_no] == "scanned" and not can_ocr:
            found["_skipped_no_ocr"].append(page_no)
            continue
        text = pagetext.get_text(conn, doc_id, page_no, ocr_lang, fast=True)  # titles only: fast OCR is enough
        statement, topics = classify_page(text)
        in_notes = in_notes or is_notes_page(text)
        # The statements sit together; three pages without one after they start means the notes have begun
        # (some companies print no 'Notes to...' heading).
        looking = not in_notes and not (len(found) > 1 and since_last >= 3)
        if (looking and statement is None and kinds[page_no] == "scanned"
                and sum(1 for tok in text.split() if looks_numeric(tok)) >= MIN_NUMBERS):
            # A table page whose title the fast reading garbled: read it properly (cached for extraction).
            full_text = pagetext.get_text(conn, doc_id, page_no, ocr_lang)
            statement = classify_page(full_text)[0] or classify_by_body(full_text)
        if statement and looking:
            conn.execute("UPDATE pages SET statement=? WHERE document_id=? AND page_no=?", (statement, doc_id, page_no))
            found.setdefault(statement, []).append(page_no)
            since_last = 0
        elif len(found) > 1:
            since_last += 1
        for tag, evidence in topics:
            conn.execute("INSERT OR REPLACE INTO page_tags VALUES (?,?,?,?)", (doc_id, page_no, tag, evidence))
    conn.commit()
    return found
