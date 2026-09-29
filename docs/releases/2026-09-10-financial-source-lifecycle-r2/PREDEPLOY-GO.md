# IC2 R2 exact source acceptance

Decision: GO

Candidate: `3d96581c2eef324df3b5ed69f7ba526bb37035fc`.
Accepted baseline: `24bc64d2a778590e8e8e6577eb3866d18727bc24`.
Failed preservation candidate retained separately: `31330640045c448f453f0430a9caa9fd66c74f5a`.

Reviewer independently verified the clean frozen Git HEAD, all 1,181 source hashes, every source ZIP entry and all twenty evidence bindings. All 1,166 unchanged IC1 files remain identical. Archive SHA256: `ef8d117ee9376c70df7c2863c9ed210427f57245e42377308b1e8717d5b6911f`.

Relative to the failed candidate, the sole difference is `baseer_pos_summary/i18n/ar.po`: removal of 45 generated-record translation occurrences and 12 entries. Independent semantic comparison proved all 451 retained static translations, flags and references unchanged. Python/XML, versions, schema, correction PO and functional behavior are identical. The final 47-file UI source inventory and all twenty UI artifacts match. PASS60 core, PASS38 summary, both real concurrency cases and actual browser accounting evidence therefore remain applicable without repeated financial/UI tests.

GO covers the already-authorized R2 source and separately approved exact-data restoration runner. It does not authorize another module update: installed functional/schema/static-translation state already matches R2. The original preservation failure is not represented as successful deployment. Recovery must restore and verify every protected original value before runtime startup, followed by coherent backup and source-only remote/CI acceptance.

Reviewer: icons_release; no production data mutation or recovery execution.
