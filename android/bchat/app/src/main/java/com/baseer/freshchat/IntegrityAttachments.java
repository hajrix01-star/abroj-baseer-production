package com.baseer.freshchat;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/** Pure descriptor merge. Does not read files, compute hashes, add removed files, or certify legacy data. */
final class IntegrityAttachments {
    private IntegrityAttachments() { }

    /** Incoming membership/order wins, but it cannot discard an already established exact checksum. */
    static ArrayList<ChatStore.Attachment> preserve(List<ChatStore.Attachment> established,
                                                 List<ChatStore.Attachment> incoming) {
        Map<String, ChatStore.Attachment> known = new HashMap<String, ChatStore.Attachment>();
        for (ChatStore.Attachment file : established) {
            if (file == null || known.put(file.id, file) != null) throw new IllegalArgumentException("Duplicate established attachment");
        }
        ArrayList<ChatStore.Attachment> merged = new ArrayList<ChatStore.Attachment>();
        Set<String> seen = new HashSet<String>();
        for (ChatStore.Attachment file : incoming) {
            if (file == null || !seen.add(file.id)) throw new IllegalArgumentException("Duplicate incoming attachment");
            ChatStore.Attachment prior = known.get(file.id);
            if (prior != null) {
                if (!sameSource(prior, file)) throw new IllegalArgumentException("Attachment identity cannot change");
                if (prior.sha256 != null && file.sha256 != null && !prior.sha256.equals(file.sha256))
                    throw new IllegalArgumentException("Established attachment checksum conflicts");
                if (prior.sha256 != null && file.sha256 == null) file = prior;
            }
            merged.add(file);
        }
        return merged;
    }
    static boolean same(List<ChatStore.Attachment> a, List<ChatStore.Attachment> b) {
        if (a.size() != b.size()) return false;
        for (int i = 0; i < a.size(); i++) if (!exact(a.get(i), b.get(i))) return false;
        return true;
    }
    static boolean exact(ChatStore.Attachment a, ChatStore.Attachment b) {
        return sameSource(a, b) && Objects.equals(a.sha256, b.sha256);
    }
    private static boolean sameSource(ChatStore.Attachment a, ChatStore.Attachment b) {
        return a.id.equals(b.id) && a.path.equals(b.path) && a.name.equals(b.name)
                && a.mime.equals(b.mime) && a.size == b.size;
    }
}
