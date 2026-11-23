# Egypt Filings Engine

Reads Egyptian listed companies' financial statements (English or Arabic, digital or scanned), extracts them into one standard template with every number traced to its source page, and measures how exposed each company is to devaluation of the Egyptian pound.

Status: **extraction and analysis working on three companies' English filings, FY2021 to FY2025** (Lecico, Arabian Cement, Misr Cement), with an Excel databook. Arabic OCR waits for Tesseract. Accuracy is measured against an answer key read from the page images by an AI model (`checked_by = claude-visual`), not yet confirmed by a person.

## Principles

- No number is invented or estimated. Missing values are stored as missing, with a reason.
- Every value records its source file, page, original text and extraction method.
- Failed checks are flagged for review, never silently fixed.
- Standard private equity definitions (docs/02); Egypt-specific analysis is a documented overlay (docs/03, docs/04).
- Runs locally and free by default (rule-based extraction and Tesseract OCR). A language-model extractor is an optional upgrade, measured against the same answer key.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,ui]"
.venv/bin/pip install -e ".[ocr-mac]"    # macOS: Apple Vision OCR for scanned English filings (free, local)
# Arabic OCR needs the tesseract binary. Homebrew builds it from source on Intel Macs and failed here;
# a prebuilt one from conda-forge is the next thing to try.
```

On macOS with a python.org build, if downloads fail with `CERTIFICATE_VERIFY_FAILED`, prefix pip with `SSL_CERT_FILE=/etc/ssl/cert.pem`.

## Usage

```bash
.venv/bin/efe ingest       # download filings listed in data/sources/filings.csv into data/raw/
.venv/bin/efe triage       # classify every page as text or scanned
.venv/bin/efe run --ticker LCSW --annual    # page map + extract + checks for one company's annual filings
.venv/bin/efe analyse      # audit opinion, metrics, exposure signals, red flags
.venv/bin/efe export       # outputs/efe_databook.xlsx: screen, one sheet per company, exposure, flags, sources
.venv/bin/efe eval         # score against tests/answer_key.csv
.venv/bin/efe review       # local review screen: flags, values with page images, unmapped labels, manual entry
.venv/bin/efe status       # documents, pages, values and failed checks per company
.venv/bin/python scripts/verify_sources.py   # re-check every source link
.venv/bin/python scripts/fetch_macro.py      # refresh USD/EGP and CPI (World Bank) in data/macro/
.venv/bin/python -m pytest
```

## How extraction works (free path)

1. **Triage:** each page is text or scanned (pypdfium2).
2. **Page map:** statement titles in the first lines; statements must come before the notes; note pages tagged by topic (FX risk, borrowings, LCs/LGs, Annex C, segments).
3. **Words with positions** from the text layer, or OCR (Apple Vision for English, Tesseract for Arabic) for scanned pages and incomplete text layers. Scanned statement pages are read twice with different image treatment; values the readings disagree on are marked low confidence.
4. **Table reading:** lines by position, period columns from the header years, digit groups joined into numbers, note references kept apart, reversed brackets from Arabic layout read as negatives.
5. **Label mapping** via `data/label_map.csv`. Unmapped rows are kept in `raw_rows`, not dropped.
6. **Checks:** accounting identities and re-addition of printed rows between subtotals. Failures are flagged, never fixed.

## Analysis

Standard PE definitions (docs/02): EBITDA, net debt, trade working capital and days, cash conversion, leverage, interest cover. Egypt overlay alongside, never instead: EBITDA before FX, USD revenue and EBITDA, real growth, and the seven devaluation-exposure signals of docs/04 (three still need note tables). Each metric keeps its formula, the fact ids behind it and its weakest input's confidence; missing inputs make a missing metric with the reason.

Downloaded filings (`data/raw/`) and the database (`data/db/`) are git-ignored. Only links to the original sources are committed (`data/sources/`).

## Layout

```
data/sources/   source register: companies.csv, filings.csv
docs/           PE definitions, Egypt context, exposure logic, schema, Arabic glossary
src/efe/        the engine (db, ingest, triage, ...)
scripts/        maintenance scripts
tests/          tests and the answer key
```
