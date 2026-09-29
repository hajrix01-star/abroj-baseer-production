/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";

function receiptFilename(number) {
    const safeNumber = String(number || "receipt")
        .replace(/[^A-Za-z0-9._-]+/g, "-")
        .replace(/^-+|-+$/g, "");
    return `${safeNumber || "receipt"}.pdf`;
}

function downloadReceipt(blob, filename) {
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    anchor.style.display = "none";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    browser.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

export class AbrojReceiptShareFormController extends FormController {
    static template = "abroj_project_costing.ReceiptShareFormController";

    setup() {
        super.setup();
        this.notification = useService("notification");
    }

    async shareReceipt() {
        const receipt = this.model.root;
        if (!receipt.resId) {
            return;
        }

        const number = receipt.data.name || "receipt";
        const filename = receiptFilename(number);
        let pdfBlob;

        try {
            const response = await browser.fetch(
                `/report/pdf/abroj_project_costing.report_receipt_voucher/${receipt.resId}`,
                { credentials: "same-origin" }
            );
            if (!response.ok) {
                throw new Error(`Receipt PDF request failed with status ${response.status}`);
            }

            pdfBlob = await response.blob();
            const receiptFile = new File([pdfBlob], filename, {
                type: pdfBlob.type || "application/pdf",
            });
            const shareData = {
                title: _t("سند قبض العميل"),
                text: `${_t("سند قبض العميل")}: ${number}`,
                files: [receiptFile],
            };
            const canShareFiles =
                typeof browser.navigator.share === "function" &&
                (!browser.navigator.canShare || browser.navigator.canShare({ files: [receiptFile] }));

            if (canShareFiles) {
                await browser.navigator.share(shareData);
                return;
            }
        } catch (error) {
            if (error?.name === "AbortError") {
                return;
            }
            if (!pdfBlob) {
                this.notification.add(_t("تعذر تجهيز ملف السند للمشاركة."), { type: "danger" });
                return;
            }
        }

        downloadReceipt(pdfBlob, filename);
        this.notification.add(
            _t("تم تنزيل السند. أرفقه في واتساب من جهازك."),
            { type: "info" }
        );
    }
}

registry.category("views").add("abroj_receipt_share_form", {
    ...formView,
    Controller: AbrojReceiptShareFormController,
});
