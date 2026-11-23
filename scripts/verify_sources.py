"""Check every URL in data/sources/filings.csv and record whether it resolves.

Adds or refreshes four columns: http_status, content_type, bytes, checked_on.
Does not download whole files (HEAD, then a 1-byte ranged GET if HEAD is refused).
Throttled to be polite to company websites.

Usage: python scripts/verify_sources.py [path/to/filings.csv]
"""
import csv
import datetime as dt
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent.parent / "data" / "sources" / "filings.csv"
UA = "Mozilla/5.0 (egypt-filings-engine source check)"
CHECK_COLS = ["http_status", "content_type", "bytes", "checked_on"]
DELAY_S = 1.0


def ssl_context():
    # python.org builds on macOS ship without CA certs; prefer certifi, then the system bundle.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    if os.path.exists("/etc/ssl/cert.pem"):
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ssl.create_default_context()


CTX = ssl_context()


def quote_url(url):
    # Some company sites use Arabic or en-dash characters in file names.
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(parts._replace(path=urllib.parse.quote(parts.path, safe="/%")))


def probe(url):
    url = quote_url(url)
    for method, headers in (("HEAD", {}), ("GET", {"Range": "bytes=0-0"})):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, **headers})
        try:
            with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
                size = r.headers.get("Content-Length", "")
                crange = r.headers.get("Content-Range", "")
                if crange and "/" in crange:
                    size = crange.rsplit("/", 1)[1]
                return str(r.status), r.headers.get("Content-Type", ""), size
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 405, 501):
                continue
            return str(e.code), "", ""
        except Exception as e:  # network errors are recorded, not raised
            return f"error: {type(e).__name__}", "", ""
    return "error: refused", "", ""


def main(path):
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = list(reader.fieldnames)
        rows = list(reader)
    cols += [c for c in CHECK_COLS if c not in cols]
    today = dt.date.today().isoformat()
    ok = bad = skipped = 0
    for row in rows:
        if not row["url"]:
            skipped += 1
            continue
        status, ctype, size = probe(row["url"])
        row.update(http_status=status, content_type=ctype, bytes=size, checked_on=today)
        if status in ("200", "206"):
            ok += 1
        else:
            bad += 1
            print(f"FAIL {status}: {row['ticker']} {row['fiscal_year']} {row['period']} {row['url']}")
        time.sleep(DELAY_S)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"ok={ok} failed={bad} no_url={skipped}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT)
