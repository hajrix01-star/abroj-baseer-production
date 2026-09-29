# IC2 R2 final independent acceptance

Decision: GO

Accepted source: `3d96581c2eef324df3b5ed69f7ba526bb37035fc`.
Published main: `be89096027c823dbe5414bbf95ce97e9e354a5b6`.
Reviewer: icons_release; evidence verification only, no MAIN business test mutations.

The separately approved R2 recovery completed without a second module update. The first candidate and failed-preservation evidence remain separate. Exactly 47 translated-name/partner-metadata rows were restored from the coherent original backup; independently compared before/after projections confirm every original column value across all 372 protected tables is unchanged. Security memberships/company access, user presets and existing audit are preserved; only the reviewed additive schema/defaults and two module versions differ. No historic operation was automatically cancelled or corrected.

Runtime is HTTP 200 on the pinned Odoo image with the accepted R2 addon mounts read-only, correction 19.0.1.1.0 and summary 19.0.1.5.1. The read-only MAIN smoke passes Arabic/English, native mobile view and shared permission setting. Accepted QA evidence remains PASS60 core, PASS38 summary, two real concurrency cases, bound UI artifacts and actual browser accounting verification.

Both stopped-service coherent backups have 661 verified attachment references. All eighteen backup file sizes and SHA256 hashes were independently verified. No new full database restore rehearsal is claimed for the post-release backup; recovery did verify the original backup through its isolated restored projections.

The clean public checkout independently matches all 1,181 frozen source hashes. Final `github-publication.json` records the same exact remote main commit, source-only publication and successful checksum/syntax verification. GitHub Actions [34511962677](https://github.com/hajrix01-star/Odoo-Baseer/actions/runs/34511962677) completed successfully for that head.

No residual release blocker remains within the approved scope. Cancellation is erroneous-bookkeeping correction, not a real bank refund; whole-batch cancellation is omitted; source/shared-settlement limitations and per-user permission/cashier denial remain as documented in the accepted IC2 review.
