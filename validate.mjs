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
const exportData = load('data/export_aggregate.js', 'LG_EXPORT');
const html = read('index.html');
const publicAssets = [read('data/summary.js'), read('data/behavior.js'), read('data/history_summary.js'), read('data/export_aggregate.js')].join('\n');

assert(summary.meta.privacy_mode === 'aggregate_only', 'Summary is not marked aggregate-only');
assert(summary.meta.customer_codes === 315757, '2025 customer total does not match audited source');
assert(summary.channels.reduce((n, c) => n + summary.channel_metrics[c].customers, 0) === 315757, 'Channel customer totals do not reconcile');
for (const channel of summary.channels) {
  const stores = Object.values(summary.store_metrics[channel]);
  assert(stores.reduce((n, x) => n + x.customers, 0) === summary.channel_metrics[channel].customers, `${channel}: store customer totals do not reconcile`);
  assert(close(stores.reduce((n, x) => n + x.value, 0), summary.channel_metrics[channel].value), `${channel}: store value totals do not reconcile`);
}
const cross = history.cross_period;
assert(history[2023].min_date_text === '25-06-2023' && history[2023].max_date_text === '31-12-2023', '2023 partial-period coverage is incorrect');
assert(history[2023].identifiable_customer_codes === 156584, '2023 customer total is incorrect');
assert(cross.distinct_codes === 686211, 'Three-period distinct-code total is incorrect');
assert(cross.exact_code_overlap_all_three === 6227, 'All-three-period overlap is incorrect');
assert(cross.overlap_2023_2024 === 20578, '2023→2024 overlap is incorrect');
assert(cross.overlap_2024_2025 === 34235, '2024→2025 overlap is incorrect');
const cohortTotal = ['2023_only','2024_only','2025_only','2023_2024_only','2023_2025_only','2024_2025_only','exact_code_overlap_all_three'].reduce((n, key) => n + cross[key], 0);
assert(cohortTotal === cross.distinct_codes, 'Three-period customer-code cohorts do not reconcile');
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
  assert(/^20(23|24|25)-\d{2}-\d{2}$/.test(row[0]), `Export row has invalid date: ${row[0]}`);
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
assert(html.includes('25 Jun 2023–31 Dec 2025') && html.includes('2023 partial period'), 'Partial-period source coverage is not visible');
assert(html.includes('Published 26 Aug 2026'), 'Dashboard publication date is missing');
for (const label of ['Daily MTD','Weekly','QTD','YoY','Trajectory','Customer']) assert(html.includes(`>${label}</a>`), `${label} suite navigation link is missing`);
assert(html.indexOf('.mobileNav{display:none}') < html.indexOf('@media(max-width:800px)'), 'Mobile navigation base rule overrides its responsive rule');
assert(!/34,237|244,922|281,520|1,384\.32|22,904|Two-Year Customer Intelligence|2024–2025 LIFEGRAPH/.test(html), 'Stale legacy audit labels or totals remain in the dashboard');
for (const path of ['data/summary.js', 'data/behavior.js', 'data/history_summary.js', 'data/export_aggregate.js']) assert(fs.existsSync(path), `${path} is missing`);

console.log(`Validation passed: ${summary.meta.customer_codes.toLocaleString('en-IN')} customers, ${behavior.length.toLocaleString('en-IN')} behavior groups, ${exportData.rows.length.toLocaleString('en-IN')} privacy-safe export cells.`);
