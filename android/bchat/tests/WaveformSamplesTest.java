import com.baseer.freshchat.WaveformSamples;
public final class WaveformSamplesTest {
    private static int checks;
    private static void check(boolean ok, String message) { if (!ok) throw new AssertionError(message); checks++; }
    public static void main(String[] args) {
        WaveformSamples s = new WaveformSamples(4, 1000); check(!s.hasSamples(), "no audio no waveform");
        s.add(0, 0f); check(s.hasSamples(), "real silence is valid PCM"); check(s.peaks()[0] == 0f, "silence never creates a decorative bar");
        s.add(200, -.25f); check(s.peaks()[0] == .25f, "negative PCM peak magnitude");
        s.add(249, .1f); check(s.peaks()[0] == .25f, "bin uses peak");
        s.add(250, .5f); check(s.peaks()[1] == .5f, "timestamp maps to next bin");
        s.add(999, 4f); check(s.peaks()[3] == 1f, "clamp amplitude");
        s.add(-1, 1f); s.add(1001, 1f); s.add(500, Float.NaN); s.add(500, Float.POSITIVE_INFINITY);
        check(s.peaks()[2] == 0f, "invalid PCM rejected");
        float[] copy = s.peaks(); copy[2] = 1f; check(s.peaks()[2] == 0f, "immutable result copy");
        s.add(1000, .7f); check(s.peaks()[3] == 1f, "duration edge bounded");
        for (int[] bad : new int[][]{{0, 10}, {257, 10}, {10, 0}, {10, -1}}) {
            boolean rejected = false; try { new WaveformSamples(bad[0], bad[1]); } catch (IllegalArgumentException expected) { rejected = true; }
            check(rejected, "invalid waveform bounds rejected");
        }
        System.out.println("PASS " + checks + " PCM waveform checks (no decoder runtime)");
    }
}
