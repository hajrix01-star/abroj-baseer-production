/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { menuService } from "@web/webclient/menus/menu_service";
import { orderApps } from "./app_order";

patch(menuService, {
    async start(env, dependencies) {
        const menu = await super.start(env, dependencies);
        const getApps = menu.getApps.bind(menu);
        return {
            ...menu,
            getApps() {
                return orderApps(getApps());
            },
        };
    },
});
