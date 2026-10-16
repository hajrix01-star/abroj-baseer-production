# BChat QA transport diagnostic — 2026-10-16

Candidate `0.7.49-qa-transport-diagnostic (65)` is a QA-only Android diagnostic build. It does not modify QA, Live, database records, permissions, or cookies. It reports fixed, non-sensitive stage codes only when authenticated v2 bootstrap fails, so a device screenshot can distinguish a WebView fetch failure, a missing JavaScript callback slot, a rejected callback response, a context reset, or a failed v1 confirmation probe.

The candidate is not a production release and must be removed or disabled after the root cause is fixed.
