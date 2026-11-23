"""Calculated figures, devaluation-exposure signals and red flags, from extracted facts.

Definitions follow docs/02 (standard PE) with the Egypt overlay of docs/03 and docs/04 kept separate:
EBITDA is standard; 'EBITDA before FX' and the USD and real-terms views are the overlay.

Every metric stores its formula with the numbers used, the fact ids behind it and the weakest input
confidence. Nothing is filled in: a metric that lacks an input is stored as missing with the reason.
"""
import datetime as dt
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field

from efe import macro

CONF_ORDER = {"low": 0, "medium": 1, "high": 2}
DEBT_FIELDS = ["short_term_borrowings", "current_portion_long_term_debt", "long_term_borrowings",
               "lease_liabilities_current", "lease_liabilities_non_current"]
# Candidates only (docs/02): listed with evidence, never netted into net debt.
DEBT_LIKE_FIELDS = ["dividends_payable", "income_tax_payable", "long_term_notes_payable", "due_to_related_parties",
                    "customer_advances", "provisions_current", "provisions_non_current"]
RESTATEMENT_FIELDS = ["revenue", "gross_profit", "operating_profit", "net_profit", "total_assets", "total_equity",
                      "cash", "cfo"]
CAPEX_FIELDS = ["capex", "capex_intangibles", "capex_projects"]
UNRELIABLE_FILING_FAILURES = 5  # a filing failing this many checks is left out of signals and marked low


def weakest(confs) -> str:
    confs = [c for c in confs if c]
    return min(confs, key=CONF_ORDER.get) if confs else "low"


@dataclass
class V:
    """A number with how it was obtained."""
    value: float | None
    formula: str
    inputs: list = field(default_factory=list)
    conf: str = "high"
    reason: str | None = None
    notes: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.value is not None


def missing(reason: str) -> V:
    return V(None, "", conf="low", reason=reason)


def fmt(x: float) -> str:
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.4g}"


def combine(value, formula, parts: list[V], notes=()) -> V:
    return V(value, formula, [i for p in parts for i in p.inputs], weakest(p.conf for p in parts),
             notes=[n for p in parts for n in p.notes] + list(notes))


def ratio(name: str, a: V, b: V, positive_denominator=True) -> V:
    if not a.ok or not b.ok:
        return missing(f"{name}: needs {'numerator' if not a.ok else 'denominator'} ({a.reason or b.reason})")
    if b.value == 0 or (positive_denominator and b.value < 0):
        return missing(f"{name}: denominator is {fmt(b.value)}, ratio not meaningful")
    return combine(a.value / b.value, f"{fmt(a.value)} / {fmt(b.value)}", [a, b])


class Book:
    """One company's facts, from its consolidated annual financial statements in one framework."""

    def __init__(self, conn: sqlite3.Connection, ticker: str):
        self.conn, self.ticker = conn, ticker
        docs = conn.execute("""SELECT * FROM documents WHERE ticker=? AND period='FY' AND scope='consolidated'
                               AND doc_type='financial_statements' AND local_path IS NOT NULL""", (ticker,)).fetchall()
        extracted = {r[0] for r in conn.execute("SELECT DISTINCT document_id FROM facts WHERE ticker=?", (ticker,))}
        docs = [d for d in docs if d["id"] in extracted]
        # One framework for the whole series so years compare; the one covering most years wins (EAS on a tie).
        count = Counter(d["framework"] or "" for d in docs)
        self.framework = max(count, key=lambda f: (count[f], f == "EAS")) if count else ""
        self.docs = {d["fiscal_year"]: d for d in docs if (d["framework"] or "") == self.framework}
        self.facts: dict[tuple[int, str, int], sqlite3.Row] = {}
        ids = list(d["id"] for d in self.docs.values())
        if ids:
            q = f"SELECT * FROM facts WHERE document_id IN ({','.join('?' * len(ids))}) ORDER BY id"
            for r in conn.execute(q, ids):  # latest row wins, so reviewer corrections apply
                self.facts[(r["fiscal_year"], r["field"], int(r["column_period_end"][:4]))] = r
            q = f"SELECT fact_ids FROM checks WHERE status='failed' AND document_id IN ({','.join('?' * len(ids))})"
            self.failed = {int(i) for r in conn.execute(q, ids) for i in (r["fact_ids"] or "").split(",") if i}
        else:
            self.failed = set()
        self.years = sorted(self.docs)
        self.unreliable = {y for y, d in self.docs.items() if conn.execute(
            "SELECT COUNT(*) FROM checks WHERE document_id=? AND status='failed'", (d["id"],)).fetchone()[0]
            >= UNRELIABLE_FILING_FAILURES}

    def period_end(self, year: int) -> str | None:
        d = self.docs.get(year) or self.docs.get(year + 1)
        return f"{year}{d['period_end'][4:]}" if d else None

    def fact(self, f: str, year: int, doc_year: int | None = None) -> V:
        """Value of a field for a fiscal year: from that year's filing, else the next filing's comparative.
        doc_year pins the filing (used for year-on-year changes, so both years come from one document)."""
        why = None
        for dy in ([doc_year] if doc_year else [year, year + 1]):
            r = self.facts.get((dy, f, year))
            if r is not None and r["value_normalised"] is None and r["missing_reason"]:
                why = why or f"{f} {year}: {r['missing_reason']}"
            if r is None or r["value_normalised"] is None:
                continue
            notes, conf = [], r["confidence"]
            if r["id"] in self.failed:
                conf = "low"
                notes.append(f"{f} {year} is on a failed check")
            if dy != year:
                notes.append(f"{f} {year} taken from the comparative column of the FY{dy} filing")
            return V(r["value_normalised"], f"{f}={fmt(r['value_normalised'])}", [r["id"]], conf, notes=notes)
        return missing(why or f"{f} {year} not extracted")

    def has(self, f: str, year: int, doc_year: int | None = None) -> bool:
        return self.fact(f, year, doc_year).ok

    def balance_sheet_read(self, year: int, doc_year: int | None = None) -> bool:
        return self.has("total_assets", year, doc_year) or self.has("total_liabilities", year, doc_year)

    def rows(self, year: int, statement: str) -> list[sqlite3.Row]:
        d = self.docs.get(year)
        if not d:
            return []
        return self.conn.execute("SELECT * FROM raw_rows WHERE document_id=? AND statement=? ORDER BY page_no, line_no",
                                 (d["id"], statement)).fetchall()


def optional_sum(book: Book, fields: list[str], year: int, doc_year=None, name="") -> V:
    """Sum of balance-sheet or cash-flow lines; a line the company does not print counts as absent, and
    is listed in the notes, only when the statement itself was read."""
    parts = [(f, book.fact(f, year, doc_year)) for f in fields]
    found = [(f, v) for f, v in parts if v.ok]
    absent = [f for f, v in parts if not v.ok]
    if not found:
        return missing(f"{name}: none of {', '.join(fields)} found for {year}")
    v = combine(sum(v.value for _, v in found), " + ".join(f"{f}={fmt(v.value)}" for f, v in found),
                [v for _, v in found])
    if absent:
        v.notes.append(f"{name}: not printed or not read: {', '.join(absent)}")
    return v


# ---------------------------------------------------------------- metrics per year

def fx_inside_operating_profit(book: Book, year: int) -> bool | None:
    rows = book.rows(year, "income_statement")
    pos = {r["field"]: i for i, r in reversed(list(enumerate(rows))) if r["field"]}
    if "fx_gain_loss_pl" not in pos or "operating_profit" not in pos:
        return None
    return pos["fx_gain_loss_pl"] < pos["operating_profit"]


def ebit(book: Book, year: int, doc_year=None) -> V:
    op = book.fact("operating_profit", year, doc_year)
    if op.ok:
        return combine(op.value, op.formula, [op], ["operating profit as printed"])
    # No operating profit line: build it up from profit before tax (docs/02: build from components).
    pbt = book.fact("profit_before_tax", year, doc_year)
    if not pbt.ok:
        return missing(f"no operating profit line and no profit before tax for {year}")
    parts, terms = [pbt], [f"profit_before_tax={fmt(pbt.value)}"]
    for f in ["finance_costs", "lease_interest", "finance_income", "share_of_associates"]:
        v = book.fact(f, year, doc_year)
        if v.ok:
            parts.append(v)
            terms.append(f"- {f}={fmt(v.value)}")
    if not book.has("finance_costs", year, doc_year):
        nfr = book.fact("net_finance_result", year, doc_year)
        if nfr.ok:
            parts.append(nfr)
            terms.append(f"- net_finance_result={fmt(nfr.value)}")
    value = pbt.value - sum(p.value for p in parts[1:])
    v = combine(value, " ".join(terms), parts,
                ["no operating profit line printed: built from profit before tax by removing finance items; "
                 "other non-operating lines between gross profit and profit before tax stay inside"])
    v.conf = weakest([v.conf, "medium"])
    return v


def d_and_a(book: Book, year: int, doc_year=None) -> V:
    dep = book.fact("depreciation", year, doc_year)
    if not dep.ok:
        return missing(f"depreciation not found in the {year} cash flow")
    return optional_sum(book, ["depreciation", "amortisation", "depreciation_right_of_use"], year, doc_year, "D&A")


def ebitda(book: Book, year: int, doc_year=None) -> tuple[V, V, bool | None]:
    """(EBITDA, EBITDA before FX, whether FX differences sit inside EBITDA)."""
    e, da = ebit(book, year, doc_year), d_and_a(book, year, doc_year)
    if not e.ok or not da.ok:
        m = missing(e.reason or da.reason)
        return m, m, None
    v = combine(e.value + da.value, f"EBIT {fmt(e.value)} + D&A {fmt(da.value)}", [e, da])
    fx = book.fact("fx_gain_loss_pl", year, doc_year)
    built_from_pbt = not book.has("operating_profit", year, doc_year)
    inside = True if built_from_pbt else fx_inside_operating_profit(book, doc_year or year)
    if not fx.ok:
        ex = combine(v.value, v.formula, [v], ["no separate FX line in the income statement"])
        return v, ex, inside
    if inside:
        ex = combine(v.value - fx.value, f"EBITDA {fmt(v.value)} - FX in P&L {fmt(fx.value)}", [v, fx])
    else:
        ex = combine(v.value, v.formula, [v], ["FX differences are printed below operating profit"])
    return v, ex, inside


def year_metrics(book: Book, y: int) -> dict[str, tuple[V, str]]:
    m: dict[str, tuple[V, str]] = {}
    egp, pct = "EGP", "%"
    rev, cos, gp = book.fact("revenue", y), book.fact("cost_of_sales", y), book.fact("gross_profit", y)
    m["revenue"] = (rev, egp)
    m["gross_profit"] = (gp, egp)
    m["gross_margin"] = (ratio("gross margin", gp, rev), pct)
    e, ex, inside = ebitda(book, y)
    if e.ok:
        e.notes.append({True: "FX differences are inside this EBITDA", False: "FX differences are below EBITDA",
                        None: "position of FX differences not determined"}[inside])
    m["ebit"] = (ebit(book, y), egp)
    m["d_and_a"] = (d_and_a(book, y), egp)
    m["ebitda"] = (e, egp)
    m["ebitda_margin"] = (ratio("EBITDA margin", e, rev), pct)
    m["ebitda_before_fx"] = (ex, egp)
    m["ebitda_before_fx_margin"] = (ratio("EBITDA before FX margin", ex, rev), pct)
    m["net_profit"] = (book.fact("net_profit", y), egp)
    m["net_margin"] = (ratio("net margin", book.fact("net_profit", y), rev), pct)
    fx = book.fact("fx_gain_loss_pl", y)
    m["fx_gain_loss_pl"] = (fx if fx.ok else missing(f"no separate FX line in the {y} income statement"), egp)
    m["fx_pl_to_ebitda_before_fx"] = (ratio("FX result / EBITDA before FX", fx, ex), pct)
    m["fx_items_oci"] = (book.fact("fx_items_oci", y), egp)

    # Debt: interest-bearing borrowings and leases (docs/02). Debt-like items are listed, not netted.
    if book.balance_sheet_read(y):
        gross = optional_sum(book, DEBT_FIELDS, y, name="gross debt")
        if not gross.ok:
            gross = V(0.0, "no borrowing or lease lines on the balance sheet", conf="medium",
                      notes=["check: balance sheet read but no debt lines found"])
    else:
        gross = missing(f"{y} balance sheet not extracted")
    cash = book.fact("cash", y)
    m["gross_debt"] = (gross, egp)
    m["cash"] = (cash, egp)
    nd = combine(gross.value - cash.value, f"gross debt {fmt(gross.value)} - cash {fmt(cash.value)}", [gross, cash]) \
        if gross.ok and cash.ok else missing(gross.reason or cash.reason)
    tb = book.fact("treasury_bills", y)
    if nd.ok and tb.ok:
        nd.notes.append(f"treasury bills {fmt(tb.value)} held outside cash, not netted")
    m["net_debt"] = (nd, egp)
    m["leverage"] = (ratio("net debt / EBITDA", nd, e), "x")
    dl = optional_sum(book, DEBT_LIKE_FIELDS, y, name="debt-like candidates") if book.balance_sheet_read(y) \
        else missing(f"{y} balance sheet not extracted")
    m["debt_like_candidates"] = (dl, egp)
    fc = optional_sum(book, ["finance_costs", "lease_interest"], y, name="finance costs")
    if fc.ok:
        fc = combine(-fc.value, f"-({fc.formula})", [fc])
        m["interest_cover"] = (ratio("EBITDA / finance costs", e, fc), "x")
    else:
        ip = book.fact("interest_paid", y)
        if ip.ok:
            ipv = combine(-ip.value, f"interest paid {fmt(-ip.value)}", [ip], ["finance costs not printed separately: cash interest paid used"])
            m["interest_cover"] = (ratio("EBITDA / interest paid", e, ipv), "x")
        else:
            m["interest_cover"] = (missing("no finance cost or interest paid line"), "x")

    # Trade working capital, period-end basis (docs/02 allows period-end; recorded here).
    m.update(working_capital(book, y, y))
    rec, inv, pay = (m[k][0] for k in ("trade_receivables_used", "inventory", "trade_payables_used"))
    m["dso"] = (scale(ratio("DSO", rec, rev), 365, "x 365"), "days")
    cos_pos = combine(-cos.value, f"cost of sales {fmt(-cos.value)}", [cos]) if cos.ok else cos
    m["dio"] = (scale(ratio("DIO", inv, cos_pos), 365, "x 365"), "days")
    m["dpo"] = (scale(ratio("DPO", pay, cos_pos), 365, "x 365"), "days")

    cfo = book.fact("cfo", y)
    capex = optional_sum(book, CAPEX_FIELDS, y, name="capex")
    m["cfo"] = (cfo, egp)
    m["capex"] = (capex, egp)
    m["fcf"] = (combine(cfo.value + capex.value, f"CFO {fmt(cfo.value)} + capex {fmt(capex.value)}", [cfo, capex])
                if cfo.ok and capex.ok else missing(cfo.reason or capex.reason), egp)
    m["cfo_to_ebitda"] = (ratio("CFO / EBITDA", cfo, e), pct)
    # Cash conversion: both NWC years from the same filing, so a restatement cannot create a movement.
    prev = working_capital(book, y - 1, y)
    nwc, nwc0 = m["nwc"][0], prev["nwc"][0]
    if e.ok and capex.ok and nwc.ok and nwc0.ok and e.value > 0:
        d = nwc.value - nwc0.value
        m["change_in_nwc"] = (combine(d, f"NWC {fmt(nwc.value)} - prior {fmt(nwc0.value)}", [nwc, nwc0]), egp)
        m["cash_conversion"] = (combine((e.value + capex.value - d) / e.value,
                                        f"(EBITDA {fmt(e.value)} + capex {fmt(capex.value)} - change in NWC {fmt(d)}) / EBITDA",
                                        [e, capex, nwc, nwc0]), pct)
    else:
        why = "EBITDA not positive" if e.ok and e.value <= 0 else (e.reason or capex.reason or nwc.reason or nwc0.reason)
        m["change_in_nwc"] = (missing(why), egp)
        m["cash_conversion"] = (missing(why), pct)

    # Growth from one filing (current vs comparative), then the USD and real-terms overlay.
    rev0 = book.fact("revenue", y - 1, doc_year=y)
    g = combine(rev.value / rev0.value - 1, f"{fmt(rev.value)} / {fmt(rev0.value)} - 1", [rev, rev0]) \
        if rev.ok and rev0.ok and rev0.value > 0 else missing(rev.reason or rev0.reason or "prior revenue not positive")
    m["revenue_growth"] = (g, pct)
    pe = book.period_end(y) or ""
    if not pe.endswith("12-31"):
        why = "fiscal year is not the calendar year: calendar-year averages would mismatch" if pe else "no filing"
        for k, u in [("usd_egp_avg", "EGP per USD"), ("revenue_usd", "USD"), ("ebitda_usd", "USD"),
                     ("revenue_growth_usd", pct), ("real_revenue_growth", pct)]:
            m[k] = (missing(why), u)
        return m
    r1, r0 = macro.get("usd_egp_avg", y), macro.get("usd_egp_avg", y - 1)
    c1, c0 = macro.get("cpi_index", y), macro.get("cpi_index", y - 1)
    m["usd_egp_avg"] = (V(r1.value, r1.ref, [f"macro:{r1.series}:{r1.year}"], "high") if r1 else missing(f"no {y} rate"), "EGP per USD")
    for k, src in [("revenue_usd", rev), ("ebitda_usd", e)]:
        m[k] = (combine(src.value / r1.value, f"{fmt(src.value)} / {r1.value:.4f} ({r1.source})", [src],
                        ["converted at the World Bank annual average official rate"]) if src.ok and r1 else
                missing(src.reason or f"no {y} average rate"), "USD")
    if g.ok and r1 and r0:
        gu = (rev.value / r1.value) / (rev0.value / r0.value) - 1
        m["revenue_growth_usd"] = (combine(gu, f"({fmt(rev.value)}/{r1.value:.4f}) / ({fmt(rev0.value)}/{r0.value:.4f}) - 1", [g]), pct)
    else:
        m["revenue_growth_usd"] = (missing(g.reason or "rate missing"), pct)
    if g.ok and c1 and c0:
        m["real_revenue_growth"] = (combine((1 + g.value) / (c1.value / c0.value) - 1,
                                            f"(1 + {g.value:.4f}) / (CPI {c1.value:.1f} / {c0.value:.1f}) - 1", [g],
                                            ["deflated by Egypt CPI annual average (World Bank)"]), pct)
    else:
        m["real_revenue_growth"] = (missing(g.reason or "CPI missing"), pct)
    return m


def scale(v: V, k: float, label: str) -> V:
    return combine(v.value * k, f"({v.formula}) {label}", [v]) if v.ok else v


def working_capital(book: Book, year: int, doc_year: int) -> dict[str, tuple[V, str]]:
    m = {}
    rec, pay = book.fact("trade_receivables", year, doc_year), book.fact("trade_payables", year, doc_year)
    if not rec.ok:
        rec = book.fact("trade_and_other_receivables", year, doc_year)
        if rec.ok:
            rec.notes.append("combined 'trade and other receivables' line used: overstates DSO")
    if not pay.ok:
        pay = book.fact("trade_and_other_payables", year, doc_year)
        if pay.ok:
            pay.notes.append("combined 'trade and other payables' line used: overstates DPO")
    inv = book.fact("inventory", year, doc_year)
    m["trade_receivables_used"], m["inventory"], m["trade_payables_used"] = (rec, "EGP"), (inv, "EGP"), (pay, "EGP")
    m["nwc"] = (combine(inv.value + rec.value - pay.value,
                        f"inventory {fmt(inv.value)} + receivables {fmt(rec.value)} - payables {fmt(pay.value)}", [inv, rec, pay])
                if inv.ok and rec.ok and pay.ok else missing(inv.reason or rec.reason or pay.reason), "EGP")
    return m


# ---------------------------------------------------------------- exposure signals (docs/04)

@dataclass
class Signal:
    code: str
    name: str
    value: float | None
    points: int | None
    rule: str
    evidence: str = ""
    conf: str = "medium"
    reason: str | None = None


def fiscal_period_end(book: Book) -> str:
    return next(iter(book.docs.values()))["period_end"] if book.docs else "0000-12-31"


def devaluation_changes(book: Book, metric_fn) -> list[tuple[int, float, str]]:
    """(year, change vs prior year, evidence) for each devaluation year, both years from that year's filing."""
    out = []
    for y, events in sorted(macro.devaluation_years(fiscal_period_end(book)).items()):
        if y not in book.docs or y in book.unreliable:
            continue
        a, b = metric_fn(y, y), metric_fn(y - 1, y)
        if a is not None and b is not None:
            out.append((y, a - b, f"FY{y} {a:.4g} vs FY{y - 1} {b:.4g} ({'; '.join(events)})"))
    return out


FX_POSITION_MATERIAL = 0.02  # net position below 2% of total assets counts as neutral (provisional, docs/04)
FX_DEBT_LOW, FX_DEBT_HIGH = 0.05, 0.25  # share of borrowings in foreign currency (docs/04: above 25% exposed)


def latest_years(book: Book) -> list[int]:
    return [y for y in sorted(book.docs, reverse=True) if y not in book.unreliable]


def fx_position_signal(book: Book) -> Signal:
    """S3: foreign-currency monetary assets less liabilities (currency risk note), latest reliable year,
    as a share of total assets. A net liability loses when the pound falls."""
    name = "Net foreign-currency monetary position (% of total assets)"
    rows, reasons = [], []
    for y in latest_years(book):
        a, l, ta = (book.fact(f, y, y) for f in ("fx_monetary_assets", "fx_monetary_liabilities", "total_assets"))
        if a.ok and l.ok and ta.ok and ta.value > 0:
            rows.append((y, a, l, ta))
        else:
            reasons.append(next(v.reason for v in (a, l, ta) if not v.ok))
    if not rows:
        return Signal("S3", name, None, None, "", reason=reasons[0] if reasons else "no reliable year")
    y, a, l, ta = rows[0]
    share = (a.value - l.value) / ta.value
    pts = 0 if abs(share) < FX_POSITION_MATERIAL else (1 if share > 0 else -1)
    ev = "; ".join(f"FY{yy} assets {fmt(aa.value)} less liabilities {fmt(ll.value)} = {fmt(aa.value - ll.value)} "
                   f"({100 * (aa.value - ll.value) / tt.value:+.1f}% of total assets)" for yy, aa, ll, tt in rows)
    return Signal("S3", name, 100 * share, pts,
                  f"latest reliable year (FY{y}); net liability: exposed; net asset: protected; "
                  f"within {FX_POSITION_MATERIAL:.0%} of total assets: neutral. EGP equivalents as printed in the note",
                  ev, weakest([a.conf, l.conf]))


def fx_debt_signal(book: Book, metrics: dict[int, dict]) -> Signal:
    """S4: borrowings in foreign currency (borrowings or currency risk note) over gross debt."""
    name = "Share of borrowings in foreign currency"
    rows, reasons = [], []
    for y in latest_years(book):
        fx = book.fact("fx_borrowings", y, y)
        gross = metrics.get(y, {}).get("gross_debt", (missing("gross debt not computed"),))[0]
        if fx.ok and gross.ok and gross.value > 0:
            rows.append((y, fx, gross))
        else:
            reasons.append(fx.reason if not fx.ok else gross.reason)
    if not rows:
        return Signal("S4", name, None, None, "", reason=reasons[0] if reasons else "no reliable year")
    y, fx, gross = rows[0]
    share = fx.value / gross.value
    pts = -1 if share > FX_DEBT_HIGH else (1 if share < FX_DEBT_LOW else 0)
    return Signal("S4", name, 100 * share, pts,
                  f"latest reliable year (FY{y}); above {FX_DEBT_HIGH:.0%}: exposed (export share not yet read, so a "
                  f"match with FX revenue is not tested); below {FX_DEBT_LOW:.0%}: protected; between: neutral",
                  "; ".join(f"FY{yy} {fmt(f.value)} of {fmt(g.value)} = {100 * f.value / g.value:.1f}%" for yy, f, g in rows),
                  weakest([fx.conf, gross.conf]))


def signals(book: Book, metrics: dict[int, dict]) -> list[Signal]:
    s = []

    def gm(y, dy):
        r, g = book.fact("revenue", y, dy), book.fact("gross_profit", y, dy)
        return 100 * g.value / r.value if r.ok and g.ok and r.value > 0 else None

    ch = devaluation_changes(book, gm)
    if ch:
        avg = sum(c for _, c, _ in ch) / len(ch)
        pts = -1 if avg <= -3 else (1 if avg >= 0 else 0)
        s.append(Signal("S1", "Gross margin change in devaluation years", avg, pts,
                        "average change <= -3pp: exposed; >= 0: protected; between: neutral",
                        "; ".join(f"{e} = {c:+.1f}pp" for _, c, e in ch)))
    else:
        s.append(Signal("S1", "Gross margin change in devaluation years", None, None, "", reason="no devaluation year with both years' margins"))

    def fxr(y, dy):
        _, ex, _ = ebitda(book, y, dy)
        fx = book.fact("fx_gain_loss_pl", y, dy)
        return 100 * fx.value / ex.value if fx.ok and ex.ok and ex.value > 0 else None

    vals = [(y, fxr(y, y)) for y in sorted(set(macro.devaluation_years(fiscal_period_end(book))) & set(book.docs))
            if y not in book.unreliable]
    vals = [(y, v) for y, v in vals if v is not None]
    if vals:
        avg = sum(v for _, v in vals) / len(vals)
        pts = -1 if avg <= -5 else 0
        s.append(Signal("S2", "FX result as % of EBITDA before FX (devaluation years)", avg, pts,
                        "losses above 5% of EBITDA: exposed. Gains or small losses stay neutral until FX booked in OCI, "
                        "equity and asset cost has been read (EAS 13 Annex C)",
                        "; ".join(f"FY{y} {v:+.1f}%" for y, v in vals),
                        reason=None if pts else "P&L only; OCI, equity and capitalised FX not yet read"))
    else:
        s.append(Signal("S2", "FX result as % of EBITDA before FX (devaluation years)", None, None, "",
                        reason="no FX line or EBITDA in a devaluation year"))
    s.append(fx_position_signal(book))
    s.append(fx_debt_signal(book, metrics))
    s.append(Signal("S5", "Export or FX-linked share of revenue", None, None, "",
                    reason="revenue or segment note tables are not read by the engine yet"))

    def dio(y, dy):
        inv, cos = book.fact("inventory", y, dy), book.fact("cost_of_sales", y, dy)
        return 365 * inv.value / -cos.value if inv.ok and cos.ok and cos.value < 0 else None

    ch = devaluation_changes(book, dio)
    if ch:
        avg = sum(c for _, c, _ in ch) / len(ch)
        s.append(Signal("S6", "Inventory days change in devaluation years (import build-up)", avg, -1 if avg >= 15 else 0,
                        "average rise of 15 days or more: exposed (stockpiling imports). Letters of credit not yet read, "
                        "so a stable figure is neutral, not protective",
                        "; ".join(f"{e} = {c:+.0f} days" for _, c, e in ch)))
    else:
        s.append(Signal("S6", "Inventory days change in devaluation years", None, None, "", reason="inventory or cost of sales missing"))

    real = [(y, metrics[y]["real_revenue_growth"][0]) for y in sorted(metrics)
            if metrics[y]["real_revenue_growth"][0].ok and y not in book.unreliable]
    if real:
        idx = 1.0
        for _, v in real:
            idx *= 1 + v.value
        cagr = idx ** (1 / len(real)) - 1
        s.append(Signal("S7", "Real revenue growth (CPI-deflated, compound annual)", 100 * cagr, -1 if cagr < 0 else 1,
                        "negative: exposed (shrinking in real terms); positive: protected",
                        "; ".join(f"FY{y} {100 * v.value:+.1f}%" for y, v in real),
                        conf=weakest(v.conf for _, v in real)))
    else:
        s.append(Signal("S7", "Real revenue growth", None, None, "", reason="no year with revenue growth and CPI"))
    return s


def profile(sigs: list[Signal]) -> Signal:
    avail = [x for x in sigs if x.points is not None]
    by = {x.code: x for x in sigs}
    rule = ("needs 4 of 7 signals; score = mean points x 100; <= -33 exposed, >= 33 protected, else mixed. "
            "Thresholds provisional until calibrated against hand-classified companies (docs/04)")
    if len(avail) < 4:
        return Signal("profile", "insufficient_evidence", None, None, rule,
                      f"{len(avail)} of 7 signals available", "low",
                      "; ".join(f"{x.code}: {x.reason}" for x in sigs if x.points is None))
    score = 100 * sum(x.points for x in avail) / len(avail)
    neg = lambda c: c in by and by[c].points == -1
    if score <= -33:
        name = "exposed_importer" if any(neg(c) for c in ("S3", "S4", "S6")) else "exposed (channel not identified)"
    elif score >= 33:
        name = "beneficiary_exporter" if by["S5"].points == 1 else "naturally_hedged"
    else:
        name = "mixed"
    conf = "high" if len(avail) >= 6 else "medium" if len(avail) >= 5 else "low"
    return Signal("profile", name, score, None, rule,
                  ", ".join(f"{x.code} {x.points:+d}" for x in avail), conf,
                  "; ".join(f"{x.code}: {x.reason}" for x in sigs if x.points is None) or None)


# ---------------------------------------------------------------- red flags and diligence questions

def red_flags(book: Book, metrics: dict[int, dict]) -> list[tuple]:
    """(year, severity, category, finding, question, evidence)"""
    out = []
    for y, d in sorted(book.docs.items()):
        a, l, ta = (book.fact(f, y, y) for f in ("fx_monetary_assets", "fx_monetary_liabilities", "total_assets"))
        if a.ok and l.ok and ta.ok and ta.value > 0 and (l.value - a.value) / ta.value >= 0.05:
            out.append((y, "medium", "fx", f"Net foreign-currency liability FY{y}: {fmt(l.value - a.value)} EGP "
                        f"({100 * (l.value - a.value) / ta.value:.0f}% of total assets)",
                        "Which currencies, what is hedged, and how much USD revenue covers it?",
                        f"currency risk note: assets {fmt(a.value)}, liabilities {fmt(l.value)}"))
        elif not a.ok and not l.ok and "no figure found" in (a.reason or ""):
            out.append((y, "low", "fx", f"FY{y} notes give no figures for foreign-currency balances",
                        "Ask for the FX position by currency (cash, receivables, payables, borrowings) at each year-end.",
                        a.reason))
        op = (d["audit_opinion"] or "").lower()
        if op and not op.startswith("unqualified"):
            out.append((y, "high", "audit", f"Audit opinion FY{y}: {d['audit_opinion']} ({d['auditor'] or 'auditor not read'})",
                        "What is the basis for the modification, is it resolved, and what is the amount at stake?",
                        f"auditor's report, document {d['id']}"))
        n = book.conn.execute("SELECT COUNT(*) FROM checks WHERE document_id=? AND status='failed'", (d["id"],)).fetchone()[0]
        if n:
            out.append((y, "medium", "data", f"{n} arithmetic check(s) fail in the FY{y} filing as extracted",
                        "Open each in the review screen: an OCR misread, or an error printed in the filing itself; both happen.",
                        f"checks table, document {d['id']}"))
        for f in RESTATEMENT_FIELDS:  # this filing's comparative vs the prior filing's current year
            a, b = book.fact(f, y - 1, doc_year=y), book.fact(f, y - 1, doc_year=y - 1)
            if a.ok and b.ok and abs(a.value - b.value) > max(1000, 0.001 * abs(b.value)):
                out.append((y, "medium", "earnings_quality", f"{f} FY{y - 1} differs between filings: {fmt(b.value)} "
                            f"(FY{y - 1} filing) vs {fmt(a.value)} (FY{y} comparative)",
                            "Was FY figure restated (error, policy change, reclassification), or is it a misread?",
                            f"facts {b.inputs + a.inputs}"))
    yrs = sorted(metrics)
    low_cash = [(y, metrics[y]["cfo_to_ebitda"][0].value) for y in yrs if metrics[y]["cfo_to_ebitda"][0].ok
                and metrics[y]["cfo_to_ebitda"][0].value < 0.7]
    if len(low_cash) >= 2:
        out.append((low_cash[-1][0], "high", "earnings_quality",
                    "Operating cash flow below 70% of EBITDA in " + ", ".join(f"FY{y} ({v:.0%})" for y, v in low_cash),
                    "Where is profit going: receivables, inventory build, capitalised costs? Ask for a monthly NWC bridge.",
                    "metric cfo_to_ebitda"))
    for y in yrs:
        m = metrics[y]
        lev, ic, fx = m["leverage"][0], m["interest_cover"][0], m["fx_pl_to_ebitda_before_fx"][0]
        if lev.ok and lev.value > 3:
            out.append((y, "high", "leverage", f"Net debt / EBITDA {lev.value:.1f}x in FY{y}",
                        "Covenant headroom, maturity profile and currency of the debt?", lev.formula))
        if ic.ok and ic.value < 2:
            out.append((y, "high", "leverage", f"EBITDA covers finance costs only {ic.value:.1f}x in FY{y}",
                        "How sensitive is interest to CBE rate moves (floating vs fixed, EGP vs USD)?", ic.formula))
        if fx.ok and fx.value < -0.10:
            out.append((y, "medium", "fx", f"FX losses in P&L equal {-fx.value:.0%} of EBITDA before FX in FY{y}",
                        "What foreign-currency liabilities drove the loss, and are they still open?", fx.formula))
        g, gu = m["revenue_growth"][0], m["revenue_growth_usd"][0]
        if g.ok and gu.ok and g.value > 0 and gu.value < 0:
            out.append((y, "medium", "fx", f"FY{y} revenue grew {g.value:.0%} in EGP but fell {-gu.value:.0%} in USD",
                        "For a USD fund this is a contraction: how much is price vs volume, and is pricing USD-linked?",
                        gu.formula))
        for k, lim in [("dso", 20), ("dio", 20)]:
            if y - 1 in metrics:
                a, b = m[k][0], metrics[y - 1][k][0]
                if a.ok and b.ok and a.value - b.value > lim:
                    out.append((y, "medium", "working_capital", f"{k.upper()} rose {a.value - b.value:.0f} days in FY{y} "
                                f"({b.value:.0f} to {a.value:.0f})",
                                "Customer terms, overdue balances, or stock build ahead of devaluation?", a.formula))
        dl = m["debt_like_candidates"][0]
        if dl.ok and dl.value:
            out.append((y, "low", "leverage", f"Debt-like candidates FY{y}: {fmt(dl.value)} EGP ({dl.formula})",
                        "Which of these does a buyer treat as debt in the equity bridge?", "balance sheet lines"))
        if m["ebit"][0].ok and any("built from profit before tax" in n for n in m["ebit"][0].notes):
            out.append((y, "low", "data", f"FY{y}: no operating profit line; EBITDA built up from profit before tax",
                        "Ask for the company's own EBITDA bridge; one-off lines may sit inside.", m["ebit"][0].formula))
    return out


# ---------------------------------------------------------------- run and store

def run(conn: sqlite3.Connection, ticker: str) -> dict:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    book = Book(conn, ticker)
    # Years with their own filing, plus the year before the first filing (from its comparatives).
    years = sorted(set(book.years) | ({book.years[0] - 1} if book.years else set()))
    metrics = {y: year_metrics(book, y) for y in years}
    # A filing failing many checks is unreliable as a whole, not only on the lines a check names.
    for y, m in metrics.items():
        d = book.docs.get(y)
        n = conn.execute("SELECT COUNT(*) FROM checks WHERE document_id=? AND status='failed'",
                         (d["id"],)).fetchone()[0] if d else 0
        if n >= UNRELIABLE_FILING_FAILURES:
            for v, _ in m.values():
                v.conf = "low"
                v.notes.append(f"FY{y} filing fails {n} arithmetic checks as extracted: every FY{y} figure needs review")
    conn.execute("DELETE FROM metrics WHERE ticker=?", (ticker,))
    for y, m in metrics.items():
        for name, (v, unit) in m.items():
            conn.execute("INSERT INTO metrics VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (ticker, y, name, v.value, unit, v.formula, json.dumps(sorted(set(map(str, v.inputs)))),
                          v.conf if v.ok else "low", v.reason, "; ".join(dict.fromkeys(v.notes)) or None, now))
    sigs = signals(book, metrics)
    if book.unreliable:
        note = f"years left out (filing fails {UNRELIABLE_FILING_FAILURES}+ checks): " + \
            ", ".join(f"FY{y}" for y in sorted(book.unreliable))
        for x in sigs:
            x.evidence = f"{x.evidence} [{note}]" if x.evidence else x.evidence
            x.reason = x.reason or (None if x.points is not None else note)
    prof = profile(sigs)
    conn.execute("DELETE FROM signals WHERE ticker=?", (ticker,))
    for s in sigs + [prof]:
        conn.execute("INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?)",
                     (ticker, s.code if s.code != "profile" else "profile", s.value, s.points,
                      f"{s.name}: {s.rule}" if s.code != "profile" else f"{s.name} | {s.rule}",
                      s.evidence, s.conf, s.reason, now))
    conn.execute("DELETE FROM flags WHERE ticker=?", (ticker,))
    flags = red_flags(book, metrics)
    for f in flags:
        conn.execute("INSERT INTO flags (ticker, fiscal_year, severity, category, finding, question, evidence, computed_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", (ticker, *f, now))
    conn.commit()
    return {"framework": book.framework, "years": years, "profile": prof.name,
            "score": None if prof.value is None else round(prof.value), "flags": len(flags)}
