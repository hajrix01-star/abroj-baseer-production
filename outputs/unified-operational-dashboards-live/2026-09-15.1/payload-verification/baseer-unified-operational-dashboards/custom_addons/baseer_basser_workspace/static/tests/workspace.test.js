/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { Deferred } from "@odoo/hoot-mock";
import { BasserWorkspace } from "@baseer_basser_workspace/workspace";


const item = { id: 11, name: "Cashier operation" };
const workspace = (name = "Cashier operation") => ({
    can_manage: false,
    sections: [{ id: 10, name: "Cashier", items: [{ ...item, name }] }],
});


function makeWorkspaceContext(call, doAction = () => {}, notify = () => {}) {
    const context = {
        requestSequence: 0,
        state: {
            status: "loading",
            sections: [],
            canManage: false,
            openingItemId: false,
        },
        orm: { call },
        action: { doAction },
        notification: { add: notify },
    };
    context.loadWorkspace = () => BasserWorkspace.prototype.loadWorkspace.call(context);
    return context;
}


test.tags("desktop");
test("BASSER opens an approved operation once while its action is pending", async () => {
    const opening = new Deferred();
    let openCalls = 0;
    const context = makeWorkspaceContext(async (_model, method) => {
        if (method === "open_workspace_item") {
            openCalls += 1;
            return opening;
        }
        throw new Error(`Unexpected workspace method: ${method}`);
    }, () => expect.step("native action"));

    const openingPromise = BasserWorkspace.prototype.openItem.call(context, item);
    expect(openCalls).toBe(1);
    expect(context.state.openingItemId).toBe(item.id);

    await BasserWorkspace.prototype.openItem.call(context, item);
    expect(openCalls).toBe(1);

    await opening.resolve({ action_id: 77 });
    await openingPromise;
    expect(context.state.openingItemId).toBe(false);
    expect.verifySteps(["native action"]);
});


test.tags("desktop");
test("BASSER recovers from a temporary workspace load failure", async () => {
    let calls = 0;
    const context = makeWorkspaceContext(async (_model, method) => {
        expect(method).toBe("get_workspace");
        calls += 1;
        if (calls === 1) {
            throw new Error("temporary backend failure");
        }
        return workspace();
    });

    await BasserWorkspace.prototype.loadWorkspace.call(context);
    expect(context.state.status).toBe("error");

    await BasserWorkspace.prototype.loadWorkspace.call(context);
    expect(calls).toBe(2);
    expect(context.state.status).toBe("ready");
    expect(context.state.sections[0].items[0].name).toBe("Cashier operation");
});


test.tags("desktop");
test("BASSER discards a late response after the active company changes", async () => {
    const staleCompany = new Deferred();
    let calls = 0;
    const context = makeWorkspaceContext(async (_model, method) => {
        expect(method).toBe("get_workspace");
        calls += 1;
        if (calls === 1) {
            return staleCompany;
        }
        return workspace("Current company operation");
    });

    const staleRequest = BasserWorkspace.prototype.loadWorkspace.call(context);
    const currentRequest = BasserWorkspace.prototype.loadWorkspace.call(context);
    await currentRequest;
    expect(calls).toBe(2);
    expect(context.state.sections[0].items[0].name).toBe("Current company operation");

    await staleCompany.resolve(workspace("Stale company operation"));
    await staleRequest;
    expect(context.state.sections[0].items[0].name).toBe("Current company operation");
});
