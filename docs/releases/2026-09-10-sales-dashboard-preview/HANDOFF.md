# SD7 — Borderless charts and explicit empty preview

Candidate `4cd5ee3e9bebcd1d85bda2723bf2781643f7f3e7`, dashboard19.0.1.1.5. Four source files changed from SD6;1131 other files unchanged. Removed outer chart/performance and KPI borders; added thin heading dividers. Empty dashboard shows faint display-only example card values, explicit translated illustrative-preview label and bar/line sales/customer legend. Real chart legend remains native Chart.js.

Five focused getter tests prove samples do not mutate payloads and actual zero, unavailable and server-formatted values remain authoritative. Actual QA data4447/202/889.40 preserved; today's empty period shows five examples and no comparison arrows. Arabic label/legend, borders0px and480px client450/scroll450 verified. Original month-to-date filter restored. Evidence: sd7-preview-checks.json, sd7-ui-checks.json, qa-real.png, qa-preview.png, qa-narrow.png.

Independent review: PREDEPLOY-GO.md. Deployment identity, protected-table comparison and coherent backups recorded separately by the release helper. No backend calculation, permissions, schema or seed changes; backend suites not rerun for this display-only delta. Final publication details appended after deployment.

Completed: MAIN HTTP200 installed1.1.5;367 protected tables exact and651 attachment references verified before/after. MAIN5sample values/translated preview and legend/three borders0px verified. GitHub source 429b8a9856fbb6e790d49e2a0c7a827b20d5bdfe;1135files hash/Python/XML passed. QA narrow screenshot replaced with fully rendered480px actual-data view.
