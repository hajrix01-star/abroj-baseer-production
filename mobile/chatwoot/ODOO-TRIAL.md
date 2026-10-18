# BChat / Odoo Android trial

The supplied MIT Chatwoot source is preserved. The default entry now selects an isolated Odoo chat feature; `EXPO_PUBLIC_BACKEND=chatwoot` explicitly selects the upstream application. Odoo mode does not initialize the upstream Redux persistence, Reactotron, Sentry, Firebase or Chatwoot authentication. Native Android trial identity is `com.baseer.bchat.trial` (not an update to the existing BChat package).

## Scope

- Odoo user login, existing per-user chat permissions, authorized companies and membership-scoped groups/history.
- Optional company-level direct conversations; only authorized app managers/system administrators change the switch. Management is not a grant to read conversation content. Legacy nongroup rooms are not reclassified.
- Text, replies, group management, photos, supported files, M4A voice recording/playback. Android is the only implemented native session adapter for this trial; iOS needs its own verified adapter.
- Remembered history is at most 500 messages/512KiB per room and 2000 messages/2MiB per account. Old history caches may be evicted; unacknowledged work is never evicted for this quota. Offline reading is available for up to 24 hours after verification. Only previously opened/cached media is available offline. Revocation cannot be discovered without a connection; known revocation immediately hides and prunes the affected scope.
- Durable outbox: 100 operations/account, stable UUID, persisted upload result, matching server ACK before removal. App-owned staging: images5MiB, supported files/audio10MiB, aggregate50MiB. No silent eviction of unacknowledged work. Foreground reconnect sends automatically; no promise of continuous OS-background delivery.
- No ERP sections, push-notification setup, deployment, operational database changes, or production-readiness claim in this source change.

Storage is the Android app sandbox/AsyncStorage, not a new encrypted database. Passwords, session Cookies and CSRF are not persisted by the feature. A compromised/unlocked device is outside the offline-cache confidentiality guarantee.

## Backend

Install `baseer_bchat_mobile_policy` alongside the existing `baseer_bchat` on a deliberately selected trial database. It depends only on the existing BChat feature and does not install the optional purchases bridge. Assign the new Mobile app administrator user flag only to chosen managers; keep existing BChat flags. See the addon's README for the policy/API contract. Do not modify a live addon directory or production database manually.

## Local setup

Requires Node24, Java17, the existing licensed Android SDK36/NDK requested by generated Gradle, and the lockfile-pinned package manager. No credential belongs in an environment file. Copy `.env.example` to a gitignored `.env.local` and replace only the fixed HTTPS origin/database with the chosen test environment. An empty configuration intentionally displays a configuration notice; a placeholder build is not a connected Odoo trial.

```powershell
npx.cmd --yes pnpm@10.11.0 install --frozen-lockfile --ignore-scripts
npm.cmd run check:odoo
npm.cmd run test:odoo
.\node_modules\.bin\expo.cmd prebuild --platform android --no-install
.\node_modules\.bin\expo.cmd export --platform android --output-dir dist-odoo --max-workers 2
# In android/: builds locally, does not install or publish
.\gradlew.bat :app:assembleRelease '-PreactNativeArchitectures=arm64-v8a,x86_64' --no-daemon --max-workers=2 --console=plain
# Windows only, if legacy Ninja reports an existing prefab file missing/MAX_PATH:
.\gradlew.bat :app:assembleRelease '-PreactNativeArchitectures=arm64-v8a,x86_64' --init-script ../tools/windows-native-staging.gradle --no-daemon --max-workers=2 --console=plain
# A deeply nested checkout may additionally need -PbchatNativeStagingRoot=D:/path/bchat-native-trial
# Choose a new, dedicated absolute directory under the authorized workspace.
```

The generated release uses the default development certificate: private trial only, not a production signing identity. `android/local.properties` can select a separately installed official NDK if the SDK auto-download stalls; it is intentionally untracked and regeneration may replace it. The Odoo-only config plugin explicitly excludes unused Firebase/Sentry/FFmpeg/Notifee native libraries; this is independently checked rather than relying on null overrides in the supplied linker config.

Use a trusted HTTPS certificate; do not disable verification. The native adapter denies redirects and uses the existing Android Cookie jar without extracting Cookies into JavaScript. A real-device clean-session login and session-expiry check are mandatory before accepting this integration.

## Acceptance / rollback

Authoritative evidence and remaining blockers are in `docs/build-governance/CHATWOOT-ODOO-TRIAL-20261018.md` at repository root. Source tests and a JavaScript export do not prove APK installation, native Cookies, microphone compatibility, two-device messaging, or real offline recovery. Those results must be recorded separately. No existing app was replaced; removing the separate trial package is the app rollback. Backend rollout/rollback must use the project's approved release process, not direct copies.

Third-party licenses remain in the supplied source (`LICENSE`). Original branding assets are temporary; the trial name is changed, but no final proprietary visual identity is claimed.
