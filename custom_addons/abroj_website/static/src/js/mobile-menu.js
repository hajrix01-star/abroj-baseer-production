/** @odoo-module **/
// Website editor copies can retain the original navigation markup.
function enhanceAbrojMobileMenu() {
    const main = document.querySelector(".abroj-v2");
    const nav = main?.querySelector(".abroj-v2__mobile-menu nav");
    if (!nav) return;
    if (!nav.querySelector(".abroj-v2__mobile-logo")) {
        const logo = document.createElement("img");
        logo.className = "abroj-v2__mobile-logo";
        logo.src = "/abroj_website/static/src/img/abroj-logo-vector-white-20260928.svg";
        logo.alt = "Abroj";
        nav.prepend(logo);
    }
    if (!nav.querySelector(".abroj-v2__mobile-cta")) {
        const cta = document.createElement("a");
        cta.className = "abroj-v2__mobile-cta";
        cta.href = "#contact";
        cta.textContent = main.getAttribute("lang") === "ar" ? "اطلب عرض سعر" : "Request a quote";
        const arrow = document.createElement("span");
        arrow.setAttribute("aria-hidden", "true");
        arrow.textContent = "←";
        cta.append(arrow);
        nav.append(cta);
    }
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", enhanceAbrojMobileMenu);
else enhanceAbrojMobileMenu();
document.addEventListener("click", (event) => {
    const menu = document.querySelector(".abroj-v2__mobile-menu[open]");
    if (menu && (event.target.closest("nav a") || event.target === menu || !event.target.closest(".abroj-v2__mobile-menu"))) menu.open = false;
});
document.addEventListener("keydown", (event) => {
    const menu = document.querySelector(".abroj-v2__mobile-menu[open]");
    if (menu && event.key === "Escape") { menu.open = false; menu.querySelector("summary").focus(); }
});
