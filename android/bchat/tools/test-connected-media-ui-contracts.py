#!/usr/bin/env python3
"""Source regression tripwires; phone camera/microphone acceptance is separate."""
from pathlib import Path

source = (Path(__file__).resolve().parents[1] / "app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java").read_text(encoding="utf-8")

def body(signature):
    start = source.index("{", source.index(signature))
    depth = 1
    for position in range(start + 1, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
        if depth == 0:
            return source[start + 1:position]
    raise AssertionError(f"Unclosed method: {signature}")

checks = {
    "Room reconciliation keeps identity only for same company and membership":
        "active.sameMembership(candidate)" in body("private void loadRooms()")
        and "validated.set(i, active)" in body("private void loadRooms()"),
    "Lost membership leaves room and invalidates media":
        "if (refreshedActive == null)" in body("private void loadRooms()")
        and "showRooms();" in body("private void loadRooms()")
        and "++mediaSessionGeneration" in body("private void showRooms()"),
    "Picker return is rejected after room session changes":
        "generation != mediaSessionGeneration" in body("protected void onActivityResult("),
    "Recording stops into preview rather than implicit upload":
        "showVoicePreview(scopedAccount, room, generation, source)" in body("private void finishConnectedVoice()")
        and "stageConnectedMedia(" not in body("private void finishConnectedVoice()"),
    "Recorded audio is sent only on explicit preview action":
        "setPositiveButton(R.string.bchat_media_preview_send" in body("private void showVoicePreview("),
    "Audio download survives same-media redraw while pending":
        "inlineAudioMediaId > 0" in body("private void renderMessageWindow("),
    "Verified history clears only the matching author's acknowledged staged media":
        "private void reconcilePendingMediaFromVerifiedHistory(" in source
        and "reconcilePendingMediaFromVerifiedHistory(account, room, validated);" in body(
            "private void loadMessages(long beforeId)")
        and "positiveId(message.opt(\"author_user_id\")) != scopedAccount.userId" in body(
            "private void reconcilePendingMediaFromVerifiedHistory(")
        and "serverMedia.id == pending.mediaId" in body(
            "private void reconcilePendingMediaFromVerifiedHistory(")
        and "mediaStore.acknowledge(scopedAccount, pending);" in body(
            "private void reconcilePendingMediaFromVerifiedHistory("),
    "Media chunks are decoded and encoded off UI thread":
        "mediaIo.execute" in body("private void readConnectedMedia(")
        and "mediaIo.execute" in body("private void sendNextMediaChunk("),
}

for label, passed in checks.items():
    assert passed, label
    print("PASS", label)
print(f"PASS {len(checks)} source contracts; device behavior not asserted")
