/** @odoo-module **/
import { registry } from '@web/core/registry';
import { localization } from '@web/core/l10n/localization';
import { DateTimeField, dateField } from '@web/views/fields/datetime/datetime_field';

// Keep the native date editor/picker and ISO value. Only the numeral system of
// this accounting review is explicit; no global date formatting is patched.
export class AccountingDateField extends DateTimeField {
    getRecordValue() {
        const value = super.getRecordValue();
        const latin = (date) => date && date.reconfigure({ numberingSystem: 'latn' });
        return Array.isArray(value) ? value.map(latin) : latin(value);
    }
    getFormattedValue(index) {
        const value = this.values[index];
        return value ? value.reconfigure({ numberingSystem: 'latn' }).toFormat(localization.dateFormat) : '';
    }
}

registry.category('fields').add('abroj_accounting_date', {
    ...dateField,
    component: AccountingDateField,
});
