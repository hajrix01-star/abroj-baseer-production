package com.baseer.freshchat;

public final class MediaRightsTest {
    private static int checks;
    private static void check(boolean value) { if (!value) throw new AssertionError(); checks++; }
    private static void rejects(Object v, Object u, Object d, boolean legacy) {
        try { MediaRights.resolve(v, u, d, legacy, true); throw new AssertionError("invalid flags accepted"); }
        catch (IllegalArgumentException expected) { checks++; }
    }
    public static void main(String[] args) {
        MediaRights old = MediaRights.resolve(null, null, null, true, true);
        check(old.view && old.upload && old.download && !old.granular);
        MediaRights preview = MediaRights.resolve(true, false, false, false, true);
        check(preview.view && !preview.upload && !preview.download);
        check(!preview.legacyCombined() && !preview.canUpload(true));
        MediaRights writer = MediaRights.resolve(true, true, false, false, true);
        check(writer.canUpload(true) && !writer.canUpload(false) && !writer.download);
        MediaRights noChat = MediaRights.resolve(true, true, true, true, false);
        check(!noChat.view && !noChat.upload && !noChat.download);
        rejects(true, null, false, false);
        rejects(true, "true", false, false);
        rejects(false, true, false, false);
        rejects(true, false, true, true);
        rejects(true, true, true, false);
        MediaRights ceiling = old.constrainedByRemembered(preview);
        check(ceiling.view && !ceiling.upload && !ceiling.download);
        check(preview.constrainedByRemembered(old) == preview);
        check(old.constrainedByRemembered(null) == old);
        MediaRights disabled = MediaRights.resolve(null, null, null, false, true);
        check(!disabled.constrainedByRemembered(old).view);
        System.out.println("PASS " + checks + " additive media-permission policy checks");
    }
}
