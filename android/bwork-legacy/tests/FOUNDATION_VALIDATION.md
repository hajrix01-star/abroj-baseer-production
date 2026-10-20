# Reconstructed UI foundations validation

## Final candidate02 evidence identity

Evidence archive: `BChat-0.5.0-Independent-Preview-QA-Evidence.zip`, 19,806,424 bytes; SHA-256 `8a597d0e9f0574660255e5b6cb97812e7e14fceb9e7fa2d55e88f9c480ed7506`.

Acceptance record `RUNTIME-ACCEPTANCE.json`: SHA-256 `994091fbb463e04b521291531c4bb003d9c5262871040fff7e3259961b3eaff5`; status `accepted_scoped`. Termination of the owned runtimes was observed. No acceptance outside the stated scope is implied.

## Current candidate02: frozen for scoped owner review

The exact candidate02 APK passed 94 ordinary assertions and 5 native-media cases / 45 assertions separately on API 27, API 29 and API 35. The unchanged API 35 orientation diagnostic verifies the AppLocale configuration fix. API 29 reinstall of the same APK added 16 repeated preservation assertions; the genuine old 0.4.4 APK and all four synthetic old-package files stayed byte-identical. The old-fixture manifest SHA-256 is `645ba261d3c9aff357061b7f98e4e50c8c2174141a30b3c258ab88ffeac5c778`. This is scoped emulator acceptance, not physical-device, old-package upgrade or complete audit acceptance.

Current APK: 340,961 bytes, SHA-256 `44bc529fb288ceab8813428f68d850a2da80c223ded9a5ff1b71d0274a57b601`. Direct 62-file app-source manifest SHA-256: `3f162b7622e0fdd48b4fe56a30ce566107cb1ebd5d141217dd2452b8e687e2ff`. Fresh signed standalone build and full host/source aggregate pass; lint reports 0 errors / 58 warnings. Candidate01 evidence below is historical: its supplementary 1,259 layout checks and 1,340 bubble assertions were not rerun on candidate02. PDF is first-page preview only, without PDF zoom or page navigation. Physical, specialized failure/resource/security, backend/DMS, capture-wiring and durable secure signer-backup gates remain open.

These sources were reconstructed after an execution-environment loss on 2026-10-08. Results for the unavailable earlier candidate do not establish acceptance of these bytes.

## Fresh checks

- Editor model and ordinary disposable file-I/O failures: 16 checks passed.
- Recovery admission through the actual MainActivity static code: 17 checks passed on a host JVM.
- Bounded transcript writer: Unicode boundary, atomic overflow, 128 Ki character budget and interruption checks passed.
- Source contracts: entry 13, menus 16, bubbles 17, bottom navigation 12, localization 16 and foundations 8 passed.
- Application Java/resources and the reconstructed editor instrumentation compiled. Bubble, entry/layout, entry-boundary and entry-lifecycle instrumentation also compiled and packaged as unsigned compile-check artifacts.

At source007, no reconstructed Android UI instrumentation execution was claimed and no substitute signer had been generated. Those unsigned packages remain compilation-only evidence. The owner later authorized a separate package, `com.baseer.bchat.preview`, with a new signer; the original key is still required for an update to the old app.

## Historical candidate01 installed-app checkpoint

The exact APK SHA-256 `6a5127b5e4fe31e70bf9582bc52a4058a31c47390ace4bb2397bf64e3bac7cb9` passed 86 ordinary API 29 app assertions, 8 entry/layout configurations / 1,259 checks and 112 bubble cases / 1,340 assertions, plus the separately recorded media suite. Same-APK reinstall passed an additional 15 preservation assertions. API 27 passed 86 ordinary assertions, 5 media cases / 45 assertions and 112 bubble cases / 1,340 assertions; its 86 include the final 15 separate-process preservation assertions. API 27 supplementary entry/layout was not run because its pre-29 path uses hidden framework inspection. Candidate01 was superseded after the API 35 configuration defect; current candidate02 acceptance is recorded above.

Ordinary draft/reply/image restoration, durable read state, search selection, rotation/recreation selection and search retention, explicit reply cancellation and one send were exercised. This does not claim the specialized failed-save/orphan/capacity harness passed. The entry harness was repaired afterward without changing app bytes; that later harness revision is not retroactively included in the native pass. See `../VALIDATION_0_5_0.md` and `../../../docs/bchat/FUNCTIONAL_QA.md` for exact-source and runtime evidence.

## Native editor harness

`EditorFoundationInstrumentation` provides `editor`, `orphan`, `capacity`, and combined `all` modes. It requires an explicitly authorized disposable installation and the argument `disposable=true`.

The fixture is installed before Activity startup. The suite preserves every preexisting private-file SHA-256 and the semantic values of each touched preference map. The failure fixture temporarily replaces only its own metadata-root file with an empty directory, restores that root, and retries. It does not exercise malformed serialization or security probes.

Coverage includes failed navigation/logout/language gating; text, attachment exclusion and quote cancellation after actual recreation; ordinary send idempotence; failed preview saves; read-only recovery; the four-editor limit for both draft and preview mutations; and legacy preview caption/file-selection migration once space becomes available.

## Legacy harness readiness

Bubble geometry and all three entry variants retain their existing measurement/layout assertions. They now wait for asynchronous store readiness, install only their owned fixture before launching the Activity, and use `UiFixtureGuard` to preserve preexisting private files, preferences and process-owned editor state. A live prior target Activity causes a setup refusal instead of silently replacing its store. Force-stop the disposable target before starting a suite.

Entry lifecycle staged process checks use a version-2 checkpoint containing baseline file hashes and preferences. Run the documented stages in sequence or the explicit `restore` stage. Do not run a second suite between stages.

Harnesses remove only explicitly owned fixture roots/sidecars and files. They do not sweep randomly named journal segments from the shared private directory; some synthetic journal bytes may remain in the disposable installation. No automatic orphan cleanup is introduced into the application.

## Commands

With an official SDK and freshly compiled application classes:

- `bash tools/test-editor-state.sh`
- `BCHAT_CLASSES=<fresh classes> bash tools/test-recovery-admission.sh`
- `python3 tools/test-foundation-ui-contracts.py`
- `BCHAT_UNSIGNED_ONLY=1 BCHAT_CLASSES=<fresh classes> bash tools/build-editor-tests.sh`
- `BCHAT_UNSIGNED_ONLY=1 APP_CLASSES=<fresh classes> bash tools/build-bubble-tests.sh`
- `BCHAT_UNSIGNED_ONLY=1 APP_CLASSES=<fresh classes> ENTRY_LAYOUT_VARIANT=layout bash tools/build-entry-layout-tests.sh`

The entry variants are `layout`, `boundary`, and `lifecycle`. Do not mistake successful compilation for native execution. Device testing requires a correctly signed candidate and explicit ownership of the single disposable emulator.
