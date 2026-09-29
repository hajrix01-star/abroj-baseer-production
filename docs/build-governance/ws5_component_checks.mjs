import fs from 'node:fs';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';

// Execute production component methods. Owl rendering, native overlay geometry,
// keyboard dispatch and browser focus behavior are verified separately in QA UI.
const path = 'custom_addons/baseer_work_schedule/static/src/time_field.js';
const original = fs.readFileSync(path, 'utf8');
const checks = [];
const result = {
    status: 'running', checks,
    source: path,
    source_sha256: crypto.createHash('sha256').update(original).digest('hex'),
    scope: 'Actual component source with stubbed Owl/usePopover/registry and deferred native record.update. Complements browser acceptance; does not simulate rendered Owl lifecycle or overlay placement.',
};
const check = async (name, fn) => {
    try {
        await fn();
        checks.push({ name, passed: true });
    } catch (error) {
        checks.push({ name, passed: false });
        throw error;
    }
};

function deferred() {
    let resolve, reject;
    const promise = new Promise((r, j) => { resolve = r; reject = j; });
    return { promise, resolve, reject };
}

const registered = new Map();
const registry = { category: () => ({ add(name, spec) { registered.set(name, spec); } }) };
const refs = () => ({ el: { focusCalls: 0, focus() { this.focusCalls++; }, querySelector() { return null; } } });
const usePopover = (Popover, options) => {
    const overlay = {
        isOpen: false, openCalls: 0, closeCalls: 0,
        open(anchor, props) {
            this.anchor = anchor;
            this.openCalls++;
            this.isOpen = true;
            this.component = new Popover();
            this.component.props = props;
            this.component.setup();
        },
        close() {
            if (!this.isOpen) { return; }
            this.isOpen = false;
            this.closeCalls++;
            options.onClose?.();
        },
    };
    return overlay;
};
const source = original.replace(/^\uFEFF/, '').replace(/^import .*;\r?\n/gm, '').replace(/export class /g, 'class ');
const { ScheduleTimeField: Field, ScheduleTimePopover: Picker } = new Function(
    'Component', 'useState', 'useRef', 'useEffect', 'useAutofocus', 'usePopover', 'registry', '_t', 'standardFieldProps',
    source + '\nreturn { ScheduleTimeField, ScheduleTimePopover };',
)(class {}, value => value, refs, () => {}, refs, usePopover, registry, value => value, {});

function fixture(value = '16:00', allowEndOfDay = true, name = 'time_to', readonly = false) {
    const calls = [], requests = [];
    const record = {
        data: { [name]: value },
        update(values) {
            calls.push({ ...values });
            const request = deferred();
            requests.push(request);
            return request.promise.then(() => Object.assign(record.data, values));
        },
    };
    const field = new Field();
    field.props = { record, name, allowEndOfDay, readonly };
    field.setup();
    return { field, record, calls, requests, open() { field.openPicker(); return field.popover.component; } };
}

try {
    await check('registered widget retains native char and endpoint option contract', () => {
        const spec = registered.get('baseer_schedule_time');
        assert.equal(spec.component, Field);
        assert.deepEqual(spec.supportedTypes, ['char']);
        assert.deepEqual(spec.extractProps({ options: { allow_end_of_day: true } }), { allowEndOfDay: true });
        assert.deepEqual(spec.extractProps({ options: {} }), { allowEndOfDay: false });
    });
    const f = fixture('16:23');
    let popup = f.open();
    await check('opening combined picker preloads existing HHMM without a record update', () => {
        assert(popup instanceof Picker);
        assert.equal(popup.value, '16:23');
        assert.equal(f.field.state.open, true);
        assert.equal(f.calls.length, 0);
        assert.equal(f.field.popover.anchor, f.field.triggerRef.el);
    });
    await check('hour and arbitrary minute selection stage locally', () => {
        popup.onOptionClick({ currentTarget: { dataset: { part: 'hour', value: '21' } } });
        popup.onOptionClick({ currentTarget: { dataset: { part: 'minute', value: '07' } } });
        assert.equal(popup.value, '21:07');
        assert.equal(f.record.data.time_to, '16:23');
        assert.deepEqual(f.calls, []);
    });
    popup.cancel();
    await check('Cancel discards draft with no update and invokes native close callback', () => {
        assert.equal(f.field.popover.isOpen, false);
        assert.equal(f.field.state.open, false);
        assert.equal(f.record.data.time_to, '16:23');
        assert.deepEqual(f.calls, []);
    });
    popup = f.open();
    await check('reopening after Cancel restores persisted value rather than abandoned draft', () => assert.equal(popup.value, '16:23'));
    popup.select('hour', '09');
    popup.select('minute', '37');
    const pending = popup.apply();
    await check('Apply sends one exact raw HHMM update and locks popup and trigger immediately', () => {
        assert.deepEqual(f.calls, [{ time_to: '09:37' }]);
        assert.equal(popup.state.busy, true);
        assert.equal(f.field.state.busy, true);
        assert.equal(f.field.popover.isOpen, true);
        assert.equal(f.record.data.time_to, '16:23');
    });
    await popup.apply();
    await f.field.applyValue('05:12');
    popup.select('minute', '58');
    popup.cancel();
    f.field.openPicker();
    await check('pending update ignores duplicate apply, selection, Cancel and trigger reopen', () => {
        assert.equal(f.calls.length, 1);
        assert.equal(popup.value, '09:37');
        assert.equal(f.field.popover.openCalls, 2);
        assert.equal(f.field.popover.closeCalls, 1);
        assert.equal(f.field.popover.isOpen, true);
    });
    f.requests[0].resolve();
    await pending;
    await check('successful native update unlocks both components then closes exactly once', () => {
        assert.equal(f.record.data.time_to, '09:37');
        assert.equal(f.field.value, '09:37');
        assert.equal(f.field.state.busy, false);
        assert.equal(popup.state.busy, false);
        assert.equal(f.field.popover.closeCalls, 2);
        assert.equal(f.field.popover.isOpen, false);
    });

    const failure = fixture('11:42');
    const failedPopup = failure.open();
    failedPopup.select('minute', '19');
    const failedApply = failedPopup.apply();
    failure.requests[0].reject(new Error('native onchange error'));
    await assert.rejects(failedApply, /native onchange error/);
    await check('rejected native update unlocks both components and preserves unsaved draft', () => {
        assert.equal(failedPopup.state.busy, false);
        assert.equal(failure.field.state.busy, false);
        assert.equal(failure.field.popover.isOpen, true);
        assert.equal(failedPopup.value, '11:19');
        assert.equal(failure.record.data.time_to, '11:42');
    });
    const retry = failedPopup.apply();
    failure.requests[1].resolve();
    await retry;
    await check('user can retry once after native error with the same staged value', () => {
        assert.deepEqual(failure.calls, [{ time_to: '11:19' }, { time_to: '11:19' }]);
        assert.equal(failure.record.data.time_to, '11:19');
        assert.equal(failure.field.popover.isOpen, false);
    });

    const endpoint = fixture('23:59');
    let endPopup = endpoint.open();
    await check('endpoint hour list uses Western padded 00 through24 with all60 minutes', () => {
        assert.equal(endPopup.hours.length, 25);
        assert.deepEqual(endPopup.hours.slice(0, 3), ['00', '01', '02']);
        assert.equal(endPopup.hours.at(-1), '24');
        assert.equal(endPopup.minutes.length, 60);
    });
    endPopup.select('hour', '24');
    endPopup.select('minute', '59');
    await check('24 endpoint stages only24:00 and excludes nonzero minutes', () => {
        assert.equal(endPopup.value, '24:00');
        assert.deepEqual(endPopup.minutes, ['00']);
        assert.deepEqual(endpoint.calls, []);
    });
    const endApply = endPopup.apply();
    endpoint.requests[0].resolve();
    await endApply;
    await check('24:00 is retained as raw endpoint without date or12-hour conversion', () => assert.deepEqual(endpoint.calls, [{ time_to: '24:00' }]));
    endPopup = endpoint.open();
    endPopup.select('hour', '23');
    endPopup.select('minute', '59');
    await check('moving away from24 restores all60 arbitrary minute choices', () => {
        assert.equal(endPopup.minutes.length, 60);
        assert.equal(endPopup.value, '23:59');
    });
    endPopup.cancel();

    const start = fixture('00:00', false, 'time_from');
    const startPopup = start.open();
    await check('start-time picker excludes24 and ignores invalid endpoint selection', () => {
        assert.equal(startPopup.hours.length, 24);
        assert.equal(startPopup.hours.at(-1), '23');
        startPopup.select('hour', '24');
        assert.equal(startPopup.value, '00:00');
    });
    await check('each of60 integer minutes stages exact Western HHMM without updates', () => {
        startPopup.select('hour', '05');
        for (let minute = 0; minute < 60; minute++) {
            const padded = String(minute).padStart(2, '0');
            startPopup.select('minute', padded);
            assert.equal(startPopup.value, `05:${padded}`);
        }
        assert.deepEqual(start.calls, []);
    });
    startPopup.select('minute', '07');
    const startApply = startPopup.apply();
    start.requests[0].resolve();
    await startApply;
    await check('same reusable picker updates the requested start field only', () => assert.deepEqual(start.calls, [{ time_from: '05:07' }]));

    const keyFixture = fixture('13:23', false);
    const keyPopup = keyFixture.open();
    function key(part, value) {
        let prevented = false, stopped = false;
        keyPopup.onColumnKeydown({ key: value, currentTarget: { dataset: { part } },
            preventDefault() { prevented = true; }, stopPropagation() { stopped = true; } });
        return { prevented, stopped };
    }
    await check('column keyboard navigation stages values and bounds arrows without record updates', () => {
        assert.deepEqual(key('minute', 'End'), { prevented: true, stopped: true });
        assert.equal(keyPopup.value, '13:59');
        key('minute', 'ArrowDown');
        assert.equal(keyPopup.value, '13:59');
        key('minute', 'Home');
        key('minute', 'ArrowUp');
        assert.equal(keyPopup.value, '13:00');
        key('minute', 'ArrowDown');
        key('hour', 'ArrowUp');
        assert.equal(keyPopup.value, '12:01');
        assert.deepEqual(keyFixture.calls, []);
    });
    await check('Tab remains available to the native dialog keyboard system', () => assert.deepEqual(key('minute', 'Tab'), { prevented: false, stopped: false }));
    keyFixture.field.popover.close();
    await check('native outside-close callback does not persist draft', () => {
        assert.deepEqual(keyFixture.calls, []);
        assert.equal(keyFixture.record.data.time_to, '13:23');
        assert.equal(keyFixture.field.state.open, false);
        assert.equal(keyFixture.open().value, '13:23');
    });
    keyFixture.field.openPicker();
    await check('trigger toggles an already open idle popover without updates', () => {
        assert.equal(keyFixture.field.popover.isOpen, false);
        assert.deepEqual(keyFixture.calls, []);
    });
    await check('panel Escape stops modal propagation and cancels staged changes without updating', () => {
        const escapeFixture = fixture('14:17');
        const escapePopup = escapeFixture.open();
        escapePopup.select('minute', '38');
        let prevented = false, stopped = false;
        const event = { key: 'Tab', preventDefault() { prevented = true; }, stopPropagation() { stopped = true; } };
        escapePopup.onPanelKeydown(event);
        assert.equal(prevented, false);
        assert.equal(stopped, false);
        assert.equal(escapeFixture.field.popover.isOpen, true);
        event.key = 'Escape';
        escapePopup.onPanelKeydown(event);
        assert.equal(prevented, true);
        assert.equal(stopped, true);
        assert.equal(escapeFixture.field.popover.isOpen, false);
        assert.equal(escapeFixture.field.state.open, false);
        assert.equal(escapeFixture.record.data.time_to, '14:17');
        assert.deepEqual(escapeFixture.calls, []);
    });
    const readonly = fixture('10:17', false, 'time_from', true);
    readonly.field.openPicker();
    await check('readonly field cannot open a writable picker', () => {
        assert.equal(readonly.field.popover.openCalls, 0);
        assert.deepEqual(readonly.calls, []);
        assert.equal(readonly.field.value, '10:17');
    });
    result.status = 'passed';
} catch (error) {
    result.status = 'failed';
    result.error = error.stack;
    process.exitCode = 1;
} finally {
    fs.writeFileSync('docs/build-governance/ws5-component-checks.json', JSON.stringify(result, null, 2) + '\n');
    console.log(`${checks.filter(c => c.passed).length}/${checks.length} component checks ${result.status}`);
    if (result.error) { console.error(result.error); }
}
