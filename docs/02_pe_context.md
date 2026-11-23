# 02. Private equity context: the rules the tool must follow

The tool must speak the language of a PE investment team. Use these definitions exactly. Egypt-specific analysis (docs/03, docs/04) is layered on top of these and never changes them.

## What PE does with financial data

A PE fund buys stakes in companies, improves them, and sells them within a fixed fund life (usually about 10 years). Returns come from four sources, shown in a **value-creation bridge**:

1. **EBITDA growth** (at a constant multiple)
2. **Multiple change** between entry and exit
3. **Debt paydown** from the company's cash flow
4. **FX** (for funds measuring returns in a different currency from the company's earnings; in Egypt usually the largest swing factor)

The analyst's job with financial statements is to answer: is the business good, are the reported earnings real and repeatable, how much of profit becomes cash, what is debt-like, and what could go wrong?

## Standard definitions (use exactly)

| Term | Definition | Notes for implementation |
| --- | --- | --- |
| Revenue | Net sales after returns, rebates and discounts | Record export and local splits where disclosed |
| Gross profit | Revenue minus cost of sales | Check: must equal the reported figure |
| Gross margin | Gross profit / revenue | |
| EBITDA | Operating profit + depreciation + amortisation | Build from components; do not take a company's "EBITDA" label at face value. Record whether FX differences sit above or below operating profit in that company's presentation |
| Adjusted EBITDA | EBITDA after removing clearly non-recurring items | The tool may *suggest* adjustments with evidence; it never applies them silently. Recurring "one-offs" are not one-off |
| EBITDA margin | EBITDA / revenue | |
| Net debt | Interest-bearing borrowings (short and long term, overdrafts, leases) minus cash and equivalents | Record debt by currency |
| Debt-like items | Obligations that reduce equity value like debt: overdue taxes, dividends payable, deferred consideration, customer advances in some cases, end-of-service obligations, amounts due to related parties | Flag candidates with evidence; do not net them into net debt automatically |
| Net working capital (trade) | Inventory + trade receivables - trade payables (customer advances shown separately) | |
| DSO / DIO / DPO | Receivables / revenue x 365; inventory / cost of sales x 365; payables / cost of sales x 365 | Use average or period-end consistently and record which |
| Cash conversion | (EBITDA - capex - change in NWC) / EBITDA | |
| Free cash flow | Operating cash flow - capex | Also report from the cash flow statement directly |
| Leverage | Net debt / EBITDA | |
| Interest cover | EBITDA / finance costs | |

## Quality of earnings principles the tool should support

1. **Cash beats profit.** Compare operating cash flow with EBITDA over several years. A persistent gap means working capital or capitalised costs are absorbing profit.
2. **Reconcile.** Statements must tie: net income to retained earnings, cash on the balance sheet to the cash flow statement, current-year comparatives to the prior year's filing (flag restatements).
3. **Read the notes.** Related parties, contingent liabilities, commitments, letters of guarantee and credit, revenue recognition, subsequent events.
4. **Separate price from volume.** In inflationary Egypt, nominal growth can hide a shrinking business.
5. **Every adjustment needs evidence.** Accept, partially accept or reject; never assume.

## How results are used (so outputs fit the workflow)

- **Screening:** a comparison table that a partner can scan in a minute. Few columns, consistent definitions, sortable, with the evidence one click away.
- **Valuation:** peer margins, growth and leverage for benchmarking a target; EV/EBITDA comparables built on consistent EBITDA.
- **Diligence:** a list of questions and red flags to put to management and accountants.
- **IC memo:** conclusion first, then evidence. The tool's outputs should be quotable in a memo with their sources.

## Presentation rules

- Lead with the conclusion, then the evidence.
- Show units and currency in every table header.
- Fiscal periods labelled clearly (for example "FY2024 (Jan to Dec 2024)" or "FY2024 (Jul 2023 to Jun 2024)").
- Show both EGP and USD views where a USD conversion is relevant, with the rate source and date.
- Separate: reported facts, calculated figures, and interpretations or classifications.
