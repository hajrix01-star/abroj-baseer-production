/* Abroj login: remember the last login name locally to prefill the form. */
(function () {
    "use strict";
    const KEY = "abroj.lastLogin";
    function init() {
        const form = document.querySelector(".abroj-login form.oe_login_form");
        if (!form) return;
        const login = form.querySelector("input[name=login]");
        const remember = form.querySelector("input[name=remember]");
        const PENDING = "abroj.pendingLogin";
        // Username (never the password) is saved only after a successful login:
        // submit parks it in sessionStorage; a failed attempt comes back here with an error.
        try {
            const pending = window.sessionStorage.getItem(PENDING);
            if (pending !== null) {
                window.sessionStorage.removeItem(PENDING);
                if (!document.querySelector(".abroj-login .alert-danger")) {
                    if (pending) window.localStorage.setItem(KEY, pending); else window.localStorage.removeItem(KEY);
                }
            }
        } catch (e) { /* storage blocked */ }
        try {
            const m = document.cookie.match(/(?:^|; )abroj_last_login=([^;]*)/);
            if (m) window.localStorage.setItem(KEY, decodeURIComponent(m[1].replace(/\+/g, " ")).replace(/^"|"$/g, ""));
        } catch (e) { /* ignore */ }
        let saved = null;
        try { saved = window.localStorage.getItem(KEY); } catch (e) { /* storage blocked */ }
        if (login && !login.value && saved) {
            login.value = saved;
            const pw = form.querySelector("input[name=password]");
            if (pw) pw.focus();
        }
        // Destination choice: keep the active pill in sync (also without :has support).
        form.querySelectorAll("input[name=abroj_target]").forEach((radio) => {
            radio.addEventListener("change", () => {
                form.querySelectorAll(".abroj-login__opt").forEach((opt) => {
                    opt.classList.toggle("is-active", opt.contains(radio) ? radio.checked : !radio.checked);
                });
            });
        });
        // Never preselect a destination (no localStorage restore); force an explicit choice.
        const radios = form.querySelectorAll("input[name=abroj_target]");
        radios.forEach((radio) => { radio.checked = false; });
        form.querySelectorAll(".abroj-login__opt").forEach((opt) => opt.classList.remove("is-active"));
        const fieldset = form.querySelector(".abroj-login__target");
        const MSG = (radios[0] && radios[0].dataset.requiredMsg) || "اختر وجهة الدخول";
        function showTargetError(show) {
            let box = form.querySelector(".abroj-login__target-error");
            if (show && !box && fieldset) {
                box = document.createElement("p");
                box.className = "abroj-login__target-error alert alert-danger";
                box.setAttribute("role", "alert");
                box.textContent = MSG;
                fieldset.after(box);
            }
            if (!show && box) box.remove();
            if (fieldset) fieldset.classList.toggle("is-invalid", show);
        }
        radios.forEach((radio) => radio.addEventListener("change", () => showTargetError(false)));
        form.addEventListener("submit", (ev) => {
            if (radios.length && !form.querySelector("input[name=abroj_target]:checked")) {
                ev.preventDefault();
                ev.stopImmediatePropagation();
                showTargetError(true);
                return;
            }
            try {
                const name = remember && remember.checked && login ? login.value.trim() : "";
                window.sessionStorage.setItem(PENDING, name);
            } catch (e) { /* ignore */ }
        });
    }
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
