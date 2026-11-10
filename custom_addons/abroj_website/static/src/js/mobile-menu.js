/** @odoo-module **/
document.addEventListener("click", (event) => {
    const menu = document.querySelector(".abroj-v2__mobile-menu[open]");
    if (menu && (event.target.closest("nav a") || event.target === menu || !event.target.closest(".abroj-v2__mobile-menu"))) menu.open = false;
});
document.addEventListener("keydown", (event) => {
    const menu = document.querySelector(".abroj-v2__mobile-menu[open]");
    if (menu && event.key === "Escape") { menu.open = false; menu.querySelector("summary").focus(); }
});
