/** @odoo-module **/

import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";


export const BASSER_ROOT_MENU_XMLID = "baseer_basser_workspace.menu_basser_root";

// This is presentation state only. It deliberately does not use an Odoo action
// context: workspace targets may be a client action, an action id, or an
// action dict with protected defaults that must remain untouched.
export const baseerWorkspaceNavigationService = {
    dependencies: ["menu"],
    start(env, { menu }) {
        const state = reactive({ active: false });
        env.bus.addEventListener("MENUS:APP-CHANGED", () => {
            if (menu.getCurrentApp()?.xmlid !== BASSER_ROOT_MENU_XMLID) {
                state.active = false;
            }
        });
        return {
            state,
            activate() {
                state.active = true;
            },
            deactivate() {
                state.active = false;
            },
        };
    },
};

registry.category("services").add("baseer_workspace_navigation", baseerWorkspaceNavigationService);
