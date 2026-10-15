package com.baseer.freshchat;

import java.util.Set;

/** The published v2 reply shape, plus one known optional preview field. */
public final class ReplyWireContract {
    private ReplyWireContract() { }

    public static void requireUnavailable(Set<String> fields, boolean unavailable) {
        if (fields == null || fields.size() != 1 || !fields.contains("unavailable") || !unavailable)
            throw new IllegalArgumentException("Invalid unavailable reply");
    }

    public static void requireAvailable(Set<String> fields, long messageId, long parentId,
                                        String authorName, String text, String mediaKind) {
        if (fields == null || !fields.contains("id") || !fields.contains("author_name")
                || !fields.contains("text") || (fields.size() != 3
                && !(fields.size() == 4 && fields.contains("media_kind")))
                || messageId <= 0 || parentId <= 0 || parentId >= messageId
                || authorName == null || authorName.trim().isEmpty() || authorName.length() > 160
                || text == null || text.length() > 160
                || (fields.contains("media_kind") && mediaKind != null
                && !"image".equals(mediaKind) && !"audio".equals(mediaKind)
                && !"file".equals(mediaKind)))
            throw new IllegalArgumentException("Invalid available reply");
    }
}
