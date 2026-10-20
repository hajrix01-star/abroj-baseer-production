package com.baseer.bwork.legacy.test;

import android.app.*;
import android.content.*;
import android.content.res.Configuration;
import android.os.*;
import android.view.*;
import android.widget.*;
import com.baseer.bwork.legacy.ChatStore;
import java.io.File;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Real Android measure/layout, synthetic data only; requires an explicitly disposable install. */
public final class BubbleGeometryInstrumentation extends Instrumentation {
    private UiFixtureGuard fixtureGuard;
    private Activity activity;
    private ChatStore store;
    private File state;
    private SharedPreferences preferences;
    private String priorLanguage;
    private Configuration priorConfiguration;
    private boolean disposable, aborted;
    private final List<String> results = new ArrayList<>();
    private int assertions, cases;
    @Override public void onCreate(Bundle args) {
        super.onCreate(args);
        disposable = args != null && "true".equals(args.getString("disposable"));
        start();
    }
    @Override public void onStart() {
        Bundle out = new Bundle(); boolean passed = false;
        try {
            if (!disposable) throw new IllegalStateException("Requires a disposable emulator/test installation: -e disposable true");
            runChecks(); passed = true;
        } catch (Throwable failure) { out.putString("failure", android.util.Log.getStackTraceString(failure)); }
        finally {
            if (!aborted) {
                if (activity != null) try { ui(() -> {
                    if (priorConfiguration != null) activity.getResources().updateConfiguration(priorConfiguration, activity.getResources().getDisplayMetrics());
                    activity.finish();
                }); } catch (Throwable failure) { passed = false; out.putString("teardown", failure.toString()); }
                if (preferences != null) {
                    SharedPreferences.Editor edit = preferences.edit();
                    if (priorLanguage == null) edit.remove("interface-language"); else edit.putString("interface-language", priorLanguage);
                    if (!edit.commit()) { passed = false; out.putString("teardown", "Language preference restoration failed"); }
                }
                try {
                    if (activity != null) {
                        long deadline=SystemClock.elapsedRealtime()+10000;
                        while(!activity.isDestroyed()&&SystemClock.elapsedRealtime()<deadline)SystemClock.sleep(40);
                        if(!activity.isDestroyed())throw new AssertionError("Activity close deadline; no fixture restore racing live UI");
                    }
                    if(fixtureGuard!=null){fixtureGuard.restore(true);fixtureGuard.verifyOriginals();results.add("PASS All preexisting private-file SHA-256 and preferences preserved");}
                    if (state != null) for(String suffix:new String[]{"", ".last-good", ".lock"}) {File file=new File(state.getPath()+suffix);if(file.exists()&&!file.delete())throw new AssertionError("Cannot remove owned fixture "+file.getName());}
                } catch(Throwable failure) {passed=false;out.putString("teardown",failure.toString());}
            }
        }
        out.putString("stream", "\n" + (passed ? "PASS" : "FAILED") + " native bubble geometry: " + cases + " cases, " + assertions + " assertions\n"
                + String.join("\n", results) + "\n" + out.getString("failure", "") + "\n" + out.getString("teardown", "") + "\n");
        finish(passed ? Activity.RESULT_OK : Activity.RESULT_CANCELED, out);
    }
    private void ui(Runnable action) {
        if (aborted) throw new AssertionError("No further UI actions after timeout");
        Handler handler = new Handler(Looper.getMainLooper());
        CountDownLatch done = new CountDownLatch(1);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        AtomicInteger gate = new AtomicInteger();
        Runnable task = () -> {
            if (!gate.compareAndSet(0, 1)) { done.countDown(); return; }
            try { action.run(); } catch (Throwable error) { failure.set(error); }
            finally { gate.set(2); done.countDown(); }
        };
        if (!handler.post(task)) throw new AssertionError("UI handler rejected action");
        try {
            if (!done.await(30000, TimeUnit.MILLISECONDS)) {
                aborted = true; gate.compareAndSet(0, 3); handler.removeCallbacks(task);
                throw new AssertionError("UI action timed out; no further mutation or cleanup");
            }
        } catch (InterruptedException failureToWait) { Thread.currentThread().interrupt(); aborted = true; throw new AssertionError(failureToWait); }
        if (failure.get() != null) throw new AssertionError("Native measurement failed", failure.get());
    }
    private static void set(Object target, String name, Object value) {
        try { Field f = target.getClass().getDeclaredField(name); f.setAccessible(true); f.set(target, value); }
        catch (ReflectiveOperationException failure) { throw new AssertionError(name, failure); }
    }
    private void check(boolean value, String label) { assertions++; if (!value) throw new AssertionError(label); }
    private int dp(float value) { return (int)(value * activity.getResources().getDisplayMetrics().density + .5f); }
    private ChatStore.Message fixture(ChatStore.Conversation conversation, boolean mine, String sender, String text,
                                      String quote, boolean deleted, List<ChatStore.Attachment> files) {
        try {
            Constructor<ChatStore.Message> c = ChatStore.Message.class.getDeclaredConstructor(String.class, String.class,
                    String.class, String.class, List.class, boolean.class, String.class, long.class, String.class,
                    String.class, String.class, boolean.class);
            c.setAccessible(true);
            return c.newInstance(UUID.randomUUID().toString(), conversation.companyId, conversation.id, text, files,
                    mine, sender, 1760000000000L, "example", null, quote, deleted);
        } catch (ReflectiveOperationException failure) { throw new AssertionError("Synthetic message", failure); }
    }
    private void runChecks() throws Exception {
        fixtureGuard=new UiFixtureGuard(getTargetContext());
        state = new File(getTargetContext().getFilesDir(), "bubble-geometry-" + UUID.randomUUID() + ".bin");
        store = new ChatStore(state);fixtureGuard.install(store);
        preferences=getTargetContext().getSharedPreferences(com.baseer.bwork.legacy.compat.LegacyIdentity.SETTINGS,Context.MODE_PRIVATE);
        priorLanguage=preferences.getString("interface-language",null);
        ActivityMonitor monitor = addMonitor("com.baseer.bwork.legacy.MainActivity", null, false);
        try {
            ui(() -> getTargetContext().startActivity(new Intent(Intent.ACTION_MAIN)
                    .setComponent(new ComponentName("com.baseer.bchat.preview", "com.baseer.bwork.legacy.MainActivity"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)));
            activity = monitor.waitForActivityWithTimeout(45000);
            if (activity == null) throw new AssertionError("Activity launch timeout");
        } finally { removeMonitor(monitor); }
        long deadline=SystemClock.elapsedRealtime()+45000;boolean[] ready={false};
        do {ui(()->{try{java.lang.reflect.Field f=activity.getClass().getDeclaredField("initializing");f.setAccessible(true);java.lang.reflect.Field saved=activity.getClass().getDeclaredField("store");saved.setAccessible(true);ready[0]=!f.getBoolean(activity)&&saved.get(activity)==store;}catch(Exception error){throw new AssertionError(error);}});if(ready[0])break;SystemClock.sleep(40);}while(SystemClock.elapsedRealtime()<deadline);
        if(!ready[0])throw new AssertionError("Isolated asynchronous startup deadline");
        enterDemoIfPresent();
        priorConfiguration = new Configuration(activity.getResources().getConfiguration());
        ui(() -> { set(activity, "store", store); set(activity, "screen", "list"); set(activity, "composer", null); });
        String company = store.companies().get(0).id;
        ChatStore.Conversation group = null, person = null;
        for (ChatStore.Conversation c : store.conversations(company)) { if ("group".equals(c.kind)) group = c; else person = c; }
        if (group == null || person == null) throw new AssertionError("Seed needs group and person conversations");
        final ChatStore.Conversation[] conversations = {group, person};
        for (String language : new String[]{"ar", "en"}) {
            if (!preferences.edit().putString("interface-language", language).commit()) throw new AssertionError("Test locale setup failed");
            ui(() -> {
                Configuration config = new Configuration(priorConfiguration);
                Locale locale = Locale.forLanguageTag(language); config.setLocale(locale); config.setLayoutDirection(locale);
                activity.getResources().updateConfiguration(config, activity.getResources().getDisplayMetrics());
            });
            for (int width : new int[]{320, 411}) for (ChatStore.Conversation c : conversations) for (boolean mine : new boolean[]{false, true}) {
                ui(() -> {
                    String prefix = language + "/" + width + "/" + c.kind + "/" + (mine ? "mine" : "incoming");
                    String sender = "ar".equals(language) ? "أحمد محمد" : "Alex Smith";
                    String shortText = "ar".equals(language) ? "تم" : "OK";
                    String longText = "Long English message with العربية and mixed directions. ";
                    measure(fixture(c, mine, sender, shortText, null, false, Collections.emptyList()), width, prefix + "/short", true);
                    measure(fixture(c, mine, sender + " " + repeat(sender, 12), repeat(longText, 12), null, false, Collections.emptyList()), width, prefix + "/long", false);
                    measure(fixture(c, mine, sender, shortText, store.lastMessage(c.companyId, c.id).id, false, Collections.emptyList()), width, prefix + "/quote", true);
                    measure(fixture(c, mine, sender, "", null, true, Collections.emptyList()), width, prefix + "/deleted", false);
                    for (String mime : new String[]{"image/png", "audio/wav", "application/pdf"}) {
                        ChatStore.Attachment attachment = new ChatStore.Attachment(new File(activity.getFilesDir(), "synthetic-not-loaded").getPath(), "fixture", mime, 1);
                        measure(fixture(c, mine, sender, "", null, false, Collections.singletonList(attachment)), width, prefix + "/" + mime, false);
                    }
                });
            }
            results.add("PASS " + language + " native RTL/LTR, 320dp/411dp, group/person, incoming/outgoing, short/long/quote/deleted/photo/audio/PDF");
        }
    }
    private static String repeat(String text, int count) { StringBuilder out = new StringBuilder(); for (int i=0; i<count; i++) out.append(text); return out.toString(); }
    private void measure(ChatStore.Message message, int widthDp, String label, boolean shortText) {
        try {
            LinearLayout root = new LinearLayout(activity); root.setOrientation(LinearLayout.VERTICAL);
            root.setLayoutDirection(activity.getResources().getConfiguration().getLayoutDirection());
            int width = dp(widthDp);
            root.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(dp(2000), View.MeasureSpec.AT_MOST));
            root.layout(0, 0, width, root.getMeasuredHeight());
            set(activity, "root", root); set(activity, "companyId", message.companyId); set(activity, "conversationId", message.conversationId);
            Method make = activity.getClass().getDeclaredMethod("messageBubble", ChatStore.Message.class); make.setAccessible(true);
            LinearLayout outer = (LinearLayout)make.invoke(activity, message);
            root.addView(outer, new LinearLayout.LayoutParams(-1, -2));
            root.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED));
            root.layout(0, 0, width, root.getMeasuredHeight());
            LinearLayout bubble = (LinearLayout)outer.getChildAt(0);
            int content = bubble.getWidth() - bubble.getPaddingLeft() - bubble.getPaddingRight();
            check(content > dp(40), label + ": content width collapsed: " + content);
            check(bubble.getWidth() <= (int)(width * .79f) + dp(2), label + ": bubble exceeds width cap: " + bubble.getWidth());
            check((outer.getGravity() & Gravity.RELATIVE_HORIZONTAL_GRAVITY_MASK) == (message.mine ? Gravity.START : Gravity.END), label + ": logical alignment changed");
            for (int i=0; i<bubble.getChildCount(); i++) {
                View child = bubble.getChildAt(i);
                check(child.getLeft() >= bubble.getPaddingLeft() && child.getRight() <= bubble.getWidth() - bubble.getPaddingRight(), label + ": child outside bubble");
                if (child instanceof TextView) {
                    TextView text = (TextView)child;
                    check(text.getWidth() > 0 && text.getLayout() != null, label + ": unreadable text bounds");
                    if (shortText && text.getText().toString().equals(message.text)) check(text.getLineCount() == 1, label + ": short body wraps");
                    if (!message.senderName.contains("  ") && text.getText().toString().equals(message.senderName) && shortText) check(text.getLineCount() == 1, label + ": short sender wraps");
                }
            }
            LinearLayout meta = (LinearLayout)bubble.getChildAt(bubble.getChildCount()-1);
            for (int i=0; i<meta.getChildCount(); i++) {
                TextView text = (TextView)meta.getChildAt(i);
                check(text.getWidth() > 0 && text.getLeft() >= 0 && text.getRight() <= meta.getWidth(), label + ": time/reply clipped");
                check(text.getLineCount() == 1, label + ": time/reply unexpectedly wraps");
            }
            if (!message.attachments.isEmpty()) {
                boolean positiveCard = false;
                for (int i=0; i<bubble.getChildCount()-1; i++) {
                    View child = bubble.getChildAt(i);
                    if (!(child instanceof TextView) && child.getLayoutParams().width > dp(100)) positiveCard = true;
                }
                check(positiveCard, label + ": explicit attachment card dimensions missing");
            }
            cases++;
        } catch (ReflectiveOperationException failure) { throw new AssertionError(label, failure); }
    }

    private void enterDemoIfPresent() {
        ui(() -> {
            View entry = activity.getWindow().getDecorView().findViewWithTag("bwork-explore-demo");
            if (entry != null && !entry.performClick()) throw new AssertionError("Demo entry was not clickable");
        });
    }
}
