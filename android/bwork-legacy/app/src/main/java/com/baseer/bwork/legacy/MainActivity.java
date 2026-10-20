// Original Baseer offline demo; real account proof lives in a separate activity.
package com.baseer.bwork.legacy;

import android.app.*;
import android.content.*;
import android.database.Cursor;
import android.graphics.*;
import android.net.Uri;
import android.os.*;
import android.provider.*;
import android.text.*;
import android.view.*;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import java.io.*;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.*;
import static com.baseer.bwork.legacy.Ui.*;

/**
 * Offline Android demo. This activity never sends its synthetic data to Odoo.
 */
public final class MainActivity extends Activity {
    private static volatile ChatStore processStore;
    private static final ExecutorService STORE_IO = Executors.newSingleThreadExecutor(r -> {
        Thread worker = new Thread(r, "bwork-store"); worker.setDaemon(true); return worker;
    });
    private static final ThreadPoolExecutor QUERY_IO = new ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS,
            new ArrayBlockingQueue<>(4), r -> { Thread worker = new Thread(r, "bwork-query"); worker.setDaemon(true); return worker; },
            new ThreadPoolExecutor.AbortPolicy());
    private static final Map<String, EditorState> processEditors = new LinkedHashMap<>();
    private static final Map<String, OrphanEditor> processOrphanEditors = new LinkedHashMap<>();
    private static ChatStore editorStore;
    private static String editorProcessEpoch = UUID.randomUUID().toString();
    private static android.content.SharedPreferences recoveryReceipts;
    private static volatile java.lang.ref.WeakReference<MainActivity> activeActivity = new java.lang.ref.WeakReference<>(null);
    private EditorState draftEditor, previewEditor;
    private TextView editorStatus;
    private long draftViewRevision, previewViewRevision;
    private boolean initializing = true, restoringScreen, navigationSaving, editorSaveQueued, previewMigrationBlocked;
    private Runnable pendingNavigation, previewSaveTask, chatSearchTask;
    private volatile int chatSearchRevision, historyRevision;
    private Future<?> chatSearchFuture, historyFuture, transcriptFuture, storageStatsFuture;
    private static final int HISTORY_WINDOW = 30, SEARCH_WINDOW = 40, MAX_RECOVERY_EDITORS = 4;
    private String historyBefore, historyAfter, recoveredEditorKey;
    private boolean historyLoading, chatSearchLoading, chatSearchHasEarlier, chatSearchHasLater, restoringSearchText;
    private ReadingState readingState, pendingReadingRestore;
    private Bundle startupState;
    private boolean reopeningHistory;
    private AlertDialog uncertainDialog;
    private ChatStore store;
    private volatile boolean destroyed;
    private ProgressDialog activeProgress;
    private AnchoredMenu overflowMenu;
    private AlertDialog menuDialog;
    private int menuContextEpoch;
    private boolean menuHostActive;
    private String companyId = "demo-nour";
    private String conversationId;
    private String screen = "list";
    private String filter = "all";
    private String listQuery = "";
    private String groupNameDraft = "", groupCompanyDraft;
    private final LinkedHashSet<String> groupMemberDraft = new LinkedHashSet<>();
    private LinearLayout root;
    private LinearLayout history;
    private LinearLayout attachmentTray, replyTray, chatSearchBar;
    private EditText chatSearchInput;
    private TextView chatSearchCount;
    private final ArrayList<ChatStore.Message> chatMatches = new ArrayList<>();
    private int chatMatchIndex = -1;
    private String chatSearchQuery = "";
    private final HashMap<String, View> messageViews = new HashMap<>();
    private EditText composer;
    private ScrollView messageScroll;
    private ArrayList<ChatStore.Attachment> draftFiles = new ArrayList<>();
    private int pageLimit = 30;
    private ArrayList<ChatStore.Message> displayedMessages = new ArrayList<>();
    private String nextBefore;
    private boolean olderAvailable;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private Runnable saveTask;
    private String cameraPath;
    private String cameraCompany;
    private String cameraConversation;
    private String pickCompany;
    private String pickConversation;
    private String previewShareId;
    private String previewCompany;
    private String previewConversation;
    private String pickerQuery = "";
    private String pickerCompany = "all";
    private String pickerKind = "all";
    private EditText previewCaption;
    private ArrayList<ChatStore.Attachment> previewFiles = new ArrayList<>();
    private Intent deferredEntryIntent, pendingStartupIntent;
    private EntryMarkView entryMark;
    private android.animation.ObjectAnimator entryMotion;
    private boolean entryMotionPlayed;
    private boolean entryWindowFocused;
    private CheckBox rememberDemoEntry;
    private Boolean entryRememberChoice;
    private boolean sending = false, creatingGroup;
    private boolean importing = false, shareIntakeInProgress;
    private int navigationEpoch;
    private ListView inbox;
    private LinearLayout inboxSearchBar;
    private EditText inboxSearchInput;
    private boolean inboxSearchExpanded;
    /** Formatting is refreshed per call so a device 12/24-hour change is respected. */
    private String displayTime(long milliseconds) {
        return AppLocale.name(this, android.text.format.DateFormat.getTimeFormat(this).format(new Date(milliseconds)));
    }
    private static final int NOTIFICATION_PERMISSION = 410;
    private String permissionTestCompany, permissionTestConversation;
    private int permissionTestDelay = -1;
    private static final int PHOTO = 401;
    private static final int PDF = 402;
    private static final int AUDIO_FILE = 404, SAVE_FILE = 405, ANY_FILE = 406, MICROPHONE_PERMISSION = 411;
    private ChatStore.Attachment exportAttachment;
    private boolean exportCopyInProgress;
    private VoiceRecorder voiceRecorder;
    private final VoiceGestureState voiceGesture = new VoiceGestureState();
    private LinearLayout voiceBar;
    private TextView voiceTimer, voiceHint;
    private Ui.ActionButton composerAction;
    private boolean compactDrafts;
    private Ui.Icon composerActionGlyph;
    private View composerAttach, voiceLockControl;
    private boolean voiceTouchTracking, suppressComposerClick;
    private float voiceDownX, voiceDownY;
    private int voicePointerId = -1;
    private final Runnable voiceTicker = new Runnable() {
        public void run() {
            if (voiceRecorder == null || !voiceGesture.isActive()) return;
            if (liveWaveform != null) liveWaveform.append(voiceRecorder.amplitude());
            updateVoiceControls(); handler.postDelayed(this, 200);
        }
    };
    private String voiceCompany, voiceConversation, micPermissionCompany, micPermissionConversation;
    private AudioPlayback audioPlayback;
    private AudioWaveforms audioWaveforms;
    private ImagePreviews imagePreviews;
    private LocalSettings settings;
    private WaveformView liveWaveform;
    private String mainSection = "list";
    private static final int CAMERA = 403;
    private static final long MAX_FILE = 25L * 1024 * 1024;
    private static final long MAX_TOTAL = 100L * 1024 * 1024;

    @Override
    protected void attachBaseContext(Context base) { super.attachBaseContext(AppLocale.wrap(base)); }

    private String s(int resource, Object... arguments) { return arguments.length == 0 ? getString(resource) : getString(resource, arguments); }
    private String displayName(String name) { return AppLocale.name(this, name); }

    @Override
    public void onCreate(Bundle saved) {
        super.onCreate(saved);
        redirectToEmployeeEntry(getIntent());
        if (isFinishing()) return;
        activeActivity = new java.lang.ref.WeakReference<>(this);
        entryMotionPlayed = saved != null && saved.getBoolean("entryMotionPlayed", false);
        if (saved != null && saved.containsKey("entryRememberChoice")) entryRememberChoice = saved.getBoolean("entryRememberChoice");
        setVolumeControlStream(android.media.AudioManager.STREAM_MUSIC);
        settings = new LocalSettings(this);
        recoveryReceipts = getApplicationContext().getSharedPreferences(com.baseer.bwork.legacy.compat.LegacyIdentity.EDITOR_RECOVERY, MODE_PRIVATE);
        overflowMenu = new AnchoredMenu(this);
        audioPlayback = new AudioPlayback(this, this::toast);
        audioWaveforms = new AudioWaveforms(this);
        imagePreviews = new ImagePreviews(this);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        openStore(saved);
    }

    private void restoreScreen(Bundle saved) {
        restoringScreen = true;
        try {
        if (saved != null) readingState = (ReadingState) saved.getSerializable("readingState");
        // This is a local demo-entry preference, never authentication or an authorization boundary.
        // Upgrades show the entry once without changing existing chats, files or drafts.
        if (saved != null && deferredEntryIntent == null) deferredEntryIntent = saved.getParcelable("deferredEntryIntent");
        if (!settings.demoSessionActive()) {
            if (deferredEntryIntent == null && isEntryDestination(getIntent())) deferredEntryIntent = new Intent(getIntent());
            showEntry(); return;
        }
        if (saved != null) {
            mainSection = saved.getString("mainSection", "list");
            filter = saved.getString("filter", "all"); listQuery = saved.getString("listQuery", "");
            inboxSearchExpanded = saved.getBoolean("inboxSearchExpanded", false);
            pickerQuery = saved.getString("pickerQuery", ""); pickerCompany = saved.getString("pickerCompany", "all");
            pickerKind = saved.getString("pickerKind", "all"); pickerSharing = saved.getBoolean("pickerSharing", false);
            previewShareId = saved.getString("previewShareId"); previewCompany = saved.getString("previewCompany");
            previewConversation = saved.getString("previewConversation");
            companyId = saved.getString("company", companyId);
            conversationId = saved.getString("conversation");
            cameraPath = saved.getString("camera");
            cameraCompany = saved.getString("cameraCompany");
            cameraConversation = saved.getString("cameraConversation");
            pickCompany = saved.getString("pickCompany");
            pickConversation = saved.getString("pickConversation");
            exportAttachment = (ChatStore.Attachment) saved.getSerializable("exportAttachment");
            if (saved.getBoolean("interruptedExport", false)) toast(s(R.string.ui_052));
            micPermissionCompany = saved.getString("micPermissionCompany");
            micPermissionConversation = saved.getString("micPermissionConversation");
            permissionTestCompany = saved.getString("notificationCompany");
            permissionTestConversation = saved.getString("notificationConversation");
            permissionTestDelay = saved.getInt("notificationDelay", -1);
            groupNameDraft = saved.getString("groupNameDraft", "");
            groupCompanyDraft = saved.getString("groupCompanyDraft");
            ArrayList<String> members = saved.getStringArrayList("groupMemberDraft");
            if (members != null) groupMemberDraft.addAll(members);
            String old = saved.getString("screen", "list");
            recoveredEditorKey = saved.getString("recoveredEditorKey");
            if ("chat".equals(old) && !knownTarget(store, companyId, conversationId)) {
                if (hasOrphanEditors()) showRecoveredEditor(recoveredEditorKey); else showList();
                return;
            }
            if (hasOrphanEditors() && ("recovery".equals(old) || "chat".equals(old) && hasOrphanDraftTarget(companyId, conversationId)
                    || "preview".equals(old) && (store.pendingShare() == null || !store.pendingShare().id.equals(previewShareId)))) {
                showRecoveredEditor(recoveredEditorKey); return;
            }
            if ("settings".equals(old)) showSettings(); else if ("orders".equals(old) || "tasks".equals(old)) showModule(old); else if ("chat".equals(old) && conversationId != null) showChat(companyId, conversationId); else if ("create_group".equals(old)) showCreateGroup(false); else if ("preview".equals(old) && previewShareId != null && store.pendingShare() != null) showSharePreview(); else if ("picker".equals(old)) showPicker(pickerSharing, true); else if (store.pendingShare() != null) showPicker(true); else showList();
        } else {
            showList();
        }
        } finally {
            restoringScreen = false;
            if (saved != null && composer != null) {
                int length = composer.length();
                int start = Math.max(0, Math.min(length, saved.getInt("composerSelectionStart", length)));
                int end = Math.max(0, Math.min(length, saved.getInt("composerSelectionEnd", start)));
                composer.setSelection(start, end);
            }
            updateEditorStatus();
            if (saved != null && saved.getBoolean("interruptedImport", false))
                new AlertDialog.Builder(this).setTitle(s(R.string.foundation_import_interrupted_title))
                        .setMessage(s(R.string.foundation_import_interrupted)).setPositiveButton(s(R.string.ui_051), null).show();
        }
    }

    private boolean isEntryDestination(Intent intent) {
        return isShare(intent) || intent != null && DemoNotifications.OPEN_ACTION.equals(intent.getAction());
    }

    private boolean isShare(Intent i) {
        return i != null && (Intent.ACTION_SEND.equals(i.getAction()) || Intent.ACTION_SEND_MULTIPLE.equals(i.getAction()));
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        redirectToEmployeeEntry(intent);
        if (isFinishing()) return;
        setIntent(intent);
        if (initializing || store == null) { if (isEntryDestination(intent)) pendingStartupIntent = new Intent(intent); return; }
        if (!settings.demoSessionActive()) {
            // A launcher ACTION_MAIN must not erase a still-unreviewed external share.
            if (isEntryDestination(intent)) deferredEntryIntent = new Intent(intent);
            showEntry(); return;
        }
        if (isShare(intent)) handleIncomingShare(intent); else handleLocalNotification(intent);
    }

    private void redirectToEmployeeEntry(Intent source) {
        Intent destination = new Intent(this, BWorkIdentityActivity.class);
        destination.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if (source != null && (Intent.ACTION_SEND.equals(source.getAction())
                || Intent.ACTION_SEND_MULTIPLE.equals(source.getAction())))
            destination.putExtra(BWorkIdentityActivity.EXTRA_SHARE_UNAVAILABLE, true);
        startActivity(destination);
        finish();
    }

    private void handleIncomingShare(Intent intent) {
        if (!beforeNavigation(() -> handleIncomingShare(intent))) { deferredEntryIntent = new Intent(intent); return; }
        deferredEntryIntent = null;
        if (importing) {
            toast(s(R.string.ui_053));
            return;
        }
        shareIntakeInProgress = true;
        persistDraft();
        final String pendingAtOpen = store.pendingShare() == null ? null : store.pendingShare().id;
        if (pendingAtOpen != null) new AlertDialog.Builder(this).setTitle(s(R.string.ui_054)).setMessage(s(R.string.ui_055)).setNegativeButton(s(R.string.ui_056), (d,w)->{shareIntakeInProgress=false;showPicker(true);}).setPositiveButton(s(R.string.ui_057), (d,w)->{
            final ChatStore targetStore=store;storeOperation(()->{targetStore.cancelPendingShare(pendingAtOpen);return true;},done->{clearPreview();receiveShare(intent);});
        }).setOnCancelListener(dialog->shareIntakeInProgress=false).show(); else receiveShare(intent);
    }

    @Override
    protected void onResume() {
        super.onResume();
        activeActivity = new java.lang.ref.WeakReference<>(this);
        reconcileEditorViews();
        menuHostActive = true;
        startEntryMotion();
    }

    @Override
    public boolean dispatchTouchEvent(MotionEvent event) {
        if ("entry".equals(screen) && event.getActionMasked() == MotionEvent.ACTION_DOWN) stopEntryMotion();
        return super.dispatchTouchEvent(event);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        boolean losingFocus = entryWindowFocused && !hasFocus;
        entryWindowFocused = hasFocus;
        super.onWindowFocusChanged(hasFocus);
        if (losingFocus) stopEntryMotion(); else if (hasFocus) startEntryMotion();
    }

    @Override
    protected void onPause() {
        menuHostActive = false;
        if (uncertainDialog != null) { uncertainDialog.dismiss(); uncertainDialog = null; }
        stopEntryMotion();
        dismissMenuContext();
        if (voiceRecorder != null) finishVoice(false);
        voiceTouchTracking = false; voicePointerId = -1;
        stopAudio();
        captureReadingState();
        persistPreview();
        persistDraft();
        super.onPause();
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        if (initializing && startupState != null) {
            out.putAll(startupState);
            if (pendingStartupIntent != null) out.putParcelable("deferredEntryIntent", pendingStartupIntent);
            super.onSaveInstanceState(out); return;
        }
        captureEditors(); captureReadingState();
        out.putSerializable("readingState", pendingReadingRestore != null ? pendingReadingRestore : readingState);
        out.putBoolean("interruptedImport", importing || shareIntakeInProgress);
        ArrayList<EditorState.Snapshot> recovered = new ArrayList<>();
        synchronized (processEditors) {
            for (EditorState value : processEditors.values()) if (value.dirty() || value.sending()) recovered.add(value.snapshot());
            out.putString("editorProcess", editorProcessEpoch);
            out.putSerializable("orphanRecovery", new ArrayList<>(processOrphanEditors.values()));
        }
        out.putSerializable("editorRecovery", recovered); out.putString("recoveredEditorKey", recoveredEditorKey);
        if (composer != null) { out.putInt("composerSelectionStart", composer.getSelectionStart()); out.putInt("composerSelectionEnd", composer.getSelectionEnd()); }
        persistDraft();
        out.putString("company", companyId);
        out.putString("conversation", conversationId);
        out.putString("screen", screen);
        out.putParcelable("deferredEntryIntent", pendingStartupIntent != null ? pendingStartupIntent : deferredEntryIntent);
        out.putBoolean("entryMotionPlayed", entryMotionPlayed);
        if (entryRememberChoice != null) out.putBoolean("entryRememberChoice", entryRememberChoice);
        out.putString("mainSection", mainSection);
        out.putString("filter", filter); out.putString("listQuery", listQuery); out.putBoolean("inboxSearchExpanded", inboxSearchExpanded);
        out.putString("pickerQuery", pickerQuery); out.putString("pickerCompany", pickerCompany); out.putString("pickerKind", pickerKind);
        out.putBoolean("pickerSharing", pickerSharing); out.putString("previewShareId", previewShareId);
        out.putString("previewCompany", previewCompany); out.putString("previewConversation", previewConversation);
        out.putString("camera", cameraPath);
        out.putString("cameraCompany", cameraCompany);
        out.putString("cameraConversation", cameraConversation);
        out.putString("pickCompany", pickCompany);
        out.putString("pickConversation", pickConversation);
        out.putSerializable("exportAttachment", exportCopyInProgress ? null : exportAttachment);
        out.putBoolean("interruptedExport", exportCopyInProgress);
        out.putString("micPermissionCompany", micPermissionCompany);
        out.putString("micPermissionConversation", micPermissionConversation);
        out.putString("notificationCompany", permissionTestCompany);
        out.putString("notificationConversation", permissionTestConversation);
        out.putInt("notificationDelay", permissionTestDelay);
        out.putString("groupNameDraft", groupNameDraft);
        out.putString("groupCompanyDraft", groupCompanyDraft);
        out.putStringArrayList("groupMemberDraft", new ArrayList<>(groupMemberDraft));
        persistPreview();
        super.onSaveInstanceState(out);
    }

    private int d(float n) {
        return dp(this, n);
    }

    private LinearLayout.LayoutParams p(int w, int h) {
        return lp(w, h);
    }

    private LinearLayout base(String state, int color) {
        navigationEpoch++;
        stopEntryMotion(); entryMark = null; rememberDemoEntry = null;
        dismissMenuContext();
        stopAudio();
        if (voiceRecorder != null) finishVoice(false);
        voiceBar = null; composerAction = null; composerActionGlyph = null; composerAttach = null;
        if (saveTask != null) handler.removeCallbacks(saveTask);
        composer = null; previewCaption = null; editorStatus = null;
        attachmentTray = null; replyTray = null; history = null; messageScroll = null;
        messageViews.clear(); displayedMessages.clear(); historyRevision++; chatSearchRevision++;
        cancelQueries(); if (chatSearchTask != null) handler.removeCallbacks(chatSearchTask);
        screen = state; pruneEditors();
        root = column(this);
        root.setLayoutDirection(AppLocale.direction(this));
        root.setBackgroundColor(color);
        setContentView(root);
        return root;
    }

    private void spacer(LinearLayout parent, int height) {
        View v = new View(this);
        parent.addView(v, p(1, d(height)));
    }

    private Ui.Icon icon(String name, int color, int size) {
        Ui.Icon v = new Ui.Icon(this, name, color);
        v.setLayoutParams(p(d(size), d(size)));
        return v;
    }

    private View buttonIcon(String kind, String description, int color, Runnable click) {
        FrameLayout frame = new FrameLayout(this);
        frame.setContentDescription(description);
        Ui.Icon i = icon(kind, color, 23);
        FrameLayout.LayoutParams ip = new FrameLayout.LayoutParams(d(23), d(23), Gravity.CENTER);
        frame.addView(i, ip);
        frame.setLayoutParams(p(d(48), d(48)));
        clickable(frame);
        frame.setOnClickListener((v)->click.run());
        return frame;
    }

    private TextView action(String text, Runnable click) {
        TextView t = Ui.text(this, text, 15, android.graphics.Color.WHITE, true);
        t.setGravity(Gravity.CENTER);
        t.setBackground(bg(GREEN, 17, this));
        pad(t, 22, 13);
        t.setMinHeight(d(50));
        clickable(t);
        t.setOnClickListener((v)->click.run());
        return t;
    }

    private void demoBar(LinearLayout parent, boolean subtle) {
        LinearLayout row = row(this);
        row.setGravity(Gravity.CENTER);
        pad(row, 10, 2);
        row.setBackgroundColor(LIGHT);
        Ui.Icon shield = icon("shield", GREEN, 13);
        row.addView(shield);
        TextView t = text(this, s(R.string.ui_058), 10, MUTED, false);
        row.addView(t);
        row.setMinimumHeight(d(22)); parent.addView(row, p(-1, -2));
    }

    private ChatStore.Company currentCompany() {
        for (ChatStore.Company c : store.companies()) if (c.id.equals(companyId)) return c;
        return store.companies().get(0);
    }

    private void showEntry() {
        if (!beforeNavigation(this::showEntry)) return;
        persistDraft(); persistPreview(); hideKeyboard(); base("entry", Color.WHITE);
        conversationId = null;
        LinearLayout top = row(this); pad(top, 16, 0);
        top.addView(new View(this), new LinearLayout.LayoutParams(0, 1, 1));
        TextView language = text(this, s(AppLocale.rtl(this) ? R.string.language_english : R.string.language_arabic), 13, GREEN, true);
        language.setTag("bwork-entry-language"); language.setGravity(Gravity.CENTER); language.setMinHeight(d(48)); pad(language, 12, 6);
        clickable(language); language.setOnClickListener(v -> { stopEntryMotion(); showLanguageSettings(); });
        top.addView(language, p(-2, -2)); root.addView(top);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true); scroll.setVerticalScrollBarEnabled(false);
        LinearLayout shell = column(this); shell.setGravity(Gravity.CENTER); pad(shell, 24, 16); scroll.addView(shell);
        LinearLayout form = column(this);
        LinearLayout.LayoutParams formSize = p(Math.min(windowWidth() - d(48), d(340)), -2); formSize.gravity = Gravity.CENTER;
        shell.addView(form, formSize);
        entryMark = new EntryMarkView(this);
        LinearLayout.LayoutParams markSize = p(d(112), d(112)); markSize.gravity = Gravity.CENTER;
        form.addView(entryMark, markSize); spacer(form, 22);
        // A deliberately read-only shell. No credential entry, autofill, password storage or fake auth.
        entryField(form, s(R.string.entry_username), "person", false);
        spacer(form, 12);
        entryField(form, "••••••••", "lock", true);
        rememberDemoEntry = new CheckBox(this); rememberDemoEntry.setTag("bwork-entry-remember");
        rememberDemoEntry.setText(s(R.string.entry_remember)); rememberDemoEntry.setTextSize(13); rememberDemoEntry.setTextColor(MUTED);
        rememberDemoEntry.setChecked(entryRememberChoice == null ? settings.rememberDemoEntry() : entryRememberChoice); rememberDemoEntry.setMinHeight(d(48));
        rememberDemoEntry.setOnCheckedChangeListener((button, checked) -> { entryRememberChoice = checked; stopEntryMotion(); });
        form.addView(rememberDemoEntry, p(-1, -2)); spacer(form, 8);
        TextView enter = action(s(R.string.entry_minimal_demo_login), () -> { stopEntryMotion(); enterDemo(); });
        enter.setTag("bwork-explore-demo"); form.addView(enter, p(-1, -2)); spacer(form, 12);
        TextView odooLogin = action(s(R.string.auth_open), () -> {
            stopEntryMotion(); startActivity(new Intent(this, BWorkIdentityActivity.class));
        });
        odooLogin.setTag("bwork-odoo-login"); form.addView(odooLogin, p(-1, -2)); spacer(form, 12);
        TextView notice = text(this, s(R.string.entry_minimal_notice), 11, MUTED, false);
        notice.setGravity(Gravity.CENTER); form.addView(notice, p(-1, -2));
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        final ViewTreeObserver.OnGlobalFocusChangeListener focusObserver = (oldFocus, newFocus) -> {
            if (newFocus != null && newFocus != root) stopEntryMotion();
        };
        final LinearLayout entryRoot = root;
        final ViewTreeObserver.OnGlobalLayoutListener layoutObserver = () -> {
            if (!"entry".equals(screen) || root != entryRoot) return;
            android.graphics.Rect visible = new android.graphics.Rect(); entryRoot.getWindowVisibleDisplayFrame(visible);
            if (entryRoot.getRootView().getHeight() - visible.height() > d(140)) stopEntryMotion();
        };
        entryRoot.getViewTreeObserver().addOnGlobalFocusChangeListener(focusObserver);
        entryRoot.getViewTreeObserver().addOnGlobalLayoutListener(layoutObserver);
        entryRoot.addOnAttachStateChangeListener(new View.OnAttachStateChangeListener() {
            public void onViewAttachedToWindow(View view) { }
            public void onViewDetachedFromWindow(View view) {
                // The shared window observer outlives setContentView. Remove our callbacks while
                // this detach callback still has the old attachment, avoiding retired entry trees.
                ViewTreeObserver observer = view.getViewTreeObserver();
                if (observer.isAlive()) {
                    observer.removeOnGlobalFocusChangeListener(focusObserver);
                    observer.removeOnGlobalLayoutListener(layoutObserver);
                }
                view.removeOnAttachStateChangeListener(this);
            }
        });
        startEntryMotion();
    }

    private void entryField(LinearLayout form, String placeholder, String glyph, boolean password) {
        LinearLayout field = row(this); pad(field, 14, 4); field.setMinimumHeight(d(56));
        field.setBackground(outline(LIGHT, LINE, 12, this)); field.addView(icon(glyph, MUTED, 20));
        TextView value = text(this, placeholder, 14, MUTED, false); value.setTextAlignment(View.TEXT_ALIGNMENT_VIEW_START);
        value.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        value.setTag(password ? "bwork-password-preview" : "bwork-username-preview");
        value.setContentDescription(s(password ? R.string.entry_password_readonly : R.string.entry_username_readonly));
        LinearLayout.LayoutParams valueSize = new LinearLayout.LayoutParams(0, -2, 1); valueSize.setMarginStart(d(12)); field.addView(value, valueSize);
        if (password) {
            final boolean[] visible = {false};
            View eye = buttonIcon("eye", s(R.string.entry_show_example), MUTED, () -> { }); eye.setTag("bwork-password-eye");
            eye.setOnClickListener(v -> {
                stopEntryMotion(); visible[0] = !visible[0]; value.setText(visible[0] ? s(R.string.entry_password_sample) : "••••••••");
                eye.setContentDescription(s(visible[0] ? R.string.entry_hide_example : R.string.entry_show_example));
            }); field.addView(eye);
        }
        form.addView(field, p(-1, -2));
    }

    private void startEntryMotion() {
        final EntryMarkView mark = entryMark;
        if (entryMotionPlayed || mark == null || !menuHostActive || !entryWindowFocused || !"entry".equals(screen)) return;
        mark.post(() -> {
            if (entryMotionPlayed || mark != entryMark || !menuHostActive || !entryWindowFocused || !mark.isAttachedToWindow() || !"entry".equals(screen)) return;
            entryMotionPlayed = true;
            // Android animator scale 0 (Remove animations/reduced motion) keeps the mark completely still.
            if (!android.animation.ValueAnimator.areAnimatorsEnabled()) return;
            entryMotion = android.animation.ObjectAnimator.ofPropertyValuesHolder(mark,
                    android.animation.PropertyValuesHolder.ofFloat(View.ROTATION_Y, -14f, 14f, 0f),
                    android.animation.PropertyValuesHolder.ofFloat(View.ROTATION, -3f, 3f, 0f));
            entryMotion.setDuration(950); entryMotion.setInterpolator(new android.view.animation.DecelerateInterpolator());
            entryMotion.start();
        });
    }

    private void stopEntryMotion() {
        if (entryMotion != null) { entryMotion.cancel(); entryMotion = null; }
        if (entryMark != null) { entryMotionPlayed = true; entryMark.setRotationY(0f); entryMark.setRotation(0f); }
    }

    private void enterDemo() {
        if (!settings.demoSessionActive(true, rememberDemoEntry != null && rememberDemoEntry.isChecked())) { toast(s(R.string.entry_state_error)); return; }
        Intent destination = deferredEntryIntent == null ? getIntent() : deferredEntryIntent;
        deferredEntryIntent = null;
        setIntent(new Intent(Intent.ACTION_MAIN).setClass(this, MainActivity.class));
        if (reopenUnsavedEditor()) { if (isEntryDestination(destination)) deferredEntryIntent = destination; return; }
        if (hasOrphanEditors()) { if (isEntryDestination(destination)) deferredEntryIntent = destination; showRecoveredEditor(recoveredEditorKey); return; }
        showList();
        if (isShare(destination)) handleIncomingShare(destination);
        else if (!handleLocalNotification(destination) && store.pendingShare() != null) showPicker(true);
    }

    private void confirmLogout() {
        new AlertDialog.Builder(this).setTitle(s(R.string.demo_logout))
                .setMessage(s(R.string.demo_logout_confirm))
                .setNegativeButton(s(R.string.ui_109), null)
                .setPositiveButton(s(R.string.demo_logout), (dialog, which) -> exitDemo()).show();
    }

    private void exitDemo() {
        if (!beforeNavigation(this::exitDemo)) return;
        persistDraft(); persistPreview();
        if (!settings.demoSessionActive(false)) { toast(s(R.string.entry_state_error)); return; }
        if (voiceRecorder != null) finishVoice(false);
        stopAudio(); DemoNotifications.cancel(this); dismissMenuContext();
        permissionTestCompany = null; permissionTestConversation = null; permissionTestDelay = -1;
        micPermissionCompany = null; micPermissionConversation = null;
        deferredEntryIntent = null;
        setIntent(new Intent(Intent.ACTION_MAIN).setClass(this, MainActivity.class));
        showEntry();
    }

    private void showList() {
        if (!beforeNavigation(this::showList)) return;
        persistDraft(); hideKeyboard(); base("list", LIGHT); conversationId = null;
        mainSection = "list";
        addMainToolbar(); addRecoveryBanner();
        inboxSearchBar = row(this); pad(inboxSearchBar, 12, 2); inboxSearchBar.setBackgroundColor(LIGHT);
        inboxSearchInput = new EditText(this); inboxSearchInput.setSingleLine(); inboxSearchInput.setTextSize(14);
        inboxSearchInput.setHint(s(R.string.ui_059)); inboxSearchInput.setTextColor(INK); inboxSearchInput.setHintTextColor(MUTED);
        inboxSearchInput.setBackground(bg(Color.WHITE, 13, this)); pad(inboxSearchInput, 12, 3); inboxSearchInput.setText(listQuery);
        inboxSearchBar.addView(inboxSearchInput, new LinearLayout.LayoutParams(0, d(44), 1));
        inboxSearchBar.addView(buttonIcon("close", s(R.string.ui_060), MUTED, this::toggleInboxSearch));
        root.addView(inboxSearchBar, p(-1, d(52))); inboxSearchBar.setVisibility(inboxSearchExpanded ? View.VISIBLE : View.GONE);
        if (store.pendingShare() != null) {
            TextView pending = text(this, s(R.string.ui_061), 11, GREEN, true); pad(pending, 20, 5);
            pending.setBackgroundColor(LIME);
            pending.setOnClickListener(v -> { pickerKind = "all"; pickerCompany = "all"; showPicker(true); });
            root.addView(pending, p(-1, d(30)));
        }
        inbox = new ListView(this); inbox.setBackgroundColor(Color.WHITE); inbox.setDivider(null);
        inbox.setClipToPadding(false); inbox.setPadding(0, 0, 0, d(8)); inbox.setVerticalScrollBarEnabled(false);
        root.addView(inbox, new LinearLayout.LayoutParams(-1, 0, 1)); updateInbox();
        inboxSearchInput.addTextChangedListener(watcher(value -> { listQuery = value; updateInbox(); }));
        demoBar(root, true);
        addMainSections();
    }

    private void addMainToolbar() {
        LinearLayout toolbar = row(this); pad(toolbar, 12, 4);
        toolbar.setTag("bwork-main-toolbar"); toolbar.setBackgroundColor(Color.WHITE);
        // Intrinsic mark width at the parent's logical START. The spacer absorbs changing actions,
        // never the wordmark itself. The artwork remains Latin LTR without any mirroring.
        BWorkWordmarkView brand = new BWorkWordmarkView(this); brand.setLayoutDirection(View.LAYOUT_DIRECTION_LTR);
        toolbar.addView(brand, p(-2, d(46)));
        toolbar.addView(new View(this), new LinearLayout.LayoutParams(0, 1, 1));
        if ("list".equals(mainSection)) {
            toolbar.addView(buttonIcon("search", s(R.string.ui_062), GREEN, this::toggleInboxSearch));
            toolbar.addView(buttonIcon("plus", s(R.string.ui_063), GREEN, this::showCreateMenu));
        }
        toolbar.addView(overflowButton(s(R.string.ui_064), this::showInboxMenu));
        root.addView(toolbar, p(-1, d(56)));
    }

    private void addMainSections() {
        // Root footer, outside the weighted scrolling content and above the system navigation bar.
        LinearLayout tabs = row(this); pad(tabs, 10, 4);
        tabs.setTag("bwork-bottom-navigation"); tabs.setBackgroundColor(Color.WHITE); tabs.setBaselineAligned(false);
        String[][] choices = {{s(R.string.ui_065), "list"}, {s(R.string.ui_066), "orders"}, {s(R.string.ui_067), "tasks"}};
        for (String[] choice : choices) {
            boolean selected = choice[1].equals(mainSection);
            TextView tab = text(this, choice[0], 12, selected ? GREEN : MUTED, selected);
            tab.setTag("bwork-section-" + choice[1]); tab.setGravity(Gravity.CENTER); tab.setMinHeight(d(48)); tab.setSelected(selected);
            tab.setBackground(bg(selected ? LIME : Color.TRANSPARENT, 12, this));
            tab.setBreakStrategy(android.graphics.text.LineBreaker.BREAK_STRATEGY_SIMPLE); tab.setPadding(d(5), d(7), d(5), d(7));
            tab.setContentDescription(selected ? s(R.string.selected_section, choice[0]) : choice[0]);
            clickable(tab); tab.setOnClickListener(v -> { if ("list".equals(choice[1])) showList(); else showModule(choice[1]); });
            LinearLayout.LayoutParams size = new LinearLayout.LayoutParams(0, -2, 1); size.setMargins(d(2), 0, d(2), 0); tabs.addView(tab, size);
        }
        root.addView(tabs, p(-1, -2));
    }

    private void showModule(String section) {
        if (!beforeNavigation(() -> showModule(section))) return;
        persistDraft(); hideKeyboard(); mainSection = section; base(section, LIGHT); conversationId = null;
        addMainToolbar();
        ScrollView scroll = new ScrollView(this); LinearLayout body = column(this); pad(body, 18, 18); scroll.addView(body);
        boolean orders = "orders".equals(section);
        body.addView(text(this, orders ? s(R.string.ui_066) : s(R.string.ui_070), 21, INK, true)); spacer(body, 8);
        TextView gate = text(this, s(R.string.module_preview_notice), 12, MUTED, false);
        body.addView(gate, p(-1, -2)); spacer(body, 18);
        if (orders) {
            modulePreviewCard(body, "PO-DEMO-01", s(R.string.ui_074), s(R.string.ui_075), s(R.string.ui_076), s(R.string.ui_077));
            modulePreviewCard(body, "PO-DEMO-02", s(R.string.ui_078), s(R.string.ui_079), s(R.string.ui_080), s(R.string.ui_081));
        } else {
            modulePreviewCard(body, "TASK-DEMO-01", s(R.string.ui_082), s(R.string.ui_083), s(R.string.ui_084), s(R.string.ui_085));
            modulePreviewCard(body, "TASK-DEMO-02", s(R.string.ui_086), s(R.string.ui_087), s(R.string.ui_088), s(R.string.ui_089));
        }
        TextView disabled = action(orders ? s(R.string.ui_090) : s(R.string.ui_091), () -> { });
        disabled.setEnabled(false); disabled.setAlpha(.45f); body.addView(disabled, p(-1, -2));
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1)); demoBar(root, true);
        addMainSections();
    }

    private void modulePreviewCard(LinearLayout body, String id, String title, String context, String status, String detail) {
        LinearLayout card = column(this); pad(card, 16, 15); card.setBackground(bg(Color.WHITE, 18, this));
        TextView reference = text(this, s(R.string.preview_reference, id), 10, GREEN, true); reference.setTextDirection(View.TEXT_DIRECTION_LTR); card.addView(reference);
        spacer(card, 9); card.addView(text(this, title, 17, INK, true)); spacer(card, 7); card.addView(text(this, context, 12, MUTED, false));
        spacer(card, 14); TextView state = text(this, status, 11, GREEN, true); card.addView(state);
        spacer(card, 5); card.addView(text(this, detail, 11, MUTED, false));
        LinearLayout.LayoutParams margin = p(-1, -2); margin.bottomMargin = d(14); body.addView(card, margin);
    }

    private void showUnavailable(String title, String reason) {
        new AlertDialog.Builder(this).setTitle(title).setMessage(reason + s(R.string.ui_092)).setPositiveButton(s(R.string.ui_051), null).show();
    }

    private String demoMembers(String co, String cv) {
        if (!"group".equals(store.conversation(co, cv).kind)) return "";
        List<String> members = store.groupMemberConversationIds(co, cv);
        if (members.isEmpty()) return s(R.string.ui_093);
        StringBuilder names = new StringBuilder();
        for (String id : members) names.append(s(R.string.list_separator)).append(displayName(store.conversation(co, id).title));
        return "\n" + s(R.string.local_member_list, names.toString());
    }

    private void showSettings() {
        if (!beforeNavigation(this::showSettings)) return;
        persistDraft(); hideKeyboard(); base("settings", LIGHT);
        LinearLayout top = row(this); pad(top, 8, 4); top.addView(buttonIcon("back", s(R.string.ui_096), INK, this::showList));
        top.addView(text(this, s(R.string.ui_097), 21, INK, true)); top.setMinimumHeight(d(56)); root.addView(top, p(-1, -2));
        ScrollView scroll = new ScrollView(this); LinearLayout body = column(this); pad(body, 18, 14); scroll.addView(body);
        body.addView(text(this, s(R.string.ui_098), 13, GREEN, true)); spacer(body, 7);
        body.addView(text(this, s(R.string.ui_099), 12, MUTED, false)); spacer(body, 18);
        settingsRow(body, s(R.string.ui_100), s(R.string.ui_101), () -> {
            new AlertDialog.Builder(this).setTitle(s(R.string.ui_102)).setItems(new String[]{s(R.string.ui_065), s(R.string.ui_066), s(R.string.ui_067)}, (dialog, which) -> {
                String category = new String[]{LocalSettingsPolicy.CONVERSATIONS, LocalSettingsPolicy.PURCHASES, LocalSettingsPolicy.TASKS}[which];
                showSoundSettings(category, new String[]{s(R.string.ui_065), s(R.string.ui_066), s(R.string.ui_067)}[which]);
            }).setNegativeButton(s(R.string.ui_051), null).show();
        });
        settingsRow(body, s(R.string.ui_103), settings.hideLockscreen() ? s(R.string.ui_104) : s(R.string.ui_105), () -> {
            boolean[] hidden = {settings.hideLockscreen()};
            new AlertDialog.Builder(this).setTitle(s(R.string.ui_103))
                    .setSingleChoiceItems(new String[]{s(R.string.ui_106), s(R.string.ui_107)}, hidden[0] ? 0 : 1, (dialog, which) -> hidden[0] = which == 0)
                    .setPositiveButton(s(R.string.ui_108), (dialog, which) -> { settings.hideLockscreen(hidden[0]); DemoNotifications.cancel(this); showSettings(); })
                    .setNegativeButton(s(R.string.ui_109), null).show();
        });
        settingsRow(body, s(R.string.ui_110), s(R.string.ui_111), () -> showUnavailable(s(R.string.ui_112), s(R.string.ui_113)));
        settingsRow(body, s(R.string.ui_114), s(R.string.ui_115), this::showStorageSettings);
        settingsRow(body, s(R.string.ui_116), s(R.string.ui_117), () -> showUnavailable(s(R.string.ui_116), s(R.string.ui_118)));
        settingsRow(body, s(R.string.ui_119), s(AppLocale.rtl(this) ? R.string.language_arabic : R.string.language_english), this::showLanguageSettings);
        settingsRow(body, s(R.string.ui_122), s(R.string.ui_123), () -> showUnavailable(s(R.string.ui_122), s(R.string.ui_124)));
        settingsRow(body, s(R.string.ui_125), s(R.string.version_preview, installedVersion()), this::showAbout);
        settingsRow(body, s(R.string.ui_127), s(R.string.ui_128), this::showWhatsNew);
        settingsRow(body, s(R.string.demo_logout), s(R.string.demo_logout_summary), this::confirmLogout);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1)); demoBar(root, true);
    }

    private void settingsRow(LinearLayout body, String title, String subtitle, Runnable click) {
        LinearLayout card = column(this); pad(card, 15, 13); card.setBackground(bg(Color.WHITE, 15, this));
        card.addView(text(this, title, 15, INK, true)); spacer(card, 4); card.addView(text(this, subtitle, 11, MUTED, false));
        clickable(card); card.setOnClickListener(v -> click.run()); LinearLayout.LayoutParams margin = p(-1, -2); margin.bottomMargin = d(9); body.addView(card, margin);
    }

    private void showLanguageSettings() {
        final String original = settings.language();
        final String[] selected = { original };
        new AlertDialog.Builder(this).setTitle(s(R.string.language_title))
                .setSingleChoiceItems(new String[]{s(R.string.language_arabic), s(R.string.language_english)},
                        AppLocalePolicy.ENGLISH.equals(original) ? 1 : 0,
                        (dialog, which) -> selected[0] = which == 0 ? AppLocalePolicy.ARABIC : AppLocalePolicy.ENGLISH)
                .setPositiveButton(s(R.string.language_apply), (dialog, which) -> applyLanguage(selected[0]))
                .setNegativeButton(s(R.string.language_cancel), null).show();
    }

    private void applyLanguage(String selected) {
        if (!AppLocalePolicy.changed(settings.language(), selected)) return;
        if (!beforeNavigation(() -> applyLanguage(selected))) return;
        persistDraft(); persistPreview();
        if (voiceRecorder != null) finishVoice(false);
        stopAudio(); dismissMenuContext();
        if (!settings.language(selected)) { toast(s(R.string.error_language_save)); return; }
        DemoNotifications.refreshLanguage(this);
        recreate();
    }

    private void showSoundSettings(String category, String title) {
        boolean[] chosen = {settings.sound(category), settings.vibration(category)};
        LinearLayout content = column(this); pad(content, 20, 8);
        content.addView(text(this, LocalSettingsPolicy.CONVERSATIONS.equals(category) ? s(R.string.ui_129) : s(R.string.ui_130), 12, MUTED, false));
        CheckBox sound = new CheckBox(this); sound.setText(s(R.string.ui_131)); sound.setChecked(chosen[0]); content.addView(sound);
        CheckBox vibration = new CheckBox(this); vibration.setText(s(R.string.ui_132)); vibration.setChecked(chosen[1]); content.addView(vibration);
        new AlertDialog.Builder(this).setTitle(title).setView(content)
                .setPositiveButton(s(R.string.ui_108), (dialog, which) -> { settings.sound(category, sound.isChecked()); settings.vibration(category, vibration.isChecked()); DemoNotifications.cancel(this); toast(s(R.string.ui_133)); })
                .setNeutralButton(s(R.string.ui_134), (dialog, which) -> { DemoNotifications.ensureChannel(this); startActivity(DemoNotifications.settings(this, false)); })
                .setNegativeButton(s(R.string.ui_109), null).show();
    }

    private void showStorageSettings() {
        final ChatStore targetStore=store;final int epoch=menuContextEpoch;if(storageStatsFuture!=null)storageStatsFuture.cancel(true);
        storageStatsFuture=queryOperation(targetStore::storageStats,stats->{if(epoch!=menuContextEpoch||!"settings".equals(screen))return;
            new AlertDialog.Builder(this).setTitle(s(R.string.ui_114)).setMessage(s(R.string.foundation_storage_details,formatSize(stats.totalPrivateBytes),formatSize(stats.attachmentBytes),stats.attachmentFiles,formatSize(stats.metadataBytes),formatSize(stats.journalBytes),formatSize(stats.legacyBytes),formatSize(stats.recoverableTempBytes),formatSize(stats.usableBytes))).setPositiveButton(s(R.string.ui_051),null).show();});
    }

    private void toggleInboxSearch() {
        if (inboxSearchBar == null) return;
        inboxSearchExpanded = !inboxSearchExpanded;
        inboxSearchBar.setVisibility(inboxSearchExpanded ? View.VISIBLE : View.GONE);
        if (inboxSearchExpanded) {
            inboxSearchInput.requestFocus();
            ((InputMethodManager) getSystemService(INPUT_METHOD_SERVICE)).showSoftInput(inboxSearchInput, InputMethodManager.SHOW_IMPLICIT);
        } else { inboxSearchInput.setText(""); listQuery = ""; hideKeyboard(); updateInbox(); }
    }

    private void showCreateMenu() {
        new AlertDialog.Builder(this).setTitle(s(R.string.ui_137))
                .setItems(new String[]{s(R.string.ui_138), s(R.string.ui_139), s(R.string.ui_140)}, (dialog, which) -> {
                    if (which == 0) { pickerKind = "all"; showPicker(false); } else if (which == 1) showCreateGroup(true);
                    else showUnavailable(s(R.string.ui_141), s(R.string.ui_142));
                }).setNegativeButton(s(R.string.ui_109), null).show();
    }

    private View overflowButton(String description, java.util.function.Consumer<View> open) {
        View button = buttonIcon("more", description, MUTED, () -> { });
        button.setLayoutParams(p(d(48), d(48)));
        button.setTag("bwork-overflow");
        button.setOnClickListener(open::accept);
        return button;
    }

    private AnchoredMenu.Scope menuScope(View anchor) {
        final int epoch = menuContextEpoch;
        final String originalScreen = screen, co = companyId, cv = conversationId;
        final View originalRoot = root;
        return () -> menuHostActive && !destroyed && !isFinishing() && !isDestroyed()
                && epoch == menuContextEpoch && originalRoot == root
                && Objects.equals(originalScreen, screen) && Objects.equals(co, companyId) && Objects.equals(cv, conversationId)
                && anchor.isAttachedToWindow() && anchor.isShown();
    }

    private void dismissMenuContext() {
        menuContextEpoch++;
        if (overflowMenu != null) overflowMenu.dismiss();
        if (menuDialog != null) { menuDialog.dismiss(); menuDialog = null; }
    }

    private void showMenuDialog(AlertDialog dialog, AnchoredMenu.Scope scope) {
        if (!scope.isCurrent()) return;
        if (menuDialog != null) menuDialog.dismiss();
        menuDialog = dialog;
        dialog.setOnDismissListener(closed -> { if (menuDialog == dialog) menuDialog = null; });
        dialog.show();
    }

    private void showInboxMenu(View anchor) {
        AnchoredMenu.Scope scope = menuScope(anchor);
        overflowMenu.show(anchor, s(R.string.ui_143), scope, inboxMenuEntries(scope));
    }

    private List<AnchoredMenu.Entry> inboxMenuEntries(AnchoredMenu.Scope scope) {
        ArrayList<AnchoredMenu.Entry> entries = new ArrayList<>();
        if ("list".equals(screen)) entries.add(AnchoredMenu.Entry.page(s(R.string.ui_144), () -> showInboxFilters(scope)));
        entries.add(AnchoredMenu.Entry.action(s(R.string.ui_145), () -> { pickerKind = "person"; showPicker(false); }));
        entries.add(AnchoredMenu.Entry.action(s(R.string.ui_146), () -> showNotificationTest(ChatStore.INITIAL_COMPANY_ID, ChatStore.INITIAL_COMPANY_ID + "-ops", scope)));
        entries.add(AnchoredMenu.Entry.disabled(s(R.string.ui_147)));
        entries.add(AnchoredMenu.Entry.disabled(s(R.string.ui_148)));
        entries.add(AnchoredMenu.Entry.action(s(R.string.ui_097), this::showSettings));
        entries.add(AnchoredMenu.Entry.action(s(R.string.ui_149), () -> showAbout(scope)));
        return entries;
    }

    private void showInboxFilters(AnchoredMenu.Scope scope) {
        ArrayList<AnchoredMenu.Entry> entries = new ArrayList<>();
        entries.add(AnchoredMenu.Entry.page(s(R.string.ui_150), () -> overflowMenu.replace(s(R.string.ui_143), inboxMenuEntries(scope))));
        String[][] choices = {{s(R.string.ui_151), "all"}, {s(R.string.ui_152), "unread"}, {s(R.string.ui_153), "group"}, {s(R.string.ui_145), "person"}};
        for (String[] choice : choices) entries.add(AnchoredMenu.Entry.choice(choice[0], choice[1].equals(filter), () -> {
            filter = choice[1]; updateInbox();
        }));
        overflowMenu.replace(s(R.string.ui_144), entries);
    }

    private void updateInbox() {
        if (inbox == null || !"list".equals(screen)) return;
        ArrayList<Object> rows = new ArrayList<>();
        String query = listQuery.trim().toLowerCase(Locale.ROOT);
        for (ChatStore.Company company : store.companies()) {
            ArrayList<ChatStore.Conversation> matches = new ArrayList<>();
            for (ChatStore.Conversation c : store.conversations(company.id)) {
                ChatStore.Message last = store.lastMessage(company.id, c.id);
                String haystack = company.name + " " + c.title + " " + (last == null ? "" : last.text);
                boolean match = query.isEmpty() || haystack.toLowerCase(Locale.ROOT).contains(query);
                if (match && ("all".equals(filter) || ("unread".equals(filter) && store.unreadCount(c.companyId, c.id) > 0) || c.kind.equals(filter))) matches.add(c);
            }
            if (matches.isEmpty()) continue;
            rows.add(company);
            // Groups come first within their own company; each row retains its own company id.
            for (ChatStore.Conversation c : matches) if ("group".equals(c.kind)) rows.add(c);
            for (ChatStore.Conversation c : matches) if (!"group".equals(c.kind)) rows.add(c);
        }
        if (rows.isEmpty()) rows.add(s(R.string.ui_154));
        inbox.setAdapter(new BaseAdapter() {
            public int getCount() { return rows.size(); }
            public Object getItem(int i) { return rows.get(i); }
            public long getItemId(int i) { return i; }
            public boolean areAllItemsEnabled() { return false; }
            public boolean isEnabled(int i) { return rows.get(i) instanceof ChatStore.Conversation; }
            public View getView(int i, View old, android.view.ViewGroup parent) {
                Object value = rows.get(i);
                if (value instanceof ChatStore.Company) return companySection((ChatStore.Company) value);
                if (value instanceof String) {
                    TextView empty = text(MainActivity.this, (String) value, 14, MUTED, false);
                    empty.setGravity(Gravity.CENTER); pad(empty, 20, 35); return empty;
                }
                return conversationRow((ChatStore.Conversation) value, false);
            }
        });
        inbox.setOnItemClickListener((a, v, i, id) -> {
            Object value = rows.get(i);
            if (value instanceof ChatStore.Conversation) {
                ChatStore.Conversation c = (ChatStore.Conversation) value;
                showChat(c.companyId, c.id);
            }
        });
    }

    private View companySection(ChatStore.Company company) {
        LinearLayout section = row(this);
        pad(section, 20, 8);
        section.setBackgroundColor(LIGHT);
        section.addView(icon("company", GREEN, 17));
        TextView label = text(this, company.name, 12, MUTED, true);
        label.setTextAlignment(View.TEXT_ALIGNMENT_VIEW_START); label.setPaddingRelative(d(8), 0, 0, 0);
        section.addView(label, new LinearLayout.LayoutParams(0, -2, 1));
        if (Build.VERSION.SDK_INT >= 28) section.setAccessibilityHeading(true);
        return section;
    }

    private View conversationRow(ChatStore.Conversation c, boolean picker) {
        LinearLayout outer = column(this); outer.setBackgroundColor(Color.WHITE);
        outer.setTag("bwork-conversation-" + c.id);
        LinearLayout r = row(this); pad(r, 16, 13); r.setMinimumHeight(d(86));
        Ui.Avatar av = new Ui.Avatar(this, c.title, c.kind, c.avatarHue);
        r.addView(av, p(d(50), d(50)));
        LinearLayout body = column(this);
        LinearLayout.LayoutParams bl = new LinearLayout.LayoutParams(0, -2, 1);
        bl.setMarginStart(d(12)); bl.setMarginEnd(d(12)); r.addView(body, bl);
        TextView name = text(this, settings.mute(c.companyId, c.id) ? s(R.string.muted_conversation, displayName(c.title)) : c.title, 16, INK, true);
        name.setTag("bwork-conversation-name");
        // The box follows the interface, while FIRST_STRONG still shapes each stored name naturally.
        name.setTextAlignment(View.TEXT_ALIGNMENT_VIEW_START);
        name.setSingleLine(); name.setEllipsize(TextUtils.TruncateAt.END); body.addView(name, p(-1, -2));
        spacer(body, 6);
        ChatStore.Message last = store.lastMessage(c.companyId, c.id);
        ChatStore.Draft draft = store.draft(c.companyId, c.id);
        String preview = picker ? displayName(companyName(c.companyId)) + " · " + conversationSubtitle(c) : !draft.text.isEmpty() || !draft.attachments.isEmpty() || draft.replyToMessageId != null ? s(R.string.draft_preview, !draft.text.isEmpty() ? displayName(draft.text) : !draft.attachments.isEmpty() ? s(R.string.ui_157) : s(R.string.ui_158)) : last == null ? s(R.string.ui_159) : last.deleted ? s(R.string.message_deleted) : !last.text.isEmpty() ? last.text : !last.attachments.isEmpty() ? s(R.string.attachment_preview, displayName(last.attachments.get(0).name)) : s(R.string.ui_161);
        TextView sub = text(this, preview, 12, MUTED, false);
        sub.setTag("bwork-conversation-preview"); sub.setTextAlignment(View.TEXT_ALIGNMENT_VIEW_START);
        sub.setSingleLine(); sub.setEllipsize(TextUtils.TruncateAt.END); body.addView(sub, p(-1, -2));
        // A separate intrinsic-width column prevents any name/preview from occupying time/badge space.
        LinearLayout metadata = column(this); metadata.setTag("bwork-conversation-metadata");
        metadata.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
        if (!picker) {
            boolean unread = store.unreadCount(c.companyId, c.id) > 0;
            TextView time = text(this, last == null ? "" : displayTime(last.createdAt), 11, unread ? GREEN : MUTED, false);
            time.setTag("bwork-conversation-time"); time.setSingleLine();
            time.setTextAlignment(View.TEXT_ALIGNMENT_VIEW_END);
            metadata.addView(time, p(-2, -2)); spacer(metadata, 7);
            if (unread) {
                TextView badge = text(this, store.unreadCount(c.companyId, c.id) > 99 ? "99+" : String.valueOf(store.unreadCount(c.companyId, c.id)), 10, Color.WHITE, true);
                badge.setTag("bwork-unread-badge"); badge.setContentDescription(s(R.string.unread_count, store.unreadCount(c.companyId, c.id)));
                badge.setTextDirection(View.TEXT_DIRECTION_LTR); badge.setGravity(Gravity.CENTER);
                badge.setMinWidth(d(22)); badge.setMinHeight(d(22)); pad(badge, 6, 2);
                badge.setBackground(bg(GREEN, 20, this)); metadata.addView(badge, p(-2, -2));
            }
        } else metadata.addView(icon(c.kind.equals("group") ? "group" : c.kind.equals("person") ? "person" : "chat", MUTED, 16));
        r.addView(metadata, p(-2, -2)); outer.addView(r, p(-1, -2));
        View divider = line(this); LinearLayout.LayoutParams dl = p(-1, d(1));
        dl.setMarginStart(d(78)); dl.setMarginEnd(d(16)); outer.addView(divider, dl);
        return outer;
    }

    /** Localized metadata is derived from kind/membership, never by rewriting saved strings. */
    private String conversationSubtitle(ChatStore.Conversation conversation) {
        if ("group".equals(conversation.kind)) {
            List<String> members = store.groupMemberConversationIds(conversation.companyId, conversation.id);
            return members.isEmpty() ? s(R.string.demo_group_subtitle)
                    : s(R.string.local_group_subtitle, members.size() + 1);
        }
        return s("person".equals(conversation.kind) ? R.string.demo_person_subtitle : R.string.demo_chat_subtitle);
    }

    /** Localized export labels surrounding verbatim stored names, text and attachment names. */
    private String messageSummary(ChatStore.Message message) {
        if (message.deleted) return s(R.string.message_deleted);
        String text = message.text.isEmpty() ? "" : message.text;
        if (!message.attachments.isEmpty()) text += (text.isEmpty() ? "" : " · ") + s(R.string.attachment_label, displayName(message.attachments.get(0).name));
        return text.length() > 140 ? text.substring(0, 140) + "…" : text;
    }

    private void beginReply(ChatStore.Message message) {
        if (store.message(message.companyId, message.conversationId, message.id).deleted) { toast(s(R.string.ui_163)); return; }
        if (!"chat".equals(screen) || !message.companyId.equals(companyId) || !message.conversationId.equals(conversationId)) {
            if (!beforeNavigation(() -> beginReply(message))) return; showChat(message.companyId, message.conversationId);
        }
        if (!canEditCurrentDraft()) { toast(s(R.string.foundation_orphan_capacity)); return; }
        if (draftEditor == null || draftEditor.sending() || composer == null) return;
        captureDraft(); EditorState.Snapshot current=draftEditor.snapshot(); draftEditor.update(current.text,current.files,message.id);
        renderReplyTray(); persistDraft(); composer.requestFocus(); composer.announceForAccessibility(s(R.string.foundation_reply_selected,displayName(message.senderName)));
        ((InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).showSoftInput(composer,InputMethodManager.SHOW_IMPLICIT);
    }

    private void renderReplyTray() {
        if (replyTray == null || conversationId == null) return;
        replyTray.removeAllViews();
        EditorState.Snapshot draft=draftEditor==null?null:draftEditor.snapshot();
        if(draft==null||draft.replyId==null)return;
        try {
            ChatStore.Message original = store.message(companyId, conversationId, draft.replyId);
            LinearLayout row = row(this); pad(row, 12, 7); row.setBackgroundColor(LIGHT);
            TextView summary = text(this, s(R.string.reply_to_summary, displayName(original.senderName), messageSummary(original)), 11, GREEN, true);
            summary.setMaxLines(2); summary.setEllipsize(TextUtils.TruncateAt.END); summary.setOnClickListener(v -> showOriginalMessage(original));
            row.addView(summary, new LinearLayout.LayoutParams(0, -2, 1));
            row.addView(buttonIcon("close", s(R.string.ui_165), MUTED, () -> {
                if (!canEditCurrentDraft() || draftEditor.sending()) { toast(s(R.string.foundation_orphan_capacity)); return; }
                captureDraft(); EditorState.Snapshot current=draftEditor.snapshot(); draftEditor.update(current.text,current.files,null);renderReplyTray();persistDraft();
            })); row.setMinimumHeight(d(56)); replyTray.addView(row, p(-1, -2));
        } catch (RuntimeException unavailable) { toast(s(R.string.ui_166)); }
    }

    private void showMessageActions(ChatStore.Message message) {
        ChatStore.Message current = store.message(message.companyId, message.conversationId, message.id);
        ArrayList<String> labels = new ArrayList<>();
        if (!current.deleted) { labels.add(s(R.string.ui_167)); labels.add(s(R.string.ui_168)); if(!current.text.isEmpty())labels.add(s(R.string.foundation_select_text)); }
        labels.add(s(R.string.ui_169));
        if (current.deleted && current.mine && ChatStore.LOCAL_ONLY.equals(current.status)) labels.add(s(R.string.ui_170));
        else if (store.canDeleteMessage(current.companyId, current.conversationId, current.id)) labels.add(s(R.string.ui_171));
        new AlertDialog.Builder(this).setTitle(current.deleted ? s(R.string.message_deleted) : s(R.string.message_from, displayName(current.senderName)))
                .setItems(labels.toArray(new String[0]), (dialog, which) -> {
                    String selected = labels.get(which);
                    if (selected.equals(s(R.string.ui_167))) beginReply(current);
                    else if (selected.equals(s(R.string.ui_168))) copyMessage(current);
                    else if(selected.equals(s(R.string.foundation_select_text)))selectMessageText(current);
                    else if (selected.equals(s(R.string.ui_171))) confirmLocalDelete(current);
                    else if (selected.equals(s(R.string.ui_170))) undoLocalDelete(current);
                    else showOriginalMessage(current);
                }).setNegativeButton(s(R.string.ui_109), null).show();
    }

    private void selectMessageText(ChatStore.Message message) {
        ChatStore.Message current=store.message(message.companyId,message.conversationId,message.id);if(current.deleted){toast(s(R.string.ui_163));return;}
        TextView selection=text(this,current.text,16,INK,false);pad(selection,20,16);selection.setTextIsSelectable(true);ScrollView scroll=new ScrollView(this);scroll.addView(selection);
        new AlertDialog.Builder(this).setTitle(s(R.string.foundation_select_text)).setView(scroll).setPositiveButton(s(R.string.ui_051),null).show();
    }

    private void confirmLocalDelete(ChatStore.Message target) {
        new AlertDialog.Builder(this).setTitle(s(R.string.ui_173))
                .setMessage(s(R.string.local_delete_confirmation,
                        displayName(store.conversation(target.companyId, target.conversationId).title),
                        displayName(companyName(target.companyId)), displayTime(target.createdAt)))
                .setNegativeButton(s(R.string.ui_109), null)
                .setPositiveButton(s(R.string.ui_171), (dialog, which) -> {
                    final ChatStore targetStore=store;
                    storeOperation(()->targetStore.deleteMessageLocally(target.companyId,target.conversationId,target.id),changed->{stopAudio();refreshAfterMessageChange(target.companyId,target.conversationId);toast(s(R.string.ui_176));});
                }).show();
    }

    private void undoLocalDelete(ChatStore.Message target) {
        final ChatStore targetStore=store;storeOperation(()->targetStore.undoLocalDeletion(target.companyId,target.conversationId,target.id),changed->{refreshAfterMessageChange(target.companyId,target.conversationId);toast(s(R.string.ui_177));});
    }

    private void refreshAfterMessageChange(String co, String cv) {
        if ("chat".equals(screen) && co.equals(companyId) && cv.equals(conversationId)) {
            if (!chatSearchQuery.isEmpty()) scheduleChatSearch(chatSearchQuery);
            renderHistory(false); renderReplyTray();
        } else if ("list".equals(screen)) updateInbox();
    }

    private void showOriginalMessage(ChatStore.Message message) {
        ChatStore.Message current = store.message(message.companyId, message.conversationId, message.id);
        LinearLayout content = column(this); pad(content, 16, 12);
        content.addView(text(this, current.senderName + " · " + displayTime(current.createdAt), 12, GREEN, true)); spacer(content, 8);
        TextView body = text(this, current.deleted ? s(R.string.message_deleted) : current.text, 15, INK, false); body.setTextIsSelectable(true); content.addView(body);
        for (ChatStore.Attachment file : current.attachments) { spacer(content, 10); content.addView(attachmentCard(file, true)); }
        ScrollView scroll = new ScrollView(this); scroll.addView(content);
        new AlertDialog.Builder(this).setTitle(s(R.string.ui_179)).setView(scroll)
                .setPositiveButton(s(R.string.ui_051), null).setNeutralButton(s(R.string.ui_180), (dialog, which) -> copyMessage(current)).show();
    }

    private void copyMessage(ChatStore.Message message) {
        ChatStore.Message selected = store.message(message.companyId, message.conversationId, message.id);
        StringBuilder copy = new StringBuilder(selected.deleted ? s(R.string.message_deleted) : selected.text);
        for (ChatStore.Attachment file : selected.attachments) copy.append(copy.length() == 0 ? "" : "\n").append(s(R.string.attachment_label, file.name));
        android.content.ClipboardManager clipboard = (android.content.ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
        try { clipboard.setPrimaryClip(ClipData.newPlainText(s(R.string.ui_181), copy.toString())); toast(s(R.string.ui_182)); }
        catch (RuntimeException unavailable) { toast(s(R.string.ui_183)); }
    }

    private void showChatMenu(View anchor, String co, String cv) {
        if (!"chat".equals(screen) || !Objects.equals(co, companyId) || !Objects.equals(cv, conversationId)) return;
        AnchoredMenu.Scope scope = menuScope(anchor);
        List<AnchoredMenu.Entry> entries = Arrays.asList(
                AnchoredMenu.Entry.action(s(R.string.ui_185), this::toggleChatSearch),
                AnchoredMenu.Entry.action(s(R.string.ui_186), () -> copyChatTranscript(co, cv, scope)),
                AnchoredMenu.Entry.action(s(R.string.ui_187), () -> showMenuDialog(new AlertDialog.Builder(this)
                        .setTitle(store.conversation(co, cv).title)
                        .setMessage(companyName(co) + "\n" + conversationSubtitle(store.conversation(co, cv)) + "\n" + s(R.string.conversation_message_count, store.messageCount(co, cv)) + demoMembers(co, cv) + s(R.string.ui_189))
                        .setPositiveButton(s(R.string.ui_051), null).create(), scope)),
                AnchoredMenu.Entry.action(s(R.string.ui_146), () -> showNotificationTest(co, cv, scope)),
                AnchoredMenu.Entry.action(settings.mute(co, cv) ? s(R.string.ui_190) : s(R.string.ui_191), () -> {
                    settings.mute(co, cv, !settings.mute(co, cv));
                    toast(settings.mute(co, cv) ? s(R.string.ui_192) : s(R.string.ui_193));
                }),
                AnchoredMenu.Entry.disabled(s(R.string.ui_194)),
                AnchoredMenu.Entry.disabled(s(R.string.ui_195)),
                AnchoredMenu.Entry.action(s(R.string.ui_097), this::showSettings));
        overflowMenu.show(anchor, s(R.string.ui_196), scope, entries);
    }

    private static Writer utf8Writer(FileOutputStream output) {
        return new BufferedWriter(new OutputStreamWriter(output, java.nio.charset.StandardCharsets.UTF_8.newEncoder()
                .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT).onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)), 8192);
    }
    private ChatStore.TranscriptLabels transcriptLabels() {
        return new ChatStore.TranscriptLabels() {
            public String header(ChatStore.Company company, ChatStore.Conversation conversation) { String value=s(R.string.transcript_header,company.name,conversation.title);return value.endsWith("\n")?value.substring(0,value.length()-1):value; }
            public String deleted(){return s(R.string.message_deleted);}
            public String reply(ChatStore.Message quoted){return s(R.string.transcript_reply,quoted.senderName,messageSummary(quoted));}
            public String attachment(ChatStore.Attachment file){return s(R.string.attachment_label,file.name);}
        };
    }
    private String conversationTranscript(String co,String cv)throws IOException{
        BoundedTextWriter output=new BoundedTextWriter(128*1024);store.writeConversationTranscript(co,cv,output,transcriptLabels());return output.toString();
    }
    private void saveTranscript(String co,String cv,AnchoredMenu.Scope scope){
        if(!scope.isCurrent())return;final ChatStore targetStore=store;final File directory=new File(getFilesDir(),"attachments");final String title=s(R.string.ui_184);final ChatStore.TranscriptLabels labels=transcriptLabels();
        if(transcriptFuture!=null)transcriptFuture.cancel(true);
        transcriptFuture=queryOperation(()->{
            if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("Cannot create export directory");
            String id=UUID.randomUUID().toString();File file=new File(directory,id+".txt");boolean complete=false;
            try{try(FileOutputStream output=new FileOutputStream(file);Writer writer=utf8Writer(output)){targetStore.writeConversationTranscript(co,cv,writer,labels);writer.flush();output.getFD().sync();}complete=true;return new ChatStore.Attachment(id,file.getAbsolutePath(),title,"text/plain",file.length());}
            finally{if(!complete)file.delete();}
        },file->{if(scope.isCurrent())saveAttachment(file);});
    }
    private void copyChatTranscript(String co,String cv,AnchoredMenu.Scope scope){
        if(!scope.isCurrent())return;if(transcriptFuture!=null)transcriptFuture.cancel(true);
        transcriptFuture=queryOperation(()->conversationTranscript(co,cv),text->{
            if(!scope.isCurrent())return;
            try{((android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText(s(R.string.ui_197),text));toast(s(R.string.ui_198));}
            catch(RuntimeException unavailable){offerTranscriptFile(co,cv,scope);}
        },failure->{if(!scope.isCurrent())return;if(failure instanceof BoundedTextWriter.LimitExceeded)offerTranscriptFile(co,cv,scope);else error(failure);});
    }
    private void offerTranscriptFile(String co,String cv,AnchoredMenu.Scope scope){
        if(!scope.isCurrent())return;showMenuDialog(new AlertDialog.Builder(this).setTitle(s(R.string.ui_199)).setMessage(s(R.string.foundation_transcript_file))
                .setPositiveButton(s(R.string.ui_201),(dialog,which)->{if(scope.isCurrent())saveTranscript(co,cv,scope);}).setNegativeButton(s(R.string.ui_109),null).create(),scope);
    }

    private void buildChatSearchBar() {
        chatSearchBar = row(this); pad(chatSearchBar, 8, 5); chatSearchBar.setBackgroundColor(Color.WHITE);
        chatSearchInput = new EditText(this); chatSearchInput.setSingleLine(); chatSearchInput.setTextSize(13);
        chatSearchInput.setHint(s(R.string.ui_202)); chatSearchInput.setTextColor(INK); chatSearchInput.setBackground(bg(LIGHT, 13, this)); pad(chatSearchInput, 10, 4);
        chatSearchBar.addView(chatSearchInput, new LinearLayout.LayoutParams(0, d(42), 1));
        chatSearchCount = text(this, "0/0", 10, MUTED, false); chatSearchCount.setGravity(Gravity.CENTER); chatSearchCount.setTextDirection(View.TEXT_DIRECTION_LTR); chatSearchBar.addView(chatSearchCount, p(d(48), d(40)));
        TextView previous = text(this, "↑", 24, GREEN, true); previous.setGravity(Gravity.CENTER); previous.setContentDescription(s(R.string.ui_203));
        previous.setOnClickListener(v -> moveChatMatch(-1)); chatSearchBar.addView(previous, p(d(32), d(42)));
        TextView next = text(this, "↓", 24, GREEN, true); next.setGravity(Gravity.CENTER); next.setContentDescription(s(R.string.ui_204));
        next.setOnClickListener(v -> moveChatMatch(1)); chatSearchBar.addView(next, p(d(32), d(42)));
        chatSearchBar.addView(buttonIcon("close", s(R.string.ui_205), MUTED, this::closeChatSearch));
        root.addView(chatSearchBar, p(-1, d(52))); chatSearchBar.setVisibility(View.GONE);
        chatSearchInput.addTextChangedListener(watcher(this::scheduleChatSearch));
    }

    private String selectedSearchId() { return chatMatchIndex >= 0 && chatMatchIndex < chatMatches.size() ? chatMatches.get(chatMatchIndex).id : null; }
    private void toggleChatSearch() {
        if (chatSearchBar == null) return;
        if (chatSearchBar.getVisibility() == View.VISIBLE) { closeChatSearch(); return; }
        chatSearchBar.setVisibility(View.VISIBLE); chatSearchInput.requestFocus();
        ((InputMethodManager) getSystemService(INPUT_METHOD_SERVICE)).showSoftInput(chatSearchInput, InputMethodManager.SHOW_IMPLICIT);
    }
    private void closeChatSearch() {
        if (chatSearchBar == null) return;
        pendingReadingRestore=null;chatSearchRevision++;if(chatSearchTask!=null)handler.removeCallbacks(chatSearchTask);if(chatSearchFuture!=null)chatSearchFuture.cancel(true);
        chatSearchBar.setVisibility(View.GONE);chatSearchInput.setText("");hideKeyboard();chatSearchQuery="";chatMatches.clear();chatMatchIndex=-1;
        historyBefore=null;historyAfter=null;renderHistory(false);
    }
    private void scheduleChatSearch(String query) {
        if (!"chat".equals(screen) || chatSearchCount == null || restoringSearchText) return;
        pendingReadingRestore=null;chatSearchQuery=query;chatMatches.clear();chatMatchIndex=-1;
        if(chatSearchTask!=null)handler.removeCallbacks(chatSearchTask);if(chatSearchFuture!=null)chatSearchFuture.cancel(true);QUERY_IO.purge();
        final int revision=++chatSearchRevision;chatSearchHasEarlier=chatSearchHasLater=false;
        if(query.trim().isEmpty()){chatSearchLoading=false;chatSearchCount.setText("0/0");historyBefore=null;historyAfter=null;renderHistory(false);return;}
        chatSearchLoading=true;chatSearchCount.setText(s(R.string.foundation_search_pending));
        chatSearchTask=()->requestSearchWindow(query,null,true,revision,false);handler.postDelayed(chatSearchTask,250);
    }
    private void requestSearchWindow(String query,String cursor,boolean backwards,int revision,boolean otherSide) {
        final String co=companyId,cv=conversationId;final ChatStore targetStore=store;chatSearchLoading=true;
        if(chatSearchFuture!=null)chatSearchFuture.cancel(true);
        chatSearchFuture=queryOperation(()->backwards?targetStore.searchMessagePageBefore(co,cv,query,cursor,SEARCH_WINDOW):targetStore.searchMessagePage(co,cv,query,cursor,SEARCH_WINDOW),page->{
            if(revision!=chatSearchRevision||!"chat".equals(screen)||!co.equals(companyId)||!cv.equals(conversationId)||!query.equals(chatSearchQuery))return;
            chatSearchLoading=false;chatMatches.clear();chatMatches.addAll(page.messages);chatMatchIndex=chatMatches.isEmpty()?-1:backwards?chatMatches.size()-1:0;
            chatSearchHasEarlier=backwards?page.hasMore:otherSide;chatSearchHasLater=backwards?otherSide:page.hasMore;refreshChatMatch();
        },failure->{if(revision!=chatSearchRevision||!"chat".equals(screen))return;chatSearchLoading=false;chatSearchCount.setText(s(R.string.ui_178));error(failure);});
    }
    private void moveChatMatch(int direction) {
        if(chatSearchLoading||chatMatches.isEmpty())return;int next=chatMatchIndex+direction;
        if(next<0&&chatSearchHasEarlier)requestSearchWindow(chatSearchQuery,chatMatches.get(0).id,true,++chatSearchRevision,true);
        else if(next>=chatMatches.size()&&chatSearchHasLater)requestSearchWindow(chatSearchQuery,chatMatches.get(chatMatches.size()-1).id,false,++chatSearchRevision,true);
        else{chatMatchIndex=Math.max(0,Math.min(chatMatches.size()-1,next));refreshChatMatch();}
    }
    private void refreshChatMatch(){updateSearchCount();pendingReadingRestore=null;historyBefore=selectedSearchId();historyAfter=null;renderHistory(false);}
    private void updateSearchCount(){
        if(chatSearchCount==null)return;boolean more=chatSearchHasEarlier||chatSearchHasLater;
        chatSearchCount.setText(chatMatches.isEmpty()?s(R.string.ui_178):(chatMatchIndex+1)+"/"+chatMatches.size()+(more?"+":""));
        chatSearchCount.setContentDescription(chatMatches.isEmpty()?s(R.string.ui_178):s(more?R.string.foundation_search_more:R.string.foundation_search_window,chatMatchIndex+1,chatMatches.size()));
    }

    private void showCreateGroup(boolean fresh) {
        if (!beforeNavigation(() -> showCreateGroup(fresh))) return;
        persistDraft();
        hideKeyboard();
        if (fresh) { groupNameDraft = ""; groupCompanyDraft = null; groupMemberDraft.clear(); }
        base("create_group", LIGHT);
        LinearLayout header = row(this); pad(header, 8, 10);
        header.addView(buttonIcon("back", s(R.string.ui_206), INK, this::showList));
        header.addView(text(this, s(R.string.ui_207), 21, INK, true));
        root.addView(header, p(-1, d(72)));
        ScrollView scroll = new ScrollView(this);
        LinearLayout body = column(this); pad(body, 22, 8); scroll.addView(body);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        TextView local = text(this, s(R.string.ui_208), 12, MUTED, false);
        body.addView(local); spacer(body, 18);
        body.addView(text(this, s(R.string.ui_209), 13, GREEN, true)); spacer(body, 7);
        EditText name = new EditText(this); name.setSingleLine(); name.setTextSize(16); name.setTextColor(INK);
        name.setHint(s(R.string.ui_210)); name.setHintTextColor(MUTED);
        name.setFilters(new InputFilter[]{new InputFilter.LengthFilter(ChatStore.MAX_GROUP_TITLE_LENGTH)});
        name.setBackground(bg(Color.WHITE, 14, this)); pad(name, 14, 10); name.setText(groupNameDraft);
        name.addTextChangedListener(watcher(value -> groupNameDraft = value)); body.addView(name, p(-1, d(54)));
        spacer(body, 18); body.addView(text(this, s(R.string.ui_211), 13, GREEN, true)); spacer(body, 7);
        TextView company = text(this, groupCompanyDraft == null ? s(R.string.ui_212) : companyName(groupCompanyDraft) + "  ⌄", 14, INK, true);
        company.setBackground(bg(Color.WHITE, 14, this)); pad(company, 14, 12); body.addView(company, p(-1, d(52)));
        spacer(body, 20); body.addView(text(this, s(R.string.ui_213), 14, GREEN, true)); spacer(body, 4);
        body.addView(text(this, s(R.string.ui_214), 11, MUTED, false));
        spacer(body, 8); LinearLayout members = column(this); body.addView(members, p(-1, -2));
        renderGroupMembers(members);
        company.setOnClickListener(v -> {
            ArrayList<String> names = new ArrayList<>();
            for (ChatStore.Company c : store.companies()) names.add(c.name);
            new AlertDialog.Builder(this).setTitle(s(R.string.ui_215)).setItems(names.toArray(new String[0]), (dialog, which) -> {
                String selected = store.companies().get(which).id;
                if (!selected.equals(groupCompanyDraft)) groupMemberDraft.clear();
                groupCompanyDraft = selected;
                company.setText(companyName(selected) + "  ⌄");
                renderGroupMembers(members);
            }).setNegativeButton(s(R.string.ui_109), null).show();
        });
        LinearLayout footer = column(this); pad(footer, 22, 12); footer.setBackgroundColor(Color.WHITE);
        footer.addView(action(s(R.string.ui_216), () -> {
            if (groupCompanyDraft == null) { toast(s(R.string.ui_217)); return; }
            if (groupNameDraft.trim().isEmpty()) { toast(s(R.string.ui_218)); return; }
            if (groupMemberDraft.isEmpty()) { toast(s(R.string.ui_219)); return; }
            if(creatingGroup)return;creatingGroup=true;final ChatStore targetStore=store;final int epoch=navigationEpoch;
            final String groupCompany=groupCompanyDraft,groupName=groupNameDraft;final ArrayList<String> membersCopy=new ArrayList<>(groupMemberDraft);
            storeOperation(()->targetStore.createDemoGroup(groupCompany,groupName,membersCopy),created->{creatingGroup=false;if(epoch==navigationEpoch&&"create_group".equals(screen)){groupNameDraft="";groupCompanyDraft=null;groupMemberDraft.clear();showChat(created.companyId,created.id);}toast(s(R.string.ui_220));},failure->{creatingGroup=false;error(failure);});
        }), p(-1, d(52)));
        root.addView(footer, p(-1, -2)); demoBar(root, true);
    }

    private void renderGroupMembers(LinearLayout parent) {
        parent.removeAllViews();
        if (groupCompanyDraft == null) { TextView hint = text(this, s(R.string.ui_221), 12, MUTED, false); pad(hint, 4, 18); parent.addView(hint); return; }
        for (ChatStore.Conversation person : store.conversations(groupCompanyDraft)) {
            if (!"person".equals(person.kind)) continue;
            LinearLayout item = row(this); pad(item, 12, 8); item.setBackground(bg(Color.WHITE, 14, this));
            item.addView(new Ui.Avatar(this, person.title, person.kind, person.avatarHue), p(d(40), d(40)));
            CheckBox check = new CheckBox(this); check.setText(person.title); check.setTextSize(14); check.setTextColor(INK);
            check.setButtonTintList(android.content.res.ColorStateList.valueOf(GREEN)); check.setChecked(groupMemberDraft.contains(person.id));
            check.setOnCheckedChangeListener((button, selected) -> { if (selected) groupMemberDraft.add(person.id); else groupMemberDraft.remove(person.id); });
            LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(0, d(50), 1); layout.setMargins(d(8), 0, d(8), 0); item.addView(check, layout);
            parent.addView(item, p(-1, d(66))); spacer(parent, 7);
        }
    }

    private String installedVersion() {
        try {
            android.content.pm.PackageInfo installed = getPackageManager().getPackageInfo(getPackageName(), 0);
            long code = Build.VERSION.SDK_INT >= 28 ? installed.getLongVersionCode() : installed.versionCode;
            return installed.versionName + " (" + code + ")";
        } catch (android.content.pm.PackageManager.NameNotFoundException unavailable) {
            return s(R.string.ui_222);
        }
    }

    private void showAbout() { showAbout(null); }

    private void showAbout(AnchoredMenu.Scope scope) {
        if (scope != null && !scope.isCurrent()) return;
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(s(R.string.ui_223))
                .setMessage(s(R.string.about_body, installedVersion(), getPackageName()))
                .setPositiveButton(s(R.string.ui_226), null).setNeutralButton(s(R.string.ui_127), (closed, which) -> showWhatsNew(scope)).create();
        if (scope == null) dialog.show(); else showMenuDialog(dialog, scope);
    }

    private void showWhatsNew() { showWhatsNew(null); }

    private void showWhatsNew(AnchoredMenu.Scope scope) {
        if (scope != null && !scope.isCurrent()) return;
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(s(R.string.whats_new_title, installedVersion()))
                .setMessage(s(R.string.whats_new_body))
                .setPositiveButton(s(R.string.ui_051), null).create();
        if (scope == null) dialog.show(); else showMenuDialog(dialog, scope);
    }

    private void showChat(String co, String cv) {
        if (!beforeNavigation(() -> showChat(co, cv))) return;
        pendingReadingRestore = readingState != null && readingState.matches(co, cv) ? readingState : null;
        persistDraft();
        hideKeyboard();
        companyId = co;
        conversationId = cv;
        final ChatStore readStore = store;
        STORE_IO.execute(() -> {
            try { readStore.markRead(co, cv); handler.post(() -> { MainActivity active = activeActivity.get(); if (active != null && active.activityAlive() && "list".equals(active.screen)) active.updateInbox(); }); }
            catch (IOException | RuntimeException failure) { handler.post(() -> { if (activityAlive()) { if (readStore.requiresReopen()) showUncertainHistory(); else toast(s(R.string.foundation_read_marker_failed)); } }); }
        });
        pageLimit = HISTORY_WINDOW; historyBefore = null; historyAfter = null;
        chatMatches.clear(); chatMatchIndex = -1; chatSearchQuery = "";
        ChatStore.Conversation chat = store.conversation(co, cv);
        base("chat", Color.WHITE);
        LinearLayout header = row(this);
        pad(header, 8, 3);
        header.addView(buttonIcon("back", s(R.string.ui_229), INK, this::showList));
        Ui.Avatar avatar = new Ui.Avatar(this, chat.title, chat.kind, chat.avatarHue);
        header.addView(avatar, p(d(40), d(40)));
        LinearLayout title = column(this);
        LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(0, -2, 1);
        tp.setMargins(d(10), 0, d(10), 0);
        header.addView(title, tp);
        TextView name = text(this, chat.title, 16, INK, true);
        name.setTextAlignment(View.TEXT_ALIGNMENT_VIEW_START);
        name.setSingleLine(true);
        name.setEllipsize(TextUtils.TruncateAt.END);
        title.addView(name);
        spacer(title, 3);
        TextView sub = text(this, currentCompany().name, 11, MUTED, false);
        sub.setTextAlignment(View.TEXT_ALIGNMENT_VIEW_START); sub.setEllipsize(TextUtils.TruncateAt.END);
        sub.setSingleLine();
        title.addView(sub);
        header.addView(buttonIcon("search", s(R.string.ui_185), GREEN, this::toggleChatSearch));
        header.addView(overflowButton(s(R.string.ui_196), anchor -> showChatMenu(anchor, co, cv)));
        header.setMinimumHeight(d(56)); root.addView(header, p(-1, -2));
        demoBar(root, true);
        buildChatSearchBar();
        FrameLayout body = new FrameLayout(this);
        body.addView(new Wallpaper(this), new FrameLayout.LayoutParams(-1, -1));
        messageScroll = new ScrollView(this);
        messageScroll.setFillViewport(true);
        messageScroll.setVerticalScrollBarEnabled(false);
        history = column(this);
        pad(history, 14, 8);
        messageScroll.addView(history);
        body.addView(messageScroll, new FrameLayout.LayoutParams(-1, -1));
        root.addView(body, new LinearLayout.LayoutParams(-1, 0, 1));
        if (pendingReadingRestore == null) renderHistory(false);
        replyTray = column(this); root.addView(replyTray, p(-1, -2));
        attachmentTray = column(this);
        root.addView(attachmentTray, p(-1, -2));
        buildVoiceControls();
        draftEditor = obtainDraftEditor(co, cv);
        EditorState.Snapshot draft = draftEditor.snapshot(); draftViewRevision = draft.revision;
        draftFiles = new ArrayList<>(draft.files); addEditorStatus();
        LinearLayout bar = row(this);
        bar.setGravity(Gravity.BOTTOM);
        pad(bar, 10, 9);
        bar.setBackgroundColor(Color.WHITE);
        FrameLayout inputBox = new FrameLayout(this);
        inputBox.setBackground(bg(LIGHT, 25, this));
        LinearLayout inputs = row(this);
        inputs.setGravity(Gravity.BOTTOM);
        composer = new EditText(this);
        composer.setTextColor(INK);
        composer.setHintTextColor(MUTED);
        composer.setTextSize(15);
        composer.setHint(s(R.string.ui_230));
        composer.setBackgroundColor(Color.TRANSPARENT);
        composer.setMaxLines(5);
        composer.setFilters(new InputFilter[]{new InputFilter.LengthFilter(ChatStore.MAX_TEXT_LENGTH)});
        composer.setMinLines(1);
        composer.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE | android.text.InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        composer.setImeOptions(android.view.inputmethod.EditorInfo.IME_FLAG_NO_EXTRACT_UI);
        composer.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        pad(composer, 14, 10);
        composer.setText(draft.text); composer.setEnabled(!draftEditor.sending() && canEditCurrentDraft());
        inputs.addView(composer, new LinearLayout.LayoutParams(0, -2, 1));
        composerAttach = buttonIcon("attach", s(R.string.ui_231), MUTED, this::attachmentMenu);
        composerAttach.setEnabled(!draftEditor.sending() && canEditCurrentDraft());
        inputs.addView(composerAttach);
        inputBox.addView(inputs, new FrameLayout.LayoutParams(-1, -2));
        bar.addView(inputBox, new LinearLayout.LayoutParams(0, -2, 1));
        composerAction = new Ui.ActionButton(this); composerAction.setBackground(bg(GREEN, 24, this));
        composerActionGlyph = icon("mic", Color.WHITE, 24);
        composerAction.addView(composerActionGlyph, new FrameLayout.LayoutParams(d(24), d(24), Gravity.CENTER));
        clickable(composerAction);
        composerAction.setOnClickListener(v -> {
            if (suppressComposerClick) { suppressComposerClick = false; return; }
            if (voiceGesture.isActive()) applyVoiceAction(voiceGesture.onStop());
            else if (hasComposedContent()) sendDraft(); else requestVoiceRecording();
        });
        composerAction.setOnTouchListener(this::onVoiceTouch);
        LinearLayout.LayoutParams sl = p(d(48), d(48)); sl.setMarginEnd(d(8));
        bar.addView(composerAction, sl);
        root.addView(bar, p(-1, -2));
        renderDraftFiles();
        renderReplyTray();
        final LinearLayout chatRoot = root;
        chatRoot.addOnLayoutChangeListener((view,l,t,r,b,ol,ot,or,ob)->{
            if (!"chat".equals(screen) || root != chatRoot || composer == null) return;
            int available = (int)((b - t) / getResources().getDisplayMetrics().density);
            boolean compact = available < 440;
            if (compactDrafts != compact) { compactDrafts = compact; renderDraftFiles(); }
            if (attachmentTray != null) attachmentTray.setVisibility(voiceGesture.isActive() || (compact && !hasAudioDraft()) ? View.GONE : View.VISIBLE);
            if (replyTray != null) replyTray.setVisibility(View.VISIBLE);
            int horizontalPadding = d(10), verticalPadding = d(available < 300 ? 4 : 9);
            if (bar.getPaddingLeft() != horizontalPadding || bar.getPaddingRight() != horizontalPadding
                    || bar.getPaddingTop() != verticalPadding || bar.getPaddingBottom() != verticalPadding)
                bar.setPadding(horizontalPadding, verticalPadding, horizontalPadding, verticalPadding);
            int maxComposerLines = available < 300 ? 1 : available < 470 ? 2 : 5;
            // TextView.setMaxLines requests layout even when the value is unchanged. Calling it
            // on every root layout can keep scheduling another layout pass and prevent UI idle.
            if (composer.getMaxLines() != maxComposerLines) composer.setMaxLines(maxComposerLines);
        });
        composer.addTextChangedListener(watcher((value)->{ captureDraft(); scheduleDraftSave(); updateComposerAction(); updateEditorStatus(); }));
        updateComposerAction(); updateEditorStatus();
        if (pendingReadingRestore != null) restoreReadingSearch(pendingReadingRestore);
    }

    /** One bounded checkpoint; no history body is serialized into Android saved state. */
    private static final class ReadingState implements Serializable {
        private static final long serialVersionUID = 1L;
        final String company, conversation, firstId, anchorId, query, selectedId;
        final int anchorOffset; final boolean searchOpen;
        ReadingState(String co, String cv, String first, String anchor, int offset, String query, String selected, boolean open) {
            company=co;conversation=cv;firstId=first;anchorId=anchor;anchorOffset=offset;this.query=query;selectedId=selected;searchOpen=open;
        }
        boolean matches(String co,String cv){return company.equals(co)&&conversation.equals(cv);}
    }
    private void captureReadingState() {
        if (!"chat".equals(screen) || history == null || messageScroll == null || displayedMessages.isEmpty()) return;
        String anchor = displayedMessages.get(0).id; int offset = 0;
        for (ChatStore.Message value : displayedMessages) {
            View view = messageViews.get(value.id); if (view == null) continue;
            Rect bounds = new Rect(); view.getDrawingRect(bounds); history.offsetDescendantRectToMyCoords(view, bounds);
            if (bounds.bottom > messageScroll.getScrollY()) { anchor = value.id; offset = bounds.top - messageScroll.getScrollY(); break; }
        }
        ChatStore.Message first = displayedMessages.get(0);
        readingState = new ReadingState(first.companyId, first.conversationId, first.id, anchor, offset, chatSearchQuery,
                selectedSearchId(), chatSearchBar != null && chatSearchBar.getVisibility() == View.VISIBLE);
    }
    private void restoreReadingSearch(ReadingState saved) {
        final String co = companyId, cv = conversationId; final int revision = ++chatSearchRevision; final ChatStore targetStore = store;
        chatSearchQuery = saved.query; restoringSearchText = true;
        try { chatSearchInput.setText(saved.query); } finally { restoringSearchText = false; }
        chatSearchBar.setVisibility(saved.searchOpen ? View.VISIBLE : View.GONE);
        if (saved.query.trim().isEmpty()) { renderHistory(false); return; }
        chatSearchLoading = true; if (chatSearchFuture != null) chatSearchFuture.cancel(true);
        chatSearchFuture = queryOperation(() -> {
            String before = null;
            if (saved.selectedId != null) { ChatStore.Page next = targetStore.pageAfter(co, cv, saved.selectedId, 1); if (!next.messages.isEmpty()) before = next.messages.get(0).id; }
            ChatStore.SearchPage page = targetStore.searchMessagePageBefore(co, cv, saved.query, before, SEARCH_WINDOW);
            boolean newer = !page.messages.isEmpty() && !targetStore.searchMessagePage(co, cv, saved.query, page.messages.get(page.messages.size()-1).id, 1).messages.isEmpty();
            return new RestoredSearch(page, newer);
        }, result -> {
            if (revision != chatSearchRevision || !"chat".equals(screen) || !co.equals(companyId) || !cv.equals(conversationId)) return;
            chatSearchLoading = false; chatMatches.clear(); chatMatches.addAll(result.page.messages); chatMatchIndex = chatMatches.isEmpty() ? -1 : chatMatches.size()-1;
            for (int index=0;index<chatMatches.size();index++) if (chatMatches.get(index).id.equals(saved.selectedId)) chatMatchIndex=index;
            chatSearchHasEarlier=result.page.hasMore;chatSearchHasLater=result.hasNewer;updateSearchCount();renderHistory(false);
        }, failure -> {
            if (revision != chatSearchRevision) return;
            chatSearchLoading=false;pendingReadingRestore=null;
            if (failure instanceof IllegalArgumentException) { scheduleChatSearch(saved.query); toast(s(R.string.foundation_reading_unavailable)); }
            else { renderHistory(false); error(failure); }
        });
    }
    private static final class RestoredSearch {
        final ChatStore.SearchPage page; final boolean hasNewer;
        RestoredSearch(ChatStore.SearchPage page,boolean newer){this.page=page;hasNewer=newer;}
    }
    private void renderHistory(boolean older) {
        if (history == null || messageScroll == null || conversationId == null) return;
        if (older) { pendingReadingRestore=null; if(historyLoading || !olderAvailable || nextBefore==null)return;historyBefore=nextBefore;historyAfter=null; }
        final int revision=++historyRevision;final String co=companyId,cv=conversationId,before=historyBefore,after=historyAfter,selected=selectedSearchId();
        final boolean include=after==null && selected!=null && selected.equals(before);final ChatStore targetStore=store;final LinearLayout expected=history;
        final ReadingState restore=pendingReadingRestore!=null && pendingReadingRestore.matches(co,cv)?pendingReadingRestore:null;
        historyLoading=true;if(historyFuture!=null)historyFuture.cancel(true);
        historyFuture=queryOperation(()->{
            ChatStore.Page page;
            if(restore!=null){ChatStore.Page previous=targetStore.page(co,cv,restore.firstId,1);String cursor=previous.messages.isEmpty()?null:previous.messages.get(previous.messages.size()-1).id;page=targetStore.pageAfter(co,cv,cursor,HISTORY_WINDOW);}
            else page=after==null?targetStore.page(co,cv,before,include?HISTORY_WINDOW-1:HISTORY_WINDOW):targetStore.pageAfter(co,cv,after,HISTORY_WINDOW);
            ArrayList<ChatStore.Message> messages=new ArrayList<>(page.messages);if(restore==null&&include)messages.add(targetStore.message(co,cv,selected));
            boolean hasOlder=restore==null&&after==null?page.hasMore:!messages.isEmpty()&&!targetStore.page(co,cv,messages.get(0).id,1).messages.isEmpty();
            boolean hasNewer=!messages.isEmpty()&&!targetStore.pageAfter(co,cv,messages.get(messages.size()-1).id,1).messages.isEmpty();
            return new HistoryWindow(messages,messages.isEmpty()?null:messages.get(0).id,hasOlder,hasNewer);
        },window->{
            if(revision!=historyRevision||history!=expected||!"chat".equals(screen)||!co.equals(companyId)||!cv.equals(conversationId))return;
            historyLoading=false;displayedMessages.clear();displayedMessages.addAll(window.messages);nextBefore=window.nextBefore;olderAvailable=window.hasOlder;
            renderHistoryWindow(window.hasNewer,selected,older,restore);
        },failure->{
            if(revision!=historyRevision||history!=expected)return;historyLoading=false;
            if(restore!=null&&failure instanceof IllegalArgumentException){pendingReadingRestore=null;historyBefore=selectedSearchId();historyAfter=null;renderHistory(false);toast(s(R.string.foundation_reading_unavailable));}
            else error(failure);
        });
    }
    private static final class HistoryWindow {
        final ArrayList<ChatStore.Message> messages;final String nextBefore;final boolean hasOlder,hasNewer;
        HistoryWindow(ArrayList<ChatStore.Message> messages,String next,boolean older,boolean newer){this.messages=messages;nextBefore=next;hasOlder=older;hasNewer=newer;}
    }
    private void renderHistoryWindow(boolean earlierWindow,String selected,boolean older,ReadingState restore) {
        history.removeAllViews();messageViews.clear();
        if(olderAvailable){
            TextView more=text(this,s(R.string.ui_232),13,GREEN,true);more.setTag("bwork-history-older");more.setGravity(Gravity.CENTER);pad(more,14,10);more.setBackground(bg(Color.WHITE,18,this));clickable(more);
            LinearLayout.LayoutParams params=p(-2,d(48));params.gravity=Gravity.CENTER;params.setMargins(0,d(4),0,d(12));history.addView(more,params);more.setOnClickListener(view->renderHistory(true));
        }else{TextView intro=text(this,s(R.string.ui_233),11,MUTED,false);intro.setGravity(Gravity.CENTER);pad(intro,12,14);history.addView(intro,p(-1,-2));}
        TextView notice=text(this,s(R.string.ui_234),10,MUTED,false);notice.setGravity(Gravity.CENTER);pad(notice,14,9);notice.setBackground(bg(LIGHT,12,this));
        LinearLayout.LayoutParams np=p(-1,-2);np.setMargins(d(8),0,d(8),d(16));history.addView(notice,np);
        String previousDay="";SimpleDateFormat day=new SimpleDateFormat("d MMMM yyyy",AppLocale.locale(this)),key=new SimpleDateFormat("yyyy-MM-dd",Locale.ROOT);
        for(ChatStore.Message message:displayedMessages){Date created=new Date(message.createdAt);String thisDay=key.format(created);
            if(!thisDay.equals(previousDay)){TextView date=text(this,day.format(created),10,MUTED,true);date.setGravity(Gravity.CENTER);date.setBackground(bg(Color.WHITE,11,this));pad(date,12,5);LinearLayout.LayoutParams dp=p(-2,-2);dp.gravity=Gravity.CENTER;dp.setMargins(0,d(6),0,d(13));history.addView(date,dp);previousDay=thisDay;}
            history.addView(messageBubble(message));
        }
        if(earlierWindow){LinearLayout navigation=row(this);navigation.setGravity(Gravity.CENTER);
            if(!displayedMessages.isEmpty()){
                TextView newer=text(this,s(R.string.foundation_history_newer),13,GREEN,true);newer.setTag("bwork-history-newer");newer.setGravity(Gravity.CENTER);pad(newer,14,12);clickable(newer);
                newer.setOnClickListener(view->{if(historyLoading||displayedMessages.isEmpty())return;historyAfter=displayedMessages.get(displayedMessages.size()-1).id;historyBefore=null;renderHistory(false);});navigation.addView(newer,new LinearLayout.LayoutParams(0,d(48),1));
            }
            TextView latest=text(this,s(R.string.foundation_history_latest),13,GREEN,true);latest.setTag("bwork-history-latest");latest.setGravity(Gravity.CENTER);pad(latest,14,12);clickable(latest);
            latest.setOnClickListener(view->{historyBefore=null;historyAfter=null;closeChatSearch();});navigation.addView(latest,new LinearLayout.LayoutParams(0,d(48),1));history.addView(navigation,p(-1,-2));
        }
        final LinearLayout rendered=history;final ScrollView scroll=messageScroll;final int revision=historyRevision;
        scroll.post(()->{
            if(!activityAlive()||history!=rendered||revision!=historyRevision)return;
            View anchor=restore==null?null:messageViews.get(restore.anchorId);
            if(anchor!=null){Rect bounds=new Rect();anchor.getDrawingRect(bounds);rendered.offsetDescendantRectToMyCoords(anchor,bounds);scroll.scrollTo(0,Math.max(0,bounds.top-restore.anchorOffset));pendingReadingRestore=null;captureReadingState();return;}
            pendingReadingRestore=null;View hit=selected==null?null:messageViews.get(selected);
            if(hit!=null){Rect bounds=new Rect();hit.getDrawingRect(bounds);rendered.offsetDescendantRectToMyCoords(hit,bounds);scroll.scrollTo(0,Math.max(0,bounds.top-d(12)));}
            else if(!earlierWindow||older)scroll.fullScroll(View.FOCUS_DOWN);else scroll.scrollTo(0,0);
        });
    }

    private View messageBubble(ChatStore.Message m) {
        LinearLayout outer = column(this);
        outer.setGravity(m.mine ? Gravity.START : Gravity.END);
        LinearLayout bubble = new Ui.ReplySwipeLayout(this,s(R.string.foundation_reply),m.deleted?null:()->beginReply(m));
        bubble.setTag("bwork-message-"+m.id);
        bubble.setBackground(m.id.equals(selectedSearchId()) ? outline(m.mine ? LIME : Color.WHITE, GREEN, 17, this) : bg(m.mine ? LIME : Color.WHITE, 17, this));
        messageViews.put(m.id, bubble);
        bubble.setOnLongClickListener(v -> { showMessageActions(m); return true; });
        pad(bubble, 12, 9);
        int max = (int)(windowWidth() * 0.79F);
        // A vertical LinearLayout otherwise gives text MATCH_PARENT width. Its uniform-width
        // pass can shrink every label to a 1px spacer inside this WRAP_CONTENT bubble.
        // Let content (including the footer on short messages) establish the bubble width.
        if (!m.mine && "group".equals(store.conversation(companyId, conversationId).kind)) {
            TextView sender = text(this, m.senderName, 11, GREEN, true);
            sender.setMaxWidth(max - d(28));
            bubble.addView(sender, p(-2, -2));
            spacer(bubble, 4);
        }
        if (m.replyToMessageId != null) {
            try {
                ChatStore.Message original = store.message(m.companyId, m.conversationId, m.replyToMessageId);
                TextView quote = text(this, "↩ " + original.senderName + "\n" + messageSummary(original), 11, GREEN, false);
                quote.setMaxLines(3); quote.setEllipsize(TextUtils.TruncateAt.END); quote.setMaxWidth(max - d(28));
                pad(quote, 10, 8); quote.setBackground(bg(LIGHT, 10, this));
                quote.setOnClickListener(v -> showOriginalMessage(original)); quote.setOnLongClickListener(v->{showMessageActions(m);return true;}); bubble.addView(quote, p(-2, -2)); spacer(bubble, 7);
            } catch (IllegalArgumentException unavailable) { }
        }
        for (ChatStore.Attachment a : m.attachments) {
            View attachment = attachmentCard(a, false);
            attachment.setOnLongClickListener(v -> { showMessageActions(m); return true; });
            bubble.addView(attachment);
            spacer(bubble, 6);
        }
        if (m.deleted) { TextView removed = text(this, s(R.string.message_deleted), 13, MUTED, false); removed.setTypeface(android.graphics.Typeface.create("sans-serif", android.graphics.Typeface.ITALIC)); removed.setMaxWidth(max - d(28)); bubble.addView(removed, p(-2, -2)); }
        if (!m.text.isEmpty()) {
            TextView body = text(this, m.text, 15, INK, false);
            body.setMaxWidth(max - d(28));
            body.setLineSpacing(d(2), 1.05F);
            body.setTextIsSelectable(false); body.setOnLongClickListener(view->{showMessageActions(m);return true;});
            bubble.addView(body, p(-2, -2));
        }
        LinearLayout meta = row(this);
        meta.setGravity(Gravity.END);
        TextView stamp = text(this, s(m.mine ? R.string.message_time_local : R.string.message_time_demo, displayTime(m.createdAt)), 9, MUTED, false);
        meta.addView(stamp);
        TextView reply = text(this,s(R.string.foundation_reply),13,GREEN,true);pad(reply,10,6);reply.setMinWidth(d(64));reply.setMinHeight(d(48));reply.setGravity(Gravity.CENTER);reply.setTag("bwork-reply-"+m.id);clickable(reply);
        reply.setContentDescription(m.deleted ? s(R.string.ui_238) : s(R.string.ui_239)); reply.setText(m.deleted ? s(R.string.foundation_message_options) : s(R.string.foundation_reply)); reply.setOnClickListener(v -> { if (m.deleted) showMessageActions(m); else beginReply(m); }); meta.addView(reply);
        LinearLayout.LayoutParams mt = p(-2, -2);
        mt.gravity = Gravity.END;
        mt.topMargin = d(5);
        bubble.addView(meta, mt);
        LinearLayout.LayoutParams bp = p(-2, -2);
        bp.setMarginStart(m.mine ? 0 : d(30)); bp.setMarginEnd(m.mine ? d(30) : 0); bp.bottomMargin = d(9);
        outer.addView(bubble, bp);
        return outer;
    }

    private static final class OrphanEditor implements Serializable {
        private static final long serialVersionUID = 1L;
        final String id; final EditorState.Snapshot snapshot;
        OrphanEditor(EditorState.Snapshot value) {
            snapshot = value;
            try {
                java.security.MessageDigest hash = java.security.MessageDigest.getInstance("SHA-256");
                for (String part : new String[]{value.editorId, String.valueOf(value.revision), value.company, value.conversation,
                        value.shareId, value.text, value.replyId, value.sendToken, value.sendCompany, value.sendConversation}) updateRecoveryDigest(hash, part);
                for (ChatStore.Attachment file : value.files) updateRecoveryDigest(hash, file.id);
                StringBuilder text = new StringBuilder(); for (byte b : hash.digest()) text.append(String.format(Locale.ROOT, "%02x", b & 255)); id = text.toString();
            } catch (java.security.NoSuchAlgorithmException unavailable) { throw new IllegalStateException(unavailable); }
        }
    }
    private static void updateRecoveryDigest(java.security.MessageDigest hash, String value) {
        if (value == null) { hash.update(new byte[]{-1, -1, -1, -1}); return; }
        int length = value.length(); hash.update(new byte[]{(byte)(length >>> 24), (byte)(length >>> 16), (byte)(length >>> 8), (byte)length});
        for (int index = 0; index < length; index++) { char unit = value.charAt(index); hash.update((byte)(unit >>> 8)); hash.update((byte)unit); }
    }
    private static boolean knownTarget(ChatStore saved, String co, String cv) {
        if (co == null || cv == null) return false;
        try { saved.conversation(co, cv); return true; } catch (IllegalArgumentException absent) { return false; }
    }
    private static boolean hasOrphanEditors() { synchronized (processEditors) { return !processOrphanEditors.isEmpty(); } }
    private static boolean hasOrphanDraftTarget(String co, String cv) {
        synchronized (processEditors) {
            for (OrphanEditor orphan : processOrphanEditors.values()) if (orphan.snapshot.shareId == null
                    && Objects.equals(co, orphan.snapshot.company) && Objects.equals(cv, orphan.snapshot.conversation)) return true;
            return false;
        }
    }
    private static void retainOrphan(EditorState.Snapshot snapshot) {
        OrphanEditor orphan = new OrphanEditor(snapshot);
        if (recoveryReceipts != null && recoveryReceipts.getBoolean(orphan.id, false)) return;
        processOrphanEditors.put(orphan.id, orphan);
    }
    private static void admitRecoveredEditor(ChatStore saved, EditorState.Snapshot value, boolean readOnly) {
        if (value.text == null || value.text.length() > ChatStore.MAX_TEXT_LENGTH || value.files.size() > 10) throw new IllegalArgumentException("Invalid editor recovery payload");
        String key = value.shareId == null ? editorKey(value.company, value.conversation) : previewKey(value.shareId);
        if (processEditors.containsKey(key)) return;
        if (value.shareId != null) {
            if (saved.isPendingShareResolved(value.shareId)) return;
            if (value.sendToken != null && knownTarget(saved, value.sendCompany, value.sendConversation)
                    && saved.findMessageByClientId(value.sendCompany, value.sendConversation, value.sendToken, value.shareId) != null) return;
            ChatStore.PendingShare pending = saved.pendingShare();
            if (readOnly || pending == null || !pending.id.equals(value.shareId)) { retainOrphan(value); return; }
        } else {
            if (!knownTarget(saved, value.company, value.conversation)) { retainOrphan(value); return; }
            if (value.sendToken != null && saved.findMessageByClientId(value.company, value.conversation, value.sendToken) != null) return;
            if (value.replyId != null) try { saved.message(value.company, value.conversation, value.replyId); }
            catch (IllegalArgumentException absent) { retainOrphan(value); return; }
            if (readOnly) { retainOrphan(value); return; }
        }
        EditorState restored = EditorState.recover(value); restored.cancelRecoveredSend(); processEditors.put(key, restored);
    }
    private void addRecoveryBanner() {
        if (!hasOrphanEditors()) return;
        TextView banner = text(this, s(R.string.foundation_orphan_banner), 13, GREEN, true);
        banner.setTag("bwork-orphan-recovery-banner"); banner.setMinHeight(d(48)); pad(banner, 16, 10); banner.setBackgroundColor(LIME); clickable(banner);
        banner.setOnClickListener(view -> showRecoveredEditor(null)); root.addView(banner, p(-1, -2));
    }
    private void showRecoveredEditor(String selectedId) {
        if (!beforeNavigation(() -> showRecoveredEditor(selectedId))) return;
        final ArrayList<OrphanEditor> records;
        synchronized (processEditors) { records = new ArrayList<>(processOrphanEditors.values()); }
        if (records.isEmpty()) { showList(); return; }
        OrphanEditor chosen = records.get(0); for (OrphanEditor item : records) if (item.id.equals(selectedId)) chosen = item;
        final OrphanEditor record = chosen; final EditorState.Snapshot value = record.snapshot;
        hideKeyboard(); base("recovery", LIGHT); conversationId = null; recoveredEditorKey = record.id;
        LinearLayout header = row(this); pad(header, 8, 6); header.addView(buttonIcon("back", s(R.string.ui_096), INK, this::showList));
        header.addView(text(this, s(R.string.foundation_orphan_title), 19, INK, true), new LinearLayout.LayoutParams(0, -2, 1)); root.addView(header, p(-1, -2));
        ScrollView scroll = new ScrollView(this); LinearLayout body = column(this); pad(body, 18, 14); scroll.addView(body); root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        body.addView(text(this, s(R.string.foundation_orphan_notice), 13, MUTED, false)); spacer(body, 12);
        if (records.size() > 1) {
            body.addView(action(s(R.string.foundation_orphan_choose, records.size()), () -> {
                String[] labels = new String[records.size()]; for (int i = 0; i < labels.length; i++) labels[i] = s(R.string.foundation_orphan_number, i + 1);
                new AlertDialog.Builder(this).setTitle(s(R.string.foundation_orphan_title)).setItems(labels, (dialog, which) -> showRecoveredEditor(records.get(which).id))
                        .setNegativeButton(s(R.string.ui_109), null).show();
            }), p(-1, -2)); spacer(body, 12);
        }
        TextView content = text(this, value.text.isEmpty() ? s(R.string.foundation_orphan_no_text) : value.text, 16, INK, false);
        content.setTag("bwork-orphan-recovery-text"); content.setTextIsSelectable(true); pad(content, 14, 14); content.setBackground(bg(Color.WHITE, 12, this)); body.addView(content, p(-1, -2)); spacer(body, 10);
        if (value.replyId != null) { body.addView(text(this, s(R.string.foundation_orphan_quote_unavailable), 12, MUTED, false)); spacer(body, 8); }
        TextView copy = action(s(R.string.foundation_orphan_copy), () -> {
            try { ((android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText(s(R.string.foundation_orphan_title), value.text)); toast(s(R.string.ui_182)); }
            catch (RuntimeException unavailable) { toast(s(R.string.ui_183)); }
        }); copy.setEnabled(!value.text.isEmpty()); body.addView(copy, p(-1, -2)); spacer(body, 8);
        body.addView(action(s(R.string.foundation_orphan_export), () -> saveRecoveredText(record)), p(-1, -2)); spacer(body, 16);
        for (ChatStore.Attachment file : value.files) {
            body.addView(attachmentCard(file, true)); spacer(body, 6);
            body.addView(action(s(R.string.foundation_orphan_save_file, displayName(file.name)), () -> saveAttachment(file)), p(-1, -2)); spacer(body, 14);
        }
        body.addView(action(s(R.string.foundation_orphan_remove), () -> confirmRecoveredEditorRemoval(record)), p(-1, -2));
    }
    private void saveRecoveredText(OrphanEditor record) {
        if (!"recovery".equals(screen) || !record.id.equals(recoveredEditorKey)) return;
        final File directory = new File(getFilesDir(), "attachments"); final String title = s(R.string.foundation_orphan_title), name = s(R.string.foundation_orphan_export_name), notice = s(R.string.foundation_orphan_notice);
        if (transcriptFuture != null) transcriptFuture.cancel(true);
        transcriptFuture = queryOperation(() -> {
            if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Cannot create recovery export directory");
            String id = UUID.randomUUID().toString(); File file = new File(directory, id + ".txt"); boolean complete = false;
            try {
                try (FileOutputStream output = new FileOutputStream(file); Writer writer = utf8Writer(output)) {
                    writer.append(title).append('\n').append(notice).append("\n\n").append(record.snapshot.text).append('\n');
                    for (ChatStore.Attachment attachment : record.snapshot.files) writer.append(s(R.string.attachment_label, attachment.name)).append('\n');
                    writer.flush(); output.getFD().sync();
                }
                complete = true; return new ChatStore.Attachment(id, file.getAbsolutePath(), name, "text/plain", file.length());
            } finally { if (!complete) file.delete(); }
        }, file -> { if ("recovery".equals(screen) && record.id.equals(recoveredEditorKey)) saveAttachment(file); });
    }
    private void confirmRecoveredEditorRemoval(OrphanEditor record) {
        new AlertDialog.Builder(this).setTitle(s(R.string.foundation_orphan_remove)).setMessage(s(R.string.foundation_orphan_remove_confirm))
                .setNegativeButton(s(R.string.ui_109), null).setPositiveButton(s(R.string.foundation_orphan_remove), (dialog, which) -> {
                    final int epoch = navigationEpoch;
                    storeOperation(() -> {
                        if (recoveryReceipts == null) throw new IOException("Recovery preference storage is unavailable");
                        if (recoveryReceipts.edit().putBoolean(record.id, true).commit()) return true;
                        recoveryReceipts.edit().remove(record.id).commit(); throw new IOException("Could not save recovery dismissal");
                    }, success -> {
                        synchronized (processEditors) { processOrphanEditors.remove(record.id); }
                        if (epoch != navigationEpoch) { updateEditorStatus(); return; }
                        if (hasOrphanEditors()) showRecoveredEditor(null); else showList();
                    });
                }).show();
    }

    private boolean activityAlive() { return !destroyed && !isDestroyed() && !isFinishing(); }
    private static String editorKey(String co, String cv) { return "draft:" + co + ":" + cv; }
    private static String previewKey(String share) { return "share:" + share; }
    private void openStore(Bundle saved) {
        initializing = true; startupState = saved;
        base("loading", LIGHT); root.setGravity(Gravity.CENTER);
        root.addView(new ProgressBar(this), p(d(48), d(48)));
        TextView loading = text(this, s(R.string.foundation_loading), 14, MUTED, false); pad(loading, 20, 16); root.addView(loading);
        final File stateFile = new File(getFilesDir(), "chat-state-v1.bin");
        STORE_IO.execute(() -> {
            Exception failure = null; ChatStore.RecoveryInfo recovery = null;
            try {
                if (processStore == null) processStore = new ChatStore(stateFile);
                else if (processStore.requiresReopen()) processStore = processStore.reopen();
                synchronized (processEditors) {
                    if (editorStore != processStore) {
                        processEditors.clear(); processOrphanEditors.clear(); editorStore = processStore;
                        editorProcessEpoch = UUID.randomUUID().toString();
                    }
                }
                restoreEditors(saved, processStore);
            } catch (IOException | RuntimeException problem) {
                failure = problem; try { recovery = ChatStore.inspectRecovery(stateFile); } catch (Exception ignored) { }
            }
            final Exception error = failure; final ChatStore.RecoveryInfo available = recovery;
            handler.post(() -> {
                if (!activityAlive()) return;
                if (error != null) { showStoreFailure(stateFile, saved, available); return; }
                store = processStore; initializing = false; restoreScreen(saved); startupState = null;
                dispatchStartupDestination(saved == null);
            });
        });
    }
    private void dispatchStartupDestination(boolean freshLaunch) {
        Intent destination = pendingStartupIntent != null ? pendingStartupIntent : deferredEntryIntent;
        pendingStartupIntent = null;
        if (destination == null && freshLaunch) destination = getIntent();
        if (isEntryDestination(destination)) {
            if (!settings.demoSessionActive()) { deferredEntryIntent = new Intent(destination); return; }
            deferredEntryIntent = null;
            if (isShare(destination)) handleIncomingShare(destination); else handleLocalNotification(destination);
        } else if (freshLaunch && settings.demoSessionActive() && store.pendingShare() != null) showPicker(true);
    }
    private void showStoreFailure(File file, Bundle saved, ChatStore.RecoveryInfo recovery) {
        String message = s(R.string.foundation_store_unavailable);
        if (recovery != null && recovery.available) message += "\n\n" + s(R.string.foundation_recovery_available,
                java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.MEDIUM, java.text.DateFormat.SHORT, AppLocale.locale(this)).format(new Date(recovery.savedAt)), recovery.messageCount);
        AlertDialog.Builder dialog = new AlertDialog.Builder(this).setTitle(s(R.string.ui_049)).setMessage(message)
                .setNegativeButton(s(R.string.ui_051), (closed, which) -> finish())
                .setPositiveButton(s(R.string.foundation_retry), (closed, which) -> openStore(saved)).setCancelable(false);
        if (recovery != null && recovery.available) dialog.setNeutralButton(s(R.string.foundation_recovery_restore), (closed, which) ->
                new AlertDialog.Builder(this).setTitle(s(R.string.foundation_recovery_title)).setMessage(s(R.string.foundation_recovery_confirm))
                        .setNegativeButton(s(R.string.ui_109), (cancel, button) -> showStoreFailure(file, saved, recovery))
                        .setPositiveButton(s(R.string.foundation_recovery_restore), (confirm, button) ->
                                storeOperation(() -> ChatStore.restoreLastGood(file, recovery), restored -> {
                                    processStore = restored; toast(s(R.string.foundation_recovery_complete)); openStore(saved);
                                }, failure -> { error(failure); showStoreFailure(file, saved, recovery); }))
                        .setCancelable(false).show());
        dialog.show();
    }
    private EditorState obtainDraftEditor(String co, String cv) {
        synchronized (processEditors) {
            String key = editorKey(co, cv); EditorState value = processEditors.get(key);
            if (value == null || value.retired()) {
                ChatStore.Draft draft = store.draft(co, cv);
                value = new EditorState(co, cv, null, draft.text, draft.attachments, draft.replyToMessageId);
                processEditors.put(key, value);
            }
            return value;
        }
    }
    private static void restoreEditors(Bundle saved, ChatStore savedStore) {
        if (saved == null) return;
        synchronized (processEditors) {
            if (editorProcessEpoch.equals(saved.getString("editorProcess"))) return;
            Object normal = saved.getSerializable("editorRecovery"), orphan = saved.getSerializable("orphanRecovery");
            ArrayList<?> drafts = normal instanceof ArrayList ? (ArrayList<?>) normal : new ArrayList<>();
            ArrayList<?> orphans = orphan instanceof ArrayList ? (ArrayList<?>) orphan : new ArrayList<>();
            if (drafts.size() + orphans.size() > MAX_RECOVERY_EDITORS) throw new IllegalArgumentException("Editor recovery exceeds the supported bound");
            for (Object item : drafts) if (item instanceof EditorState.Snapshot) admitRecoveredEditor(savedStore, (EditorState.Snapshot) item, false);
            for (Object item : orphans) if (item instanceof OrphanEditor) admitRecoveredEditor(savedStore, ((OrphanEditor) item).snapshot, true);
        }
    }
    private void captureDraft() {
        if (reopeningHistory || !"chat".equals(screen) || composer == null || draftEditor == null) return;
        EditorState.Snapshot current = draftEditor.snapshot();
        if (current.revision != draftViewRevision) { reconcileEditorViews(); return; }
        if (!canEditCurrentDraft() || draftEditor.sending()) {
            if (!composer.getText().toString().equals(current.text)) composer.setText(current.text);
            return;
        }
        draftEditor.update(composer.getText().toString(), draftFiles, current.replyId); draftViewRevision = draftEditor.snapshot().revision;
    }
    private void capturePreview() {
        if (previewEditor == null || previewEditor.retired() || !canEditPreview()) return;
        if ("preview".equals(screen) && previewCaption != null) {
            if (previewEditor.snapshot().revision != previewViewRevision) { reconcileEditorViews(); return; }
            previewText = previewCaption.getText().toString();
        }
        if (previewText != null) previewEditor.update(previewText, previewFiles, null);
        previewViewRevision = previewEditor.snapshot().revision;
    }
    private void reconcileEditorViews() {
        if (destroyed) return;
        if ("chat".equals(screen) && draftEditor != null && composer != null) {
            EditorState.Snapshot current = draftEditor.snapshot();
            if (current.revision != draftViewRevision) {
                draftViewRevision = current.revision; draftFiles = new ArrayList<>(current.files);
                if (!composer.getText().toString().equals(current.text)) composer.setText(current.text);
                renderDraftFiles(); renderReplyTray();
            }
            composer.setEnabled(!draftEditor.sending() && canEditCurrentDraft());
            if (composerAttach != null) composerAttach.setEnabled(!draftEditor.sending() && canEditCurrentDraft());
        }
        if ("preview".equals(screen) && previewEditor != null && previewCaption != null && !previewEditor.retired()) {
            EditorState.Snapshot current = previewEditor.snapshot();
            if (current.revision != previewViewRevision) {
                previewViewRevision = current.revision; previewText = current.text; previewFiles = new ArrayList<>(current.files);
                if (!previewCaption.getText().toString().equals(current.text)) previewCaption.setText(current.text);
            }
            previewCaption.setEnabled(!previewEditor.sending() && canEditPreview());
        }
        updateEditorStatus();
    }
    private static void notifyActiveEditorChange() {
        MainActivity current = activeActivity.get();
        if (current != null && current.activityAlive()) { current.reconcileEditorViews(); current.pruneEditors(); }
    }
    private void captureEditors() { captureDraft(); capturePreview(); }
    private boolean dirtyEditors() {
        synchronized (processEditors) { for (EditorState state : processEditors.values()) if (state.dirty()) return true; }
        return false;
    }
    private int dirtyEditorCount() {
        int count = 0;
        synchronized (processEditors) {
            for (EditorState state : processEditors.values()) if (state.dirty() || state.sending()) count++;
            return count + processOrphanEditors.size();
        }
    }
    private boolean sendingEditor() {
        synchronized (processEditors) { for (EditorState state : processEditors.values()) if (state.sending()) return true; }
        return false;
    }
    private boolean canEditCurrentDraft() { return !reopeningHistory && draftEditor != null && (draftEditor.dirty() || draftEditor.sending() || dirtyEditorCount() < MAX_RECOVERY_EDITORS); }
    private boolean canEditPreview() { return !reopeningHistory && !previewMigrationBlocked && previewEditor != null && (previewEditor.dirty() || previewEditor.sending() || dirtyEditorCount() < MAX_RECOVERY_EDITORS); }
    private boolean beforeNavigation(Runnable afterSave) {
        if (initializing || store == null || !activityAlive()) return false;
        if (restoringScreen) return true;
        if (reopeningHistory) { toast(s(R.string.foundation_operation_wait)); return false; }
        if (store.requiresReopen()) { showUncertainHistory(); return false; }
        captureReadingState(); captureEditors();
        if (sending || sendingEditor()) { toast(s(R.string.foundation_operation_wait)); return false; }
        if (!dirtyEditors()) return true;
        pendingNavigation = afterSave;
        if (!navigationSaving) {
            navigationSaving = true;
            flushEditors(() -> {
                navigationSaving = false; Runnable next = pendingNavigation; pendingNavigation = null;
                if (next != null) next.run();
            }, true);
        }
        return false;
    }
    private void flushEditors(Runnable complete, boolean navigation) {
        if (store == null || initializing) return;
        captureEditors(); if (!navigation && editorSaveQueued) return;
        if (!navigation) editorSaveQueued = true;
        final ChatStore targetStore = store; final ArrayList<EditorState> values;
        synchronized (processEditors) { values = new ArrayList<>(processEditors.values()); }
        updateEditorStatus();
        STORE_IO.execute(() -> {
            Exception failure = null; EditorState failed = null;
            for (EditorState state : values) {
                EditorState.Snapshot snapshot = state.snapshot();
                if (state.sending() || !state.needsWrite(snapshot)) continue;
                try {
                    if (snapshot.shareId == null) targetStore.setDraft(snapshot.company, snapshot.conversation, snapshot.text, snapshot.files, snapshot.replyId);
                    else targetStore.updatePendingSharePreview(snapshot.shareId, snapshot.text, snapshot.files);
                    state.committed(snapshot);
                } catch (IOException | RuntimeException error) { state.failed(snapshot, error); failure = error; failed = state; break; }
            }
            final Exception error = failure; final EditorState failedState = failed;
            handler.post(() -> {
                notifyActiveEditorChange(); if (!activityAlive()) return;
                if (!navigation) editorSaveQueued = false; updateEditorStatus();
                if (error != null) {
                    if (navigation) { navigationSaving = false; pendingNavigation = null; revealFailedEditor(failedState); toast(s(R.string.foundation_save_failed)); }
                    return;
                }
                if (complete != null) complete.run(); else if (dirtyEditors()) scheduleDraftSave();
            });
        });
    }
    private void pruneEditors() {
        String currentKey = "chat".equals(screen) && conversationId != null ? editorKey(companyId, conversationId) : null;
        synchronized (processEditors) {
            Iterator<Map.Entry<String, EditorState>> iterator = processEditors.entrySet().iterator();
            while (iterator.hasNext()) {
                Map.Entry<String, EditorState> entry = iterator.next(); EditorState state = entry.getValue();
                if (entry.getKey().equals(currentKey) || state == previewEditor && !state.retired() || state.dirty() || state.sending()) continue;
                state.retire(); iterator.remove();
            }
        }
    }
    private boolean reopenUnsavedEditor() {
        EditorState.Snapshot snapshot = null;
        synchronized (processEditors) { for (EditorState state : processEditors.values()) if (state.dirty() || state.sending()) { snapshot = state.snapshot(); break; } }
        if (snapshot == null) return false;
        restoringScreen = true;
        try { if (snapshot.shareId == null) showChat(snapshot.company, snapshot.conversation); else showPicker(true); }
        finally { restoringScreen = false; }
        toast(s(R.string.foundation_recovered_editor)); return true;
    }
    private void revealFailedEditor(EditorState failed) {
        if (failed == null || failed == draftEditor && "chat".equals(screen) || failed == previewEditor && "preview".equals(screen)) return;
        EditorState.Snapshot value = failed.snapshot(); restoringScreen = true;
        try {
            if (value.shareId == null) showChat(value.company, value.conversation);
            else if (previewCompany != null && previewConversation != null) {
                previewShareId = value.shareId; previewEditor = failed; previewText = value.text; previewFiles = new ArrayList<>(value.files); showSharePreview();
            } else showPicker(true);
        } finally { restoringScreen = false; }
    }
    private void showUncertainHistory() {
        if (!activityAlive() || reopeningHistory || uncertainDialog != null && uncertainDialog.isShowing()) return;
        uncertainDialog = new AlertDialog.Builder(this).setTitle(s(R.string.ui_049)).setMessage(s(R.string.foundation_commit_uncertain))
                .setNegativeButton(s(R.string.ui_109), null).setPositiveButton(s(R.string.foundation_reopen_history), (dialog, which) -> reopenCurrentHistory()).create();
        uncertainDialog.setOnDismissListener(dialog -> uncertainDialog = null); uncertainDialog.show(); updateEditorStatus();
    }
    private void reopenCurrentHistory() {
        if (reopeningHistory || store == null) return;
        hideKeyboard(); Bundle recovery = new Bundle(); onSaveInstanceState(recovery);
        final ChatStore previous = store; reopeningHistory = true; cancelQueries();
        if (composer != null) composer.setEnabled(false); if (previewCaption != null) previewCaption.setEnabled(false); updateEditorStatus();
        STORE_IO.execute(() -> {
            ChatStore reopened = null; Exception failure = null;
            try {
                reopened = previous.reopen();
                synchronized (processEditors) {
                    Map<String, EditorState> previousEditors = new LinkedHashMap<>(processEditors);
                    Map<String, OrphanEditor> previousOrphans = new LinkedHashMap<>(processOrphanEditors);
                    ChatStore previousOwner = editorStore; String previousEpoch = editorProcessEpoch;
                    try {
                        processStore = reopened; editorStore = reopened; processEditors.clear(); processOrphanEditors.clear(); editorProcessEpoch = UUID.randomUUID().toString();
                        restoreEditors(recovery, reopened);
                    } catch (RuntimeException admissionFailure) {
                        processStore = previous; editorStore = previousOwner; editorProcessEpoch = previousEpoch;
                        processEditors.clear(); processEditors.putAll(previousEditors); processOrphanEditors.clear(); processOrphanEditors.putAll(previousOrphans);
                        throw admissionFailure;
                    }
                }
            } catch (IOException | RuntimeException problem) { failure = problem; }
            final ChatStore result = reopened; final Exception error = failure;
            handler.post(() -> {
                if (!activityAlive()) return; reopeningHistory = false;
                if (error != null) { reconcileEditorViews(); toast(s(R.string.foundation_reopen_failed)); return; }
                store = result; restoreScreen(recovery);
            });
        });
    }

    private void addEditorStatus() {
        editorStatus = text(this, "", 12, MUTED, false); editorStatus.setTag("bwork-editor-save-status");
        editorStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE); editorStatus.setMinHeight(d(44));
        pad(editorStatus, 14, 8); editorStatus.setBackgroundColor(LIGHT); clickable(editorStatus);
        editorStatus.setOnClickListener(view -> {
            if (store != null && store.requiresReopen()) { showUncertainHistory(); return; }
            if ("chat".equals(screen) && !canEditCurrentDraft() || "preview".equals(screen) && !canEditPreview()) { showRecoveredEditor(null); return; }
            captureEditors(); flushEditors(null, false);
        });
        root.addView(editorStatus, p(-1, -2)); updateEditorStatus();
    }
    private void updateEditorStatus() {
        if (editorStatus == null) return;
        if (reopeningHistory || store != null && store.requiresReopen()) {
            editorStatus.setVisibility(View.VISIBLE); editorStatus.setText(s(reopeningHistory ? R.string.foundation_reopening : R.string.foundation_commit_uncertain)); return;
        }
        if ("chat".equals(screen) && draftEditor != null && !canEditCurrentDraft()) { editorStatus.setVisibility(View.VISIBLE); editorStatus.setText(s(R.string.foundation_orphan_capacity)); return; }
        if ("preview".equals(screen) && previewEditor != null && !canEditPreview()) {
            editorStatus.setVisibility(View.VISIBLE); editorStatus.setText(s(previewMigrationBlocked ? R.string.foundation_preview_migration_capacity : R.string.foundation_preview_capacity)); return;
        }
        EditorState current = "preview".equals(screen) ? previewEditor : "chat".equals(screen) ? draftEditor : null;
        if (current == null || current.retired() || !current.dirty() && !current.sending()) { editorStatus.setVisibility(View.GONE); return; }
        editorStatus.setVisibility(View.VISIBLE);
        editorStatus.setText(s(current.failure() != null ? R.string.foundation_save_failed_retry : current.sending() ? R.string.foundation_sending_local : R.string.foundation_saving));
        editorStatus.setTextColor(current.failure() != null ? Color.rgb(155, 54, 33) : MUTED);
    }
    private interface StoreOperation<T> { T run() throws Exception; }
    private interface StoreResult<T> { void accept(T value); }
    private <T> void storeOperation(StoreOperation<T> work, StoreResult<T> complete) { storeOperation(work, complete, this::error); }
    private <T> void storeOperation(StoreOperation<T> work, StoreResult<T> complete, StoreResult<Exception> failed) {
        STORE_IO.execute(() -> {
            T value = null; Exception failure = null;
            try { value = work.run(); } catch (Exception problem) { failure = problem; }
            final T result = value; final Exception error = failure;
            handler.post(() -> { if (!activityAlive()) return; if (error != null) failed.accept(error); else complete.accept(result); });
        });
    }
    private <T> Future<?> queryOperation(StoreOperation<T> work, StoreResult<T> complete) { return queryOperation(work, complete, this::error); }
    private <T> Future<?> queryOperation(StoreOperation<T> work, StoreResult<T> complete, StoreResult<Exception> failed) {
        QUERY_IO.purge(); final java.util.concurrent.atomic.AtomicBoolean canceled = new java.util.concurrent.atomic.AtomicBoolean();
        FutureTask<Void> task = new FutureTask<Void>(() -> {
            T value = null; Exception failure = null;
            try { if (Thread.currentThread().isInterrupted()) return null; value = work.run(); } catch (Exception problem) { failure = problem; }
            if (Thread.currentThread().isInterrupted()) return null;
            final T result = value; final Exception error = failure;
            handler.post(() -> { if (canceled.get() || !activityAlive()) return; if (error != null) failed.accept(error); else complete.accept(result); });
            return null;
        }) { @Override public boolean cancel(boolean interrupt) { canceled.set(true); return super.cancel(interrupt); } };
        try { QUERY_IO.execute(task); }
        catch (RejectedExecutionException full) { task.cancel(false); if (activityAlive()) failed.accept(new IOException("Local query queue is busy; retry")); }
        return task;
    }
    private void cancelQueries() {
        for (Future<?> task : new Future<?>[]{chatSearchFuture, historyFuture, transcriptFuture, storageStatsFuture}) if (task != null) task.cancel(true);
        QUERY_IO.purge();
    }
    private void scheduleDraftSave() { if (saveTask != null) handler.removeCallbacks(saveTask); saveTask = this::persistDraft; handler.postDelayed(saveTask, 350); }
    private void persistDraft() { if (saveTask != null) handler.removeCallbacks(saveTask); captureDraft(); if (store != null && dirtyEditors()) flushEditors(null, false); }
    private void sendDraft() {
        if (!canEditCurrentDraft()) { toast(s(R.string.foundation_orphan_capacity)); return; }
        if (sending || composer == null || voiceRecorder != null || draftEditor == null || draftEditor.sending()) return;
        captureDraft(); EditorState.Snapshot current = draftEditor.snapshot();
        if (current.text.trim().isEmpty() && current.files.isEmpty()) return;
        stopAudio(); sending = true; final EditorState editor = draftEditor; final ChatStore targetStore = store;
        final EditorState.Snapshot value = editor.beginSend(UUID.randomUUID().toString(), current.company, current.conversation);
        composer.setEnabled(false); if (composerAttach != null) composerAttach.setEnabled(false); updateEditorStatus();
        STORE_IO.execute(() -> {
            Exception failure = null;
            try { targetStore.sendDraftSnapshot(value.company, value.conversation, value.text, value.files, value.replyId, value.sendToken); editor.sent(value); }
            catch (IOException | RuntimeException problem) { if (targetStore.requiresReopen()) editor.commitUncertain(value, problem); else editor.sendFailed(value, problem); failure = problem; }
            final Exception error = failure;
            handler.post(() -> { MainActivity active = activeActivity.get(); if (active != null && active.activityAlive()) active.completeDraftSend(editor, error); });
        });
    }
    private void completeDraftSend(EditorState editor, Exception error) {
        sending = false; reconcileEditorViews();
        if (!"chat".equals(screen) || draftEditor != editor || composer == null) return;
        if (error != null) { error(error); return; }
        chatMatches.clear(); chatMatchIndex = -1; chatSearchQuery = "";
        if (chatSearchBar != null) { chatSearchBar.setVisibility(View.GONE); chatSearchInput.setText(""); }
        pendingReadingRestore = null; historyBefore = null; historyAfter = null; renderHistory(false);
    }


    private boolean hasAudioDraft() {
        for (ChatStore.Attachment file : draftFiles) if (file.mime.startsWith("audio/")) return true;
        return false;
    }

    private void showDraftAttachments() {
        ArrayList<ChatStore.Attachment> files = new ArrayList<>(draftFiles); String[] names = new String[files.size()];
        for (int i = 0; i < names.length; i++) names[i] = files.get(i).name;
        new AlertDialog.Builder(this).setTitle(s(R.string.ui_241)).setItems(names, (dialog, which) -> inspectAttachment(files.get(which)))
                .setNegativeButton(s(R.string.ui_051), null).show();
    }

    private void renderDraftFiles() {
        if (attachmentTray == null) return;
        attachmentTray.removeAllViews();
        if (draftFiles.isEmpty()) { updateComposerAction(); return; }
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(false);
        LinearLayout items = column(this); pad(items, 10, 4);
        ArrayList<ChatStore.Attachment> visible = new ArrayList<>(draftFiles);
        if (compactDrafts && hasAudioDraft()) {
            ChatStore.Attachment last = null;
            for (ChatStore.Attachment file : visible) if (file.mime.startsWith("audio/")) last = file;
            visible.clear(); visible.add(last);
        }
        if (draftFiles.size() > visible.size()) {
            TextView all = text(this, s(R.string.draft_attachments_count, draftFiles.size()), 11, GREEN, true);
            pad(all, 8, 4); all.setOnClickListener(v -> showDraftAttachments()); items.addView(all);
        }
        for (ChatStore.Attachment file : visible) {
            LinearLayout item = row(this); item.setBackground(bg(LIGHT, 14, this));
            if (file.mime.startsWith("audio/")) {
                item.addView(new VoicePlayerView(this, file, audioPlayback, audioWaveforms, () -> inspectAttachment(file), compactDrafts), new LinearLayout.LayoutParams(0, -2, 1));
            } else {
                LinearLayout info = row(this); pad(info, 10, 8);
                if (file.mime.startsWith("image/")) {
                    ImagePreviewView thumbnail = new ImagePreviewView(this, file, imagePreviews, 150, true);
                    info.addView(thumbnail, p(d(48), d(48)));
                } else info.addView(icon(file.mime.equals("application/pdf") ? "pdf" : "attach", GREEN, 25));
                TextView name = text(this, "  " + file.name + "\n  " + attachmentKind(file) + " · " + formatSize(file.size), 12, INK, false);
                name.setMaxLines(2); name.setEllipsize(TextUtils.TruncateAt.MIDDLE); info.addView(name, new LinearLayout.LayoutParams(0, -2, 1));
                info.setContentDescription(s(R.string.preview_file, displayName(file.name))); info.setOnClickListener(v -> inspectAttachment(file));
                item.addView(info, new LinearLayout.LayoutParams(0, -2, 1));
            }
            View remove = buttonIcon("close", s(R.string.remove_draft_file, displayName(file.name)), MUTED, () -> {
                if (!canEditCurrentDraft() || draftEditor.sending()) { toast(s(R.string.foundation_orphan_capacity)); return; }
                stopAudio(); draftFiles.remove(file); persistDraft(); renderDraftFiles();
            });
            remove.setTag("bwork-draft-remove-" + file.id);
            remove.setEnabled(canEditCurrentDraft() && !draftEditor.sending());
            item.addView(remove);
            LinearLayout.LayoutParams spacing = p(-1, -2); spacing.bottomMargin = d(4); items.addView(item, spacing);
        }
        scroll.addView(items); int height = compactDrafts ? 120 : draftFiles.size() > 1 ? 228 : hasAudioDraft() ? 138 : 80;
        attachmentTray.addView(scroll, p(-1, d(height))); updateComposerAction();
    }

    private void attachmentMenu() {
        if (!canEditCurrentDraft()) { toast(s(R.string.foundation_orphan_capacity)); return; }
        persistDraft();
        new AlertDialog.Builder(this).setTitle(s(R.string.ui_246))
                .setItems(new String[]{s(R.string.ui_247), s(R.string.ui_248), s(R.string.ui_249), s(R.string.ui_250), s(R.string.ui_251), s(R.string.ui_252)}, (dialog, which) -> {
                    if (which == 0) pickFile("image/*", PHOTO);
                    else if (which == 1) pickFile("application/pdf", PDF);
                    else if (which == 2) pickFile("audio/*", AUDIO_FILE);
                    else if (which == 3) pickFile("*/*", ANY_FILE);
                    else if (which == 4) capturePhoto();
                    else requestVoiceRecording();
                }).setNegativeButton(s(R.string.ui_109), null).show();
    }

    private void pickFile(String mime, int request) {
        if (!beforeNavigation(() -> pickFile(mime, request))) return;
        persistDraft();
        if (pickCompany != null) { toast(s(R.string.ui_253)); return; }
        pickCompany = companyId; pickConversation = conversationId;
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType(mime)
                .addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try { startActivityForResult(intent, request); }
        catch (ActivityNotFoundException missing) { pickCompany = null; pickConversation = null; toast(s(R.string.ui_254)); }
    }

    private void capturePhoto() {
        if (!beforeNavigation(this::capturePhoto)) return;
        persistDraft();
        File dir = new File(getFilesDir(), "attachments");
        dir.mkdirs();
        File file = new File(dir, UUID.randomUUID() + ".jpg");
        cameraPath = file.getAbsolutePath();
        cameraCompany = companyId;
        cameraConversation = conversationId;
        Uri out = Uri.parse("content://" + getPackageName() + ".files/" + file.getName());
        Intent i = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
        i.putExtra(MediaStore.EXTRA_OUTPUT, out);
        i.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
        i.setClipData(ClipData.newRawUri(s(R.string.ui_255), out));
        try {
            startActivityForResult(i, CAMERA);
        } catch (ActivityNotFoundException e) {
            cameraPath = null;
            toast(s(R.string.ui_256));
        }
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == SAVE_FILE) {
            ChatStore.Attachment file = exportAttachment;
            if (result == RESULT_OK && data != null && data.getData() != null && file != null) {
                Uri destination = data.getData();
                exportCopyInProgress = true;
                io.execute(() -> {
                    String failure = null;
                    try { AttachmentSupport.saveToUri(getApplicationContext(), file, destination); }
                    catch (IOException | RuntimeException error) { failure = AppLocale.error(this, error.getMessage()); }
                    final String problem = failure;
                    runOnUiThread(() -> {
                        exportAttachment = null; exportCopyInProgress = false;
                        if (!destroyed) cleanupAttachments();
                        if (!destroyed && !isFinishing()) toast(problem == null ? s(R.string.ui_258) : s(R.string.file_save_failed, problem));
                    });
                });
            } else { exportAttachment = null; exportCopyInProgress = false; cleanupAttachments(); }
            return;
        }
        boolean documentResult = request == PHOTO || request == PDF || request == AUDIO_FILE || request == ANY_FILE;
        final String selectedCompany = documentResult ? pickCompany : null;
        final String selectedConversation = documentResult ? pickConversation : null;
        if (documentResult) { pickCompany = null; pickConversation = null; }
        if (documentResult && result == RESULT_OK && data == null) { toast(s(R.string.ui_260)); return; }
        if (result != RESULT_OK) {
            if (request == PHOTO || request == PDF || request == AUDIO_FILE || request == ANY_FILE) { pickCompany = null; pickConversation = null; }
            if (request == CAMERA && cameraPath != null) {
                new File(cameraPath).delete();
                cameraPath = null;
            }
            return;
        }
        if (request == CAMERA) {
            if (cameraPath == null) return;
            File f = new File(cameraPath);
            String co = cameraCompany;
            String cv = cameraConversation;
            cameraPath = null;
            if (!f.isFile() || f.length() == 0) {
                toast(s(R.string.ui_261));
                return;
            }
            if (f.length() > MAX_FILE) {
                f.delete();
                toast(s(R.string.ui_262));
                return;
            }
            ChatStore.Attachment photo = new ChatStore.Attachment(UUID.randomUUID().toString(), f.getAbsolutePath(), s(R.string.ui_264), "image/jpeg", f.length());
            try { AttachmentSupport.requirePrivateFile(this, photo); }
            catch (IOException unavailable) { toast(s(R.string.ui_263)); return; }
            // Persist the original immediately. Codec/header checks belong to the asynchronous
            // preview, so Activity recreation after the camera result cannot lose an awaiting photo.
            addFilesToDraft(co, cv, Collections.singletonList(photo));
            return;
        }
        if ((request == PHOTO || request == PDF || request == AUDIO_FILE || request == ANY_FILE) && data != null) {
            ArrayList<Uri> uris = new ArrayList<>();
            if (data.getClipData() != null) for (int i = 0; i < data.getClipData().getItemCount(); i++) uris.add(data.getClipData().getItemAt(i).getUri()); else if (data.getData() != null) uris.add(data.getData());
            String co = selectedCompany;
            String cv = selectedConversation;
            pickCompany = null;
            pickConversation = null;
            if (co == null || cv == null) {
                toast(s(R.string.ui_265));
                return;
            }
            if (uris.isEmpty()) { toast(s(R.string.ui_266)); return; }
            importUris(uris, null, (files)->addFilesToDraft(co, cv, files));
        }
    }

    private boolean addFilesToDraft(String co, String cv, List<ChatStore.Attachment> files) {
        try {
            if ("chat".equals(screen) && co.equals(companyId) && cv.equals(conversationId)) captureDraft();
            EditorState editor = obtainDraftEditor(co, cv);
            if (!editor.dirty() && dirtyEditorCount() >= MAX_RECOVERY_EDITORS - 1) { toast(s(R.string.foundation_finish_pending_edits)); return false; }
            if (editor.sending()) { toast(s(R.string.foundation_operation_wait)); return false; }
            EditorState.Snapshot draft = editor.snapshot(); ArrayList<ChatStore.Attachment> combined = new ArrayList<>(draft.files); combined.addAll(files);
            long size = 0; for (ChatStore.Attachment file : combined) size += file.size;
            if (combined.size() > 10 || size > MAX_TOTAL) { toast(s(R.string.ui_267)); return false; }
            editor.update(draft.text, combined, draft.replyId);
            if ("chat".equals(screen) && co.equals(companyId) && cv.equals(conversationId)) { draftEditor = editor; draftFiles = combined; renderDraftFiles(); }
            flushEditors(null, false); return true;
        } catch (IllegalArgumentException failure) { error(failure); return false; }
    }
    private boolean pickerSharing;
    private ListView recipientList;
    private String previewText;

    private void showPicker(boolean sharing) { showPicker(sharing, false); }

    private void showPicker(boolean sharing, boolean restoreSelection) {
        if (!beforeNavigation(() -> showPicker(sharing, restoreSelection))) return;
        persistDraft();
        hideKeyboard();
        pickerSharing = sharing;
        if (!restoreSelection) { pickerQuery = ""; pickerCompany = "all"; }
        if (sharing && store.pendingShare() == null) {
            showList();
            return;
        }
        base("picker", LIGHT);
        LinearLayout top = row(this);
        pad(top, 8, 10);
        top.addView(buttonIcon("back", s(R.string.ui_096), INK, ()->leavePicker()));
        LinearLayout heading = column(this);
        heading.addView(text(this, sharing ? s(R.string.ui_269) : s(R.string.ui_270), 23, INK, true));
        heading.addView(text(this, sharing ? s(R.string.ui_271) : s(R.string.ui_272), 11, MUTED, false));
        top.addView(heading, new LinearLayout.LayoutParams(0, -2, 1));
        root.addView(top, p(-1, d(80)));
        if (sharing) {
            ChatStore.PendingShare share = store.pendingShare();
            LinearLayout summary = row(this);
            pad(summary, 16, 12);
            summary.setBackground(bg(LIGHT, 15, this));
            summary.addView(icon(share.attachments.isEmpty() ? "chat" : "attach", GREEN, 23));
            TextView t = text(this, s(R.string.pending_share_count, share.attachments.size()), 11, GREEN, false);
            summary.addView(t);
            LinearLayout.LayoutParams l = p(-1, -2);
            l.setMargins(d(20), 0, d(20), d(14));
            root.addView(summary, l);
        }
        LinearLayout search = row(this);
        pad(search, 13, 0);
        search.setBackground(bg(LINE, 16, this));
        search.addView(icon("search", MUTED, 21));
        EditText q = new EditText(this);
        q.setSingleLine();
        q.setTextSize(14);
        q.setTextColor(INK);
        q.setHintTextColor(MUTED);
        q.setHint(s(R.string.ui_275)); q.setTag("bwork-recipient-search"); q.setText(pickerQuery);
        q.setBackgroundColor(Color.TRANSPARENT);
        pad(q, 10, 0);
        search.addView(q, new LinearLayout.LayoutParams(0, d(49), 1));
        LinearLayout.LayoutParams sp = p(-1, d(49));
        sp.setMargins(d(20), 0, d(20), 0);
        root.addView(search, sp);
        HorizontalScrollView filters = new HorizontalScrollView(this);
        filters.setHorizontalScrollBarEnabled(false);
        LinearLayout fr = row(this);
        pad(fr, 20, 11);
        String[][] kinds = {{s(R.string.ui_151), "all"}, {s(R.string.ui_276), "person"}, {s(R.string.ui_277), "group"}, {s(R.string.ui_278), "chat"}};
        for (String[] k : kinds) {
            TextView chip = pill(this, k[0], pickerKind.equals(k[1]));
            LinearLayout.LayoutParams cp = p(-2, d(36));
            cp.setMarginStart(d(7));
            fr.addView(chip, cp);
            chip.setOnClickListener((v)->{
                pickerKind = k[1];
                showPicker(sharing, true);
            });
        }
        filters.addView(fr);
        root.addView(filters, p(-1, d(59)));
        TextView allCompanies = text(this, s(R.string.ui_279), 11, MUTED, false);
        pad(allCompanies, 22, 9);
        root.addView(allCompanies, p(-1, d(40)));
        if (!sharing) {
            TextView create = text(this, s(R.string.ui_280), 13, GREEN, true);
            pad(create, 22, 11);
            create.setOnClickListener(v -> showCreateGroup(true));
            root.addView(create, p(-1, d(43)));
        }
        recipientList = new ListView(this);
        recipientList.setDivider(null);
        recipientList.setVerticalScrollBarEnabled(false);
        recipientList.setBackgroundColor(Color.WHITE);
        root.addView(recipientList, new LinearLayout.LayoutParams(-1, 0, 1));
        q.addTextChangedListener(watcher((s)->{
            pickerQuery = s;
            updateRecipients();
        }));
        updateRecipients();
        demoBar(root, true);
    }

    private String companyName(String id) {
        for (ChatStore.Company c : store.companies()) if (c.id.equals(id)) return c.name;
        return s(R.string.ui_281);
    }

    private void updateRecipients() {
        ArrayList<Object> rows = new ArrayList<>();
        String lastCompany = "";
        for (ChatStore.Recipient r : store.searchRecipients(pickerQuery)) {
            if (!"all".equals(pickerCompany) && !pickerCompany.equals(r.company.id)) continue;
            if (!"all".equals(pickerKind) && !pickerKind.equals(r.conversation.kind)) continue;
            if (!lastCompany.equals(r.company.id)) {
                rows.add(r.company.name);
                lastCompany = r.company.id;
            }
            rows.add(r);
        }
        if (rows.isEmpty()) rows.add(s(R.string.ui_282));
        recipientList.setAdapter(new BaseAdapter(){

            public int getCount() {
                return rows.size();
            }

            public Object getItem(int i) {
                return rows.get(i);
            }

            public long getItemId(int i) {
                return i;
            }

            public boolean isEnabled(int i) {
                return rows.get(i) instanceof ChatStore.Recipient;
            }

            public View getView(int i, View old, android.view.ViewGroup parent) {
                Object o = rows.get(i);
                if (o instanceof String) {
                    TextView label = text(MainActivity.this, (String)o, 11, GREEN, true);
                    pad(label, 22, 11);
                    label.setBackgroundColor(LIGHT);
                    return label;
                }
                ChatStore.Recipient r = (ChatStore.Recipient)o;
                return conversationRow(r.conversation, true);
            }
        });
        recipientList.setOnItemClickListener((a,v,i,id)->{
            if (!(rows.get(i) instanceof ChatStore.Recipient)) return;
            ChatStore.Recipient r = (ChatStore.Recipient)rows.get(i);
            if (pickerSharing) {
                previewCompany = r.company.id;
                previewConversation = r.conversation.id;
                ChatStore.PendingShare s = store.pendingShare();
                if (s == null) {
                    showList();
                    return;
                }
                if (previewText == null || !s.id.equals(previewShareId)) loadPreview(s);
                showSharePreview();
            } else {
                pickerKind = "all";
                showChat(r.company.id, r.conversation.id);
            }
        });
    }

    private void leavePicker() {
        if (!beforeNavigation(this::leavePicker)) return;
        persistPreview();
        hideKeyboard();
        if (!pickerSharing) {
            pickerKind = "all";
            showList();
            return;
        }
        final String cancelShareId = store.pendingShare() == null ? null : store.pendingShare().id;
        new AlertDialog.Builder(this).setTitle(s(R.string.ui_283)).setMessage(s(R.string.ui_284)).setPositiveButton(s(R.string.ui_056), (di,w)->showList()).setNeutralButton(s(R.string.ui_285), (di,w)->{
            final ChatStore targetStore=store;storeOperation(()->{if(cancelShareId!=null)targetStore.cancelPendingShare(cancelShareId);return true;},done->{clearPreview();showList();});
        }).setNegativeButton(s(R.string.ui_286), null).show();
    }

    private void showSharePreview() {
        capturePreview();
        hideKeyboard();
        ChatStore.PendingShare pending = store.pendingShare();
        if (pending == null) {
            showList();
            return;
        }
        if (!pending.id.equals(previewShareId) || previewCompany == null || previewConversation == null) {
            showPicker(true); return;
        }
        final ChatStore.Conversation c;
        try { c = store.conversation(previewCompany, previewConversation); }
        catch (IllegalArgumentException staleDestination) { showPicker(true); return; }
        // A recreated Activity has only IDs until its edited caption and selected files are reloaded.
        if (previewText == null || previewEditor == null || previewMigrationBlocked) loadPreview(pending);
        base("preview", LIGHT);
        LinearLayout header = row(this);
        pad(header, 8, 10);
        header.addView(buttonIcon("back", s(R.string.ui_287), INK, ()->showPicker(true)));
        header.addView(text(this, s(R.string.ui_288), 22, INK, true));
        root.addView(header, p(-1, d(72)));
        addEditorStatus();
        ScrollView scroll = new ScrollView(this);
        LinearLayout body = column(this);
        pad(body, 20, 4);
        scroll.addView(body);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout recipient = row(this);
        pad(recipient, 15, 16);
        recipient.setBackground(outline(Color.WHITE, LINE, 19, this));
        recipient.addView(new Ui.Avatar(this, c.title, c.kind, c.avatarHue), p(d(51), d(51)));
        LinearLayout dest = column(this);
        LinearLayout.LayoutParams dp = new LinearLayout.LayoutParams(0, -2, 1);
        dp.setMargins(d(12), 0, d(12), 0);
        recipient.addView(dest, dp);
        dest.addView(text(this, s(R.string.ui_289), 10, MUTED, false));
        dest.addView(text(this, c.title, 17, INK, true));
        dest.addView(text(this, companyName(previewCompany), 11, GREEN, true));
        TextView change = text(this, s(R.string.ui_290), 12, GREEN, true);
        recipient.addView(change);
        recipient.setOnClickListener((v)->showPicker(true));
        body.addView(recipient, p(-1, -2));
        spacer(body, 18);
        TextView note = text(this, s(R.string.ui_291), 11, MUTED, false);
        body.addView(note);
        spacer(body, 14);
        for (ChatStore.Attachment a : new ArrayList<>(previewFiles)) {
            LinearLayout wrap = column(this);
            wrap.setBackground(bg(Color.WHITE, 18, this));
            pad(wrap, 10, 10);
            wrap.addView(attachmentCard(a, true));
            TextView remove = text(this, s(R.string.ui_292), 11, MUTED, false);
            pad(remove, 6, 8);
            remove.setOnClickListener((v)->{
                if (!canEditPreview() || previewEditor.sending()) return;
                previewFiles.remove(a);
                persistPreview();
                showSharePreview();
            });
            remove.setTag("bwork-preview-remove-" + a.id); remove.setEnabled(canEditPreview() && !previewEditor.sending()); remove.setAlpha(remove.isEnabled() ? 1f : .45f);
            wrap.addView(remove);
            body.addView(wrap, p(-1, -2));
            spacer(body, 10);
        }
        TextView captionLabel = text(this, previewFiles.isEmpty() ? s(R.string.ui_293) : s(R.string.ui_294), 12, GREEN, true);
        body.addView(captionLabel);
        spacer(body, 8);
        previewCaption = new EditText(this);
        previewViewRevision = previewEditor.snapshot().revision;
        previewCaption.setText(previewText == null ? pending.text : previewText);
        previewCaption.setEnabled(!previewEditor.sending() && canEditPreview());
        previewCaption.setHint(s(R.string.ui_295));
        previewCaption.setTextColor(INK);
        previewCaption.setHintTextColor(MUTED);
        previewCaption.setTextSize(15);
        previewCaption.setMinLines(3);
        previewCaption.setFilters(new InputFilter[]{new InputFilter.LengthFilter(ChatStore.MAX_TEXT_LENGTH)});
        previewCaption.setGravity(Gravity.START | Gravity.TOP);
        previewCaption.setBackground(bg(Color.WHITE, 16, this));
        pad(previewCaption, 15, 14);
        body.addView(previewCaption, p(-1, -2));
        previewCaption.addTextChangedListener(watcher(value -> {
            if (!canEditPreview() || previewEditor.sending()) { if (!Objects.equals(value, previewText)) previewCaption.setText(previewText); return; }
            previewText = value; schedulePreviewSave();
        }));
        spacer(body, 20);
        LinearLayout footer = column(this);
        pad(footer, 20, 12);
        footer.setBackgroundColor(Color.WHITE);
        TextView send = action(s(R.string.send_to_name, displayName(c.title)), ()->sendShare());
        send.setTag("bwork-share-send"); send.setEnabled(canEditPreview() && !previewEditor.sending()); send.setAlpha(send.isEnabled() ? 1f : .45f);
        footer.addView(send, p(-1, d(53)));
        TextView local = text(this, s(R.string.ui_297), 10, MUTED, false);
        local.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams l = p(-1, d(25));
        footer.addView(local, l);
        root.addView(footer, p(-1, -2));
    }

    private void cleanupAttachments() {
        // Automatic orphan deletion is intentionally disabled. Android's private-root aliases can
        // make stored canonical paths differ from enumerated absolute paths; the former sweep
        // could delete live originals. Even normalized paths cannot prove stale references safe.
        // Retain unused bytes until a separately reviewed storage-cleanup action exists. Explicit
        // import/recording/camera failure or cancellation still cleans only its own in-progress file.
    }

    private void clearPreview() {
        if (previewEditor != null) previewEditor.retire();
        previewEditor = null; previewMigrationBlocked = false; previewShareId = null; previewText = null; previewCaption = null; previewFiles.clear(); cleanupAttachments();
    }
    private void loadPreview(ChatStore.PendingShare pending) {
        previewShareId = pending.id; previewMigrationBlocked = false;
        synchronized (processEditors) {
            previewEditor = processEditors.get(previewKey(pending.id));
            if (previewEditor == null || previewEditor.retired()) {
                previewEditor = new EditorState(null, null, pending.id, pending.text, pending.attachments, null); processEditors.put(previewKey(pending.id), previewEditor);
            }
        }
        if (!pending.previewEdited && !previewEditor.dirty() && !previewEditor.sending()) {
            android.content.SharedPreferences prefs = getSharedPreferences("share-preview", MODE_PRIVATE);
            if (pending.id.equals(prefs.getString("id", null))) {
                String legacyText = prefs.getString("text", pending.text); Set<String> ids = prefs.getStringSet("attachments", Collections.emptySet());
                ArrayList<ChatStore.Attachment> kept = new ArrayList<>(); for (ChatStore.Attachment file : pending.attachments) if (ids.contains(file.id)) kept.add(file);
                if (dirtyEditorCount() >= MAX_RECOVERY_EDITORS) {
                    previewMigrationBlocked = true; previewText = legacyText; previewFiles = kept; previewViewRevision = previewEditor.snapshot().revision; return;
                }
                previewEditor.update(legacyText, kept, null); previewEditor.requireSave();
            }
        }
        EditorState.Snapshot value = previewEditor.snapshot(); previewText = value.text; previewFiles = new ArrayList<>(value.files); previewViewRevision = value.revision;
        if (previewEditor.dirty()) persistPreview();
    }
    private void persistPreview() { if (previewSaveTask != null) handler.removeCallbacks(previewSaveTask); capturePreview(); if (store != null && dirtyEditors()) flushEditors(null, false); }
    private void schedulePreviewSave() { capturePreview(); updateEditorStatus(); if (previewSaveTask != null) handler.removeCallbacks(previewSaveTask); previewSaveTask = this::persistPreview; handler.postDelayed(previewSaveTask, 350); }
    private void sendShare() {
        if (!canEditPreview()) { toast(s(R.string.foundation_preview_capacity)); return; }
        if (sending || previewEditor == null || previewEditor.sending()) return;
        capturePreview(); ChatStore.PendingShare pending = store.pendingShare();
        if (pending == null || !pending.id.equals(previewShareId)) { toast(s(R.string.ui_298)); clearPreview(); if (pending == null) showList(); else showPicker(true); return; }
        final EditorState editor = previewEditor; EditorState.Snapshot current = editor.snapshot();
        if (current.text.trim().isEmpty() && current.files.isEmpty()) { toast(s(R.string.ui_299)); return; }
        sending = true; stopAudio(); final String co = previewCompany, cv = previewConversation;
        final EditorState.Snapshot value = editor.beginSend(UUID.randomUUID().toString(), co, cv); final ChatStore targetStore = store;
        if (previewCaption != null) previewCaption.setEnabled(false); updateEditorStatus();
        STORE_IO.execute(() -> {
            Exception failure = null;
            try { targetStore.sendPendingShare(value.shareId, co, cv, value.text, value.files, value.sendToken); editor.sent(value); }
            catch (IOException | RuntimeException problem) { if (targetStore.requiresReopen()) editor.commitUncertain(value, problem); else editor.sendFailed(value, problem); failure = problem; }
            final Exception error = failure;
            handler.post(() -> {
                MainActivity active = activeActivity.get(); if (active == null || !active.activityAlive()) return;
                active.sending = false; active.reconcileEditorViews(); if (active.previewEditor != editor) return;
                if (error != null) { active.error(error); return; }
                active.clearPreview(); active.pickerKind = "all"; active.showChat(co, cv); active.toast(active.s(R.string.ui_300));
            });
        });
    }

    private View attachmentCard(ChatStore.Attachment a, boolean large) {
        if (a.mime.startsWith("audio/")) {
            VoicePlayerView voice = new VoicePlayerView(this, a, audioPlayback, audioWaveforms, () -> inspectAttachment(a), false);
            voice.setLayoutParams(p(large ? -1 : Math.max(d(180), (int)(windowWidth() * .79f) - d(28)), -2));
            return voice;
        }
        if (a.mime.startsWith("image/")) {
            float density = getResources().getDisplayMetrics().density;
            int width = ImagePreviewPolicy.boundedWidth(windowWidth(), density, large);
            ImagePreviewView photo = new ImagePreviewView(this, a, imagePreviews, large ? 1000 : 650, false);
            // Give the OUTER attachment its own width and height. A default MATCH_PARENT card
            // inside a WRAP_CONTENT image-only bubble can otherwise measure as a tall empty strip.
            photo.setLayoutParams(p(width, ImagePreviewPolicy.boundedHeight(width, density, large)));
            photo.setOnClickListener(v -> inspectAttachment(a));
            return photo;
        }
        LinearLayout card = column(this);
        card.setLayoutParams(p(large ? -1 : Math.min(d(235), (int)(windowWidth() * .67F)), -2));
        {
            LinearLayout pdf = row(this);
            pad(pdf, 12, 14);
            pdf.setBackground(bg(LIGHT, 13, this));
            FrameLayout f = new FrameLayout(this);
            f.setBackground(bg(LIME, 11, this));
            f.addView(icon(a.mime.equals("application/pdf") ? "pdf" : "attach", GREEN, 26), new FrameLayout.LayoutParams(d(26), d(26), Gravity.CENTER));
            pdf.addView(f, p(d(45), d(49)));
            LinearLayout labels = column(this);
            LinearLayout.LayoutParams ll = new LinearLayout.LayoutParams(0, -2, 1);
            ll.setMargins(d(10), 0, d(10), 0);
            pdf.addView(labels, ll);
            TextView title = text(this, a.name, 13, INK, true);
            title.setMaxWidth(d(large ? 245 : 155));
            title.setMaxLines(2);
            title.setEllipsize(TextUtils.TruncateAt.MIDDLE);
            labels.addView(title);
            labels.addView(text(this, s(R.string.attachment_metadata_preview, attachmentKind(a), formatSize(a.size)), 10, MUTED, false));
            card.addView(pdf, p(large ? -1 : Math.min(d(235), (int)(windowWidth() * 0.67F)), -2));
        }
        card.setOnClickListener((v)->inspectAttachment(a));
        card.setContentDescription(s(R.string.preview_file, displayName(a.name)));
        return card;
    }

    private String attachmentKind(ChatStore.Attachment file) {
        if (file.mime.startsWith("audio/")) return s(R.string.ui_303);
        if (file.mime.equals("application/pdf")) return "PDF";
        if (file.mime.startsWith("image/")) return s(R.string.ui_255);
        return s(R.string.ui_304);
    }

    private void inspectAttachment(ChatStore.Attachment file) {
        stopAudio();
        LinearLayout content = column(this); pad(content, 14, 12);
        TextView name = text(this, file.name, 15, INK, true); content.addView(name); spacer(content, 10);
        String extra = s(R.string.attachment_metadata_original, attachmentKind(file), formatSize(file.size));
        if (file.mime.startsWith("image/")) {
            ImagePreviewView image = new ImagePreviewView(this, file, imagePreviews, 1400, false);
            int width = ImagePreviewPolicy.boundedWidth(windowWidth(), getResources().getDisplayMetrics().density, true);
            content.addView(image, p(width, d(390)));
        }
        else if (file.mime.equals("application/pdf")) { content.addView(new PdfPreviewView(this, file), p(-1, d(390))); }
        if (file.mime.startsWith("audio/")) {
            content.addView(new VoicePlayerView(this, file, audioPlayback, audioWaveforms, null, false), p(-1, -2)); spacer(content, 12);
        } else if (!file.mime.startsWith("image/") && !file.mime.equals("application/pdf")) {
            content.addView(text(this, s(R.string.ui_309), 12, MUTED, false)); spacer(content, 10);
        }
        content.addView(text(this, extra, 11, MUTED, false));
        ScrollView scroll = new ScrollView(this); scroll.addView(content);
        AlertDialog dialog = new AlertDialog.Builder(this).setView(scroll).setPositiveButton(s(R.string.ui_051), null)
                .setNeutralButton(s(R.string.ui_310), (d, w) -> saveAttachment(file)).create();
        dialog.setOnDismissListener(d -> stopAudio()); dialog.show();
    }

    private void stopAudio() { if (audioPlayback != null) audioPlayback.stop(); }

    private void saveAttachment(ChatStore.Attachment file) {
        if (exportAttachment != null) { toast(s(R.string.ui_311)); return; }
        exportAttachment = file;
        Intent save = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType(file.mime == null || file.mime.contains("*") ? "application/octet-stream" : file.mime)
                .putExtra(Intent.EXTRA_TITLE, file.name);
        try { startActivityForResult(save, SAVE_FILE); }
        catch (ActivityNotFoundException missing) { exportAttachment = null; toast(s(R.string.ui_312)); }
    }

    private boolean hasComposedContent() {
        return composer != null && (!composer.getText().toString().trim().isEmpty() || !draftFiles.isEmpty());
    }

    private void updateComposerAction() {
        if (composerAction == null || composerActionGlyph == null) return;
        boolean active = voiceGesture.isActive();
        composerActionGlyph.kind = active && voiceGesture.isLocked() ? "stop" : !active && hasComposedContent() ? "send" : "mic";
        composerActionGlyph.invalidate();
        composerAction.setBackground(bg(active ? Color.rgb(180, 63, 54) : GREEN, 24, this));
        composerAction.setContentDescription(active ? s(R.string.ui_313) : hasComposedContent() ? s(R.string.ui_314) : s(R.string.ui_315));
        if (composerAttach != null) composerAttach.setEnabled(!active);
    }

    private void buildVoiceControls() {
        voiceBar = column(this); pad(voiceBar, 10, 5); voiceBar.setBackgroundColor(LIGHT);
        LinearLayout controls = row(this);
        voiceTimer = text(this, "● 0:00 / 2:00", 13, Color.rgb(175, 60, 52), true); voiceTimer.setGravity(Gravity.CENTER);
        controls.addView(voiceTimer, p(d(108), d(42)));
        liveWaveform = new WaveformView(this); voiceBar.addView(liveWaveform, p(-1, d(28)));
        controls.addView(new View(this), new LinearLayout.LayoutParams(0, 1, 1));
        voiceLockControl = buttonIcon("lock", s(R.string.ui_316), GREEN, () -> {
            if (voiceGesture.isHolding()) applyVoiceAction(voiceGesture.onMove(0, -VoiceGestureState.LOCK_DISTANCE_DP));
        });
        controls.addView(voiceLockControl);
        controls.addView(buttonIcon("stop", s(R.string.ui_317), GREEN, () -> applyVoiceAction(voiceGesture.onStop())));
        controls.addView(buttonIcon("close", s(R.string.ui_318), MUTED, () -> applyVoiceAction(voiceGesture.onCancel())));
        voiceBar.addView(controls, p(-1, d(44)));
        voiceHint = text(this, s(R.string.ui_319), 10, MUTED, false); voiceHint.setGravity(Gravity.CENTER);
        voiceBar.addView(voiceHint, p(-1, -2)); root.addView(voiceBar, p(-1, -2)); voiceBar.setVisibility(View.GONE);
    }

    private void updateVoiceControls() {
        if (voiceBar == null) return;
        boolean active = voiceGesture.isActive() && voiceRecorder != null;
        voiceBar.setVisibility(active ? View.VISIBLE : View.GONE);
        if (active) {
            long seconds = voiceRecorder.elapsedMillis() / 1000;
            voiceTimer.setText(String.format(Locale.ROOT, "● %d:%02d / 2:00", seconds / 60, seconds % 60));
            voiceHint.setText(voiceGesture.isLocked() ? s(R.string.ui_320) : s(R.string.ui_319));
            voiceLockControl.setEnabled(voiceGesture.isHolding()); voiceLockControl.setAlpha(voiceGesture.isHolding() ? 1f : .35f);
        }
        updateComposerAction();
    }

    private boolean onVoiceTouch(View view, android.view.MotionEvent event) {
        int action = event.getActionMasked();
        if (action == android.view.MotionEvent.ACTION_DOWN) {
            if (voiceGesture.isLocked() || hasComposedContent()) return false;
            voiceTouchTracking = true; voicePointerId = event.getPointerId(0); voiceDownX = event.getRawX(); voiceDownY = event.getRawY();
            view.getParent().requestDisallowInterceptTouchEvent(true);
            if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                requestMicrophonePermission(); return true;
            }
            startVoice(companyId, conversationId, false); return true;
        }
        if (!voiceTouchTracking) return false;
        if (action == android.view.MotionEvent.ACTION_POINTER_DOWN) { applyVoiceAction(voiceGesture.onCancel()); return true; }
        if (action == android.view.MotionEvent.ACTION_MOVE) {
            if (event.findPointerIndex(voicePointerId) < 0) applyVoiceAction(voiceGesture.onCancel());
            else applyVoiceAction(voiceGesture.onMove((event.getRawX() - voiceDownX) / getResources().getDisplayMetrics().density,
                    (event.getRawY() - voiceDownY) / getResources().getDisplayMetrics().density));
            return true;
        }
        if (action == android.view.MotionEvent.ACTION_UP) {
            voiceTouchTracking = false; voicePointerId = -1;
            applyVoiceAction(voiceGesture.onPointerUp());
            view.getParent().requestDisallowInterceptTouchEvent(false);
            // Preserve the accessibility click contract without starting or sending again on release.
            suppressComposerClick = true; view.performClick(); return true;
        }
        if (action == android.view.MotionEvent.ACTION_CANCEL) {
            voiceTouchTracking = false; voicePointerId = -1; applyVoiceAction(voiceGesture.onCancel());
            view.getParent().requestDisallowInterceptTouchEvent(false); return true;
        }
        return true;
    }

    private void applyVoiceAction(VoiceGestureState.Action action) {
        if (action == VoiceGestureState.Action.STOP_FOR_PREVIEW) finishVoice(true);
        else if (action == VoiceGestureState.Action.CANCEL_AND_DISCARD) { finishVoice(false); toast(s(R.string.ui_321)); }
        else if (action == VoiceGestureState.Action.LOCKED) { updateVoiceControls(); if (voiceBar != null) voiceBar.announceForAccessibility(s(R.string.ui_322)); }
    }

    private void requestMicrophonePermission() {
        micPermissionCompany = companyId; micPermissionConversation = conversationId;
        requestPermissions(new String[]{android.Manifest.permission.RECORD_AUDIO}, MICROPHONE_PERMISSION);
    }

    /** Explicit click/menu/accessibility alternative starts in hands-free lock mode. */
    private void requestVoiceRecording() {
        if (!canEditCurrentDraft()) { toast(s(R.string.foundation_orphan_capacity)); return; }
        if (!"chat".equals(screen) || conversationId == null || voiceRecorder != null) return;
        if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestMicrophonePermission(); return;
        }
        startVoice(companyId, conversationId, true);
    }

    private void startVoice(String co, String cv, boolean locked) {
        if (!canEditCurrentDraft()) { toast(s(R.string.foundation_orphan_capacity)); return; }
        if (destroyed || isFinishing() || !"chat".equals(screen) || co == null || cv == null || !co.equals(companyId) || !cv.equals(conversationId) || voiceRecorder != null) return;
        if (draftFiles.size() >= 10) { toast(s(R.string.ui_323)); return; }
        persistDraft(); stopAudio();
        final long[] gestureSession = {0};
        try {
            store.conversation(co, cv); voiceCompany = co; voiceConversation = cv;
            voiceRecorder = new VoiceRecorder(getApplicationContext(), new VoiceRecorder.Listener() {
                public void onLimitReached() { applyVoiceAction(voiceGesture.onLimitReached(gestureSession[0])); }
                public void onError(String reason) {
                    if (gestureSession[0] == voiceGesture.sessionId()) { voiceGesture.onError(); finishVoice(false); toast(AppLocale.error(MainActivity.this, reason)); }
                }
            });
            if (liveWaveform != null) liveWaveform.samples(null);
            voiceRecorder.start();
            if (!voiceGesture.onRecorderStarted(true, locked)) { voiceRecorder.cancel(); voiceRecorder = null; return; }
            gestureSession[0] = voiceGesture.sessionId();
            updateVoiceControls(); handler.removeCallbacks(voiceTicker); handler.post(voiceTicker);
        } catch (IOException | RuntimeException error) {
            if (voiceRecorder != null) voiceRecorder.cancel(); voiceRecorder = null; voiceGesture.reset(); updateVoiceControls(); error(error);
        }
    }

    private void finishVoice(boolean keep) {
        VoiceRecorder recorder = voiceRecorder; voiceRecorder = null;
        voiceGesture.reset(); handler.removeCallbacks(voiceTicker);
        if (recorder == null) { updateVoiceControls(); return; }
        try {
            if (keep) {
                ChatStore.Attachment file = recorder.finish();
                boolean added = addFilesToDraft(voiceCompany, voiceConversation, Collections.singletonList(file));
                if (added) {
                    hideKeyboard();
                    if (attachmentTray != null) attachmentTray.setVisibility(View.VISIBLE);
                    toast(s(R.string.ui_324));
                }
            } else recorder.cancel();
        } catch (IOException | RuntimeException error) { recorder.cancel(); error(error); }
        updateVoiceControls();
    }

        private int windowWidth() {
            return root != null && root.getWidth() > 0 ? root.getWidth() : getResources().getDisplayMetrics().widthPixels;
        }

    private String formatSize(long size) {
        if (size == 0) { return "0 B"; }
        return size >= 1024 * 1024 ? s(R.string.file_megabytes, String.format(Locale.ROOT, "%.1f", size / (1024.0 * 1024))) : s(R.string.file_kilobytes, Math.max(1, size / 1024));
    }

    private interface FilesReady {

            void done(List<ChatStore.Attachment> files);
        }

        private interface Changed {

            void changed(String value);
        }

        private TextWatcher watcher(Changed callback) {
            return new TextWatcher(){

                public void beforeTextChanged(CharSequence s, int st, int count, int after) {
                }

                public void onTextChanged(CharSequence s, int st, int before, int count) {
                    callback.changed(s.toString());
                }

                public void afterTextChanged(Editable e) {
                }
            };
        }

        private void receiveShare(Intent incoming) {
            if (importing) {
                toast(s(R.string.ui_053));
                return;
            }
            persistDraft();
            ArrayList<Uri> uris = new ArrayList<>();
            String text = "";
            try {
                CharSequence value = incoming.getCharSequenceExtra(Intent.EXTRA_TEXT);
                if (value != null) text = value.toString();
                if (text.length() > ChatStore.MAX_TEXT_LENGTH) {
                    toast(s(R.string.ui_325));
                    return;
                }
                if (Intent.ACTION_SEND_MULTIPLE.equals(incoming.getAction())) {
                    ArrayList<Uri> list = incoming.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
                    if (list != null) uris.addAll(list);
                } else {
                    Uri uri = incoming.getParcelableExtra(Intent.EXTRA_STREAM);
                    if (uri != null) uris.add(uri);
                }
                if (uris.isEmpty() && incoming.getClipData() != null) {
                    for (int i = 0; i < incoming.getClipData().getItemCount(); i++) {
                        Uri u = incoming.getClipData().getItemAt(i).getUri();
                        if (u != null) uris.add(u);
                    }
                }
            } catch (RuntimeException e) {
                toast(s(R.string.ui_326));
                return;
            }
            uris = new ArrayList<>(new LinkedHashSet<>(uris));
            if (uris.isEmpty() && text.trim().isEmpty()) {
                toast(s(R.string.ui_327));
                return;
            }
            final String sharedText = text;
            final int shareNavigationEpoch = navigationEpoch;
            importUris(uris, incoming.getType(), (files)->{
                final ChatStore targetStore=store;final ArrayList<ChatStore.Attachment> imported=new ArrayList<>(files);
                storeOperation(()->targetStore.stagePendingShare(sharedText,imported),pending->{shareIntakeInProgress=false;clearPreview();pickerCompany="all";pickerKind="all";if(navigationEpoch==shareNavigationEpoch)showPicker(true);else toast(s(R.string.ui_328));},failure->{shareIntakeInProgress=false;error(failure);});
            });
        }

    private void importUris(ArrayList<Uri> uris, String fallbackMime, FilesReady ready) {
        if (uris.size() > 10) { toast(s(R.string.ui_329)); return; }
        if (uris.isEmpty()) { ready.done(Collections.emptyList()); return; }
        if (importing) return;
        importing = true;
        ProgressDialog progress = new ProgressDialog(this); activeProgress = progress;
        progress.setMessage(s(R.string.ui_330)); progress.setCancelable(false); progress.show();
        io.execute(() -> {
            ArrayList<ChatStore.Attachment> files = new ArrayList<>();
            String failure = null;
            try {
                long remaining = MAX_TOTAL;
                for (Uri uri : uris) {
                    if (destroyed || Thread.currentThread().isInterrupted()) throw new IOException(s(R.string.ui_331));
                    ChatStore.Attachment file = AttachmentSupport.importUri(getApplicationContext(), uri, fallbackMime, remaining);
                    files.add(file); remaining -= file.size;
                }
            } catch (Exception error) {
                for (ChatStore.Attachment file : files) new File(file.path).delete();
                failure = AppLocale.error(this, error.getMessage());
            }
            final String error = failure;
            runOnUiThread(() -> {
                importing = false;
                try { if (progress.isShowing()) progress.dismiss(); } catch (RuntimeException ignored) { }
                activeProgress = null;
                if (destroyed || isDestroyed() || isFinishing()) { for (ChatStore.Attachment file : files) new File(file.path).delete(); return; }
                if (error != null) {shareIntakeInProgress=false;toast(error);} else { ready.done(files); cleanupAttachments(); }
            });
        });
    }

    private boolean handleLocalNotification(Intent intent) {
        if (intent == null || !DemoNotifications.OPEN_ACTION.equals(intent.getAction())) return false;
        navigationEpoch++;
        persistDraft();
        persistPreview();
        try {
            NotificationDemoPolicy.Target target = NotificationDemoPolicy.target(store,
                    intent.getStringExtra(DemoNotifications.COMPANY),
                    intent.getStringExtra(DemoNotifications.CONVERSATION), NotificationDemoPolicy.IMMEDIATE);
            showChat(target.companyId, target.conversationId);
        } catch (RuntimeException invalid) {
            toast(s(R.string.ui_333));
            showList();
        }
        return true;
    }

    private void showNotificationTest(String co, String cv, AnchoredMenu.Scope scope) {
        if (!scope.isCurrent()) return;
        hideKeyboard();
        persistDraft();
        final NotificationDemoPolicy.Target target;
        try { target = NotificationDemoPolicy.target(store, co, cv, NotificationDemoPolicy.IMMEDIATE); }
        catch (RuntimeException invalid) { error(invalid); return; }
        DemoNotifications.ensureChannel(this);
        LinearLayout content = column(this);
        pad(content, 22, 12);
        TextView destination = text(this, target.conversationTitle + "\n" + target.companyName, 14, GREEN, true);
        content.addView(destination);
        spacer(content, 12);
        TextView explanation = text(this, s(R.string.ui_334)
                + DemoNotifications.soundHint(this)
                + s(R.string.ui_335), 12, MUTED, false);
        content.addView(explanation);
        spacer(content, 10);
        String blocker = DemoNotifications.postingBlocker(this);
        TextView status = text(this, blocker == null ? DemoNotifications.status(this) : blocker, 11, GREEN, false);
        content.addView(status);
        spacer(content, 16);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(content);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(s(R.string.ui_146))
                .setView(scroll).setNegativeButton(s(R.string.ui_051), null).create();
        content.addView(action(s(R.string.ui_336), () -> { dialog.dismiss(); if (scope.isCurrent()) requestNotificationTest(co, cv, NotificationDemoPolicy.IMMEDIATE); }), p(-1, d(50)));
        spacer(content, 8);
        content.addView(action(s(R.string.ui_337), () -> { dialog.dismiss(); if (scope.isCurrent()) requestNotificationTest(co, cv, NotificationDemoPolicy.DELAYED); }), p(-1, d(50)));
        spacer(content, 10);
        TextView settings = text(this, s(R.string.ui_338), 13, GREEN, true);
        pad(settings, 8, 10);
        settings.setOnClickListener(v -> { dialog.dismiss(); if (scope.isCurrent()) openNotificationSettings(DemoNotifications.permissionGranted(this)); });
        content.addView(settings, p(-1, d(44)));
        TextView cancel = text(this, s(R.string.ui_339), 12, MUTED, false);
        pad(cancel, 8, 10);
        cancel.setOnClickListener(v -> { dialog.dismiss(); if (scope.isCurrent()) { DemoNotifications.cancel(this); toast(DemoNotifications.status(this)); } });
        content.addView(cancel, p(-1, d(44)));
        showMenuDialog(dialog, scope);
    }

    private void requestNotificationTest(String co, String cv, int delay) {
        try { NotificationDemoPolicy.target(store, co, cv, delay); }
        catch (RuntimeException invalid) { error(invalid); return; }
        if (Build.VERSION.SDK_INT >= 33
                && NotificationDemoPolicy.needsRuntimePermission(Build.VERSION.SDK_INT, DemoNotifications.permissionGranted(this))) {
            // A dismissed prompt is not a permanent denial. Every request here follows a new explicit test press;
            // Android decides whether to show the dialog or return a denial, which offers Settings below.
            permissionTestCompany = co;
            permissionTestConversation = cv;
            permissionTestDelay = delay;
            requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS}, NOTIFICATION_PERMISSION);
            return;
        }
        runNotificationTest(co, cv, delay);
    }

    private void runNotificationTest(String co, String cv, int delay) {
        DemoNotifications.ensureChannel(this);
        String blocker = DemoNotifications.postingBlocker(this);
        if (blocker != null) { showNotificationProblem(blocker); return; }
        try {
            NotificationDemoPolicy.Target target = NotificationDemoPolicy.target(store, co, cv, delay);
            toast(DemoNotifications.start(this, target));
        } catch (RuntimeException invalid) { error(invalid); }
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == MICROPHONE_PERMISSION) {
            String co = micPermissionCompany, cv = micPermissionConversation;
            micPermissionCompany = null; micPermissionConversation = null;
            if (results.length > 0 && results[0] == android.content.pm.PackageManager.PERMISSION_GRANTED)
                toast(s(R.string.ui_340));
            else new AlertDialog.Builder(this).setTitle(s(R.string.ui_341))
                    .setMessage(s(R.string.ui_342))
                    .setPositiveButton(s(R.string.ui_343), (dialog, which) -> {
                        try { startActivity(new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + getPackageName()))); }
                        catch (ActivityNotFoundException unavailable) { toast(s(R.string.ui_344)); }
                    }).setNegativeButton(s(R.string.ui_051), null).show();
            return;
        }
        if (requestCode != NOTIFICATION_PERMISSION) return;
        String co = permissionTestCompany, cv = permissionTestConversation;
        int delay = permissionTestDelay;
        permissionTestCompany = null;
        permissionTestConversation = null;
        permissionTestDelay = -1;
        if (results.length > 0 && results[0] == android.content.pm.PackageManager.PERMISSION_GRANTED) {
            if (co != null && cv != null && delay >= 0) runNotificationTest(co, cv, delay);
            else toast(s(R.string.ui_345));
        } else showNotificationProblem(s(R.string.ui_346));
    }

    private void showNotificationProblem(String reason) {
        new AlertDialog.Builder(this).setTitle(s(R.string.ui_347)).setMessage(reason
                + s(R.string.ui_348))
                .setPositiveButton(s(R.string.ui_343), (dialog, which) -> openNotificationSettings(DemoNotifications.permissionGranted(this)))
                .setNegativeButton(s(R.string.ui_349), null).show();
    }

    private void openNotificationSettings(boolean channel) {
        try { startActivity(DemoNotifications.settings(this, channel)); }
        catch (ActivityNotFoundException missing) {
            try { startActivity(new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:" + getPackageName()))); }
            catch (ActivityNotFoundException unavailable) { toast(s(R.string.ui_350)); }
        }
    }

    private void hideKeyboard() {
                    View v = getCurrentFocus();
                    if (v != null) {
                        ((InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(v.getWindowToken(), 0);
                        v.clearFocus();
                    }
                }

                private void toast(String message) {
                    Toast.makeText(this, message, Toast.LENGTH_LONG).show();
                }

                private void error(Exception e) {
                    if (store != null && store.requiresReopen()) { showUncertainHistory(); return; }
                    toast(s(R.string.operation_failed, AppLocale.error(this, e.getMessage())));
                }

                @Override
                public void onBackPressed() {
                    if (overflowMenu != null && overflowMenu.dismiss()) return;
                    if (importing || initializing) return;
                    if (voiceRecorder != null) { finishVoice(false); toast(s(R.string.ui_353)); return; }
                    if ("chat".equals(screen)) showList(); else if ("preview".equals(screen)) showPicker(true); else if ("picker".equals(screen)) leavePicker(); else if ("recovery".equals(screen) || "create_group".equals(screen) || "settings".equals(screen) || "orders".equals(screen) || "tasks".equals(screen)) showList(); else {
                        if (beforeNavigation(this::finish)) super.onBackPressed();
                    }
                }

                @Override
                public void onConfigurationChanged(android.content.res.Configuration c) {
                    super.onConfigurationChanged(c);
                    String old = screen;
                    if ("chat".equals(old)) {
                        captureEditors(); captureReadingState();
                        int start = composer == null ? -1 : composer.getSelectionStart(), end = composer == null ? -1 : composer.getSelectionEnd();
                        String co = companyId, cv = conversationId; restoringScreen = true;
                        try { showChat(co, cv); } finally { restoringScreen = false; }
                        if (composer != null && start >= 0 && end >= 0) composer.setSelection(Math.min(start, composer.length()), Math.min(end, composer.length()));
                    } else if ("recovery".equals(old)) showRecoveredEditor(recoveredEditorKey); else if ("entry".equals(old)) showEntry(); else if ("settings".equals(old)) showSettings(); else if ("orders".equals(old) || "tasks".equals(old)) showModule(old); else if ("preview".equals(old)) showSharePreview(); else if ("picker".equals(old)) showPicker(pickerSharing, true); else if ("create_group".equals(old)) showCreateGroup(false); else showList();
                }

                @Override
                protected void onDestroy() {
                    stopEntryMotion();
                    dismissMenuContext();
                    if (saveTask != null) handler.removeCallbacks(saveTask);
                    if (previewSaveTask != null) handler.removeCallbacks(previewSaveTask);
                    if (chatSearchTask != null) handler.removeCallbacks(chatSearchTask);
                    handler.removeCallbacks(voiceTicker);
                    if (voiceRecorder != null) finishVoice(false);
                    destroyed = true; cancelQueries();
                    stopAudio(); if (audioWaveforms != null) audioWaveforms.close();
                    if (imagePreviews != null) imagePreviews.close();
                    io.shutdownNow();
                    if (activeProgress != null) try {
                        activeProgress.dismiss();
                    } catch (RuntimeException ignored) {
                    }
                    super.onDestroy();
                }
            }
