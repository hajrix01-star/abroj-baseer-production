import { chromium } from "file:///D:/Codex/Baseer-ERP/node_modules/playwright/index.mjs";

const browser = await chromium.launch({ headless: true });
const qaUser = process.env.BASEER_QA_USER || "admin";
const qaPassword = process.env.BASEER_QA_PASSWORD;
if (!qaPassword) throw new Error("BASEER_QA_PASSWORD is required");
const viewportWidth = Number(process.env.VIEWPORT_WIDTH || 390);
const context = await browser.newContext({ viewport: { width: viewportWidth, height: 844 }, locale: "ar-SA" });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(String(error)));

await page.goto("http://127.0.0.1:18081/web/login", { waitUntil: "domcontentloaded" });
await page.locator('input[name="login"]').fill(qaUser);
await page.locator('input[name="password"]').fill(qaPassword);
await Promise.all([
    page.waitForURL(/\/odoo(?:\/|$)/),
    page.locator('form[action*="/web/login"] button[type="submit"]').click(),
]);
const assetMode = process.env.DEBUG_ASSETS ? "?debug=assets" : "";
await page.goto(`http://127.0.0.1:18081/odoo/action-828${assetMode}`, { waitUntil: "domcontentloaded" });
await page.locator(".o_prc_pos_shell").waitFor({ state: "visible", timeout: 20000 });

const productPane = page.locator(".o_prc_product_pane");
const cartPane = page.locator(".o_prc_cart_pane");
const mobileNav = page.locator(".o_prc_mobile_nav");
const cssFallback = await page.getByText("A css error occurred", { exact: false }).count();
const initial = {
    viewport: await page.evaluate(() => ({ width: innerWidth, height: innerHeight })),
    document: await page.evaluate(() => ({ clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth })),
    productPaneVisible: await productPane.isVisible(),
    cartPaneVisible: await cartPane.isVisible(),
    mobileNavVisible: await mobileNav.isVisible(),
    cssFallback: Boolean(cssFallback),
};
await page.screenshot({ path: `docs/audits/2026-09-11-procurement-pos-ui/mobile-products-${viewportWidth}.png`, fullPage: false });

await page.locator(".o_prc_product_card").first().click();
await page.locator(".o_prc_mobile_nav button").nth(1).click();
await cartPane.waitFor({ state: "visible" });
const cart = {
    productPaneVisible: await productPane.isVisible(),
    cartPaneVisible: await cartPane.isVisible(),
    cartLines: await page.locator(".o_prc_cart_line").count(),
    total: await page.locator(".o_prc_total_row strong").textContent(),
};
await page.screenshot({ path: `docs/audits/2026-09-11-procurement-pos-ui/mobile-cart-${viewportWidth}.png`, fullPage: false });

await page.keyboard.press("Escape");
await productPane.waitFor({ state: "visible", timeout: 2000 });
const afterEscape = {
    productPaneVisible: await productPane.isVisible(),
    cartPaneVisible: await cartPane.isVisible(),
};

console.log(JSON.stringify({ initial, cart, afterEscape, errors }, null, 2));
await browser.close();
