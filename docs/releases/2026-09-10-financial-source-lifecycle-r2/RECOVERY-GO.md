# IC2 R2 exact restoration approval

Decision: GO

Candidate: `3d96581c2eef324df3b5ed69f7ba526bb37035fc`.
Runner: `docs/build-governance/ic2_recovery.py`.
Runner SHA256: `ba8089d99a36a324eeb7d85b459b3eca1d34636d6417835d60102268aff36697`.
Reviewed failed-release row-diff SHA256: `36ab6b2fee000d9685fa799259f3d41b5fb9bee6eb68d3f63a66d60814a1c36c`.
Original protected-projection SHA256: `ff5e8f7c4a78a889df94a4194205de01ad268af2e00754df91ae7138efe0aa76`.

The runner matches its frozen evidence copy and has been independently reviewed. It restores only the documented preservation drift from the first update: names on 45 generated account/journal/payment-category/payment-method rows and write_uid/write_date on two partners. No amount, account mapping, journal posting, transaction state or user permission is to be altered. Each claimed original value is checked against the independently restored coherent pre-upgrade backup; each current field must equal the exact captured failed-after value.

Before mutation, require the exact candidate and both GO files, exclusive maintenance lock, stopped MAIN/no other database clients, unchanged failed projections, complete 372-table inventory, coherent backup dump hash, exact restored original projections, installed versions/security/presets, and the reviewed additive schema/defaults. One serializable SQL transaction locks all 372 protected tables, restores only the whitelisted fields and checks every original-column row projection before COMMIT. An unexpected current value or projection mismatch aborts the transaction.

After restoration, require exact protected data/security/preset results, switch only the compose source path to R2, reload the backup mapping, take a coherent stopped-service post-backup, then start and verify the pinned read-only R2 runtime. No second module upgrade or live financial fixture is authorized or needed. Preserve failed candidate/logs and original backup evidence. The separately frozen R2 source removes the translation references that caused the label drift; unchanged functional code and static translations are already installed.

This is scoped approval to execute the reviewed recovery for this exact candidate. It does not claim recovery has completed; final acceptance requires successful restored projections, runtime and source-only publication evidence. Reviewer: icons_release, with no MAIN mutations.
