// Presentation preference shared by the two dashboards in this browser session.
// It never persists operational data or grants source access.
const selections = new Map();
const listeners = new Set();

export function noorixScope(userId, companyId) {
    return `${userId}:${companyId}`;
}

export function getNoorixSelection(scope) {
    return selections.get(scope) === true;
}

export function setNoorixSelection(scope, included) {
    if (typeof included !== "boolean") {
        throw new TypeError("The Noorix selection must be a boolean.");
    }
    if (getNoorixSelection(scope) === included) { return; }
    selections.set(scope, included);
    for (const listener of listeners) { listener(scope, included); }
}

export function subscribeNoorixSelection(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
}
