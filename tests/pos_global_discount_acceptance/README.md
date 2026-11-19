# Offline native Saudi POS acceptance

Test addon only. Never install it on QA/production operating databases. It uses
Odoo's native Saudi **test fixtures** on an isolated synthetic database and
imports them by module; it contains no certificates, credentials or copied
Enterprise source.

Install `baseer_pos_global_discount_acceptance` with this folder in the Odoo
addons path, then run `--test-tags=/baseer_pos_global_discount_acceptance`.
The POS CI workflow runs these four scenarios alongside the owned addon tests.

Assertions exercise real native payment, posted/balanced accounting invoices,
full/partial credit notes, original-invoice links, document allowances by tax
category, XML totals and QR totals. The external EDI worker boundary is paused
and all `requests` network calls are denied. This proves internal fiscal parity;
it does not run the ZATCA SDK or submit anything to the authority.
