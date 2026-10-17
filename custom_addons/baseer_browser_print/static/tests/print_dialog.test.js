/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { BrowserPrintDialog } from "@baseer_browser_print/print_dialog";


test.tags("desktop");
test("PDF preview ignores a late load from a cross-origin native frame", async () => {
    const frame = {};
    Object.defineProperty(frame, "contentWindow", {
        get() {
            throw new DOMException("Blocked a cross-origin frame", "SecurityError");
        },
    });
    const context = {
        destroyed: false,
        compatibleLoading: false,
        frame: { el: frame },
        state: { compatible: true, warning: "", ready: false },
        labels: { help: "Use the viewer print button" },
    };

    await BrowserPrintDialog.prototype.onLoad.call(context);

    expect(context.state.warning).toBe("");
    expect(context.compatibleLoading).toBe(false);
});


test("PDF preview continues when the same-origin viewer finishes loading", async () => {
    const app = { initializedPromise: Promise.resolve() };
    const context = {
        destroyed: false,
        compatibleLoading: false,
        frame: { el: { contentWindow: { PDFViewerApplication: app } } },
        state: { compatible: true, warning: "", ready: false },
        labels: { help: "Use the viewer print button" },
        waitForPages(loadedApp, attempts) {
            expect(loadedApp).toBe(app);
            expect(attempts).toBe(0);
            expect.step("viewer ready");
        },
    };

    await BrowserPrintDialog.prototype.onLoad.call(context);

    expect(context.compatibleLoading).toBe(true);
    expect.verifySteps(["viewer ready"]);
});
