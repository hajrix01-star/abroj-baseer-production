package com.baseer.freshchat.sync;

/** Identity of the exact editor revision consumed by a durable enqueue transaction. */
public final class BChatComposerSnapshot {
    private final String accountKey, body;
    private final long roomId, membershipId, revision, replyId;
    public BChatComposerSnapshot(AccountScope account, long roomId, long membershipId,
                                 long revision, String body, long replyId) {
        if (account == null || roomId <= 0 || membershipId <= 0 || body == null)
            throw new IllegalArgumentException("Invalid composer scope");
        this.accountKey = account.key; this.roomId = roomId; this.membershipId = membershipId;
        this.revision = revision; this.body = body; this.replyId = replyId;
    }
    public boolean matches(AccountScope currentAccount, long currentRoomId, long currentMembershipId,
                           long currentRevision, String currentBody, long currentReplyId) {
        return currentAccount != null && accountKey.equals(currentAccount.key)
                && roomId == currentRoomId && membershipId == currentMembershipId
                && revision == currentRevision && body.equals(currentBody) && replyId == currentReplyId;
    }
}
