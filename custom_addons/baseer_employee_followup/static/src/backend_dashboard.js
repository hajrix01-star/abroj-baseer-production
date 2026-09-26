/** @odoo-module **/

import { Component, onMounted, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

export class FollowUpBackendDashboard extends Component {
    static template = "baseer_employee_followup.BackendDashboard";
    static props = ["*"];

    setup() {
        this.state = useState({ loading: true, error: false, data: false });
        onWillStart(async () => {
            try {
                this.state.data = await rpc("/employee-app/backend-dashboard-data", {});
            } catch (error) {
                this.state.error = error.message || "Could not load the dashboard.";
            } finally {
                this.state.loading = false;
            }
        });
        onMounted(() => this._insertAppLink());
    }

    _insertAppLink() {
        const header = document.querySelector(".o_baseer_followup_dashboard .o_followup_dashboard_header");
        if (!header || header.querySelector(".o_followup_app_link")) {
            return;
        }
        const appUrl = `${window.location.origin}/employee-app`;
        const panel = document.createElement("section");
        panel.className = "o_followup_app_link";
        panel.setAttribute("aria-label", "رابط التطبيق");
        const label = document.createElement("label");
        label.textContent = "رابط التطبيق";
        const controls = document.createElement("div");
        controls.className = "o_followup_app_link_controls";
        const input = document.createElement("input");
        input.value = appUrl;
        input.readOnly = true;
        input.dir = "ltr";
        input.setAttribute("aria-label", "رابط التطبيق");
        const copy = document.createElement("button");
        copy.type = "button";
        copy.className = "btn btn-secondary";
        copy.textContent = "نسخ";
        copy.addEventListener("click", () => this._copyAppUrl(appUrl, copy));
        const open = document.createElement("button");
        open.type = "button";
        open.className = "btn btn-primary";
        open.textContent = "فتح";
        open.addEventListener("click", () => window.open(appUrl, "_blank", "noopener"));
        controls.append(input, copy, open);
        panel.append(label, controls);
        header.append(panel);
    }

    async _copyAppUrl(value, button) {
        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(value);
            } else {
                const textarea = document.createElement("textarea");
                textarea.value = value;
                textarea.setAttribute("readonly", "");
                textarea.style.position = "fixed";
                textarea.style.opacity = "0";
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand("copy");
                textarea.remove();
            }
            button.textContent = "تم النسخ";
            window.setTimeout(() => { button.textContent = "نسخ"; }, 1800);
        } catch {}
    }
}

registry.category("actions").add("baseer_employee_followup.backend_dashboard", FollowUpBackendDashboard);
