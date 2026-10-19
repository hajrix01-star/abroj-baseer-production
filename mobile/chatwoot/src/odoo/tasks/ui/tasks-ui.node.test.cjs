const { test } = require('node:test');
const assert = require('node:assert/strict');
const { harness, nodes, one, byId, button, text } = require('./tasks-harness.cjs');
const waiting = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
test('task-only users see all authorized companies by default and filters are global server queries', async () => {
  const app = harness(); try {
    await app.flush(); assert.deepEqual(JSON.parse(JSON.stringify(app.calls.find(call => call[0] === 'list')[1])), { view: 'mine', state: 'open' });
    assert.equal(one(app.render(), 'CompanySelector').permission, 'task_view');
    await app.act(() => one(app.render(), 'CompanySelector').onSelect(1));
    assert.equal(app.calls.filter(call => call[0] === 'list').at(-1)[1].companyId, 1);
    await app.act(() => byId(app.render(), 'tasks-view-created').onPress());
    assert.equal(app.calls.filter(call => call[0] === 'list').at(-1)[1].view, 'created');
    await app.act(() => byId(app.render(), 'tasks-state-cancelled').onPress());
    assert.equal(app.calls.filter(call => call[0] === 'list').at(-1)[1].state, 'cancelled');
  } finally { await app.unmount(); }
});
test('one company is automatic, hidden in browsing and creation, with explicit operation company', async () => {
  const app = harness(); app.options.companies = [{ id: 1, name: 'Only company' }]; app.props.identity.company_ids = [1];
  try { await app.flush(); assert.equal(nodes(app.render()).some(node => node.type === 'CompanySelector'), false);
    assert.equal(app.calls.find(call => call[0] === 'list')[1].companyId, 1);
    await app.act(() => button(app.render(), 'New task').onPress());
    assert.equal(nodes(app.render()).some(node => node.type === 'CompanySelector'), false);
    await app.act(() => byId(app.render(), 'task-title').onChangeText('Repair AC'));
    await app.act(() => byId(app.render(), 'task-assignee-picker').onPress());
    await app.act(() => byId(app.render(), 'task-assignee-11').onPress());
    await app.act(() => button(app.render(), 'Assign task').onPress());
    assert.equal(app.calls.find(call => call[0] === 'create')[1].company_id, 1);
    assert.equal(app.calls.find(call => call[0] === 'create')[1].assignee_id, 11);
  } finally { await app.unmount(); }
});
test('multi-company creation never treats all as a company and direct completion uses row company and canonical result', async () => {
  const app = harness(); try { await app.flush(); await app.act(() => button(app.render(), 'New task').onPress());
    assert.equal(button(app.render(), 'Assign task').disabled, true);
    assert.equal(byId(app.render(), 'task-assignee-picker').disabled, true);
    await app.act(() => button(app.render(), 'Back').onPress());
    await app.act(() => byId(app.render(), 'task-row-2-7').onPress());
    assert.deepEqual(app.calls.find(call => call[0] === 'detail'), ['detail', 7, 2]);
    await app.act(() => byId(app.render(), 'task-note').onChangeText('Repaired'));
    const complete = button(app.render(), 'Mark completed').onPress;
    await app.act(() => { complete(); complete(); });
    assert.equal(app.calls.filter(call => call[0] === 'transition').length, 1);
    const transition = app.calls.find(call => call[0] === 'transition'); assert.equal(transition[1].company_id, 2); assert.equal(transition[2].action, 'done');
    assert.match(text(app.render()), /Canonical actor/); assert.match(text(app.render()), /Repaired/);
  } finally { await app.unmount(); }
});
test('hidden workspace retains draft but stale callbacks cannot read/write or show modal content', async () => {
  const app = harness(); try { await app.flush(); await app.act(() => button(app.render(), 'New task').onPress());
    await app.act(() => one(app.render(), 'CompanySelector').onSelect(1));
    await app.act(() => byId(app.render(), 'task-title').onChangeText('Retained draft'));
    const pick = byId(app.render(), 'task-assignee-picker').onPress;
    app.props.presented = false; await app.flush(); const before = app.calls.filter(call => call[0] !== 'cancelReads').length;
    await app.act(() => pick()); assert.ok(byId(app.render(), 'tasks-privacy-cover'));
    assert.equal(nodes(app.render()).some(node => node.type === 'Sheet'), false);
    assert.equal(app.calls.filter(call => call[0] !== 'cancelReads').length, before);
    app.props.presented = true; await app.flush(); assert.equal(byId(app.render(), 'task-title').value, 'Retained draft');
    assert.equal(app.calls.some(call => ['create', 'transition', 'retry'].includes(call[0])), false);
    app.props.identity = { ...app.props.identity, user_id: 10 }; app.props.scopeKey = 'another-user'; await app.flush();
    assert.equal(nodes(app.render()).some(node => node.props.testID === 'task-title'), false);
  } finally { await app.unmount(); }
});
test('interrupted GET resumes once after presentation and lost writes expose only manual retry', async () => {
  const app = harness(), delayed = waiting(); let attempts = 0;
  app.engine.list = async query => { app.calls.push(['list', query]); if (++attempts === 1) return delayed.promise; return { tasks: [app.task()], next_before_id: null }; };
  try { await app.flush(); app.props.presented = false; await app.flush();
    await app.act(() => delayed.reject({ code: 'stale' })); assert.equal(attempts, 1);
    app.props.presented = true; await app.flush(); assert.equal(attempts, 2);
    app.props.presented = false; await app.flush(); app.props.presented = true; await app.flush(); assert.equal(attempts, 2);
    app.engine.pending = async () => [{ uuid: 'saved-uuid', kind: 'transition', companyId: 2, taskId: 7, createdAt: 1 }];
    await app.act(() => one(app.render(), 'IconButton', props => props.label === 'Refresh').onPress());
    assert.equal(app.calls.some(call => call[0] === 'retry'), false);
    await app.act(() => button(app.render(), 'Retry saved attempt · 7').onPress());
    assert.deepEqual(app.calls.filter(call => call[0] === 'retry'), [['retry', 'saved-uuid']]);
  } finally { await app.unmount(); }
});
test('view-only and no-view users gain no management or chat capability', async () => {
  for (const access of ['view', 'none']) { const app = harness(); app.props.identity.permissions.task_manage = false; app.options.can_manage = false;
    if (access === 'none') app.props.identity.permissions.task_view = false;
    try { await app.flush(); assert.equal(nodes(app.render()).some(node => node.type === 'Button' && node.props.title === 'New task'), false);
      if (access === 'none') assert.equal(app.calls.some(call => call[0] === 'options' || call[0] === 'list'), false);
      assert.equal(app.props.identity.permissions.chat_view, false);
    } finally { await app.unmount(); }
  }
});
test('resumed options verify silently before stale reads and actions, including server management revocation', async () => {
  const app = harness(); try { await app.flush(); await app.act(() => byId(app.render(), 'task-row-2-7').onPress());
    const oldComplete = button(app.render(), 'Mark completed').onPress;
    app.props.presented = false; await app.flush();
    const delayed = waiting(); app.engine.options = async () => { app.calls.push(['options']); return delayed.promise; };
    app.props.presented = true; await app.flush();
    assert.equal(button(app.render(), 'Mark completed').disabled, true);
    const before = app.calls.filter(call => ['list', 'detail', 'transition'].includes(call[0])).length;
    await app.act(() => oldComplete()); assert.equal(app.calls.filter(call => ['list', 'detail', 'transition'].includes(call[0])).length, before);
    await app.act(() => delayed.resolve({ ...app.options, can_manage: false }));
    assert.equal(nodes(app.render()).some(node => node.type === 'Button' && node.props.title === 'Mark completed'), false);
    assert.ok(byId(app.render(), 'task-detail')); assert.equal(app.calls.some(call => call[0] === 'transition'), false);
  } finally { await app.unmount(); }
});
test('interrupted first options recover once rather than leaving a permanent loading state', async () => {
  const app = harness(), delayed = waiting(); let attempts = 0;
  app.engine.options = async () => { app.calls.push(['options']); if (++attempts === 1) return delayed.promise; return app.options; };
  try { await app.flush(); app.props.presented = false; await app.flush(); app.props.presented = true; await app.flush();
    await app.act(() => delayed.reject({ code: 'stale' })); assert.equal(attempts, 2); assert.ok(byId(app.render(), 'task-row-2-7'));
  } finally { await app.unmount(); }
});
test('an unresolved create never traps Back or blocks an unrelated same-company task', async () => {
  const app = harness(); app.options.companies = [{ id: 1, name: 'Only company' }]; app.props.identity.company_ids = [1];
  app.engine.pending = async () => [{ uuid: 'unresolved-create', kind: 'create', companyId: 1, createdAt: 1 }];
  try { await app.flush(); await app.act(() => button(app.render(), 'New task').onPress());
    assert.equal(byId(app.render(), 'task-title').editable, true);
    await app.act(() => button(app.render(), 'Back').onPress());
    assert.equal(nodes(app.render()).some(node => node.props.testID === 'task-composer'), false);
    await app.act(() => button(app.render(), 'New task').onPress());
    await app.act(() => byId(app.render(), 'task-title').onChangeText('An unrelated repair'));
    await app.act(() => byId(app.render(), 'task-assignee-picker').onPress()); await app.act(() => byId(app.render(), 'task-assignee-11').onPress());
    assert.equal(button(app.render(), 'Assign task').disabled, false);
    await app.act(() => button(app.render(), 'Assign task').onPress());
    assert.equal(app.calls.filter(call => call[0] === 'create').length, 1);
    assert.equal(app.calls.some(call => call[0] === 'retry'), false, 'the unknown original was never automatically retried');
  } finally { await app.unmount(); }
});
test('known options denial clears old private content and only fresh verified options can restore the section', async () => {
  const app = harness(); try { await app.flush(); assert.ok(byId(app.render(), 'task-row-2-7'));
    const validOptions = app.engine.options;
    app.engine.options = async () => { app.calls.push(['options']); throw { code: 'forbidden', status: 403 }; };
    await app.act(() => one(app.render(), 'IconButton', props => props.label === 'Refresh').onPress());
    assert.equal(nodes(app.render()).some(node => node.props.testID?.startsWith('task-row-')), false);
    assert.equal(nodes(app.render()).some(node => node.type === 'CompanySelector'), false);
    assert.equal(text(app.render()).includes('Task 7'), false);
    const before = app.calls.filter(call => call[0] !== 'cancelReads').length;
    await app.flush(); assert.equal(app.calls.filter(call => call[0] !== 'cancelReads').length, before, 'known denial is not retried automatically');
    app.props.presented = false; await app.flush();
    const retry = button(app.render(), 'Try again').onPress;
    await app.act(retry); assert.equal(app.calls.filter(call => call[0] !== 'cancelReads').length, before, 'hidden retry cannot request authority');
    app.engine.options = validOptions; app.props.presented = true; await app.flush(); assert.ok(byId(app.render(), 'task-row-2-7'));
  } finally { await app.unmount(); }
});
test('known paged-list denial removes already loaded rows, not just their action buttons', async () => {
  const app = harness(); app.engine.list = async query => { app.calls.push(['list', query]); if (query.beforeId) throw { code: 'forbidden', status: 403 }; return { tasks: [app.task()], next_before_id: 6 }; };
  try { await app.flush(); assert.ok(byId(app.render(), 'task-row-2-7'));
    await app.act(() => button(app.render(), 'Load more').onPress());
    assert.equal(nodes(app.render()).some(node => node.props.testID === 'tasks-list'), false);
    assert.equal(text(app.render()).includes('Task 7'), false); assert.equal(nodes(app.render()).some(node => node.type === 'CompanySelector'), false);
    await app.act(() => button(app.render(), 'Try again').onPress()); assert.ok(byId(app.render(), 'task-row-2-7'));
  } finally { await app.unmount(); }
});
test('known detail denial clears the cached detail and any late callback cannot restore it', async () => {
  const app = harness(); try { await app.flush(); await app.act(() => byId(app.render(), 'task-row-2-7').onPress()); assert.ok(byId(app.render(), 'task-detail'));
    const oldComplete = button(app.render(), 'Mark completed').onPress;
    app.engine.transition = async () => { throw { code: 'revision_conflict' }; };
    await app.act(oldComplete);
    app.engine.detail = async () => { throw { code: 'forbidden', status: 403 }; };
    await app.act(() => button(app.render(), 'Refresh').onPress());
    assert.equal(nodes(app.render()).some(node => node.props.testID === 'task-detail'), false); assert.equal(text(app.render()).includes('Repair equipment'), false);
    const before = app.calls.length; await app.act(oldComplete); assert.equal(app.calls.length, before, 'unmounted detail cannot act again');
    await app.act(() => button(app.render(), 'Try again').onPress()); assert.equal(nodes(app.render()).some(node => node.props.testID === 'task-detail'), false);
  } finally { await app.unmount(); }
});
test('known assignee denial clears the entire composer and its private draft rather than hiding a modal only', async () => {
  const app = harness(); try { await app.flush(); await app.act(() => button(app.render(), 'New task').onPress()); await app.act(() => one(app.render(), 'CompanySelector').onSelect(1));
    await app.act(() => byId(app.render(), 'task-title').onChangeText('Private equipment repair draft'));
    app.engine.assignees = async () => { throw { code: 'forbidden', status: 403 }; };
    await app.act(() => byId(app.render(), 'task-assignee-picker').onPress());
    assert.equal(nodes(app.render()).some(node => node.props.testID === 'task-composer'), false); assert.equal(nodes(app.render()).some(node => node.type === 'Sheet'), false);
    assert.equal(JSON.stringify(app.render()).includes('Private equipment repair draft'), false);
    await app.act(() => button(app.render(), 'Try again').onPress());
    assert.equal(nodes(app.render()).some(node => node.props.testID === 'task-composer'), false);
    await app.act(() => button(app.render(), 'New task').onPress()); assert.equal(byId(app.render(), 'task-title').value, '');
  } finally { await app.unmount(); }
});
