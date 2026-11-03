# Grok Notes sync

Set `ODOO_API_KEY` in the environment. Connection defaults are `https://abroj.sa`, `baseer_prod`, and UID 2; override with `--url`, `--db`, `--uid` or `--login` (or `ODOO_URL`, `ODOO_DB`, `ODOO_UID`, `ODOO_LOGIN`). Global options precede the subcommand.

`python sync_notes.py pull --out notes.ts` exports notes; omitting `pull` writes to stdout. `python sync_notes.py push --file pending.json` previews changes using read-only calls. Add `--confirm` to apply them. Input is a list of notes or an object with a `notes` list. Existing notes update only when `updated_at` is strictly newer than their Odoo `write_date`; omitted items and labels are unchanged, while supplied lists replace them. Timestamps are UTC.
