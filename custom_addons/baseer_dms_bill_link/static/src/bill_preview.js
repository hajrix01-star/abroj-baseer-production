import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

const IMAGE_TYPES = new Set([
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/avif",
]);

export function billContentUrl(id, checksum, download = false) {
    const params = new URLSearchParams({
        model: "dms.file", id: String(id), field: "content", filename_field: "name",
        download: String(download), unique: checksum || "",
    });
    return `/web/content?${params}`;
}

export class BillPreviewDialog extends Component {
    static template = "baseer_dms_bill_link.PreviewDialog";
    static components = { Dialog };
    static props = { name: String, mimetype: String, contentUrl: String, downloadUrl: String, close: Function };

    setup() {
        this.state = useState({ loading: true, failed: false });
        this.labels = {
            title: _t("Document preview"), close: _t("Close"), download: _t("Download"),
            loading: _t("Loading preview…"),
            failed: _t("The preview could not be loaded. You can download the document."),
            pdf: _t("PDF preview"),
        };
    }

    get isPdf() {
        return this.props.mimetype === "application/pdf";
    }

    get pdfUrl() {
        return `/web/static/lib/pdfjs/web/viewer.html?file=${encodeURIComponent(this.props.contentUrl)}#zoom=page-width`;
    }

    loaded() {
        this.state.loading = false;
    }

    failed() {
        this.state.loading = false;
        this.state.failed = true;
    }
}

export class BillPreviewWidget extends Component {
    static template = "baseer_dms_bill_link.PreviewWidget";
    static props = { ...standardWidgetProps, thumbnail: { type: Boolean, optional: true } };

    setup() {
        this.dialog = useService("dialog");
        this.state = useState({ thumbnailFailed: false });
        this.labels = { preview: _t("Preview document"), download: _t("Download document") };
    }

    get data() {
        return this.props.record.data;
    }

    get isImage() {
        return IMAGE_TYPES.has(this.data.mimetype);
    }

    get canPreview() {
        return this.isImage || this.data.mimetype === "application/pdf";
    }

    get contentUrl() {
        return billContentUrl(this.props.record.resId, this.data.checksum);
    }

    get downloadUrl() {
        return billContentUrl(this.props.record.resId, this.data.checksum, true);
    }

    get thumbnailUrl() {
        return `/web/image/dms.file/${this.props.record.resId}/content/128x128?unique=${encodeURIComponent(this.data.checksum || "")}`;
    }

    preview(event) {
        event.stopPropagation();
        if (!this.canPreview || !this.props.record.resId) {
            return;
        }
        this.dialog.add(BillPreviewDialog, {
            name: this.data.name || this.labels.preview, mimetype: this.data.mimetype,
            contentUrl: this.contentUrl, downloadUrl: this.downloadUrl,
        });
    }

    thumbnailFailed() {
        this.state.thumbnailFailed = true;
    }
}

registry.category("view_widgets").add("baseer_dms_bill_preview", {
    component: BillPreviewWidget,
    extractProps: ({ attrs }) => ({ thumbnail: attrs.thumbnail === "true" }),
});
