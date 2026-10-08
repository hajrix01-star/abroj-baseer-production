# P&L QA retry after disk exhaustion — 2026-10-08

This is a **new, bounded QA policy**, not a new financial build. The original `baseer-2026-10-08-profit-loss.env` and its request remain immutable. Retry policy `baseer-2026-10-08-profit-loss-r2` points to the same reviewed source commit `e501bd423d05176c9a42bd6b150f4bd0e3ce8783` and allows only `baseer_profit_loss_report`; it changes no module code, financial calculation, other module, QA data, or production service.

## Incident and current evidence

- [Request run 37777268440](https://github.com/hajrix01-star/abroj-baseer-production/actions/runs/37777268440) completed **successfully as a queue operation** (GitHub metadata verified 2026-10-08); that result is not proof of QA installation. The operator reports the host-side deployment failed with `ENOSPC` while creating the filestore tar recovery copy, **before switching the release source**. Host recovery outcome and current module state must be checked independently; this document does not infer them from the green queue run.
- The QA release poller timer was stopped by the operator to prevent retries. Do not restart it solely because this policy is merged. The old request ID must not be replayed.
- [Guard PR #234](https://github.com/hajrix01-star/abroj-baseer-production/pull/234) merged at `93b9d517fd09fd67b2ac9f57e2367939aacafa3a` after an independent GO reported by the release lead. Its wrapper checks free bytes **and inodes** against the copied release plus DB/filestore recovery pair before prefetch and again before backup, and fails closed on incomplete rollback. The host-installed wrapper version is **not yet verified**. Repository merge alone does not protect the running QA host.
- The 100k-line capacity archive and concurrent-reader evidence remain pending/limited as recorded in `QA-PROFIT-LOSS-20261008.md`; this retry neither reruns nor upgrades that evidence. Existing P&L source CI and financial tests apply to the **same source commit** and need not be repeated merely for a new policy ID.

## Preconditions before any dispatch (not performed here)

1. Operator verifies host free bytes **and inodes** meet the installed wrapper's preflight calculation with margin, after separately approved archival/cleanup; confirms the recovery pair can be created without risking the active release. No deletion or disk cleanup is authorized by this policy.
2. Operator verifies `/usr/local/sbin/baseer-qa-deploy` and the approved QA poller/approval wrappers on the host match reviewed guard `93b9d517...` and that the current QA symlink, source marker, module state, and service health are known. Any incomplete recovery or mismatch is NO-GO until resolved.
3. This policy PR passes source-integrity CI and `reports_release_review_oct8` reviews the exact policy diff and incident gates independently. After approved merge to `main`, a **new** explicit QA request for the r2 ID may be queued through the official workflow; the poller is resumed only by the authorized operator after gates 1–2. Queue success alone remains insufficient: require host `QA_DEPLOY=GO`, installed module/version/source verification, and visual/accounting acceptance on QA.

Rollback remains the protected QA wrapper's DB+filestore recovery pair and previous release link, subject to the verified host state. **No merge, QA dispatch, timer restart, production change, or cleanup is part of this policy preparation.**

## Executed recovery and subsequent CSS correction

- Host recovery completed: 66 inactive source releases were archived locally, every file verified, independently reviewed, and removed from QA after a successful dry run. Five existing successful releases remained; DB/filestore backups were not deleted. Free space rose from about 65 MiB to 7.5 GiB before retry.
- Installed QA wrapper matches merged `93b9d517fd09fd67b2ac9f57e2367939aacafa3a`, SHA256 `870984958169b7f53d0c875d8c7ba3af96792b604110024c8cb9a43a60d41cc7`; prior wrapper retained for recovery. Both capacity checks passed, timer resumed.
- Retry run `37783694705` produced actual host `QA_DEPLOY=GO` and `QA_POLLER=GO`, source `e501bd423d05176c9a42bd6b150f4bd0e3ce8783`, installed module `19.0.1.0.0`, no fatal upgrade log lines. JavaScript HTTP 200 and exact Git blob hash confirmed deployment, **not visual acceptance**.
- Owner screenshots then exposed shared CSS failure. Actual QA LibSass 0.22.0 rejects `min(22rem, 90vw)` with incompatible units in both `web.assets_web` and `web.assets_web_print`. In-memory compilation of the complete P&L SCSS proves original FAIL / width-and-max-width correction PASS. No financial code changed.
- Independent reviewer approved PR #236 at `2db65e80e05bae71e8889feaab6ad474e35303b3`; source CI `37785648221`, backend `37785648195`, and Hoot plus real shipped-SCSS compile `37785648294` all passed. Squash source is `f0c5d34ec33684be471f77f61972e581b6d5e244`.
- New policy `baseer-2026-10-08-profit-loss-css` upgrades only `baseer_profit_loss_report` via the same protected QA workflow. Runtime acceptance requires screen and print CSS compilation, RTL/LTR served bundles without error/fallback markers, and the corrected selector. QA-only; no production release or full report-suite acceptance.
