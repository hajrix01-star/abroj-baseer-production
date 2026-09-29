# AR1 ready access presets and private employee advances

Scope: seeded Owner / General Manager, Accountant and Cashier roles. Assign through Settings > Users > Ready access role. Existing users are not reassigned automatically.

Owner receives the reviewed installed application manager groups and all companies. Accountant has Invoicing, Purchase, Sales and POS. Cashier has POS and own bulk purchase batches; cashier saves drafts, accountant approves/posts. Employee advances are available to both through POS > Employee advances (also Invoicing for accountant). Both may approve/disburse using a company cash/bank journal. Cashier sees own entries; accountant sees allowed-company entries. Salary, private HR records and native payroll interfaces remain inaccessible to these limited roles.

Advance disbursement uses the existing payroll loan and installment ledger, including its accounting and duplicate protection. It records a disbursement; it does not send an external bank transfer. Only a narrow server-only capability and payroll version bump modify existing payroll source. Other 1,133 baseline files remain unchanged.

Validation: 95 role/bulk-bill checks, 83 advance checks, 122 financial privacy checks (all rollback); 12 clean-install/update/uninstall checks; 9 Arabic browser evidence groups, including cashier draft save, accountant posted bill, owner preset selection and cashier actual synthetic advance disbursement. Private fixture operations occurred only on isolated clones. Browser tested native desktop forms; no separate mobile claim. PDF permission and generation checks passed; PDF visual completeness is not claimed.

Release identity, preservation and runtime results are recorded in candidate.json, main-preservation.json and runtime.json. Coherent pre/post original database and filestore backups remain private. GitHub receives application source only, never user data, database backups or test credentials.

Deployment completed: source `98f9d4dced9f7a844d3d44e63f89d8d0d8218664`, MAIN HTTP200 and all preservation checks passed. GitHub `c021ceac3a7ce2c980687e1fd46f073a2ab21426` matches all 1,156 source files; workflow34482110786 succeeded. Original users must be assigned the desired preset explicitly by an administrator.
