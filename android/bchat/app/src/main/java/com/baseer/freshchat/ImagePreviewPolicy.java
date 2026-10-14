package com.baseer.freshchat;

/** Pure limits for read-only image previews. Original attachment bytes are never rewritten. */
public final class ImagePreviewPolicy {
    public static final int MAX_EDGE = 1400;
    public static final int MAX_SOURCE_EDGE = 100_000;
    public static final long MAX_SOURCE_PIXELS = 200_000_000L;
    private ImagePreviewPolicy() { }

    public static boolean validSource(int width, int height) {
        return width > 0 && height > 0 && width <= MAX_SOURCE_EDGE && height <= MAX_SOURCE_EDGE
                && (long)width * height <= MAX_SOURCE_PIXELS;
    }

    public static int checkedTarget(int maxEdge) { return Math.max(1, Math.min(MAX_EDGE, maxEdge)); }

    public static int[] fit(int width, int height, int maxEdge) {
        if (!validSource(width, height)) throw new IllegalArgumentException("Invalid preview dimensions");
        double scale = Math.min(1d, checkedTarget(maxEdge) / (double)Math.max(width, height));
        return new int[]{Math.max(1, (int)Math.floor(width * scale)), Math.max(1, (int)Math.floor(height * scale))};
    }

    /** Ceil-aware power-of-two sampling guarantees even extreme aspect ratios stay bounded. */
    public static int sampleSize(int width, int height, int maxEdge) {
        if (!validSource(width, height)) throw new IllegalArgumentException("Invalid preview dimensions");
        int target = checkedTarget(maxEdge), sample = 1;
        while (((long)Math.max(width, height) + sample - 1) / sample > target) sample *= 2;
        return sample;
    }

    public static int detailSample(int width, int height, float scale) {
        int bounded = sampleSize(width, height, MAX_EDGE);
        if (!Float.isFinite(scale) || scale <= 0) return bounded;
        int desired = Integer.highestOneBit(Math.max(1, (int)Math.min(131072d, 1d / scale)));
        return Math.max(bounded, desired);
    }

    public static int boundedWidth(int windowPx, float density, boolean large) {
        float scale = Float.isNaN(density) || Float.isInfinite(density) || density <= 0 ? 1f : density;
        int window = Math.max(1, windowPx);
        // Leave bubble padding and chat/dialog margins even in split-screen or a small window.
        int available = Math.max(1, window - Math.round(large ? 80 * scale : 72 * scale));
        int preferred = Math.max(1, Math.round((large ? 480 : 215) * scale));
        return Math.max(1, Math.min(available, Math.min(preferred, (int)(window * (large ? .9 : .65)))));
    }

    public static int boundedHeight(int widthPx, float density, boolean large) {
        float scale = Float.isNaN(density) || Float.isInfinite(density) || density <= 0 ? 1f : density;
        return Math.max(1, Math.min(Math.round((large ? 360 : 245) * scale),
                Math.max(Math.round(120 * scale), Math.round(Math.max(1, widthPx) * .86f))));
    }
}
