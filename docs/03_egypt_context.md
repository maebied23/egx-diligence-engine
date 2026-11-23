# 03. Egypt context: what changes, and what does not

**Principle:** the PE method in docs/02 applies unchanged. Egypt changes which risks dominate and which items deserve extra attention. Every Egypt adjustment must be an explicit, documented overlay on standard definitions, so any PE professional (Egyptian or not) can follow it.

Facts below were checked in November 2026. Items not yet confirmed against the primary source say so.

## 1. Accounting framework

- Egyptian companies report under **Egyptian Accounting Standards (EAS)**. They are based on IFRS but are not identical to it. Each standard or change is issued by Prime Ministerial decree and published in the official Gazette; the Financial Regulatory Authority (FRA) hosts the decrees on its website.
- Statements are typically issued as **consolidated** (المجمعة) and **separate/standalone** (المستقلة). Prefer consolidated.
- Units vary: EGP, EGP thousands, EGP millions. Read the unit from each statement header. Never assume.
- **Fiscal year-ends:** most companies use 31 December; some use 30 June. Always record the period start and end. Devaluation analysis depends on which fiscal year contains each devaluation date.
- **Bilingual disclosure:** EGX rules require listed companies with annual revenue of EGP 2bn or more to publish financial statements in Arabic and English simultaneously. Smaller companies may publish in Arabic only.

## 2. FX accounting quirks (critical for this tool)

During the 2022 to 2023 devaluations, Egypt allowed special accounting treatments for FX differences under **EAS 13, "The Effects of Changes in Foreign Exchange Rates"**:

- Appendices/annexes to EAS 13 (Appendix B in 2022; Annex/Appendix C introduced in 2022 and later amended and extended) created a **special accounting treatment for entities affected by the 27 October 2022 exchange rate movement**. It allowed certain currency differences to be recognised outside the normal profit and loss line (for example in other comprehensive income) and allowed an option applied **asset by asset**, such as adding FX differences on liabilities used to acquire assets into those assets' cost. VERIFY the exact paragraphs, eligible items and years from the FRA-hosted decrees.
- The Annex C period was extended (covering FY2023 for many companies); not yet confirmed against the FRA decree.
- In 2024 EAS 13 was replaced (Prime Ministerial Decree 636 of 2024) to align with the IAS 21 amendments on lack of exchangeability, including requirements to estimate exchange rates and related disclosures.

**Implication for the tool:** a company can show small FX losses in its income statement because it used the special treatment, not because it was hedged. Before concluding anything about FX exposure:

1. Check the income statement FX line.
2. Check other comprehensive income and the statement of changes in equity for FX-related reserves or items.
3. Check PPE and projects-in-progress notes for capitalised FX differences.
4. Check the accounting policies note for any mention of the EAS 13 annex or special treatment.
5. Record which treatment the company used, with page references.

## 3. Devaluation timeline (analysis windows)

Use these as event dates for before/after analysis. Pre-2026 rates are approximate and must be replaced with official CBE data before use.

| Event | Date | Approximate USD/EGP | Source to confirm |
| --- | --- | --- | --- |
| Float under IMF programme | 3 Nov 2016 | ~8.9 to ~18 | CBE |
| Devaluation | 21 Mar 2022 | ~15.7 to ~18.3 | CBE |
| Move to flexible regime | 27 Oct 2022 | ~19.7 to ~23+ | CBE |
| Further depreciation | Early Jan 2023 | to ~30 | CBE |
| Float with 6-point rate hike | 6 Mar 2024 | ~31 to ~50 | CBE |
| Pressure during regional war | Late Feb to Oct 2026 | ~47.7 to above 56, ~53.8 mid-Nov 2026 | CBE, press |

Also note the **2023 FX shortage**: a parallel market and delays obtaining dollars for imports and dividend repatriation. Companies built inventory and relied on letters of credit.

## 4. Macro facts as of November 2026 (refresh before publishing)

- CBE raised rates 100 bps on 29 October 2026, its first hike since March 2024: overnight deposit 20%, lending 21%. Inflation target 7% (plus or minus 2%) moved to Q4 2027.
- Urban headline inflation was 13.9% in September 2026.
- Egypt's $8bn IMF Extended Fund Facility runs to December 2026.
- Damodaran (January 2026): Egypt rated Caa1, country risk premium 9.71%, total equity risk premium 13.94%, corporate tax rate 22.5%.

## 5. How to adjust analysis for Egypt (overlays on standard PE analysis)

| Standard PE analysis | Egypt overlay | Why |
| --- | --- | --- |
| Revenue growth | Split into real and nominal using CAPMAS CPI; where disclosed, split price and volume | Inflation of 10 to 35% can make shrinking businesses look like growth stories |
| Gross margin trend | Compare the fiscal year containing each devaluation with the prior year | Tests pricing power and import dependence |
| Net debt | Split by currency (EGP vs USD/EUR) | Dollar debt with pound revenue is the most dangerous mismatch |
| Working capital | Track inventory build-up around devaluations; government receivables separately | Stockpiling and slow state payers absorb cash |
| FX gains/losses | Check P&L, OCI, equity and capitalised amounts (section 2) | Special accounting treatments hide exposure |
| Commitments | Letters of credit (الاعتمادات المستندية) and letters of guarantee (خطابات الضمان) | LCs signal import activity; LGs are contingent exposures, common for contractors |
| Valuation | Keep currency consistent: EGP cash flows at an EGP discount rate, or USD cash flows at a USD rate plus country risk premium. Never mix | The most common Egypt valuation error |
| Returns | Show USD returns = EGP returns x (entry FX / exit FX); add an FX bar to the value-creation bridge | Shows how much of the return is a currency bet |

Relative purchasing power parity links the two discount rates:
(1 + r_EGP) = (1 + r_USD) x (1 + inflation_EGP) / (1 + inflation_USD)

## 6. Sector notes for the default universe (construction, building materials, industrials)

- **Contractors:** revenue on percentage-of-completion; check contract assets/liabilities (under- and over-billing), retentions, claims, government receivables, letters of guarantee, margin fade on projects.
- **Building materials (cement, steel, ceramics, etc.):** energy and imported input costs (scrap, coal, equipment, spare parts), export sales share, pricing power in a cyclical domestic market.
- **Industrials:** imported components and machinery, export contracts, USD-linked pricing.

## 7. Things the tool must not do

- Do not treat Egyptian conditions as a reason to redefine EBITDA, net debt or working capital.
- Do not hard-code an assumed future exchange rate. FX paths are scenario inputs supplied by the user.
- Do not treat an EGX IPO as a likely exit by default. That is a judgement for the user, not the tool.
