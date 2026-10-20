/** One local gate. Reuse existing tests; require approved cases to actually pass, not merely exist. */
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { performance } = require('node:perf_hooks');

function assertBaseline(baseline) {
  if (baseline.schema !== 1 || !Array.isArray(baseline.suites) || !baseline.suites.length || !Array.isArray(baseline.invariants) || !baseline.invariants.length) throw Error('Invalid BWork baseline');
  const ids = new Set();
  for (const item of baseline.invariants) {
    if (!item.id || ids.has(item.id) || !item.test || !item.description || !baseline.suites.includes(item.suite)) throw Error(`Invalid/duplicate invariant: ${item.id}`);
    ids.add(item.id);
  }
}
function assertExecuted(baseline, results) {
  assertBaseline(baseline);
  const missing = [];
  for (const item of baseline.invariants) {
    const result = results[item.suite];
    const lines = (result?.stdout ?? '').split(/\r?\n/);
    const executed = lines.some(line => {
      const match = /^(ok|not ok) \d+ - (.*?)(?: # (SKIP|TODO)\b.*)?$/.exec(line);
      return match && match[1] === 'ok' && match[2] === item.test && !match[3];
    });
    if (!result || result.status !== 0 || result.error || result.signal || !executed) missing.push(item.id);
  }
  if (missing.length) throw Error(`Approved tests missing, skipped or failing: ${missing.join(', ')}`);
}
function nodeArgs(command) {
  if (typeof command !== 'string' || !command.startsWith('node ')) throw Error('Gate expects an existing single Node test command');
  const args = command.slice(5).trim().split(/\s+/);
  if (!args.includes('--test') || args.some(arg => !/^[a-zA-Z0-9_./:@*=\-]+$/.test(arg) || arg.startsWith('--test-reporter'))) throw Error('Unsupported test command; review the gate explicitly');
  return ['--test-reporter=tap', ...args];
}
function main() {
  const root = path.resolve(__dirname, '..'); const started = performance.now();
  const baseline = JSON.parse(fs.readFileSync(path.join(__dirname, 'bwork-baseline.json'), 'utf8'));
  const scripts = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).scripts;
  assertBaseline(baseline);
  const typecheck = spawnSync(process.execPath, ['node_modules/typescript/bin/tsc', '--project', 'tsconfig.bwork.json', '--pretty', 'false'], { cwd: root, stdio: 'inherit' });
  if (typecheck.error || typecheck.signal || typecheck.status !== 0) throw Error('BWork typecheck failed');
  const results = {};
  for (const suite of baseline.suites) {
    const result = spawnSync(process.execPath, nodeArgs(scripts[suite]), { cwd: root, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024, env: { ...process.env, BWORK_ARCHIVE_BENCH: '0' } });
    results[suite] = result;
    if (result.error || result.signal || result.status !== 0) {
      process.stderr.write(`${result.stdout ?? ''}${result.stderr ?? ''}`);
      throw Error(`${suite} failed: ${result.error?.message ?? result.signal ?? result.status}`);
    }
    console.log(`${suite}: ${result.stdout.split(/\r?\n/).filter(line => /^# (tests|pass|fail|skipped) /.test(line)).join(' | ')}`);
  }
  assertExecuted(baseline, results);
  console.log(`BWORK BASELINE PASS: ${baseline.invariants.length} approved behaviors; ${((performance.now() - started) / 1000).toFixed(2)}s including typecheck.`);
  for (const gap of baseline.openGaps ?? []) console.log(`KNOWN GAP (not approved behavior): ${gap.id} — ${gap.description}`);
}
module.exports = { assertBaseline, assertExecuted, nodeArgs };
if (require.main === module) { try { main(); } catch (error) { console.error(`BWORK GATE FAILED: ${error.message}`); process.exitCode = 1; } }
