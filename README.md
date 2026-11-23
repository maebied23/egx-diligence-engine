# Egypt Filings Engine

Reads the published financial statements of companies listed on the Egyptian Exchange (EGX) into one standard template, with every number traced to its page in the filing. It then computes standard private equity metrics and the evidence for one question an investor in Egypt has to answer: **how does this business hold up when the pound falls?**

The output is an Excel databook. Every cell carries a comment giving the formula, the figures used and the page each came from.

## Summary

- **Problem.** Egyptian filings are often scanned PDFs, sometimes Arabic only, in mixed units. They report under Egyptian Accounting Standards, which in 2022–23 let companies keep some currency losses out of the income statement. Spreading five years of one company by hand takes days, and the most important devaluation effects are easy to miss.
- **What it does.** Extracts the three statements from five years of annual filings (FY2021–FY2025) for three EGX building-materials companies: Lecico (LCSW), Arabian Cement (ARCC) and Misr Cement Qena (MCQE). That is 17 filings, most of them scanned. From the extracted statements it builds EBITDA, net debt, working capital, cash conversion and leverage on standard definitions. Alongside these it shows an Egypt view: EBITDA before FX, revenue and EBITDA in USD, inflation-adjusted growth, and seven devaluation-exposure signals.
- **How far to trust it.** On 127 checked values, 97.5% of extracted figures match the filing, and every one that does not is flagged. Years with five or more failed arithmetic checks are marked low confidence and excluded from the exposure signals. Unreadable or missing figures stay blank, with the reason.
- **What it shows already.** In 2023–24 all three companies grew revenue 29–48% a year in pounds, and every one of them shrank in dollars. For a fund that reports in USD, the headline growth story is the wrong one.

## The problem: why Egypt needs its own overlay

The PE method does not change in Egypt. The definitions of EBITDA, net debt and working capital stay the same ([docs/02](docs/02_pe_context.md)). What changes is which risks dominate:

| Standard analysis | What goes wrong in Egypt | What the engine does |
| --- | --- | --- |
| Revenue growth | Five devaluations since 2016 (Nov 2016; Mar 2022; Oct 2022; Jan 2023; Mar 2024) and inflation of 10–35% make shrinking businesses look like growth stories | Shows EGP, USD (World Bank average rate) and CPI-deflated growth side by side, and flags EGP growth that is a USD decline |
| EBITDA | FX gains and losses sit inside operating profit for some companies and below it for others | Standard EBITDA plus **EBITDA before FX**, with the FX line's position read from the statement |
| FX losses | Under EAS 13 Annex C, companies could take FX differences to equity or capitalise them into assets, so a small P&L loss proves nothing | FX signals stay neutral until other comprehensive income, equity and capitalised FX are read, and say why |
| Net debt | Customer advances, dividends payable and tax payable build up when dollars are scarce | Debt stays on the standard definition; debt-like items are listed separately for the equity bridge, never netted |
| Quality of earnings | Restatements and qualified audit opinions are common, and buried | Audit opinion and auditor read from the report; each figure compared with the next year's comparative to detect restatements |

The full overlay is in [docs/03](docs/03_egypt_context.md) and the exposure scoring in [docs/04](docs/04_exposure_logic.md).

## What you get

`efe export` writes `outputs/efe_databook.xlsx`:

| Sheet | What it holds |
| --- | --- |
| **Read me** | Definitions, colour key, sources |
| **Screen** | One row per company, about fifteen columns for the latest year with EBITDA: revenue, margins, EBITDA (and before FX), leverage, cash conversion, USD growth, audit opinion, exposure profile |
| **One sheet per company** | Five years of metrics (EGP m), then the reported figures as extracted. Every cell is commented with its formula, the inputs and the source page; low-confidence cells are shaded; missing cells say why |
| **Exposure** | The seven signals per company, with value, points, rule and evidence, or the reason a signal is missing |
| **Flags** | Each red flag with the finding, **the question to put to management or the auditors**, and the evidence |
| **Sources** | Every filing used, with its URL, framework, auditor and opinion |

Example flags from the current run:

| Company | Finding | Question it raises |
| --- | --- | --- |
| LCSW | Audit opinion qualified in every year FY2021–FY2025 (KPMG Hazem Hassan from FY2022), with an emphasis of matter from FY2024 | What is the qualification, and is it resolved before signing? |
| ARCC | Operating cash flow below 70% of EBITDA in three years, most recently FY2023 (52%) | Where did the cash go: receivables, inventory, or timing of payables? |
| MCQE | EBITDA covered finance costs only 1.8x in FY2023 | How much of the debt is floating-rate, and what does cover look like after the October 2026 rate rise? |

## Example output: growth in pounds versus dollars

Revenue as extracted, EGP millions. USD growth uses the World Bank average USD/EGP rate; real growth uses the World Bank CPI index.

| Company | Year | Revenue (EGP m) | Growth in EGP | Growth in USD | Real growth (CPI) | Confidence |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| LCSW | FY2023 | 4,842.9 | +47.9% | −7.5% | +10.5% | high |
| LCSW | FY2024 | 6,644.7 | +37.2% | −7.2% | +7.0% | high |
| ARCC | FY2023 | 6,042.8 | +29.3% | −19.1% | −3.5% | medium |
| ARCC | FY2024 | 8,729.8 | +44.5% | −2.3% | +12.6% | medium |
| MCQE | FY2023 | 4,029.4 | +43.1% | −10.5% | +6.9% | medium |

Inflation-adjusted growth and USD growth tell different stories, because Egyptian prices lagged the currency. A local lender may be satisfied with positive real growth. A USD fund marks its returns in dollars, and for two years running every one of these businesses got smaller in dollars.

These figures show what the engine produces. They are not an investment view. The exposure profiles are **not yet quotable**: the 2022 filings, which cover the key devaluation year, fail too many checks for all three companies, and three of the seven signals need note tables that are not read yet (see Limitations).

## How it works

1. **Triage.** Each page is classified as text or scanned.
2. **Page map.** Finds the statements and the notes, using titles, body content and page order. It repairs garbled OCR titles, turns upside-down pages and straightens tilted scans.
3. **Reading the numbers.** Uses the text layer, or OCR (Apple Vision, local and free) on scanned pages. Scanned statement pages are read twice with different image treatment, and any value the two readings disagree on is marked low confidence.
4. **Table reading.** Rebuilds lines by position, period columns from the header years, digit groups into numbers, bracketed negatives, and note references kept apart from values.
5. **Label mapping.** Maps printed line labels to standard fields through `data/label_map.csv`. Unmapped lines are kept, not dropped.
6. **Checks.** Tests accounting identities and re-adds printed rows between subtotals. Failures are flagged, never corrected.
7. **Analysis and export.** Computes the metrics, the exposure signals and the red flags, then writes the databook.

Every stored value records its file, page, original text, extraction method and confidence. Each metric records its formula, the ids of the facts behind it and the confidence of its weakest input.

## Accuracy and trust

| Measure | Result |
| --- | --- |
| Answer-key values (4 filings, all three companies, text and scanned) | 127 |
| Extracted and correct | 117 |
| Extracted, wrong, and flagged as doubtful | 3 |
| Extracted, wrong, and **not** flagged | **0** |
| Not extracted (left blank with a reason) | 7 |
| Accuracy on extracted values | 97.5% |

- The key goal is zero unflagged errors, since a wrong number nobody questions is the one that reaches an investment committee. A regression test fails the build if accuracy drops below 95% or any wrong value goes unflagged.
- **The answer key was read from the page images by an AI model (`checked_by = claude-visual`). No person has confirmed it yet.** Treat the 97.5% as provisional until a hand check is done.
- 7 of the 17 filing-years fail five or more arithmetic checks. These are mostly OCR misreads on poor scans. In one case (MCQE FY2024) the printed figures are misaligned with their labels in the filing itself. These years are shaded and excluded from the exposure signals rather than repaired.

## Limitations

- **English filings only.** Arabic OCR needs Tesseract, which is not installed yet. Smaller EGX companies publish only in Arabic.
- **Notes to the accounts are not read.** Debt by currency, the net FX position, export share, letters of credit and covenants are therefore still missing. Exposure signals S3–S5 wait on these.
- **Three companies, one sector.** No peer medians yet.
- **Exposure thresholds are starting points.** They are not yet calibrated against hand-classified companies.
- **No market data.** There is no share price or EV/EBITDA yet.

## Roadmap

1. Read the borrowings and currency-risk notes: debt by currency and maturity, and the net FX position.
2. Read the segment note for export share, and the commitments note for letters of credit and guarantees.
3. Add Arabic OCR to cover Arabic-only filers.
4. Have a person check the answer key, and test on filings the engine was not tuned on.
5. Widen to the rest of the building-materials universe in `data/sources/companies.csv`, including delisted companies, so the sample is not survivorship-biased.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,ui]"
.venv/bin/pip install -e ".[ocr-mac]"    # macOS: Apple Vision OCR for scanned English filings (free, local)
```

On macOS with a python.org build, if downloads fail with `CERTIFICATE_VERIFY_FAILED`, prefix pip with `SSL_CERT_FILE=/etc/ssl/cert.pem`.

```bash
.venv/bin/efe ingest       # download the filings listed in data/sources/filings.csv into data/raw/
.venv/bin/efe triage       # classify every page as text or scanned
.venv/bin/efe run --ticker LCSW --annual    # page map, extraction and checks for one company's annual filings
.venv/bin/efe analyse      # audit opinion, metrics, exposure signals, red flags
.venv/bin/efe export       # write outputs/efe_databook.xlsx
.venv/bin/efe eval         # score against tests/answer_key.csv
.venv/bin/efe review       # local review screen: flags, values beside page images, unmapped labels
.venv/bin/efe status       # documents, pages, values and failed checks per company
.venv/bin/python scripts/fetch_macro.py      # refresh USD/EGP and CPI from the World Bank
.venv/bin/python -m pytest
```

Filings, the database and the databook stay local and are not in this repository. Only links to the public sources are committed (`data/sources/`).

## Repository

```
src/efe/        the engine: ingest, triage, page map, OCR, table reading, checks, analysis, export
app/            local review screen
data/sources/   source register: companies and filings with links
data/macro/     USD/EGP and CPI series with source and retrieval date
docs/           PE definitions (02), Egypt overlay (03), exposure logic (04), schema (05), Arabic glossary (06)
tests/          unit tests, accuracy regression test, answer key
```
