/** @odoo-module **/

// Odoo 19.0 1fe5b09b9da730a57fe6541da14db41101a762c4 (LGPL-3).
// Do not snapshot/restore counters: another tab may have advanced them.
export function clearLocalStorage() {
    for (const key of Object.keys(localStorage)) {
        if (key !== "device_uuid" && !key.endsWith("-unique_device_identifier")) {
            localStorage.removeItem(key);
        }
    }
}
