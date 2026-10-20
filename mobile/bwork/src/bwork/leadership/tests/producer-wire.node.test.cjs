/** Executes the production Python serializer with synthetic sources, not Odoo/ACL proof. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { existsSync } = require('node:fs');
const { dirname, resolve } = require('node:path');
const { spawnSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');

test('real backend serializer output is accepted by the strict native report decoder', async () => {
  const bundledPython = resolve(dirname(process.execPath), '../../python/python.exe');
  const python = process.env.BWORK_PYTHON || (existsSync(bundledPython) ? bundledPython : process.platform === 'win32' ? 'python' : 'python3');
  const fixture = resolve(__dirname, '../../../../../../custom_addons/baseer_bwork_dashboard/tests/wire_fixture.py');
  const result = spawnSync(python, [fixture], { encoding: 'utf8', timeout: 20000, maxBuffer: 1048576 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  const { reportResponse } = await import(pathToFileURL(resolve(__dirname, '../validation.ts')).href);
  const options = { api_version: 2, leadership_version: 1, can_view: true, companies: [{ id: 7, name: 'Synthetic wire fixture' }], max_companies: 10 };
  const report = reportResponse(JSON.parse(result.stdout), { companyId: 7, month: '2026-10', period: 'month' }, options);
  assert.equal(report.calendar.days.length, 31);
  assert.equal(report.overview.current_month.completed_days, 18);
  assert.equal(report.overview.sales.value, '3000.00');
  assert.equal(report.calendar.weekdays.length, 7);
});
