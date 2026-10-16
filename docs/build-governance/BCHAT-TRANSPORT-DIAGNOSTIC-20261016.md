# BChat QA transport diagnostic — 2026-10-16

Candidate `0.7.49-qa-transport-diagnostic (65)` was a QA-only Android diagnostic build. It did not modify QA, Live, database records, permissions, or cookies. Its safe, fixed stage codes established that v1 authentication and the direct v2 bootstrap both returned HTTP 200, while the next transferred `WebMessagePort` request (`/rooms`) failed and caused the misleading generic connection shell.

Recovery candidate `0.7.50-qa-direct-read-recovery (66)` therefore makes bounded, authenticated idempotent GET reads use the same verified direct WebView callback that succeeded for bootstrap. POST routes retain the existing port path and uncertain-write safeguards; no write is retried or converted. Diagnostic UI is disabled in v66. This remains QA-only and requires real-device acceptance before any promotion decision.
