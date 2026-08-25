# Customer Intelligence metric dictionary

This public dashboard contains aggregate data only. Customer names, customer codes, phone numbers, email addresses, and row-level customer exports are not published.

## Source and audit rules

- Coverage: full calendar years 2024 and 2025.
- Cancelled transactions are excluded before all calculations.
- Duplicate removal: exact equality across all 53 source columns. This intentionally avoids the earlier, over-broad transaction key that could remove valid multi-line sales.
- Net customer-linked value: sum of `Total` after the exclusions above, including valid returns as negative value.
- Cross-year identity: exact Customer Code only. Unmatched codes are not automatically called new customers or churned customers.

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
