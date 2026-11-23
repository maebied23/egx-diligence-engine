# 04. Devaluation-exposure logic

Goal: classify each company's exposure to a falling Egyptian pound, show the evidence, and be transparent about the rule used. Thresholds below are **starting points to be calibrated** against hand-classified companies. They are not established facts.

## Output per company

- **Profile:** one of `exposed_importer`, `naturally_hedged`, `beneficiary_exporter`, `mixed`, `insufficient_evidence`.
- **Score:** -100 (highly exposed) to +100 (benefits from devaluation), with the contribution of each signal.
- **Evidence list:** each signal with its value, period, source page and the rule applied.
- **Confidence:** high / medium / low, based on how many signals were available and whether they agree.

## Signals

Each signal is computed per fiscal year. "Devaluation years" are the fiscal years containing the event dates in docs/03.

| # | Signal | How to compute | Points toward exposed | Points toward protected |
| --- | --- | --- | --- | --- |
| S1 | Gross margin around devaluations | Gross margin in devaluation year minus prior year (percentage points), averaged over events | Fall of 3pp or more | Stable or rising |
| S2 | FX result, all locations | P&L FX line + FX items in OCI/equity + FX capitalised into assets (docs/03 section 2), as % of EBITDA | Losses above 5% of EBITDA | Gains |
| S3 | Net foreign-currency position | From the currency risk note: FX monetary assets minus FX monetary liabilities | Net liability | Net asset |
| S4 | Foreign-currency debt | Share of borrowings in USD/EUR | Above 25% with mainly EGP revenue | None, or matched by FX revenue |
| S5 | Export or FX-linked revenue | Export sales / total revenue (segment or revenue notes) | Below 10% | Above 25% |
| S6 | Import activity indicators | Letters of credit outstanding; mentions of imported raw materials; inventory build-up in devaluation years (DIO change) | Large LCs, rising DIO | None |
| S7 | Real revenue growth | Nominal growth deflated by CAPMAS CPI over the period | Negative real growth | Positive real growth |

## Rules

1. A signal that cannot be computed is recorded as missing, with the reason. Missing signals never count as neutral evidence.
2. Classification needs at least 4 of 7 signals available; otherwise `insufficient_evidence`.
3. If signals conflict strongly (for example S5 says exporter but S1 shows margin collapse), classify as `mixed` and say why.
4. If the company used the EAS 13 special treatment, S2 must include the non-P&L amounts; if they cannot be found, S2 is low confidence.
5. Every classification is explainable in one sentence plus the evidence table. Example: "Exposed importer: gross margin fell an average of 9pp in devaluation years, FX losses including amounts recorded in OCI averaged 18% of EBITDA, and 41% of borrowings are in USD."

## Calibration

- Calibration: hand-classify 5 to 10 companies, then tune thresholds so the rules match analyst judgement.
