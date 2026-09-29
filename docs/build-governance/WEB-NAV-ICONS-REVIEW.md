# NAV1 independent review — native desktop app icons

Reviewer s2_review; 2026-09-08; QA only. No application edits by reviewer.

## R1 — G0–G4 GO

Read `WEB-NAV-ICONS.md` and native `odoo/addons/web/static/src/webclient/navbar/navbar.xml`, including the complete `web.NavBar.AppsMenu` desktop branch. **G0–G4 approved for the proposed independent web-only addon.** Extending the existing repeated DropdownItem content is the shortest appropriate route: the native menu service remains the authorized, dynamic source of app names and icons, so later installed permitted apps need no hardcoded mapping or new service.

Remove only the target item's `t-esc` attribute and replace its content with the app icon and separately escaped native label. Preserve the original loop/key, class/focus, onSelected, href and menu attributes. Use decorative images (`alt=""`, hidden from accessibility) and the native decorative oi-apps fallback when webIconData is absent. Scope spacing and 32px sizing to the new inner content wrapper. Preserve native focus and keyboard ownership; do not modify the mobile branch, menu cache, source icon data or permission filtering. No new JavaScript, schema, dependency beyond web, accounting behavior or core Odoo edits are justified.

G5–G8 remain open for low-impact acceptance: native asset/template build, existing desktop apps with matching labels and icons, fallback and a later-app template fixture, working native app selection and keyboard navigation, RTL/LTR layout, and unchanged mobile rendering. Recovery by removing the independent QA addon is sufficient; no business-data migration belongs to this slice. Approval is QA-only and does not authorize main deployment.

## R2 — final independent NAV1 QA delivery decision

**GO for NAV1 in QA, version 19.0.1.0.0; G5–G8 closed for this bounded presentation slice.** Independently checked all four file SHA256 values in `docs/build-governance/nav1_manifest.json`; all match. Read the complete addon manifest, QWeb extension and stylesheet. The inheritance changes only the original desktop item's escaped content, retains its native app loop, item attributes and selection callback, and renders decorative native icons with a separately escaped label. Styles are scoped to the new wrapper. There is no new JavaScript, business model, ACL, dependency beyond web or core source modification.

Read the successful native QA install log and updated NAV1-003 ledger. Reviewed actual Arabic desktop and mobile screenshots: eight matching native icons appear beside names on desktop, and the original mobile sidebar remains visually intact. Lead browser measurements report eight loaded 32px desktop icons, 40px content rows, and eight original mobile icons with no desktop wrapper. Native keyboard Enter selected POS and opened its existing dashboard. These checks are proportionate to this reversible rendering-only change; a financial regression suite is unnecessary.

Acceptance limits are explicit and accepted for QA: no extra future module was installed, the missing-icon fallback was source-reviewed rather than exercised in a browser fixture, and English LTR was not replayed. Future-app behavior follows the unchanged native dynamic apps loop; no fixed application list exists. Layout uses direction-neutral flex/gap. These are bounded coverage limits, not claims of executed tests. The updated manifest records them accurately.

No material blocker remains. Recovery is uninstalling this independent QA addon; it owns no business records. Main installation/deployment and unrelated pending business-feature requests are outside this GO.
