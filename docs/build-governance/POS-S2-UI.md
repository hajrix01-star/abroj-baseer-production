# POS-S2 entry UI

Owned files: summary_views.xml; static/src/js/payment_amount_grid.js; static/src/xml/payment_amount_grid.xml; static/src/scss/summary.scss. No backend, manifest, translation or runtime changes by UI worker.

| Before | After | Why |
| --- | --- | --- |
| Add allocation row, select method and inspect category | Server-configured methods shown above fixed amount boxes | Less repetitive daily input; categories remain reporting metadata |
| External reference entry | Native generated summary name | No manual reference required |
| Mobile row dialogs | Two-column amount grid with native monetary fields | Direct touch input and visible labels |
| Single period radio | Explicit day schedule plus shift selection | Distinguishes planned single shift from incomplete split day |
| Totals separate from customer average | Native computed gross, customers and average in one panel | No client-side monetary calculations |

Widget extends Odoo19 X2ManyField and reuses x2ManyField registry metadata (useSubView/relatedFields/context/normal ORM model). Each MonetaryField receives the native allocation Record and amount field. Odoo useInputField owns parsing, NEED_LOCAL_CHANGES flushing, FIELD_IS_DIRTY, onchange and saving. No RPC, sum, independent state or dataset. All nested fields needed by native MonetaryField are loaded by the list subview; 25-row limit matches backend bound.

CSS uses scoped grid, Odoo/Bootstrap border and focus tokens, logical spacing, tabular numbers, four columns desktop and two mobile. Every editable amount has a linked label and 44px box; native readonly uses text. No animation or new library. Native smartbuttons/approval/manual WhatsApp remain.

Validation: local XML parsing passed. Parent owns module validation, browser desktop/mobile/Arabic/English, save/approve dirty flush, zero toggle, accessibility and screenshot evidence.

The split-shift control is a native RadioField subclass overriding only items to filter out all-day; native template and record.update remain unchanged. Backend validates schedule/period independently.
