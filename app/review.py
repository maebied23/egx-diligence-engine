"""Review screen: flags, extracted values, unmapped labels, manual entry. Run with `efe review`.

Corrections never overwrite: each is a new fact row with method 'manual' that supersedes the old one.
"""
import csv
import datetime as dt
import json
import re

import pandas as pd
import pypdfium2 as pdfium
import streamlit as st

from efe import config, db, mapping

st.set_page_config(page_title="EFE review", layout="wide")
conn = db.connect()
db.init(conn)


@st.cache_data(show_spinner=False)
def page_image(path: str, page_no: int, scale: float = 1.6):
    pdf = pdfium.PdfDocument(path)
    try:
        return pdf[page_no - 1].render(scale=scale).to_pil()
    finally:
        pdf.close()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


reviewer = st.sidebar.text_input("Reviewer initials", key="reviewer")
docs = conn.execute("""SELECT d.*, (SELECT COUNT(*) FROM facts f WHERE f.document_id=d.id) n_facts,
                              (SELECT COUNT(*) FROM checks c WHERE c.document_id=d.id AND c.status='failed') n_failed
                       FROM documents d WHERE d.doc_type='financial_statements' ORDER BY ticker, fiscal_year DESC, period""").fetchall()
only_extracted = st.sidebar.checkbox("Only documents with extracted values", value=True)
docs = [dict(d) for d in docs if d["n_facts"] or not only_extracted]  # widgets need plain, copyable values
if not docs:
    st.info("No extracted documents yet. Run `efe run --ticker LCSW --annual` first.")
    st.stop()
choice = st.sidebar.selectbox(
    "Document", docs,
    format_func=lambda d: f"{d['ticker']} {d['fiscal_year']} {d['period']} {d['scope']} {d['framework'] or ''}"
                          f" ({d['n_facts']} values, {d['n_failed']} failed)")
doc_path = str(config.ROOT / choice["local_path"])
st.sidebar.caption(choice["source_url"])

tab_flags, tab_values, tab_unmapped, tab_manual = st.tabs(["Flags", "Values", "Unmapped labels", "Manual entry"])

with tab_flags:
    rows = conn.execute("SELECT * FROM checks WHERE document_id=? ORDER BY CASE status WHEN 'failed' THEN 0 "
                        "WHEN 'warning' THEN 1 WHEN 'not_checked' THEN 2 ELSE 3 END, check_name", (choice["id"],)).fetchall()
    counts = pd.Series([r["status"] for r in rows]).value_counts().to_dict() if rows else {}
    st.write(counts)
    for r in rows:
        if r["status"] == "passed":
            continue
        with st.expander(f"{r['status'].upper()}: {r['check_name']}"):
            st.write(r["detail"])
            ids = [int(x) for x in (r["fact_ids"] or "").split(",") if x]
            pages = sorted({f["source_page"] for f in conn.execute(
                f"SELECT source_page FROM facts WHERE id IN ({','.join('?' * len(ids))})", ids)}) if ids else []
            for p in pages:
                st.image(page_image(doc_path, p), caption=f"page {p}")

with tab_values:
    facts = pd.read_sql_query(
        """SELECT id, field, column_period_end AS period, value, unit, currency, source_page AS page, method,
                  confidence, source_text, supersedes_id, entered_by FROM facts WHERE document_id=? ORDER BY source_page, id""",
        conn, params=(choice["id"],))
    st.dataframe(facts, width="stretch", hide_index=True)
    st.subheader("Correct a value")
    if len(facts):
        fid = st.selectbox("Fact", facts["id"], format_func=lambda i: (
            lambda r: f"#{i} {r.field} [{r.period}] = {r.value} (p{r.page})")(facts.set_index("id").loc[i]))
        f = conn.execute("SELECT * FROM facts WHERE id=?", (int(fid),)).fetchone()
        left, right = st.columns([1, 1])
        with left:
            new_value = st.text_input("Correct value, as printed (negative with minus)", value="" if f["value"] is None else f"{f['value']:.0f}")
            reason = st.text_input("Reason / what the page shows")
            if st.button("Save correction", disabled=not reviewer):
                value = float(new_value.replace(",", "")) if new_value.strip() else None
                scale = {"units": 1, "thousands": 1e3, "millions": 1e6}.get(f["unit"], 1)
                statement = conn.execute("SELECT statement FROM raw_rows WHERE document_id=? AND page_no=? LIMIT 1",
                                         (f["document_id"], f["source_page"])).fetchone()
                norm = mapping.normalise_sign(statement["statement"] if statement else "", f["field"], value) * scale if value is not None else None
                conn.execute(
                    """INSERT INTO facts (document_id, ticker, fiscal_year, period, period_end, column_period_end, scope, field,
                           value, value_normalised, currency, unit, source_page, source_text, source_language, method, confidence,
                           missing_reason, supersedes_id, entered_by, created_at, notes)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'manual','high',?,?,?,?,?)""",
                    (f["document_id"], f["ticker"], f["fiscal_year"], f["period"], f["period_end"], f["column_period_end"],
                     f["scope"], f["field"], value, norm, f["currency"], f["unit"], f["source_page"], f["source_text"],
                     f["source_language"], None if value is not None else reason, f["id"], reviewer, now(), reason))
                conn.commit()
                st.success("Saved. Re-run `efe check` to refresh the flags.")
        with right:
            if f["source_page"]:
                st.image(page_image(doc_path, f["source_page"]), caption=f"page {f['source_page']}")

with tab_unmapped:
    raw = conn.execute("SELECT * FROM raw_rows WHERE document_id=? AND field IS NULL AND label != '' ORDER BY page_no, line_no",
                       (choice["id"],)).fetchall()
    st.caption("Assigning a field adds an exact-match rule to data/label_map.csv. Re-run `efe extract` afterwards.")
    fields = sorted({r.field for r in mapping.rules()})
    for r in raw:
        cols = st.columns([4, 3, 2, 1])
        cols[0].write(f"p{r['page_no']} · {r['statement']} · **{r['label']}**")
        cols[1].caption(", ".join(f"{v['raw']}" for v in json.loads(r["values_json"])))
        field = cols[2].selectbox("field", ["(leave unmapped)"] + fields + ["(new field...)"], key=f"f{r['id']}",
                                  label_visibility="collapsed")
        if cols[3].button("Add", key=f"b{r['id']}", disabled=not reviewer or field == "(leave unmapped)"):
            if field == "(new field...)":
                st.warning("Add new field names in data/label_map.csv and docs/05_schema.md by hand.")
            else:
                with open(mapping.LABEL_MAP, "a", newline="", encoding="utf-8") as fh:
                    csv.writer(fh).writerow([r["statement"], "", "^" + re.escape(mapping.normalise_label(r["label"])) + "$",
                                             field, f"added in review by {reviewer} {now()[:10]}"])
                mapping.rules.cache_clear()
                st.success(f"Rule added: {r['label']} -> {field}")

with tab_manual:
    st.caption("For values the free extractor does not read yet, mostly from the notes. Record the page and the exact text.")
    note_fields = ["debt_by_currency_usd", "debt_by_currency_eur", "fx_monetary_assets_usd", "fx_monetary_liabilities_usd",
                   "fx_sensitivity_disclosed", "letters_of_credit_outstanding", "letters_of_guarantee_outstanding",
                   "capital_commitments", "fx_capitalised_in_assets", "fx_items_oci", "employee_profit_share",
                   "treasury_bills", "closing_fx_rate_used", "revenue_export", "revenue_local", "trade_receivables",
                   "trade_payables", "shares_outstanding"]
    with st.form("manual"):
        c1, c2, c3 = st.columns(3)
        field = c1.selectbox("Field", note_fields)
        column = c2.text_input("Period end (column)", value=choice["period_end"])
        page = c3.number_input("PDF page", min_value=1, max_value=choice["page_count"] or 1, step=1)
        c4, c5, c6 = st.columns(3)
        value = c4.text_input("Value as printed (negative with minus)")
        unit = c5.selectbox("Unit", ["units", "thousands", "millions"])
        currency = c6.selectbox("Currency", ["EGP", "USD", "EUR", "other"])
        text = st.text_area("Exact text or table row from the page")
        if st.form_submit_button("Save value", disabled=not reviewer) and value.strip() and text.strip():
            v = float(value.replace(",", ""))
            conn.execute(
                """INSERT INTO facts (document_id, ticker, fiscal_year, period, period_end, column_period_end, scope, field,
                       value, value_normalised, currency, unit, source_page, source_text, source_language, method, confidence,
                       entered_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'manual','high',?,?)""",
                (choice["id"], choice["ticker"], choice["fiscal_year"], choice["period"], choice["period_end"], column,
                 choice["scope"], field, v, v * {"units": 1, "thousands": 1e3, "millions": 1e6}[unit], currency, unit,
                 int(page), text, choice["language"] or "en", reviewer, now()))
            conn.commit()
            st.success("Saved.")
    st.image(page_image(doc_path, int(page)), caption=f"page {int(page)}")
