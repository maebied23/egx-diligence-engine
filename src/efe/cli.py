"""Command line: efe init | ingest | triage | pagemap | extract | check | run | analyse | export | eval | status | review"""
import argparse
import subprocess
import sys

from efe import analysis, audit, checks, config, db, evaluate, export, extract, ingest, notes, pagemap, triage


def select_docs(conn, args):
    sql = "SELECT * FROM documents WHERE doc_type='financial_statements' AND local_path IS NOT NULL"
    params = []
    if getattr(args, "doc", None):
        sql += f" AND id IN ({','.join('?' * len(args.doc))})"
        params += args.doc
    if getattr(args, "ticker", None):
        sql += f" AND ticker IN ({','.join('?' * len(args.ticker))})"
        params += args.ticker
    if getattr(args, "year", None):
        sql += f" AND fiscal_year IN ({','.join('?' * len(args.year))})"
        params += args.year
    if getattr(args, "annual", False):
        sql += " AND period='FY'"
    return conn.execute(sql + " ORDER BY ticker, fiscal_year, period", params).fetchall()


def label(d):
    return f"[{d['id']}] {d['ticker']} {d['fiscal_year']} {d['period']} {d['scope']} {d['framework'] or ''}"


def cmd_init(conn, args):
    db.init(conn)
    print("database ready")


def cmd_ingest(conn, args):
    db.init(conn)
    print(ingest.run(conn, tickers=set(args.ticker) if args.ticker else None))


def cmd_triage(conn, args):
    for t, fy, period, scope, doc_type, n, scanned in triage.run(conn, redo=args.redo):
        print(f"{t} {fy} {period:<3} {scope:<12} {doc_type:<22} pages={n:<4} scanned={scanned}")


def cmd_pagemap(conn, args):
    for d in select_docs(conn, args):
        found = pagemap.map_document(conn, d["id"], max_pages=args.max_pages)
        skipped = found.pop("_skipped_no_ocr", [])
        print(label(d), found, f"(skipped {len(skipped)} scanned pages: no OCR)" if skipped else "")


def cmd_extract(conn, args):
    for d in select_docs(conn, args):
        s = extract.extract_document(conn, d["id"])
        print(label(d), f"rows={s['rows']} mapped={s['mapped']} facts={s['facts']} unit={s['unit']}")
        for page, what in s["pages"].items():
            print(f"    p{page}: {what}")


def cmd_check(conn, args):
    for d in select_docs(conn, args):
        print(label(d), checks.run(conn, d["id"]))


def cmd_run(conn, args):
    for d in select_docs(conn, args):
        pagemap.map_document(conn, d["id"], max_pages=args.max_pages)
        s = extract.extract_document(conn, d["id"])
        c = checks.run(conn, d["id"])
        print(label(d), f"facts={s['facts']}", c)


def cmd_analyse(conn, args):
    args.annual = True
    docs = [d for d in select_docs(conn, args) if d["scope"] == "consolidated"]
    for d in docs:
        if conn.execute("SELECT 1 FROM facts WHERE document_id=? LIMIT 1", (d["id"],)).fetchone():
            r = audit.run(conn, d["id"])
            print(label(d), f"audit: {r['opinion'] or 'not found'} ({r['auditor'] or 'auditor not identified'})"
                  + (f" p{r['page']}" if r["page"] else ""))
            print(label(d), "notes:", notes.run(conn, d["id"]) or "no currency figures found")
    for t in sorted({d["ticker"] for d in docs}):
        print(t, analysis.run(conn, t))


def cmd_export(conn, args):
    print("wrote", export.build(conn))


def cmd_eval(conn, args):
    r = evaluate.run(conn)
    print(f"answer-key rows filled: {r['filled_key_rows']} (checked by: {r['checked_by']})")
    print(r["results"], "accuracy on extracted:", r["accuracy_on_extracted"])
    for e in r["errors"]:
        print("  ", e)


def cmd_status(conn, args):
    rows = conn.execute(
        """SELECT d.ticker, COUNT(DISTINCT d.id) AS docs, SUM(d.page_count) AS pages,
                  (SELECT COUNT(*) FROM pages p JOIN documents d2 ON d2.id = p.document_id
                    WHERE d2.ticker = d.ticker AND p.kind = 'scanned') AS scanned,
                  (SELECT COUNT(*) FROM facts f WHERE f.ticker = d.ticker) AS facts,
                  (SELECT COUNT(*) FROM checks c JOIN documents d3 ON d3.id = c.document_id
                    WHERE d3.ticker = d.ticker AND c.status = 'failed') AS failed
           FROM documents d GROUP BY d.ticker ORDER BY d.ticker"""
    ).fetchall()
    print(f"{'ticker':<8}{'docs':>6}{'pages':>8}{'scanned':>9}{'facts':>8}{'failed':>8}")
    for r in rows:
        print(f"{r['ticker']:<8}{r['docs']:>6}{r['pages'] or 0:>8}{r['scanned']:>9}{r['facts']:>8}{r['failed']:>8}")


def cmd_review(conn, args):
    app = config.ROOT / "app" / "review.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app)], check=False)


def main(argv=None):
    p = argparse.ArgumentParser(prog="efe")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_filters(sp):
        sp.add_argument("--ticker", action="append")
        sp.add_argument("--year", action="append", type=int)
        sp.add_argument("--doc", action="append", type=int)
        sp.add_argument("--annual", action="store_true", help="FY documents only")
        return sp

    sub.add_parser("init").set_defaults(fn=cmd_init)
    pi = sub.add_parser("ingest", help="download filings from data/sources/filings.csv")
    pi.add_argument("--ticker", action="append")
    pi.set_defaults(fn=cmd_ingest)
    pt = sub.add_parser("triage", help="classify each page as text or scanned")
    pt.add_argument("--redo", action="store_true")
    pt.set_defaults(fn=cmd_triage)
    pm = with_filters(sub.add_parser("pagemap", help="find statement pages and note topics"))
    pm.add_argument("--max-pages", type=int)
    pm.set_defaults(fn=cmd_pagemap)
    with_filters(sub.add_parser("extract", help="read primary statements into facts")).set_defaults(fn=cmd_extract)
    with_filters(sub.add_parser("check", help="run arithmetic checks")).set_defaults(fn=cmd_check)
    pr = with_filters(sub.add_parser("run", help="pagemap + extract + check"))
    pr.add_argument("--max-pages", type=int)
    pr.set_defaults(fn=cmd_run)
    with_filters(sub.add_parser("analyse", help="audit opinion, metrics, exposure signals, red flags")).set_defaults(fn=cmd_analyse)
    sub.add_parser("export", help="write the Excel databook to outputs/").set_defaults(fn=cmd_export)
    sub.add_parser("eval", help="score against tests/answer_key.csv").set_defaults(fn=cmd_eval)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("review", help="open the review screen").set_defaults(fn=cmd_review)
    args = p.parse_args(argv)
    with db.connect() as conn:
        db.init(conn)
        args.fn(conn, args)


if __name__ == "__main__":
    main()
