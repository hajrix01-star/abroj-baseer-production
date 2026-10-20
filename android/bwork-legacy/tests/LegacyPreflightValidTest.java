import com.baseer.bwork.legacy.LegacyPreflight;
import java.io.File;
import java.nio.file.Files;
import java.util.Arrays;

/** Invoke only with genuine ordinary v1/v2/v3 ChatStore fixtures. */
public final class LegacyPreflightValidTest {
    public static void main(String[] args) throws Exception {
        if (args.length == 0) throw new IllegalArgumentException("Supply genuine normal legacy fixture paths");
        int passed = 0;
        for (String path : args) {
            File file = new File(path);
            byte[] original = Files.readAllBytes(file.toPath());
            LegacyPreflight.validate(file);
            LegacyPreflight.validate(original);
            if (!Arrays.equals(original, Files.readAllBytes(file.toPath()))) throw new AssertionError("Preflight changed original bytes");
            System.out.println("PASS normal legacy fixture " + file.getName() + " (file and byte snapshot, exact bytes retained)");
            passed++;
        }
        System.out.println("PASS: " + passed + " genuine normal legacy fixtures");
    }
}
