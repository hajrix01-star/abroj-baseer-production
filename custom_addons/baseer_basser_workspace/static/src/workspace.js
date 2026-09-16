/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { userBus } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";


function isAccessError(error) {
    return Boolean(error?.data?.name?.includes("AccessError"));
}


export class BasserWorkspace extends Component {
    static template = "baseer_basser_workspace.Workspace";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.requestSequence = 0;
        this.state = useState({
            status: "loading",
            sections: [],
            canManage: false,
            openingItemId: false,
        });
        this.labels = {
            title: _t("Baseer | بصير"),
            description: _t("Your approved operational workspace."),
            loading: _t("Loading your workspace…"),
            empty: _t("No operational items are configured for your role and active company."),
            noAccess: _t("You are not allowed to use this workspace."),
            error: _t("Baseer could not be loaded."),
            retry: _t("Retry"),
            opening: _t("Opening…"),
        };
        onWillStart(() => this.loadWorkspace());
        useBus(userBus, "ACTIVE_COMPANIES_CHANGED", () => {
            document.activeElement?.blur();
            this.loadWorkspace();
        });
    }

    async loadWorkspace() {
        const sequence = ++this.requestSequence;
        this.state.status = "loading";
        this.state.sections = [];
        this.state.openingItemId = false;
        try {
            const workspace = await this.orm.call(
                "baseer.basser.workspace.section", "get_workspace", [],
            );
            if (sequence !== this.requestSequence) {
                return;
            }
            this.state.sections = workspace.sections || [];
            this.state.canManage = Boolean(workspace.can_manage);
            if (this.state.canManage && !this.state.sections.length) {
                // Owners have a configuration destination rather than an
                // operational card. Open it immediately and avoid a blank
                // landing page plus an extra management click.
                await this.openManagement(false);
                return;
            }
            this.state.status = this.state.sections.length || this.state.canManage ? "ready" : "empty";
        } catch (error) {
            if (sequence !== this.requestSequence) {
                return;
            }
            this.state.status = isAccessError(error) ? "no_access" : "error";
        }
    }

    async openItem(item) {
        if (this.state.openingItemId) {
            return;
        }
        this.state.openingItemId = item.id;
        try {
            const result = await this.orm.call(
                "baseer.basser.workspace.section", "open_workspace_item", [item.id],
            );
            await this.action.doAction(result.action || result.action_id);
        } catch (_error) {
            this.notification.add(_t("This operation is no longer available to you."), {
                type: "danger",
            });
            await this.loadWorkspace();
        } finally {
            this.state.openingItemId = false;
        }
    }

    async openManagement(reloadOnError = true) {
        if (this.state.openingItemId) {
            return;
        }
        this.state.openingItemId = "management";
        try {
            const result = await this.orm.call(
                "baseer.basser.workspace.section", "open_workspace_management", [],
            );
            await this.action.doAction(result.action_id);
        } catch (_error) {
            this.notification.add(_t("Baseer configuration is not available."), { type: "danger" });
            if (reloadOnError) {
                await this.loadWorkspace();
            } else {
                this.state.status = "error";
            }
        } finally {
            this.state.openingItemId = false;
        }
    }
}

registry.category("actions").add("baseer_basser_workspace.workspace", BasserWorkspace);
