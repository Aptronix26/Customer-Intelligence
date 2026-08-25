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
const html = read('index.html');
const publicAssets = [read('data/summary.js'), read('data/behavior.js')].join('\n');

assert(summary.meta.privacy_mode === 'aggregate_only', 'Summary is not marked aggregate-only');
assert(summary.meta.customer_codes === 315757, '2025 customer total does not match audited source');
assert(summary.channels.reduce((n, c) => n + summary.channel_metrics[c].customers, 0) === 315757, 'Channel customer totals do not reconcile');
for (const channel of summary.channels) {
  const stores = Object.values(summary.store_metrics[channel]);
  assert(stores.reduce((n, x) => n + x.customers, 0) === summary.channel_metrics[channel].customers, `${channel}: store customer totals do not reconcile`);
  assert(close(stores.reduce((n, x) => n + x.value, 0), summary.channel_metrics[channel].value), `${channel}: store value totals do not reconcile`);
}
assert(history.cross_year.distinct_codes === 560681, 'Two-year distinct-code total is incorrect');
assert(history.cross_year.exact_code_overlap === 34235, 'Cross-year overlap is incorrect');
assert(history.cross_year['2024_only'] === 244924, '2024-only total is incorrect');
assert(history.cross_year['2025_first_seen_by_code'] === 281522, '2025 first-seen total is incorrect');
assert(Array.isArray(behavior) && behavior.length === 4707, 'Behavior dataset is incomplete');
const behaviorMrp = behavior.reduce((n, row) => n + row.mrp, 0);
const behaviorSales = behavior.reduce((n, row) => n + row.sales, 0);
assert(behaviorMrp >= behaviorSales && behaviorMrp / behaviorSales < 2, 'Aggregate MRP is implausible relative to realised value');
for (const row of behavior) {
  const bandUnits = row.full + row.d05 + row.d510 + row.d1020 + row.d20;
  assert(close(bandUnits, row.units, 0.001), 'Behavior discount-band units do not reconcile');
  assert(row.customers >= 0 && row.units >= 0 && row.mrp >= 0, 'Behavior row has an invalid negative count/value');
}
assert(!/CUS[-_ ]?\d{4,}|Custt_/i.test(publicAssets), 'Possible customer identifier found in public aggregate assets');
assert(!/Customer Explorer|Marketing Export/.test(html.match(/<div class="nav">[\s\S]*?<\/div>/)?.[0] || ''), 'Customer-level navigation remains public');
assert(html.includes('Public aggregate-only build'), 'Public privacy statement is missing');
assert(html.indexOf('.mobileNav{display:none}') < html.indexOf('@media(max-width:800px)'), 'Mobile navigation base rule overrides its responsive rule');
assert(!/34,237|244,922|281,520|1,384\.32|22,904/.test(html), 'Stale legacy audit totals remain in the dashboard');
for (const path of ['data/summary.js', 'data/behavior.js', 'data/history_summary.js']) assert(fs.existsSync(path), `${path} is missing`);

console.log(`Validation passed: ${summary.meta.customer_codes.toLocaleString('en-IN')} customers, ${behavior.length.toLocaleString('en-IN')} behavior groups, aggregate-only public build.`);
