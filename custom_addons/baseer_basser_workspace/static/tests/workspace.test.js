/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { Deferred } from "@odoo/hoot-mock";
import { EventBus } from "@odoo/owl";
import { NavBar } from "@web/webclient/navbar/navbar";
import "@baseer_basser_workspace/workspace_navigation_bar";
import { BasserWorkspace } from "@baseer_basser_workspace/workspace";
import {
    BASSER_ROOT_MENU_XMLID,
    baseerWorkspaceNavigationService,
} from "@baseer_basser_workspace/workspace_navigation";


const item = { id: 11, name: "Cashier operation" };
const workspace = (name = "Cashier operation") => ({
    can_manage: false,
    sections: [{ id: 10, name: "Cashier", items: [{ ...item, name }] }],
});


function makeWorkspaceContext(call, doAction = () => {}, notify = () => {}) {
    const context = {
        props: {},
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
        workspaceNavigation: {
            activate: () => expect.step("workspace navigation activated"),
            deactivate: () => expect.step("workspace navigation deactivated"),
        },
    };
    context.isOwnerLanding = () => BasserWorkspace.prototype.isOwnerLanding.call(context);
    context.loadWorkspace = () => BasserWorkspace.prototype.loadWorkspace.call(context);
    context.openManagement = (reloadOnError) => BasserWorkspace.prototype.openManagement.call(context, reloadOnError);
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
    expect.verifySteps(["workspace navigation activated", "native action"]);
});


test.tags("desktop");
test("BASSER preserves each approved action shape while activating workspace navigation", async () => {
    const clientAction = { type: "ir.actions.client", tag: "approved.client" };
    const companyPoolAction = {
        type: "ir.actions.act_window",
        context: { default_company_id: 7, default_is_company_pool: true },
    };
    const responses = [
        { action: clientAction },
        { action_id: 77 },
        { action: companyPoolAction },
    ];
    const actions = [];
    const context = makeWorkspaceContext(async (_model, method) => {
        expect(method).toBe("open_workspace_item");
        return responses.shift();
    }, async (action) => actions.push(action));

    await BasserWorkspace.prototype.openItem.call(context, item);
    await BasserWorkspace.prototype.openItem.call(context, item);
    await BasserWorkspace.prototype.openItem.call(context, item);

    expect(actions).toEqual([clientAction, 77, companyPoolAction]);
    expect(companyPoolAction.context).toEqual({
        default_company_id: 7,
        default_is_company_pool: true,
    });
    expect.verifySteps([
        "workspace navigation activated",
        "workspace navigation activated",
        "workspace navigation activated",
    ]);
});


test.tags("desktop");
test("BASSER clears the navigation state when opening an operation fails", async () => {
    const context = makeWorkspaceContext(async () => ({ action_id: 77 }), async () => {
        throw new Error("navigation failed");
    });
    context.loadWorkspace = async () => expect.step("workspace reloaded");

    await BasserWorkspace.prototype.openItem.call(context, item);
    expect(context.state.openingItemId).toBe(false);
    expect.verifySteps([
        "workspace navigation activated",
        "workspace navigation deactivated",
        "workspace reloaded",
    ]);
});


test.tags("desktop");
test("workspace navigation is not retained after leaving Baseer", () => {
    let currentApp = { xmlid: BASSER_ROOT_MENU_XMLID };
    const env = { bus: new EventBus() };
    const navigation = baseerWorkspaceNavigationService.start(env, {
        menu: { getCurrentApp: () => currentApp },
    });
    navigation.activate();
    expect(navigation.state.active).toBe(true);

    currentApp = { xmlid: "base.menu_administration" };
    env.bus.trigger("MENUS:APP-CHANGED");
    expect(navigation.state.active).toBe(false);
});


test.tags("desktop");
test("the Baseer home button is visible only for a workspace-originated Baseer operation", () => {
    const context = {
        baseerWorkspaceNavigationState: { active: true },
        currentApp: { xmlid: BASSER_ROOT_MENU_XMLID },
    };
    expect(NavBar.prototype.showBaseerWorkspaceHome.call(context)).toBe(true);

    context.baseerWorkspaceNavigationState.active = false;
    expect(NavBar.prototype.showBaseerWorkspaceHome.call(context)).toBe(false);
    context.baseerWorkspaceNavigationState.active = true;
    context.currentApp.xmlid = "base.menu_administration";
    expect(NavBar.prototype.showBaseerWorkspaceHome.call(context)).toBe(false);
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
test("BASSER opens owner management directly when there are no operational cards", async () => {
    const context = makeWorkspaceContext(async (_model, method) => {
        expect(method).toBe("get_workspace");
        return { can_manage: true, sections: [] };
    });
    context.openManagement = async (reloadOnError) => {
        expect(reloadOnError).toBe(false);
        expect.step("open management");
    };

    await BasserWorkspace.prototype.loadWorkspace.call(context);
    expect.verifySteps(["open management"]);
});


test.tags("desktop");
test("BASSER shows an owner landing after an explicit return home", async () => {
    const context = makeWorkspaceContext(async (_model, method) => {
        expect(method).toBe("get_workspace");
        return { can_manage: true, sections: [] };
    });
    context.isOwnerLanding = () => true;
    context.openManagement = async () => expect.step("open management");

    await BasserWorkspace.prototype.loadWorkspace.call(context);
    expect(context.state.status).toBe("ready");
    expect.verifySteps([]);
});


test.tags("desktop");
test("BASSER keeps the home route available while opening owner management", async () => {
    const actions = [];
    const context = makeWorkspaceContext(async (_model, method) => {
        expect(method).toBe("open_workspace_management");
        return { action_id: 72 };
    }, async (action) => actions.push(action));

    await BasserWorkspace.prototype.openManagement.call(context);
    expect(actions).toEqual([72]);
    expect(context.state.openingItemId).toBe(false);
    expect.verifySteps(["workspace navigation activated"]);
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
