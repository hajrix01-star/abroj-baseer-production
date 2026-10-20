#!/usr/bin/env python3
"""Focused BWork source contracts; emulator/phone behavior is checked separately."""

from pathlib import Path

source = (Path(__file__).resolve().parents[1] /
          "app/src/main/java/com/baseer/bwork/legacy/BWorkIdentityActivity.java").read_text(encoding="utf-8")


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
        and "Math.max(1, displayedMessages.size())" in source,
    "Connected older pages prepend within bounded window":
        "MAX_CONNECTED_MESSAGE_WINDOW = 500" in source
        and "for (JSONObject item : fetched) byId.put" in body("private List<JSONObject> messageWindow(")
        and "for (JSONObject item : displayedMessages) byId.put" in body("private List<JSONObject> messageWindow("),
    "Unchanged polls do not rebuild every visible bubble":
        "messageAdapter.notifyItemRangeInserted(0, prepend)" in body("private void updateMessageRows(")
        and "messageAdapter.notifyItemChanged(prepend + i)" in body("private void updateMessageRows("),
    "Offline older pages remain an explicit action":
        "if (offlineHistory || olderPageLoading" in body("private void maybeLoadOlderMessages()")
        and "offlineHistory || olderPageFailed" in body("private void updateOlderControl()"),
    "A short first page loads until scrolling is possible":
        "!messageScroll.canScrollVertically(-1)" in body("private void renderMessageWindow(")
        and "!messageScroll.canScrollVertically(1)" in body("private void renderMessageWindow("),
    "Visible-only read receipts keep the previous threshold":
        "messageScroll.getChildCount()" in body("private void scanVisibleMessageReceipts()")
        and "Math.min(Math.max(1, bubble.getHeight() / 2), dp(96))" in body(
            "private void scanVisibleMessageReceipts()"),
    "Delivery receipts cover received page, not only attached views":
        "for (JSONObject item : validated)" in body("private void loadMessages(long beforeId)"),
    "Group company labels use verified profile, not order options or IDs":
        'profileSnapshot.optJSONArray("companies")' in body("private void chooseGroupCompany()")
        and "companyNames.get(companies.get(i))" in body("private void chooseGroupCompany()")
        and "bwork_group_company_id" not in body("private void chooseGroupCompany()"),
    "Group member picker loads real candidates before asking for a search":
        'loadGroupCandidates(companyId, "", selected,' in body("private void showGroupCreateForm(")
        and 'loadGroupCandidates(room.companyId, "", selected,' in body("private void addGroupMember(")
        and 'addGroupMember(room, members)' in body("private void showGroupInfoPage(")
        and 'setNeutralButton(R.string.bwork_group_search' in body("private void loadGroupCandidates("),
    "Missing group route does not invalidate a valid session":
        'fetchV2("GET", V2_ROOMS, null,' in body("private boolean handleGroupRouteFailure(")
        and 'probeStatus == 200' in body("private boolean handleGroupRouteFailure(")
        and 'handleGroupRouteFailure(status, false)' in body("private void loadGroupCandidates("),
    "Media send conflict refreshes membership without unconditional room exit":
        "else if (statusCode == 409) loadRooms();" in body("private void sendConnectedMedia("),
    "Recycled voice controls detach without stopping same-media playback":
        "detachAudioControls(holder.bubble)" in source
        and "inlineAudioSeek != null" in body("private void tickInlineAudio("),
    "Thumbnail decoding stays off the UI thread":
        "mediaIo.execute(() ->" in body("private void pumpMediaThumbnails()")
        and "BitmapFactory.decodeFile" in body("private void pumpMediaThumbnails()"),
    "Stale document policy cannot repeat an identical failed send":
        "entry.policyVersion != room.invoicePolicyVersion" in body("private void retryConnectedMedia()")
        and "if (!policyChanged && !uploadBlocked) review.setPositiveButton" in body("private void reviewConnectedMedia()"),
    "Deterministic upload rejection is durable and user can explicitly clear local copy":
        "mediaStore.markUploadBlocked(scopedAccount, entry, code)" in body("private void uploadConnectedMedia(")
        and "!entry.uploadBlockCode.isEmpty()" in body("private void retryConnectedMedia()")
        and "discardLocalMediaAfterReview(scope, room, entry, true)" in body("private void discardConnectedMedia(")
        and "mediaStore.discard(scope, entry)" in body("private void discardLocalMediaAfterReview("),
}

for label, passed in checks.items():
    assert passed, label
    print("PASS", label)
print(f"PASS {len(checks)} focused source contracts; device behavior not asserted")
