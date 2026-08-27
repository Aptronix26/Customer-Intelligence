# Customer Intelligence metric dictionary

This public dashboard contains aggregate data only. Customer names, customer codes, phone numbers, email addresses, and row-level customer exports are not published.

## Source and audit rules

- Coverage: full calendar years 2022, 2023, 2024 and 2025. Two half-year workbooks form 2022. For 2023, the Jan–Jun source is authoritative through 30 June and the earlier historical source is used from 1 July onward.
- Cancelled transactions are excluded before all calculations.
- Duplicate removal: exact equality across the canonical A:AZ transaction columns within each calendar year. This intentionally avoids an over-broad transaction key that could remove valid multi-line sales.
- Net customer-linked value: sum of `Total` after the exclusions above, including valid returns as negative value.
- June 2023 overlap: both supplied files contain 25–30 June. All 5,727 invoice interactions in that window match; the earlier historical file's June rows are excluded so no activity is double-counted.
- Cross-period identity: exact Customer Code only across full-year 2022–2025 sources. Unmatched codes are not automatically called new customers or churned customers.
- Four-year cohorts are mutually exclusive by observed year-presence pattern. Their sum must reconcile to the distinct-code union.

## Customer metrics

- Identifiable customers: distinct Customer Codes in the audited source.
- Repeat customer: at least two distinct valid POS invoice numbers.
- Multi-category customer: purchases in at least two core Apple device categories: iPhone, Mac, iPad, Watch, or AirPods.
- One-bill customer: exactly one distinct valid POS invoice number.
- Priority relationship pool: at least three valid POS invoices, or at least two core Apple categories, or net customer-linked value of ₹150,000 or more. This is a transparent business rule, not a predictive score.
- Possible next-category pool: customers without a recorded purchase in that core Apple category.

## Channel and store rules

Each customer belongs to one channel using this priority: Warehouse → SMB → Corporate → E-commerce → Online Executive → Retail Stores. Store metrics use the customer's assigned primary selling point, so channel and store customer totals reconcile without double counting.

## Customer Choice Intelligence

- Includes valid POS rows for core Apple device categories only.
- MRP uses Actual MRP when available, otherwise MRP.
- A price is accepted only when it is a plausible positive line value relative to realised sales and quantity; otherwise realised value is used as a conservative fallback.
- Realised value uses the audited source realised-value field.
- Discount bands are based on effective realised discount from MRP: full price, 0–5%, 5–10%, 10–20%, and above 20%.
- Customer interactions are distinct within each Store × Core LOB × Sub-LOB group. They are not additive across groups; unit and value measures are additive.

## Data Export Centre

- Public export grain: Date × City × Store / Selling Point × Channel × Product Family.
- Filters: supplied date range, city, store / selling point, channel, and product family.
- Report layouts: daily detailed cells, monthly, city, store, channel, or product-family summary.
- Privacy suppression: a granular cell is not written to the public data asset unless it contains at least 10 distinct identifiable Customer Codes. Low-volume store cells are combined into a city rollup, and remaining low-volume city cells into a national rollup. A rollup is published only when it also reaches 10 customers; anything still below the threshold is excluded. The original low-volume cells cannot be recovered in the browser or in a download.
- Transaction lines: valid, de-duplicated customer-linked source rows after cancelled rows are excluded.
- Invoice interactions: distinct Transaction Type + Invoice Number combinations within an original published cell. This is non-additive across cells and is labelled as summed interactions in summary layouts.
- Customer interactions: distinct Customer Codes within an original published cell. This is non-additive across cells and is labelled as summed interactions in summary layouts.
- Net units: signed, additive quantity, including returns.
- Net value: signed, additive source `Total` in INR, including returns.
- CSV and JSON downloads are standards-based. The Excel download is SpreadsheetML XML, which opens directly in Microsoft Excel without embedding a third-party library.
- Public exports contain no customer name, Customer Code, phone number, email address, or sales-executive identifier. Customer-level activation remains a separate private-tool requirement.
