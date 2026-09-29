import { localizationService } from "@web/core/l10n/localization_service";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

const { Settings } = luxon;

// Keep Odoo's Arabic translations, date order, week start and timezone. Luxon
// supplies the month/day names and numerals used by every standard date field.
registry.category("services").add(
    "localization",
    {
        ...localizationService,
        async start(...args) {
            const result = await localizationService.start(...args);
            const language = user.lang || document.documentElement.lang || "";
            if (/^ar(?:[_-]|$)/i.test(language)) {
                Settings.defaultLocale = "en-GB";
                Settings.defaultNumberingSystem = "latn";
            }
            return result;
        },
    },
    { force: true }
);
