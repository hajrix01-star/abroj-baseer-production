/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { formatRequestDateTime } from "@baseer_procurement_requests/representative_petty_cash";


test.tags("desktop");
test("request datetime is parsed as UTC and crosses into the user's next local day", () => {
    const label = formatRequestDateTime("2026-10-15 21:30:00", "en-GB", "Asia/Riyadh");
    expect(label).toContain("16/10/2026");
});


test.tags("desktop");
test("request datetime uses Arabic UI text with Latin digits and a Gregorian date", () => {
    const label = formatRequestDateTime("2026-10-15 21:30:00", "ar_001", "Asia/Riyadh");
    expect(/16\D*10\D*2026/.test(label)).toBe(true);
    expect(/[0-9]/.test(label)).toBe(true);
    expect(/[٠-٩]/.test(label)).toBe(false);
});


test.tags("desktop");
test("request datetime accepts Odoo's underscored English locale", () => {
    const label = formatRequestDateTime("2026-10-15 21:30:00", "en_US", "Asia/Riyadh");
    expect(label).toContain("10/16/2026");
});
