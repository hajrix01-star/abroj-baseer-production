package com.baseer.freshchat;

/** Additive permissions v1 media policy; flags never authenticate a file read. */
final class MediaRights {
    final boolean view, upload, download, granular;
    private MediaRights(boolean view, boolean upload, boolean download, boolean granular) {
        this.view = view;
        this.upload = view && upload;
        this.download = view && download;
        this.granular = granular;
    }

    static MediaRights resolve(Object view, Object upload, Object download,
                               boolean legacy, boolean chatView) {
        if (view == null && upload == null && download == null)
            return new MediaRights(chatView && legacy, legacy, legacy, false);
        if (!(view instanceof Boolean) || !(upload instanceof Boolean) || !(download instanceof Boolean))
            throw new IllegalArgumentException("Incomplete media permissions");
        boolean canView = (Boolean) view, canUpload = (Boolean) upload, canDownload = (Boolean) download;
        if (legacy != (canView && canUpload && canDownload)
                || !canView && (canUpload || canDownload))
            throw new IllegalArgumentException("Inconsistent media permissions");
        return new MediaRights(chatView && canView, canUpload, canDownload, true);
    }

    /** An old server must not silently widen previously confirmed independent restrictions. */
    MediaRights constrainedByRemembered(MediaRights remembered) {
        if (granular || remembered == null) return this;
        return new MediaRights(view && remembered.view, upload && remembered.upload,
                download && remembered.download, false);
    }

    boolean legacyCombined() { return view && upload && download; }
    boolean canUpload(boolean chatSend) { return view && upload && chatSend; }
}
