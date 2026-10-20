import com.baseer.bwork.legacy.AudioDiagnostic;
import java.io.IOException;
import static com.baseer.bwork.legacy.AudioDiagnostic.Stage.*;
import static com.baseer.bwork.legacy.AudioDiagnostic.Kind.*;

public final class AudioDiagnosticTest {
    private static int checks;
    private static void check(boolean ok, String message) { if (!ok) throw new AssertionError(message); checks++; }
    public static void main(String[] args) {
        AudioDiagnostic d = new AudioDiagnostic();
        check(d.snapshot().isEmpty(), "diagnostics start empty");
        AudioDiagnostic.Event source = d.exception(SOURCE, new IOException("/data/private/customer-secret.m4a"));
        check(source.code().equals("BP-SOURCE-IO"), "source failure has stable code");
        check(!d.summary().contains("private") && !d.summary().contains("customer"), "exception messages and private paths excluded");
        check(d.exception(START, new IllegalStateException("secret")).kind == STATE, "state exception classified");
        check(d.exception(FOCUS, new SecurityException("secret")).kind == SECURITY, "security exception classified");
        check(d.exception(SPEED, new IllegalArgumentException("secret")).kind == ARGUMENT, "argument exception classified");
        AudioDiagnostic.Event nativeError = d.record(PREPARE, NATIVE, 1, -1010);
        check(nativeError.unsupported() && nativeError.summary().contains("what=1 extra=-1010"), "native codes preserved without raw logs");
        check(!d.record(PREPARE, NATIVE, 1, -1004).unsupported(), "I/O error is not called unsupported codec");
        check(!d.record(FOCUS, DENIED, 0, 0).unsupported(), "focus denial is not codec failure");
        check(d.record(PREPARE, TIMEOUT, 0, 0).code().equals("BP-PREPARE-TIMEOUT"), "prepare timeout actionable");
        d.snapshot().clear(); check(!d.snapshot().isEmpty(), "snapshot cannot mutate diagnostics");
        for (int i=0; i<100; i++) d.record(PROGRESS, NATIVE, i, -i);
        check(d.snapshot().size() == AudioDiagnostic.CAPACITY, "ring bounded at 12 events");
        check(d.snapshot().get(0).what == 88 && d.snapshot().get(11).what == 99, "ring retains latest events in order");
        check(d.summary().length() < 1200, "summary bounded");
        check(nativeError.guidance().contains("حفظ نسخة"), "unsupported codec has explicit export guidance");
        check(source.guidance().contains("لا تحذف التطبيق"), "missing source guidance preserves drafts");
        AudioDiagnostic.Event missing = d.record(SOURCE, MISSING, 0, 0);
        check(missing.code().equals("BP-SOURCE-MISSING"), "Missing original has a distinct safe code");
        check(missing.guidance().equals("ATTACHMENT_SOURCE_MISSING"), "Missing original resolves through localized domain message");
        System.out.println("PASS " + checks + " private audio diagnostic checks");
    }
}
