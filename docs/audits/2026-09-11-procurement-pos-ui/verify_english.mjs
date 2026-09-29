import { chromium } from "file:///D:/Codex/Baseer-ERP/node_modules/playwright/index.mjs";

const browser = await chromium.launch({ headless: true });
const qaUser = process.env.BASEER_QA_USER || "admin";
const qaPassword = process.env.BASEER_QA_PASSWORD;
if (!qaPassword) throw new Error("BASEER_QA_PASSWORD is required");
const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: "en-US" });
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
await page.goto("http://127.0.0.1:18081/odoo/action-828", { waitUntil: "domcontentloaded" });
await page.locator(".o_prc_pos_shell").waitFor({ state: "visible", timeout: 20000 });
const result = {
    lang: await page.locator("html").getAttribute("lang"),
    dir: await page.locator("html").getAttribute("dir"),
    title: await page.locator(".o_prc_pos_identity h1").textContent(),
    productPaneVisible: await page.locator(".o_prc_product_pane").isVisible(),
    cartPaneVisible: await page.locator(".o_prc_cart_pane").isVisible(),
    document: await page.evaluate(() => ({ clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth })),
    errors,
};
await page.screenshot({ path: "docs/audits/2026-09-11-procurement-pos-ui/desktop-en.png", fullPage: false });
console.log(JSON.stringify(result, null, 2));
await browser.close();
