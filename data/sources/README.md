# Source register

Where each filing comes from. Links only: the PDFs themselves go in `data/raw/` (git-ignored), never in the repo.

| File | What it holds |
| --- | --- |
| `companies.csv` | Universe: EGX building materials, steel, aluminium, ceramics, glass and cables. One row per company with listing status, fiscal year-end, where its filings are published and its role (`core`, `candidate`, `exclude`, `survivorship_case`). |
| `filings.csv` | One row per document found: period, scope (consolidated / separate), accounting framework, language, URL, and the result of the last link check. |

Run `python scripts/verify_sources.py` to re-check every link. It records `http_status`, `content_type`, `bytes` and `checked_on`.

## State as of 2026-11-22

- **Full online history:** ARCC, MCQE (FY2021 to FY2025, quarterly and annual, consolidated and standalone). Both publish scanned PDFs with no text layer, so the OCR or vision path is needed from the start.
- **Partial online:** LCSW (IFRS series complete; EAS only from FY2024), SWDY (results page needs a browser), ESRS (LSE announcements).
- **Not found online:** every other core company. These need the EGX disclosure archive, which refused connections from this machine.
- **Survivorship cases:** IRON (in liquidation since 2021), ALEX (delisted 2020), TORA (delisted), and ESRS (EGX delisting approved Dec 2024). Kept in the register so the sample is not survivorship-biased.

## Caveats

- `framework` for ARCC and MCQE is EAS, confirmed from the auditor's report in one filing each (ARCC FY2024, MCQE FY2022) and assumed for the rest.
- Lecico's site labels the FY2025 statements `fy-2026`; the cover pages say year ended 31 December 2025.
- Interim periods are recorded as Q1, H1, 9M. Whether a file shows cumulative or quarter-only figures must be checked when it is extracted.
- Market caps and listing status came from TradingView and press reports. Not yet confirmed against EGX.
