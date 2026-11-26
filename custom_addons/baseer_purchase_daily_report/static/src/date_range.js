/** @odoo-module **/

const RIYADH = "Asia/Riyadh";

export function riyadhYmd(now = new Date()) {
    const iso = new Intl.DateTimeFormat("en-CA", {
        timeZone: RIYADH,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    }).format(now);
    const [year, month, day] = iso.split("-").map(Number);
    return { year, month, day, iso };
}

export function isoDate(year, month, day) {
    return [
        String(year),
        String(month).padStart(2, "0"),
        String(day).padStart(2, "0"),
    ].join("-");
}

export function lastDayOfMonth(year, month) {
    return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

export function addDays(year, month, day, delta) {
    const date = new Date(Date.UTC(year, month - 1, day + delta));
    return {
        year: date.getUTCFullYear(),
        month: date.getUTCMonth() + 1,
        day: date.getUTCDate(),
        iso: isoDate(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate()),
    };
}

export function monthValue(year, month) {
    return `${year}-${String(month).padStart(2, "0")}`;
}

export function rangeForDay(iso) {
    return { from: iso, to: iso };
}

export function rangeForMonth(yearMonth, today = riyadhYmd()) {
    const [year, month] = yearMonth.split("-").map(Number);
    const from = isoDate(year, month, 1);
    const last = lastDayOfMonth(year, month);
    const isCurrent = year === today.year && month === today.month;
    const to = isCurrent ? today.iso : isoDate(year, month, last);
    return { from, to };
}

export function rangeForPreset(preset, now = new Date()) {
    const today = riyadhYmd(now);
    if (preset === "today") {
        return { from: today.iso, to: today.iso, period: "day", day: today.iso, month: monthValue(today.year, today.month) };
    }
    if (preset === "yesterday") {
        const yesterday = addDays(today.year, today.month, today.day, -1);
        return { from: yesterday.iso, to: yesterday.iso, period: "day", day: yesterday.iso, month: monthValue(yesterday.year, yesterday.month) };
    }
    if (preset === "this_week") {
        // Saudi business week starts Sunday and ends Saturday.
        const weekday = new Date(Date.UTC(today.year, today.month - 1, today.day)).getUTCDay();
        const start = addDays(today.year, today.month, today.day, -weekday);
        return { from: start.iso, to: today.iso, period: "range", day: today.iso, month: monthValue(today.year, today.month) };
    }
    if (preset === "this_month") {
        return {
            from: isoDate(today.year, today.month, 1),
            to: today.iso,
            period: "month",
            day: today.iso,
            month: monthValue(today.year, today.month),
        };
    }
    if (preset === "last_month") {
        const month = today.month === 1 ? 12 : today.month - 1;
        const year = today.month === 1 ? today.year - 1 : today.year;
        const last = lastDayOfMonth(year, month);
        return {
            from: isoDate(year, month, 1),
            to: isoDate(year, month, last),
            period: "month",
            day: isoDate(year, month, last),
            month: monthValue(year, month),
        };
    }
    throw new Error(`Unknown date preset: ${preset}`);
}

export function detectPreset(from, to, now = new Date()) {
    for (const preset of ["today", "yesterday", "this_week", "this_month", "last_month"]) {
        const range = rangeForPreset(preset, now);
        if (range.from === from && range.to === to) {
            return preset;
        }
    }
    return from === to ? "day" : "range";
}
