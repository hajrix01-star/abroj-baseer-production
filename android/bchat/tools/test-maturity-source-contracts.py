#!/usr/bin/env python3
"""Wire behavior suites into release protection; these checks are not runtime acceptance."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


store = read("app/src/main/java/com/baseer/freshchat/sync/BChatConnectedMediaStore.java")
assert "new AtomicFile(json).openRead()" in store
assert "synchronized (STORE_LOCK)" in store and "Diagnostics diagnostics(" in store
assert "MAX_DIAGNOSTIC_PROBLEMS" in store
ledger = read("app/src/main/java/com/baseer/freshchat/BChatNotificationLedger.java")
assert "MAX_EVENTS = 512" in ledger and "MAX_AGE_MILLIS = 7L" in ledger
assert "new HashSet<>(stored)" in ledger and ".commit()" in ledger
service = read("app/src/main/java/com/baseer/freshchat/BChatFirebaseMessagingService.java")
assert service.index("manager.notify(notificationTag, 0,") < service.index("BChatNotificationLedger.recordShown")
assert service.index("if (!posted || !channelPosted[0] || !bufferPosted[0] || !childPosted[0]) return;") < service.index("BChatNotificationLedger.recordShown")
assert ".setOnlyAlertOnce(true)" in service
palette = read("app/src/main/java/com/baseer/freshchat/UiPalette.java")
assert "c.getColor(R.color.bchat_surface)" in palette
appearance = read("app/src/main/java/com/baseer/freshchat/ChatAppearance.java")
assert "createConfigurationContext(override)" in appearance and "override.uiMode" in appearance
ui = read("app/src/main/java/com/baseer/freshchat/Ui.java")
assert "AvatarInitials.of(name)" in ui and "static LinearLayout messageMeta(" in ui
assert "row.setContentDescription(" in ui and "getPaddingRight()" in ui
assert "bg(Color.WHITE, radius, context)).mutate()" in ui
focus = read("app/src/main/java/com/baseer/freshchat/AudioFocusLease.java")
assert "Lease reserve(Interrupted interrupted)" in focus and "if (current != this || attributes == null) return false" in focus
assert ".setOnAudioFocusChangeListener(this, main)" in focus
playback = read("app/src/main/java/com/baseer/freshchat/AudioPlayback.java")
assert playback.index("focus = audioFocus.reserve(") < playback.index("next.prepareAsync()")
prepared = playback[playback.index("private void prepared("):playback.index("void seek(")]
assert "focus.gainFocus(attributes(), false)" in prepared and "if (!gainFocus())" not in prepared
previews = read("app/src/main/java/com/baseer/freshchat/ImagePreviews.java")
assert "loadConnectedDetail(" in previews and "getCanonicalFile()" in previews
zoom = read("app/src/main/java/com/baseer/freshchat/ZoomableImageView.java")
assert "overviewSuppressed" in zoom and "!canShowDetail()" in zoom and "onDetachedFromWindow()" in zoom
draw = zoom[zoom.index("@Override protected void onDraw("):zoom.index("@Override protected void onDetachedFromWindow(")]
assert "new Matrix(" not in draw and "tileTransform.postConcat(sourceToView())" in draw
assert "sourceTransform.set(detailOrientation)" in zoom
for mode in ("values", "values-night"):
    assert (ROOT / f"app/src/main/res/{mode}/chat_colors.xml").is_file()
transfer = read("app/src/main/java/com/baseer/freshchat/BChatTransferCoordinator.java")
for required in (
    'scope.key.equals(entry.accountKey)', 'ticket.matches(entry)',
    'if(Build.VERSION.SDK_INT>=34)', '.setUserInitiated(true)',
    '.removeCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)',
    'visibleUserEligible.getAsBoolean()', 'app.startForegroundService(intent)',
    'PendingIntent.FLAG_IMMUTABLE', 'new WeakReference<>(observer)',
):
    assert required in transfer, required
for forbidden in ('NET_CAPABILITY_VALIDATED', 'NET_CAPABILITY_NOT_METERED',
                  'bindProcessToNetwork', 'getCookie(', 'AlarmManager', '.setPersisted(true)'):
    assert forbidden not in transfer, forbidden
assert 'extras.putInt(EXTRA_ID,w.id)' in transfer
assert transfer.count('extras.put') == 1  # Platform extras never carry grant/account/file data.
for test in ('TransferInstrumentation.java', 'TransferProcessDeathInstrumentation.java',
             'DraftRevisionInstrumentation.java'):
    assert (ROOT / 'tests/transfers-android/com/baseer/freshchat' / test).is_file()
workflow = (REPO / ".github/workflows/bchat-cumulative-contracts.yml").read_text(encoding="utf-8")
for test in ("test-connected-media-store.py", "test-notification-presentation.py", "test-push-routing-state.py", "test-appearance-foundations.py"):
    assert test in workflow and (ROOT / "tools" / test).is_file()
builder = read("tools/build-unified-preview.ps1")
assert "--porcelain --untracked-files=normal" in builder and "ExpectedSourceCommit" in builder
assert "ExpectedSourceBranch" in builder and "sourceBranch = $sourceBranch" in builder
assert "Source changed during the build" in builder
assert "SOURCE_DATE_EPOCH" in builder and "firebaseMessagingVerified = $true" in builder
assert "PreviousVersionCode -lt 87" in builder
assert builder.index("The reviewed release checkout must be clean") < builder.index("$signingRoot =")
print("PASS maturity behavior-suite wiring, semantic UI, bounded presentation and release-source contracts")
