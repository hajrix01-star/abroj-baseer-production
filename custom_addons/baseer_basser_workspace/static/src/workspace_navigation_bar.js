/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";
import { NavBar } from "@web/webclient/navbar/navbar";
import { useService } from "@web/core/utils/hooks";
import { BASSER_ROOT_MENU_XMLID } from "./workspace_navigation";


patch(NavBar.prototype, {
    setup() {
        super.setup(...arguments);
        this.baseerWorkspaceNavigation = useService("baseer_workspace_navigation");
        this.baseerWorkspaceNavigationState = useState(this.baseerWorkspaceNavigation.state);
    },

    get showBaseerWorkspaceHome() {
        return this.baseerWorkspaceNavigationState.active
            && this.currentApp?.xmlid === BASSER_ROOT_MENU_XMLID;
    },

    onNavBarDropdownItemSelection(menu) {
        if (menu?.xmlid === BASSER_ROOT_MENU_XMLID) {
            this.baseerWorkspaceNavigation.deactivate();
        }
        return super.onNavBarDropdownItemSelection(...arguments);
    },

    async returnToBaseerWorkspace() {
        this.baseerWorkspaceNavigation.deactivate();
        await this.actionService.doAction({
            type: "ir.actions.client",
            tag: "baseer_basser_workspace.workspace",
            params: { show_landing: true },
        });
    },
});
