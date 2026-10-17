#!/usr/bin/env python3
"""Read-only source/package safety assertions; these do not replace Android runtime tests."""
from pathlib import Path
import xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[1]
manifest=ET.parse(root/'app/src/main/AndroidManifest.xml').getroot()
a='{http://schemas.android.com/apk/res/android}'
assert manifest.attrib['package']=='com.baseer.bchat.preview'
permissions={e.get(a+'name') for e in manifest.findall('uses-permission')}
assert permissions=={'android.permission.POST_NOTIFICATIONS','android.permission.VIBRATE','android.permission.RECORD_AUDIO','android.permission.INTERNET','android.permission.ACCESS_NETWORK_STATE'}, 'Only explicitly used demo and Odoo identity permissions are allowed'
app=manifest.find('application')
assert app.get(a+'allowBackup')=='false'
assert app.get(a+'supportsRtl')=='true'
assert app.get(a+'usesCleartextTraffic')=='false'
assert app.get(a+'networkSecurityConfig')=='@xml/bchat_network_security'
identity_activity=next(e for e in app.findall('activity') if e.get(a+'name')=='com.baseer.freshchat.OdooIdentityActivity')
assert identity_activity.get(a+'exported')=='true' and identity_activity.get(a+'launchMode')=='singleTask'
identity_actions={e.get(a+'name') for e in identity_activity.findall('intent-filter/action')}
assert {'android.intent.action.MAIN','android.intent.action.SEND','android.intent.action.SEND_MULTIPLE'} <= identity_actions
provider=app.find('provider')
assert provider.get(a+'exported')=='false'
activity=next(e for e in app.findall('activity') if e.get(a+'name')=='com.baseer.freshchat.MainActivity')
assert activity.get(a+'windowSoftInputMode')=='adjustResize'
assert activity.get(a+'exported')=='false' and not activity.findall('intent-filter')
assert ET.parse(root/'app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml').getroot().tag=='adaptive-icon'
for path in (root/'app/src/main/res').rglob('*.xml'): ET.parse(path)
source=(root/'app/src/main/java/com/baseer/freshchat/MainActivity.java').read_text(encoding='utf-8')
for snippet in ['previewShareId', 'sendPendingShare(value.shareId, co, cv, value.text, value.files, value.sendToken)', 'cleanupAttachments()', 'if (isShare(intent)) handleIncomingShare(intent)','pickerSharing','previewCompany','sendPendingShare(', 'pickCompany','isDestroyed()', 'PdfPreviewView', 'LengthFilter(ChatStore.MAX_TEXT_LENGTH)']:
 assert snippet in source, snippet
print('PASS manifest, isolated Odoo identity permission, adaptive icon, XML, and critical demo source contracts')

notifications=(root/'app/src/main/java/com/baseer/freshchat/DemoNotifications.java').read_text(encoding='utf-8')
for required in ['FLAG_IMMUTABLE', 'IMPORTANCE_HIGH', 'TYPE_NOTIFICATION', 'postingBlockerId(context)', 'MAIN.postDelayed', 'OPEN_ACTION', 'setLocalOnly(true)']:
 assert required in notifications, required
assert not app.findall('service') and not app.findall('receiver')
assert 'AlarmManager' not in notifications
assert 'setBypassDnd' not in notifications
print('PASS bounded user-triggered local notification source contracts; no alarm, service, receiver, or DND bypass')

list_screen=source[source.index('private void showList()'):source.index('private void updateInbox()')]
assert 'addMainToolbar()' in list_screen and 'inboxSearchExpanded ? View.VISIBLE : View.GONE' in list_screen
assert 'bottomNav()' not in source and 'addFilter(' not in list_screen
assert 'VoiceGestureState.Action.STOP_FOR_PREVIEW' in source
assert 'suppressComposerClick = true; view.performClick()' in source
assert 'hasAudioDraft()' in source and 'compactDrafts && hasAudioDraft()' in source
assert '.deleteMessageLocally(' in source and 'confirmLocalDelete' in source
print('PASS compact default toolbar, collapsed search, hold-release click suppression, compact audio preview, and local delete confirmation source contracts')

assert app.get(a+'label')=='BChat'
assert int(manifest.get(a+'versionCode', '0')) >= 22
assert 'AudioPlayback' in source and 'VoicePlayerView' in source and 'AudioWaveforms' in source
assert 'addMainSections()' in source and 'showSettings()' in source
assert 'mainSection = "list"' in source
canonical=root.parent.parent/'custom_addons/baseer_basser_workspace/static/description/baseer-mark-b.png'
if canonical.exists(): assert (root/'app/src/main/res/drawable-nodpi/baseer_mark_b.png').read_bytes()==canonical.read_bytes(), 'Original B must remain byte-identical'
login_mark=(root/'app/src/main/java/com/baseer/freshchat/EntryMarkView.java').read_text(encoding='utf-8')
vector_mark=(root/'app/src/main/res/drawable/bchat_mark_hq.xml').read_text(encoding='utf-8')
master_mark=(root/'app/src/main/res/raw/bchat_mark_hq.svg').read_text(encoding='utf-8')
assert 'R.drawable.bchat_mark_hq' in login_mark and 'original.draw(canvas)' in login_mark
assert 'android:pathData' in vector_mark and 'viewBox="0 0 2048 2048"' in master_mark
print('PASS BChat identity, supplied vector login mark, original launcher asset, main sections, settings and shared audio controls')

waveforms=(root/'app/src/main/java/com/baseer/freshchat/AudioWaveforms.java').read_text(encoding='utf-8')
player_view=(root/'app/src/main/java/com/baseer/freshchat/VoicePlayerView.java').read_text(encoding='utf-8')
assert 'new LinkedBlockingQueue<>(8)' in waveforms and 'pending.size() >= 8' in waveforms
assert 'worker.remove((Runnable)job.task)' in waveforms and 'pending.get(key) != job' in waveforms
assert 'analysis.cancel()' in player_view and 'isAttachedToWindow()' in player_view
assert 'MediaCodec' in waveforms and 'getShort() / 32768f' in waveforms
assert 'target.conversationTitle)' not in notifications and 'target.companyName)' not in notifications
print('PASS bounded/cancellable local PCM analysis, detached-view fencing and generic private notifications')

import re
gradle=(root/'app/build.gradle').read_text(encoding='utf-8')
build_script=(root/'tools/build-apk.sh').read_text(encoding='utf-8')
# Gradle overrides legacy source-manifest labels; it is the signed APK's version source.
version_match = re.search(r"versionCode\s+(\d+)\b", gradle)
assert version_match and int(version_match.group(1)) >= 73, 'BChat instant-push profile candidate requires versionCode 73 or newer'
assert "versionName '0.7.62-qa-vector-brand'" in gradle
assert "BCHAT_TRANSPORT_DIAGNOSTICS', 'false'" in gradle
assert "BCHAT_PUSH_REGISTRATION_DIAGNOSTICS', 'true'" in gradle
assert 'installed.versionName' in source and 'getLongVersionCode()' in source
assert 'showWhatsNew()' in source
assert 'الإصدار 0.3.0' not in source and 'الإصدار 0.4.0' not in source
print('PASS QA Gradle release version, installed-package About version and in-app push-registration trace')

push=(root/'app/src/main/java/com/baseer/freshchat/BChatFirebaseMessagingService.java').read_text(encoding='utf-8')
for required in ('bchat-events-v3', 'setSound(Settings.System.DEFAULT_NOTIFICATION_URI',
                 'setVisibility(Notification.VISIBILITY_PRIVATE)', 'message_preview',
                 'sender_name', 'Notification.BigTextStyle'):
 assert required in push, required
assert 'android.permission.ACCESS_NETWORK_STATE' in permissions

assert notifications.index('channel.setVibrationPattern(') < notifications.index('channel.enableVibration(settings.vibration(CATEGORY))'), 'Apply vibration Off after Android pattern setter'
notification_start=notifications[notifications.index('static String start('):notifications.index('private static String post(')]
assert notification_start.index('MAIN.removeCallbacks(pending)') < notification_start.index('.mute(target.companyId'), 'Muted new test must still cancel the earlier pending test'
print('PASS vibration-off setter ordering and pending-test replacement before mute checks')

assert 'compile --no-crunch --dir' in build_script
assert 'cruncherEnabled = false' in gradle
print('PASS original brand PNG crunching disabled for standalone and Gradle builds')

foreground=ET.parse(root/'app/src/main/res/drawable/ic_foreground.xml').getroot()
bitmap=foreground.find('bitmap')
assert bitmap is not None and bitmap.get(a+'src')=='@drawable/baseer_mark_b' and bitmap.get(a+'tint')=='#FFFFFF'
print('PASS launcher uses original B with XML white tint on navy; wordmark keeps original navy B')

assert 'final boolean busy' in waveforms and 'new Result(0, null, true)' in waveforms
assert 'if (result.busy)' in player_view and 'postDelayed(analysisRetry, 750)' in player_view
assert 'removeCallbacks(analysisRetry)' in player_view and 'epoch != analysisEpoch' in player_view
print('PASS decoder saturation is a bounded cancellable retry, distinct from unsupported media')

import runpy
runpy.run_path(str(root/'tools/check-icon-geometry.py'),run_name='__main__')

assert "keytool -genkeypair" not in build_script, "Do not invent a new signing identity"

assert 'final EditorState.Snapshot value = editor.beginSend(' in source
assert 'STORE_IO.execute(() -> {' in source
assert 'if (!beforeNavigation(() -> handleIncomingShare(intent)))' in source
print('PASS complete reviewed editor snapshot and save-aware deferred share intent contracts')

assert "System.getenv('BCHAT_SIGNING_KEY')" in gradle
assert "System.getenv('BCHAT_SIGNING_PASSWORD_FILE')" in gradle
assert re.search(r'debug\s*\{\s*signingConfig signingConfigs\.preview', gradle)
assert re.search(r'release\s*\{\s*signingConfig signingConfigs\.preview', gradle)
print('PASS independent preview requires an explicitly supplied local signer; no implicit replacement signer')

identity=(root/'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java').read_text(encoding='utf-8')
assert 'networkAvailable() && offerOfflineHistory()' in identity
assert 'scrollAfterOwnSend = true;\n                            loadMessages(0);' in identity
assert 'channel.getImportance() < NotificationManager.IMPORTANCE_DEFAULT' in identity
assert 'channel.getSound() == null' in identity
assert 'Settings.ACTION_APP_NOTIFICATION_SETTINGS' in identity
verified_push = identity[identity.index('applyPermissionSet(account, granted);'):identity.index('profileSnapshot = verifiedProfile;')]
assert 'maybeRegisterPush();' not in verified_push
assert 'if (chatAllowed()) loadRooms();' in identity
assert 'handler.post(this::maybeRegisterPush);' in identity
clear_chat=identity[identity.index('private void clearChatView()'):identity.index('private void queueHistoryWrite(')]
assert 'pendingPushRoomId = 0;' in clear_chat and 'pendingPushRoomMessageId = 0;' in clear_chat
print('PASS private chat previews, replacement sound channel, deferred push registration and immediate offline history fallback')
assert 'private static final String ORIGIN = RuntimeOrigin.forHardware(Build.HARDWARE, BuildConfig.BCHAT_ORIGIN);' in identity
assert '"https".equals(uri.getScheme())' in identity
assert 'expected.getHost().equals(uri.getHost()) && uri.getPort() == expected.getPort()' in identity
assert '"https://localhost:18443"' in gradle and 'bchatEmulatorLocal' in gradle
assert '"https://baseer-live-qa.tail938958.ts.net"' in gradle
assert '"baseer_live_qa_clean_20260928"' in gradle
assert '"https://desktop-cvc68i5.tail938958.ts.net:18444"' not in gradle
assert 'return configuredOrigin;' in (root/'app/src/main/java/com/baseer/freshchat/RuntimeOrigin.java').read_text(encoding='utf-8')
assert '"http://' not in gradle
print('PASS Odoo identity WebView is pinned to the selected HTTPS build origin')
assert source.index('redirectToEmployeeEntry(getIntent())') < source.index('openStore(saved)')
assert 'redirectToEmployeeEntry(intent)' in source and 'destination.putExtra(OdooIdentityActivity.EXTRA_SHARE_UNAVAILABLE, true)' in source
for required in ('f.requestSubmit()', 'csrf_token', 'CookieManager.getInstance().flush()',
                 'getBoolean(REMEMBER, false)', 'putBoolean(REMEMBER, canRemember)',
                 'auth_native_title', 'auth_shell_unavailable', 'auth_share_unavailable'):
 assert required in identity, required
for forbidden in ('postUrl(', 'onReceivedClientCertRequest', 'setAcceptThirdPartyCookies(web, true)'):
 assert forbidden not in identity, forbidden
assert 'private static boolean isLoginPath(String path)' in identity
assert 'isLoginPath(path)' in identity and 'isLoginPath(page.getPath())' in identity
assert 'location.pathname===\'/web/login\'' in identity and 'A-Za-z0-9_-' in identity
assert 'navigationFailed = true;' in identity and 'currentWeb != webEpoch || navigationFailed' in identity
for required in ('BRIDGE_PATH = "/bchat/app/bridge"',
                 'LOGIN = ORIGIN + "/web/login?db=" + Uri.encode(DATABASE)',
                 'private static final String DATABASE = BuildConfig.BCHAT_DATABASE;',
                 'private static boolean isBridgeUrl(Uri uri)',
                 'BRIDGE.equals(uri.toString())', 'private void divertErp(WebView view, int expectedWeb)',
                 'if (request.isForMainFrame() && isErpPath(path))',
                 'if (isErpPath(page.getPath()))', 'if (!allowedMainFrame(page))',
                 'if(location.href!==', 'openWeb(BRIDGE);'):
 assert required in identity, required
assert 'openWeb(ORIGIN + "/odoo")' not in identity
assert identity.count('|| !isBridgeUrl(Uri.parse(web.getUrl()))') >= 3
print('PASS native employee entry, no demo-store startup, same-origin official login form, session-only remember and disabled sharing')

v2_outbox=(root/'app/src/main/java/com/baseer/freshchat/sync/BChatV2Outbox.java').read_text(encoding='utf-8')
for required in ('/bchat/api/v2/bootstrap', '/bchat/api/v2/rooms', 'author_name',
                 'new WebMessagePort[]{channel[1]}', 'redirect:\'manual\'',
                 'MAX_V2_RESPONSE = 131072', 'probeV1AfterTransportFailure(writeRequest)',
                 'room.membershipId', 'outbox.acknowledge(account, entry)'):
 assert required in identity, required
for required in ('account_key', 'membership_id', 'client_uuid', 'Resolve the pending message first'):
 assert required in v2_outbox, required
for required in ('firstStale(AccountScope account', 'convertToDraft(AccountScope account',
                 'discard(AccountScope account', 'createDraftTable(db)',
                 'account_key=? AND room_id=? AND membership_id<>?', 'db.setTransactionSuccessful()',
                 'pageForAccount(AccountScope account', 'recordRejected(AccountScope account',
                 'review_code INTEGER NOT NULL DEFAULT 0'):
 assert required in v2_outbox, required
for required in ('clearChatView();\n            account = nextAccount',
                 'if (initial) {\n                    shell.setVisibility(View.GONE);',
                 'outbox.firstStale(account, selectedRoom.id, selectedRoom.membershipId)',
                 'confirmConvertToDraft(verifiedAccount, room, entry)',
                 'confirmDiscard(verifiedAccount, room, entry)',
                 'flushDraftSave();', 'chat_v2_uncertain', 'draftActive = true;',
                 'showGlobalPending(0)', 'confirmGlobalConvert(verifiedAccount, entry, choices.get(which))',
                 'outbox.recordRejected(account, entry)', 'pending.reviewCode == 1'):
 assert required in identity, required
assert 'new ChatStore(' not in identity and 'MainActivity.class' not in identity
assert 'CookieManager.getInstance().getCookie(' not in identity
assert 'clipboard.getPrimaryClip(' not in identity and 'clipboard.getPrimaryClipDescription(' not in identity
print('PASS v2 bounded transport, fresh room gate, account-scoped pending recovery, persistent rejection, atomic draft migration, and no native cookie/clipboard extraction')

assert provider.get(a+'authorities')=='com.baseer.bchat.preview.files'
assert activity.get(a+'name')=='com.baseer.freshchat.MainActivity'
assert provider.get(a+'name')=='com.baseer.freshchat.DemoFileProvider'
assert "applicationId 'com.baseer.bchat.preview'" in gradle
assert '--custom-package com.baseer.freshchat' in build_script
assert 'getPackageName() + ".files/"' in source
assert 'content://com.baseer.freshchat.files/' not in source
print('PASS separate preview package/provider with original Java namespace and dynamic camera authority')
assert manifest.get(a+'sharedUserId') is None, 'Independent preview must not share an Android UID'
assert not app.findall('uses-library'), 'No shared application library is introduced'
print('PASS independent Android sandbox declaration; no shared UID')

gradle_manifest=ET.parse(root/'app/src/gradle/AndroidManifest.xml').getroot()
push_manifest=ET.parse(root/'app/src/gradle/AndroidManifestPush.xml').getroot()
assert gradle_manifest.get('package') is None
canonical_manifest=ET.fromstring(ET.tostring(manifest))
canonical_manifest.attrib.pop('package')
standalone_sdk=canonical_manifest.find('uses-sdk')
gradle_sdk=gradle_manifest.find('uses-sdk')
assert standalone_sdk is not None and gradle_sdk is not None
assert standalone_sdk.attrib==gradle_sdk.attrib
canonical_manifest.remove(standalone_sdk)
gradle_manifest.remove(gradle_sdk)
assert ET.tostring(canonical_manifest)==ET.tostring(gradle_manifest), 'Standalone and Gradle manifests must match except package attribute'
assert "'src/gradle/AndroidManifest.xml'" in gradle
assert "'src/gradle/AndroidManifestPush.xml'" in gradle
push_app=push_manifest.find('application')
push_service=next(e for e in push_app.findall('service') if e.get(a+'name')=='com.baseer.freshchat.BChatFirebaseMessagingService')
assert any(action.get(a+'name')=='com.google.firebase.MESSAGING_EVENT'
           for action in push_service.findall('intent-filter/action'))
print('PASS package-free AGP input exactly matches standalone app manifest semantics')
