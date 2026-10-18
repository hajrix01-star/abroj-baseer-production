#!/usr/bin/env python3
"""Focused BChat source contracts; emulator/phone behavior is checked separately."""

from pathlib import Path

source = (Path(__file__).resolve().parents[1] /
          "app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java").read_text(encoding="utf-8")


def body(signature):
    start = source.index("{", source.index(signature))
    depth = 1
    for index in range(start + 1, len(source)):
        depth += (source[index] == "{") - (source[index] == "}")
        if depth == 0:
            return source[start + 1:index]
    raise AssertionError(f"Unclosed method: {signature}")


checks = {
    "Timeline uses recycled views and stable message IDs":
        "new RecyclerView(this)" in source
        and "setHasStableIds(true)" in source
        and "Math.max(1, displayedMessages.size() + localTextRows.size())" in source,
    "Connected older pages prepend within bounded window":
        "MAX_CONNECTED_MESSAGE_WINDOW = 500" in source
        and "for (JSONObject item : fetched) byId.put" in body("private List<JSONObject> messageWindow(")
        and "for (JSONObject item : displayedMessages) byId.put" in body("private List<JSONObject> messageWindow("),
    "Unchanged polls do not rebuild every visible bubble":
        "publishMessageRows(window, localTextRows)" in body("private void updateMessageRows(")
        and "BChatTimelineChangePlan.between(messageRowSnapshot, next)" in body("private boolean publishMessageRows(")
        and "plan.removeOldDescending" in body("private boolean publishMessageRows(")
        and "plan.insertNewAscending" in body("private boolean publishMessageRows(")
        and "plan.changeNewPositions" in body("private boolean publishMessageRows(")
        and ".toString()" not in body("private BChatTimelineRows.Snapshot projectMessageRows("),
    "Offline older pages remain an explicit action":
        "if (offlineHistory || olderPageLoading" in body("private void maybeLoadOlderMessages()")
        and "offlineHistory || olderPageFailed" in body("private void updateOlderControl()"),
    "A short first page loads until scrolling is possible":
        "!messageScroll.canScrollVertically(-1)" in body("private void renderMessageWindowWithLocals(")
        and "!messageScroll.canScrollVertically(1)" in body("private void renderMessageWindowWithLocals("),
    "Timeline ownership is captured before reads and never borrowed by projection":
        "final TimelineWindowOwner readOwner = new TimelineWindowOwner(room)" in body("private void loadMessages(")
        and "!readOwner.bindingCurrent()" in body("private void loadMessages(")
        and "admitMessageTimelineOwner(readOwner)" in body("private void loadMessages(")
        and "new TimelineWindowOwner" not in body("private BChatTimelineRows.Snapshot projectMessageRows(")
        and "admitMessageTimelineOwner" not in body("private boolean publishMessageRows("),
    "Identity and rights changes scrub before replacing the timeline owner":
        "++messageWindowAdmissionEpoch" in body("private void invalidateMessageTimelineOwner(")
        and "holder.container.removeAllViews()" in body("private void clearMessageTimelinePresentation(")
        and "messageScroll.setAdapter(null)" in body("private void clearMessageTimelinePresentation(")
        and "getRecycledViewPool().clear()" in body("private void clearMessageTimelinePresentation(")
        and all("invalidateMessageTimelineOwner()" in body(marker) for marker in (
            "private void clearChatView(", "private void applyPermissionSet(",
            "private void restrictCompanyScope(", "private void selectRoom(Room room, long")),
    "Local states and durable retirement use the same atomic publication":
        "publishMessageRows(displayedMessages, snapshot.text)" in body("private void refreshLocalRoom(")
        and "localTextRows.removeIf" not in body("private void reconcileTextReceipt(")
        and "renderMessageWindowWithLocals(room, window, anchor.atBottom, 0, anchor, remaining)" in body("private void reconcileTextReceipt("),
    "Own-send position intent is captured before enqueue and bound to the exact durable entry":
        body("private void sendText()").index("captureTimelineSendOrigin()")
        < body("private void sendText()").index("box.enqueue(")
        and "rememberTimelineSendFollow(sendOrigin, entry)" in body("private void sendText()")
        and "entry.id == follow.id && follow.uuid.equals(entry.uuid)" in body("private void admitTimelineSendFollow(")
        and "messageScroll.getAdapter() != messageAdapter" in body("private TimelineSendOrigin captureTimelineSendOrigin(")
        and "messageScroll.isLayoutRequested()" in body("private TimelineSendOrigin captureTimelineSendOrigin(")
        and "hasPendingAdapterUpdates()" in body("private TimelineSendOrigin captureTimelineSendOrigin("),
    "Local follow is presentation-only and includes local rows after canonical records":
        "admitTimelineSendFollow(nextLocals)" in body("private boolean publishMessageRows(")
        and "postTimelineSendFollow(owner)" in body("private boolean publishMessageRows(")
        and "messageAdapter.getItemCount() - 1" in body("private void postTimelineSendFollow(")
        and "messageAdapter.getItemCount() - 1" in body("private void renderMessageWindowWithLocals(")
        and "displayedMessages.size() - 1" not in body("private void renderMessageWindowWithLocals("),
    "Explicit navigation and gestures supersede stale local position callbacks":
        body("private void jumpToCanonicalMessage(").count("beginTimelinePositionIntent()") >= 3
        and "beginTimelinePositionIntent()" in body("private void showNewerMessages()")
        and "beginTimelinePositionIntent()" in body("private void jumpToLatest()")
        and "beginTimelinePositionIntent()" in body("private void clearMessageTimelinePresentation()")
        and "messagePositionIntentSerial != positionIntent" in body("private void renderMessageWindowWithLocals(")
        and "positionIntent == messagePositionIntentSerial" in body("private final class TimelineSendOrigin")
        and "onScrollStateChanged" in source
        and "previousState == RecyclerView.SCROLL_STATE_IDLE" in source,
    "Latest position intent survives initial admission without borrowing a newer intent":
        "final boolean requestedOwnSend = beforeId == 0 && scrollAfterOwnSend" in body("private void loadMessages(")
        and body("private void loadMessages(").index("boolean ownSend = requestedOwnSend &&")
        < body("private void loadMessages(").index("admitMessageTimelineOwner(readOwner)"),
    "Manual cached navigation preserves the dispatch anchor across composer reflow":
        "final ScrollAnchor requestedAnchor = beforeId > 0 && !firstOpen ? currentScrollAnchor() : null;"
        in body("private void showCachedMessages(")
        and body("private void showCachedMessages(").index("final ScrollAnchor requestedAnchor")
        < body("private void showCachedMessages(").index("local(scope, () ->")
        and "ScrollAnchor anchor = requestedAnchor != null ? requestedAnchor : currentScrollAnchor();"
        in body("private void showCachedMessages(")
        and body("private void showCachedMessages(").index("!readOwner.bindingCurrent()")
        < body("private void showCachedMessages(").index("ScrollAnchor anchor = requestedAnchor"),
    "Visible-only read receipts keep the previous threshold":
        "messageScroll.getChildCount()" in body("private void scanVisibleMessageReceipts()")
        and "Math.min(Math.max(1, bubble.getHeight() / 2), dp(96))" in body(
            "private void scanVisibleMessageReceipts()"),
    "Delivery receipts cover received page, not only attached views":
        "for (JSONObject item : validated)" in body("private void loadMessages(long beforeId)"),
    "Group company labels use verified profile, not order options or IDs":
        'profileSnapshot.optJSONArray("companies")' in body("private void chooseGroupCompany()")
        and "companyNames.get(companies.get(i))" in body("private void chooseGroupCompany()")
        and "bchat_group_company_id" not in body("private void chooseGroupCompany()"),
    "Group member picker loads real candidates before asking for a search":
        'loadGroupCandidates(companyId, "", selected,' in body("private void showGroupCreateForm(")
        and 'loadGroupCandidates(room.companyId, "", selected,' in body("private void addGroupMember(")
        and 'addGroupMember(room, members)' in body("private void showGroupInfoPage(")
        and 'setNeutralButton(R.string.bchat_group_search' in body("private void loadGroupCandidates("),
    "Missing group route does not invalidate a valid session":
        'fetchV2("GET", V2_ROOMS, null,' in body("private boolean handleGroupRouteFailure(")
        and 'probeStatus == 200' in body("private boolean handleGroupRouteFailure(")
        and 'handleGroupRouteFailure(status, false)' in body("private void loadGroupCandidates("),
    "Media send conflict refreshes membership without unconditional room exit":
        "else if (statusCode == 409) loadRooms();" in body("private void sendClaimedConnectedMedia("),
    "Recycled voice controls detach without stopping same-media playback":
        "detachAudioControls(holder.bubble)" in source
        and "inlineAudioSeek != null" in body("private void tickInlineAudio("),
    "Thumbnail decoding stays off the UI thread":
        "mediaIo.execute(() ->" in body("private void pumpMediaThumbnails()")
        and "BitmapFactory.decodeFile" in body("private void pumpMediaThumbnails()"),
    "Stale document policy cannot repeat an identical failed send":
        "entry.policyVersion != room.invoicePolicyVersion" in body("private void retryConnectedMedia()")
        and "(!policyChanged && !uploadBlocked)" in body("private void reviewConnectedMedia()"),
    "Explicit local media removal uses the exact durable ticket and fingerprint":
        "discardLocalMediaAfterReview(scope, room, entry, true)" in body("private void discardConnectedMedia(")
        and "ticket.matches(entry)&&box.tickets().discardMedia(scope,ticket," in body("private void discardLocalMediaAfterReview(")
        and "store.retireReceipted(scope,entry.uploadUuid,ticket.fingerprint)" in body("private void discardLocalMediaAfterReview("),
}

for label, passed in checks.items():
    assert passed, label
    print("PASS", label)
print(f"PASS {len(checks)} focused source contracts; device behavior not asserted")
