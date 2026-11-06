import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";

const sharedSource = fs.readFileSync(new URL("../src/noorix_toggle.js", import.meta.url), "utf8");
const shared = {};
vm.createContext(shared);
vm.runInContext(sharedSource.replaceAll("export ", "") + `
this.api = { noorixScope, getNoorixSelection, setNoorixSelection, subscribeNoorixSelection };`, shared);
const api = shared.api;
const user = { userId: 41, activeCompany: { id: 7 } };

function loadComponent(url, name, hooks = {}) {
    const source = fs.readFileSync(url, "utf8").replace(/^import .*;\s*$/gm, "").replaceAll("export ", "");
    const sandbox = { ...api, user, Component: class {}, Dialog: class {}, _t: text => text, ...hooks };
    vm.createContext(sandbox);
    vm.runInContext(source + `\nthis.Report = ${name};`, sandbox);
    return sandbox.Report;
}
const Sales = loadComponent(new URL("../src/sales_dashboard.js", import.meta.url), "BaseerSalesDashboard");
const Heat = loadComponent(new URL("../../../baseer_sales_heat_calendar/static/src/heat_calendar.js", import.meta.url), "BaseerHeatCalendar");

function report(Type, call) {
    const component = Object.create(Type.prototype);
    component.props = { dashboardId: 12, dateFilter: { type: "month", month: 11, year: 2026 } };
    component.requestGeneration = 0;
    component.disposed = false;
    component.state = { month: "2026-11", loading: false, error: "", payload: null, selectedDay: null };
    component.orm = { call };
    return component;
}
function deferred() {
    let resolve, reject;
    const promise = new Promise((a, b) => { resolve = a; reject = b; });
    return { promise, resolve, reject };
}
function identity() {
    user.userId = 41;
    user.activeCompany = { id: 7 };
    api.setNoorixSelection(api.noorixScope(41, 7), false);
}

test("preference starts false and synchronizes only the same user/company", () => {
    const scope = api.noorixScope(91, 2);
    assert.equal(api.getNoorixSelection(scope), false);
    const seen = [];
    const unsubscribe = api.subscribeNoorixSelection((changedScope, value) => seen.push([changedScope, value]));
    api.setNoorixSelection(scope, true);
    assert.equal(api.getNoorixSelection(scope), true);
    assert.equal(api.getNoorixSelection(api.noorixScope(91, 3)), false);
    assert.equal(api.getNoorixSelection(api.noorixScope(92, 2)), false);
    assert.deepEqual(seen, [[scope, true]]);
    unsubscribe();
    api.setNoorixSelection(scope, false);
    assert.equal(seen.length, 1);
    assert.throws(() => api.setNoorixSelection(scope, "true"), { name: "TypeError" });
});

test("native change handlers update both mounted components and issue one request each", async () => {
    identity();
    const requests = [], cleanup = [];
    const services = {
        orm: { call: async (_model, method, _args, kwargs) => {
            requests.push({ method, included: kwargs.include_noorix });
            return { month: "2026-11", include_noorix: kwargs.include_noorix };
        } }, action: {}, dialog: {},
    };
    const hooks = {
        userBus: {}, useState: value => value, useRef: () => ({}),
        useService: name => services[name], useBus() {}, useEffect() {},
        onWillStart() {}, onWillUpdateProps() {}, onWillUnmount: callback => cleanup.push(callback),
    };
    const mounted = [
        ["../src/sales_dashboard.js", "BaseerSalesDashboard"],
        ["../../../baseer_sales_heat_calendar/static/src/heat_calendar.js", "BaseerHeatCalendar"],
    ].map(([path, name]) => {
        const Type = loadComponent(new URL(path, import.meta.url), name, hooks);
        const instance = new Type();
        instance.props = { dashboardId: 12, dateFilter: null };
        instance.setup();
        return instance;
    });
    try {
        assert.equal(mounted[0].state.includeNoorix, false);
        assert.equal(mounted[1].state.includeNoorix, false);
        // Owl's native checkbox model updates checked state before change.
        // The initiating component must still request its own payload, rather
        // than relying on its peer-notification subscription to do so.
        mounted[0].state.includeNoorix = true;
        await mounted[0].toggleNoorix({ target: { checked: true } });
        await Promise.resolve();
        assert.equal(mounted[0].state.includeNoorix, true);
        assert.equal(mounted[1].state.includeNoorix, true);
        assert.equal(requests.length, 2);
        assert.ok(requests.every(request => request.included === true));
        mounted[1].state.includeNoorix = false;
        await mounted[1].toggleNoorix({ target: { checked: false } });
        await Promise.resolve();
        assert.equal(mounted[0].state.includeNoorix, false);
        assert.equal(mounted[1].state.includeNoorix, false);
        assert.equal(requests.length, 4);
        assert.ok(requests.slice(2).every(request => request.included === false));
    } finally {
        for (const callback of cleanup) { callback(); }
    }
});

for (const [name, Type, method] of [["sales", Sales, "get_baseer_sales_metrics"], ["heat", Heat, "get_baseer_heat_calendar"]]) {
    test(`${name}: RPC uses a boolean keyword, keeps its period, and shares the selection`, async () => {
        identity();
        let request;
        const component = report(Type, async (...args) => { request = args; return { month: "2026-11" }; });
        await component.load();
        assert.equal(request[1], method);
        assert.equal(request[3].include_noorix, false);
        api.setNoorixSelection(component.noorixSelectionScope, true);
        await component.load();
        assert.equal(request[3].include_noorix, true);
        assert.equal(name === "sales" ? request[2][1].native.month : request[2][1], name === "sales" ? 11 : "2026-11");
        assert.equal(component.state.includeNoorix, true);
    });

    test(`${name}: a late success or error cannot overwrite a newer selection`, async () => {
        identity();
        const old = deferred(), latest = deferred();
        let calls = 0;
        const component = report(Type, () => (++calls === 1 ? old : latest).promise);
        const first = component.load();
        api.setNoorixSelection(component.noorixSelectionScope, true);
        const second = component.load();
        latest.resolve({ month: "2026-11", include_noorix: true, marker: "latest" });
        await second;
        old.reject({ data: { name: "odoo.exceptions.AccessError", message: "obsolete failure" } });
        await first;
        assert.equal(component.state.payload.marker, "latest");
        assert.equal(component.state.error, "");
        assert.equal(component.state.loading, false);
    });

    test(`${name}: an old success cannot end the newer request's loading state`, async () => {
        identity();
        const old = deferred(), latest = deferred();
        let calls = 0;
        const component = report(Type, () => (++calls === 1 ? old : latest).promise);
        const first = component.load();
        api.setNoorixSelection(component.noorixSelectionScope, true);
        const second = component.load();
        old.resolve({ month: "2026-10", marker: "obsolete" });
        await first;
        assert.equal(component.state.payload, null);
        assert.equal(component.state.loading, true);
        latest.resolve({ month: "2026-11", marker: "latest" });
        await second;
        assert.equal(component.state.payload.marker, "latest");
    });

    test(`${name}: turning off recovers after a source access error and clears old details`, async () => {
        identity();
        const component = report(Type, async (_model, _method, _args, kwargs) => {
            if (kwargs.include_noorix) { throw { data: { name: "odoo.exceptions.AccessError", message: "Source unavailable" }, message: "Source unavailable" }; }
            return { month: "2026-11", include_noorix: false };
        });
        api.setNoorixSelection(component.noorixSelectionScope, true);
        await component.load();
        assert.ok(component.state.error);
        component.state.selectedDay = { source_action: "old" };
        api.setNoorixSelection(component.noorixSelectionScope, false);
        await component.load();
        assert.equal(component.state.includeNoorix, false);
        assert.equal(component.state.error, "");
        assert.equal(component.state.payload.include_noorix, false);
        if (name === "heat") { assert.equal(component.state.selectedDay, null); }
    });

    test(`${name}: a company change resets an unselected scope and invalidates old requests`, async () => {
        identity();
        const old = deferred();
        let calls = 0;
        const component = report(Type, (_m, _fn, _args, kwargs) => ++calls === 1 ? old.promise : Promise.resolve({ month: "2026-11", include_noorix: kwargs.include_noorix, company: 8 }));
        api.setNoorixSelection(component.noorixSelectionScope, true);
        const first = component.load();
        user.activeCompany = { id: 8 };
        await component.load();
        old.resolve({ month: "2026-11", company: 7 });
        await first;
        assert.equal(component.state.includeNoorix, false);
        assert.equal(component.state.payload.company, 8);
    });

    test(`${name}: unmounted components ignore a pending response`, async () => {
        identity();
        const pending = deferred();
        const component = report(Type, () => pending.promise);
        const loading = component.load();
        component.disposed = true;
        component.requestGeneration++;
        pending.resolve({ month: "2026-11", marker: "unmounted" });
        await loading;
        assert.equal(component.state.payload, null);
    });
}
