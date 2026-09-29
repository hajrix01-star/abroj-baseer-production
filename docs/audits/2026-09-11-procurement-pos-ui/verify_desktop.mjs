import { chromium } from "file:///D:/Codex/Baseer-ERP/node_modules/playwright/index.mjs";

const browser = await chromium.launch({ headless: true });
const qaUser = process.env.BASEER_QA_USER || "admin";
const qaPassword = process.env.BASEER_QA_PASSWORD;
if (!qaPassword) throw new Error("BASEER_QA_PASSWORD is required");
const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: "ar-SA" });
const page = await context.newPage();
const pageErrors = [];
const consoleErrors = [];
page.on("pageerror", (error) => pageErrors.push(String(error)));
page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
});

await page.goto("http://127.0.0.1:18081/web/login", { waitUntil: "domcontentloaded" });
await page.locator('input[name="login"]').fill(qaUser);
await page.locator('input[name="password"]').fill(qaPassword);
await Promise.all([
    page.waitForURL(/\/odoo(?:\/|$)/),
    page.locator('form[action*="/web/login"] button[type="submit"]').click(),
]);
await page.goto("http://127.0.0.1:18081/odoo/action-828", { waitUntil: "domcontentloaded" });
await page.locator(".o_prc_pos_shell").waitFor({ state: "visible", timeout: 20000 });

const productPane = page.locator(".o_prc_product_pane");
const cartPane = page.locator(".o_prc_cart_pane");
const search = page.locator('.o_prc_search input[type="search"]');
const initial = {
    title: await page.locator(".o_prc_pos_identity h1").textContent(),
    productPaneVisible: await productPane.isVisible(),
    cartPaneVisible: await cartPane.isVisible(),
    mobileNavVisible: await page.locator(".o_prc_mobile_nav").isVisible(),
    document: await page.evaluate(() => ({ clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth })),
    cssFallback: Boolean(await page.getByText("A css error occurred", { exact: false }).count()),
};

await search.fill("طماطم");
await page.waitForTimeout(500);
const searchCount = await page.locator(".o_prc_product_card").count();
const searchNames = await page.locator(".o_prc_product_card strong").allTextContents();
await search.fill("");
await page.waitForTimeout(500);

const firstCard = page.locator(".o_prc_product_card").first();
await firstCard.focus();
await page.keyboard.press("Enter");
await page.locator(".o_prc_cart_line").waitFor({ state: "visible" });
await page.waitForTimeout(300);
const quantityBefore = await page.locator(".o_prc_stepper input").inputValue();
const totalBefore = await page.locator(".o_prc_total_row strong").textContent();
await page.locator(".o_prc_stepper button").last().click();
await page.waitForTimeout(300);
const interaction = {
    keyboardAdded: quantityBefore === "1",
    quantityAfterIncrement: await page.locator(".o_prc_stepper input").inputValue(),
    totalBefore,
    totalAfter: await page.locator(".o_prc_total_row strong").textContent(),
};
await page.screenshot({ path: "docs/audits/2026-09-11-procurement-pos-ui/desktop-pos.png", fullPage: false });

console.log(JSON.stringify({ initial, search: { count: searchCount, names: searchNames.slice(0, 8) }, interaction, pageErrors, consoleErrors }, null, 2));
await browser.close();
