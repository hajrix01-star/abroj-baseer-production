# LIVE1 — Original system to live hosting and GitHub

2026-09-09. User authorizes moving original MAIN with data to a server, storing code in GitHub, and publishing future updates. Target server/domain/repository are not yet supplied; an asynchronous question is pending. GitHub CLI authenticates as hajrix01-star; root has no tracked files and no remote. No remote creation or push until repository target is resolved.

## G0 — Scope and critical path

Preserve accepted source1108f2a8fc0edee2f61d728135feee02590a8f46 and original database baseer_dev with coherent filestore. Initial migration includes employee/company/payroll/business records. QA fixture databases never migrate. GitHub receives source/config templates/operations only; no database dumps, employee reports, attachments, credentials or local evidence directory. Use an isolated allowlisted repository export; never stage the root wholesale.

Local preparation now: reproducible source-only export from accepted manifest with1118verified files; security/allowlist validation; concise first-migration and future-release contract. Destination-specific provisioning, workflow activation and data transfer wait for target details. Preparation does not interrupt MAIN or change application behavior.

## G1 — Capacity and availability

Provisional target is a Linux Docker host compatible with current pinned Odoo19 image and PostgreSQL16. Final stack depends on target. Reuse measured local database/source/filestore sizes; no production capacity claim until host resources and concurrency are known. Single initial cutover requires a short source write freeze and final coherent backup; after cutover the live DB becomes authoritative. Backups before every upgrade plus off-host scheduled backup must be verified on target. No destructive automatic retention default.

## G2 — Data and deployment boundaries

Initial import runs only against an empty explicitly named target, under a lock, with digest verification, database+filestore restoration, attachment reconciliation and business table/count checks before traffic. Never run initial import from the normal update workflow.

Future changes: local reviewed release -> private GitHub repository -> CI -> pinned artifact -> serialized server deployment -> coherent live backup -> changed-module upgrade -> health/functional checks. Preserve live data; never replace it from a later local copy. No code-only automatic downgrade after a schema change. Failed upgrade keeps maintenance active until a compatible recovery is chosen. Server/domain/secrets/host key and targetDB must be explicit before deploy activation. No background filesystem watcher publishing unfinished edits.

## G3 — Technology and direct path

Keep existing Odoo19 modules, PostgreSQL16 and Docker; no ERP redesign or new UI. GitHub Actions can drive accepted-branch deployments after CI; workflow and SSH/hosting integration depend on the chosen destination. HTTPS reverse proxy, proxy_mode, restricted dbfilter and disabled database listing are production requirements. Only proxy exposes public ports. Credentials stay outside source and workflow logs. Existing local backup/release evidence is referenced privately, not copied into GitHub.

Sources checked: https://www.odoo.com/documentation/19.0/administration/on_premise/deploy.html and https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments . Existing release protections remain applicable. New trust boundary is public hosting and CI; independent reviewer owns LIVE1-REVIEW.md. Root owns export preparation, documentation and later target integration.

## Live log

- LIVE1-01: Read AGENTS, current release manifest/runtime, compose, sanitized configuration, git state and ignore rules. Read alpha build/delivery/migration guidance. No code or remote changes. Confirmed source-only export needed because root contains private migration/release reports. Requested server/domain/repository identifiers without secrets. G0–G3 local preparation awaits independent approval; live launch blocked by unspecified destination.
- LIVE1-02: Read-only source inventory: MAIN has50employee records including archived,3companies and104258583database bytes. Acceptedbackup has651verified attachment references; it is a coherent local backup, not a new server restore drill. GitHub authenticationavailable. Production review found local database application role superuser; target must use separate restricted app role. Current local config is not a deployable public server configuration. No source snapshot or business backup uploaded.
- LIVE1-03: User selected existing empty PUBLIC repository https://github.com/hajrix01-star/Odoo-Baseer; authenticated ADMIN verified. Local-preparation G0-G3 independently approved. Exporter wrote1118hash-matched source files plus6clean repository files to isolated ignored repository. No local credentials/private-key markers found; Python/XML syntax and inventory pass. Local candidate5ba4857f69c389fc81ecbd1e5559e2758622eb9d committed with origin configured, not yet pushed. Independent audit classifies3supplierVAT seeds as officially published corporate metadata (SEC/stc/Mobily) backed by prior local research; no importedemployee/payroll dataset found. Server question remains pending.
- LIVE1-04: Independent LIVE1-R04 approved public source candidate5ba4857f69c389fc81ecbd1e5559e2758622eb9d; bounded source audit complete with no confirmed secret/privacy blocker. Pushed main to user-selected https://github.com/hajrix01-star/Odoo-Baseer; GitHub remote SHA matched exactly. Source-check Actions run34400882692 started. No database/filestore/credential uploads; local MAIN untouched. No server or domain supplied, so no production deployment or automatic server update activation.
- LIVE1-05: GitHub Actions run34400882692 completed SUCCESS for exactpublishedcommit5ba4857f69c389fc81ecbd1e5559e2758622eb9d. Evidence live1-github-ci.json. GitHub publication complete; LIVE server migration and code-deployment automation remain pending server/domain/access information, not claimed complete.
