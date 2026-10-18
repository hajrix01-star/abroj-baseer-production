#!/usr/bin/env python3
"""Source tripwires for the real receipt-details Host, not an Activity/device journey.

The native component has separate Dialog/JSON tests with a declared fake Host.
These checks keep its real Host GET-only and scoped until full product acceptance.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
activity = (ROOT / 'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java').read_text(encoding='utf-8')


def method(marker):
    begin = activity.index(marker)
    opening = activity.index('{', begin)
    depth, end = 1, opening + 1
    while depth:
        depth += (activity[end] == '{') - (activity[end] == '}')
        end += 1
    return activity[begin:end]


host = method('private void showMessageDetails(')
assert 'positiveId(item.opt("author_user_id")) != scopedAccount.userId' in host
assert host.index('!stillCurrent(scopedAccount, room)') < host.index('new BChatReceiptDetailsPanel(')
assert 'receiptDeliverySupported && receiptsAvailable' in host
for condition in ('captured == scopedAccount', 'requestedRoom == room.id',
                  'requestedMembership == room.membershipId', 'requestedMessage == messageId',
                  'requestedGeneration == generation'):
    assert condition in host, condition
assert host.count('receiptDetailsBinding(scopedAccount, room, session, generation)') >= 3
assert 'reply == null || !liveForeground || v2Busy || csrfToken == null' in host
assert 'ReceiptDetailsProtocol.path(room.id, messageId, afterId)' in host
assert 'fetchV2("GET", path, null' in host
assert '"POST"' not in host and 'enqueueLive(' not in host
assert 'if (statusCode == 401)' in host and 'handleV2TransportFailure(statusCode)' in host
assert host.index('new BChatReceiptDetailsPanel(') < host.index('// Read-only legacy aggregate')

binding = method('private boolean receiptDetailsBinding(')
for condition in ('!offlineHistory', '!recheckOnResume', 'session == epoch',
                  'generation == mediaSessionGeneration', 'roomsVerifiedForSession',
                  'v1Companies.contains(room.companyId)', 'receiptDeliverySupported',
                  'receiptsAvailable', 'chatAllowed()', 'stillCurrent(scope, room)'):
    assert condition in binding, condition
scope = method('private boolean stillCurrent(')
for condition in ('!closed', 'verified', 'account == verifiedAccount',
                  'selectedRoom == room', 'rooms.contains(room)'):
    assert condition in scope, condition
for marker in ('private void clearChatView(', 'private void showRooms(',
               'private void selectRoom(Room room, long notifiedMessageId)',
               '@Override protected void onDestroy('):
    assert 'closeReceiptDetails();' in method(marker), marker
assert 'if (!next.chatView) closeReceiptDetails();' in method('private void applyPermissionSet(')
assert 'receiptDetailsPanel.pause();' in method('@Override protected void onPause(')
assert 'receiptDetailsPanel.resume();' in method('@Override protected void onResume(')

panel = (ROOT / 'app/src/main/java/com/baseer/freshchat/BChatReceiptDetailsPanel.java').read_text(encoding='utf-8')
assert 'host.current(scope, roomId, membershipId, messageId, bindingGeneration)' in panel
assert 'serial == requestSerial' in panel and 'paused = true; ++requestSerial;' in panel
assert 'postDelayed(' not in panel and 'fetchV2(' not in panel and '"POST"' not in panel
assert 'rows.removeAllViews();' in panel and 'String.format(Locale.ROOT, "%d", value)' in panel
assert 'ReceiptDetailsProtocol.page(body, roomId, membershipId, messageId, after)' in panel
print('PASS real receipt-details Host read-only path, identity/epoch/lifecycle source tripwires; no runtime Activity claim')
