import fs from 'node:fs';
import vm from 'node:vm';

const read = path => fs.readFileSync(path, 'utf8');
const load = (path, key) => {
  const sandbox = {window: {}};
  vm.runInNewContext(read(path), sandbox, {filename: path});
  return sandbox.window[key];
};
const assert = (ok, message) => { if (!ok) throw new Error(message); };
const close = (a, b, tolerance = 0.02) => Math.abs(a - b) <= tolerance;

const summary = load('data/summary.js', 'LG_SUMMARY');
const behavior = load('data/behavior.js', 'LG_BEHAVIOR');
const history = load('data/history_summary.js', 'LG_HISTORY');
const premium = load('data/premium_summary.js', 'LG_PREMIUM');
const exportData = load('data/export_aggregate.js', 'LG_EXPORT');
const html = read('index.html');
const publicAssets = [read('data/summary.js'), read('data/behavior.js'), read('data/history_summary.js'), read('data/premium_summary.js'), read('data/export_aggregate.js')].join('\n');

assert(summary.meta.privacy_mode === 'aggregate_only', 'Summary is not marked aggregate-only');
assert(summary.meta.customer_codes === 315757, '2025 customer total does not match audited source');
assert(summary.channels.reduce((n, c) => n + summary.channel_metrics[c].customers, 0) === 315757, 'Channel customer totals do not reconcile');
for (const channel of summary.channels) {
  const stores = Object.values(summary.store_metrics[channel]);
  assert(stores.reduce((n, x) => n + x.customers, 0) === summary.channel_metrics[channel].customers, `${channel}: store customer totals do not reconcile`);
  assert(close(stores.reduce((n, x) => n + x.value, 0), summary.channel_metrics[channel].value), `${channel}: store value totals do not reconcile`);
}
const cross = history.cross_period;
assert(history[2022].min_date_text === '01-01-2022' && history[2022].max_date_text === '31-12-2022', '2022 coverage is incorrect');
assert(history[2023].min_date_text === '01-01-2023' && history[2023].max_date_text === '31-12-2023', '2023 coverage is incorrect');
assert(history[2022].identifiable_customer_codes === 273416, '2022 customer total is incorrect');
assert(history[2023].identifiable_customer_codes === 283695, '2023 customer total is incorrect');
assert(cross.distinct_codes === 1004604, 'Four-year distinct-code total is incorrect');
assert(cross.exact_code_overlap_all_four === 3856, 'All-four-year overlap is incorrect');
assert(cross.overlap_2022_2023 === 34947, '2022→2023 overlap is incorrect');
assert(cross.overlap_2023_2024 === 32454, '2023→2024 overlap is incorrect');
assert(cross.overlap_2024_2025 === 34235, '2024→2025 overlap is incorrect');
const cohortTotal = Object.values(cross.cohorts_by_year_presence).reduce((n, value) => n + value, 0);
assert(cohortTotal === cross.distinct_codes && cross.cohort_total === cross.distinct_codes, 'Four-year customer-code cohorts do not reconcile');
assert(history.overlap_qa.matching_invoice_interactions === 5727, 'June 2023 overlap reconciliation changed');
assert(premium.meta.privacy_mode === 'aggregate_only', 'Premiumisation dataset is not marked aggregate-only');
assert(premium.meta.coverage_start === '2022-01-01' && premium.meta.coverage_end === '2025-12-31', 'Premiumisation coverage is incorrect');
assert(premium.national_columns.join('|') === 'year|channel|family|total_units|total_value|premium_units|premium_value', 'Premiumisation national schema changed unexpectedly');
assert(premium.detail_columns.join('|') === 'year|city|channel|family|total_units|total_value|premium_units|premium_value', 'Premiumisation detail schema changed unexpectedly');
assert(premium.national_rows.length > 0 && premium.detail_rows.length > 0, 'Premiumisation aggregates are empty');
assert(premium.meta.detail_value_coverage_pct > 0 && premium.meta.detail_value_coverage_pct <= 100, 'Premiumisation detail coverage is invalid');
for (const row of [...premium.national_rows, ...premium.detail_rows]) {
  const offset = row.length === 7 ? 3 : 4;
  assert(row[0] >= 2022 && row[0] <= 2025, 'Premiumisation row has an invalid year');
  assert(row[offset] >= 0 && row[offset + 1] >= 0 && row[offset + 2] >= 0 && row[offset + 3] >= 0, 'Premiumisation row has an invalid negative metric');
  assert(row[offset + 2] <= row[offset] + 0.001, 'Premium units exceed core units');
  assert(row[offset + 3] <= row[offset + 1] + 0.02, 'Premium value exceeds core value');
}
for (const year of [2022, 2023, 2024, 2025]) {
  const totals = premium.national_rows.filter(row => row[0] === year).reduce((a, row) => a.map((value, index) => value + row[index + 3]), [0, 0, 0, 0]);
  const source = premium.meta.source_stats[String(year)];
  assert(close(totals[0], source.eligible_core_units, 0.001), `${year}: premium core units do not reconcile`);
  assert(close(totals[1], source.eligible_core_value, 0.02), `${year}: premium core value does not reconcile`);
  assert(close(totals[2], source.premium_units, 0.001), `${year}: premium units do not reconcile`);
  assert(close(totals[3], source.premium_value, 0.02), `${year}: premium value does not reconcile`);
}
assert(Array.isArray(behavior) && behavior.length === 4707, 'Behavior dataset is incomplete');
const behaviorMrp = behavior.reduce((n, row) => n + row.mrp, 0);
const behaviorSales = behavior.reduce((n, row) => n + row.sales, 0);
assert(behaviorMrp >= behaviorSales && behaviorMrp / behaviorSales < 2, 'Aggregate MRP is implausible relative to realised value');
for (const row of behavior) {
  const bandUnits = row.full + row.d05 + row.d510 + row.d1020 + row.d20;
  assert(close(bandUnits, row.units, 0.001), 'Behavior discount-band units do not reconcile');
  assert(row.customers >= 0 && row.units >= 0 && row.mrp >= 0, 'Behavior row has an invalid negative count/value');
}
assert(exportData.meta.privacy_mode === 'aggregate_only', 'Export dataset is not marked aggregate-only');
assert(exportData.meta.minimum_customer_threshold === 10, 'Export privacy threshold is not 10 customers');
assert(exportData.columns.join('|') === 'date|city|store|channel|product_family|transaction_lines|invoice_interactions|customer_interactions|net_units|net_value_inr', 'Export schema changed unexpectedly');
assert(exportData.rows.length > 0, 'Export dataset is empty');
for (const row of exportData.rows) {
  assert(row.length === exportData.columns.length, 'Export row does not match schema');
  assert(/^20(22|23|24|25)-\d{2}-\d{2}$/.test(row[0]), `Export row has invalid date: ${row[0]}`);
  assert(row[7] >= exportData.meta.minimum_customer_threshold, 'Low-customer export cell escaped suppression');
  assert(row[5] >= 0 && row[6] >= 0 && row[7] >= 0, 'Export row has an invalid interaction count');
}
const exportLines = exportData.rows.reduce((n, row) => n + row[5], 0);
const exportUnits = exportData.rows.reduce((n, row) => n + row[8], 0);
const exportValue = exportData.rows.reduce((n, row) => n + row[9], 0);
assert(exportLines === exportData.meta.published.lines, 'Published export lines do not reconcile');
assert(close(exportUnits, exportData.meta.published.units, 0.02), 'Published export units do not reconcile');
assert(close(exportValue, exportData.meta.published.value, 0.02), 'Published export value does not reconcile');
assert(exportData.meta.published_value_coverage_pct > 0 && exportData.meta.published_value_coverage_pct <= 100, 'Export value coverage is invalid');
assert(!exportData.columns.some(name => /customer_(name|code)|phone|email|executive/i.test(name)), 'Identifying field exists in export schema');
assert(!/CUS[-_ ]?\d{4,}|Custt_/i.test(publicAssets), 'Possible customer identifier found in public aggregate assets');
assert(!/Customer Explorer|Marketing Export/.test(html.match(/<div class="nav">[\s\S]*?<\/div>/)?.[0] || ''), 'Customer-level navigation remains public');
assert(html.includes('Public aggregate-only build'), 'Public privacy statement is missing');
assert(html.includes('Data Export Centre') && html.includes('fewer than <b>10 identifiable customers</b>'), 'Public export navigation or privacy rule is missing');
assert(html.includes('Premiumisation Intelligence') && html.includes('iPhone Pro/Pro Max'), 'Premiumisation navigation or definition is missing');
assert(html.includes('1 Jan 2022–31 Dec 2025') && html.includes('4 full calendar years'), 'Four-year source coverage is not visible');
assert(html.includes('Published 27 Aug 2026'), 'Dashboard publication date is missing');
for (const label of ['Daily MTD','Weekly','QTD','YoY','Trajectory','Customer']) assert(html.includes(`>${label}</a>`), `${label} suite navigation link is missing`);
assert(html.indexOf('.mobileNav{display:none}') < html.indexOf('@media(max-width:800px)'), 'Mobile navigation base rule overrides its responsive rule');
assert(!/Two-Year Customer Intelligence|Three-Period Customer Intelligence|2024–2025 LIFEGRAPH/.test(html), 'Stale legacy audit labels remain in the dashboard');
for (const path of ['data/summary.js', 'data/behavior.js', 'data/history_summary.js', 'data/premium_summary.js', 'data/export_aggregate.js']) assert(fs.existsSync(path), `${path} is missing`);

console.log(`Validation passed: ${summary.meta.customer_codes.toLocaleString('en-IN')} customers, ${behavior.length.toLocaleString('en-IN')} behavior groups, ${exportData.rows.length.toLocaleString('en-IN')} privacy-safe export cells.`);
