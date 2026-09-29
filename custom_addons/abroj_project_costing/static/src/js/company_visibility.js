/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { user, userBus } from "@web/core/user";
import { menuService } from "@web/webclient/menus/menu_service";

const ABROJ_ROOT_MENU = "abroj_project_costing.menu_abroj_cost_root";

function costingEnabledForActiveCompany() {
    const company = user.activeCompany || user.activeCompanies?.[0];
    return Boolean(company?.abroj_project_costing_enabled);
}

patch(menuService, {
    async start(env, dependencies) {
        const menu = await super.start(env, dependencies);
        const getApps = menu.getApps.bind(menu);

        userBus.addEventListener("ACTIVE_COMPANIES_CHANGED", () => {
            env.bus.trigger("MENUS:APP-CHANGED");
        });

        return {
            ...menu,
            getApps() {
                return getApps().filter(
                    (app) => app.xmlid !== ABROJ_ROOT_MENU || costingEnabledForActiveCompany()
                );
            },
        };
    },
});
