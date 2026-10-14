package com.baseer.freshchat.test;

import android.app.*;
import android.content.*;
import android.os.*;
import android.view.*;
import android.widget.*;
import com.baseer.freshchat.ChatStore;
import com.baseer.freshchat.R;
import java.io.*;
import java.lang.reflect.*;
import java.nio.file.Files;
import java.util.*;

/** Device-only regression tests. Run solely on an authorized disposable test installation. */
public final class LocaleInstrumentation extends Instrumentation {
    private volatile Activity activity;
    private Throwable uiFailure;
    private final List<String> results = new ArrayList<>();
    private SharedPreferences preferences;
    private String previousLanguage;
    private ChatStore store;
    private ChatStore.Draft previousDraft;
    private File fixture;
    private String testShareId;
    private final List<File> shareFixtureFiles = new ArrayList<>();
    private final String company = "demo-nour", conversation = "demo-nour-ops";
    private static final String DRAFT = "Draft العربية / English, 100% unchanged";
    private final Application.ActivityLifecycleCallbacks lifecycle = new Application.ActivityLifecycleCallbacks() {
        public void onActivityResumed(Activity current) { activity = current; }
        public void onActivityCreated(Activity current, Bundle saved) { }
        public void onActivityStarted(Activity current) { }
        public void onActivityPaused(Activity current) { }
        public void onActivityStopped(Activity current) { }
        public void onActivitySaveInstanceState(Activity current, Bundle saved) { }
        public void onActivityDestroyed(Activity current) { }
    };
    public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    public void onStart() {
        Bundle output = new Bundle(); boolean passed = false;
        try { runChecks(); passed = true; }
        catch (Throwable failure) { output.putString("failure", android.util.Log.getStackTraceString(failure)); }
        finally {
            try {
                if (activity != null) ui(() -> {
                    // Stop draft persistence before restoring the exact earlier draft below.
                    invoke(activity, "showList", new Class<?>[0]);
                    activity.getApplication().unregisterActivityLifecycleCallbacks(lifecycle);
                    activity.finish();
                });
                if (store != null && testShareId != null) {
                    store.cancelPendingShare(testShareId);
                    getTargetContext().getSharedPreferences("share-preview", Context.MODE_PRIVATE).edit().clear().commit();
                }
                if (store != null && previousDraft != null) {
                    store.setDraft(company, conversation, previousDraft.text, previousDraft.attachments);
                    store.setReplyTarget(company, conversation, previousDraft.replyToMessageId);
                }
                if (preferences != null) {
                    SharedPreferences.Editor edit = preferences.edit();
                    if (previousLanguage == null) edit.remove("interface-language"); else edit.putString("interface-language", previousLanguage);
                    edit.commit();
                }
                if (fixture != null) fixture.delete();
                for (File file : shareFixtureFiles) file.delete();
            } catch (Throwable cleanup) { passed = false; output.putString("cleanup", cleanup.toString()); }
        }
        output.putString("stream", "\n" + (passed ? "PASS " : "FAILED after ") + results.size()
                + " locale device checks\n" + String.join("\n", results) + "\n"
                + output.getString("failure", "") + output.getString("cleanup", "") + "\n");
        finish(passed ? Activity.RESULT_OK : Activity.RESULT_CANCELED, output);
    }
    private void check(boolean condition, String name) { if (!condition) throw new AssertionError(name); results.add("PASS " + name); }
    private void ui(Runnable work) {
        uiFailure = null;
        runOnMainSync(() -> { try { work.run(); } catch (Throwable failure) { uiFailure = failure; } });
        if (uiFailure != null) throw new AssertionError("UI call failed", uiFailure);
        waitForIdleSync();
    }
    private static Object field(Object object, String name) {
        try { Field field = object.getClass().getDeclaredField(name); field.setAccessible(true); return field.get(object); }
        catch (ReflectiveOperationException error) { throw new AssertionError(name, error); }
    }
    private static void setField(Object object, String name, Object value) {
        try { Field field = object.getClass().getDeclaredField(name); field.setAccessible(true); field.set(object, value); }
        catch (ReflectiveOperationException error) { throw new AssertionError(name, error); }
    }
    private static Object invoke(Object object, String name, Class<?>[] types, Object... arguments) {
        try { Method method = object.getClass().getDeclaredMethod(name, types); method.setAccessible(true); return method.invoke(object, arguments); }
        catch (ReflectiveOperationException error) { throw new AssertionError(name, error); }
    }
    private Object callStatic(String className, String method, Class<?>[] types, Object... arguments) {
        try {
            Class<?> type = activity.getClassLoader().loadClass("com.baseer.freshchat." + className);
            Method call = type.getDeclaredMethod(method, types); call.setAccessible(true); return call.invoke(null, arguments);
        } catch (ReflectiveOperationException failure) { throw new AssertionError(method, failure); }
    }
    private void launch() {
        activity = startActivitySync(new Intent(Intent.ACTION_MAIN)
                .setComponent(new ComponentName("com.baseer.bchat.preview", "com.baseer.freshchat.MainActivity"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        waitForIdleSync();
        enterDemoIfPresent();
    }
    private void changeLanguage(String language) {
        Activity previous = activity;
        ui(() -> invoke(previous, "applyLanguage", new Class<?>[]{String.class}, language));
        long deadline = SystemClock.elapsedRealtime() + 8000;
        while ((activity == previous || !language.equals(activity.getResources().getConfiguration().getLocales().get(0).getLanguage()))
                && SystemClock.elapsedRealtime() < deadline) { waitForIdleSync(); SystemClock.sleep(40); }
        check(activity != previous, "Language " + language + " recreates the Activity");
        check(language.equals(activity.getResources().getConfiguration().getLocales().get(0).getLanguage()), "Activity resources use " + language);
        check(language.equals(preferences.getString("interface-language", "")), "Language " + language + " is committed");
    }
    private void checkBottomNavigation(String section, String language) {
        ui(() -> {
            LinearLayout root = (LinearLayout)field(activity, "root");
            LinearLayout tabs = (LinearLayout)root.findViewWithTag("bchat-bottom-navigation");
            String context = language + " " + section;
            check(section.equals(field(activity, "screen")) && section.equals(field(activity, "mainSection")), "Main section survives recreation: " + context);
            check(tabs != null && tabs.getChildCount() == 3 && tabs.getParent() == root
                    && root.getChildAt(root.getChildCount() - 1) == tabs, "Three fixed bottom destinations: " + context);
            check(tabs.getBottom() == root.getHeight() - root.getPaddingBottom(), "Navigation remains at bottom: " + context);
            String[] destinations = {"list", "orders", "tasks"};
            int[] labels = {R.string.ui_065, R.string.ui_066, R.string.ui_067};
            for (int index = 0; index < destinations.length; index++) {
                TextView tab = (TextView)tabs.getChildAt(index);
                boolean selected = destinations[index].equals(section);
                String title = activity.getString(labels[index]);
                check(title.contentEquals(tab.getText()) && tab.isSelected() == selected, "Translated selected destination " + destinations[index] + ": " + context);
                check((selected ? activity.getString(R.string.selected_section, title) : title).contentEquals(tab.getContentDescription()),
                        "Localized accessibility state " + destinations[index] + ": " + context);
            }
            boolean rtl = "ar".equals(language);
            check(tabs.getLayoutDirection() == (rtl ? View.LAYOUT_DIRECTION_RTL : View.LAYOUT_DIRECTION_LTR), "Navigation direction: " + context);
            check((tabs.getChildAt(0).getLeft() > tabs.getChildAt(2).getLeft()) == rtl, "Visual destination order: " + context);
        });
    }
    private void noBottomNavigation(String context) {
        ui(() -> check(activity.getWindow().getDecorView().findViewWithTag("bchat-bottom-navigation") == null,
                "No main navigation in " + context));
    }
    private void bottomNavigationLocaleChecks() {
        for (String section : new String[]{"list", "orders", "tasks"}) {
            ui(() -> {
                if ("list".equals(section)) invoke(activity, "showList", new Class<?>[0]);
                else activity.getWindow().getDecorView().findViewWithTag("bchat-section-" + section).performClick();
            });
            checkBottomNavigation(section, "ar");
            changeLanguage("en"); checkBottomNavigation(section, "en");
            ui(() -> activity.getWindow().getDecorView().findViewWithTag("bchat-section-" + section).performClick());
            checkBottomNavigation(section, "en");
            changeLanguage("ar"); checkBottomNavigation(section, "ar");
        }
        ui(() -> activity.onBackPressed());
        checkBottomNavigation("list", "ar");
    }
    private List<ChatStore.Attachment> createShareFixtures(File directory) throws IOException {
        List<ChatStore.Attachment> result = new ArrayList<>();
        String[] types = {"image/png", "application/pdf", "audio/wav"};
        String[] names = {"صورة original.png", "مستند original.pdf", "تسجيل original.wav"};
        for (int index = 0; index < types.length; index++) {
            String id = UUID.randomUUID().toString(); File file = new File(directory, id + ".bin"); shareFixtureFiles.add(file);
            try (FileOutputStream output = new FileOutputStream(file)) {
                if (index == 0) {
                    android.graphics.Bitmap bitmap = android.graphics.Bitmap.createBitmap(4, 4, android.graphics.Bitmap.Config.ARGB_8888);
                    bitmap.eraseColor(android.graphics.Color.BLUE);
                    bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, output); bitmap.recycle();
                } else if (index == 1) {
                    android.graphics.pdf.PdfDocument pdf = new android.graphics.pdf.PdfDocument();
                    android.graphics.pdf.PdfDocument.Page page = pdf.startPage(new android.graphics.pdf.PdfDocument.PageInfo.Builder(40, 40, 1).create());
                    page.getCanvas().drawColor(android.graphics.Color.WHITE); pdf.finishPage(page); pdf.writeTo(output); pdf.close();
                } else {
                    int dataSize = 16_000;
                    java.nio.ByteBuffer wav = java.nio.ByteBuffer.allocate(44 + dataSize).order(java.nio.ByteOrder.LITTLE_ENDIAN);
                    wav.put(new byte[]{'R','I','F','F'}).putInt(36 + dataSize).put(new byte[]{'W','A','V','E','f','m','t',' '});
                    wav.putInt(16).putShort((short)1).putShort((short)1).putInt(8000).putInt(16000).putShort((short)2).putShort((short)16);
                    wav.put(new byte[]{'d','a','t','a'}).putInt(dataSize); output.write(wav.array());
                }
                output.getFD().sync();
            }
            result.add(new ChatStore.Attachment(id, file.getAbsolutePath(), names[index], types[index], file.length()));
        }
        return result;
    }
    private void runChecks() throws Exception {
        preferences = getTargetContext().getSharedPreferences("bchat-local-settings-v1", Context.MODE_PRIVATE);
        previousLanguage = preferences.getString("interface-language", null);
        check(preferences.edit().putString("interface-language", "ar").commit(), "Arabic fixture choice stored");
        launch(); activity.getApplication().registerActivityLifecycleCallbacks(lifecycle);
        bottomNavigationLocaleChecks();
        store = (ChatStore)field(activity, "store"); previousDraft = store.draft(company, conversation);
        ChatStore.Message original = store.searchMessages(company, conversation, "").get(0);
        String originalName = original.senderName, originalText = original.text, title = store.conversation(company, conversation).title;
        File directory = new File(activity.getFilesDir(), "attachments"); directory.mkdirs();
        String id = UUID.randomUUID().toString(); fixture = new File(directory, id + ".bin");
        byte[] content = new byte[]{1,2,3,4,5};
        try (FileOutputStream out = new FileOutputStream(fixture)) { out.write(content); out.getFD().sync(); }
        ChatStore.Attachment attachment = new ChatStore.Attachment(id, fixture.getAbsolutePath(), "ملف original.bin", "application/octet-stream", content.length);
        store.setDraft(company, conversation, "Saved before typing", Collections.singletonList(attachment));
        store.setReplyTarget(company, conversation, original.id);
        ui(() -> {
            invoke(activity, "showChat", new Class<?>[]{String.class,String.class}, company, conversation);
            ((EditText)field(activity, "composer")).setText(DRAFT);
            check(((View)field(activity, "root")).getLayoutDirection() == View.LAYOUT_DIRECTION_RTL, "Arabic chat is RTL");
        });
        noBottomNavigation("Arabic chat");
        changeLanguage("en");
        noBottomNavigation("English chat");
        ui(() -> {
            check("chat".equals(field(activity, "screen")), "Chat navigation survives language recreation");
            check(conversation.equals(field(activity, "conversationId")), "Conversation scope survives recreation");
            check(((View)field(activity, "root")).getLayoutDirection() == View.LAYOUT_DIRECTION_LTR, "English chat is LTR");
            EditText composer = (EditText)field(activity, "composer");
            check(DRAFT.contentEquals(composer.getText()), "Unsaved typed draft survives English switch verbatim");
            check(!composer.getHint().toString().matches(".*[\\u0600-\\u06ff].*"), "English composer hint is translated");
            Context audioContext = (Context)field(field(activity, "audioPlayback"), "context");
            check("en".equals(audioContext.getResources().getConfiguration().getLocales().get(0).getLanguage()), "Application audio context uses English");
        });
        ChatStore reloaded = new ChatStore(new File(activity.getFilesDir(), "chat-state-v1.bin"));
        ChatStore.Draft saved = reloaded.draft(company, conversation);
        check(DRAFT.equals(saved.text), "Draft is durable in reloaded ChatStore");
        check(saved.attachments.size() == 1 && id.equals(saved.attachments.get(0).id), "Finished attachment survives language change");
        check(original.id.equals(saved.replyToMessageId), "Reply target survives language change");
        check(Arrays.equals(content, Files.readAllBytes(fixture.toPath())), "Original attachment bytes unchanged");
        check(title.equals(reloaded.conversation(company, conversation).title), "Stored conversation name unchanged");
        check(originalText.equals(reloaded.message(company, conversation, original.id).text), "Synthetic message text unchanged");
        check(originalName.equals(reloaded.message(company, conversation, original.id).senderName), "Synthetic sender name unchanged");
        Context appLocale = (Context)callStatic("AppLocale", "wrap", new Class<?>[]{Context.class}, activity.getApplicationContext());
        check("English".equals(appLocale.getString(R.string.language_english)), "Saved locale applies to fresh application-context lookup");
        String status = (String)callStatic("DemoNotifications", "status", new Class<?>[]{Context.class}, activity.getApplicationContext());
        check(!status.matches("(?s).*[\\u0600-\\u06ff].*"), "Notification status is English from application context");
        check(store.pendingShare() == null, "Disposable fixture has no pending share");
        List<ChatStore.Attachment> shareAttachments = createShareFixtures(directory);
        Map<String, byte[]> shareBytes = new HashMap<>();
        for (ChatStore.Attachment file : shareAttachments) shareBytes.put(file.id, Files.readAllBytes(new File(file.path).toPath()));
        ChatStore.PendingShare pending = store.stagePendingShare("Original share caption", shareAttachments);
        testShareId = pending.id;
        ui(() -> {
            setField(activity, "previewCompany", company); setField(activity, "previewConversation", conversation);
            invoke(activity, "loadPreview", new Class<?>[]{ChatStore.PendingShare.class}, pending);
            invoke(activity, "showSharePreview", new Class<?>[0]);
            ((EditText)field(activity, "previewCaption")).setText("Edited share / تعليق محفوظ");
        });
        changeLanguage("ar");
        noBottomNavigation("Arabic share preview");
        ui(() -> {
            check("preview".equals(field(activity, "screen")), "Share preview screen survives recreation");
            check("Edited share / تعليق محفوظ".equals(field(activity, "previewText")), "Edited share caption reloads verbatim");
            List<?> files = (List<?>)field(activity, "previewFiles");
            check(files.size() == 3, "Image, PDF and audio share attachments reload after recreation");
            for (int index = 0; index < files.size(); index++)
                check(shareAttachments.get(index).id.equals(((ChatStore.Attachment)files.get(index)).id), "Share attachment identity " + index + " survives");
            check(conversation.equals(field(activity, "previewConversation")), "Explicit share recipient survives recreation");
        });
        check(DRAFT.equals(store.draft(company, conversation).text), "Share locale change preserves unrelated conversation draft");
        for (ChatStore.Attachment file : shareAttachments)
            check(Arrays.equals(shareBytes.get(file.id), Files.readAllBytes(new File(file.path).toPath())), "Original " + file.mime + " share bytes unchanged");
        ui(() -> {
            ((List<?>)field(activity, "previewFiles")).remove(1);
            invoke(activity, "persistPreview", new Class<?>[0]);
        });
        changeLanguage("en");
        noBottomNavigation("English share preview");
        ui(() -> check(((List<?>)field(activity, "previewFiles")).size() == 2, "Removed share attachment stays removed after recreation"));
        store.cancelPendingShare(testShareId); testShareId = null;
        ui(() -> invoke(activity, "clearPreview", new Class<?>[0]));
        ui(() -> {
            invoke(activity, "showPicker", new Class<?>[]{boolean.class}, false);
            setField(activity, "pickerCompany", company); setField(activity, "pickerKind", "person");
            ((EditText)activity.getWindow().getDecorView().findViewWithTag("bchat-recipient-search")).setText("سارة");
        });
        changeLanguage("ar");
        noBottomNavigation("Arabic recipient picker");
        ui(() -> {
            check("picker".equals(field(activity, "screen")), "Picker navigation survives language recreation");
            check("سارة".equals(field(activity, "pickerQuery")), "Picker query survives language recreation");
            check(company.equals(field(activity, "pickerCompany")) && "person".equals(field(activity, "pickerKind")), "Picker company and kind filters survive recreation");
            check("سارة".contentEquals(((EditText)activity.getWindow().getDecorView().findViewWithTag("bchat-recipient-search")).getText()), "Visible picker search is restored");
        });
        changeLanguage("en");
        noBottomNavigation("English recipient picker");
        ui(() -> invoke(activity, "showSettings", new Class<?>[0]));
        noBottomNavigation("English settings");
        changeLanguage("ar");
        noBottomNavigation("Arabic settings");
        ui(() -> check("settings".equals(field(activity, "screen")), "Settings navigation survives Arabic switch"));
        changeLanguage("en");
        ui(() -> activity.finish()); launch();
        check("en".equals(activity.getResources().getConfiguration().getLocales().get(0).getLanguage()), "English survives Activity close and fresh launch");
        check(DRAFT.equals(((ChatStore)field(activity, "store")).draft(company, conversation).text), "Draft survives language switch and relaunch");
    }

    private void enterDemoIfPresent() {
        ui(() -> {
            View entry = activity.getWindow().getDecorView().findViewWithTag("bchat-explore-demo");
            if (entry != null && !entry.performClick()) throw new AssertionError("Demo entry was not clickable");
        });
    }
}
