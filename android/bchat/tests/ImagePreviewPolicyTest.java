import com.baseer.freshchat.ImagePreviewPolicy;
import java.util.Random;

/** Pure size/overflow policy checks. No Android image decoder is exercised here. */
public final class ImagePreviewPolicyTest {
    private static int checks;
    private static void check(boolean value, String label) {
        if (!value) throw new AssertionError(label);
        checks++;
    }
    private static void rejected(int width, int height) {
        check(!ImagePreviewPolicy.validSource(width, height), "invalid source dimensions");
        try { ImagePreviewPolicy.fit(width, height, 650); throw new AssertionError("fit accepted invalid source"); }
        catch (IllegalArgumentException expected) { checks++; }
        try { ImagePreviewPolicy.sampleSize(width, height, 650); throw new AssertionError("sample accepted invalid source"); }
        catch (IllegalArgumentException expected) { checks++; }
    }
    private static void dimensions(int width, int height, int requested) {
        int target = ImagePreviewPolicy.checkedTarget(requested);
        int[] fit = ImagePreviewPolicy.fit(width, height, requested);
        check(fit.length == 2 && fit[0] > 0 && fit[1] > 0, "fit never collapses");
        check(fit[0] <= Math.min(width, target) && fit[1] <= Math.min(height, target), "fit bounded without upscaling");
        double scale = Math.min(1d, target / (double)Math.max(width, height));
        check(Math.abs(fit[0] - width * scale) < 1.00001 && Math.abs(fit[1] - height * scale) < 1.00001,
                "fit preserves aspect within integer rounding");
        int sample = ImagePreviewPolicy.sampleSize(width, height, requested);
        check(sample > 0 && (sample & (sample - 1)) == 0, "sample is a power of two");
        check(((long)Math.max(width, height) + sample - 1) / sample <= target, "sample ceil edge stays bounded");
        check(sample == 1 || ((long)Math.max(width, height) + sample / 2 - 1) / (sample / 2) > target,
                "sample is the smallest sufficient power of two");
    }
    public static void main(String[] args) {
        check(ImagePreviewPolicy.MAX_EDGE == 1400 && ImagePreviewPolicy.MAX_SOURCE_EDGE == 100000
                && ImagePreviewPolicy.MAX_SOURCE_PIXELS == 200000000L, "declared allocation limits");
        check(ImagePreviewPolicy.checkedTarget(Integer.MIN_VALUE) == 1
                && ImagePreviewPolicy.checkedTarget(Integer.MAX_VALUE) == 1400, "target clamps safely");
        rejected(0, 1); rejected(1, 0); rejected(-1, 5); rejected(5, -1);
        rejected(100001, 1); rejected(1, 100001); rejected(100000, 2001);
        rejected(Integer.MAX_VALUE, Integer.MAX_VALUE);
        check(ImagePreviewPolicy.validSource(100000, 2000), "exact pixel cap accepted without int overflow");
        int[][] sources = {{1,1},{1,100000},{100000,1},{4000,3000},{3000,4000},{100000,2000},{1400,1400},{2,3}};
        for (int[] source : sources) for (int target : new int[]{Integer.MIN_VALUE,0,1,48,650,1000,1400,Integer.MAX_VALUE})
            dimensions(source[0], source[1], target);
        Random random = new Random(4216L);
        for (int i = 0; i < 5000; i++) {
            int width = 1 + random.nextInt(100000);
            int height = 1 + random.nextInt((int)Math.min(100000L, 200000000L / width));
            dimensions(width, height, random.nextInt(3000) - 100);
        }
        for (float density : new float[]{Float.NaN,Float.POSITIVE_INFINITY,0,-1,0.75f,1,2,3,4}) {
            for (int window : new int[]{Integer.MIN_VALUE,0,1,32,160,320,720,1080,2560}) {
                for (boolean large : new boolean[]{false,true}) {
                    int width = ImagePreviewPolicy.boundedWidth(window, density, large);
                    int height = ImagePreviewPolicy.boundedHeight(width, density, large);
                    check(width > 0 && width <= Math.max(1,window), "card stays within viewport");
                    check(height > 0, "card has nonzero height before decode");
                }
            }
        }
        check(ImagePreviewPolicy.boundedWidth(1080,3,false) > 100, "image-only card has a substantive phone width");
        System.out.println("PASS " + checks + " image policy assertions; native codecs/layout not executed");
    }
}
