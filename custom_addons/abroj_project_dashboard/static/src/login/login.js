/* Abroj login: remember the last login name locally to prefill the form. */
(function () {
    "use strict";
    const KEY = "abroj.lastLogin";
    function init() {
        const form = document.querySelector(".abroj-login form.oe_login_form");
        if (!form) return;
        const login = form.querySelector("input[name=login]");
        const remember = form.querySelector("input[name=remember]");
        let saved = null;
        try { saved = window.localStorage.getItem(KEY); } catch (e) { /* storage blocked */ }
        if (login && !login.value && saved) {
            login.value = saved;
            const pw = form.querySelector("input[name=password]");
            if (pw) pw.focus();
        }
        form.addEventListener("submit", () => {
            try {
                if (remember && remember.checked && login && login.value) {
                    window.localStorage.setItem(KEY, login.value.trim());
                } else {
                    window.localStorage.removeItem(KEY);
                }
            } catch (e) { /* ignore */ }
        });
    }
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
