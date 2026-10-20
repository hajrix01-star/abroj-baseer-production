package com.baseer.bwork.legacy;

/** Peak bins from actual decoded PCM. No invented bars or interpolation of missing audio. */
public final class WaveformSamples {
    private final float[] peaks;
    private final long durationUs;
    private int samples;
    public WaveformSamples(int bins, long durationUs) {
        if (bins < 1 || bins > 256 || durationUs <= 0) throw new IllegalArgumentException("Invalid waveform bounds");
        peaks = new float[bins]; this.durationUs = durationUs;
    }
    public void add(long timeUs, float amplitude) {
        if (!Float.isFinite(amplitude) || timeUs < 0 || timeUs > durationUs) return;
        int bin = (int)Math.min(peaks.length - 1, (double)timeUs * peaks.length / durationUs);
        peaks[bin] = Math.max(peaks[bin], Math.min(1f, Math.abs(amplitude))); samples++;
    }
    public boolean hasSamples() { return samples > 0; }
    public float[] peaks() { return peaks.clone(); }
}
