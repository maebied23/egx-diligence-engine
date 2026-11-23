"""Download Egypt's annual USD/EGP rate and CPI from the World Bank API into data/macro/egypt_macro.csv.

Public data, committed with its source and retrieval date so every USD or real-terms figure can be traced.
Run: .venv/bin/python scripts/fetch_macro.py
"""
import csv
import datetime as dt
import json
import ssl
import urllib.request
from pathlib import Path

import certifi

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "macro" / "egypt_macro.csv"
SERIES = {
    "usd_egp_avg": ("PA.NUS.FCRF", "Official exchange rate (EGP per USD, period average)"),
    "cpi_index": ("FP.CPI.TOTL", "Consumer price index (2010 = 100), annual average"),
}
URL = "https://api.worldbank.org/v2/country/EGY/indicator/{code}?format=json&date=2010:2030&per_page=100"


def fetch(code: str) -> list[dict]:
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(URL.format(code=code), context=ctx, timeout=30) as r:
        meta, rows = json.load(r)
    return [{"year": int(x["date"]), "value": x["value"], "last_updated": meta.get("lastupdated", "")} for x in rows]


def main():
    today = dt.date.today().isoformat()
    out = []
    for series, (code, desc) in SERIES.items():
        for x in fetch(code):
            if x["value"] is not None:
                out.append({"series": series, "year": x["year"], "value": x["value"], "description": desc,
                            "source": "World Bank WDI", "source_url": URL.format(code=code),
                            "source_last_updated": x["last_updated"], "retrieved_on": today})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(sorted(out, key=lambda r: (r["series"], r["year"])))
    print(f"wrote {len(out)} rows to {OUT}")


if __name__ == "__main__":
    main()
