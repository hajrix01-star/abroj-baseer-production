#!/usr/bin/env python3
"""Source tripwires for privacy/reset/service seams; not a full Activity or OS test."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'app/src/main/java/com/baseer/freshchat'


def source(name):
    return (ROOT / (name + '.java')).read_text(encoding='utf-8')


def method(text, marker):
    begin = text.index(marker)
    opening = text.index('{', begin)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[begin:end]


push = source('BChatPushState')
clear = method(push, 'private static void clearPresentationLocked(')
assert '++s.presentationSerial;' in clear
assert 'BChatNotificationConversations.reset();' in clear
assert 'BChatNotificationPresentationReset.cancel(s.notifications);' in clear
for unrelated in ('s.epoch', 's.intent', 'BChatNotificationLedger', '.edit(', 'persistLocked('):
    assert unrelated not in clear, unrelated
load = method(push, 'private static void load(')
assert load.index('clearPresentationLocked(s);') < load.index('s.ready = true;')
gate = method(push, 'static boolean present(')
assert 's.presentationSerial != delivery.presentationSerial' in gate
invalidate = method(push, 'public static void contentInvalidated(')
assert '!s.ready' in invalidate and '!Objects.equals(scope.key, s.scope)' in invalidate
assert '!active(s)' not in invalidate and 'clearPresentationLocked(s);' in invalidate
for marker in ('static void beginPreviewChange(', 'static void beginPreviewControl(',
               'static void acceptPreviewMode('):
    assert 'previewLocked(s,' in method(push, marker), marker
assert 'previewLocked(s, acceptedMode);' in push
assert 'previewLocked(s, "none"); ++s.intent;' in push
reset = source('BChatNotificationPresentationReset')
assert '.cancelAll(' not in reset and '.getActiveNotifications()' in reset
assert 'row.getTag(), row.getId()' in reset and 'id == 0' in reset and 'id == 1' in reset
admission = method(reset, 'static boolean posting(')
assert 'MAX_KNOWN = 512' in reset and '!owned(tag, id)' in admission
assert admission.index('manager.cancel(') < admission.index('KNOWN.remove(oldest.getKey())')
assert 'catch (RuntimeException unavailable) { return false; }' in admission
assert reset.index('manager.cancel(row.getKey(), row.getValue());') < reset.index('pending.remove();')

service = source('BChatFirebaseMessagingService')
assert service.index('BChatPushState.present(') < service.index('BChatNotificationChannels.present(')
assert service.index('BChatNotificationChannels.present(') < service.index('BChatNotificationConversations.append(')
assert 'bufferPosted[0] = BChatNotificationConversations.present(projection.conversation, render);' in service
assert 'if (!posted || !channelPosted[0] || !bufferPosted[0] || !childPosted[0]) return;' in service
assert service.index('if (!posted || !channelPosted[0] || !bufferPosted[0] || !childPosted[0]) return;') < service.index('BChatNotificationLedger.recordShown(')
assert service.index('if (!BChatNotificationPresentationReset.posting(manager, notificationTag, 0)) return;') < service.index('manager.notify(notificationTag, 0,')
assert service.index('if (!BChatNotificationPresentationReset.posting(manager, account + ":bchat-summary", 1)) return;') < service.index('manager.notify(account + ":bchat-summary", 1,')
assert service.index('manager.notify(notificationTag, 0,') < service.index('childPosted[0] = true;')
assert 'projection == null ? presentationKey : projection.conversation.tag' in service
assert 'manager.cancel(tag, 0)' in service
assert 'BChatMessagingNotificationStyle.create(this, channelRoute.channelId, projection.conversation)' in service

activity = source('OdooIdentityActivity')
owner = method(activity, 'private boolean notificationPresentationOwned(')
for condition in ('scope == account', '!closed', 'verified', '!offlineHistory',
                  'receiptStorageGeneration == historyGlobalGeneration',
                  'receiptNeedsRoomRebind && receiptRebindGeneration == historyGlobalGeneration'):
    assert condition in owner, condition
for marker in ('private void applyLiveHint(', 'private void applyPermissionSet(', 'private void loadRooms('):
    body = method(activity, marker)
    assert 'notificationPresentationOwned(' in body and 'BChatPushState.contentInvalidated(' in body, marker
permissions = method(activity, 'private void refreshPermissionSet(')
assert 'notificationSession != epoch' in permissions and 'notificationGeneration != historyGlobalGeneration' in permissions
company = method(activity, 'private void restrictCompanyScope(')
assert company.index('BChatPushState.contentInvalidated(') < company.index('invalidateReceiptRoomBinding(')
assert company.index('BChatPushState.contentInvalidated(') < company.index('++historyGlobalGeneration;')
bootstrap = method(activity, 'private void verifyV2(')
for condition in ('account != notificationAccount', 'notificationSession != epoch',
                  'notificationGeneration != historyGlobalGeneration'):
    assert condition in bootstrap, condition
assert bootstrap.index('BChatPushState.contentInvalidated(') < bootstrap.index('clearChatView(')
print('PASS privacy serial, selective presentation cancellation and three final gates; source seams only, no full Activity/OS claim')
