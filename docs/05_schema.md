# 05. Data schema

## Value record (every extracted number)

| Field | Description |
| --- | --- |
| company_id | EGX ticker or internal ID |
| fiscal_year | Label, e.g. FY2024 |
| period_start / period_end | ISO dates |
| statement_scope | consolidated / separate |
| field | Standard field name (below) |
| value | Number as reported (sign as reported) |
| value_normalised | Number in EGP units, sign convention applied |
| currency | EGP, USD, EUR... |
| unit | units / thousands / millions (as stated in the source) |
| source_file | File name and original URL |
| source_page | Page number |
| source_text | Exact text or table row the value came from |
| source_language | ar / en |
| method | text_pdf / ocr / vision_model / excel |
| confidence | high / medium / low |
| check_status | passed / failed / not_checked, with check name |
| is_restated | true if a later filing shows a different comparative |
| notes | Free text, e.g. label variant used |

## Standard fields (v1)

Income statement: `revenue`, `revenue_export`, `revenue_local`, `cost_of_sales`, `gross_profit`, `selling_expenses`, `admin_expenses`, `other_operating_income`, `operating_profit`, `depreciation`, `amortisation`, `fx_gain_loss_pl`, `finance_costs`, `finance_income`, `profit_before_tax`, `income_tax`, `net_profit`, `net_profit_parent`, `non_controlling_interest`

Other comprehensive income / equity: `fx_items_oci`, `fx_reserve_movement`

Balance sheet: `ppe`, `projects_in_progress`, `intangibles`, `inventory`, `trade_receivables`, `contract_assets`, `due_from_related_parties`, `cash`, `total_assets`, `trade_payables`, `customer_advances`, `contract_liabilities`, `due_to_related_parties`, `short_term_borrowings`, `current_portion_long_term_debt`, `long_term_borrowings`, `lease_liabilities`, `total_liabilities`, `total_equity`

Cash flow: `cfo`, `capex`, `cfi`, `cff`, `dividends_paid`

Notes: `debt_by_currency` (list of currency/amount), `fx_monetary_assets_by_currency`, `fx_monetary_liabilities_by_currency`, `letters_of_credit_outstanding`, `letters_of_guarantee_outstanding`, `capital_commitments`, `contingent_liabilities`, `fx_capitalised_in_assets`, `special_fx_treatment_used` (true/false + reference)

Added 2026-11-22:

- Notes: `fx_sensitivity_disclosed` (the company's own currency-risk sensitivity, e.g. effect on profit of a 10% USD/EGP move, with the % used), `treasury_bills` and `investments_amortised_cost` (cash-like holdings outside cash equivalents; kept separate, never netted into net debt automatically), `provisions`, `tax_disputes` (amounts under dispute with the Egyptian Tax Authority), `capitalised_interest`, `impairments`, `closing_fx_rate_used` (USD/EGP rate the company used at period end, as disclosed)
- Equity / appropriation: `employee_profit_share`, `board_remuneration` (often booked through the profit appropriation, not the income statement)
- Market: `shares_outstanding`, `share_price` (with date and source), for EV/EBITDA comparables
- Segments: `segment_revenue` and `segment_operating_profit` (list of segment/amount), where disclosed

## Document-level facts

Stored once per document (`documents` table), each with page provenance in `facts`: `framework` (EAS / IFRS), `auditor`, `audit_opinion` (unqualified / qualified / adverse / disclaimer, plus emphasis-of-matter text), `functional_currency`, `presentation_currency`. Some EGX companies report in USD; never assume EGP.

## Calculated fields (never stored as extracted)

`ebitda`, `gross_margin`, `ebitda_margin`, `net_debt`, `nwc`, `dso`, `dio`, `dpo`, `cash_conversion`, `fcf`, `leverage`, `interest_cover`, `real_revenue_growth`, exposure signals S1 to S7. Each calculated field stores its formula and input record IDs.

## Checks (run after extraction)

- gross_profit == revenue - cost_of_sales (tolerance: rounding in the stated unit)
- total_assets == total_liabilities + total_equity
- cash (balance sheet) == closing cash (cash flow), allowing for overdraft presentation
- prior-year comparatives in this filing == values extracted from the prior filing (else `is_restated`)
- signs and units consistent across years
