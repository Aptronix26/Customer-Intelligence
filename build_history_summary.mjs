import fs from 'node:fs';
import path from 'node:path';

const audit = JSON.parse(fs.readFileSync('raw_audit_2022_2025.json', 'utf8'));
const periods = audit.periods.map(period => ({
  ...period,
  source_files: period.source_files.map(source => path.basename(source)),
}));
const history = {
  coverage_note: audit.coverage_note,
  2022: periods[0],
  2023: periods[1],
  2024: periods[2],
  2025: periods[3],
  cross_period: audit.cross_period,
  overlap_qa: audit.overlap_qa,
};
fs.mkdirSync('data', {recursive: true});
fs.writeFileSync('data/history_summary.js', `window.LG_HISTORY=${JSON.stringify(history)};`);
