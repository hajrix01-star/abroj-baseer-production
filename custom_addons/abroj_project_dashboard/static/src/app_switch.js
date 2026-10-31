import { Component, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";

class AbrojAppSwitch extends Component {
    static props = {};
    static template = xml`<div class="o_abroj_app_switch d-flex align-items-center">
        <a href="/abroj/switch" class="o-dropdown--narrow d-flex align-items-center px-2" title="تبديل التطبيق" aria-label="تبديل التطبيق">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>
        </a></div>`;
}
registry.category("systray").add("abroj_app_switch", { Component: AbrojAppSwitch }, { sequence: 1 });
