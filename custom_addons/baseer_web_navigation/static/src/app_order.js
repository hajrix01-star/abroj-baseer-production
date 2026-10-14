/** @odoo-module **/

// Sort only the applications already visible to the user. Never add a menu.
export const APP_ORDER = Object.freeze([
    "spreadsheet_dashboard.spreadsheet_dashboard_menu_root",
    "point_of_sale.menu_point_root",
    "sale.sale_menu_root",
    "purchase.menu_purchase_root",
    "account.menu_finance",
    "stock.menu_stock_root",
    "baseer_google_business.menu_gbp_root",
    "baseer_google_ads.menu_gads_root",
    "baseer_employee_followup.followup_root",
    "baseer_pos_suite.menu_baseer_pos_suite",
]);

export function orderApps(apps) {
    const ranks = new Map(APP_ORDER.map((xmlid, index) => [xmlid, index]));
    return apps.map((app, index) => ({ app, index })).sort((a, b) =>
        (ranks.get(a.app.xmlid) ?? APP_ORDER.length) -
        (ranks.get(b.app.xmlid) ?? APP_ORDER.length) || a.index - b.index
    ).map(({ app }) => app);
}
