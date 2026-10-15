#!/usr/bin/env python3
"""Static contract checks for authoritative BChat unread badges.

They complement the Odoo receipt service test: this check makes sure Android
does not quietly restore an optimistic count update when the UI evolves.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID = (ROOT / 'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java').read_text(encoding='utf-8')
SERVER = (ROOT.parent.parent / 'custom_addons/baseer_bchat/models/v2_service.py').read_text(encoding='utf-8')


def method(source, name):
    start = source.index('    def ' + name + '(')
    end = source.find('\n    @', start + 1)
    return source[start:] if end < 0 else source[start:end]


receipt = method(SERVER, '_v2_receipt_ack')
assert "candidate.room_id = %s" in receipt
assert "candidate.company_id = %s" in receipt
assert "receipt.read_at IS NULL" in receipt
assert "'unread_count': unread_count" in receipt
assert "'last_message_id': last_message_id" in receipt

start = ANDROID.index('private void acknowledgeMessage(')
end = ANDROID.index('    /** A read ACK is emitted', start)
ack = ANDROID[start:end]
assert 'nonnegativeCursor(result.get("unread_count"))' in ack
assert 'nonnegativeCursor(result.get("last_message_id"))' in ack
assert 'candidate.sameMembership(room)' in ack
assert 'candidate.lastMessageId != responseLastMessageId' in ack
assert 'requestRoomMetadataGeneration != roomMetadataGeneration' in ack
assert 'if ("read".equals(kind)) {' in ack
assert 'room.unreadCount--' not in ack
assert 'room.unreadCount = 0;' not in ack

rooms_start = ANDROID.index('private void loadRooms()')
rooms_end = ANDROID.index('private void selectRoom(', rooms_start)
rooms = ANDROID[rooms_start:rooms_end]
assert 'final int requestUnreadMetadataGeneration = unreadMetadataGeneration;' in rooms
assert 'requestUnreadMetadataGeneration != unreadMetadataGeneration' in rooms
assert 'loadRooms();' in rooms
print('PASS authoritative post-ack unread-count contract')
