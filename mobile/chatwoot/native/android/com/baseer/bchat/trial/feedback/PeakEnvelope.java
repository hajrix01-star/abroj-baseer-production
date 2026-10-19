package com.baseer.bchat.trial.feedback;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Fixed-size real PCM envelope. Never retain decoded audio or synthesize peaks. */
public final class PeakEnvelope {
    private final double[] peaks = new double[40];
    private final long durationUs;
    private long samples;
    private long bytes;
    private long inRangeSamples;
    private long firstUs = Long.MAX_VALUE, lastUs = Long.MIN_VALUE;
    public PeakEnvelope(long durationUs) {
        if (durationUs <= 0 || durationUs > 600_000_000L) throw new IllegalArgumentException("duration_limit");
        this.durationUs = durationUs;
    }
    public void accept(ByteBuffer pcm, long presentationUs, int rate, int channels, int encoding) {
        if (rate < 8000 || rate > 192000 || channels < 1 || channels > 2) throw new IllegalArgumentException("unsupported_pcm");
        final int width = encoding == 2 ? 2 : encoding == 3 ? 1 : encoding == 4 ? 4 : 0;
        if (width == 0 || pcm.remaining() > 1024 * 1024 || pcm.remaining() % (width * channels) != 0) throw new IllegalArgumentException("unsupported_pcm");
        bytes += pcm.remaining(); samples += pcm.remaining() / width;
        if (bytes > 256L * 1024 * 1024 || samples > 128_000_000L) throw new IllegalArgumentException("pcm_limit");
        pcm.order(ByteOrder.LITTLE_ENDIAN);
        long sample = 0;
        while (pcm.remaining() >= width) {
            double value = encoding == 2 ? Math.abs(pcm.getShort() / 32768.0)
                : encoding == 3 ? Math.abs(((pcm.get() & 255) - 128) / 128.0) : Math.abs(pcm.getFloat());
            if (!Double.isFinite(value)) throw new IllegalArgumentException("invalid_pcm");
            final long time = presentationUs + (sample++ / channels) * 1_000_000L / rate;
            if (time >= 0 && time < durationUs) {
                inRangeSamples++;
                firstUs = Math.min(firstUs, time); lastUs = Math.max(lastUs, time);
                final int bucket = (int) Math.min(39, time * 40 / durationUs);
                peaks[bucket] = Math.max(peaks[bucket], Math.min(1, value));
            }
        }
    }
    public double[] finish() {
        if (samples == 0 || inRangeSamples == 0) throw new IllegalArgumentException("empty_pcm");
        // EOS alone does not prove container duration was fully decoded. Reject
        // a truncated/incorrectly long span instead of inventing silent bins.
        final long toleranceUs = Math.min(250_000, Math.max(20_000, durationUs / 20));
        if (firstUs > toleranceUs || lastUs < durationUs - toleranceUs) throw new IllegalArgumentException("incomplete_pcm");
        return peaks.clone();
    }
}
