# SD5 — Native dashboard tab icons

Deployed MAIN candidate `de89a85675cb7d36a503618a4fa5fb9faf6ad696`, dashboard version `19.0.1.1.3`. Two files changed from PP1; all1133 other source files unchanged. Shift/payment tabs use native Odoo graph/pivot icons with translated hover titles, accessible names and existing keyboard behavior.

QA: `sd5-ui-checks.json`, `qa-details.png`, `qa-narrow.png`; both click transitions and keyboard End/Home checked, actual480px viewport without tab overflow. MAIN native icons and both Details transitions verified after upgrade. Backend logic unchanged; backend suites not rerun.

Independent acceptance: `PREDEPLOY-GO.md`. Deployment: `runtime.json`, `main-preservation.json`; all367 protected business tables exactly unchanged. Coherent backups before/after with651 attachment references verified. Daily backup source mapping updated. QA data retained; original receives no demo data.

GitHub source `4f40d7249b477c981d1cc61f637b9c639d0f977f`; clean checkout,1135 source files passed hash/Python/XML checks. Export contains only2 addon changes and release-source manifest. CI run34474321378.
