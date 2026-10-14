import com.baseer.freshchat.ImagePreviewPolicy;
/** Ordinary dimension cases only. No malformed/native decoder probes. */
public final class MediaImageRecoveryPolicyTest {
    public static void main(String[] args){
        int count=0;
        int[][] shapes={{1200,20000},{20000,1200},{2048,2048},{320,180},{180,320},{1200,700}};
        for(int[] shape:shapes)for(float scale:new float[]{.02f,.2f,.5f,1f,2f}){
            int sample=ImagePreviewPolicy.detailSample(shape[0],shape[1],scale);
            if(sample<1||(sample&(sample-1))!=0||((long)Math.max(shape[0],shape[1])+sample-1)/sample>1400)throw new AssertionError("Bounded source region sample");count++;
        }
        if(ImagePreviewPolicy.detailSample(1200,700,1f)!=1)throw new AssertionError("Original pixel region");count++;
        System.out.println("PASS "+count+" ordinary image-region policy checks; native Android NOT executed");
    }
}
