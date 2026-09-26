/** @odoo-module **/

import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";
import { CharField } from "@web/views/fields/char/char_field";
import { Many2One } from "@web/views/fields/many2one/many2one";
import { ListRenderer } from "@web/views/list/list_renderer";
import { SwitchCompanyMenu } from "@web/webclient/switch_company_menu/switch_company_menu";
import { SwitchCompanyItem } from "@web/webclient/switch_company_menu/switch_company_item";

const ARABIC = /[\u0620-\u064a\u066e-\u06d3\u06fa-\u06fc]/;
const LATIN = /[A-Za-z]/;

/** Select an explicit bilingual label without changing its source value. */
export function reportName(label, lang, hierarchy = false) {
    if (typeof label !== "string" || !label) {
        return label;
    }
    if (hierarchy && label.includes(" / ")) {
        return label.split(" / ").map((part) => reportName(part, lang)).join(" / ");
    }
    const parts = label.split("|").map((part) => part.trim());
    if (parts.length !== 2 || parts.some((part) => !part)) {
        return label;
    }
    const arabic = parts.filter((part) => ARABIC.test(part));
    const english = parts.filter((part) => LATIN.test(part) && !ARABIC.test(part));
    if (arabic.length !== 1 || english.length !== 1) {
        return label;
    }
    return (lang || "").toLowerCase().startsWith("ar") ? arabic[0] : english[0];
}

// Intentionally excludes documents, descriptions, users and arbitrary custom models.
const CATALOG_MODELS = new Set([
    "res.company", "res.partner", "pos.payment.method", "baseer.pos.payment.category",
    "product.category", "account.analytic.plan", "account.analytic.account", "account.journal",
    "product.product", "product.template", "pos.config", "baseer.gads.connection",
    "baseer.gbp.location",
]);

export function catalogName(label, model, lang) {
    return CATALOG_MODELS.has(model)
        ? reportName(label, lang, ["product.category", "account.analytic.plan"].includes(model))
        : label;
}

export function fieldNameModel(record, fieldName) {
    const field = record.fields[fieldName];
    if (field?.type === "many2one") {
        return field.relation;
    }
    if (field?.type === "char" && ["name", "display_name"].includes(fieldName)) {
        return record.resModel;
    }
    return undefined;
}

patch(CharField.prototype, {
    get formattedValue() {
        const value = super.formattedValue;
        return this.props.readonly && !this.props.isPassword
            ? catalogName(value, fieldNameModel(this.props.record, this.props.name), user.lang)
            : value;
    },
});

patch(Many2One.prototype, {
    get displayName() {
        const value = super.displayName;
        return this.props.readonly ? catalogName(value, this.props.relation, user.lang) : value;
    },
});

patch(ListRenderer.prototype, {
    getFormattedValue(column, record) {
        const value = super.getFormattedValue(column, record);
        // Formatter cells are native readonly output. Never alter an editing row,
        // widget-specific title or an explicitly unformatted source value.
        if (record.isInEdition || !this.canUseFormatter(column, record) ||
            column.options?.enable_formatting === false || column.attrs?.password) {
            return value;
        }
        return catalogName(value, fieldNameModel(record, column.name), user.lang);
    },
});

patch(SwitchCompanyMenu.prototype, {
    baseerCompanyName(name) {
        return reportName(name, user.lang);
    },
});

patch(SwitchCompanyItem.prototype, {
    baseerCompanyName(name) {
        return reportName(name, user.lang);
    },
});
