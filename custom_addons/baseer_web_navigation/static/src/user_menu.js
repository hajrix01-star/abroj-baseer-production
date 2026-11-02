/** @odoo-module **/

import "@web/webclient/user_menu/user_menu_items";
import { registry } from "@web/core/registry";

// Both desktop and mobile use this registry. Keep all other user actions intact.
registry.category("user_menuitems").remove("odoo_account");
