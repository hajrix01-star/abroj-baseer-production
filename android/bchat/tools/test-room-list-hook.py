#!/usr/bin/env python3
"""C11 source tripwires only; native AndroidX and measured comparisons are separate evidence."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
source = root / 'app/src/main/java/com/baseer/freshchat'
activity = (source / 'OdooIdentityActivity.java').read_text(encoding='utf-8')
adapter = (source / 'BChatRoomListAdapter.java').read_text(encoding='utf-8')
row = (source / 'BChatRoomRow.java').read_text(encoding='utf-8')


def method(name):
    match = re.search(r'    private [^\n]+\b' + re.escape(name) + r'\([^\n]*\)\s*\{', activity)
    assert match, name
    opening = activity.index('{', match.start())
    depth, end = 1, opening + 1
    while depth:
        depth += (activity[end] == '{') - (activity[end] == '}')
        end += 1
    return activity[match.start():end]


render = method('renderRooms')
assert 'new BChatRoomListAdapter(' in render and 'roomRecycler.setAdapter(roomListAdapter)' in render
assert 'BChatRoomRow.filter(' in render and 'roomListAdapter.submit(' in render
assert 'admitRoomListSnapshot()' not in render
assert 'roomItems.addView(entry' not in render  # Overlay is not the authoritative row container.
owner = method('roomListOwnerCurrent')
for guard in ('roomListAdmitted', 'owner == roomListEpoch', 'account == roomListAccount',
              'epoch == roomListSession', 'historyGlobalGeneration == roomListGlobal',
              'offlineHistory == roomListOffline', 'permissionSet.chatView', 'roomsVerifiedForSession'):
    assert guard in owner, guard
resolve = method('currentRoomRow')
assert 'roomListOwnerCurrent(owner)' in resolve and 'room.membershipId == key.membership' in resolve
assert 'v1Companies.contains(room.companyId)' in resolve
clear = method('clearRoomListNow')
assert clear.index('++roomListEpoch') < clear.index('roomListAdapter.invalidateNow()') < clear.index('roomRecycler.setAdapter(null)')
assert 'roomListLane.close()' in activity
assert 'new ArrayBlockingQueue<>(1)' in adapter and 'worker.shutdownNow()' in adapter
assert 'setBackgroundThreadExecutor(worker)' in adapter and 'if(usable())' in adapter
assert 'holder.scrub(); if(!usable())return;' in adapter and 'host.current(row)' in adapter
assert 'holder.releaseAvatar()' in adapter and 'avatar.removeAllViews()' in adapter
assert 'Ui.ACTION_TONAL' in adapter and 'badge.setMinHeight' in adapter
assert 'new LinearLayout.LayoutParams(-2,Ui.dp(context,22))' not in adapter
assert 'MAX_ROOMS = 100' in row and 'Collections.unmodifiableList(result)' in row
assert 'key.equals(row.key)' in row and 'renderKey.equals(row.renderKey)' in row
assert 'membership=room.membershipId' in activity and 'currentGroupAvatar(request)' in activity
workflow = (root.parents[1] / '.github/workflows/bchat-cumulative-contracts.yml').read_text(encoding='utf-8')
assert 'test-room-list.py --label ci' in workflow
print('PASS room-list ownership, recycling, compound identity, bounded diff and UI-hook source contracts; not runtime acceptance')
