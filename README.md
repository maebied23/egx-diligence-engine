# Egypt Filings Engine

Reads the published financial statements and notes of companies listed on the Egyptian Exchange (EGX) into a standard template, with every number traced to its page. It computes PE metrics on standard definitions and then answers the question an investor in Egypt always has to ask: **what happens to this business when the pound falls?**

The output is an Excel databook. Every cell carries a comment with the formula, the figures used and the page each came from.

## What it shows

Three EGX building-materials companies, Lecico (LCSW), Arabian Cement (ARCC) and Misr Cement Qena (MCQE), from five years of annual filings (FY2021–FY2025), most of them scanned PDFs.

**1. Growth in pounds was decline in dollars.** In 2023–24 all three grew revenue 29–48% a year in EGP, and all three shrank in USD.

| Company | Year | Revenue (EGP m) | Growth in EGP | Growth in USD | Real growth (CPI) |
| --- | --- | ---: | ---: | ---: | ---: |
| LCSW | FY2023 | 4,842.9 | +47.9% | −7.5% | +10.5% |
| LCSW | FY2024 | 6,644.7 | +37.2% | −7.2% | +7.0% |
| ARCC | FY2023 | 6,042.8 | +29.3% | −19.1% | −3.5% |
| ARCC | FY2024 | 8,729.8 | +44.5% | −2.3% | +12.6% |
| MCQE | FY2023 | 4,029.4 | +43.1% | −10.5% | +6.9% |

Inflation-adjusted growth was mostly positive, because prices lagged the currency. A local lender might be satisfied with that. A fund that marks its returns in dollars owns a smaller business each year. (USD at the World Bank average rate; CPI from the World Bank.)

**2. The notes tell you who carries currency risk, and one company does not tell you at all.** The currency-risk notes, read by the engine, show:

| Company | FY2024 foreign-currency monetary assets | Liabilities | Position |
| --- | ---: | ---: | --- |
| LCSW | EGP 736.2m | EGP 370.5m | Net asset of EGP 365.7m: a devaluation raises its pound value |
| ARCC | EGP 1,092.3m | EGP 916.1m | Roughly matched; foreign-currency borrowings only EGP 2.8m (an EBRD loan) |
| MCQE | not disclosed | not disclosed | The notes call FX risk "limited" and give no figures, FY2021–FY2025 |

For MCQE the databook does not guess. It records the figure as missing, names the pages read, and puts a question on the Flags sheet: ask for the FX position by currency at each year-end.

**3. Some red flags only appear when you read every page.**
- **Audit opinion:** Lecico's is qualified in every year FY2021–FY2025, with an emphasis of matter from FY2024.
- **Arithmetic in the filing itself:** Misr Cement's FY2022 income statement splits net profit into 93,044,053 (parent) and 34,566,219 (minority interests) and prints the total as 131,610,272. The two add to 127,610,272.

The engine flags such errors. It does not fix them.

These are outputs of the engine, not investment views.

## Why Egypt needs its own overlay

The PE method does not change in Egypt: EBITDA, net debt and working capital keep their standard definitions ([docs/02](docs/02_pe_context.md)). What changes is which risks dominate. The Egypt analysis sits alongside the standard figures and never replaces them:

| Standard analysis | What goes wrong in Egypt | What the engine does |
| --- | --- | --- |
| Revenue growth | Five devaluations since 2016 and inflation of 10–35% make shrinking businesses look like growth stories | EGP, USD and CPI-deflated growth side by side; a flag when EGP growth is a USD decline |
| EBITDA | FX gains and losses sit inside operating profit for some companies and below it for others | Standard EBITDA plus **EBITDA before FX**, with the FX line's position read from the statement |
| FX losses | Under EAS 13 Annex C, companies could take FX differences to equity or into asset cost, so a small P&L loss proves nothing | The P&L FX signal stays neutral until OCI, equity and capitalised FX are read, and says so |
| Currency exposure | The income statement does not show it; the currency-risk and borrowings notes do | Net FX monetary position and the FX share of borrowings, read from the notes with page references |
| Net debt | Customer advances, dividends payable and tax payable build up when dollars are scarce | Debt on the standard definition; debt-like items listed separately for the equity bridge, never netted |
| Quality of earnings | Restatements and qualified opinions are common and buried | Auditor and opinion read from the report; every figure compared with the next year's comparative |

Exposure is scored on seven signals: gross margin in devaluation years, FX result, net FX position, FX debt, export share, inventory build-up and real growth. A profile needs four of the seven, and every signal shows its evidence and rule ([docs/04](docs/04_exposure_logic.md)). The thresholds are starting points, not yet calibrated against companies classified by hand.

## What you get

| Databook sheet | What it holds |
| --- | --- |
| **Screen** | One row per company, about fifteen columns: revenue, margins, EBITDA and EBITDA before FX, leverage, cash conversion, USD growth, audit opinion, exposure profile |
| **One sheet per company** | Five years of metrics (EGP m) and the figures as reported. Low-confidence cells are shaded, and missing cells say why |
| **Exposure** | The seven signals with value, rule and evidence, or the reason a signal is missing |
| **Flags** | Each finding with **the question to put to management or the auditors**, and the evidence |
| **Sources** | Every filing used, with its URL, framework, auditor and opinion |

## How far to trust it

| Answer key: 127 values, 4 filings, all three companies, text and scanned | Result |
| --- | --- |
| Extracted and correct | 117 |
| Extracted, wrong, and flagged as doubtful | 3 |
| Extracted, wrong, and **not** flagged | **0** |
| Not extracted (blank, with the reason) | 7 |
| Accuracy on extracted values | 97.5% |

- **The target is zero unflagged errors.** A wrong number nobody questions is the one that reaches an investment committee. A regression test fails the build if accuracy drops below 95% or any wrong value goes unflagged.
- **Every failed check is investigated, not overridden.** The three FY2022 filings, the year of the main devaluation, started with 18 failed arithmetic checks. 17 traced to the engine: misread or tilted scans, and one check too narrow for a restricted-deposits line. Those were fixed in the engine, for every filing. The 18th is the addition error printed in Misr Cement's own statement, and it stays flagged.
- **The answer key was read from the page images by an AI model and has not yet been confirmed by a person.** Treat 97.5% as provisional until a hand check is done.

## How it works

1. **Page map.** Finds the statements and the notes from titles, body content and page order. It survives garbled OCR titles, upside-down pages and tilted scans.
2. **Several readings of every scanned page.** OCR runs at two resolutions with different image treatment. Any figure the readings disagree on is cropped and read again on its own at 600 and 450 dpi, away from the rule lines and bold totals that confuse a whole-page reading. Two readings that agree decide the figure, and a figure no two readings agree on stays flagged. The same applies to labels the mapper cannot recognise, and to figures taken from the notes.
3. **Table reading.** Rebuilds rows by position, straightens pages tilted beyond what OCR corrects, joins digit groups, handles bracketed and reversed-bracket negatives, and keeps note references apart from values. It infers balance-sheet sections from subtotals when a heading is unreadable.
4. **Mapping and checks.** Printed labels are mapped to standard fields (`data/label_map.csv`). Unmapped lines are kept, never dropped. Accounting identities and subtotals are re-added, and failures are flagged, never corrected.
5. **Notes.** Reads foreign-currency assets, liabilities and borrowings from the currency-risk and borrowings notes, in the four layouts these companies use.
6. **Analysis and export.** Metrics, exposure signals and flags go into the databook. Each value keeps its formula, the ids of the facts behind it, and the confidence of its weakest input.

It runs locally and free: Apple Vision for OCR, with no paid API.

## Roadmap

1. Export share from the segment note (the last unread exposure signal), plus letters of credit and covenants.
2. FX booked in OCI, equity and asset cost (EAS 13 Annex C), so the FX signal can count it.
3. A person checks the answer key, and accuracy is tested on filings the engine was not tuned on.
4. Arabic OCR, for companies that publish only in Arabic.
5. The rest of the building-materials universe in `data/sources/companies.csv`, including delisted companies, so the sample is not survivorship-biased. Then share data, for EV/EBITDA in EGP and USD.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,ui]"
.venv/bin/pip install -e ".[ocr-mac]"    # macOS: Apple Vision OCR for scanned English filings (free, local)

.venv/bin/efe ingest       # download the filings listed in data/sources/filings.csv
.venv/bin/efe triage       # classify every page as text or scanned
.venv/bin/efe run --ticker LCSW --annual    # page map, extraction and checks
.venv/bin/efe analyse      # audit opinion, notes, metrics, exposure signals, flags
.venv/bin/efe export       # outputs/efe_databook.xlsx
.venv/bin/efe eval         # score against tests/answer_key.csv
.venv/bin/efe review       # local review screen: flags and values beside page images
.venv/bin/python scripts/fetch_macro.py      # refresh USD/EGP and CPI from the World Bank
.venv/bin/python -m pytest
```

On macOS with a python.org build, if downloads fail with `CERTIFICATE_VERIFY_FAILED`, prefix pip with `SSL_CERT_FILE=/etc/ssl/cert.pem`. Filings, the database and the databook stay local; only links to the public sources are committed.

## Repository

```
src/efe/        the engine: page map, OCR, table reading, checks, notes, analysis, export
app/            local review screen
data/sources/   companies and filings, with links
data/macro/     USD/EGP and CPI series with source and retrieval date
docs/           PE definitions (02), Egypt overlay (03), exposure logic (04), schema (05), Arabic glossary (06)
tests/          unit tests, accuracy regression test, answer key
```
