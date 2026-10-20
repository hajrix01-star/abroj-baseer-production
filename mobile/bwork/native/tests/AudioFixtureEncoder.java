import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import android.os.SystemClock;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Test-only app_process entrypoint: synthesize six seconds of real AAC/M4A.
 * Never copied by the native plugin or linked into the production application.
 */
public final class AudioFixtureEncoder {
    public static void main(String[] args) throws Exception {
        if (args.length != 1 || !args[0].startsWith("/data/local/tmp/bwork-") || !args[0].endsWith(".m4a")) throw new IllegalArgumentException("isolated fixture path required");
        final int rate = 16000, sampleCount = rate * 6;
        final long deadline = SystemClock.elapsedRealtime() + 15000;
        MediaCodec codec = null; MediaMuxer muxer = null; boolean started = false;
        try {
            MediaFormat format = MediaFormat.createAudioFormat("audio/mp4a-latm", rate, 1);
            format.setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC);
            format.setInteger(MediaFormat.KEY_BIT_RATE, 64000);
            format.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 4096);
            codec = MediaCodec.createEncoderByType("audio/mp4a-latm"); codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE); codec.start();
            muxer = new MediaMuxer(args[0], MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
            int frame = 0, track = -1; boolean inputDone = false, outputDone = false;
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            while (!outputDone) {
                if (SystemClock.elapsedRealtime() > deadline) throw new IllegalStateException("fixture timeout");
                if (!inputDone) {
                    int input = codec.dequeueInputBuffer(10000);
                    if (input >= 0) {
                        ByteBuffer pcm = codec.getInputBuffer(input); if (pcm == null) throw new IllegalStateException(); pcm.clear(); pcm.order(ByteOrder.LITTLE_ENDIAN);
                        final int begin = frame;
                        while (pcm.remaining() >= 2 && frame < sampleCount) {
                            final double amplitude = frame < rate * 2 ? 0.08 : frame < rate * 4 ? 0.8 : 0.2;
                            pcm.putShort((short) (Math.sin(2 * Math.PI * 440 * frame / rate) * amplitude * 32767)); frame++;
                        }
                        final int size = pcm.position(); inputDone = frame >= sampleCount;
                        codec.queueInputBuffer(input, 0, size, begin * 1_000_000L / rate, inputDone ? MediaCodec.BUFFER_FLAG_END_OF_STREAM : 0);
                    }
                }
                int output = codec.dequeueOutputBuffer(info, 10000);
                if (output == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) { track = muxer.addTrack(codec.getOutputFormat()); muxer.start(); started = true; }
                else if (output >= 0) {
                    try {
                        if (info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                            if (!started) throw new IllegalStateException("muxer not ready");
                            ByteBuffer encoded = codec.getOutputBuffer(output); if (encoded == null) throw new IllegalStateException();
                            encoded.position(info.offset); encoded.limit(info.offset + info.size); muxer.writeSampleData(track, encoded, info);
                        }
                    } finally { codec.releaseOutputBuffer(output, false); }
                    outputDone = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                }
            }
            muxer.stop(); started = false;
            System.out.println("AAC_FIXTURE_PASS " + args[0] + " 6s/16000Hz/mono/quiet-loud-medium");
        } finally {
            if (codec != null) { try { codec.stop(); } catch (RuntimeException ignored) {} codec.release(); }
            if (muxer != null) { if (started) { try { muxer.stop(); } catch (RuntimeException ignored) {} } muxer.release(); }
        }
    }
}
