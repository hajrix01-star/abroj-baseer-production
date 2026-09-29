# SD1 — Independent G8 predeployment review

**Decision: GO** for controlled deployment of commit `2d2ff102d11a53fc2fca1b8c1707fc81c77537ab` only. Reviewer: independent accounting and release gate agent `/root/payment_seed_review`. Date: 2026-09-09. No open blocking finding in this bounded change. This is permission to execute the prepared deployment, not a claim that MAIN has already passed postdeployment checks.

## Candidate and scope

- Independently matched all **1118** source file hashes to `candidate.json`; all **1106** baseline files from `8aff2c48f66df5925cf9dd98e9e7f11b55741f50` remain unchanged. The difference is the 12-file `baseer_sales_dashboard` addon. Frozen checkout is clean.
- Archive SHA256 verified: `0be236623979452ea7b640600e7613818490d8ad09fe368b6a9fb80878c3aa96`.
- Runtime image remains pinned to `odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd`.
- G0–G3 definitions and G4–G6 implementation review are recorded in `../../build-governance/SALES-DASHBOARD-REVIEW.md`. Native accounting, payroll and POS posting logic are outside the unchanged difference and were not recertified here.

## Evidence accepted

- **84 backend checks passed**, including independent totals and ratios, approved versus completed-day populations, partial closures, missing customers, true zero versus absent data, monthly aggregation, calendar comparisons, date bounds, real-user access and company isolation, and absence of endpoint writes. The reviewed backend SHA256 is `555144d0769a058af3755fbc3c3a9701366d3fbaa493d60f1a7c14920589922e`, matching the frozen file and backend evidence.
- **17 component checks passed** for the final JavaScript SHA256 `05a76f383b8e0a5d1bffdff2491a1d586e9eb28e50dbeb7d630a68e42962aa27`, including stale-response rejection, cleanup, gaps and faithful rendering of server-calculated values. These use component stubs and are supplemented by actual browser evidence.
- Reviewed `browser-evidence.md` and independently inspected `qa-mobile-ar.jpg` and `qa-desktop-en.jpg`: native Dashboards/Sales integration, legible Arabic RTL and Western numeric strings, two-column mobile cards, all five desktop cards and monthly charts. The fixture values 58,650 / 318 / 4,887.50 / 26.50 / 184.43 and comparison directions agree with the numerical evidence. Browser records also cover native Sales roundtrip, company switching, empty state and the custom September 1–30 daily range.
- Final XML date-input remount keys and SCSS numeric direction/color changes are presentation changes. The mobile screenshot precedes the remount-key correction; its final native-calendar behavior was subsequently checked in the browser as recorded. Older backend evidence contains an earlier UI snapshot; no claim is made that every older UI hash matches the final candidate.
- Performance evidence meets the local two-second target for one reader, with approximately 0.025–0.027 seconds for a year plus comparison year. It does not certify concurrent production capacity.

## Deployment protection and closure

Reviewed `../../build-governance/sales_dashboard_release.py`: it verifies the frozen source, baseline and archive; binds this review to the commit; stops MAIN before a coherent backup; installs only the new addon from immutable mounts; compares stable full-row projections of existing financial, operational, HR/resource and company/partner/user tables; and leaves MAIN stopped on a preservation failure. Native dashboard/module metadata additions are expected. No business seed or transaction migration is part of this release.

The helper retains the prior compose and backup mapping for recovery and verifies the pinned runtime, mounted source, installed module version, absence of pending modules and a single published special dashboard after restart. This review does not assert a newly executed restoration drill or broaden the guard into proof of every database DDL object.

Deployment owner reports QA fixture/account cleanup and QA shutdown completed. Final closure remains the normal MAIN runtime and preservation evidence from the authorized deployment, plus a read-only dashboard/navigation check. No reviewer action changed MAIN or implementation files.
