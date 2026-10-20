package com.baseer.bwork.feedback;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
public final class PeakEnvelopeHarness {
    static void denied(Runnable operation) { boolean failed = false; try { operation.run(); } catch (IllegalArgumentException expected) { failed = true; } if (!failed) throw new AssertionError("must fail"); }
    public static void main(String[] args) {
        PeakEnvelope pcm = new PeakEnvelope(1_000_000);
        ByteBuffer sixteen = ByteBuffer.allocate(16000).order(ByteOrder.LITTLE_ENDIAN);
        for (int n = 0; n < 8000; n++) sixteen.putShort((short) (n < 4000 ? 0 : 16384));
        sixteen.flip(); pcm.accept(sixteen, 0, 8000, 1, 2);
        double[] peaks = pcm.finish(); if (peaks.length != 40) throw new AssertionError();
        for (int n = 0; n < 40; n++) if (peaks[n] != (n < 20 ? 0 : 0.5)) throw new AssertionError("real time bins " + n);
        PeakEnvelope unsigned = new PeakEnvelope(1_000_000); byte[] eight = new byte[8000]; java.util.Arrays.fill(eight, (byte)128); eight[0] = 0; eight[1] = (byte)255;
        unsigned.accept(ByteBuffer.wrap(eight), 0, 8000, 1, 3);
        if (unsigned.finish()[0] != 1) throw new AssertionError("PCM8 unsigned");
        PeakEnvelope floating = new PeakEnvelope(1_000_000);
        ByteBuffer floats = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putFloat(Float.NaN); floats.flip();
        denied(() -> floating.accept(floats, 0, 8000, 1, 4));
        denied(() -> new PeakEnvelope(600_000_001)); denied(() -> new PeakEnvelope(0));
        denied(() -> new PeakEnvelope(1).finish());
        PeakEnvelope truncated = new PeakEnvelope(1_000_000); truncated.accept(ByteBuffer.wrap(new byte[]{(byte)128, 0, (byte)255}), 0, 8000, 1, 3); denied(() -> truncated.finish());
        denied(() -> pcm.accept(ByteBuffer.allocate(1024 * 1024 + 1), 0, 8000, 1, 2));
        denied(() -> pcm.accept(ByteBuffer.allocate(2), 0, 8000, 1, 99));
        denied(() -> pcm.accept(ByteBuffer.allocate(2), 0, 8000, 3, 2));
        peaks[0] = 1; if (pcm.finish()[0] != 0) throw new AssertionError("defensive output");
        System.out.println("PeakEnvelope actual PCM8/PCM16/float/time bins/limits PASS");
    }
}
