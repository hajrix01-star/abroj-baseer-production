package com.baseer.freshchat;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.DatePickerDialog;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.TimePickerDialog;
import android.Manifest;
import android.content.Context;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.provider.MediaStore;
import android.provider.Settings;
import android.graphics.Color;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Rect;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaPlayer;
import android.media.AudioAttributes;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Bundle;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Base64;
import android.util.Log;
import android.util.LruCache;
import android.text.BidiFormatter;
import android.text.InputType;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.TouchDelegate;
import android.view.View;
import android.view.ViewParent;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.net.http.SslError;
import android.webkit.WebMessage;
import android.webkit.WebMessagePort;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.GridLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.PopupMenu;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;
import androidx.annotation.NonNull;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.baseer.freshchat.sync.AccountScope;
import com.baseer.freshchat.sync.BChatV2Outbox;
import com.baseer.freshchat.sync.BChatConnectedMediaStore;
import com.baseer.freshchat.sync.ConnectedHistoryCache;
import com.baseer.freshchat.sync.OutboxPolicy;
import com.baseer.freshchat.sync.TaskOfflineCache;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedList;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;
import java.util.ArrayList;
import java.util.List;
import java.util.Calendar;
import java.util.Collections;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;
import java.util.UUID;
import java.text.SimpleDateFormat;
import java.nio.charset.StandardCharsets;
import java.math.BigDecimal;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Employee entry and isolated BChat v2 text client. The offline demo store stays untouched. */
public final class OdooIdentityActivity extends Activity {
    private static final String TRANSPORT_LOG_TAG = "BChatTransport";
    public static final String EXTRA_SHARE_UNAVAILABLE = "com.baseer.bchat.SHARE_UNAVAILABLE";
    private static final String ORIGIN = RuntimeOrigin.forHardware(Build.HARDWARE, BuildConfig.BCHAT_ORIGIN);
    private static final String DATABASE = BuildConfig.BCHAT_DATABASE;
    private static final String BRIDGE_PATH = "/bchat/app/bridge";
    private static final String BRIDGE = ORIGIN + BRIDGE_PATH;
    // QA hides its database selector. Pin the known QA database before submitting
    // the official Odoo form, otherwise a fresh WebView is diverted to /web/database/selector.
    private static final String LOGIN = ORIGIN + "/web/login?db=" + Uri.encode(DATABASE)
            + "&redirect=%2Fbchat%2Fapp%2Fbridge";
    private static final String V1_BOOTSTRAP = "/bchat/api/v1/bootstrap";
    private static final String BOOTSTRAP = ORIGIN + V1_BOOTSTRAP;
    private static final String V2_BOOTSTRAP = "/bchat/api/v2/bootstrap";
    private static final String V2_ROOMS = "/bchat/api/v2/rooms";
    private static final String V2_PROFILE_AVATAR = "/bchat/api/v2/profile/avatar";
    private static final String V2_TASKS = "/bchat/api/v2/tasks";
    private static final String V2_ATTENTION = "/bchat/api/v2/attention";
    private static final String V2_ORDERS = "/bchat/api/v2/orders";
    private static final String V2_CHANGES = "/bchat/api/v2/changes";
    private static final String LIVE_PREFS = "bchat-change-cursor-v1";
    private static final String V2_PUSH_REGISTER = "/bchat/api/v2/notifications/register";
    private static final String V2_PUSH_UNREGISTER = "/bchat/api/v2/notifications/unregister";
    private static final String V2_PUSH_EVENTS = "/bchat/api/v2/notifications/";
    private static final String LOGOUT = ORIGIN + "/web/session/logout?redirect=%2Fweb%2Flogin%3Fdb%3D"
            + Uri.encode(DATABASE);
    private static final String PREFS = "bchat-employee-auth-v1";
    private static final String TASK_CREATE_PREFS = "bchat-task-create-pending-v1";
    private static final String ORDER_CREATE_PREFS = "bchat-order-create-pending-v1";
    private static final String ORDER_COMPANY_PREFS = "bchat-order-company-v1";
    private static final String ORDER_COMPANY_OWNER = "account-key";
    private static final String ORDER_COMPANY_SELECTED = "company-id";
    private static final String RECEIPT_CONFIRM_PREFS = "bchat-receipt-confirm-pending-v1";
    private static final String RECEIPT_SHARE_PREFS = "bchat-receipt-share-pending-v1";
    private static final String GROUP_CREATE_PREFS = "bchat-group-create-pending-v1";
    private static final String PERMISSION_PREFS = "bchat-permissions-v1";
    private static final String ORDER_PERMISSION_PREFS = "bchat-order-permissions-v1";
    private static final String REMEMBER = "remember-session";
    private static final String PUSH_PERMISSION_ASKED = "push-permission-asked";
    private static final int PUSH_PERMISSION_REQUEST = 1204;
    private static final int MAX_RESPONSE = 8192;
    private static final int MAX_V2_RESPONSE = 131072;
    private static final int MAX_PROFILE_BYTES = 16 * 1024;
    private static final int MAX_PRIVATE_AVATAR_BYTES = 256 * 1024;
    private static final int MAX_ORDER_IMAGE_BYTES = 131072;
    private static final long BRIDGE_NAVIGATION_TIMEOUT_MILLIS = 8000L;
    // The verified v2 attachment capability is the runtime gate.
    private static final boolean CONNECTED_MEDIA_UI_ENABLED = true;
    private static final int MEDIA_PICK_REQUEST = 1205;
    private static final int MEDIA_SAVE_REQUEST = 1206;
    private static final int MEDIA_CAMERA_REQUEST = 1207;
    private static final int MEDIA_RECORD_PERMISSION_REQUEST = 1208;
    private static final int GROUP_PHOTO_REQUEST = 1209;
    private static final int MEDIA_READ_CHUNK_BYTES = 64 * 1024;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final SharedPreferences.OnSharedPreferenceChangeListener pushTokenListener =
            (preferences, key) -> {
                if ("fcm-token".equals(key)) handler.post(this::maybeRegisterPush);
            };
    private boolean pushRegistrationBusy;
    private boolean pushRegistrationScheduled;
    // QA stage codes only. Never include a URL, account, token, CSRF value, or response body.
    private String pushRegistrationDiagnostic = "P00_IDLE";
    private PushTarget pendingPush;
    private boolean pushNavigationBusy;
    private boolean pushNavigationScheduled;
    private int pushNavigationRetries;
    private long pendingNotificationTaskId;
    private long pendingNotificationMessageId;
    /** A push can name a freshly-added room that the cached room list has not seen yet. */
    private long pendingPushRoomId;
    private long pendingPushRoomMessageId;
    private LinearLayout layout;
    private TextView status;
    private TextView shellNotice;
    private Button shellRetry;
    private ScrollView nativeForm;
    private TextView loginReleaseFooter;
    private LinearLayout shell;
    private EditText loginInput;
    private EditText passwordInput;
    private Button signIn;
    private Button localExit;
    private WebView web;
    private WebMessagePort replyPort;
    private WebMessagePort v2Port;
    private int v2Nonce;
    private boolean v2Busy;
    private WebMessagePort livePort;
    private WebMessagePort busPort;
    private final LinkedList<LiveRequest> liveQueue = new LinkedList<>();
    private final Set<String> acknowledgedMessages = new HashSet<>();
    private final Set<String> pendingAcknowledgements = new HashSet<>();
    private int liveNonce, busNonce;
    private boolean liveBusy, feedQueued, snapshotInProgress, liveStarted, liveForeground, busConnected;
    private boolean receiptsAvailable;
    private long feedCursor, feedRetryAt;
    private int feedFailures, busFailures;
    private Runnable feedTimer, busReconnect;
    private boolean liveRoomsDirty, liveMessagesDirty, liveTasksDirty, liveOrdersDirty;
    private boolean liveUiScheduled;
    private String csrfToken;
    private AccountScope account;
    private final Set<Long> v1Companies = new HashSet<>();
    private BChatV2Outbox outbox;
    private ConnectedHistoryCache historyCache;
    private TaskOfflineCache taskOfflineCache;
    private PermissionSet permissionSet = PermissionSet.legacy();
    private AccountScope permissionAccount;
    private boolean permissionRefreshScheduled;
    private long lastPermissionRefreshAt;
    private static final Object historyStorageLock = new Object();
    private static volatile int historyGlobalGeneration;
    private final ExecutorService historyWrites = Executors.newSingleThreadExecutor();
    private final ExecutorService mediaIo = Executors.newSingleThreadExecutor();
    /** Read-only fallback when an Android WebView drops a message-port response. */
    private boolean webV2GetFallbackBusy;
    private int webV2GetFallbackGeneration;
    /** Safe stage codes for the QA-only transport diagnostic; never include response content. */
    private String transportDiagnostic = "D00";
    private volatile int historyWriteGeneration;
    private boolean offlineHistory;
    private boolean offlineChatCacheAvailable, offlineTaskCacheAvailable;
    private long offlineChatVerifiedAt, offlineTaskVerifiedAt;
    private static final long MAX_OFFLINE_AGE_MILLIS = 24L * 60L * 60L * 1000L;
    private boolean offlineUncertainWrite;
    private final List<JSONObject> displayedMessages = new ArrayList<>();
    private static final int MAX_CONNECTED_MESSAGE_WINDOW = 500;
    private boolean olderPageLoading;
    private boolean olderPageFailed;
    private boolean scrollAfterOwnSend;
    private int messageRenderSerial;
    private BChatConnectedMediaStore mediaStore;
    private boolean mediaAvailable;
    private View mediaPickButton;
    private Button mediaReviewButton;
    private BChatNativeMediaUploader.Call mediaNativeUpload;
    private Runnable mediaUploadTimeout;
    private int mediaUploadNonce;
    private boolean mediaUploadBusy;
    private boolean mediaConfirmBusy;
    private boolean mediaReplayAfterInitialHistory;
    private Room mediaConfirmRoom;
    /** Generation fence for a read-only recovery after a lost media-message reply. */
    private int mediaConfirmRecoveryGeneration;
    private AccountScope mediaPickerAccount;
    private Room mediaPickerRoom;
    private int mediaPickerGeneration;
    private int mediaSessionGeneration;
    private File cameraCaptureFile;
    private VoiceRecorder connectedVoiceRecorder;
    private File voicePreviewFile;
    private AlertDialog voicePreviewDialog;
    private MediaPlayer voicePreviewPlayer;
    private View mediaVoiceButton;
    private boolean mediaStageBusy;
    private boolean mediaCancelBusy;
    private WebMessagePort mediaReadPort;
    private FileOutputStream mediaReadOutput;
    private boolean mediaReadChunkPending;
    private File mediaReadFile;
    private Runnable mediaReadTimeout;
    private int mediaReadNonce, mediaReadSequence, mediaReadBytes;
    private boolean mediaReadBusy;
    private boolean mediaReadStarted;
    private File pendingPdfDownload;
    private AccountScope pendingPdfAccount;
    private Room pendingPdfRoom;
    private AlertDialog mediaPreviewDialog;
    private int mediaOpenNonce;
    private MediaPlayer inlineAudioPlayer;
    private File inlineAudioFile;
    private Room inlineAudioRoom;
    private AccountScope inlineAudioAccount;
    private long inlineAudioMediaId;
    private TextView inlineAudioPlay;
    private SeekBar inlineAudioSeek;
    private WaveformView inlineAudioWave;
    private AudioWaveforms connectedWaveforms;
    private TextView inlineAudioTime;
    private boolean inlineAudioSeeking;
    private boolean inlineAudioPrepared;
    private int inlineAudioRequest;
    private Runnable inlineAudioTicker;
    private AlertDialog sensitiveDetailDialog;
    private final List<MediaThumbTarget> mediaThumbnailQueue = new ArrayList<>();
    private final LruCache<String, Bitmap> mediaThumbnailCache = new LruCache<String, Bitmap>(2 * 1024 * 1024) {
        @Override protected int sizeOf(String key, Bitmap bitmap) { return bitmap.getByteCount(); }
    };
    private final List<Room> rooms = new ArrayList<>();
    /** Advances only after a complete authoritative /rooms replacement. */
    private int roomMetadataGeneration;
    /** Advances after a locally confirmed read so an older /rooms reply cannot restore its badge. */
    private int unreadMetadataGeneration;
    private AccountScope groupPhotoAccount;
    private Room groupPhotoRoom;
    private final Map<String, List<ImageView>> groupAvatarWaiting = new LinkedHashMap<>();
    private final LinkedList<Room> groupAvatarQueue = new LinkedList<>();
    private boolean groupAvatarBusy;
    private WebMessagePort groupAvatarPort;
    private int groupAvatarNonce;
    private final LruCache<String, Bitmap> groupAvatarCache = new LruCache<String, Bitmap>(4 * 1024 * 1024) {
        @Override protected int sizeOf(String key, Bitmap bitmap) { return bitmap.getByteCount(); }
    };
    /** Member images are private, session-bound reads; initials remain the safe fallback. */
    private final Map<String, List<ImageView>> privateAvatarWaiting = new LinkedHashMap<>();
    private final LinkedList<PrivateAvatarRequest> privateAvatarQueue = new LinkedList<>();
    private boolean privateAvatarBusy;
    private WebMessagePort privateAvatarPort;
    private int privateAvatarNonce;
    private final LruCache<String, Bitmap> privateAvatarCache = new LruCache<String, Bitmap>(4 * 1024 * 1024) {
        @Override protected int sizeOf(String key, Bitmap bitmap) { return bitmap.getByteCount(); }
    };
    private Room selectedRoom;
    private Room pendingOrderShareRoom;
    private long nextBeforeId;
    private LinearLayout chatRoot;
    private LinearLayout chatPane;
    private LinearLayout brandBar;
    private LinearLayout chatTitleBar;
    private LinearLayout roomListHeader;
    private LinearLayout roomSearchSurface;
    private View roomPendingButton;
    private View createGroupButton;
    private FrameLayout roomAvatarSlot;
    private TextView roomSubtitle;
    private LinearLayout modulePane;
    private LinearLayout orderItems;
    private ScrollView orderScroll;
    private TextView orderNotice;
    private TextView orderCartSummary;
    private LinearLayout orderCartBar;
    private View orderCatalogLine, orderMineLine, orderReceiptLine;
    private String orderRenderedKey;
    private Runnable orderLoadingTask;
    private Runnable orderRetryAction;
    private boolean orderLoadingVisible;
    private LinearLayout orderDetailsPanel, orderFiltersRow, orderPagingRow;
    private Button orderDetailsButton, orderPreviousButton;
    private Button orderWarehouseButton, orderRepresentativeButton, orderCartRouteButton,
            orderCartRepresentativeButton;
    private TextView orderHeaderCompanyButton;
    private TextView chatHeaderCompanyButton;
    private long selectedChatCompanyId;
    private Button orderCatalogButton, orderMineButton, orderReceiptButton, orderCategoryButton;
    private Button orderCartButton, orderPendingButton, receiptPendingButton,
            receiptSharePendingButton, orderOlderButton;
    private EditText orderSearch;
    private final List<TaskChoice> orderCompanies = new ArrayList<>();
    private final Set<Long> deniedOrderCompanyIds = new HashSet<>();
    private final List<TaskChoice> orderWarehouses = new ArrayList<>();
    private final List<TaskChoice> orderRepresentatives = new ArrayList<>();
    private final List<String> orderPurchaseRoutes = new ArrayList<>();
    private final List<TaskChoice> orderCategories = new ArrayList<>();
    private final List<OrderOption> orderOptions = new ArrayList<>();
    private final List<OrderSummary> orderSummaries = new ArrayList<>();
    private final List<ReceiptSummary> receiptSummaries = new ArrayList<>();
    private final Map<Long, OrderCartLine> orderCart = new LinkedHashMap<>();
    private int orderCartRevision = 1;
    private String orderQuoteTotal;
    private String orderQuoteCurrency;
    private boolean orderQuoteLoading;
    private Runnable orderQuoteTask;
    private AlertDialog orderCartDialog;
    private AlertDialog receiptFlowDialog;
    private LinearLayout orderCartLinesView;
    private TextView orderCartTotalView;
    private OrderCartLine lastRemovedOrderLine;
    private long orderCompanyId, orderWarehouseId, orderRepresentativeId, orderCategoryId;
    private String orderPurchaseRoute = "representative";
    private long orderCatalogAfterId, orderListBeforeId;
    private long receiptBeforeId;
    private long orderCurrentPageStartId;
    private final List<Long> orderPageHistory = new ArrayList<>();
    private int orderViewSerial;
    private boolean ordersAvailable, ordersDenied, orderMine, orderReceiving;
    private boolean orderCanView, orderCanCreate, orderCanReceive;
    private String orderAccess = "";
    private long lastOrderCapabilityProbeAt;
    private boolean orderCapabilityProbeScheduled;
    private int orderCapabilityProbeFailures;
    private JSONObject orderCapabilityOptions;
    private AccountScope orderCapabilityAccount;
    private long orderCapabilityOptionsAt;
    private Runnable queuedOrderLoad;
    private boolean allOrdersRecoveryAttempted;
    private boolean orderCompanyOptionsLoaded;
    private Runnable orderSearchTask;
    private WebMessagePort orderImagePort;
    private int orderImageNonce;
    private boolean orderImageBusy;
    private boolean orderImagePumpScheduled;
    private final List<OrderImageTarget> orderImageTargets = new ArrayList<>();
    private final Set<String> orderImageFailedKeys = new HashSet<>();
    private final LruCache<String, Bitmap> orderImageCache = new LruCache<String, Bitmap>(2 * 1024 * 1024) {
        @Override protected int sizeOf(String key, Bitmap bitmap) { return bitmap.getByteCount(); }
    };
    private LinearLayout taskPane;
    private LinearLayout taskItems;
    private TextView taskNotice;
    private TextView taskHeading;
    private Button taskNewButton;
    private Button taskPendingButton;
    private Button taskAllButton, taskOpenButton, taskDoneButton;
    private View taskAllLine, taskOpenLine, taskDoneLine;
    private Button taskOlderButton;
    private View roomTasksButton;
    private long taskRoomFilter;
    /** Scope currently rendered in the task list; never keep another room's rows on screen. */
    private long renderedTaskRoomFilter = Long.MIN_VALUE;
    private long taskBeforeId;
    private int taskViewSerial;
    private String taskStateFilter = "open";
    private boolean tasksAvailable;
    private final List<Task> tasks = new ArrayList<>();
    private final List<TaskChoice> taskCompanies = new ArrayList<>();
    private LinearLayout bottomTabs;
    private View headerRefresh;
    private FrameLayout headerAttention;
    private TextView headerAttentionBadge;
    private boolean attentionLoading;
    private AlertDialog attentionDialog;
    private AnchoredMenu accountMenu;
    private AnchoredMenu orderCompanyMenu;
    private AnchoredMenu chatCompanyMenu;
    private AnchoredMenu roomActionMenu;
    private JSONObject profileSnapshot;
    private AlertDialog profileDialog;
    private AlertDialog groupCreateDialog;
    private AlertDialog groupInfoDialog;
    private boolean recreateForLanguage;
    private LinearLayout composerRow;
    private TextView recordingBadge;
    private long recordingStartedAt;
    private Runnable recordingTicker;
    private LinearLayout replyTray;
    private TextView replyPreview;
    private long selectedReplyMessageId;
    private FrameLayout messageFrame;
    private String visibleSection = "chats";
    private LinearLayout roomItems;
    private EditText roomSearchInput;
    private LinearLayoutManager messageLayout;
    private MessageTimelineAdapter messageAdapter;
    private TextView chatNotice;
    private TextView chatTitle;
    private EditText messageInput;
    private View sendButton;
    private Button retryButton;
    private Button resolvePendingButton;
    private Button stalePendingButton;
    private LinearLayout pendingActionsRow;
    private Button olderButton;
    private Button newerButton;
    private TextView refreshHint;
    private View roomBackButton;
    private ScrollView roomScroll;
    private RecyclerView messageScroll;
    private LinearLayout olderControl;
    private LinearLayout newerControl;
    private boolean historicalWindow;
    private boolean draftActive;
    private boolean suppressDraftChanges;
    private boolean unresolvedSendNotice;
    private AlertDialog pendingDialog;
    private Runnable draftSaveTask;
    private int epoch;
    private int webEpoch;
    private int pageEpoch;
    private boolean pageReady;
    private boolean navigationFailed;
    private boolean probing;
    private boolean submitting;
    private boolean loggingOut;
    private boolean verified;
    private boolean closed;
    private boolean recheckOnResume;
    private boolean shareUnavailablePending;
    private boolean bridgeRecoveryUsed;
    private boolean bridgeRecoveryPending;
    private Runnable bridgeNavigationTimeout;

    private static boolean isExternalShare(Intent intent) {
        return intent != null && (Intent.ACTION_SEND.equals(intent.getAction())
                || Intent.ACTION_SEND_MULTIPLE.equals(intent.getAction()));
    }

    @Override protected void attachBaseContext(Context base) { super.attachBaseContext(AppLocale.wrap(base)); }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        historyCache = new ConnectedHistoryCache(this);
        taskOfflineCache = new TaskOfflineCache(this);
        if (BuildConfig.BCHAT_PUSH_ENABLED) BChatPushState.observe(this, pushTokenListener);
        capturePushTarget(getIntent());
        if (!preferences().getBoolean(REMEMBER, false)) BChatPushState.clearAccount(this);
        buildScreen();
        showShareNotice(getIntent());
        if ((state != null && state.getBoolean("bchat-language-recreate", false))
                || preferences().getBoolean(REMEMBER, false)) openWeb(BRIDGE);
        else clearCookies(() -> { if (!closed) openWeb(LOGIN); });
    }

    @Override protected void onSaveInstanceState(Bundle state) {
        state.putBoolean("bchat-language-recreate", recreateForLanguage);
        super.onSaveInstanceState(state);
    }

    private SharedPreferences preferences() { return getSharedPreferences(PREFS, MODE_PRIVATE); }
    private SharedPreferences taskCreatePreferences() {
        return getSharedPreferences(TASK_CREATE_PREFS, MODE_PRIVATE);
    }
    private SharedPreferences orderCreatePreferences() {
        return getSharedPreferences(ORDER_CREATE_PREFS, MODE_PRIVATE);
    }
    private SharedPreferences orderCompanyPreferences() {
        return getSharedPreferences(ORDER_COMPANY_PREFS, MODE_PRIVATE);
    }

    private void prepareOrderCompanyAccount(AccountScope scope) {
        SharedPreferences stored = orderCompanyPreferences();
        if (!scope.key.equals(stored.getString(ORDER_COMPANY_OWNER, null)))
            stored.edit().clear().putString(ORDER_COMPANY_OWNER, scope.key).commit();
    }

    private long savedOrderCompany(AccountScope scope) {
        SharedPreferences stored = orderCompanyPreferences();
        if (!scope.key.equals(stored.getString(ORDER_COMPANY_OWNER, null))) return 0;
        long id = stored.getLong(ORDER_COMPANY_SELECTED, 0);
        if (id > 0 && v1Companies.contains(id)) return id;
        if (id != 0) stored.edit().remove(ORDER_COMPANY_SELECTED).apply();
        return 0;
    }

    private void saveOrderCompany(long companyId) {
        if (account != null && companyId > 0 && v1Companies.contains(companyId))
            orderCompanyPreferences().edit()
                    .putString(ORDER_COMPANY_OWNER, account.key)
                    .putLong(ORDER_COMPANY_SELECTED, companyId).apply();
    }

    private SharedPreferences receiptConfirmPreferences() {
        return getSharedPreferences(RECEIPT_CONFIRM_PREFS, MODE_PRIVATE);
    }
    private SharedPreferences receiptSharePreferences() {
        return getSharedPreferences(RECEIPT_SHARE_PREFS, MODE_PRIVATE);
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private LinearLayout.LayoutParams fieldSize(int top) {
        LinearLayout.LayoutParams size = new LinearLayout.LayoutParams(-1, -2);
        size.topMargin = dp(top);
        return size;
    }

    private void collapseWhenEmpty(TextView view) {
        // Keep the notice slot reserved.  A GONE/visible flip during a network
        // refresh moved the tabs and list vertically, which felt like a jump.
        view.setVisibility(View.INVISIBLE);
        view.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) { }
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {
                view.setVisibility(s == null || s.length() == 0 ? View.INVISIBLE : View.VISIBLE);
            }
            @Override public void afterTextChanged(Editable value) { }
        });
    }

    private EditText field(LinearLayout parent, int label, boolean password) {
        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setTextSize(16);
        input.setInputType(password ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD
                : InputType.TYPE_CLASS_TEXT);
        input.setHint(label);
        input.setHintTextColor(0xff64748b);
        input.setTextColor(0xff182a3b);
        input.setBackground(Ui.outline(Color.WHITE, 0xffbfd0df, 14, this));
        input.setMinHeight(dp(56));
        input.setPadding(dp(16), 0, dp(16), 0);
        input.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        input.setContentDescription(getString(label));
        parent.addView(input, fieldSize(12));
        return input;
    }

    private void buildScreen() {
        layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setBackgroundColor(Color.WHITE);
        layout.setPadding(dp(20), dp(16), dp(20), dp(16));
        layout.setLayoutDirection(AppLocale.direction(this));
        status = new TextView(this);
        status.setTextSize(14);
        status.setTextColor(0xff44566b);
        status.setText(R.string.auth_loading);
        layout.addView(status, new LinearLayout.LayoutParams(-1, -2));

        nativeForm = new ScrollView(this);
        // The credentials occupy their natural height. A full-height child left an empty
        // block beneath the sign-in control on some Android devices.
        nativeForm.setFillViewport(false);
        nativeForm.setVerticalScrollBarEnabled(false);
        nativeForm.setBackgroundColor(Color.WHITE);
        LinearLayout fields = new LinearLayout(this);
        fields.setOrientation(LinearLayout.VERTICAL);
        fields.setGravity(Gravity.CENTER_HORIZONTAL);
        fields.setPadding(dp(12), dp(20), dp(12), dp(14));
        fields.setBackgroundColor(Color.WHITE);
        nativeForm.addView(fields, new ScrollView.LayoutParams(-1, -2));
        LoginBrandView mark = new LoginBrandView(this);
        LinearLayout.LayoutParams markSize = new LinearLayout.LayoutParams(dp(148), dp(158));
        markSize.gravity = Gravity.CENTER_HORIZONTAL;
        fields.addView(mark, markSize);
        TextView title = new TextView(this);
        title.setText(R.string.auth_native_title);
        title.setTextSize(23);
        title.setTextColor(0xff0d3f68);
        title.setGravity(Gravity.CENTER);
        fields.addView(title, fieldSize(8));
        loginInput = field(fields, R.string.auth_native_username, false);
        passwordInput = field(fields, R.string.auth_native_password, true);
        signIn = new Button(this);
        signIn.setText(R.string.auth_native_sign_in);
        styleAction(signIn, true);
        signIn.setMinHeight(dp(54));
        signIn.setEnabled(false);
        signIn.setOnClickListener(v -> submitLogin());
        fields.addView(signIn, fieldSize(12));
        layout.addView(nativeForm, new LinearLayout.LayoutParams(-1, 0, 1));
        // The installed build identity is a fixed part of the login screen, not a scrolling
        // child that can be displaced by viewport resizing or a keyboard.
        loginReleaseFooter = new TextView(this);
        loginReleaseFooter.setText(getString(R.string.bchat_login_release_footer,
                BidiFormatter.getInstance(AppLocale.rtl(this)).unicodeWrap(installedBChatReleaseName()),
                getString(R.string.bchat_login_release_date)));
        loginReleaseFooter.setTextSize(12);
        loginReleaseFooter.setTextColor(0xff64748b);
        loginReleaseFooter.setGravity(Gravity.CENTER);
        loginReleaseFooter.setTextDirection(View.TEXT_DIRECTION_FIRST_STRONG);
        loginReleaseFooter.setLayoutDirection(AppLocale.direction(this));
        loginReleaseFooter.setPadding(0, dp(4), 0, dp(4));
        LinearLayout.LayoutParams releaseFooterSize = new LinearLayout.LayoutParams(-1, -2);
        releaseFooterSize.setMargins(0, dp(4), 0, dp(8));
        layout.addView(loginReleaseFooter, releaseFooterSize);

        shell = new LinearLayout(this);
        shell.setOrientation(LinearLayout.VERTICAL);
        shell.setGravity(Gravity.CENTER);
        TextView brand = new TextView(this);
        brand.setText(R.string.auth_shell_brand);
        brand.setTextColor(0xff0d3f68);
        brand.setTextSize(28);
        brand.setGravity(Gravity.CENTER);
        shell.addView(brand, fieldSize(4));
        TextView heading = new TextView(this);
        heading.setText(R.string.auth_shell_heading);
        heading.setTextColor(0xff0d3f68);
        heading.setTextSize(20);
        heading.setGravity(Gravity.CENTER);
        shell.addView(heading, fieldSize(16));
        shellNotice = new TextView(this);
        shellNotice.setText(R.string.auth_shell_unavailable);
        shellNotice.setTextColor(0xff44566b);
        shellNotice.setTextSize(15);
        shellNotice.setGravity(Gravity.CENTER);
        shell.addView(shellNotice, fieldSize(16));
        shellRetry = new Button(this);
        shellRetry.setText(R.string.chat_v2_retry_login);
        styleAction(shellRetry, false);
        shellRetry.setVisibility(View.GONE);
        shellRetry.setOnClickListener(v -> {
            if (closed || web != null) return;
            verified = false;
            offlineHistory = false;
            bridgeRecoveryUsed = false;
            shell.setVisibility(View.GONE);
            status.setVisibility(View.VISIBLE);
            status.setText(R.string.auth_verifying);
            openWeb(BRIDGE);
        });
        shell.addView(shellRetry, fieldSize(8));
        Button signOut = new Button(this);
        signOut.setText(R.string.auth_native_sign_out);
        Ui.styleAction(signOut, Ui.ActionTone.TEXT);
        signOut.setOnClickListener(v -> logout());
        shell.addView(signOut, fieldSize(16));
        shell.setVisibility(View.GONE);
        layout.addView(shell, new LinearLayout.LayoutParams(-1, 0, 1));

        chatRoot = new LinearLayout(this);
        chatRoot.setOrientation(LinearLayout.VERTICAL);
        chatRoot.setLayoutDirection(AppLocale.direction(this));
        chatRoot.setBackgroundColor(Ui.LIGHT);
        chatRoot.setVisibility(View.GONE);
        brandBar = Ui.row(this);
        brandBar.setLayoutDirection(View.LAYOUT_DIRECTION_LTR);
        Ui.pad(brandBar, 10, 4);
        brandBar.setBackgroundColor(Ui.NAVY);
        TextView compactBrand = Ui.text(this, "BChat", 23, Color.WHITE, true);
        compactBrand.setTextDirection(View.TEXT_DIRECTION_LTR);
        compactBrand.setLayoutDirection(View.LAYOUT_DIRECTION_LTR);
        android.text.SpannableString brandLetters = new android.text.SpannableString("BChat");
        brandLetters.setSpan(new android.text.style.ForegroundColorSpan(Ui.SKY), 0, 1,
                android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        compactBrand.setText(brandLetters);
        compactBrand.setContentDescription("BChat");
        brandBar.addView(compactBrand, new LinearLayout.LayoutParams(-2, dp(48)));
        // Keep the two fixed header actions visible on narrow phones. The company label owns
        // only the remaining width instead of growing past the bell and the account menu.
        FrameLayout headerCompanySlot = new FrameLayout(this);
        chatHeaderCompanyButton = Ui.text(this, "", 14, Color.WHITE, true);
        chatHeaderCompanyButton.setGravity(Gravity.CENTER_VERTICAL | Gravity.END);
        chatHeaderCompanyButton.setSingleLine(true);
        chatHeaderCompanyButton.setEllipsize(android.text.TextUtils.TruncateAt.END);
        chatHeaderCompanyButton.setPaddingRelative(dp(8), 0, dp(8), 0);
        chatHeaderCompanyButton.setVisibility(View.GONE);
        chatHeaderCompanyButton.setOnClickListener(v -> showChatCompanyMenu(chatHeaderCompanyButton));
        headerCompanySlot.addView(chatHeaderCompanyButton,
                new FrameLayout.LayoutParams(-1, dp(48)));
        chatCompanyMenu = new AnchoredMenu(this);
        orderHeaderCompanyButton = Ui.text(this, "", 14, Color.WHITE, true);
        orderHeaderCompanyButton.setGravity(Gravity.CENTER);
        orderHeaderCompanyButton.setSingleLine(true);
        orderHeaderCompanyButton.setEllipsize(android.text.TextUtils.TruncateAt.END);
        orderHeaderCompanyButton.setPaddingRelative(dp(8), 0, dp(8), 0);
        orderHeaderCompanyButton.setVisibility(View.GONE);
        orderHeaderCompanyButton.setOnClickListener(v -> showOrderCompanyMenu());
        headerCompanySlot.addView(orderHeaderCompanyButton,
                new FrameLayout.LayoutParams(-1, dp(48)));
        orderCompanyMenu = new AnchoredMenu(this);
        brandBar.addView(headerCompanySlot, new LinearLayout.LayoutParams(0, dp(48), 1f));
        headerRefresh = Ui.iconButton(this, "refresh", getString(R.string.chat_v2_refresh));
        headerRefresh.setOnClickListener(v -> refreshCurrentSection());
        headerAttention = Ui.iconButton(this, "bell", getString(R.string.bchat_attention));
        Ui.styleHeaderIcon(headerAttention);
        headerAttentionBadge = Ui.text(this, "", 10, Color.WHITE, true);
        headerAttentionBadge.setGravity(Gravity.CENTER);
        headerAttentionBadge.setSingleLine(true);
        headerAttentionBadge.setMinWidth(dp(18));
        headerAttentionBadge.setMinHeight(dp(18));
        headerAttentionBadge.setPadding(dp(3), 0, dp(3), 0);
        headerAttentionBadge.setBackground(Ui.bg(Ui.TASK_ACTIVE, 12, this));
        headerAttentionBadge.setVisibility(View.GONE);
        FrameLayout.LayoutParams attentionBadgeSize = new FrameLayout.LayoutParams(-2, dp(18),
                Gravity.TOP | Gravity.END);
        attentionBadgeSize.setMargins(0, dp(4), dp(3), 0);
        headerAttention.addView(headerAttentionBadge, attentionBadgeSize);
        headerAttention.setOnClickListener(v -> showAttentionCenter());
        brandBar.addView(headerAttention, new LinearLayout.LayoutParams(dp(48), dp(48)));
        View accountButton = Ui.iconButton(this, "kebab", getString(R.string.bchat_account_menu));
        Ui.styleHeaderIcon(accountButton);
        accountMenu = new AnchoredMenu(this);
        accountButton.setOnClickListener(v -> showAccountMenu(accountButton));
        brandBar.addView(accountButton, new LinearLayout.LayoutParams(dp(48), dp(48)));
        chatRoot.addView(brandBar, new LinearLayout.LayoutParams(-1, -2));

        chatPane = Ui.column(this);
        chatTitleBar = Ui.row(this);
        Ui.pad(chatTitleBar, 8, 5);
        chatTitleBar.setBackgroundColor(Ui.NAVY);
        roomBackButton = Ui.iconButton(this, "back", getString(R.string.chat_v2_back));
        Ui.styleHeaderIcon(roomBackButton);
        roomBackButton.setOnClickListener(v -> showRooms());
        chatTitleBar.addView(roomBackButton, new LinearLayout.LayoutParams(dp(48), dp(48)));
        roomAvatarSlot = new FrameLayout(this);
        roomAvatarSlot.setOnClickListener(v -> {
            if (selectedRoom != null) showGroupInfo(selectedRoom);
        });
        LinearLayout.LayoutParams avatarSlotSize = new LinearLayout.LayoutParams(dp(48), dp(48));
        avatarSlotSize.setMarginStart(dp(4));
        chatTitleBar.addView(roomAvatarSlot, avatarSlotSize);
        chatTitle = Ui.text(this, getString(R.string.chat_v2_rooms),
                Ui.CHAT_HEADER_TITLE_SP, Color.WHITE, true);
        chatTitle.setSingleLine(true);
        int roomTextGravity = chatTitleBar.getLayoutDirection() == View.LAYOUT_DIRECTION_RTL
                ? Gravity.RIGHT : Gravity.LEFT;
        chatTitle.setGravity(roomTextGravity | Gravity.CENTER_VERTICAL);
        chatTitle.setOnClickListener(v -> {
            if (selectedRoom != null) showGroupInfo(selectedRoom);
        });
        chatTitle.setEllipsize(android.text.TextUtils.TruncateAt.END);
        LinearLayout roomTitles = Ui.column(this);
        roomTitles.setGravity(Gravity.CENTER_VERTICAL);
        roomTitles.setMinimumHeight(dp(48));
        roomTitles.setPadding(0, dp(4), 0, dp(4));
        roomTitles.addView(chatTitle, new LinearLayout.LayoutParams(-1, -2));
        roomSubtitle = Ui.text(this, getString(R.string.chat_v2_room_label), 12,
                0xffd5e4ef, false);
        roomSubtitle.setSingleLine(true);
        roomSubtitle.setGravity(roomTextGravity | Gravity.CENTER_VERTICAL);
        roomSubtitle.setEllipsize(android.text.TextUtils.TruncateAt.END);
        roomTitles.addView(roomSubtitle, new LinearLayout.LayoutParams(-1, -2));
        roomTitles.setOnClickListener(v -> {
            if (selectedRoom != null) showGroupInfo(selectedRoom);
        });
        LinearLayout.LayoutParams roomTitleSize = new LinearLayout.LayoutParams(0, -2, 1);
        roomTitleSize.setMarginStart(dp(10));
        chatTitleBar.addView(roomTitles, roomTitleSize);
        roomActionMenu = new AnchoredMenu(this);
        roomTasksButton = Ui.iconButton(this, "kebab", getString(R.string.chat_v2_room_actions));
        Ui.styleHeaderIcon(roomTasksButton);
        roomTasksButton.setOnClickListener(v -> showRoomActionMenu(v));
        chatTitleBar.addView(roomTasksButton, new LinearLayout.LayoutParams(dp(48), dp(48)));
        chatPane.addView(chatTitleBar, new LinearLayout.LayoutParams(-1, -2));
        refreshHint = new TextView(this);
        refreshHint.setText(R.string.chat_v2_manual_refresh);
        refreshHint.setTextColor(Ui.MUTED);
        refreshHint.setTextSize(11);
        Ui.pad(refreshHint, 10, 3);
        refreshHint.setVisibility(View.GONE);
        chatPane.addView(refreshHint, new LinearLayout.LayoutParams(-1, -2));
        chatNotice = new TextView(this);
        chatNotice.setTextColor(Ui.GREEN);
        chatNotice.setTextSize(12);
        chatNotice.setGravity(Gravity.CENTER);
        chatNotice.setBackground(Ui.bg(Ui.ACTION_TONAL, 12, this));
        Ui.pad(chatNotice, 12, 7);
        collapseWhenEmpty(chatNotice);
        LinearLayout.LayoutParams noticeSize = new LinearLayout.LayoutParams(-1, -2);
        noticeSize.setMargins(dp(10), dp(3), dp(10), dp(3));
        chatPane.addView(chatNotice, noticeSize);
        roomListHeader = Ui.column(this);
        roomListHeader.setBackgroundColor(Color.WHITE);
        LinearLayout roomHeadingRow = Ui.row(this);
        roomHeadingRow.setGravity(Gravity.CENTER_VERTICAL);
        TextView roomsHeading = Ui.text(this, getString(R.string.chat_v2_rooms), 20,
                Ui.NAVY, true);
        roomsHeading.setSingleLine(true);
        roomsHeading.setEllipsize(android.text.TextUtils.TruncateAt.END);
        roomsHeading.setPaddingRelative(dp(12), dp(4), dp(12), dp(4));
        roomHeadingRow.addView(roomsHeading, new LinearLayout.LayoutParams(0, -2, 1));
        roomPendingButton = Ui.iconButton(this, "clock",
                getString(R.string.chat_v2_global_pending));
        Ui.styleIconAction(roomPendingButton, Ui.IconTone.TONAL);
        roomPendingButton.setTooltipText(getString(R.string.chat_v2_global_pending));
        roomPendingButton.setVisibility(View.GONE);
        roomPendingButton.setOnClickListener(v -> showGlobalPending(0));
        roomHeadingRow.addView(roomPendingButton,
                new LinearLayout.LayoutParams(dp(48), dp(48)));
        View roomSearchButton = Ui.iconButton(this, "search",
                getString(R.string.chat_v2_search_rooms));
        roomSearchButton.setOnClickListener(v -> toggleRoomSearch());
        roomHeadingRow.addView(roomSearchButton,
                new LinearLayout.LayoutParams(dp(48), dp(48)));
        createGroupButton = Ui.iconButton(this, "plus", getString(R.string.bchat_group_create));
        createGroupButton.setOnClickListener(v -> chooseGroupCompany());
        roomHeadingRow.addView(createGroupButton, new LinearLayout.LayoutParams(dp(48), dp(48)));
        roomListHeader.addView(roomHeadingRow, new LinearLayout.LayoutParams(-1, -2));
        roomSearchSurface = Ui.row(this);
        roomSearchSurface.setBackground(Ui.bg(0xfff7f8fa, 14, this));
        Ui.Icon searchIcon = new Ui.Icon(this, "search", Ui.MUTED);
        LinearLayout.LayoutParams searchIconSize = new LinearLayout.LayoutParams(dp(20), dp(20));
        searchIconSize.setMarginStart(dp(14));
        roomSearchSurface.addView(searchIcon, searchIconSize);
        roomSearchInput = new EditText(this);
        roomSearchInput.setHint(R.string.chat_v2_search_rooms);
        roomSearchInput.setTextSize(15);
        roomSearchInput.setSingleLine(true);
        roomSearchInput.setTextColor(Ui.INK);
        roomSearchInput.setHintTextColor(Ui.MUTED);
        roomSearchInput.setBackgroundColor(Color.TRANSPARENT);
        roomSearchInput.setPaddingRelative(dp(10), dp(8), dp(14), dp(8));
        roomSearchInput.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) { }
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {
                renderRooms();
            }
            @Override public void afterTextChanged(Editable value) { }
        });
        roomSearchSurface.addView(roomSearchInput, new LinearLayout.LayoutParams(0, -2, 1));
        LinearLayout.LayoutParams searchSurfaceSize = new LinearLayout.LayoutParams(-1, -2);
        searchSurfaceSize.setMargins(dp(12), 0, dp(12), dp(8));
        roomSearchSurface.setVisibility(View.GONE);
        roomListHeader.addView(roomSearchSurface, searchSurfaceSize);
        chatPane.addView(roomListHeader, new LinearLayout.LayoutParams(-1, -2));
        roomScroll = new ScrollView(this);
        roomScroll.setFillViewport(true);
        roomScroll.setBackgroundColor(Color.WHITE);
        roomItems = new LinearLayout(this);
        roomItems.setOrientation(LinearLayout.VERTICAL);
        roomScroll.addView(roomItems);
        chatPane.addView(roomScroll, new LinearLayout.LayoutParams(-1, 0, 1));
        olderButton = new Button(this);
        olderButton.setText(R.string.chat_v2_older);
        styleAction(olderButton, false);
        olderButton.setMinWidth(dp(160));
        olderButton.setMinHeight(dp(48));
        olderButton.setOnClickListener(v -> {
            if (nextBeforeId > 0 && !olderPageLoading) loadMessages(nextBeforeId);
        });
        messageFrame = new FrameLayout(this);
        messageFrame.addView(new Ui.Wallpaper(this), new FrameLayout.LayoutParams(-1, -1));
        LinearLayout threadViewport = Ui.column(this);
        olderControl = Ui.row(this);
        olderControl.setGravity(Gravity.CENTER);
        Ui.pad(olderControl, 8, 2);
        olderControl.addView(olderButton, new LinearLayout.LayoutParams(-2, dp(48)));
        olderControl.setVisibility(View.GONE);
        threadViewport.addView(olderControl, new LinearLayout.LayoutParams(-1, -2));
        messageScroll = new RecyclerView(this);
        messageLayout = new LinearLayoutManager(this);
        messageLayout.setStackFromEnd(true);
        messageScroll.setLayoutManager(messageLayout);
        messageScroll.setHasFixedSize(false);
        messageScroll.setItemAnimator(null);
        messageScroll.setClipToPadding(false);
        Ui.pad(messageScroll, 12, 12);
        messageAdapter = new MessageTimelineAdapter();
        messageScroll.setAdapter(messageAdapter);
        messageScroll.addOnScrollListener(new RecyclerView.OnScrollListener() {
            @Override public void onScrolled(@NonNull RecyclerView list, int dx, int dy) {
                updateOlderButtonAvailability();
                pumpMediaThumbnails();
                scanVisibleMessageReceipts();
                if (dy < 0) maybeLoadOlderMessages();
            }
        });
        threadViewport.addView(messageScroll, new LinearLayout.LayoutParams(-1, 0, 1));
        newerControl = Ui.row(this);
        newerControl.setGravity(Gravity.CENTER);
        Ui.pad(newerControl, 8, 2);
        newerButton = new Button(this);
        newerButton.setText(R.string.chat_v2_newer);
        styleAction(newerButton, false);
        newerButton.setMinWidth(dp(160));
        newerButton.setMinHeight(dp(48));
        newerButton.setOnClickListener(v -> showNewerMessages());
        newerControl.addView(newerButton, new LinearLayout.LayoutParams(-2, dp(48)));
        newerControl.setVisibility(View.GONE);
        threadViewport.addView(newerControl, new LinearLayout.LayoutParams(-1, -2));
        messageFrame.addView(threadViewport, new FrameLayout.LayoutParams(-1, -1));
        chatPane.addView(messageFrame, new LinearLayout.LayoutParams(-1, 0, 1));
        replyTray = Ui.row(this);
        Ui.pad(replyTray, 12, 4);
        replyTray.setBackgroundColor(Color.WHITE);
        replyPreview = Ui.text(this, "", 14, Ui.INK, false);
        replyPreview.setMaxLines(2);
        replyPreview.setEllipsize(android.text.TextUtils.TruncateAt.END);
        replyTray.addView(replyPreview, new LinearLayout.LayoutParams(0, -2, 1));
        Button cancelReply = new Button(this);
        cancelReply.setText(R.string.chat_v2_cancel_reply);
        styleAction(cancelReply, false);
        cancelReply.setOnClickListener(v -> clearSelectedReply());
        replyTray.addView(cancelReply, new LinearLayout.LayoutParams(-2, dp(48)));
        replyTray.setVisibility(View.GONE);
        chatPane.addView(replyTray, new LinearLayout.LayoutParams(-1, -2));
        recordingBadge = Ui.text(this, "", 13, Ui.GREEN, true);
        Ui.styleAction(recordingBadge, Ui.ActionTone.SECONDARY);
        recordingBadge.setVisibility(View.GONE);
        recordingBadge.setOnClickListener(v -> finishConnectedVoice());
        chatPane.addView(recordingBadge, new LinearLayout.LayoutParams(-1, -2));
        composerRow = Ui.row(this);
        Ui.pad(composerRow, 8, 6);
        composerRow.setBackgroundColor(Ui.CHAT_CANVAS);
        LinearLayout composerSurface = Ui.row(this);
        composerSurface.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 24, this));
        composerSurface.setMinimumHeight(dp(48));
        messageInput = new EditText(this);
        messageInput.setHint(R.string.chat_v2_compose);
        messageInput.setMinLines(1);
        messageInput.setMaxLines(4);
        messageInput.setTextSize(16);
        messageInput.setTextColor(Ui.INK);
        messageInput.setBackgroundColor(Color.TRANSPARENT);
        messageInput.setMinHeight(dp(48));
        messageInput.setPaddingRelative(dp(16), dp(8), dp(5), dp(8));
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P)
            messageInput.setLineHeight(Math.max(messageInput.getLineHeight(), dp(Ui.CHAT_TEXT_LINE_DP)));
        messageInput.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) { }
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) { }
            @Override public void afterTextChanged(Editable value) {
                Room room = selectedRoom;
                if (suppressDraftChanges || !draftActive || room == null || account == null || outbox == null)
                    return;
                scheduleDraftSave(account, room, value.toString());
            }
        });
        composerSurface.addView(messageInput, new LinearLayout.LayoutParams(0, -2, 1));
        mediaPickButton = Ui.iconButton(this, "attach", getString(R.string.bchat_media_attach));
        mediaPickButton.setVisibility(View.GONE);
        mediaPickButton.setOnClickListener(v -> chooseConnectedMedia());
        composerSurface.addView(mediaPickButton, new LinearLayout.LayoutParams(dp(48), dp(48)));
        mediaVoiceButton = Ui.iconButton(this, "mic", getString(R.string.bchat_media_record));
        mediaVoiceButton.setVisibility(View.GONE);
        mediaVoiceButton.setOnClickListener(v -> toggleConnectedVoice());
        composerSurface.addView(mediaVoiceButton, new LinearLayout.LayoutParams(dp(48), dp(48)));
        composerRow.addView(composerSurface, new LinearLayout.LayoutParams(0, -2, 1));
        retryButton = new Button(this);
        retryButton.setText("↻");
        retryButton.setContentDescription(getString(R.string.chat_v2_retry));
        styleAction(retryButton, false);
        retryButton.setOnClickListener(v -> retryPending());
        pendingActionsRow = Ui.row(this);
        Ui.pad(pendingActionsRow, 8, 0);
        pendingActionsRow.addView(retryButton, new LinearLayout.LayoutParams(dp(48), dp(48)));
        mediaReviewButton = new Button(this);
        mediaReviewButton.setText(R.string.bchat_media_review_pending);
        styleAction(mediaReviewButton, false);
        mediaReviewButton.setVisibility(View.GONE);
        mediaReviewButton.setOnClickListener(v -> reviewConnectedMedia());
        chatPane.addView(mediaReviewButton, new LinearLayout.LayoutParams(-1, dp(48)));
        resolvePendingButton = new Button(this);
        resolvePendingButton.setText(R.string.chat_v2_review_pending);
        styleAction(resolvePendingButton, false);
        resolvePendingButton.setOnClickListener(v -> reviewPending(false));
        pendingActionsRow.addView(resolvePendingButton, new LinearLayout.LayoutParams(0, dp(48), 1));
        pendingActionsRow.setVisibility(View.GONE);
        chatPane.addView(pendingActionsRow, new LinearLayout.LayoutParams(-1, dp(48)));
        stalePendingButton = new Button(this);
        stalePendingButton.setText(R.string.chat_v2_review_old_pending);
        styleAction(stalePendingButton, false);
        stalePendingButton.setOnClickListener(v -> reviewPending(true));
        chatPane.addView(stalePendingButton, new LinearLayout.LayoutParams(-1, dp(48)));
        sendButton = Ui.iconButton(this, "send", getString(R.string.chat_v2_send));
        Ui.styleIconAction(sendButton, Ui.IconTone.FILLED);
        sendButton.setOnClickListener(v -> sendText());
        LinearLayout.LayoutParams sendSize = new LinearLayout.LayoutParams(dp(48), dp(48));
        sendSize.setMarginStart(dp(2));
        composerRow.addView(sendButton, sendSize);
        chatPane.addView(composerRow, new LinearLayout.LayoutParams(-1, -2));
        chatRoot.addView(chatPane, new LinearLayout.LayoutParams(-1, 0, 1));
        modulePane = Ui.column(this);
        orderNotice = Ui.text(this, "", 14, Ui.INK, false);
        Ui.pad(orderNotice, 14, 10);
        orderNotice.setBackground(Ui.outline(0xffeaf4ff, 0xffd5e8f8, 12, this));
        orderNotice.setElevation(dp(3));
        collapseWhenEmpty(orderNotice);
        orderDetailsButton = orderChoiceButton(R.string.order_details, () ->
                orderDetailsPanel.setVisibility(orderDetailsPanel.getVisibility() == View.VISIBLE
                        ? View.GONE : View.VISIBLE));
        orderDetailsButton.setSingleLine(true);
        orderDetailsButton.setEllipsize(android.text.TextUtils.TruncateAt.END);
        orderDetailsButton.setText("⋮");
        orderDetailsButton.setTextSize(20);
        orderDetailsButton.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 12, this));
        orderDetailsButton.setContentDescription(getString(R.string.order_details));
        orderDetailsPanel = Ui.column(this);
        Ui.pad(orderDetailsPanel, 6, 6);
        orderDetailsPanel.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 14, this));
        orderWarehouseButton = orderChoiceButton(R.string.order_choose_warehouse, () ->
                chooseOrderChoice(orderWarehouses, R.string.order_choose_warehouse,
                        choice -> { if (orderWarehouseId != choice.id) {
                                orderWarehouseId = choice.id; invalidateOrderQuote();
                            }
                            orderDetailsPanel.setVisibility(View.GONE);
                            updateOrderSelectors(); }));
        orderDetailsPanel.addView(orderWarehouseButton, fieldSize(4));
        orderRepresentativeButton = orderChoiceButton(R.string.order_choose_representative, () ->
                chooseOrderChoice(orderRepresentatives, R.string.order_choose_representative,
                        choice -> { orderRepresentativeId = choice.id; orderDetailsPanel.setVisibility(View.GONE);
                            updateOrderSelectors(); }));
        orderDetailsPanel.addView(orderRepresentativeButton, fieldSize(4));
        orderDetailsPanel.setVisibility(View.GONE);
        LinearLayout orderTabs = Ui.row(this);
        Ui.pad(orderTabs, 8, 2);
        orderCatalogButton = orderChoiceButton(R.string.order_catalog, () -> showOrderMode(false));
        orderMineButton = orderChoiceButton(R.string.order_mine, () -> showOrderMode(true));
        orderReceiptButton = orderChoiceButton(R.string.receipt_tab, this::showReceiptMode);
        LinearLayout orderSegments = Ui.row(this);
        orderSegments.setBackgroundColor(Color.WHITE);
        orderCatalogLine = addOrderTab(orderSegments, orderCatalogButton);
        orderMineLine = addOrderTab(orderSegments, orderMineButton);
        orderReceiptLine = addOrderTab(orderSegments, orderReceiptButton);
        orderTabs.addView(orderSegments, new LinearLayout.LayoutParams(0, -2, 1));
        modulePane.addView(orderTabs);
        LinearLayout.LayoutParams detailsSize = new LinearLayout.LayoutParams(-1, -2);
        detailsSize.setMargins(dp(8), 0, dp(8), dp(4));
        modulePane.addView(orderDetailsPanel, detailsSize);
        orderSearch = new EditText(this);
        orderSearch.setSingleLine(true);
        orderSearch.setHint(R.string.order_search);
        orderSearch.setInputType(InputType.TYPE_CLASS_TEXT);
        orderSearch.setTextSize(15);
        Ui.pad(orderSearch, 14, 7);
        orderSearch.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) { }
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) { }
            @Override public void afterTextChanged(Editable value) {
                if (orderSearchTask != null) handler.removeCallbacks(orderSearchTask);
                if (!ordersAvailable || orderMine || orderReceiving) return;
                prepareOrderContent(orderContentKey("catalog", orderCompanyId,
                        orderCategoryId, value.toString().trim(), 0));
                orderSearchTask = () -> { orderSearchTask = null; loadOrderCatalog(0); };
                handler.postDelayed(orderSearchTask, 350);
            }
        });
        orderCategoryButton = orderChoiceButton(R.string.order_all_categories, this::chooseOrderCategory);
        orderCategoryButton.setSingleLine(true);
        orderCategoryButton.setEllipsize(android.text.TextUtils.TruncateAt.END);
        orderCategoryButton.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 12, this));
        orderFiltersRow = Ui.row(this);
        Ui.pad(orderFiltersRow, 6, 2);
        orderSearch.setMinHeight(dp(48));
        orderSearch.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 12, this));
        orderFiltersRow.addView(orderSearch, new LinearLayout.LayoutParams(0, dp(48), 1));
        LinearLayout.LayoutParams categorySize = new LinearLayout.LayoutParams(dp(106), dp(48));
        categorySize.setMarginStart(dp(4));
        orderFiltersRow.addView(orderCategoryButton, categorySize);
        LinearLayout.LayoutParams optionsSize = new LinearLayout.LayoutParams(dp(48), dp(48));
        optionsSize.setMarginStart(dp(4));
        orderFiltersRow.addView(orderDetailsButton, optionsSize);
        modulePane.addView(orderFiltersRow);
        orderScroll = new ScrollView(this);
        orderScroll.setOnScrollChangeListener((v, x, y, oldX, oldY) ->
                scheduleOrderImagePump());
        orderItems = Ui.column(this);
        orderItems.setBackgroundColor(Color.WHITE);
        orderItems.addOnLayoutChangeListener((v, left, top, right, bottom,
                oldLeft, oldTop, oldRight, oldBottom) -> scheduleOrderImagePump());
        orderScroll.addView(orderItems);
        FrameLayout orderContent = new FrameLayout(this);
        orderContent.addView(orderScroll, new FrameLayout.LayoutParams(-1, -1));
        FrameLayout.LayoutParams orderNoticeSize = new FrameLayout.LayoutParams(-1, -2, Gravity.TOP);
        orderNoticeSize.setMargins(dp(12), dp(8), dp(12), 0);
        orderContent.addView(orderNotice, orderNoticeSize);
        modulePane.addView(orderContent, new LinearLayout.LayoutParams(-1, 0, 1));
        orderOlderButton = orderChoiceButton(R.string.order_older, () -> {
            if (orderReceiving) loadReceipts(receiptBeforeId);
            else if (orderMine) loadOrderSummaries(orderListBeforeId);
            else loadOrderCatalog(orderCatalogAfterId);
        });
        orderPreviousButton = orderChoiceButton(R.string.order_previous_products, () -> {
            if (!orderMine && !orderReceiving && !orderPageHistory.isEmpty())
                loadOrderCatalog(orderPageHistory.get(orderPageHistory.size() - 1), -1);
        });
        orderPagingRow = Ui.row(this);
        orderPagingRow.addView(orderPreviousButton, new LinearLayout.LayoutParams(0, dp(48), 1));
        orderPagingRow.addView(orderOlderButton, new LinearLayout.LayoutParams(0, dp(48), 1));
        orderItems.addView(orderPagingRow);
        orderPreviousButton.setVisibility(View.GONE);
        orderOlderButton.setVisibility(View.GONE);
        orderCartButton = orderChoiceButton(R.string.order_cart, this::reviewOrderCart);
        orderCartBar = Ui.row(this);
        orderCartBar.setGravity(Gravity.CENTER_VERTICAL);
        Ui.pad(orderCartBar, 12, 6);
        orderCartBar.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 0, this));
        orderCartSummary = Ui.text(this, "", 14, Ui.INK, true);
        orderCartSummary.setMaxLines(2);
        orderCartSummary.setEllipsize(android.text.TextUtils.TruncateAt.END);
        orderCartBar.addView(orderCartSummary, new LinearLayout.LayoutParams(0, -2, 1));
        orderCartButton.setText(R.string.order_view_cart);
        Ui.styleAction(orderCartButton, Ui.ActionTone.PRIMARY);
        LinearLayout.LayoutParams cartActionSize = new LinearLayout.LayoutParams(-2, dp(48));
        cartActionSize.setMarginStart(dp(10));
        orderCartBar.addView(orderCartButton, cartActionSize);
        modulePane.addView(orderCartBar);
        orderPendingButton = orderChoiceButton(R.string.order_review_pending, this::reviewPendingOrder);
        modulePane.addView(orderPendingButton, new LinearLayout.LayoutParams(-1, dp(48)));
        orderPendingButton.setVisibility(View.GONE);
        receiptPendingButton = orderChoiceButton(R.string.receipt_review_pending,
                this::reviewPendingReceipt);
        modulePane.addView(receiptPendingButton, new LinearLayout.LayoutParams(-1, dp(48)));
        receiptPendingButton.setVisibility(View.GONE);
        receiptSharePendingButton = orderChoiceButton(R.string.receipt_share_review_pending,
                this::reviewPendingReceiptShares);
        modulePane.addView(receiptSharePendingButton, new LinearLayout.LayoutParams(-1, dp(48)));
        receiptSharePendingButton.setVisibility(View.GONE);
        modulePane.setVisibility(View.GONE);
        chatRoot.addView(modulePane, new LinearLayout.LayoutParams(-1, 0, 1));
        taskPane = Ui.column(this);
        taskHeading = Ui.text(this, getString(R.string.chat_v2_tasks), 19, Ui.INK, true);
        Ui.pad(taskHeading, 12, 4);
        taskHeading.setVisibility(View.GONE);
        taskPane.addView(taskHeading);
        taskNotice = Ui.text(this, "", 14, Ui.INK, false);
        Ui.pad(taskNotice, 12, 4);
        collapseWhenEmpty(taskNotice);
        taskPane.addView(taskNotice);
        LinearLayout taskTabs = Ui.row(this);
        Ui.pad(taskTabs, 8, 2);
        LinearLayout taskSegments = Ui.row(this);
        taskSegments.setBackgroundColor(Color.WHITE);
        taskAllButton = orderChoiceButton(R.string.task_tab_closed, () -> selectTaskState("cancelled"));
        taskOpenButton = orderChoiceButton(R.string.task_tab_open, () -> selectTaskState("open"));
        taskDoneButton = orderChoiceButton(R.string.task_tab_done, () -> selectTaskState("done"));
        taskAllLine = addOrderTab(taskSegments, taskAllButton);
        taskOpenLine = addOrderTab(taskSegments, taskOpenButton);
        taskDoneLine = addOrderTab(taskSegments, taskDoneButton);
        taskTabs.addView(taskSegments, new LinearLayout.LayoutParams(0, -2, 1));
        taskPane.addView(taskTabs);
        taskNewButton = new Button(this);
        taskNewButton.setText(R.string.task_new);
        Ui.styleAction(taskNewButton, Ui.ActionTone.PRIMARY);
        taskNewButton.setOnClickListener(v -> createTaskDialog());
        LinearLayout taskActions = Ui.row(this);
        Ui.pad(taskActions, 6, 4);
        taskActions.addView(taskNewButton, new LinearLayout.LayoutParams(-1, dp(48)));
        taskPane.addView(taskActions);
        taskPendingButton = new Button(this);
        taskPendingButton.setText(R.string.task_review_pending);
        Ui.styleAction(taskPendingButton, Ui.ActionTone.SECONDARY);
        taskPendingButton.setVisibility(View.GONE);
        taskPendingButton.setOnClickListener(v -> reviewPendingTaskCreate());
        taskPane.addView(taskPendingButton, fieldSize(4));
        ScrollView taskScroll = new ScrollView(this);
        taskScroll.setFillViewport(true);
        taskItems = Ui.column(this);
        taskItems.setBackgroundColor(Color.WHITE);
        taskScroll.addView(taskItems);
        taskPane.addView(taskScroll, new LinearLayout.LayoutParams(-1, 0, 1));
        taskOlderButton = new Button(this);
        taskOlderButton.setText(R.string.task_older);
        Ui.styleAction(taskOlderButton, Ui.ActionTone.SECONDARY);
        taskOlderButton.setOnClickListener(v -> loadTasks(taskBeforeId));
        taskPane.addView(taskOlderButton, new LinearLayout.LayoutParams(-1, dp(48)));
        taskPane.setVisibility(View.GONE);
        chatRoot.addView(taskPane, new LinearLayout.LayoutParams(-1, 0, 1));
        bottomTabs = Ui.row(this);
        Ui.pad(bottomTabs, 6, 0);
        bottomTabs.setTag("bchat-bottom-navigation");
        bottomTabs.setBackgroundColor(Color.WHITE);
        chatRoot.addView(Ui.line(this));
        chatRoot.addView(bottomTabs, new LinearLayout.LayoutParams(-1, -2));
        layout.addView(chatRoot, new LinearLayout.LayoutParams(-1, 0, 1));
        showRooms();
        renderBottomTabs();

        localExit = new Button(this);
        localExit.setText(R.string.auth_local_exit);
        Ui.styleAction(localExit, Ui.ActionTone.TEXT);
        localExit.setVisibility(View.GONE);
        localExit.setOnClickListener(v -> {
            purgeHistory();
            ++epoch;
            loggingOut = false;
            verified = false;
            preferences().edit().putBoolean(REMEMBER, false).apply();
            clearCookies(() -> {
                if (closed) return;
                showLoginForm();
                openWeb(LOGIN);
                status.setText(R.string.auth_logout_unconfirmed);
            });
        });
        layout.addView(localExit, new LinearLayout.LayoutParams(-1, -2));
        setContentView(layout);
    }

    private void styleAction(Button button, boolean primary) {
        Ui.styleAction(button, primary ? Ui.ActionTone.PRIMARY : Ui.ActionTone.SECONDARY);
    }

    private void refreshCurrentSection() {
        if (offlineHistory) { retryOnlineSession(); return; }
        if (!verified || v2Busy) return;
        if ("orders".equals(visibleSection)) {
            if (orderMine) {
                allOrdersRecoveryAttempted = false;
                if (ordersAvailable) loadOrderSummaries(0);
                else { ordersDenied = false; discoverOrders(); }
            }
            else if (orderCompanyId == 0) {
                deniedOrderCompanyIds.clear();
                ordersDenied = false;
                discoverOrders();
            }
            else if (!ordersAvailable) discoverOrders();
            else if (orderReceiving) loadReceipts(0);
            else if (orderMine) loadOrderSummaries(0);
            else {
                loadOrderCatalog(0);
                if (!orderCart.isEmpty()) {
                    orderQuoteTotal = orderQuoteCurrency = null;
                    orderQuoteLoading = true;
                    refreshOrderQuoteLabels();
                    scheduleOrderQuote();
                }
            }
        } else if ("tasks".equals(visibleSection)) {
            if (tasksAvailable) loadTasks(0);
            else discoverTasks();
        } else if (selectedRoom == null) loadRooms();
        else loadMessages(0);
    }

    private void showAccountMenu(View anchor) {
        if ((!verified && !offlineHistory) || account == null || accountMenu == null) return;
        if (orderCompanyMenu != null) orderCompanyMenu.dismiss();
        final AccountScope scopedAccount = account;
        accountMenu.show(anchor, getString(R.string.bchat_account_menu),
                () -> (verified || offlineHistory) && account == scopedAccount
                        && chatRoot.getVisibility() == View.VISIBLE,
                offlineHistory ? offlineAccountEntries() : accountRootEntries());
    }

    private void showRoomActionMenu(View anchor) {
        final Room room = selectedRoom;
        final AccountScope scopedAccount = account;
        if (!verified || room == null || scopedAccount == null || roomActionMenu == null) return;
        List<AnchoredMenu.Entry> entries = new ArrayList<>();
        entries.add(AnchoredMenu.Entry.action(getString(room.isGroup
                ? R.string.bchat_group_info : R.string.bchat_room_info), "group",
                () -> showGroupInfo(room)));
        if (permissionSet.taskView)
            entries.add(AnchoredMenu.Entry.action(getString(R.string.task_room_tasks), "clock",
                    () -> openTasks(room.id)));
        entries.add(AnchoredMenu.Entry.action(getString(R.string.chat_v2_refresh), "refresh",
                this::refreshCurrentSection));
        roomActionMenu.show(anchor, getString(R.string.chat_v2_room_actions),
                () -> verified && account == scopedAccount && selectedRoom == room
                        && chatTitleBar.isShown(), entries);
    }

    private void chooseGroupCompany() {
        if (!permissionSet.groupCreate) return;
        if (!verified || offlineHistory) {
            chatNotice.setText(offlineNotice()); return;
        }
        if (account == null || v2Busy) return;
        String pending = getSharedPreferences(GROUP_CREATE_PREFS, MODE_PRIVATE)
                .getString(account.key, null);
        if (pending != null) {
            Ui.decorateDialog(new AlertDialog.Builder(this)
                    .setTitle(R.string.bchat_group_unconfirmed_title)
                    .setMessage(R.string.bchat_group_unconfirmed_explain)
                    .setPositiveButton(R.string.bchat_group_retry, (dialog, which) ->
                            submitGroupCreate(pending))
                    .setNeutralButton(R.string.bchat_group_discard, (dialog, which) -> {
                        getSharedPreferences(GROUP_CREATE_PREFS, MODE_PRIVATE).edit()
                                .remove(account.key).commit();
                        chooseGroupCompany();
                    }).setNegativeButton(R.string.chat_v2_cancel, null).show());
            return;
        }
        // The orders catalogue is optional and may not have been opened yet. The verified
        // bootstrap profile is the authoritative display source for every allowed company.
        JSONArray profileCompanies = profileSnapshot == null ? null
                : profileSnapshot.optJSONArray("companies");
        if (profileCompanies == null) {
            chatNotice.setText(R.string.bchat_profile_unavailable);
            return;
        }
        Map<Long, String> companyNames = new LinkedHashMap<>();
        for (int i = 0; i < profileCompanies.length(); i++) {
            JSONObject company = profileCompanies.optJSONObject(i);
            if (company == null) continue;
            long id = company.optLong("id");
            String name = localizedCompanyName(company);
            if (v1Companies.contains(id) && !name.isEmpty()) companyNames.put(id, name);
        }
        if (companyNames.size() != v1Companies.size()) {
            chatNotice.setText(R.string.bchat_profile_unavailable);
            return;
        }
        List<Long> companies = new ArrayList<>(companyNames.keySet());
        companies.sort(Long::compareTo);
        if (companies.size() == 1) { showGroupCreateForm(companies.get(0)); return; }
        if (companies.isEmpty()) return;
        // The header chooses the company for a new group; it never hides existing rooms.
        if (companyNames.containsKey(selectedChatCompanyId)) {
            showGroupCreateForm(selectedChatCompanyId);
            return;
        }
        String[] labels = new String[companies.size()];
        for (int i = 0; i < companies.size(); i++) labels[i] = companyNames.get(companies.get(i));
        Ui.decorateDialog(new AlertDialog.Builder(this)
                .setTitle(R.string.order_choose_company).setItems(labels,
                        (dialog, which) -> showGroupCreateForm(companies.get(which)))
                .setNegativeButton(R.string.chat_v2_cancel, null).show());
    }

    private void showGroupCreateForm(long companyId) {
        if (!verified || !v1Companies.contains(companyId)) return;
        LinearLayout content = Ui.column(this);
        Ui.pad(content, 18, 10);
        EditText name = new EditText(this);
        name.setSingleLine(true);
        name.setTextSize(16);
        name.setHint(R.string.bchat_group_name);
        content.addView(name, new LinearLayout.LayoutParams(-1, dp(52)));
        EditText description = new EditText(this);
        description.setSingleLine(false);
        description.setMinLines(2);
        description.setMaxLines(4);
        description.setTextSize(14);
        description.setHint(R.string.bchat_group_description_hint);
        content.addView(description, fieldSize(8));
        TextView membersLabel = Ui.text(this, getString(R.string.bchat_group_select_members),
                14, Ui.MUTED, false);
        content.addView(membersLabel, new LinearLayout.LayoutParams(-1, -2));
        List<TaskChoice> selected = new ArrayList<>();
        Button add = new Button(this);
        add.setText(R.string.bchat_group_add_member);
        styleAction(add, false);
        add.setOnClickListener(v -> loadGroupCandidates(companyId, "", selected,
                () -> membersLabel.setText(getString(R.string.bchat_group_selected_count,
                        selected.size()) + "\n" + groupMemberNames(selected))));
        content.addView(add, new LinearLayout.LayoutParams(-1, dp(48)));
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(R.string.bchat_group_create)
                .setView(content)
                .setPositiveButton(R.string.bchat_group_create, null)
                .setNegativeButton(R.string.chat_v2_cancel, null).create();
        groupCreateDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (groupCreateDialog == dialog) groupCreateDialog = null;
        });
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE)
                .setOnClickListener(v -> {
                    String title = name.getText().toString().trim();
                    if (title.isEmpty()) { name.setError(getString(R.string.bchat_group_name)); return; }
                    if (title.getBytes(StandardCharsets.UTF_8).length > 256) {
                        name.setError(getString(R.string.bchat_group_name_too_long)); return;
                    }
                    String details = description.getText().toString().trim();
                    if (details.getBytes(StandardCharsets.UTF_8).length > 1024) {
                        description.setError(getString(R.string.bchat_group_description_too_long)); return;
                    }
                    if (selected.isEmpty()) {
                        membersLabel.setText(R.string.bchat_group_select_members); return;
                    }
                    JSONObject payload = new JSONObject();
                    JSONArray ids = new JSONArray();
                    try {
                        for (TaskChoice member : selected) ids.put(member.id);
                        payload.put("api_version", 2);
                        payload.put("client_uuid", UUID.randomUUID().toString());
                        payload.put("company_id", companyId);
                        payload.put("name", title);
                        if (!details.isEmpty()) payload.put("description", details);
                        payload.put("member_user_ids", ids);
                    } catch (Exception invalid) { return; }
                    dialog.dismiss();
                    submitGroupCreate(payload.toString());
                }));
        dialog.show();
        Ui.decorateDialog(dialog);
    }

    private String groupMemberNames(List<TaskChoice> selected) {
        StringBuilder text = new StringBuilder();
        for (TaskChoice choice : selected) {
            if (text.length() > 0) text.append("، ");
            text.append(choice.name);
        }
        return text.toString();
    }

    private View roomAvatarView(Room room) {
        FrameLayout holder = new FrameLayout(this);
        holder.addView(new Ui.Avatar(this, room.name, "group",
                (int) ((room.id * 47) % 360)), new FrameLayout.LayoutParams(-1, -1));
        if (!verified || offlineHistory || account == null || !room.isGroup
                || room.avatarVersion <= 0) return holder;
        ImageView image = new ImageView(this);
        image.setScaleType(ImageView.ScaleType.CENTER_CROP);
        GradientDrawable circle = new GradientDrawable();
        circle.setShape(GradientDrawable.OVAL);
        circle.setColor(Ui.LIGHT);
        image.setBackground(circle);
        image.setClipToOutline(true);
        image.setVisibility(View.GONE);
        holder.addView(image, new FrameLayout.LayoutParams(-1, -1));
        String key = account.key + ":" + room.id + ":" + room.avatarVersion;
        Bitmap cached = groupAvatarCache.get(key);
        if (cached != null) {
            image.setImageBitmap(cached);
            image.setVisibility(View.VISIBLE);
        }
        else {
            List<ImageView> waiting = groupAvatarWaiting.get(key);
            if (waiting == null) {
                waiting = new ArrayList<>();
                groupAvatarWaiting.put(key, waiting);
                groupAvatarQueue.add(room);
                handler.post(this::pumpGroupAvatars);
            }
            waiting.add(image);
        }
        return holder;
    }

    private void pumpGroupAvatars() {
        if (groupAvatarBusy || groupAvatarQueue.isEmpty() || !verified || account == null
                || web == null || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl())))
            return;
        Room room = groupAvatarQueue.removeFirst();
        AccountScope scoped = account;
        int version = room.avatarVersion;
        String key = scoped.key + ":" + room.id + ":" + version;
        if (!groupAvatarWaiting.containsKey(key)) { handler.post(this::pumpGroupAvatars); return; }
        groupAvatarBusy = true;
        String path = V2_ROOMS + "/" + room.id + "/avatar?version=" + version;
        String url = ORIGIN + path;
        int currentWeb = webEpoch;
        int currentPage = pageEpoch;
        int request = ++groupAvatarNonce;
        WebMessagePort[] channel = web.createWebMessageChannel();
        groupAvatarPort = channel[0];
        groupAvatarPort.setWebMessageCallback(new WebMessagePort.WebMessageCallback() {
            @Override public void onMessage(WebMessagePort port, WebMessage message) {
                if (request != groupAvatarNonce || port != groupAvatarPort
                        || !verified || account != scoped || currentWeb != webEpoch
                        || currentPage != pageEpoch || room.avatarVersion != version) return;
                String encoded = null;
                try {
                    String data = message.getData();
                    if (data != null && data.length() <= 360000) {
                        JSONObject response = new JSONObject(data);
                        if (response.getInt("nonce") == request && response.getInt("status") == 200
                                && url.equals(response.getString("url"))
                                && "image/png".equals(response.getString("type")))
                            encoded = response.getString("body");
                    }
                } catch (Exception ignored) { }
                if (encoded == null) { finishGroupAvatar(key, null, request); return; }
                String safe = encoded;
                mediaIo.execute(() -> {
                    Bitmap bitmap = null;
                    try {
                        byte[] bytes = Base64.decode(safe, Base64.DEFAULT);
                        if (bytes.length > 0 && bytes.length <= 262144)
                            bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.length);
                        if (bitmap != null && (bitmap.getWidth() > 256 || bitmap.getHeight() > 256))
                            bitmap = null;
                    } catch (Exception ignored) { }
                    Bitmap ready = bitmap;
                    handler.post(() -> finishGroupAvatar(key, ready, request));
                });
            }
        });
        String script = "(function(){var h=function(e){var p=e.ports&&e.ports[0];"
                + "if(!p||e.data!=='group-avatar')return;window.removeEventListener('message',h);"
                + "var u=new URL(" + JSONObject.quote(path) + ",location.origin);"
                + "if(location.href!==" + JSONObject.quote(BRIDGE)
                + "||u.origin!==location.origin){p.postMessage('{}');return;}"
                + "fetch(u.href,{credentials:'same-origin',redirect:'manual',cache:'no-store'})"
                + ".then(function(r){if(r.status!==200||r.url!==u.href||"
                + "(r.headers.get('content-type')||'').split(';')[0]!=='image/png')throw Error('image');"
                + "return r.arrayBuffer();}).then(function(raw){if(!raw||raw.byteLength>262144)throw Error('size');"
                + "var bytes=new Uint8Array(raw),parts=[];for(var i=0;i<bytes.length;i+=8192)"
                + "parts.push(String.fromCharCode.apply(null,bytes.subarray(i,i+8192)));"
                + "p.postMessage(JSON.stringify({nonce:" + request
                + ",status:200,url:u.href,type:'image/png',body:btoa(parts.join(''))}));})"
                + ".catch(function(){p.postMessage('{}');});};"
                + "window.addEventListener('message',h);})();";
        web.evaluateJavascript(script, ignored -> {
            if (request == groupAvatarNonce && web != null && currentWeb == webEpoch
                    && currentPage == pageEpoch && groupAvatarPort == channel[0])
                web.postWebMessage(new WebMessage("group-avatar",
                        new WebMessagePort[]{channel[1]}), Uri.parse(ORIGIN));
        });
        handler.postDelayed(() -> {
            if (request == groupAvatarNonce && groupAvatarBusy)
                finishGroupAvatar(key, null, request);
        }, 12000);
    }

    private void finishGroupAvatar(String key, Bitmap bitmap, int request) {
        if (request != groupAvatarNonce) return;
        ++groupAvatarNonce;
        if (groupAvatarPort != null) { groupAvatarPort.close(); groupAvatarPort = null; }
        List<ImageView> waiting = groupAvatarWaiting.remove(key);
        if (bitmap != null && waiting != null && verified && account != null
                && key.startsWith(account.key + ":")) {
            groupAvatarCache.put(key, bitmap);
            for (ImageView target : waiting) {
                target.setImageBitmap(bitmap);
                target.setVisibility(View.VISIBLE);
            }
        }
        groupAvatarBusy = false;
        handler.post(this::pumpGroupAvatars);
    }

    /** Builds an image slot with initials underneath; image access is never public. */
    private View privateAvatarView(String key, String path, String name, int hue) {
        FrameLayout holder = new FrameLayout(this);
        holder.addView(new Ui.Avatar(this, name, "employee", hue),
                new FrameLayout.LayoutParams(-1, -1));
        if (!verified || offlineHistory || account == null) return holder;
        ImageView image = new ImageView(this);
        image.setScaleType(ImageView.ScaleType.CENTER_CROP);
        GradientDrawable circle = new GradientDrawable();
        circle.setShape(GradientDrawable.OVAL);
        circle.setColor(Ui.LIGHT);
        image.setBackground(circle);
        image.setClipToOutline(true);
        image.setVisibility(View.GONE);
        image.setTag(key);
        holder.addView(image, new FrameLayout.LayoutParams(-1, -1));
        Bitmap cached = privateAvatarCache.get(key);
        if (cached != null) {
            image.setImageBitmap(cached);
            image.setVisibility(View.VISIBLE);
        } else {
            List<ImageView> waiting = privateAvatarWaiting.get(key);
            if (waiting == null) {
                waiting = new ArrayList<>();
                privateAvatarWaiting.put(key, waiting);
                privateAvatarQueue.add(new PrivateAvatarRequest(key, path));
                handler.post(this::pumpPrivateAvatars);
            }
            waiting.add(image);
        }
        return holder;
    }

    private void pumpPrivateAvatars() {
        if (privateAvatarBusy || privateAvatarQueue.isEmpty() || !verified || account == null
                || web == null || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl()))) return;
        PrivateAvatarRequest item = privateAvatarQueue.removeFirst();
        AccountScope scoped = account;
        if (!privateAvatarWaiting.containsKey(item.key)) { handler.post(this::pumpPrivateAvatars); return; }
        privateAvatarBusy = true;
        String url = ORIGIN + item.path;
        int currentWeb = webEpoch;
        int currentPage = pageEpoch;
        int request = ++privateAvatarNonce;
        WebMessagePort[] channel = web.createWebMessageChannel();
        privateAvatarPort = channel[0];
        privateAvatarPort.setWebMessageCallback(new WebMessagePort.WebMessageCallback() {
            @Override public void onMessage(WebMessagePort port, WebMessage message) {
                if (request != privateAvatarNonce || port != privateAvatarPort || !verified
                        || account != scoped || currentWeb != webEpoch || currentPage != pageEpoch) return;
                String encoded = null;
                try {
                    String data = message.getData();
                    if (data != null && data.length() <= 360000) {
                        JSONObject response = new JSONObject(data);
                        if (response.getInt("nonce") == request && response.getInt("status") == 200
                                && url.equals(response.getString("url"))
                                && "image/png".equals(response.getString("type")))
                            encoded = response.getString("body");
                    }
                } catch (Exception ignored) { }
                if (encoded == null) { finishPrivateAvatar(item.key, null, request); return; }
                String safe = encoded;
                mediaIo.execute(() -> {
                    Bitmap bitmap = null;
                    try {
                        byte[] bytes = Base64.decode(safe, Base64.DEFAULT);
                        if (bytes.length > 0 && bytes.length <= MAX_PRIVATE_AVATAR_BYTES)
                            bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.length);
                        if (bitmap != null && (bitmap.getWidth() > 128 || bitmap.getHeight() > 128))
                            bitmap = null;
                    } catch (Exception ignored) { }
                    Bitmap ready = bitmap;
                    handler.post(() -> finishPrivateAvatar(item.key, ready, request));
                });
            }
        });
        String script = "(function(){var h=function(e){var p=e.ports&&e.ports[0];"
                + "if(!p||e.data!=='private-avatar')return;window.removeEventListener('message',h);"
                + "var u=new URL(" + JSONObject.quote(item.path) + ",location.origin);"
                + "if(location.href!==" + JSONObject.quote(BRIDGE)
                + "||u.origin!==location.origin){p.postMessage('{}');return;}"
                + "fetch(u.href,{credentials:'same-origin',redirect:'manual',cache:'no-store'})"
                + ".then(function(r){if(r.status!==200||r.url!==u.href||"
                + "(r.headers.get('content-type')||'').split(';')[0]!=='image/png')throw Error('image');"
                + "return r.arrayBuffer();}).then(function(raw){if(!raw||raw.byteLength>"
                + MAX_PRIVATE_AVATAR_BYTES + ")throw Error('size');var bytes=new Uint8Array(raw),parts=[];"
                + "for(var i=0;i<bytes.length;i+=8192)parts.push(String.fromCharCode.apply(null,bytes.subarray(i,i+8192)));"
                + "p.postMessage(JSON.stringify({nonce:" + request
                + ",status:200,url:u.href,type:'image/png',body:btoa(parts.join(''))}));})"
                + ".catch(function(){p.postMessage('{}');});};window.addEventListener('message',h);})();";
        web.evaluateJavascript(script, ignored -> {
            if (request == privateAvatarNonce && web != null && currentWeb == webEpoch
                    && currentPage == pageEpoch && privateAvatarPort == channel[0])
                web.postWebMessage(new WebMessage("private-avatar",
                        new WebMessagePort[]{channel[1]}), Uri.parse(ORIGIN));
        });
        handler.postDelayed(() -> {
            if (request == privateAvatarNonce && privateAvatarBusy)
                finishPrivateAvatar(item.key, null, request);
        }, 12000);
    }

    private void finishPrivateAvatar(String key, Bitmap bitmap, int request) {
        if (request != privateAvatarNonce) return;
        ++privateAvatarNonce;
        if (privateAvatarPort != null) { privateAvatarPort.close(); privateAvatarPort = null; }
        List<ImageView> waiting = privateAvatarWaiting.remove(key);
        if (bitmap != null && waiting != null && verified && account != null
                && key.startsWith(account.key + ":")) {
            privateAvatarCache.put(key, bitmap);
            for (ImageView target : waiting) {
                if (key.equals(target.getTag())) {
                    target.setImageBitmap(bitmap);
                    target.setVisibility(View.VISIBLE);
                }
            }
        }
        privateAvatarBusy = false;
        handler.post(this::pumpPrivateAvatars);
    }

    private void searchGroupMember(long companyId, List<TaskChoice> selected,
                                   Runnable afterSelect) {
        EditText search = new EditText(this);
        search.setSingleLine(true);
        search.setTextSize(16);
        search.setHint(R.string.bchat_group_search_member);
        Ui.decorateDialog(new AlertDialog.Builder(this)
                .setTitle(R.string.bchat_group_add_member)
                .setView(search)
                .setPositiveButton(R.string.bchat_group_search, (dialog, which) ->
                        loadGroupCandidates(companyId, search.getText().toString(), selected,
                                afterSelect))
                .setNegativeButton(R.string.chat_v2_cancel, null).show());
    }

    private void loadGroupCandidates(long companyId, String query,
                                     List<TaskChoice> selected, Runnable afterSelect) {
        if (!verified || account == null || v2Busy || !v1Companies.contains(companyId)) return;
        String path = "/bchat/api/v2/member-candidates?company_id=" + companyId
                + "&q=" + Uri.encode(query.trim());
        final AccountScope scoped = account;
        fetchV2("GET", path, null, (status, result) -> {
            if (handleGroupRouteFailure(status, false)) return;
            if (!verified || account != scoped) return;
            try {
                if (status != 200 || result == null || result.getInt("api_version") != 2)
                    throw new IllegalArgumentException();
                JSONArray users = result.getJSONArray("users");
                if (users.length() > 40) throw new IllegalArgumentException();
                List<TaskChoice> candidates = new ArrayList<>();
                for (int i = 0; i < users.length(); i++) {
                    JSONObject user = users.getJSONObject(i);
                    long id = positiveId(user.get("user_id"));
                    if (id == scoped.userId) continue;
                    boolean already = false;
                    for (TaskChoice member : selected) if (member.id == id) already = true;
                    if (!already) candidates.add(new TaskChoice(id, user.getString("name")));
                }
                if (candidates.isEmpty()) {
                    Ui.decorateDialog(new AlertDialog.Builder(this)
                            .setMessage(R.string.bchat_group_no_candidates)
                            .setNeutralButton(R.string.bchat_group_search, (dialog, which) ->
                                    searchGroupMember(companyId, selected, afterSelect))
                            .setPositiveButton(R.string.bchat_group_ok, null).show());
                    return;
                }
                String[] labels = new String[candidates.size()];
                for (int i = 0; i < labels.length; i++) labels[i] = candidates.get(i).name;
                Ui.decorateDialog(new AlertDialog.Builder(this)
                        .setTitle(R.string.bchat_group_select_members)
                        .setItems(labels, (dialog, which) -> {
                            boolean includesSelf = false;
                            for (TaskChoice member : selected)
                                if (member.id == scoped.userId) includesSelf = true;
                            if (selected.size() >= (includesSelf ? 50 : 49)) return;
                            selected.add(candidates.get(which));
                            afterSelect.run();
                        }).setNeutralButton(R.string.bchat_group_search, (dialog, which) ->
                                searchGroupMember(companyId, selected, afterSelect))
                        .setNegativeButton(R.string.chat_v2_cancel, null).show());
            } catch (Exception invalid) { chatNotice.setText(R.string.bchat_group_failed); }
        });
    }

    private void submitGroupCreate(String raw) {
        if (!permissionSet.groupCreate || !verified || account == null || v2Busy) return;
        final AccountScope scoped = account;
        if (!getSharedPreferences(GROUP_CREATE_PREFS, MODE_PRIVATE).edit()
                .putString(scoped.key, raw).commit()) {
            chatNotice.setText(R.string.chat_v2_save_failed);
            return;
        }
        fetchV2("POST", V2_ROOMS, raw, (status, result) -> {
            if (handleGroupRouteFailure(status, true)) return;
            if (!verified || account != scoped) return;
            try {
                if (status != 200 || result == null || result.getInt("api_version") != 2
                        || positiveId(result.get("room_id")) <= 0)
                    throw new IllegalArgumentException();
                getSharedPreferences(GROUP_CREATE_PREFS, MODE_PRIVATE).edit()
                        .remove(scoped.key).commit();
                loadRooms();
            } catch (Exception invalid) {
                if (status >= 400 && status < 500)
                    getSharedPreferences(GROUP_CREATE_PREFS, MODE_PRIVATE).edit()
                            .remove(scoped.key).commit();
                chatNotice.setText(status == 0 ? R.string.bchat_group_unconfirmed_title
                        : R.string.bchat_group_failed);
            }
        });
    }

    private Room currentGroupRoom(Room candidate) {
        if (candidate == null || !candidate.isGroup) return null;
        for (Room current : rooms)
            if (current.isGroup && current.sameMembership(candidate)) return current;
        return null;
    }

    private Room currentInfoRoom(Room candidate) {
        if (candidate == null) return null;
        for (Room current : rooms)
            if (current.sameMembership(candidate)) return current;
        return null;
    }

    private void showGroupInfo(Room room) {
        if (!verified || account == null || v2Busy || room == null
                || currentInfoRoom(room) == null) return;
        final AccountScope scoped = account;
        fetchV2("GET", V2_ROOMS + "/" + room.id + "/group", null, (status, result) -> {
            if (handleGroupRouteFailure(status, false)) return;
            if (!verified || account != scoped || currentInfoRoom(room) == null) return;
            try {
                if (status != 200 || result == null || result.getInt("api_version") != 2
                        || positiveId(result.getJSONObject("room").get("id")) != room.id)
                    throw new IllegalArgumentException();
                JSONArray members = result.getJSONArray("members");
                if (members.length() > 50) throw new IllegalArgumentException();
                boolean managedGroup = result.getJSONObject("room").getBoolean("is_group");
                if (managedGroup != room.isGroup) throw new IllegalArgumentException();
                boolean canManage = permissionSet.groupManage && managedGroup
                        && result.getBoolean("can_manage");
                showGroupInfoPage(room, result.getJSONObject("room"), members, canManage);
            } catch (Exception invalid) {
                if (status == 403 || status == 409) loadRooms();
                else chatNotice.setText(R.string.bchat_group_failed);
            }
        });
    }

    private String groupCompanyName(long id) {
        JSONArray companies = profileSnapshot == null ? null : profileSnapshot.optJSONArray("companies");
        if (companies != null) for (int i = 0; i < companies.length(); i++) {
            JSONObject company = companies.optJSONObject(i);
            if (company != null && company.optLong("id") == id)
                return localizedCompanyName(company);
        }
        return getString(R.string.bchat_group_company_id, id);
    }

    private View groupInfoAction(int label, Runnable action) {
        LinearLayout row = Ui.row(this);
        row.setMinimumHeight(dp(48));
        row.setBackground(Ui.bg(Ui.SURFACE, 12, this));
        Ui.pad(row, 16, 8);
        TextView title = Ui.text(this, getString(label), 15,
                label == R.string.bchat_group_leave ? Color.rgb(171, 56, 54) : Ui.INK, false);
        row.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        TextView indicator = Ui.text(this,
                AppLocale.direction(this) == View.LAYOUT_DIRECTION_RTL ? "‹" : "›",
                21, Ui.MUTED, false);
        indicator.setGravity(Gravity.CENTER);
        indicator.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        row.addView(indicator, new LinearLayout.LayoutParams(dp(24), dp(32)));
        row.setContentDescription(getString(label));
        Ui.clickable(row);
        row.setOnClickListener(view -> {
            if (groupInfoDialog != null) groupInfoDialog.dismiss();
            action.run();
        });
        return row;
    }

    private void showGroupInfoPage(Room room, JSONObject details, JSONArray members,
                                   boolean canManage) {
        if (groupInfoDialog != null) groupInfoDialog.dismiss();
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout content = Ui.column(this);
        content.setBackgroundColor(Ui.LIGHT);
        Ui.pad(content, 12, 18);
        scroll.addView(content);
        FrameLayout avatar = (FrameLayout) roomAvatarView(room);
        LinearLayout.LayoutParams avatarSize = new LinearLayout.LayoutParams(dp(88), dp(88));
        avatarSize.gravity = Gravity.CENTER_HORIZONTAL;
        content.addView(avatar, avatarSize);
        TextView title = Ui.text(this, details.optString("name", room.name), 20, Ui.INK, true);
        title.setGravity(Gravity.CENTER);
        content.addView(title, fieldSize(10));
        TextView company = Ui.text(this, groupCompanyName(room.companyId), 13, Ui.MUTED, false);
        company.setGravity(Gravity.CENTER);
        content.addView(company, fieldSize(2));
        String description = details.optString("description", "").trim();
        if (room.isGroup) {
            TextView descriptionLabel = Ui.text(this, getString(R.string.bchat_group_description),
                    13, Ui.MUTED, true);
            content.addView(descriptionLabel, fieldSize(22));
            TextView descriptionText = Ui.text(this, description.isEmpty()
                    ? getString(R.string.bchat_group_no_description) : description, 15, Ui.INK, false);
            descriptionText.setBackground(Ui.bg(Ui.SURFACE, 14, this));
            Ui.pad(descriptionText, 16, 12);
            descriptionText.setMinHeight(dp(56));
            content.addView(descriptionText, fieldSize(8));
        }
        if (canManage) {
            content.addView(groupInfoAction(R.string.bchat_group_rename,
                    () -> renameGroup(room)), fieldSize(12));
            content.addView(groupInfoAction(R.string.bchat_group_edit_description,
                    () -> editGroupDescription(room, description)), fieldSize(2));
            content.addView(groupInfoAction(R.string.bchat_group_change_photo,
                    () -> chooseGroupPhoto(room)), fieldSize(2));
            content.addView(groupInfoAction(R.string.bchat_group_add_member,
                    () -> addGroupMember(room, members)), fieldSize(2));
        }
        TextView membersLabel = Ui.text(this,
                getString(R.string.bchat_group_members_count, members.length()), 16, Ui.INK, true);
        content.addView(membersLabel, fieldSize(24));
        for (int i = 0; i < members.length(); i++) {
            JSONObject member = members.optJSONObject(i);
            if (member == null) continue;
            String memberName = member.optString("name");
            if (memberName.isEmpty()) continue;
            boolean admin = member.optBoolean("is_admin");
            LinearLayout memberRow = Ui.row(this);
            memberRow.setBackground(Ui.bg(Ui.SURFACE, 12, this));
            Ui.pad(memberRow, 12, 6);
            TextView initial = Ui.text(this, memberName.substring(0, 1), 18, Ui.GREEN, true);
            initial.setGravity(Gravity.CENTER);
            initial.setBackground(Ui.bg(Ui.ACTION_TONAL, 24, this));
            memberRow.addView(initial, new LinearLayout.LayoutParams(dp(40), dp(40)));
            LinearLayout identity = Ui.column(this);
            LinearLayout.LayoutParams identitySize = new LinearLayout.LayoutParams(0, -2, 1);
            identitySize.setMarginStart(dp(12));
            identity.addView(Ui.text(this, memberName, 15, Ui.INK, true));
            if (admin) identity.addView(Ui.text(this, getString(R.string.bchat_group_admin),
                    12, Ui.MUTED, false));
            memberRow.addView(identity, identitySize);
            if (canManage && member.optLong("user_id") != account.userId) {
                Ui.clickable(memberRow);
                memberRow.setOnClickListener(view -> {
                    if (groupInfoDialog != null) groupInfoDialog.dismiss();
                    showGroupMemberActions(room, member);
                });
            }
            content.addView(memberRow, fieldSize(4));
        }
        if (!room.isGroup) content.addView(Ui.text(this,
                getString(R.string.bchat_legacy_room_read_only), 13, Ui.MUTED, false), fieldSize(20));
        else content.addView(groupInfoAction(R.string.bchat_group_leave,
                () -> confirmLeaveGroup(room)), fieldSize(20));
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(room.isGroup
                ? R.string.bchat_group_info : R.string.bchat_room_info)
                .setView(scroll).setNegativeButton(R.string.chat_v2_cancel, null).create();
        groupInfoDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (groupInfoDialog == dialog) groupInfoDialog = null;
        });
        dialog.show();
        Ui.decorateDialog(dialog);
        if (dialog.getWindow() != null) dialog.getWindow().setLayout(-1,
                (int) (getResources().getDisplayMetrics().heightPixels * 0.9f));
    }

    private void addGroupMember(Room room, JSONArray members) {
        List<TaskChoice> selected = new ArrayList<>();
        try {
            for (int i = 0; i < members.length(); i++) {
                JSONObject item = members.getJSONObject(i);
                selected.add(new TaskChoice(positiveId(item.get("user_id")),
                        item.getString("name")));
            }
        } catch (Exception invalid) { return; }
        loadGroupCandidates(room.companyId, "", selected, () -> {
            TaskChoice chosen = selected.get(selected.size() - 1);
            submitGroupChange(room, "add_member", chosen.id, null);
        });
    }

    private void showGroupMemberActions(Room room, JSONObject member) {
        long userId = member.optLong("user_id");
        if (userId <= 0 || account == null || userId == account.userId) return;
        boolean admin = member.optBoolean("is_admin");
        String[] actions = new String[]{getString(admin
                ? R.string.bchat_group_demote : R.string.bchat_group_promote),
                getString(R.string.bchat_group_remove)};
        Ui.decorateDialog(new AlertDialog.Builder(this)
                .setTitle(member.optString("name"))
                .setItems(actions, (choice, action) -> submitGroupChange(room,
                        action == 1 ? "remove_member"
                                : admin ? "demote_admin" : "promote_admin", userId, null))
                .setNegativeButton(R.string.chat_v2_cancel, null).show());
    }

    private void editGroupDescription(Room room, String current) {
        EditText description = new EditText(this);
        description.setText(current);
        description.setSingleLine(false);
        description.setMinLines(3);
        description.setMaxLines(5);
        description.setHint(R.string.bchat_group_description_hint);
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(R.string.bchat_group_edit_description).setView(description)
                .setPositiveButton(R.string.bchat_group_save, null)
                .setNegativeButton(R.string.chat_v2_cancel, null).create();
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE)
                .setOnClickListener(view -> {
                    String changed = description.getText().toString().trim();
                    if (changed.getBytes(StandardCharsets.UTF_8).length > 1024) {
                        description.setError(getString(R.string.bchat_group_description_too_long));
                        return;
                    }
                    dialog.dismiss();
                    if (!changed.equals(current))
                        submitGroupChange(room, "set_description", 0, changed);
                }));
        dialog.show();
        Ui.decorateDialog(dialog);
    }

    private void showGroupMembers(Room room, JSONArray members, boolean canManage) {
        String[] labels = new String[members.length()];
        try {
            for (int i = 0; i < members.length(); i++) {
                JSONObject member = members.getJSONObject(i);
                labels[i] = member.getString("name") + (member.getBoolean("is_admin")
                        ? " · " + getString(R.string.bchat_group_admin) : "");
            }
        } catch (Exception invalid) { return; }
        Ui.decorateDialog(new AlertDialog.Builder(this)
                .setTitle(R.string.bchat_group_members)
                .setItems(labels, (dialog, which) -> {
                    if (!canManage) return;
                    JSONObject member = members.optJSONObject(which);
                    if (member == null) return;
                    long userId = member.optLong("user_id");
                    if (userId <= 0 || userId == account.userId) return;
                    boolean admin = member.optBoolean("is_admin");
                    String[] actions = new String[]{getString(admin
                            ? R.string.bchat_group_demote : R.string.bchat_group_promote),
                            getString(R.string.bchat_group_remove)};
                    Ui.decorateDialog(new AlertDialog.Builder(this)
                            .setTitle(member.optString("name"))
                            .setItems(actions, (choice, action) -> submitGroupChange(room,
                                    action == 1 ? "remove_member"
                                            : admin ? "demote_admin" : "promote_admin",
                                    userId, null))
                            .setNegativeButton(R.string.chat_v2_cancel, null).show());
                }).setNegativeButton(R.string.chat_v2_cancel, null).show());
    }

    private void renameGroup(Room room) {
        EditText name = new EditText(this);
        name.setSingleLine(true);
        name.setTextSize(16);
        name.setText(room.name);
        Ui.decorateDialog(new AlertDialog.Builder(this)
                .setTitle(R.string.bchat_group_rename).setView(name)
                .setPositiveButton(R.string.bchat_group_save, (dialog, which) -> {
                    String changed = name.getText().toString().trim();
                    if (!changed.isEmpty() && !changed.equals(room.name))
                        submitGroupChange(room, "rename", 0, changed);
                }).setNegativeButton(R.string.chat_v2_cancel, null).show());
    }

    private void confirmLeaveGroup(Room room) {
        Ui.decorateDialog(new AlertDialog.Builder(this)
                .setTitle(R.string.bchat_group_leave)
                .setMessage(R.string.bchat_group_leave_confirm)
                .setPositiveButton(R.string.bchat_group_leave, (dialog, which) ->
                        submitGroupChange(room, "leave", 0, null))
                .setNegativeButton(R.string.chat_v2_cancel, null).show());
    }

    private void submitGroupChange(Room room, String action, long userId, String name) {
        if (!verified || account == null || v2Busy || currentGroupRoom(room) == null
                || !room.isGroup) return;
        final AccountScope scoped = account;
        try {
            JSONObject payload = new JSONObject();
            payload.put("api_version", 2);
            payload.put("action", action);
            if (userId > 0) payload.put("user_id", userId);
            if (name != null) payload.put("set_description".equals(action)
                    ? "description" : "name", name);
            fetchV2("POST", V2_ROOMS + "/" + room.id + "/group", payload.toString(),
                    (status, result) -> {
                        if (handleGroupRouteFailure(status, true)) return;
                        if (!verified || account != scoped) return;
                        if (status == 200 && result != null
                                && result.optInt("api_version") == 2
                                && result.optLong("room_id") == room.id
                                && action.equals(result.optString("action"))) {
                            if ("leave".equals(action)) showRooms();
                            loadRooms();
                        } else {
                            chatNotice.setText(R.string.bchat_group_failed);
                            if (status == 403 || status == 409) loadRooms();
                        }
                    });
        } catch (Exception invalid) { chatNotice.setText(R.string.bchat_group_failed); }
    }

    private void chooseGroupPhoto(Room room) {
        if (!verified || account == null || !room.isGroup
                || currentGroupRoom(room) == null) return;
        Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        picker.addCategory(Intent.CATEGORY_OPENABLE);
        picker.setType("image/*");
        picker.putExtra(Intent.EXTRA_MIME_TYPES,
                new String[]{"image/jpeg", "image/png", "image/webp"});
        groupPhotoAccount = account;
        groupPhotoRoom = room;
        try { startActivityForResult(picker, GROUP_PHOTO_REQUEST); }
        catch (RuntimeException unavailable) {
            groupPhotoAccount = null; groupPhotoRoom = null;
            chatNotice.setText(R.string.bchat_group_photo_failed);
        }
    }

    private void prepareGroupPhoto(AccountScope scoped, Room room, Uri selected) {
        mediaIo.execute(() -> {
            String encoded = null;
            try {
                BitmapFactory.Options bounds = new BitmapFactory.Options();
                bounds.inJustDecodeBounds = true;
                try (InputStream input = getContentResolver().openInputStream(selected)) {
                    if (input == null) throw new IOException("Image is unavailable");
                    BitmapFactory.decodeStream(input, null, bounds);
                }
                long pixels = (long)bounds.outWidth * bounds.outHeight;
                if (bounds.outWidth <= 0 || bounds.outHeight <= 0 || pixels > 40_000_000)
                    throw new IOException("Invalid image size");
                BitmapFactory.Options options = new BitmapFactory.Options();
                options.inSampleSize = 1;
                while (Math.max(bounds.outWidth, bounds.outHeight) / options.inSampleSize > 1024)
                    options.inSampleSize *= 2;
                Bitmap image;
                try (InputStream input = getContentResolver().openInputStream(selected)) {
                    if (input == null) throw new IOException("Image is unavailable");
                    image = BitmapFactory.decodeStream(input, null, options);
                }
                if (image == null) throw new IOException("Invalid image");
                int maximum = Math.max(image.getWidth(), image.getHeight());
                if (maximum > 512) {
                    float scale = 512f / maximum;
                    Bitmap resized = Bitmap.createScaledBitmap(image,
                            Math.max(1, Math.round(image.getWidth() * scale)),
                            Math.max(1, Math.round(image.getHeight() * scale)), true);
                    image.recycle(); image = resized;
                }
                ByteArrayOutputStream output = new ByteArrayOutputStream();
                for (int quality = 85; quality >= 50; quality -= 10) {
                    output.reset();
                    if (!image.compress(Bitmap.CompressFormat.JPEG, quality, output))
                        throw new IOException("Cannot encode image");
                    if (output.size() <= 512 * 1024) break;
                }
                image.recycle();
                if (output.size() == 0 || output.size() > 512 * 1024)
                    throw new IOException("Image is too large");
                encoded = Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP);
            } catch (Exception invalid) { /* No image bytes leave the device on failure. */ }
            final String ready = encoded;
            handler.post(() -> {
                if (!verified || account != scoped || currentGroupRoom(room) == null) return;
                if (ready == null) { chatNotice.setText(R.string.bchat_group_photo_failed); return; }
                fetchV2Internal("POST", V2_ROOMS + "/" + room.id + "/avatar",
                        null, ready, (status, result) -> {
                            if (!verified || account != scoped
                                    || currentGroupRoom(room) == null) return;
                            if (status == 200 && result != null
                                    && result.optInt("api_version") == 2
                                    && result.optLong("room_id") == room.id
                                    && result.optInt("avatar_version") > room.avatarVersion) {
                                loadRooms();
                            } else chatNotice.setText(R.string.bchat_group_photo_failed);
                        });
            });
        });
    }

    private List<AnchoredMenu.Entry> offlineAccountEntries() {
        List<AnchoredMenu.Entry> entries = new ArrayList<>();
        entries.add(AnchoredMenu.Entry.action(getString(R.string.chat_v2_retry_login),
                "refresh", this::retryOnlineSession));
        entries.add(AnchoredMenu.Entry.action(getString(R.string.auth_native_sign_out),
                "logout", this::leaveOfflineHistory));
        return entries;
    }

    private String localizedCompanyName(JSONObject company) {
        return AppLocale.name(this, CompanyLabel.choose(company.optString("name"),
                company.optString("name_ar"), company.optString("name_en"), AppLocale.rtl(this)));
    }

    private String companyNameForId(long id, String fallback) {
        JSONArray companies = profileSnapshot == null ? null : profileSnapshot.optJSONArray("companies");
        if (companies != null) for (int i = 0; i < companies.length(); i++) {
            JSONObject company = companies.optJSONObject(i);
            if (company != null && company.optLong("id") == id)
                return localizedCompanyName(company);
        }
        return AppLocale.name(this, CompanyLabel.choose(fallback, "", "", AppLocale.rtl(this)));
    }

    private void refreshChatCompanySelector() {
        if (chatHeaderCompanyButton == null) return;
        JSONArray companies = profileSnapshot == null ? null : profileSnapshot.optJSONArray("companies");
        if (companies == null || companies.length() == 0 || !verified || v1Companies.isEmpty()) {
            chatHeaderCompanyButton.setVisibility(View.GONE);
            selectedChatCompanyId = 0;
            return;
        }
        JSONObject selected = null;
        JSONObject firstAllowed = null;
        int allowedCount = 0;
        for (int i = 0; i < companies.length(); i++) {
            JSONObject candidate = companies.optJSONObject(i);
            if (candidate == null || !v1Companies.contains(candidate.optLong("id"))) continue;
            ++allowedCount;
            if (firstAllowed == null) firstAllowed = candidate;
            if (candidate.optLong("id") == selectedChatCompanyId) selected = candidate;
        }
        if (selected == null) selected = firstAllowed;
        selectedChatCompanyId = selected == null ? 0 : selected.optLong("id");
        if (selected == null || selectedChatCompanyId == 0) {
            chatHeaderCompanyButton.setVisibility(View.GONE);
            return;
        }
        String name = localizedCompanyName(selected);
        boolean canSwitch = allowedCount > 1;
        chatHeaderCompanyButton.setText(name + (canSwitch ? " ⌄" : ""));
        chatHeaderCompanyButton.setContentDescription(getString(
                R.string.bchat_group_company_context, name));
        chatHeaderCompanyButton.setEnabled(canSwitch);
        chatHeaderCompanyButton.setVisibility("chats".equals(visibleSection)
                ? View.VISIBLE : View.GONE);
    }

    private void refreshRoomCompanySubtitle() {
        if (roomSubtitle == null) return;
        JSONArray companies = profileSnapshot == null ? null : profileSnapshot.optJSONArray("companies");
        if (selectedRoom == null || companies == null) {
            roomSubtitle.setText(R.string.chat_v2_room_label);
            roomSubtitle.setOnClickListener(null);
            roomSubtitle.setClickable(false);
            return;
        }
        String name = companyNameForId(selectedRoom.companyId, "");
        if (name.isEmpty()) {
            roomSubtitle.setText(R.string.chat_v2_room_label);
            roomSubtitle.setOnClickListener(null);
            roomSubtitle.setClickable(false);
            return;
        }
        boolean canSwitch = verified && companies.length() > 1 && !name.isEmpty();
        roomSubtitle.setText(name + (canSwitch ? " ⌄" : ""));
        roomSubtitle.setContentDescription(name);
        roomSubtitle.setOnClickListener(canSwitch ? v -> showChatCompanyMenu(roomSubtitle) : null);
        roomSubtitle.setClickable(canSwitch);
    }

    private void showChatCompanyMenu(View anchor) {
        JSONArray companies = profileSnapshot == null ? null : profileSnapshot.optJSONArray("companies");
        if (!verified || account == null || chatCompanyMenu == null || companies == null
                || companies.length() < 2 || !"chats".equals(visibleSection)
                || (selectedRoom == null && anchor != chatHeaderCompanyButton)
                || (selectedRoom != null && anchor != roomSubtitle)) return;
        if (accountMenu != null) accountMenu.dismiss();
        final AccountScope scopedAccount = account;
        final Room scopedRoom = selectedRoom;
        List<AnchoredMenu.Entry> entries = new ArrayList<>();
        for (int i = 0; i < companies.length(); i++) {
            JSONObject company = companies.optJSONObject(i);
            if (company == null) continue;
            long id = company.optLong("id");
            if (!v1Companies.contains(id)) continue;
            entries.add(AnchoredMenu.Entry.choice(localizedCompanyName(company), "company",
                    id == selectedChatCompanyId, () -> {
                        if (account != scopedAccount || selectedRoom != scopedRoom
                                || !verified || !v1Companies.contains(id)) return;
                        if (scopedRoom != null) showRooms();
                        selectedChatCompanyId = id;
                        refreshChatCompanySelector();
                        renderRooms();
                    }));
        }
        chatCompanyMenu.show(anchor, getString(R.string.order_choose_company),
                () -> verified && account == scopedAccount && "chats".equals(visibleSection)
                        && selectedRoom == scopedRoom && anchor.isShown(), entries);
    }

    private void showOrderCompanyMenu() {
        if (!verified || account == null || orderCompanyMenu == null
                || !"orders".equals(visibleSection) || orderCompanies.size() < 2) return;
        if (accountMenu != null) accountMenu.dismiss();
        final AccountScope scopedAccount = account;
        List<AnchoredMenu.Entry> entries = new ArrayList<>();
        for (TaskChoice company : orderCompanies)
            entries.add(AnchoredMenu.Entry.choice(companyNameForId(company.id, company.name),
                    "company", company.id == orderCompanyId,
                    () -> selectOrderCompany(company.id)));
        orderCompanyMenu.show(orderHeaderCompanyButton, getString(R.string.order_choose_company),
                () -> verified && account == scopedAccount && "orders".equals(visibleSection)
                        && orderHeaderCompanyButton.isShown(), entries);
    }

    private List<AnchoredMenu.Entry> accountRootEntries() {
        List<AnchoredMenu.Entry> entries = new ArrayList<>();
        entries.add(AnchoredMenu.Entry.action(getString(R.string.bchat_profile), "person", this::showProfile));
        entries.add(AnchoredMenu.Entry.action(getString(R.string.chat_v2_refresh), "refresh",
                this::refreshCurrentSection));
        entries.add(AnchoredMenu.Entry.page(getString(R.string.bchat_settings), "settings", this::showAccountSettings));
        entries.add(AnchoredMenu.Entry.page(getString(R.string.bchat_about), "info", this::showAccountAbout));
        entries.add(AnchoredMenu.Entry.action(getString(R.string.auth_native_sign_out), "logout", this::logout));
        return entries;
    }

    private void showAccountSettings() {
        if (accountMenu == null) return;
        List<AnchoredMenu.Entry> entries = new ArrayList<>();
        entries.add(AnchoredMenu.Entry.page(getString(R.string.bchat_menu_back), "back",
                () -> accountMenu.replace(getString(R.string.bchat_account_menu), accountRootEntries())));
        entries.add(AnchoredMenu.Entry.action(getString(R.string.bchat_notifications), "bell",
                this::showNotificationSettings));
        entries.add(AnchoredMenu.Entry.action(getString(R.string.language_title), "language", this::showLanguageSettings));
        accountMenu.replace(getString(R.string.bchat_settings), entries);
    }

    /** Android permission and the BChat channel are separate, user-controlled delivery settings. */
    private void showNotificationSettings() {
        if (!BuildConfig.BCHAT_PUSH_ENABLED) {
            new AlertDialog.Builder(this).setTitle(R.string.bchat_notifications)
                    .setMessage(R.string.bchat_notifications_unavailable)
                    .setPositiveButton(R.string.task_close, null).show();
            return;
        }
        boolean permissionGranted = Build.VERSION.SDK_INT < 33
                || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED;
        NotificationManager notifications = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        ensureBChatNotificationChannel(notifications);
        boolean enabled = notifications != null && notifications.areNotificationsEnabled();
        boolean channelMuted = false;
        if (Build.VERSION.SDK_INT >= 26 && notifications != null) {
            NotificationChannel channel = notifications.getNotificationChannel("bchat-events-v3");
            // Android preserves a user's per-channel sound choice.  Treat a quiet
            // channel as unavailable too, otherwise the status screen would claim
            // that delivery has sound even after the user muted it.
            channelMuted = channel != null && (channel.getImportance() < NotificationManager.IMPORTANCE_DEFAULT
                    || channel.getSound() == null);
        }
        boolean linked = account != null && !BChatPushState.needsRegistration(this, account);
        final boolean openChannelSettings = permissionGranted && enabled && channelMuted;
        int action = !permissionGranted && !preferences().getBoolean(PUSH_PERMISSION_ASKED, false)
                ? R.string.bchat_notifications_enable : R.string.bchat_notifications_manage;
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(R.string.bchat_notifications)
                .setMessage(notificationStatusMessage(permissionGranted, enabled, channelMuted, linked))
                .setNegativeButton(R.string.task_close, null)
                .setPositiveButton(action, null).create();
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE)
                .setOnClickListener(v -> {
                    if (!permissionGranted && !preferences().getBoolean(PUSH_PERMISSION_ASKED, false)
                            && Build.VERSION.SDK_INT >= 33) {
                        preferences().edit().putBoolean(PUSH_PERMISSION_ASKED, true).apply();
                        requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},
                                PUSH_PERMISSION_REQUEST);
                    } else openNotificationSettings(openChannelSettings);
                    dialog.dismiss();
                }));
        dialog.show();
        maybeRegisterPush();
        refreshNotificationStatus(dialog, permissionGranted, enabled, channelMuted);
    }

    private String notificationStatusMessage(boolean permissionGranted, boolean enabled,
                                             boolean channelMuted, boolean linked) {
        int state = !permissionGranted || !enabled || channelMuted
                ? R.string.bchat_notifications_off
                : linked ? R.string.bchat_notifications_on : R.string.bchat_notifications_linking;
        String message = getString(state, linked ? getString(R.string.bchat_device_linked)
                : getString(R.string.bchat_device_linking));
        return BuildConfig.BCHAT_PUSH_REGISTRATION_DIAGNOSTICS
                ? message + "\nQA push: " + pushRegistrationDiagnostic : message;
    }

    /** Refresh only local state while the dialog is open; this never issues another registration. */
    private void refreshNotificationStatus(AlertDialog dialog, boolean permissionGranted,
                                           boolean enabled, boolean channelMuted) {
        if (dialog == null || !dialog.isShowing()) return;
        boolean linked = account != null && !BChatPushState.needsRegistration(this, account);
        dialog.setMessage(notificationStatusMessage(permissionGranted, enabled, channelMuted, linked));
        if (!linked && permissionGranted && enabled && !channelMuted) {
            handler.postDelayed(() -> refreshNotificationStatus(dialog, permissionGranted, enabled,
                    channelMuted), 300);
        }
    }

    private void ensureBChatNotificationChannel(NotificationManager notifications) {
        if (Build.VERSION.SDK_INT < 26 || notifications == null) return;
        NotificationChannel channel = new NotificationChannel("bchat-events-v3", "BChat",
                NotificationManager.IMPORTANCE_HIGH);
        channel.setDescription(getString(R.string.bchat_push_channel_description));
        channel.enableVibration(true);
        channel.setVibrationPattern(new long[]{0, 160, 100, 160});
        channel.setSound(Settings.System.DEFAULT_NOTIFICATION_URI,
                new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION).build());
        notifications.createNotificationChannel(channel);
    }

    private void openNotificationSettings(boolean openChannel) {
        Intent intent;
        if (Build.VERSION.SDK_INT >= 26 && openChannel) {
            intent = new Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName())
                    .putExtra(Settings.EXTRA_CHANNEL_ID, "bchat-events-v3");
        } else if (Build.VERSION.SDK_INT >= 26) {
            // A disabled app or denied POST_NOTIFICATIONS permission cannot be
            // repaired from a channel page; Android exposes both controls here.
            intent = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName());
        } else {
            intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                    .setData(Uri.fromParts("package", getPackageName(), null));
        }
        startActivity(intent);
    }

    private void showAccountAbout() {
        if (accountMenu == null) return;
        List<AnchoredMenu.Entry> entries = new ArrayList<>();
        entries.add(AnchoredMenu.Entry.page(getString(R.string.bchat_menu_back), "back",
                () -> accountMenu.replace(getString(R.string.bchat_account_menu), accountRootEntries())));
        entries.add(AnchoredMenu.Entry.disabled(getString(R.string.bchat_about_summary)));
        entries.add(AnchoredMenu.Entry.disabled(getString(R.string.bchat_installed_version, installedBChatVersion())));
        entries.add(AnchoredMenu.Entry.action(getString(R.string.bchat_whats_new), "info", this::showBChatWhatsNew));
        accountMenu.replace(getString(R.string.bchat_about), entries);
    }

    private String installedBChatVersion() {
        try {
            android.content.pm.PackageInfo info = getPackageManager().getPackageInfo(getPackageName(), 0);
            long code = android.os.Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode;
            return info.versionName + " (" + code + ")";
        } catch (android.content.pm.PackageManager.NameNotFoundException unavailable) {
            return getString(R.string.bchat_version_unavailable);
        }
    }

    private String installedBChatReleaseName() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (android.content.pm.PackageManager.NameNotFoundException unavailable) {
            return getString(R.string.bchat_version_unavailable);
        }
    }

    private void showBChatWhatsNew() {
        if (!verified || account == null) return;
        new AlertDialog.Builder(this)
                .setTitle(getString(R.string.bchat_whats_new_title, installedBChatVersion()))
                .setMessage(R.string.bchat_whats_new_body)
                .setPositiveButton(R.string.task_close, null).show();
    }

    private void showProfile() {
        if (!verified || account == null) return;
        AccountScope profileAccount = account;
        int profileEpoch = epoch;
        if (profileDialog != null) { profileDialog.dismiss(); profileDialog = null; }
        JSONObject profile = profileSnapshot;
        if (profile == null) {
            profileDialog = new AlertDialog.Builder(this).setTitle(R.string.bchat_profile)
                    .setMessage(R.string.bchat_profile_unavailable)
                    .setPositiveButton(R.string.task_close, null).create();
            if (verified && account == profileAccount && epoch == profileEpoch) profileDialog.show();
            return;
        }
        LinearLayout body = Ui.column(this);
        Ui.pad(body, 18, 18);
        LinearLayout hero = Ui.column(this);
        hero.setGravity(Gravity.CENTER_HORIZONTAL);
        hero.setBackground(Ui.bg(Ui.LIGHT, 18, this));
        Ui.pad(hero, 18, 18);
        String profileName = AppLocale.name(this, profile.optString("name"));
        if (profileName.trim().isEmpty()) profileName = getString(R.string.bchat_profile);
        View photo = privateAvatarView(profileAccount.key + ":profile:" + profileAccount.userId,
                V2_PROFILE_AVATAR, profileName, (int) (profileAccount.userId * 47 % 360));
        LinearLayout.LayoutParams photoSize = new LinearLayout.LayoutParams(dp(84), dp(84));
        photoSize.gravity = Gravity.CENTER_HORIZONTAL;
        hero.addView(photo, photoSize);
        TextView name = Ui.text(this, profileName, 21, Ui.INK, true);
        name.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams nameSize = fieldSize(10);
        nameSize.gravity = Gravity.CENTER_HORIZONTAL;
        hero.addView(name, nameSize);
        body.addView(hero, new LinearLayout.LayoutParams(-1, -2));
        JSONArray companies = profile.optJSONArray("companies");
        if (companies != null) for (int i = 0; i < companies.length(); i++) {
            JSONObject company = companies.optJSONObject(i);
            if (company == null) continue;
            LinearLayout companyCard = Ui.column(this);
            companyCard.setBackground(Ui.outline(Ui.SURFACE, Ui.LINE, 14, this));
            Ui.pad(companyCard, 14, 12);
            LinearLayout.LayoutParams companyCardSize = new LinearLayout.LayoutParams(-1, -2);
            companyCardSize.topMargin = dp(12);
            // Prefer the dedicated localized label over a legacy legal name that can join both languages.
            TextView companyName = Ui.text(this, localizedCompanyName(company), 15, Ui.GREEN, true);
            companyCard.addView(companyName, fieldSize(6));
            JSONArray titles = company.optJSONArray("job_titles");
            StringBuilder jobs = new StringBuilder();
            if (titles != null) for (int j = 0; j < titles.length(); j++) {
                if (j > 0) jobs.append(" · ");
                jobs.append(AppLocale.name(this, titles.optString(j)));
            }
            // An absent optional title is not an error state; do not repeat an empty-state chip
            // on every company card.
            if (jobs.length() > 0) {
                TextView job = Ui.text(this, jobs.toString(), 13, Ui.MUTED, false);
                job.setBackground(Ui.bg(Ui.ACTION_TONAL, 9, this));
                Ui.pad(job, 10, 6);
                companyCard.addView(job, new LinearLayout.LayoutParams(-2, -2));
            }
            body.addView(companyCard, companyCardSize);
        }
        ScrollView scroll = new ScrollView(this);
        scroll.addView(body);
        profileDialog = new AlertDialog.Builder(this).setTitle(R.string.bchat_profile).setView(scroll)
                .setPositiveButton(R.string.task_close, null).create();
        if (verified && account == profileAccount && epoch == profileEpoch) profileDialog.show();
    }

    private void showLanguageSettings() {
        if (!verified) return;
        LocalSettings settings = new LocalSettings(this);
        final String[] selected = {settings.language()};
        new AlertDialog.Builder(this).setTitle(R.string.language_title)
                .setSingleChoiceItems(new String[]{getString(R.string.language_arabic),
                        getString(R.string.language_english)},
                        "en".equals(selected[0]) ? 1 : 0,
                        (dialog, which) -> selected[0] = which == 1 ? "en" : "ar")
                .setPositiveButton(R.string.language_apply, (dialog, which) -> {
                    if (!AppLocalePolicy.changed(settings.language(), selected[0])) return;
                    if (!settings.language(selected[0])) {
                        new AlertDialog.Builder(this).setMessage(R.string.error_language_save)
                                .setPositiveButton(R.string.task_close, null).show();
                        return;
                    }
                    recreateForLanguage = true;
                    recreate();
                })
                .setNegativeButton(R.string.language_cancel, null).show();
    }

    private Button orderChoiceButton(int label, Runnable action) {
        Button button = new Button(this);
        button.setText(label);
        styleAction(button, false);
        button.setOnClickListener(v -> action.run());
        return button;
    }

    private View addOrderTab(LinearLayout tabs, Button button) {
        LinearLayout cell = Ui.column(this);
        cell.setGravity(Gravity.CENTER);
        cell.addView(button, new LinearLayout.LayoutParams(-1, dp(48)));
        View line = new View(this);
        LinearLayout.LayoutParams lineSize = new LinearLayout.LayoutParams(-1, dp(3));
        lineSize.setMargins(dp(12), 0, dp(12), 0);
        cell.addView(line, lineSize);
        tabs.addView(cell, new LinearLayout.LayoutParams(0, -2, 1));
        return line;
    }

    private String orderContentKey(String mode, long companyId, long categoryId,
                                   String search, long cursor) {
        return mode + ':' + companyId + ':' + categoryId + ':' + search.length() + ':'
                + search + ':' + cursor;
    }

    private void prepareOrderContent(String key) {
        if (key.equals(orderRenderedKey)) return;
        clearOrderRetry();
        orderRenderedKey = null;
        resetOrderImages(false);
        orderItems.removeAllViews();
        orderItems.setBackgroundColor(Color.WHITE);
        // Neutral transition: never present another company/filter/page as current data.
        View placeholder = new View(this);
        placeholder.setBackground(Ui.bg(Ui.LIGHT, 12, this));
        LinearLayout.LayoutParams size = new LinearLayout.LayoutParams(-1, dp(68));
        size.setMargins(dp(12), dp(12), dp(12), 0);
        orderItems.addView(placeholder, size);
    }

    private void beginOrderLoading(int serial, int label) {
        boolean keepVisible = orderLoadingVisible
                && getString(label).contentEquals(orderNotice.getText());
        if (orderLoadingTask != null) handler.removeCallbacks(orderLoadingTask);
        orderLoadingTask = null;
        clearOrderRetry();
        if (keepVisible) return;
        orderLoadingVisible = false;
        orderNotice.setText("");
        orderLoadingTask = () -> {
            orderLoadingTask = null;
            if (serial != orderViewSerial || !"orders".equals(visibleSection)) return;
            orderLoadingVisible = true;
            orderNotice.setText(label);
        };
        handler.postDelayed(orderLoadingTask, 220);
    }

    private void queueOrderLoadWhenIdle(Runnable load) {
        queuedOrderLoad = load;
    }

    private void runQueuedOrderLoad() {
        if (v2Busy || queuedOrderLoad == null) return;
        Runnable load = queuedOrderLoad;
        queuedOrderLoad = null;
        if (verified && "orders".equals(visibleSection)) load.run();
    }

    private void finishOrderLoading() {
        if (orderLoadingTask != null) handler.removeCallbacks(orderLoadingTask);
        orderLoadingTask = null;
        if (orderLoadingVisible) orderNotice.setText("");
        orderLoadingVisible = false;
    }

    private void clearOrderRetry() {
        orderRetryAction = null;
        if (orderNotice != null) orderNotice.setOnClickListener(null);
    }

    private void showOrderLoadError(int label, Runnable retry) {
        orderRetryAction = retry;
        orderNotice.setText(getString(R.string.order_retry_message,
                getString(label), getString(R.string.order_tap_retry)));
        orderNotice.setOnClickListener(v -> {
            Runnable action = orderRetryAction;
            clearOrderRetry();
            orderNotice.setText("");
            if (action != null && verified && "orders".equals(visibleSection)) action.run();
        });
    }

    private void renderBottomTabs() {
        if (bottomTabs == null) return;
        bottomTabs.removeAllViews();
        String[] sections = {"chats", "orders", "tasks"};
        int[] labels = {R.string.chat_v2_rooms, R.string.chat_v2_orders, R.string.chat_v2_tasks};
        String[] icons = {"chat", "orders", "tasks"};
        for (int i = 0; i < sections.length; i++) {
            final String section = sections[i];
            if ("chats".equals(section) && !chatAllowed()) continue;
            if ("tasks".equals(section) && !permissionSet.taskView) continue;
            if ("orders".equals(section) && !orderCanView) continue;
            if (offlineHistory && "chats".equals(section) && !offlineChatCacheAvailable) continue;
            if (offlineHistory && "tasks".equals(section) && !offlineTaskCacheAvailable) continue;
            boolean selected = section.equals(visibleSection);
            LinearLayout tab = Ui.column(this);
            tab.setGravity(Gravity.CENTER);
            tab.setTag("bchat-section-" + section);
            tab.setMinimumHeight(dp(60));
            FrameLayout indicator = new FrameLayout(this);
            Ui.Icon icon = new Ui.Icon(this, icons[i], selected ? Ui.GREEN : Ui.MUTED);
            indicator.addView(icon, new FrameLayout.LayoutParams(dp(22), dp(22), Gravity.CENTER));
            tab.addView(indicator, new LinearLayout.LayoutParams(dp(56), dp(30)));
            TextView label = Ui.text(this, getString(labels[i]), 12,
                    selected ? Ui.GREEN : Ui.MUTED, selected);
            label.setGravity(Gravity.CENTER);
            label.setSingleLine(true);
            tab.addView(label, new LinearLayout.LayoutParams(-1, -2));
            tab.setContentDescription(getString(labels[i]));
            Ui.styleTab(tab, indicator, label, selected);
            View selectedLine = new View(this);
            selectedLine.setBackground(Ui.bg(selected ? Ui.SKY : Color.TRANSPARENT, 2, this));
            LinearLayout.LayoutParams lineSize = new LinearLayout.LayoutParams(dp(50), dp(3));
            lineSize.gravity = Gravity.CENTER_HORIZONTAL;
            lineSize.topMargin = dp(3);
            tab.addView(selectedLine, lineSize);
            tab.setOnClickListener(v -> {
                    if ("tasks".equals(section)) {
                    ++taskViewSerial;
                    taskRoomFilter = 0;
                    if ("tasks".equals(visibleSection)) {
                        if (offlineHistory) showCachedTasks(); else discoverTasks();
                    }
                    else switchSection(section);
                } else switchSection(section);
            });
            LinearLayout.LayoutParams tabSize = new LinearLayout.LayoutParams(0, -2, 1);
            tabSize.setMargins(dp(1), 0, dp(1), 0);
            bottomTabs.addView(tab, tabSize);
        }
    }

    private void switchSection(String section) {
        if (!"chats".equals(section) && !"orders".equals(section) && !"tasks".equals(section)) return;
        if ("chats".equals(section) && !chatAllowed()) return;
        if ("tasks".equals(section) && !permissionSet.taskView) return;
        if ("orders".equals(section) && !orderCanView) return;
        if (offlineHistory && "chats".equals(section) && !offlineChatCacheAvailable) return;
        if (offlineHistory && "tasks".equals(section) && !offlineTaskCacheAvailable) return;
        if (section.equals(visibleSection) && ("chats".equals(section) ? chatPane.getVisibility() == View.VISIBLE
                : "tasks".equals(section) ? taskPane.getVisibility() == View.VISIBLE
                : modulePane.getVisibility() == View.VISIBLE)) return;
        if (accountMenu != null) accountMenu.dismiss();
        if (orderCompanyMenu != null) orderCompanyMenu.dismiss();
        if (chatCompanyMenu != null) chatCompanyMenu.dismiss();
        if (!"chats".equals(section)) { stopInlineAudio(); closeMediaRead(); }
        flushDraftSave();
        if ("tasks".equals(visibleSection) && !"tasks".equals(section)) ++taskViewSerial;
        if ("orders".equals(visibleSection) && !"orders".equals(section)) {
            queuedOrderLoad = null;
            if (receiptFlowDialog != null) receiptFlowDialog.dismiss();
            ++orderViewSerial;
            resetOrderImages(false);
            invalidateOrderQuote();
        }
        if (pendingDialog != null) { pendingDialog.dismiss(); pendingDialog = null; }
        visibleSection = section;
        orderHeaderCompanyButton.setVisibility("orders".equals(section)
                && (orderCanCreate || orderCanReceive) && !orderCompanies.isEmpty()
                ? View.VISIBLE : View.GONE);
        refreshChatCompanySelector();
        boolean chats = "chats".equals(section);
        chatPane.setVisibility(chats ? View.VISIBLE : View.GONE);
        modulePane.setVisibility("orders".equals(section) ? View.VISIBLE : View.GONE);
        taskPane.setVisibility("tasks".equals(section) ? View.VISIBLE : View.GONE);
        boolean insideRoom = chats && selectedRoom != null;
        brandBar.setVisibility(insideRoom ? View.GONE : View.VISIBLE);
        bottomTabs.setVisibility(insideRoom || (offlineHistory
                && !(offlineChatCacheAvailable && offlineTaskCacheAvailable)) ? View.GONE : View.VISIBLE);
        if ("orders".equals(section)) {
            // A denied role can be granted during this session. Otherwise the scoped
            // content request still checks authorization without repeating both options calls.
            boolean needsDiscovery = !ordersAvailable || ordersDenied
                    || (!orderMine && orderCompanies.isEmpty());
            ordersDenied = false;
            if (needsDiscovery) discoverOrders();
            else if (orderMine) loadOrderSummaries(0);
            else if (!orderReceiving && !orderMine && orderCompanyId > 0 && !orderCompanyOptionsLoaded)
                loadOrderCompanyOptions();
            else if (orderCompanyId > 0) {
                if (orderReceiving) loadReceipts(0);
                else if (orderMine) loadOrderSummaries(0);
                else {
                    loadOrderCatalog(0);
                    if (!orderCart.isEmpty()) scheduleOrderQuote();
                }
            }
        }
        if ("tasks".equals(section)) {
            if (offlineHistory) showCachedTasks(); else discoverTasks();
        }
        renderBottomTabs();
        if (!"orders".equals(section)) handler.post(this::maybeProbeOrderCapability);
        handler.post(this::flushLiveUi);
    }

    private static boolean sameOrigin(Uri uri) {
        Uri expected = Uri.parse(ORIGIN);
        return uri != null && "https".equals(uri.getScheme())
                && expected.getHost().equals(uri.getHost()) && uri.getPort() == expected.getPort()
                && uri.getUserInfo() == null;
    }

    private static boolean isLoginPath(String path) {
        return "/web/login".equals(path)
                || (path != null && path.matches("/[A-Za-z][A-Za-z0-9_-]{1,15}/web/login"));
    }

    private static boolean isBridgeUrl(Uri uri) {
        return sameOrigin(uri) && BRIDGE.equals(uri.toString());
    }

    private static boolean isErpPath(String path) {
        return "/web".equals(path) || (path != null && path.startsWith("/odoo"));
    }

    private boolean allowedMainFrame(Uri uri) {
        if (!sameOrigin(uri)) return false;
        String path = uri.getPath();
        return isLoginPath(path) || isBridgeUrl(uri)
                || (path != null && path.endsWith("/web/login/totp"))
                || (loggingOut && "/web/session/logout".equals(path));
    }

    /** An unexpected Odoo ERP document cannot become the BChat authentication surface. */
    private void divertErp(WebView view, int expectedWeb) {
        if (view != web || expectedWeb != webEpoch) return;
        hideWeb();
        view.stopLoading();
        if (bridgeRecoveryPending) return;
        if (loggingOut) {
            releaseWeb();
            fail(R.string.auth_logout_unconfirmed);
            return;
        }
        if (bridgeRecoveryUsed) {
            releaseWeb();
            fail(R.string.auth_denied);
            return;
        }
        bridgeRecoveryUsed = true;
        bridgeRecoveryPending = true;
        handler.post(() -> {
            if (closed || view != web || expectedWeb != webEpoch) return;
            bridgeRecoveryPending = false;
            openWeb(BRIDGE);
        });
    }

    private void hideWeb() {
        if (web == null) return;
        web.setLayoutParams(new LinearLayout.LayoutParams(-1, dp(1)));
        web.setVisibility(View.INVISIBLE);
    }

    private void showWebChallenge() {
        if (web == null) return;
        web.setLayoutParams(new LinearLayout.LayoutParams(-1, 0, 1));
        web.setVisibility(View.VISIBLE);
    }

    private void cancelBridgeNavigationTimeout() {
        if (bridgeNavigationTimeout == null) return;
        handler.removeCallbacks(bridgeNavigationTimeout);
        bridgeNavigationTimeout = null;
    }

    /**
     * Odoo intentionally returns 404 for private routes before authentication.
     * WebView implementations do not consistently surface that main-document
     * response through onReceivedHttpError, so the v1 bootstrap path uses this
     * same bounded recovery too. A plain navigation timeout never purges cache.
     */
    private boolean recoverExpiredPrivateBridgeSession() {
        if (closed || loggingOut) return false;
        // An expired web session does not revoke this employee's scoped offline snapshot.
        releaseWeb();
        clearCookies(() -> {
            if (!closed) {
                showLoginForm();
                openWeb(LOGIN);
            }
        });
        return true;
    }

    private void scheduleBridgeNavigationTimeout(WebView expectedView, int expectedWeb) {
        cancelBridgeNavigationTimeout();
        bridgeNavigationTimeout = () -> {
            if (closed || expectedView != web || expectedWeb != webEpoch || verified
                    || navigationFailed || loggingOut) return;
            navigationFailed = true;
            expectedView.stopLoading();
            if (!offerOfflineHistory()) fail(R.string.auth_network_error);
        };
        handler.postDelayed(bridgeNavigationTimeout, BRIDGE_NAVIGATION_TIMEOUT_MILLIS);
    }

    /** A remembered account should not wait for a WebView navigation timeout when offline. */
    private boolean networkAvailable() {
        ConnectivityManager manager = getSystemService(ConnectivityManager.class);
        if (manager == null) return true; // Let the authenticated bridge remain the authority when unknown.
        Network network = manager.getActiveNetwork();
        NetworkCapabilities capabilities = network == null ? null : manager.getNetworkCapabilities(network);
        return capabilities != null && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
    }

    private void openWeb(String url) {
        if (closed) return;
        if (BRIDGE.equals(url) && !loggingOut && !networkAvailable() && offerOfflineHistory()) return;
        final String intendedUrl = url;
        if (LOGIN.equals(url) || LOGOUT.equals(url)) {
            bridgeRecoveryUsed = false;
            bridgeRecoveryPending = false;
        }
        releaseWeb();
        pageReady = false;
        navigationFailed = false;
        signIn.setEnabled(false);
        web = new WebView(this);
        final int currentWeb = ++webEpoch;
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true); // Odoo login and MFA need its own JavaScript.
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setSaveFormData(false);
        settings.setSafeBrowsingEnabled(true);
        web.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (!sameOrigin(request.getUrl())) return true;
                String path = request.getUrl().getPath();
                if (request.isForMainFrame() && isErpPath(path)) {
                    divertErp(view, currentWeb);
                    return true;
                }
                if (request.isForMainFrame() && !allowedMainFrame(request.getUrl())) {
                    view.stopLoading();
                    releaseWeb();
                    fail(R.string.auth_denied);
                    return true;
                }
                return false;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                if (sameOrigin(request.getUrl())) return null;
                return new WebResourceResponse("text/plain", "UTF-8", new ByteArrayInputStream(new byte[0]));
            }
            @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                if (view != web || currentWeb != webEpoch) return;
                ++pageEpoch;
                pageReady = false;
                navigationFailed = false;
                signIn.setEnabled(false);
                Uri page = Uri.parse(url);
                if (!sameOrigin(page)) {
                    view.stopLoading();
                    fail(R.string.auth_tls_error);
                    return;
                }
                if (isErpPath(page.getPath())) {
                    divertErp(view, currentWeb);
                    return;
                }
                if (!allowedMainFrame(page)) {
                    view.stopLoading();
                    releaseWeb();
                    fail(R.string.auth_denied);
                    return;
                }
                if (verified && chatRoot.getVisibility() == View.VISIBLE) {
                    // A changed document cannot keep a v2 request or its native transcript alive.
                    verified = false;
                    csrfToken = null;
                    closeV2Port();
                    clearChatView();
                    shell.setVisibility(View.GONE);
                }
            }
            @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel();
                if (view == web && currentWeb == webEpoch) {
                    cancelBridgeNavigationTimeout();
                    navigationFailed = true;
                    fail(R.string.auth_tls_error);
                }
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request,
                    android.webkit.WebResourceError error) {
                if (view == web && currentWeb == webEpoch && request.isForMainFrame()) {
                    cancelBridgeNavigationTimeout();
                    navigationFailed = true;
                    int code = error.getErrorCode();
                    boolean transport = code == WebViewClient.ERROR_HOST_LOOKUP
                            || code == WebViewClient.ERROR_CONNECT
                            || code == WebViewClient.ERROR_TIMEOUT
                            || code == WebViewClient.ERROR_IO;
                    if (!transport || !offerOfflineHistory()) fail(R.string.auth_network_error);
                }
            }
            @Override public void onReceivedHttpError(WebView view, WebResourceRequest request,
                    WebResourceResponse response) {
                if (view == web && currentWeb == webEpoch && request.isForMainFrame()
                        && response.getStatusCode() >= 400) {
                    cancelBridgeNavigationTimeout();
                    navigationFailed = true;
                    // Odoo deliberately conceals auth='user' routes from an anonymous WebView
                    // with 404. A remembered session can expire between launches, so only this
                    // exact private landing page recovers by opening the canonical Odoo login.
                    if (!loggingOut && response.getStatusCode() == 404 && BRIDGE.equals(intendedUrl)) {
                        recoverExpiredPrivateBridgeSession();
                        return;
                    }
                    if (response.getStatusCode() == 401 || response.getStatusCode() == 403)
                        purgeHistory();
                    fail(R.string.auth_network_error);
                }
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (closed || view != web || currentWeb != webEpoch || navigationFailed
                        || !sameOrigin(Uri.parse(url))) return;
                String path = Uri.parse(url).getPath();
                if (loggingOut) {
                    if (path != null && path.endsWith("/web/login")) {
                        loggingOut = false;
                        preferences().edit().putBoolean(REMEMBER, false).apply();
                        clearCookies(() -> {
                            if (closed) return;
                            showLoginForm();
                            openWeb(LOGIN);
                        });
                    }
                    return;
                }
                if (isLoginPath(path)) {
                    // A remembered Odoo session redirected from the bridge has expired.
                    if (BRIDGE.equals(intendedUrl)) purgeHistory();
                    pageReady = true;
                    signIn.setEnabled(true);
                    if (submitting) {
                        submitting = false;
                        status.setText(R.string.auth_native_invalid);
                    } else if (!verified) status.setText(R.string.auth_native_ready);
                    showLoginForm();
                } else if (path != null && path.endsWith("/web/login/totp")) {
                    submitting = false;
                    status.setText(R.string.auth_native_mfa);
                    nativeForm.setVisibility(View.GONE);
                    if (loginReleaseFooter != null) loginReleaseFooter.setVisibility(View.GONE);
                    shell.setVisibility(View.GONE);
                    showWebChallenge();
                } else if (isBridgeUrl(Uri.parse(url))) {
                    cancelBridgeNavigationTimeout();
                    hideWeb(); // Only the exact BChat bridge can initiate bootstrap.
                    if (!verified && !probing) verifySession();
                } else if (isErpPath(path)) {
                    divertErp(view, currentWeb);
                } else {
                    releaseWeb();
                    fail(R.string.auth_denied);
                }
            }
        });
        layout.addView(web, new LinearLayout.LayoutParams(-1, dp(1)));
        hideWeb();
        web.loadUrl(url);
        if (BRIDGE.equals(intendedUrl) && !loggingOut) scheduleBridgeNavigationTimeout(web, currentWeb);
        if (!loggingOut) status.setText(R.string.auth_loading);
    }

    private void submitLogin() {
        if (closed || submitting || probing || loggingOut || verified) return;
        Uri page = web == null || web.getUrl() == null ? null : Uri.parse(web.getUrl());
        if (!pageReady || !sameOrigin(page) || !isLoginPath(page.getPath())) {
            openWeb(LOGIN);
            return;
        }
        String username = loginInput.getText().toString().trim();
        String password = passwordInput.getText().toString();
        if (username.isEmpty() || password.isEmpty()) {
            status.setText(R.string.auth_native_required);
            return;
        }
        final int attempt = ++epoch;
        final int currentWeb = webEpoch;
        final int currentPage = pageEpoch;
        submitting = true;
        signIn.setEnabled(false);
        status.setText(R.string.auth_native_signing_in);
        // The official form performs CSRF and optional MFA/CAPTCHA handling on this same origin.
        String script = "(function(){var f=document.querySelector('form.oe_login_form');"
                + "if(location.origin!==" + JSONObject.quote(ORIGIN)
                + "||!(location.pathname==='/web/login'||/^\\/[A-Za-z][A-Za-z0-9_-]{1,15}\\/web\\/login$/.test(location.pathname))"
                + "||!f)return 'invalid';"
                + "var a=new URL(f.action,location.href),c=f.querySelector('input[name=csrf_token]'),"
                + "l=f.querySelector('input[name=login]'),p=f.querySelector('input[name=password]');"
                + "if(a.origin!==location.origin||a.pathname!=='/web/login'||!c||!c.value||!l||!p"
                + "||typeof f.requestSubmit!=='function')return 'invalid';"
                + "l.value=" + JSONObject.quote(username) + ";p.value=" + JSONObject.quote(password) + ";"
                + "f.requestSubmit();return 'submitted';})()";
        passwordInput.setText("");
        web.evaluateJavascript(script, result -> {
            if (closed || attempt != epoch || currentWeb != webEpoch || currentPage != pageEpoch) return;
            if (!"\"submitted\"".equals(result)) fail(R.string.auth_native_unavailable);
        });
        handler.postDelayed(() -> {
            if (closed || attempt != epoch || currentWeb != webEpoch || !submitting || verified || loggingOut) return;
            // A configured external CAPTCHA cannot complete in this same-origin-only build.
            fail(R.string.auth_native_unavailable);
            signIn.setEnabled(false);
            releaseWeb(); // Reject even a late login response after the attempt has timed out.
            clearCookies(() -> { if (!closed) signIn.setEnabled(true); });
        }, 8000);
    }

    private void verifySession() {
        if (closed || web == null || probing || loggingOut || verified || web.getUrl() == null
                || !isBridgeUrl(Uri.parse(web.getUrl()))) return;
        probing = true;
        resetTransportDiagnostic();
        submitting = false;
        status.setText(R.string.auth_verifying);
        final int attempt = ++epoch;
        final int currentWeb = webEpoch;
        final int currentPage = pageEpoch;
        closePort();
        WebMessagePort[] channel = web.createWebMessageChannel();
        replyPort = channel[0];
        replyPort.setWebMessageCallback(new WebMessagePort.WebMessageCallback() {
            @Override public void onMessage(WebMessagePort port, WebMessage message) {
                if (closed || attempt != epoch || !probing || port != replyPort || web == null
                        || currentWeb != webEpoch || currentPage != pageEpoch
                        || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl()))) return;
                acceptResponse(message.getData(), attempt);
            }
        });
        // The browser itself performs fetch with its own Odoo cookie. No cookie or password enters native HTTP.
        String script = "(function(){"
                + "if(location.href!==" + JSONObject.quote(BRIDGE) + ")return;"
                + "if(window.__bchatAuthPortHandler)window.removeEventListener('message',window.__bchatAuthPortHandler);"
                + "window.__bchatAuthPortHandler=function(e){var p=e.ports&&e.ports[0];if(!p)return;"
                + "window.removeEventListener('message',window.__bchatAuthPortHandler);"
                + "fetch('/bchat/api/v1/bootstrap',{credentials:'same-origin',redirect:'manual',cache:'no-store'})"
                + ".then(function(r){if(!r.body||!r.body.getReader)throw Error('stream required');"
                + "var reader=r.body.getReader(),decoder=new TextDecoder('utf-8',{fatal:true}),body='',size=0;"
                + "function read(){return reader.read().then(function(part){if(part.done){body+=decoder.decode();"
                + "return {nonce:" + attempt + ",status:r.status,type:r.headers.get('content-type')||'',url:r.url,body:body};}"
                + "size+=part.value.byteLength;if(size>8192){reader.cancel();throw Error('oversize');}"
                + "body+=decoder.decode(part.value,{stream:true});return read();});}return read();})"
                + ".then(function(x){p.postMessage(JSON.stringify(x));})"
                + ".catch(function(){p.postMessage(JSON.stringify({nonce:" + attempt + ",status:0}));});};"
                + "window.addEventListener('message',window.__bchatAuthPortHandler);})();";
        web.evaluateJavascript(script, ignored -> {
            if (closed || attempt != epoch || web == null || currentWeb != webEpoch || currentPage != pageEpoch
                    || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl()))) return;
            web.postWebMessage(new WebMessage("bootstrap", new WebMessagePort[]{channel[1]}), Uri.parse(ORIGIN));
        });
        handler.postDelayed(() -> {
            if (!closed && attempt == epoch && probing && currentWeb == webEpoch)
                if (!offerOfflineHistory()) fail(R.string.auth_network_error);
        }, 10000);
    }

    private static long positiveId(Object value) {
        if (!(value instanceof Number) || !value.toString().matches("[1-9][0-9]*"))
            throw new IllegalArgumentException("Invalid ID");
        long id = ((Number) value).longValue();
        if (id <= 0 || id > 2147483647L) throw new IllegalArgumentException("Invalid ID");
        return id;
    }

    private void acceptResponse(String data, int attempt) {
        try {
            if (data == null || data.length() > MAX_RESPONSE + 1024) throw new IllegalArgumentException("Envelope too large");
            JSONObject envelope = new JSONObject(data);
            if (envelope.optInt("nonce", -1) == attempt && envelope.optInt("status", -1) == 0) {
                if (!offerOfflineHistory()) fail(R.string.auth_network_error);
                return;
            }
            // Some Android WebView versions finish the private 404 document, then surface
            // the same unauthenticated state only through the bootstrap fetch below.
            if (envelope.optInt("nonce", -1) == attempt && envelope.optInt("status", -1) == 404) {
                recoverExpiredPrivateBridgeSession();
                return;
            }
            if (envelope.optInt("nonce", -1) == attempt
                    && (envelope.optInt("status", -1) == 401
                    || envelope.optInt("status", -1) == 403)) {
                purgeHistory();
                preferences().edit().putBoolean(REMEMBER, false).apply();
                fail(R.string.auth_denied);
                return;
            }
            String mime = envelope.getString("type").toLowerCase(java.util.Locale.ROOT).split(";", 2)[0].trim();
            if (envelope.getInt("nonce") != attempt || envelope.getInt("status") != 200
                    || !BOOTSTRAP.equals(envelope.getString("url"))
                    || !"application/json".equals(mime))
                throw new IllegalArgumentException("Unverified HTTP response");
            String body = envelope.getString("body");
            if (body.length() > MAX_RESPONSE) throw new IllegalArgumentException("Body too large");
            JSONObject result = new JSONObject(body);
            Object csrf = result.opt("csrf_token");
            if (positiveId(result.get("api_version")) != 1
                    || !"odoo_user_session".equals(result.getString("authentication"))
                    || !DATABASE.equals(result.getString("database"))
                    || result.opt("integration_enabled") != Boolean.FALSE
                    || !(csrf instanceof String) || ((String) csrf).trim().isEmpty()
                    || ((String) csrf).length() > 512)
                throw new IllegalArgumentException("Unexpected bootstrap contract");
            long uid = positiveId(result.get("user_id"));
            JSONArray companies = result.getJSONArray("company_ids");
            if (companies.length() == 0 || companies.length() > 128) throw new IllegalArgumentException("No companies");
            Set<Long> ids = new HashSet<>();
            for (int i = 0; i < companies.length(); i++) {
                long id = positiveId(companies.get(i));
                if (!ids.add(id)) throw new IllegalArgumentException("Duplicate company");
            }
            JSONObject capabilities = result.getJSONObject("capabilities");
            String[] expected = {"messages", "conversations", "attachments", "history", "membership",
                    "tasks", "shifts", "procurement", "report_events", "delivery_receipts", "read_receipts"};
            for (String key : expected) if (capabilities.opt(key) != Boolean.FALSE)
                throw new IllegalArgumentException("Capability mismatch");
            Iterator<String> keys = capabilities.keys();
            while (keys.hasNext()) if (capabilities.opt(keys.next()) != Boolean.FALSE)
                throw new IllegalArgumentException("Unexpected enabled capability");
            AccountScope nextAccount = new AccountScope(ORIGIN, DATABASE, uid);
            boolean canRemember = historyCache != null && taskOfflineCache != null;
            ++historyWriteGeneration; // Fence queued writes before account-switch cleanup.
            ++historyGlobalGeneration; // Also fence the previous Activity after a fast recreate.
            if (historyCache != null && taskOfflineCache != null) try {
                synchronized (historyStorageLock) {
                    historyCache.purgeOtherAccounts(nextAccount);
                    taskOfflineCache.purgeOtherAccounts(nextAccount);
                }
            }
            catch (RuntimeException storage) {
                // No cold-start access can be offered if account-switch cleanup failed.
                canRemember = false;
                preferences().edit().putBoolean(REMEMBER, false).apply();
                synchronized (historyStorageLock) {
                    historyCache.close();
                    historyCache = null;
                    taskOfflineCache.close();
                    taskOfflineCache = null;
                }
            }
            prepareOrderCompanyAccount(nextAccount);
            clearChatView();
            account = nextAccount; // The server authorizes all work.
            v1Companies.clear();
            v1Companies.addAll(ids);
            traceTransport("D02_V1_ACCEPTED");
            verified = true;
            probing = false;
            submitting = false;
            closePort();
            if (canRemember) CookieManager.getInstance().flush();
            preferences().edit().putBoolean(REMEMBER, canRemember).apply();
            showShell();
            verifyV2();
        } catch (Exception invalid) {
            if (attempt == epoch) fail(R.string.auth_denied);
        }
    }

    private interface V2Callback { void complete(int status, JSONObject body); }

    private void resetTransportDiagnostic() {
        if (!BuildConfig.BCHAT_TRANSPORT_DIAGNOSTICS) return;
        transportDiagnostic = "D00";
        traceTransport("D01_V1_START");
    }

    private void traceTransport(String stage) {
        if (!BuildConfig.BCHAT_TRANSPORT_DIAGNOSTICS) return;
        // Stage labels are fixed source strings or HTTP status integers only. Do not add URLs,
        // account identifiers, cookies, response bodies, or message content to this trace.
        String next = transportDiagnostic == null || transportDiagnostic.isEmpty()
                ? stage : transportDiagnostic + ">" + stage;
        transportDiagnostic = next.length() > 180 ? next.substring(next.length() - 180) : next;
        Log.i(TRANSPORT_LOG_TAG, stage);
    }

    private String transportDiagnosticNotice() {
        return BuildConfig.BCHAT_TRANSPORT_DIAGNOSTICS
                ? "\n" + getString(R.string.bchat_transport_diagnostic, transportDiagnostic) : "";
    }

    /** Fixed route labels only: no URL parameters, account identifiers, or server data are traced. */
    private String transportReadLabel(String path) {
        if (!BuildConfig.BCHAT_TRANSPORT_DIAGNOSTICS) return null;
        if (V2_BOOTSTRAP.equals(path)) return "V2B";
        if (V2_ROOMS.equals(path)) return "ROOMS";
        if (V1_BOOTSTRAP.equals(path)) return "V1B";
        return null;
    }

    private void closeV2Port() {
        ++v2Nonce;
        ++webV2GetFallbackGeneration;
        webV2GetFallbackBusy = false;
        v2Busy = false;
        if (v2Port != null) { v2Port.close(); v2Port = null; }
    }

    private void releaseV2Port() {
        v2Busy = false;
        if (v2Port != null) { v2Port.close(); v2Port = null; }
    }

    /**
     * Repeat only authenticated GET requests after a failed WebMessagePort delivery.  The retry
     * stays in the same, authenticated WebView; it never extracts cookies or retries a POST.
     */
    private boolean fetchVerifiedGetInWebView(String method, String path, int maximum,
                                              int expectedWeb, int expectedPage, int expectedEpoch,
                                              V2Callback callback) {
        if (!"GET".equals(method) || closed || webV2GetFallbackBusy || callback == null
                || web == null || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl()))) return false;
        final int fallback = ++webV2GetFallbackGeneration;
        final String slot = "__bchatReadFallback" + fallback;
        final String diagnosticRead = transportReadLabel(path);
        if (diagnosticRead != null) traceTransport("D12_" + diagnosticRead + "_DIRECT_START");
        webV2GetFallbackBusy = true;
        releaseV2Port();
        // The direct reader occupies the same authenticated WebView. Keep the shared busy
        // signal true so push registration and optional reads wait instead of racing it.
        v2Busy = true;
        String script = "(function(){if(location.href!==" + JSONObject.quote(BRIDGE) + ")return;"
                + "var u=new URL(" + JSONObject.quote(path) + ",location.origin);"
                + "if(u.origin!==location.origin)return;"
                + "var done=function(x){window[" + JSONObject.quote(slot) + "]=JSON.stringify(x);};"
                + "fetch(u.href,{method:'GET',credentials:'same-origin',redirect:'manual',cache:'no-store',headers:{Accept:'application/json'}})"
                + ".then(function(r){if(r.type==='opaqueredirect')return {nonce:" + fallback
                + ",status:401,type:'application/json',url:u.href,body:'{}'};"
                + "if(!r.body||!r.body.getReader)throw Error('stream');"
                + "var rd=r.body.getReader(),d=new TextDecoder('utf-8',{fatal:true}),b='',n=0;"
                + "function read(){return rd.read().then(function(x){if(x.done){b+=d.decode();return {nonce:"
                + fallback + ",status:r.status,type:r.headers.get('content-type')||'',url:r.url,body:b};}"
                + "n+=x.value.byteLength;if(n>" + maximum + "){rd.cancel();throw Error('size');}"
                + "b+=d.decode(x.value,{stream:true});return read();});}return read();})"
                + ".then(done).catch(function(){done({nonce:" + fallback + ",status:0});});})();";
        web.evaluateJavascript(script, ignored -> {
            if (diagnosticRead != null) traceTransport("D13_" + diagnosticRead + "_FETCH_DISPATCHED");
            pollVerifiedGetFallback(slot, fallback, path, maximum,
                    expectedWeb, expectedPage, expectedEpoch, callback, 0);
        });
        return true;
    }

    /**
     * The affected Android WebView can receive direct fetch callbacks but drops transferred
     * WebMessagePorts. Push registration uses the bounded direct callback; native media uses it
     * only to issue a capability and streams no file bytes through WebView.
     *
     * This sends one request only. The polling below merely reads the result already produced
     * by the WebView; it never repeats a registration whose outcome might be uncertain.
     */
    private boolean registerPushDirectlyInWebView(String payload, V2Callback callback) {
        return postSmallFormDirectlyInWebView(V2_PUSH_REGISTER, "payload", payload, callback);
    }

    /**
     * Sends only a bounded, idempotency-safe control payload in the authenticated WebView.
     * Native media bytes never use this path: it issues a one-time capability only.
     */
    private boolean postSmallFormDirectlyInWebView(String path, String field, String payload,
                                                   V2Callback callback) {
        boolean supported = V2_PUSH_REGISTER.equals(path)
                || path.matches("/bchat/api/v2/rooms/[1-9][0-9]*/mobile-upload-grants");
        if (closed || !verified || account == null || csrfToken == null || callback == null
                || payload == null || payload.length() > (V2_PUSH_REGISTER.equals(path) ? 8192 : 4096) || field == null
                || !field.matches("[a-z_]{1,32}") || !supported || webV2GetFallbackBusy
                || v2Busy || web == null || web.getUrl() == null
                || !isBridgeUrl(Uri.parse(web.getUrl()))) return false;
        final int fallback = ++webV2GetFallbackGeneration;
        final String slot = "__bchatSmallPost" + fallback;
        final int currentWeb = webEpoch;
        final int currentPage = pageEpoch;
        final int currentEpoch = epoch;
        webV2GetFallbackBusy = true;
        releaseV2Port();
        v2Busy = true;
        String script = "(function(){if(location.href!==" + JSONObject.quote(BRIDGE) + ")return;"
                + "var u=new URL(" + JSONObject.quote(path) + ",location.origin);"
                + "if(u.origin!==location.origin||u.pathname!==" + JSONObject.quote(path)
                + ")return;var done=function(x){window[" + JSONObject.quote(slot)
                + "]=JSON.stringify(x);};"
                + "fetch(u.href,{method:'POST',credentials:'same-origin',redirect:'manual',cache:'no-store',"
                + "headers:{Accept:'application/json','Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'},"
                + "body:(function(){var p=new URLSearchParams();p.set('csrf_token',"
                + JSONObject.quote(csrfToken) + ");p.set(" + JSONObject.quote(field) + ","
                + JSONObject.quote(payload) + ");return p.toString();})()})"
                + ".then(function(r){if(r.type==='opaqueredirect')return {nonce:" + fallback
                + ",status:401,type:'application/json',url:u.href,body:'{}'};"
                + "if(!r.body||!r.body.getReader)throw Error('stream');"
                + "var rd=r.body.getReader(),d=new TextDecoder('utf-8',{fatal:true}),b='',n=0;"
                + "function read(){return rd.read().then(function(x){if(x.done){b+=d.decode();return {nonce:"
                + fallback + ",status:r.status,type:r.headers.get('content-type')||'',url:r.url,body:b};}"
                + "n+=x.value.byteLength;if(n>" + MAX_V2_RESPONSE + "){rd.cancel();throw Error('size');}"
                + "b+=d.decode(x.value,{stream:true});return read();});}return read();})"
                + ".then(done).catch(function(){done({nonce:" + fallback + ",status:0});});})();";
        web.evaluateJavascript(script, ignored -> pollVerifiedGetFallback(slot, fallback,
                path, MAX_V2_RESPONSE, currentWeb, currentPage, currentEpoch, callback, 0));
        return true;
    }

    private void pollVerifiedGetFallback(String slot, int fallback, String path, int maximum,
                                         int expectedWeb, int expectedPage, int expectedEpoch,
                                         V2Callback callback, int attempt) {
        if (fallback != webV2GetFallbackGeneration) return;
        if (closed || web == null || expectedWeb != webEpoch || expectedPage != pageEpoch
                || expectedEpoch != epoch || web.getUrl() == null
                || !isBridgeUrl(Uri.parse(web.getUrl()))) {
            String label = transportReadLabel(path);
            if (label != null) traceTransport("D14_" + label + "_CONTEXT_CHANGED");
            webV2GetFallbackBusy = false;
            v2Busy = false;
            return;
        }
        String read = "(function(){var value=window[" + JSONObject.quote(slot)
                + "];if(value!==undefined){delete window[" + JSONObject.quote(slot)
                + "];return value;}return null;})()";
        web.evaluateJavascript(read, value -> {
            if (fallback != webV2GetFallbackGeneration) return;
            if (value == null || "null".equals(value)) {
                if (attempt < 60) handler.postDelayed(() -> pollVerifiedGetFallback(slot, fallback,
                        path, maximum, expectedWeb, expectedPage, expectedEpoch, callback, attempt + 1), 100);
                else {
                    String label = transportReadLabel(path);
                    if (label != null) traceTransport("D14_" + label + "_SLOT_TIMEOUT");
                    completeVerifiedGetFallback(fallback, path, 0, null, expectedWeb, expectedPage,
                            expectedEpoch, callback);
                }
                return;
            }
            String label = transportReadLabel(path);
            if (label != null) traceTransport("D14_" + label + "_SLOT_RECEIVED");
            int statusCode = 0;
            JSONObject body = null;
            try {
                String data = new JSONArray("[" + value + "]").getString(0);
                if (data.length() > maximum * 6 + 4096) throw new IllegalArgumentException();
                JSONObject response = new JSONObject(data);
                if (response.getInt("nonce") != fallback) throw new IllegalArgumentException();
                String finalUrl = response.getString("url");
                Uri finalUri = Uri.parse(finalUrl);
                if (sameOrigin(finalUri) && isLoginPath(finalUri.getPath())) {
                    statusCode = 401;
                    body = new JSONObject();
                } else {
                    if (!(ORIGIN + path).equals(finalUrl)) throw new IllegalArgumentException();
                    statusCode = response.getInt("status");
                    if (statusCode != 404 && statusCode != 503) {
                        String mime = response.getString("type").toLowerCase(Locale.ROOT)
                                .split(";", 2)[0].trim();
                        if (!"application/json".equals(mime)) throw new IllegalArgumentException();
                        String content = response.getString("body");
                        if (content.length() > maximum || statusCode < 200 || statusCode > 599)
                            throw new IllegalArgumentException();
                        body = new JSONObject(content);
                    }
                }
            } catch (Exception ignored) {
                if (label != null) traceTransport("D15_" + label + "_RESPONSE_REJECTED");
                statusCode = 0;
                body = null;
            }
            if (label != null && statusCode == 0)
                traceTransport("D15_" + label + "_WEB_FETCH_ZERO");
            completeVerifiedGetFallback(fallback, path, statusCode, body, expectedWeb, expectedPage,
                    expectedEpoch, callback);
        });
    }

    private void completeVerifiedGetFallback(int fallback, String path, int statusCode, JSONObject body,
                                             int expectedWeb, int expectedPage, int expectedEpoch,
                                             V2Callback callback) {
        if (fallback != webV2GetFallbackGeneration) return;
        webV2GetFallbackBusy = false;
        v2Busy = false;
        if (closed || expectedWeb != webEpoch || expectedPage != pageEpoch || expectedEpoch != epoch) return;
        String label = transportReadLabel(path);
        if (label != null) traceTransport("D16_" + label + "_CALLBACK_" + statusCode);
        callback.complete(statusCode, body);
        handler.post(this::runQueuedOrderLoad);
        handler.post(this::maybeProbeOrderCapability);
        scheduleOrderImagePump();
        handler.post(this::flushLiveUi);
    }

    /**
     * Authenticated reads must not depend on transferred WebMessagePorts.  The affected Android
     * WebView can read bootstrap through the direct callback but drops the next transferred port
     * (normally /rooms), leaving a valid session on a misleading connection-error shell.
     *
     * This applies only to bounded idempotent GET routes.  Writes retain the port path and their
     * existing uncertain-write handling; this method never repeats or converts a POST.
     */
    private boolean fetchV2ReadDirectlyInWebView(String path, V2Callback callback) {
        if (closed || !verified || account == null || v2Busy || webV2GetFallbackBusy
                || web == null || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl()))
                || !(V1_BOOTSTRAP.equals(path)
                        || path.matches("/bchat/api/v2/[A-Za-z0-9/?=&_%~.-]+"))) return false;
        String label = transportReadLabel(path);
        if (label != null) traceTransport("D11_" + label + "_READ_START");
        int maximum = V2_BOOTSTRAP.equals(path) || V1_BOOTSTRAP.equals(path)
                ? MAX_RESPONSE : MAX_V2_RESPONSE;
        return fetchVerifiedGetInWebView("GET", path, maximum,
                webEpoch, pageEpoch, epoch, callback);
    }

    /** Every request runs inside the already authenticated, same-origin WebView. */
    private void fetchV2(String method, String path, String payload, V2Callback callback) {
        // A device trace proved bootstrap succeeds but the subsequent transferred /rooms port
        // does not.  Use the bounded direct callback for every authenticated read, not only
        // bootstrap; POST routes remain on their separate write-safe path below.
        if ("GET".equals(method) && payload == null
                && fetchV2ReadDirectlyInWebView(path, callback)) return;
        fetchV2Internal(method, path, payload, null, callback);
    }

    private void fetchV2Internal(String method, String path, String payload,
                                 String avatarBase64, V2Callback callback) {
        if (closed || !verified || account == null || web == null || v2Busy || webV2GetFallbackBusy || callback == null
                || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl()))
                || !(V1_BOOTSTRAP.equals(path) || path.matches("/bchat/api/v2/[A-Za-z0-9/?=&_%~.-]+"))
                || !("GET".equals(method) || "POST".equals(method))
                || ("POST".equals(method) && (csrfToken == null
                        || (payload == null && avatarBase64 == null)))
                || (avatarBase64 != null && (!"POST".equals(method)
                        || !path.matches("/bchat/api/v2/rooms/[1-9][0-9]*/avatar")
                        || avatarBase64.length() > 700000))) {
            if (callback != null) callback.complete(0, null);
            return;
        }
        cancelOrderImageFetch();
        v2Busy = true;
        final int request = ++v2Nonce;
        final int currentWeb = webEpoch;
        final int currentPage = pageEpoch;
        final int currentEpoch = epoch;
        final int maximum = V2_BOOTSTRAP.equals(path) || V1_BOOTSTRAP.equals(path)
                ? MAX_RESPONSE : MAX_V2_RESPONSE;
        WebMessagePort[] channel = web.createWebMessageChannel();
        v2Port = channel[0];
        v2Port.setWebMessageCallback(new WebMessagePort.WebMessageCallback() {
            @Override public void onMessage(WebMessagePort port, WebMessage message) {
                if (closed || !v2Busy || request != v2Nonce || port != v2Port || web == null
                        || currentWeb != webEpoch || currentPage != pageEpoch || currentEpoch != epoch
                        || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl()))) return;
                int statusCode = 0;
                JSONObject body = null;
                try {
                    String data = message.getData();
                    if (data == null || data.length() > maximum * 6 + 4096) throw new IllegalArgumentException();
                    JSONObject response = new JSONObject(data);
                    String mime = response.getString("type").toLowerCase(java.util.Locale.ROOT)
                            .split(";", 2)[0].trim();
                    if (response.getInt("nonce") != request) throw new IllegalArgumentException();
                    String finalUrl = response.getString("url");
                    Uri finalUri = Uri.parse(finalUrl);
                    if (sameOrigin(finalUri) && isLoginPath(finalUri.getPath())) {
                        statusCode = 401;
                        body = new JSONObject();
                        throw new SessionRedirect();
                    }
                    if (!(ORIGIN + path).equals(finalUrl))
                        throw new IllegalArgumentException();
                    statusCode = response.getInt("status");
                    if (statusCode == 404 || statusCode == 503) {
                        // A missing or stopped optional module may return an HTML Odoo page.
                        body = null;
                        throw new OptionalModuleUnavailable();
                    }
                    if (!"application/json".equals(mime)) throw new IllegalArgumentException();
                    String content = response.getString("body");
                    if (content.length() > maximum) throw new IllegalArgumentException();
                    if (statusCode < 200 || statusCode > 599) throw new IllegalArgumentException();
                    body = new JSONObject(content);
                } catch (SessionRedirect expected) {
                    // A manual same-origin login redirect is an expired session, not a network retry.
                } catch (OptionalModuleUnavailable expected) {
                    // Keep the authenticated shell and report feature availability truthfully.
                } catch (Exception invalid) {
                    if (fetchVerifiedGetInWebView(method, path, maximum, currentWeb, currentPage,
                            currentEpoch, callback)) return;
                    statusCode = 0;
                    body = null;
                }
                releaseV2Port();
                callback.complete(statusCode, body);
                handler.post(OdooIdentityActivity.this::runQueuedOrderLoad);
                handler.post(OdooIdentityActivity.this::maybeProbeOrderCapability);
                scheduleOrderImagePump();
                handler.post(OdooIdentityActivity.this::flushLiveUi);
            }
        });
        String script = "(function(){"
                + "var h=function(e){var p=e.ports&&e.ports[0];if(!p||e.data!=='v2')return;window.removeEventListener('message',h);"
                + "if(location.href!==" + JSONObject.quote(BRIDGE) + "){p.postMessage('{}');return;}"
                + "var path=" + JSONObject.quote(path) + ",u=new URL(path,location.origin);"
                + "if(u.origin!==location.origin||!(u.pathname.startsWith('/bchat/api/v2/')||u.pathname==='/bchat/api/v1/bootstrap')){p.postMessage('{}');return;}"
                + "var options={method:" + JSONObject.quote(method)
                + ",credentials:'same-origin',redirect:'manual',cache:'no-store',headers:{Accept:'application/json'}};"
                + (avatarBase64 == null ? "" : "var raw=atob(" + JSONObject.quote(avatarBase64)
                + "),bytes=new Uint8Array(raw.length);for(var i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);"
                + "var form=new FormData();form.append('csrf_token'," + JSONObject.quote(csrfToken)
                + ");form.append('file',new Blob([bytes],{type:'image/jpeg'}),'group.jpg');"
                + "options.body=form;")
                + (payload == null ? "" : "options.headers['Content-Type']='application/x-www-form-urlencoded;charset=UTF-8';"
                + "options.body=new URLSearchParams({csrf_token:" + JSONObject.quote(csrfToken)
                + ",payload:" + JSONObject.quote(payload) + "}).toString();")
                + "fetch(u.href,options).then(function(r){if(r.type==='opaqueredirect')return {nonce:"
                + request + ",status:401,type:'application/json',url:u.href,body:'{}'};"
                + "if(!r.body||!r.body.getReader)throw Error('stream');"
                + "var rd=r.body.getReader(),d=new TextDecoder('utf-8',{fatal:true}),b='',n=0;"
                + "function read(){return rd.read().then(function(x){if(x.done){b+=d.decode();return {nonce:"
                + request + ",status:r.status,type:r.headers.get('content-type')||'',url:r.url,body:b};}"
                + "n+=x.value.byteLength;if(n>" + maximum + "){rd.cancel();throw Error('size');}"
                + "b+=d.decode(x.value,{stream:true});return read();});}return read();})"
                + ".then(function(x){p.postMessage(JSON.stringify(x));})"
                + ".catch(function(){p.postMessage(JSON.stringify({nonce:" + request + ",status:0}));});};"
                + "window.addEventListener('message',h);})();";
        web.evaluateJavascript(script, ignored -> {
            if (closed || !v2Busy || request != v2Nonce || web == null || currentWeb != webEpoch
                    || currentPage != pageEpoch || currentEpoch != epoch || web.getUrl() == null
                    || !isBridgeUrl(Uri.parse(web.getUrl()))) return;
            web.postWebMessage(new WebMessage("v2", new WebMessagePort[]{channel[1]}), Uri.parse(ORIGIN));
        });
        handler.postDelayed(() -> {
            if (!closed && v2Busy && request == v2Nonce) {
                if (fetchVerifiedGetInWebView(method, path, maximum, currentWeb, currentPage,
                        currentEpoch, callback)) return;
                closeV2Port();
                callback.complete(0, null);
                handler.post(this::runQueuedOrderLoad);
                handler.post(this::maybeProbeOrderCapability);
                scheduleOrderImagePump();
                handler.post(this::flushLiveUi);
            }
        }, 12000);
    }

    /** A separate bounded channel prevents a busy catalogue or media request dropping change hints. */
    private static final class LiveRequest {
        final String method, path, formKey, formValue;
        final AccountScope scope;
        final V2Callback callback;
        LiveRequest(String method, String path, String formKey, String formValue,
                    AccountScope scope, V2Callback callback) {
            this.method = method; this.path = path; this.formKey = formKey;
            this.formValue = formValue; this.scope = scope; this.callback = callback;
        }
    }

    private static final class PrivateAvatarRequest {
        final String key, path;
        PrivateAvatarRequest(String key, String path) { this.key = key; this.path = path; }
    }

    private void closeLiveSync() {
        liveStarted = false;
        busConnected = false;
        feedQueued = false;
        snapshotInProgress = false;
        ++liveNonce;
        ++busNonce;
        if (feedTimer != null) { handler.removeCallbacks(feedTimer); feedTimer = null; }
        if (busReconnect != null) { handler.removeCallbacks(busReconnect); busReconnect = null; }
        if (livePort != null) { livePort.close(); livePort = null; }
        if (busPort != null) { busPort.close(); busPort = null; }
        liveBusy = false;
        liveQueue.clear();
        pendingAcknowledgements.clear();
        if (web != null && web.getUrl() != null && isBridgeUrl(Uri.parse(web.getUrl())))
            web.evaluateJavascript("if(window.__bchatLiveBus){window.__bchatLiveBus.close();window.__bchatLiveBus=null}", null);
    }

    private boolean liveReady(AccountScope scope) {
        return liveStarted && liveForeground && !closed && verified && scope != null
                && account == scope && web != null && web.getUrl() != null
                && isBridgeUrl(Uri.parse(web.getUrl()));
    }

    private void enqueueLive(String method, String path, String formKey, String formValue,
                             V2Callback callback) {
        AccountScope scope = account;
        if (!liveReady(scope) || callback == null || !path.matches("/bchat/api/v2/[A-Za-z0-9/?=&_%~.-]+")
                || !("GET".equals(method) || "POST".equals(method))
                || ("POST".equals(method) && (csrfToken == null || formKey == null))) {
            if (callback != null) callback.complete(0, null);
            return;
        }
        if (liveQueue.size() >= 128) { callback.complete(0, null); return; }
        LiveRequest request = new LiveRequest(method, path, formKey, formValue, scope, callback);
        if (path.startsWith(V2_CHANGES)) liveQueue.addFirst(request);
        else liveQueue.addLast(request);
        pumpLiveQueue();
    }

    private void pumpLiveQueue() {
        if (liveBusy || liveQueue.isEmpty()) return;
        LiveRequest item = liveQueue.removeFirst();
        if (!liveReady(item.scope)) { item.callback.complete(0, null); pumpLiveQueue(); return; }
        liveBusy = true;
        final int nonce = ++liveNonce, currentWeb = webEpoch, currentPage = pageEpoch,
                currentEpoch = epoch;
        final int maximum = MAX_V2_RESPONSE;
        final WebMessagePort[] channel = web.createWebMessageChannel();
        livePort = channel[0];
        livePort.setWebMessageCallback(new WebMessagePort.WebMessageCallback() {
            @Override public void onMessage(WebMessagePort port, WebMessage message) {
                if (!liveBusy || nonce != liveNonce || port != livePort) return;
                int statusCode = 0;
                JSONObject body = null;
                try {
                    if (!liveReady(item.scope) || currentWeb != webEpoch || currentPage != pageEpoch
                            || currentEpoch != epoch || message.getData() == null
                            || message.getData().length() > maximum * 6 + 4096)
                        throw new IllegalArgumentException();
                    JSONObject envelope = new JSONObject(message.getData());
                    if (envelope.getInt("nonce") != nonce) throw new IllegalArgumentException();
                    Uri finalUri = Uri.parse(envelope.getString("url"));
                    if (sameOrigin(finalUri) && isLoginPath(finalUri.getPath())) {
                        statusCode = 401;
                        throw new SessionRedirect();
                    }
                    if (!(ORIGIN + item.path).equals(finalUri.toString()))
                        throw new IllegalArgumentException();
                    statusCode = envelope.getInt("status");
                    if (statusCode == 404 || statusCode == 503) throw new OptionalModuleUnavailable();
                    if (!"application/json".equals(envelope.getString("type")
                            .toLowerCase(Locale.ROOT).split(";", 2)[0].trim()))
                        throw new IllegalArgumentException();
                    String raw = envelope.getString("body");
                    if (raw.length() > maximum || statusCode < 200 || statusCode > 599)
                        throw new IllegalArgumentException();
                    body = new JSONObject(raw);
                } catch (SessionRedirect | OptionalModuleUnavailable expected) {
                    // Optional endpoints may not exist during a staged server rollout.
                } catch (Exception invalid) { statusCode = 0; body = null; }
                finishLiveRequest(nonce, item, statusCode, body);
            }
        });
        String script = "(function(){var h=function(e){var p=e.ports&&e.ports[0];"
                + "if(!p||e.data!=='bchat-live')return;window.removeEventListener('message',h);"
                + "if(location.href!==" + JSONObject.quote(BRIDGE) + "){p.postMessage('{}');return;}"
                + "var u=new URL(" + JSONObject.quote(item.path) + ",location.origin);"
                + "if(u.origin!==location.origin||!u.pathname.startsWith('/bchat/api/v2/')){p.postMessage('{}');return;}"
                + "var o={method:" + JSONObject.quote(item.method)
                + ",credentials:'same-origin',redirect:'manual',cache:'no-store',headers:{Accept:'application/json'}};"
                + ("POST".equals(item.method)
                    ? "o.headers['Content-Type']='application/x-www-form-urlencoded;charset=UTF-8';"
                    + "o.body=new URLSearchParams({csrf_token:" + JSONObject.quote(csrfToken)
                    + (item.formKey.isEmpty() ? "" : "," + item.formKey + ":" + JSONObject.quote(item.formValue))
                    + "}).toString();" : "")
                + "fetch(u.href,o).then(function(r){if(r.type==='opaqueredirect')return {nonce:"
                + nonce + ",status:401,type:'application/json',url:u.href,body:'{}'};"
                + "if(!r.body||!r.body.getReader)throw Error('stream');"
                + "var rd=r.body.getReader(),d=new TextDecoder('utf-8',{fatal:true}),b='',n=0;"
                + "function read(){return rd.read().then(function(x){if(x.done){b+=d.decode();return {nonce:"
                + nonce + ",status:r.status,type:r.headers.get('content-type')||'',url:r.url,body:b};}"
                + "n+=x.value.byteLength;if(n>" + maximum + "){rd.cancel();throw Error('size');}"
                + "b+=d.decode(x.value,{stream:true});return read();});}return read();})"
                + ".then(function(x){p.postMessage(JSON.stringify(x));})"
                + ".catch(function(){p.postMessage(JSON.stringify({nonce:" + nonce + ",status:0}));});};"
                + "window.addEventListener('message',h);})();";
        web.evaluateJavascript(script, ignored -> {
            if (!liveBusy || nonce != liveNonce || !liveReady(item.scope)
                    || currentWeb != webEpoch || currentPage != pageEpoch || currentEpoch != epoch) return;
            web.postWebMessage(new WebMessage("bchat-live", new WebMessagePort[]{channel[1]}), Uri.parse(ORIGIN));
        });
        handler.postDelayed(() -> {
            if (liveBusy && nonce == liveNonce) finishLiveRequest(nonce, item, 0, null);
        }, 10000);
    }

    private void finishLiveRequest(int nonce, LiveRequest item, int statusCode, JSONObject body) {
        if (!liveBusy || nonce != liveNonce) return;
        liveBusy = false;
        if (livePort != null) { livePort.close(); livePort = null; }
        item.callback.complete(statusCode, body);
        handler.post(this::pumpLiveQueue);
    }

    private static long nonnegativeCursor(Object value) {
        if (!(value instanceof Number) || !value.toString().matches("(?:0|[1-9][0-9]*)"))
            throw new IllegalArgumentException("Invalid change cursor");
        long cursor = ((Number) value).longValue();
        if (cursor < 0 || cursor > 2147483647L) throw new IllegalArgumentException("Invalid change cursor");
        return cursor;
    }

    private void startLiveSync() {
        if (liveStarted || !liveForeground || !verified || account == null || csrfToken == null) return;
        liveStarted = true;
        feedCursor = getSharedPreferences(LIVE_PREFS, MODE_PRIVATE).getLong(account.key, 0);
        if (feedCursor < 0 || feedCursor > 2147483647L) feedCursor = 0;
        feedFailures = busFailures = 0;
        scheduleFeed(0);
        connectLiveBus();
    }

    private void scheduleFeed(long delayMs) {
        if (feedTimer != null) handler.removeCallbacks(feedTimer);
        if (!liveReady(account)) return;
        feedTimer = () -> { feedTimer = null; requestFeed(); };
        handler.postDelayed(feedTimer, Math.max(0, delayMs));
    }

    private void requestFeed() {
        if (!liveReady(account) || feedQueued || snapshotInProgress) return;
        if (SystemClock.elapsedRealtime() < feedRetryAt) {
            scheduleFeed(feedRetryAt - SystemClock.elapsedRealtime()); return;
        }
        final AccountScope scope = account;
        final long requestedAfter = feedCursor;
        feedQueued = true;
        enqueueLive("GET", V2_CHANGES + "?after=" + requestedAfter
                + "&limit=100&permissions_version=1", null, null,
                (statusCode, result) -> {
                    feedQueued = false;
                    if (!liveReady(scope)) return;
                    if (statusCode == 401) { logout(); return; }
                    try {
                        if (statusCode != 200 || result == null
                                || nonnegativeCursor(result.get("api_version")) != 2)
                            throw new IllegalArgumentException();
                        long watermark = nonnegativeCursor(result.get("watermark"));
                        if (result.optBoolean("reset_required", false)) {
                            if (!result.optBoolean("snapshot_required", false))
                                throw new IllegalArgumentException();
                            snapshotChanges(scope, watermark, 0, 0, 0);
                            return;
                        }
                        JSONArray rows = result.getJSONArray("changes");
                        if (rows.length() > 100) throw new IllegalArgumentException();
                        long next = nonnegativeCursor(result.get("next_after"));
                        if (next < requestedAfter || next > watermark
                                || !(result.opt("has_more") instanceof Boolean))
                            throw new IllegalArgumentException();
                        long last = requestedAfter;
                        for (int i = 0; i < rows.length(); i++) {
                            JSONObject change = rows.getJSONObject(i);
                            long seq = nonnegativeCursor(change.get("seq"));
                            if (seq <= last || seq > next) throw new IllegalArgumentException();
                            last = seq;
                            applyLiveHint(change);
                        }
                        if (result.getBoolean("has_more") && next == requestedAfter)
                            throw new IllegalArgumentException();
                        if (!getSharedPreferences(LIVE_PREFS, MODE_PRIVATE).edit()
                                .putLong(scope.key, next).commit()) throw new IllegalStateException();
                        feedCursor = next;
                        feedFailures = 0;
                        feedRetryAt = 0;
                        flushLiveUi();
                        scheduleFeed(result.getBoolean("has_more") ? 0 : busConnected ? 2500 : 850);
                    } catch (Exception invalid) { retryFeed(); }
                });
    }

    private void retryFeed() {
        snapshotInProgress = false;
        feedFailures = Math.min(6, feedFailures + 1);
        long delay = Math.min(30000L, 500L << (feedFailures - 1));
        feedRetryAt = SystemClock.elapsedRealtime() + delay;
        scheduleFeed(delay);
    }

    private void applyLiveHint(JSONObject change) throws Exception {
        String kind = change.getString("kind");
        long roomId = change.has("room_id") ? positiveId(change.get("room_id")) : 0;
        if ("revoked".equals(kind)) {
            if (historyCache != null && account != null && roomId > 0)
                try { purgeCachedRoom(account, roomId); }
                catch (RuntimeException storage) { purgeHistory(); }
            liveRoomsDirty = true;
            if (selectedRoom != null && selectedRoom.id == roomId) {
                showRooms();
                liveMessagesDirty = false;
            }
        } else if ("task_revoked".equals(kind)) {
            liveTasksDirty = true;
        } else if ("room".equals(kind)) {
            liveRoomsDirty = true;
        } else if ("message".equals(kind) || "receipt".equals(kind)) {
            liveRoomsDirty = true;
            if (selectedRoom != null && selectedRoom.id == roomId) liveMessagesDirty = true;
        } else if ("task".equals(kind)) {
            liveTasksDirty = true;
            if (roomId > 0) liveRoomsDirty = true;
        } else if ("order".equals(kind)) {
            liveOrdersDirty = true;
        } else if ("permissions".equals(kind) || "permission".equals(kind)) {
            lastPermissionRefreshAt = 0;
            handler.post(this::refreshPermissionSet);
        } else throw new IllegalArgumentException("Unknown BChat change kind");
    }

    private void snapshotChanges(AccountScope scope, long watermark, int sectionIndex,
                                 long beforeId, int pages) {
        if (!liveReady(scope)) return;
        snapshotInProgress = true;
        if (sectionIndex == 3) {
            snapshotInProgress = false;
            if (!getSharedPreferences(LIVE_PREFS, MODE_PRIVATE).edit()
                    .putLong(scope.key, watermark).commit()) { retryFeed(); return; }
            feedCursor = watermark;
            feedFailures = 0;
            liveRoomsDirty = liveTasksDirty = liveOrdersDirty = true;
            if (selectedRoom != null) liveMessagesDirty = true;
            flushLiveUi();
            scheduleFeed(0);
            return;
        }
        if (pages >= 1000) { retryFeed(); return; }
        String section = new String[]{"rooms", "tasks", "orders"}[sectionIndex];
        String path = V2_CHANGES + "/snapshot?section=" + section + "&watermark=" + watermark
                + (beforeId > 0 ? "&before_id=" + beforeId : "");
        enqueueLive("GET", path, null, null, (statusCode, result) -> {
            if (!liveReady(scope)) return;
            if (statusCode == 401) { logout(); return; }
            try {
                if (statusCode != 200 || result == null || nonnegativeCursor(result.get("api_version")) != 2
                        || nonnegativeCursor(result.get("snapshot_watermark")) != watermark
                        || !section.equals(result.getString("section")))
                    throw new IllegalArgumentException();
                JSONArray rows = result.getJSONArray(section);
                if (rows.length() > 30) throw new IllegalArgumentException();
                Object nextValue = result.opt("next_before_id");
                long next = nextValue == null || nextValue == JSONObject.NULL
                        ? 0 : positiveId(nextValue);
                if (next > 0 && (rows.length() == 0 || next == beforeId))
                    throw new IllegalArgumentException();
                if (next > 0) snapshotChanges(scope, watermark, sectionIndex, next, pages + 1);
                else snapshotChanges(scope, watermark, sectionIndex + 1, 0, pages + 1);
            } catch (Exception invalid) { retryFeed(); }
        });
    }

    private void flushLiveUi() {
        if (!liveReady(account) || chatRoot == null || chatRoot.getVisibility() != View.VISIBLE) return;
        if (v2Busy) {
            if (!liveUiScheduled) {
                liveUiScheduled = true;
                handler.postDelayed(() -> { liveUiScheduled = false; flushLiveUi(); }, 200);
            }
            return;
        }
        if (liveRoomsDirty) { liveRoomsDirty = false; loadRooms(); return; }
        if (liveMessagesDirty && selectedRoom != null) {
            liveMessagesDirty = false;
            loadMessages(0);
            return;
        }
        if (liveTasksDirty && "tasks".equals(visibleSection) && tasksAvailable) {
            liveTasksDirty = false;
            loadTasks(0);
            return;
        }
        if (liveOrdersDirty && "orders".equals(visibleSection) && ordersAvailable) {
            liveOrdersDirty = false;
            if (orderReceiving) loadReceipts(0);
            else if (orderMine) loadOrderSummaries(0);
        }
    }

    private void connectLiveBus() {
        if (!liveReady(account) || busPort != null) return;
        final AccountScope scope = account;
        final int nonce = ++busNonce, currentWeb = webEpoch, currentPage = pageEpoch;
        final WebMessagePort[] channel = web.createWebMessageChannel();
        busPort = channel[0];
        busPort.setWebMessageCallback(new WebMessagePort.WebMessageCallback() {
            @Override public void onMessage(WebMessagePort port, WebMessage message) {
                if (port != busPort || nonce != busNonce || !liveReady(scope)
                        || currentWeb != webEpoch || currentPage != pageEpoch) return;
                String signal = message.getData();
                if (signal == null || signal.length() > 64) return;
                if ("open".equals(signal)) { busConnected = true; busFailures = 0; scheduleFeed(0); }
                else if ("wake".equals(signal)) scheduleFeed(0);
                else if ("closed".equals(signal)) {
                    busConnected = false;
                    if (busPort != null) { busPort.close(); busPort = null; }
                    busFailures = Math.min(5, busFailures + 1);
                    long delay = Math.min(30000L, 1000L << (busFailures - 1));
                    if (busReconnect != null) handler.removeCallbacks(busReconnect);
                    busReconnect = () -> { busReconnect = null; connectLiveBus(); };
                    handler.postDelayed(busReconnect, delay);
                    scheduleFeed(0);
                }
            }
        });
        String script = "(function(){var h=function(e){var p=e.ports&&e.ports[0];"
                + "if(!p||e.data!=='bchat-ws')return;window.removeEventListener('message',h);"
                + "if(location.href!==" + JSONObject.quote(BRIDGE) + "){p.postMessage('closed');return;}"
                + "try{if(window.__bchatLiveBus)window.__bchatLiveBus.close();"
                + "var u=new URL('/websocket?version=19.0-2',location.origin);"
                + "u.protocol=location.protocol==='https:'?'wss:':'ws:';"
                + "var s=new WebSocket(u.href);window.__bchatLiveBus=s;"
                + "s.onopen=function(){s.send(JSON.stringify({event_name:'subscribe',data:{channels:[],last:0}}));p.postMessage('open')};"
                + "s.onmessage=function(e){try{var a=JSON.parse(e.data);if(!Array.isArray(a))a=[a];"
                + "for(var i=0;i<a.length;i++){var m=a[i]&&a[i].message;"
                + "if(m&&m.type==='bchat.change'){p.postMessage('wake');break}}}catch(_){}};"
                + "s.onclose=function(){if(window.__bchatLiveBus===s)window.__bchatLiveBus=null;p.postMessage('closed')};"
                + "s.onerror=function(){s.close()};}catch(_){p.postMessage('closed')}};"
                + "window.addEventListener('message',h);})();";
        web.evaluateJavascript(script, ignored -> {
            if (nonce != busNonce || !liveReady(scope) || currentWeb != webEpoch
                    || currentPage != pageEpoch || busPort == null) return;
            web.postWebMessage(new WebMessage("bchat-ws", new WebMessagePort[]{channel[1]}), Uri.parse(ORIGIN));
        });
    }

    private static boolean flag(JSONObject object, String key, boolean expected) {
        return object != null && object.opt(key) instanceof Boolean && object.optBoolean(key) == expected;
    }

    private JSONObject verifiedProfile(JSONObject response, Set<Long> authorizedCompanies) {
        JSONObject profile = response.optJSONObject("profile");
        if (profile == null || profile.toString().getBytes(StandardCharsets.UTF_8).length > MAX_PROFILE_BYTES
                || !(profile.opt("name") instanceof String)) return null;
        JSONArray companies = profile.optJSONArray("companies");
        if (companies == null || companies.length() != authorizedCompanies.size()) return null;
        Set<Long> seen = new HashSet<>();
        List<JSONObject> sortedCompanies = new ArrayList<>();
        try {
            for (int i = 0; i < companies.length(); i++) {
                JSONObject company = companies.getJSONObject(i);
                long id = positiveId(company.get("id"));
                if (!authorizedCompanies.contains(id) || !seen.add(id)
                        || !(company.opt("name") instanceof String)) return null;
                for (String language : new String[]{"name_ar", "name_en"})
                    if (company.has(language) && !(company.opt(language) instanceof String)) return null;
                JSONArray titles = company.getJSONArray("job_titles");
                for (int j = 0; j < titles.length(); j++)
                    if (!(titles.get(j) instanceof String)) return null;
                sortedCompanies.add(company);
            }
            sortedCompanies.sort((first, second) -> Long.compare(
                    first.optLong("id"), second.optLong("id")));
            JSONArray ordered = new JSONArray();
            for (JSONObject company : sortedCompanies) ordered.put(company);
            profile.put("companies", ordered);
        } catch (Exception invalid) { return null; }
        return profile;
    }

    private static final class SessionRedirect extends RuntimeException { }
    private static final class OptionalModuleUnavailable extends RuntimeException { }

    /** Additive v2 contract: old servers omit permissions, not legacy capabilities. */
    private static final class PermissionSet {
        final long revision;
        final boolean chatView, chatSend, media, groupCreate, groupManage;
        final boolean taskView, taskManage, roomAdmin;
        final boolean ordersIncluded, orderView, orderCreate, orderReceive;

        private PermissionSet(long revision, boolean chatView, boolean chatSend, boolean media,
                boolean groupCreate, boolean groupManage, boolean taskView,
                boolean taskManage, boolean roomAdmin, boolean ordersIncluded,
                boolean orderView, boolean orderCreate, boolean orderReceive) {
            this.revision = revision;
            this.chatView = chatView;
            this.chatSend = chatSend && chatView;
            this.media = media && this.chatView;
            this.groupCreate = groupCreate && chatView;
            this.groupManage = groupManage && chatView;
            this.taskView = taskView;
            this.taskManage = taskManage && taskView;
            this.roomAdmin = roomAdmin && chatView;
            this.ordersIncluded = ordersIncluded;
            this.orderView = ordersIncluded && orderView;
            this.orderCreate = this.orderView && orderCreate;
            this.orderReceive = this.orderView && orderReceive;
        }

        static PermissionSet legacy() {
            return new PermissionSet(-1, true, true, true, true, true,
                    true, true, true, false, false, false, false);
        }

        static PermissionSet parse(JSONObject source) throws Exception {
            if (source == null || source.getInt("version") != 1)
                throw new IllegalArgumentException("Unknown permissions contract");
            Object value = source.get("revision");
            if (!(value instanceof Number))
                throw new IllegalArgumentException("Invalid permissions revision");
            long revision = ((Number) value).longValue();
            if (revision < 0 || ((Number) value).doubleValue() != (double) revision)
                throw new IllegalArgumentException("Invalid permissions revision");
            boolean orderView = source.has("order_view");
            boolean orderCreate = source.has("order_create");
            boolean orderReceive = source.has("order_receive");
            if ((orderView || orderCreate || orderReceive)
                    && !(orderView && orderCreate && orderReceive))
                throw new IllegalArgumentException("Incomplete order permissions");
            return new PermissionSet(revision,
                    requiredFlag(source, "chat_view"), requiredFlag(source, "chat_send"),
                    requiredFlag(source, "media"), requiredFlag(source, "group_create"),
                    requiredFlag(source, "group_manage"), requiredFlag(source, "task_view"),
                    requiredFlag(source, "task_manage"), requiredFlag(source, "room_admin"),
                    orderView, orderView && requiredFlag(source, "order_view"),
                    orderView && requiredFlag(source, "order_create"),
                    orderView && requiredFlag(source, "order_receive"));
        }

        private static boolean requiredFlag(JSONObject source, String key) throws Exception {
            Object value = source.get(key);
            if (!(value instanceof Boolean)) throw new IllegalArgumentException("Invalid permission flag");
            return (Boolean) value;
        }

        boolean sameAs(PermissionSet other) {
            return other != null && revision == other.revision
                    && chatView == other.chatView && chatSend == other.chatSend
                    && media == other.media && groupCreate == other.groupCreate
                    && groupManage == other.groupManage && taskView == other.taskView
                    && taskManage == other.taskManage && roomAdmin == other.roomAdmin
                    && ordersIncluded == other.ordersIncluded && orderView == other.orderView
                    && orderCreate == other.orderCreate && orderReceive == other.orderReceive;
        }

        JSONObject toJson() throws Exception {
            JSONObject value = new JSONObject();
            value.put("version", 1).put("revision", revision)
                    .put("chat_view", chatView).put("chat_send", chatSend)
                    .put("media", media).put("group_create", groupCreate)
                    .put("group_manage", groupManage).put("task_view", taskView)
                    .put("task_manage", taskManage).put("room_admin", roomAdmin);
            if (ordersIncluded) value.put("order_view", orderView)
                    .put("order_create", orderCreate).put("order_receive", orderReceive);
            return value;
        }
    }

    private PermissionSet rememberedPermissions(AccountScope scope) {
        if (scope == null) return null;
        String raw = getSharedPreferences(PERMISSION_PREFS, MODE_PRIVATE).getString(scope.key, null);
        if (raw == null) return null;
        try { return PermissionSet.parse(new JSONObject(raw)); }
        catch (Exception invalid) { return null; }
    }

    private PermissionSet permissionContract(JSONObject bootstrap, AccountScope scope) throws Exception {
        JSONObject supplied = bootstrap.optJSONObject("permissions");
        if (supplied != null) return PermissionSet.parse(supplied);
        if (bootstrap.has("permissions")) throw new IllegalArgumentException("Invalid permissions");
        // A downgraded/old server must not silently regrant rights revoked by a newer one.
        PermissionSet saved = rememberedPermissions(scope);
        return saved == null ? PermissionSet.legacy() : saved;
    }

    private boolean chatAllowed() { return permissionSet.chatView; }
    private boolean sendAllowed() { return permissionSet.chatSend; }
    private boolean mediaAllowed() { return permissionSet.media && mediaAvailable; }
    private boolean mediaUploadAllowed() { return sendAllowed() && mediaAllowed(); }

    private void showPermittedRoot() {
        if (shell != null) shell.setVisibility(View.GONE);
        if (chatRoot != null) chatRoot.setVisibility(View.VISIBLE);
        if (loginReleaseFooter != null) loginReleaseFooter.setVisibility(View.GONE);
        if (layout != null) layout.setPadding(0, 0, 0, 0);
    }

    private void cancelRevokedMediaSending(AccountScope scope) {
        ++mediaSessionGeneration;
        closeMediaUpload();
        mediaStageBusy = false;
        mediaConfirmBusy = false;
        mediaConfirmRoom = null;
        if (cameraCaptureFile != null) { cameraCaptureFile.delete(); cameraCaptureFile = null; }
        mediaPickerAccount = null;
        mediaPickerRoom = null;
        stopRecordingBadge();
        clearVoicePreview();
        if (connectedVoiceRecorder != null) {
            connectedVoiceRecorder.cancel(); connectedVoiceRecorder = null;
        }
        if (mediaStore != null) try { mediaStore.purgeAccount(scope); }
        catch (IOException unavailable) {
            // A failed private-file purge must not retain a cold-start offline session.
            preferences().edit().putBoolean(REMEMBER, false).commit();
        }
    }

    private void purgeRevokedMedia(AccountScope scope) {
        cancelRevokedMediaSending(scope);
        closeMediaRead();
        clearPendingPdf();
        clearMediaReadCache();
        mediaThumbnailQueue.clear();
        mediaThumbnailCache.evictAll();
        if (mediaPreviewDialog != null) mediaPreviewDialog.dismiss();
        stopInlineAudio();
    }

    private void applyPermissionSet(AccountScope scope, PermissionSet next) {
        if (permissionAccount != scope || permissionSet.revision != next.revision) {
            orderCapabilityOptions = null;
            orderCapabilityAccount = null;
            orderCapabilityOptionsAt = 0;
            lastOrderCapabilityProbeAt = 0;
        }
        permissionSet = next;
        permissionAccount = scope;
        if (next.ordersIncluded) setOrderRights(scope, next.orderView,
                next.orderCreate, next.orderReceive);
        else if (next.revision >= 0) setOrderRights(scope, false, false, false);
        try {
            if (next.revision >= 0 && !getSharedPreferences(PERMISSION_PREFS, MODE_PRIVATE).edit()
                    .putString(scope.key, next.toJson().toString()).commit())
                throw new IllegalStateException("Cannot save permission snapshot");
        } catch (Exception storage) {
            // Never offer stale offline history when the newer revocation cannot be persisted.
            purgeHistory();
        }
        if (!next.chatView) {
            ++historyWriteGeneration;
            ++historyGlobalGeneration;
            try { synchronized (historyStorageLock) {
                if (historyCache != null) historyCache.purgeAccount(scope);
            } } catch (RuntimeException damaged) { purgeHistory(); }
            rooms.clear();
            selectedRoom = null;
            displayedMessages.clear();
            if (roomItems != null) roomItems.removeAllViews();
            if (messageAdapter != null) messageAdapter.notifyDataSetChanged();
            closeLiveSync();
        }
        if (!next.chatSend || !next.chatView) {
            flushDraftSave();
            try { if (outbox != null) outbox.purgeAccount(scope); }
            catch (RuntimeException damaged) { preferences().edit().putBoolean(REMEMBER, false).commit(); }
            getSharedPreferences(GROUP_CREATE_PREFS, MODE_PRIVATE).edit().remove(scope.key).commit();
            if (messageInput != null) {
                suppressDraftChanges = true;
                messageInput.setText("");
                suppressDraftChanges = false;
            }
        }
        if (!next.media || !next.chatView) purgeRevokedMedia(scope);
        else if (!next.chatSend) cancelRevokedMediaSending(scope);
        if (!next.groupCreate)
            getSharedPreferences(GROUP_CREATE_PREFS, MODE_PRIVATE).edit().remove(scope.key).commit();
        if ((!next.groupManage || !next.chatView) && groupInfoDialog != null)
            groupInfoDialog.dismiss();
        if (!next.taskView) {
            ++taskViewSerial;
            try { synchronized (historyStorageLock) {
                if (taskOfflineCache != null) taskOfflineCache.purgeAccount(scope);
            } } catch (RuntimeException damaged) { purgeHistory(); }
            tasksAvailable = false;
            tasks.clear();
            taskCompanies.clear();
            if (taskItems != null) taskItems.removeAllViews();
        }
        if (!next.taskManage)
            taskCreatePreferences().edit().remove(scope.key).commit();
        if (createGroupButton != null) createGroupButton.setVisibility(
                next.groupCreate ? View.VISIBLE : View.GONE);
        if (selectedRoom != null) {
            if (composerRow != null) composerRow.setVisibility(next.chatSend ? View.VISIBLE : View.GONE);
            if (mediaPickButton != null) mediaPickButton.setVisibility(mediaUploadAllowed()
                    ? View.VISIBLE : View.GONE);
            if (mediaVoiceButton != null) mediaVoiceButton.setVisibility(mediaUploadAllowed()
                    ? View.VISIBLE : View.GONE);
        }
        if (taskNewButton != null) taskNewButton.setVisibility(next.taskManage && tasksAvailable
                && !taskCompanies.isEmpty() ? View.VISIBLE : View.GONE);
        if (visibleSection.equals("chats") && !next.chatView) {
            if (next.taskView) { showPermittedRoot(); switchSection("tasks"); }
            else if (orderCanView) { showPermittedRoot(); switchSection("orders"); }
            else if (chatRoot != null) {
                showShell();
                shellNotice.setText(R.string.chat_v2_denied);
            }
        } else if (visibleSection.equals("tasks") && !next.taskView) {
            if (next.chatView) { showPermittedRoot(); switchSection("chats"); }
            else if (orderCanView) { showPermittedRoot(); switchSection("orders"); }
            else { showShell(); shellNotice.setText(R.string.task_denied); }
        }
        renderBottomTabs();
    }

    /** A v2 bootstrap can revoke companies while this Activity stays open. */
    private void restrictCompanyScope(AccountScope scope, Set<Long> allowed) {
        if (scope != account || allowed.equals(v1Companies)) return;
        if (!v1Companies.containsAll(allowed)) return; // Grants require a fresh v1 identity check.
        ++historyWriteGeneration;
        ++historyGlobalGeneration;
        ++mediaSessionGeneration;
        Set<Long> retainedRooms = new HashSet<>();
        for (Room room : rooms) if (allowed.contains(room.companyId)) retainedRooms.add(room.id);
        if (historyCache != null) try { synchronized (historyStorageLock) {
            for (ConnectedHistoryCache.RoomRecord room : historyCache.rooms(scope)) {
                if (allowed.contains(room.companyId)) retainedRooms.add(room.id);
                else historyCache.purgeRoom(scope, room.id);
            }
        } } catch (RuntimeException damaged) { purgeHistory(); }
        if (taskOfflineCache != null) try { synchronized (historyStorageLock) {
            taskOfflineCache.purgeExceptCompanySet(scope, allowed);
        } } catch (RuntimeException damaged) { purgeHistory(); }
        if (selectedRoom != null && !allowed.contains(selectedRoom.companyId)) showRooms();
        rooms.removeIf(room -> !allowed.contains(room.companyId));
        displayedMessages.removeIf(message -> selectedRoom == null
                || !allowed.contains(selectedRoom.companyId));
        try { if (outbox != null) outbox.purgeExceptRooms(scope, retainedRooms); }
        catch (RuntimeException damaged) { preferences().edit().putBoolean(REMEMBER, false).commit(); }
        try { if (mediaStore != null) mediaStore.purgeCompaniesNotIn(scope, allowed); }
        catch (IOException damaged) {
            try { if (mediaStore != null) mediaStore.purgeAccount(scope); }
            catch (IOException ignored) { preferences().edit().putBoolean(REMEMBER, false).commit(); }
        }
        try {
            String pendingGroup = getSharedPreferences(GROUP_CREATE_PREFS, MODE_PRIVATE)
                    .getString(scope.key, null);
            if (pendingGroup != null && !allowed.contains(
                    positiveId(new JSONObject(pendingGroup).get("company_id"))))
                getSharedPreferences(GROUP_CREATE_PREFS, MODE_PRIVATE).edit()
                        .remove(scope.key).commit();
        } catch (Exception invalid) {
            getSharedPreferences(GROUP_CREATE_PREFS, MODE_PRIVATE).edit().remove(scope.key).commit();
        }
        try {
            String pendingTask = taskCreatePreferences().getString(scope.key, null);
            if (pendingTask != null && !allowed.contains(new PendingTaskCreate(scope, pendingTask).companyId))
                taskCreatePreferences().edit().remove(scope.key).commit();
        } catch (Exception invalid) { taskCreatePreferences().edit().remove(scope.key).commit(); }
        try {
            String pendingOrder = orderCreatePreferences().getString(scope.key, null);
            if (pendingOrder != null && !allowed.contains(new PendingOrder(scope, pendingOrder).companyId))
                orderCreatePreferences().edit().remove(scope.key).commit();
        } catch (Exception invalid) { orderCreatePreferences().edit().remove(scope.key).commit(); }
        try {
            String pendingReceipt = receiptConfirmPreferences().getString(scope.key, null);
            if (pendingReceipt != null && !allowed.contains(new PendingReceipt(scope, pendingReceipt).companyId))
                receiptConfirmPreferences().edit().remove(scope.key).commit();
        } catch (Exception invalid) { receiptConfirmPreferences().edit().remove(scope.key).commit(); }
        SharedPreferences shares = receiptSharePreferences();
        SharedPreferences.Editor sharesEdit = shares.edit();
        for (Map.Entry<String, ?> item : shares.getAll().entrySet())
            if (item.getKey().startsWith(scope.key + ":")
                    && (!(item.getValue() instanceof Number)
                    || !allowed.contains(((Number) item.getValue()).longValue())))
                sharesEdit.remove(item.getKey());
        sharesEdit.commit();
        closeMediaRead();
        clearPendingPdf();
        clearMediaReadCache();
        stopInlineAudio();
        mediaThumbnailQueue.clear();
        mediaThumbnailCache.evictAll();
        if (mediaPreviewDialog != null) mediaPreviewDialog.dismiss();
        v1Companies.clear();
        v1Companies.addAll(allowed);
        JSONObject updatedProfile = null;
        if (profileSnapshot != null) try {
            updatedProfile = new JSONObject(profileSnapshot.toString());
            JSONArray old = updatedProfile.optJSONArray("companies");
            JSONArray kept = new JSONArray();
            if (old != null) for (int i = 0; i < old.length(); i++) {
                JSONObject company = old.optJSONObject(i);
                if (company != null && allowed.contains(company.optLong("id"))) kept.put(company);
            }
            updatedProfile.put("companies", kept);
        } catch (Exception damaged) { updatedProfile = null; }
        profileSnapshot = updatedProfile;
        refreshChatCompanySelector();
        if (orderCompanyId > 0 && !allowed.contains(orderCompanyId)) {
            orderCompanyId = 0;
            orderCompanyPreferences().edit().remove(ORDER_COMPANY_SELECTED).apply();
        }
        ++taskViewSerial;
        tasks.clear();
        taskCompanies.clear();
        taskBeforeId = 0;
        if (taskItems != null) taskItems.removeAllViews();
        if (taskRoomFilter > 0 && !retainedRooms.contains(taskRoomFilter)) taskRoomFilter = 0;
        ++orderViewSerial;
        orderSummaries.clear();
        receiptSummaries.clear();
        orderCompanies.clear();
        orderOptions.clear();
        orderCart.clear();
        if (orderItems != null) orderItems.removeAllViews();
        if (receiptFlowDialog != null) receiptFlowDialog.dismiss();
        if (orderCartDialog != null) orderCartDialog.dismiss();
        if (roomItems != null && "chats".equals(visibleSection) && selectedRoom == null) renderRooms();
        if (chatAllowed()) handler.post(() -> {
            if (verified && account == scope) loadRooms();
        });
        if ("tasks".equals(visibleSection)) handler.post(() -> {
            if (verified && account == scope) discoverTasks();
        });
        if ("orders".equals(visibleSection)) handler.post(() -> {
            if (verified && account == scope) discoverOrders();
        });
    }

    private void revalidateCompanyIdentity(AccountScope scope) {
        if (account != scope || !verified) return;
        // A v2 grant never widens the v1-verified company set. Reuse the Odoo cookie
        // to verify v1 again without a logout or a second password prompt.
        verified = false;
        probing = false;
        csrfToken = null;
        clearChatView();
        showShell();
        shellNotice.setText(R.string.auth_verifying);
        openWeb(BRIDGE);
    }

    private void refreshPermissionSet() {
        if (!verified || offlineHistory || account == null || web == null) return;
        long now = SystemClock.elapsedRealtime();
        if (now - lastPermissionRefreshAt < 10000 && lastPermissionRefreshAt > 0) return;
        if (v2Busy) {
            if (!permissionRefreshScheduled) {
                permissionRefreshScheduled = true;
                handler.postDelayed(() -> {
                    permissionRefreshScheduled = false;
                    refreshPermissionSet();
                }, 500);
            }
            return;
        }
        lastPermissionRefreshAt = now;
        final AccountScope scoped = account;
        fetchV2("GET", V2_BOOTSTRAP, null, (status, result) -> {
            if (scoped != account || !verified) return;
            if (handleV2TransportFailure(status)) return;
            try {
                if (status != 200 || result == null || positiveId(result.get("api_version")) != 2
                        || positiveId(result.get("user_id")) != scoped.userId
                        || !DATABASE.equals(result.getString("database"))) return;
                JSONArray listed = result.getJSONArray("company_ids");
                Set<Long> validCompanies = new HashSet<>();
                for (int i = 0; i < listed.length(); i++)
                    validCompanies.add(positiveId(listed.get(i)));
                if (listed.length() != validCompanies.size()) return;
                if (!validCompanies.equals(v1Companies)) {
                    Set<Long> stillVerified = new HashSet<>(v1Companies);
                    stillVerified.retainAll(validCompanies);
                    boolean newCompanies = !v1Companies.containsAll(validCompanies);
                    restrictCompanyScope(scoped, stillVerified);
                    if (newCompanies) {
                        revalidateCompanyIdentity(scoped);
                        return;
                    }
                }
                PermissionSet next = permissionContract(result, scoped);
                boolean gainedChat = !permissionSet.chatView && next.chatView;
                if (permissionAccount != scoped || !next.sameAs(permissionSet))
                    applyPermissionSet(scoped, next);
                if (gainedChat) loadRooms();
                maybeProbeOrderCapability();
            } catch (Exception invalid) { /* A malformed refresh must not grant rights. */ }
        });
    }

    private void verifyV2() {
        fetchV2("GET", V2_BOOTSTRAP, null, (statusCode, result) -> {
            traceTransport("D08_V2_VERIFY_" + statusCode);
            if (handleV2TransportFailure(statusCode)) return;
            if (statusCode == 403) purgeHistory();
            try {
                if (statusCode != 200 || result == null || positiveId(result.get("api_version")) != 2
                        || !DATABASE.equals(result.getString("database"))
                        || account == null || positiveId(result.get("user_id")) != account.userId)
                    throw new IllegalArgumentException();
                String token = result.getString("csrf_token");
                if (token.trim().isEmpty() || token.length() > 512) throw new IllegalArgumentException();
                JSONArray companies = result.getJSONArray("company_ids");
                if (companies.length() != v1Companies.size()) throw new IllegalArgumentException();
                Set<Long> v2Companies = new HashSet<>();
                for (int i = 0; i < companies.length(); i++) v2Companies.add(positiveId(companies.get(i)));
                if (!v2Companies.equals(v1Companies)) throw new IllegalArgumentException();
                JSONObject caps = result.getJSONObject("capabilities");
                if (!flag(caps, "rooms", true) || !flag(caps, "messages", true)
                        || !flag(caps, "history", true)
                        || !(flag(caps, "attachments", false) || flag(caps, "attachments", true))
                        || !(flag(caps, "delivery_receipts", false) || flag(caps, "delivery_receipts", true))
                        || !(flag(caps, "read_receipts", false) || flag(caps, "read_receipts", true))
                        || !flag(caps, "tasks", false)) throw new IllegalArgumentException();
                Iterator<String> keys = caps.keys();
                while (keys.hasNext()) {
                    String key = keys.next();
                    if (!("rooms".equals(key) || "messages".equals(key) || "history".equals(key)
                            || "attachments".equals(key) || "delivery_receipts".equals(key)
                            || "read_receipts".equals(key)) && !flag(caps, key, false))
                        throw new IllegalArgumentException();
                }
                JSONObject verifiedProfile = verifiedProfile(result, v2Companies);
                boolean canUseMedia = flag(caps, "attachments", true);
                PermissionSet granted = permissionContract(result, account);
                csrfToken = token;
                BChatPushState.verifiedAccount(this, account);
                requestFirebaseToken();
                if (outbox == null) outbox = new BChatV2Outbox(this);
                if (mediaStore == null) mediaStore = new BChatConnectedMediaStore(this);
                clearChatView();
                mediaAvailable = canUseMedia;
                applyPermissionSet(account, granted);
                profileSnapshot = verifiedProfile;
                selectedChatCompanyId = v2Companies.contains(result.optLong("current_company_id"))
                        ? result.optLong("current_company_id") : 0;
                refreshChatCompanySelector();
                long rememberedOrderCompany = savedOrderCompany(account);
                orderCompanyId = rememberedOrderCompany > 0
                        ? rememberedOrderCompany : selectedChatCompanyId;
                receiptsAvailable = flag(caps, "delivery_receipts", true)
                        && flag(caps, "read_receipts", true);
                shellNotice.setText(R.string.chat_v2_loading);
                if (chatAllowed()) loadRooms();
                else {
                    shell.setVisibility(View.GONE);
                    chatRoot.setVisibility(View.VISIBLE);
                    if (loginReleaseFooter != null) loginReleaseFooter.setVisibility(View.GONE);
                    layout.setPadding(0, 0, 0, 0);
                    if (permissionSet.taskView) switchSection("tasks");
                    else {
                        showShell();
                        shellNotice.setText(R.string.chat_v2_denied);
                    }
                    maybeProbeOrderCapability();
                    // Task-only users do not load rooms. Queue registration after their first
                    // UI read; its busy check defers safely if that read is still in progress.
                    handler.post(this::maybeRegisterPush);
                }
                // A task-only account may never load rooms. Refreshing here
                // plus the post-load calls keeps the header independent from
                // the active tab and retries once the v2 channel is free.
                handler.post(this::refreshAttentionBadge);
            } catch (Exception invalid) {
                // v1's disabled shell is the safe fallback. Never expose demo data.
                BChatPushState.clearAccount(this);
                csrfToken = null;
                releaseWeb();
                showShell();
            }
        });
    }

    /** The optional SDK class is absent from local builds without Firebase files. */
    private void requestFirebaseToken() {
        if (!BuildConfig.BCHAT_PUSH_ENABLED) return;
        try {
            Class.forName("com.baseer.freshchat.BChatFirebaseTokenSource")
                    .getMethod("refresh", Context.class).invoke(null, this);
        } catch (ReflectiveOperationException | LinkageError ignored) {
            // Missing or broken optional Firebase setup never affects BChat login.
        }
    }

    /** Stores a fixed QA-only registration stage; it never records request or account data. */
    private void tracePushRegistration(String stage) {
        if (BuildConfig.BCHAT_PUSH_REGISTRATION_DIAGNOSTICS) pushRegistrationDiagnostic = stage;
    }

    /** Optional push registration uses only the authenticated same-origin API. */
    private void maybeRegisterPush() {
        if (!BuildConfig.BCHAT_PUSH_ENABLED) { tracePushRegistration("P01_PUSH_DISABLED"); return; }
        if (closed || !verified || account == null || csrfToken == null || web == null) {
            tracePushRegistration("P02_NOT_READY");
            return;
        }
        if (pushRegistrationBusy) { tracePushRegistration("P03_IN_FLIGHT"); return; }
        if (!BChatPushState.needsRegistration(this, account)) {
            tracePushRegistration("P04_NOT_NEEDED");
            return;
        }
        if (v2Busy || webV2GetFallbackBusy) {
            tracePushRegistration("P05_WAITING_FOR_READ");
            schedulePushRegistration();
            return;
        }
        final AccountScope scopedAccount = account;
        final String token = BChatPushState.pendingToken(this);
        final String installation = BChatPushState.installationId(this);
        if (token == null || installation == null) {
            tracePushRegistration("P06_LOCAL_IDENTITY_MISSING");
            return;
        }
        final JSONObject payload = new JSONObject();
        try {
            payload.put("api_version", 2);
            payload.put("installation_id", installation);
            payload.put("fcm_token", token);
        } catch (Exception invalid) { tracePushRegistration("P07_PAYLOAD_REJECTED"); return; }
        pushRegistrationBusy = true;
        tracePushRegistration("P08_DISPATCHED");
        if (!registerPushDirectlyInWebView(payload.toString(), (statusCode, response) -> {
            pushRegistrationBusy = false;
            tracePushRegistration("P09_HTTP_" + statusCode);
            if (closed || account == null || !account.key.equals(scopedAccount.key)
                    || !installation.equals(BChatPushState.installationId(this))) return;
            try {
                if (statusCode != 200) { tracePushRegistration("P10_HTTP_" + statusCode); return; }
                if (response == null) { tracePushRegistration("P11_RESPONSE_EMPTY"); return; }
                if (positiveId(response.get("api_version")) != 2) {
                    tracePushRegistration("P12_API_VERSION");
                    return;
                }
                if (!installation.equals(response.getString("installation_id"))) {
                    tracePushRegistration("P13_INSTALLATION_MISMATCH");
                    return;
                }
                if (!(response.opt("push_enabled") instanceof Boolean)) {
                    tracePushRegistration("P14_PUSH_FLAG_INVALID");
                    return;
                }
                if (BChatPushState.registered(this, scopedAccount, token, installation,
                        response.getString("account_key"))) tracePushRegistration("P15_LINKED");
                else tracePushRegistration("P16_LOCAL_SAVE_REJECTED");
            } catch (Exception invalid) {
                // Missing optional module or untrusted response never enables push.
                tracePushRegistration("P17_RESPONSE_MALFORMED");
            }
        })) {
            pushRegistrationBusy = false;
            tracePushRegistration("P18_DIRECT_PATH_UNAVAILABLE");
            if (!closed) schedulePushRegistration();
        }
    }

    private void schedulePushRegistration() {
        if (pushRegistrationScheduled) return;
        pushRegistrationScheduled = true;
        handler.postDelayed(() -> {
            pushRegistrationScheduled = false;
            maybeRegisterPush();
        }, 1500);
    }

    private static final class PushTarget {
        final long eventId;
        final String kind, accountKey, scope;
        PushTarget(long eventId, String kind, String accountKey, String scope) {
            this.eventId = eventId;
            this.kind = kind;
            this.accountKey = accountKey;
            this.scope = scope;
        }
    }

    /** Notification extras are only a hint and are never trusted as a destination. */
    private void capturePushTarget(Intent intent) {
        if (!BuildConfig.BCHAT_PUSH_ENABLED || intent == null
                || !Intent.ACTION_VIEW.equals(intent.getAction())) return;
        try {
            String key = intent.getStringExtra(BChatPushState.EXTRA_ACCOUNT_KEY);
            String kind = intent.getStringExtra(BChatPushState.EXTRA_KIND);
            String event = intent.getStringExtra(BChatPushState.EXTRA_EVENT_ID);
            String scope = BChatPushState.scopeForKey(this, key);
            if (scope == null || !("chat".equals(kind) || "task".equals(kind)
                    || "order".equals(kind)) || event == null
                    || !event.matches("[1-9][0-9]{0,9}")) return;
            long id = Long.parseLong(event);
            if (id > 2147483647L || !Uri.parse("bchat://notification/" + key + "/"
                    + kind + "/" + event).equals(intent.getData())) return;
            pendingPush = new PushTarget(id, kind, key, scope);
            pushNavigationRetries = 0;
            intent.removeExtra(BChatPushState.EXTRA_ACCOUNT_KEY);
            intent.removeExtra(BChatPushState.EXTRA_KIND);
            intent.removeExtra(BChatPushState.EXTRA_EVENT_ID);
        } catch (RuntimeException invalid) {
            // A malformed or stale external intent never navigates anywhere.
        }
    }

    private void finishPushNavigation() {
        pushNavigationBusy = false;
        if (pendingPush != null) processPendingPush();
    }

    private void pushUnavailable() {
        if (closed || !verified || account == null) return;
        android.widget.Toast.makeText(this, R.string.bchat_push_unavailable,
                android.widget.Toast.LENGTH_SHORT).show();
    }

    private void showSensitiveDetail(AlertDialog dialog, AccountScope scopedAccount) {
        if (dialog == null || scopedAccount == null || account != scopedAccount
                || !verified || closed || isFinishing() || isDestroyed()) return;
        if (sensitiveDetailDialog != null) sensitiveDetailDialog.dismiss();
        sensitiveDetailDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (sensitiveDetailDialog == dialog) sensitiveDetailDialog = null;
        });
        dialog.show();
        Ui.decorateDialog(dialog);
    }

    private void processPendingPush() {
        if (pendingPush == null || pushNavigationBusy || closed || !verified || account == null
                || csrfToken == null || chatRoot == null || chatRoot.getVisibility() != View.VISIBLE) return;
        if (!account.key.equals(pendingPush.scope)) { pendingPush = null; return; }
        if (v2Busy) {
            if (!pushNavigationScheduled && pushNavigationRetries++ < 30) {
                pushNavigationScheduled = true;
                handler.postDelayed(() -> {
                    pushNavigationScheduled = false;
                    processPendingPush();
                }, 500);
            } else if (pushNavigationRetries >= 30) pendingPush = null;
            return;
        }
        final PushTarget target = pendingPush;
        pendingPush = null;
        pushNavigationBusy = true;
        final AccountScope scopedAccount = account;
        fetchV2("GET", V2_PUSH_EVENTS + target.eventId, null, (status, body) -> {
            if (scopedAccount != account || !verified || closed) { finishPushNavigation(); return; }
            if (handleV2TransportFailure(status)) { finishPushNavigation(); return; }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                JSONObject notification = body.getJSONObject("notification");
                if (positiveId(notification.get("id")) != target.eventId
                        || !target.kind.equals(notification.getString("kind")))
                    throw new IllegalArgumentException();
                JSONObject reference = notification.getJSONObject("source_ref");
                String destination = reference.getString("destination");
                if ("room_message".equals(destination)
                        && ("chat".equals(target.kind) || "order".equals(target.kind))) {
                    openPushRoomMessage(scopedAccount, positiveId(reference.get("room_id")),
                            positiveId(reference.get("message_id")));
                } else if ("task".equals(destination) && "task".equals(target.kind)) {
                    pendingNotificationTaskId = positiveId(reference.get("task_id"));
                    openTasks(0); // The task detail endpoint rechecks current access.
                    finishPushNavigation();
                } else if ("representative_order".equals(destination)
                        && "order".equals(target.kind)) {
                    openPushRepresentativeOrder(scopedAccount, positiveId(reference.get("order_id")));
                } else throw new IllegalArgumentException();
            } catch (Exception invalid) {
                pushUnavailable();
                finishPushNavigation();
            }
        });
    }

    private void openPushRoomMessage(AccountScope scopedAccount, long roomId, long messageId) {
        fetchV2("GET", V2_ROOMS + "/" + roomId + "/messages/" + messageId,
                null, (status, body) -> {
            if (scopedAccount != account || !verified || closed) { finishPushNavigation(); return; }
            if (handleV2TransportFailure(status)) { finishPushNavigation(); return; }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2
                        || positiveId(body.getJSONObject("message").get("id")) != messageId)
                    throw new IllegalArgumentException();
                Room targetRoom = null;
                for (Room room : rooms) if (room.id == roomId) { targetRoom = room; break; }
                if (targetRoom == null) {
                    // The detail route has already rechecked membership. Refresh the bounded
                    // room index once instead of incorrectly claiming that the push vanished.
                    pendingPushRoomId = roomId;
                    pendingPushRoomMessageId = messageId;
                    loadRooms();
                    finishPushNavigation();
                    return;
                }
                selectRoom(targetRoom, messageId);
            } catch (Exception invalid) { pushUnavailable(); }
            finishPushNavigation();
        });
    }

    private void openPushRepresentativeOrder(AccountScope scopedAccount, long orderId) {
        fetchV2("GET", V2_ORDERS + "/" + orderId + "/representative", null,
                (status, body) -> {
            if (scopedAccount != account || !verified || closed) { finishPushNavigation(); return; }
            if (handleV2TransportFailure(status)) { finishPushNavigation(); return; }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                JSONObject order = body.getJSONObject("order");
                if (positiveId(order.get("id")) != orderId
                        || !v1Companies.contains(positiveId(order.get("company_id"))))
                    throw new IllegalArgumentException();
                String requester = boundedTaskText(order.getString("requester_name"), 256, true);
                String total = boundedTaskText(order.getString("requested_total"), 32, true);
                String currency = boundedTaskText(order.getString("currency"), 16, true);
                JSONArray lines = order.getJSONArray("lines");
                if (lines.length() > 100) throw new IllegalArgumentException();
                StringBuilder detail = new StringBuilder(getString(R.string.bchat_push_order_requester,
                        requester, total, currency));
                for (int i = 0; i < lines.length(); i++) {
                    JSONObject line = lines.getJSONObject(i);
                    String product = boundedTaskText(line.getString("product_name"), 256, true);
                    String option = boundedTaskText(line.getString("option_name"), 256, false);
                    String quantity = boundedTaskText(line.getString("quantity"), 32, true);
                    detail.append('\n').append(quantity).append(" × ").append(product);
                    if (!option.isEmpty()) detail.append(" · ").append(option);
                    if (detail.length() > 10000) throw new IllegalArgumentException();
                }
                if (scopedAccount != account || !verified) throw new IllegalArgumentException();
                switchSection("orders");
                showSensitiveDetail(new AlertDialog.Builder(this)
                        .setTitle(R.string.bchat_push_order_detail)
                        .setMessage(detail.toString())
                        .setPositiveButton(R.string.task_close, null).create(), scopedAccount);
            } catch (Exception invalid) { pushUnavailable(); }
            finishPushNavigation();
        });
    }

    /** Logout never waits for the network; the local push identity is removed first. */
    private void unregisterPushBestEffort(String installation, String token, Runnable navigate) {
        if (!BuildConfig.BCHAT_PUSH_ENABLED || installation == null || token == null
                || web == null || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl()))) {
            navigate.run();
            return;
        }
        try {
            JSONObject payload = new JSONObject();
            payload.put("api_version", 2);
            payload.put("installation_id", installation);
            String script = "(function(){if(location.href!==" + JSONObject.quote(BRIDGE) + ")return;"
                    + "fetch(" + JSONObject.quote(V2_PUSH_UNREGISTER)
                    + ",{method:'POST',credentials:'same-origin',redirect:'manual',keepalive:true,"
                    + "cache:'no-store',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'},"
                    + "body:new URLSearchParams({csrf_token:" + JSONObject.quote(token)
                    + ",payload:" + JSONObject.quote(payload.toString())
                    + "}).toString()}).catch(function(){});})();";
            web.evaluateJavascript(script, ignored -> navigate.run());
            handler.postDelayed(navigate, 500);
        } catch (Exception ignored) { navigate.run(); }
    }

    private boolean handleV2TransportFailure(int statusCode) {
        return handleV2TransportFailure(statusCode, false);
    }

    /** A missing optional group route can redirect to login while the session is still valid. */
    private boolean handleGroupRouteFailure(int statusCode, boolean writeRequest) {
        if (statusCode != 401) return handleV2TransportFailure(statusCode, writeRequest);
        AccountScope scoped = account;
        if (scoped == null) return true;
        fetchV2("GET", V2_ROOMS, null, (probeStatus, probe) -> {
            if (account != scoped || !verified) return;
            if (probeStatus == 200 && probe != null && probe.optInt("api_version") == 2) {
                chatNotice.setText(R.string.bchat_group_server_outdated);
                if (groupCreateDialog != null) groupCreateDialog.dismiss();
                Ui.decorateDialog(new AlertDialog.Builder(this)
                        .setMessage(R.string.bchat_group_server_outdated)
                        .setPositiveButton(R.string.bchat_group_ok, null).show());
                return;
            }
            if (!handleV2TransportFailure(probeStatus, writeRequest))
                chatNotice.setText(R.string.bchat_group_failed);
        });
        return true;
    }

    private boolean handleV2TransportFailure(int statusCode, boolean writeRequest) {
        if (statusCode == 401) { logout(); return true; }
        if (statusCode == 0) { probeV1AfterTransportFailure(writeRequest); return true; }
        return false;
    }

    private void probeV1AfterTransportFailure(boolean uncertainWrite) {
        if (closed || !verified || account == null) return;
        clearChatView();
        csrfToken = null;
        showShell();
        shellNotice.setText(R.string.auth_verifying);
        traceTransport("D09_V1_PROBE_START");
        fetchV2("GET", V1_BOOTSTRAP, null, (statusCode, result) -> {
            traceTransport("D10_V1_PROBE_" + statusCode);
            if (statusCode == 401) { logout(); return; }
            boolean sameUser = false;
            try {
                if (statusCode == 200 && result != null && positiveId(result.get("api_version")) == 1
                        && DATABASE.equals(result.getString("database"))
                        && positiveId(result.get("user_id")) == account.userId
                        && result.opt("integration_enabled") == Boolean.FALSE) {
                    JSONArray companies = result.getJSONArray("company_ids");
                    Set<Long> ids = new HashSet<>();
                    for (int i = 0; i < companies.length(); i++) ids.add(positiveId(companies.get(i)));
                    sameUser = ids.equals(v1Companies);
                }
            } catch (Exception invalid) { sameUser = false; }
            if (statusCode == 200 && !sameUser) { logout(); return; }
            if (statusCode == 0 && offerOfflineHistory()) {
                if (uncertainWrite) {
                    if (offlineHistory) {
                        offlineUncertainWrite = true;
                        chatNotice.setText(offlineNotice());
                    } else {
                        shellNotice.setText(getString(R.string.chat_v2_uncertain_network)
                                + "\n" + getString(R.string.chat_v2_load_failed));
                    }
                }
                return;
            }
            releaseWeb();
            showShell();
            if (uncertainWrite) shellNotice.setText(R.string.chat_v2_uncertain_network);
            else shellNotice.setText(getString(R.string.auth_network_error) + transportDiagnosticNotice());
            shellRetry.setVisibility(View.VISIBLE);
        });
    }

    private static final class Room {
        final long id, companyId, membershipId;
        String name, invoicePolicy;
        int invoicePolicyVersion;
        String lastMessagePreview = "", lastMessageAt = "", lastMessageKind = "";
        long lastMessageId;
        int unreadCount, avatarVersion, memberCount;
        boolean groupAdmin, isGroup, hasActiveTask;
        Room(long id, long companyId, long membershipId, String name,
             String invoicePolicy, int invoicePolicyVersion) {
            this.id = id; this.companyId = companyId; this.membershipId = membershipId;
            this.name = name; this.invoicePolicy = invoicePolicy;
            this.invoicePolicyVersion = invoicePolicyVersion;
        }
        Room(long id, long companyId, long membershipId, String name) {
            this(id, companyId, membershipId, name, "off", 1);
        }
        boolean sameMembership(Room other) {
            return other != null && id == other.id && companyId == other.companyId
                    && membershipId == other.membershipId;
        }
        void updateMetadata(Room other) {
            name = other.name;
            invoicePolicy = other.invoicePolicy;
            invoicePolicyVersion = other.invoicePolicyVersion;
            lastMessagePreview = other.lastMessagePreview;
            lastMessageAt = other.lastMessageAt;
            lastMessageKind = other.lastMessageKind;
            lastMessageId = other.lastMessageId;
            unreadCount = other.unreadCount;
            avatarVersion = other.avatarVersion;
            memberCount = other.memberCount;
            groupAdmin = other.groupAdmin;
            isGroup = other.isGroup;
            hasActiveTask = other.hasActiveTask;
        }
    }

    private void purgeHistory() {
        ++historyWriteGeneration;
        ++historyGlobalGeneration;
        // If disk deletion fails, a restarted app must still refuse stale offline access.
        preferences().edit().putBoolean(REMEMBER, false).commit();
        if (historyCache == null && taskOfflineCache == null) return;
        try { synchronized (historyStorageLock) {
            if (historyCache != null) historyCache.purgeAll();
            if (taskOfflineCache != null) taskOfflineCache.purgeAll();
        } }
        catch (RuntimeException damaged) {
            // A damaged local cache must not authorize cold-start browsing later.
            preferences().edit().putBoolean(REMEMBER, false).commit();
        }
    }

    private void purgeCachedRoom(AccountScope scopedAccount, long roomId) {
        ++historyWriteGeneration;
        ++historyGlobalGeneration;
        synchronized (historyStorageLock) {
            if (historyCache != null) historyCache.purgeRoom(scopedAccount, roomId);
        }
    }

    /** An offline snapshot is a read-only fallback after transport failure, never a session. */
    private boolean offerOfflineHistory() {
        if (closed || loggingOut || !preferences().getBoolean(REMEMBER, false)
                || (historyCache == null && taskOfflineCache == null)) return false;
        ConnectedHistoryCache.Snapshot history = null;
        TaskOfflineCache.Snapshot taskSnapshot = null;
        PermissionSet saved;
        try {
            long now = System.currentTimeMillis();
            if (historyCache != null)
                history = historyCache.remembered(ORIGIN, DATABASE, now, MAX_OFFLINE_AGE_MILLIS);
            if (taskOfflineCache != null)
                taskSnapshot = taskOfflineCache.remembered(ORIGIN, DATABASE, now, MAX_OFFLINE_AGE_MILLIS);
            if (history == null && taskSnapshot == null) return false;
            AccountScope candidate = history != null ? history.account : taskSnapshot.account;
            if (history != null && taskSnapshot != null
                    && !history.account.key.equals(taskSnapshot.account.key)) return false;
            saved = rememberedPermissions(candidate);
            if (saved == null || (history == null || !saved.chatView)
                    && (taskSnapshot == null || !saved.taskView)) return false;
        } catch (Exception unavailable) { return false; }
        ++epoch;
        probing = false;
        submitting = false;
        verified = false;
        csrfToken = null;
        releaseWeb();
        return browseRememberedHistory(history, taskSnapshot, saved);
    }

    private void retryOnlineSession() {
        if (closed) return;
        offlineHistory = false;
        account = null;
        clearChatView();
        bridgeRecoveryUsed = false;
        showShell();
        shellNotice.setText(R.string.auth_verifying);
        openWeb(BRIDGE);
    }

    private void leaveOfflineHistory() {
        purgeHistory();
        preferences().edit().putBoolean(REMEMBER, false).apply();
        BChatPushState.clearAccount(this);
        verified = false;
        account = null;
        clearChatView();
        clearCookies(() -> {
            if (closed) return;
            showLoginForm();
            openWeb(LOGIN);
        });
    }

    private boolean browseRememberedHistory(ConnectedHistoryCache.Snapshot snapshot,
                                            TaskOfflineCache.Snapshot taskSnapshot,
                                            PermissionSet saved) {
        if (closed || saved == null || (snapshot == null && taskSnapshot == null)
                || !preferences().getBoolean(REMEMBER, false)) return false;
        try {
            releaseWeb();
            clearChatView();
            account = snapshot != null ? snapshot.account : taskSnapshot.account;
            csrfToken = null;
            verified = false;
            offlineHistory = true;
            offlineChatCacheAvailable = snapshot != null;
            offlineTaskCacheAvailable = taskSnapshot != null;
            offlineChatVerifiedAt = snapshot == null ? 0 : snapshot.verifiedAt;
            offlineTaskVerifiedAt = taskSnapshot == null ? 0 : taskSnapshot.verifiedAt;
            permissionSet = saved;
            permissionAccount = account;
            v1Companies.clear();
            if (taskSnapshot != null) v1Companies.addAll(taskSnapshot.companyIds);
            if (snapshot != null) for (ConnectedHistoryCache.RoomRecord record : snapshot.rooms) {
                rooms.add(new Room(record.id, record.companyId, record.membershipId,
                        record.name, record.policy, record.policyVersion));
                v1Companies.add(record.companyId);
            }
            shell.setVisibility(View.GONE);
            nativeForm.setVisibility(View.GONE);
            if (loginReleaseFooter != null) loginReleaseFooter.setVisibility(View.GONE);
            status.setVisibility(View.GONE);
            chatRoot.setVisibility(View.VISIBLE);
            layout.setPadding(0, 0, 0, 0);
            if (saved.chatView && snapshot != null) showRooms();
            else if (saved.taskView && taskSnapshot != null) switchSection("tasks");
            else return false;
            return true;
        } catch (Exception unavailable) {
            clearChatView();
            account = null;
            return false;
        }
    }

    private String offlineNotice() { return offlineNotice(false); }

    /** Offline pages are always dated so users do not mistake a cache for current server state. */
    private String offlineNotice(boolean tasks) {
        String readOnly = getString(tasks ? R.string.chat_v2_offline_tasks_read_only
                : R.string.chat_v2_offline_read_only);
        long verifiedAt = tasks ? offlineTaskVerifiedAt : offlineChatVerifiedAt;
        if (verifiedAt > 0) {
            Date date = new Date(verifiedAt);
            readOnly += "\n" + getString(R.string.chat_v2_offline_saved_at,
                    asciiDigits(android.text.format.DateFormat.getDateFormat(this).format(date)
                            + " " + android.text.format.DateFormat.getTimeFormat(this).format(date)));
        }
        return offlineUncertainWrite
                ? getString(R.string.chat_v2_uncertain_network) + "\n" + readOnly : readOnly;
    }

    private void scheduleDraftSave(AccountScope scopedAccount, Room scopedRoom, String body) {
        if (draftSaveTask != null) handler.removeCallbacks(draftSaveTask);
        final Runnable[] task = new Runnable[1];
        task[0] = () -> {
            if (draftSaveTask != task[0]) return;
            draftSaveTask = null;
            if (closed || account != scopedAccount || selectedRoom != scopedRoom || !draftActive
                    || outbox == null) return;
            try { outbox.saveDraft(scopedAccount, scopedRoom.id, scopedRoom.membershipId, body); }
            catch (Exception invalid) { chatNotice.setText(R.string.chat_v2_save_failed); }
        };
        draftSaveTask = task[0];
        handler.postDelayed(task[0], 300);
    }

    private void flushDraftSave() {
        Runnable pending = draftSaveTask;
        if (pending != null) {
            handler.removeCallbacks(pending);
            pending.run();
        }
    }

    private void clearChatView() {
        ++mediaSessionGeneration;
        ++historyWriteGeneration;
        closeLiveSync();
        acknowledgedMessages.clear();
        pendingAcknowledgements.clear();
        displayedMessages.clear();
        olderPageLoading = false;
        olderPageFailed = false;
        ++messageRenderSerial;
        historicalWindow = false;
        offlineHistory = false;
        offlineChatCacheAvailable = offlineTaskCacheAvailable = false;
        offlineChatVerifiedAt = offlineTaskVerifiedAt = 0;
        offlineUncertainWrite = false;
        receiptsAvailable = false;
        liveRoomsDirty = liveMessagesDirty = liveTasksDirty = liveOrdersDirty = false;
        stopInlineAudio();
        stopRecordingBadge();
        if (connectedVoiceRecorder != null) {
            connectedVoiceRecorder.cancel(); connectedVoiceRecorder = null;
        }
        clearVoicePreview();
        if (cameraCaptureFile != null) { cameraCaptureFile.delete(); cameraCaptureFile = null; }
        mediaPickerAccount = null;
        mediaPickerRoom = null;
        groupPhotoAccount = null;
        groupPhotoRoom = null;
        groupAvatarWaiting.clear();
        groupAvatarQueue.clear();
        groupAvatarBusy = false;
        ++groupAvatarNonce;
        if (groupAvatarPort != null) { groupAvatarPort.close(); groupAvatarPort = null; }
        groupAvatarCache.evictAll();
        privateAvatarWaiting.clear();
        privateAvatarQueue.clear();
        privateAvatarBusy = false;
        ++privateAvatarNonce;
        if (privateAvatarPort != null) { privateAvatarPort.close(); privateAvatarPort = null; }
        privateAvatarCache.evictAll();
        pushRegistrationBusy = false;
        pushRegistrationScheduled = false;
        pushNavigationBusy = false;
        pendingNotificationTaskId = 0;
        pendingPushRoomId = 0;
        pendingPushRoomMessageId = 0;
        closeMediaUpload();
        closeMediaRead();
        if (sensitiveDetailDialog != null) { sensitiveDetailDialog.dismiss(); sensitiveDetailDialog = null; }
        if (mediaPreviewDialog != null) { mediaPreviewDialog.dismiss(); mediaPreviewDialog = null; }
        mediaThumbnailQueue.clear();
        mediaThumbnailCache.evictAll();
        clearPendingPdf();
        clearMediaReadCache();
        mediaAvailable = false;
        mediaStageBusy = false;
        mediaCancelBusy = false;
        mediaConfirmBusy = false;
        mediaConfirmRoom = null;
        mediaPickerAccount = null;
        mediaPickerRoom = null;
        if (accountMenu != null) accountMenu.dismiss();
        if (orderCompanyMenu != null) orderCompanyMenu.dismiss();
        if (chatCompanyMenu != null) chatCompanyMenu.dismiss();
        if (profileDialog != null) { profileDialog.dismiss(); profileDialog = null; }
        if (groupCreateDialog != null) { groupCreateDialog.dismiss(); groupCreateDialog = null; }
        if (groupInfoDialog != null) { groupInfoDialog.dismiss(); groupInfoDialog = null; }
        if (receiptFlowDialog != null) { receiptFlowDialog.dismiss(); receiptFlowDialog = null; }
        profileSnapshot = null;
        selectedChatCompanyId = 0;
        if (chatHeaderCompanyButton != null) chatHeaderCompanyButton.setVisibility(View.GONE);
        flushDraftSave();
        if (pendingDialog != null) { pendingDialog.dismiss(); pendingDialog = null; }
        rooms.clear();
        ++roomMetadataGeneration;
        ++unreadMetadataGeneration;
        selectedRoom = null;
        if (chatCompanyMenu != null) chatCompanyMenu.dismiss();
        pendingNotificationMessageId = 0;
        clearSelectedReply();
        nextBeforeId = 0;
        historicalWindow = false;
        draftActive = false;
        unresolvedSendNotice = false;
        if (roomItems != null) roomItems.removeAllViews();
        if (messageAdapter != null) messageAdapter.notifyDataSetChanged();
        if (chatTitle != null) chatTitle.setText(R.string.chat_v2_rooms);
        if (refreshHint != null) refreshHint.setVisibility(View.GONE);
        if (messageInput != null) {
            suppressDraftChanges = true;
            messageInput.setText("");
            suppressDraftChanges = false;
        }
        if (chatNotice != null) {
            chatNotice.setText("");
            chatNotice.setOnClickListener(null);
        }
        visibleSection = "chats";
        if (chatPane != null) chatPane.setVisibility(View.VISIBLE);
        if (modulePane != null) modulePane.setVisibility(View.GONE);
        resetOrderImages(true);
        if (orderSearchTask != null) { handler.removeCallbacks(orderSearchTask); orderSearchTask = null; }
        orderCompanyId = orderWarehouseId = orderRepresentativeId = orderCategoryId = 0;
        orderCatalogAfterId = orderListBeforeId = 0;
        orderCurrentPageStartId = 0;
        orderPageHistory.clear();
        orderCompanies.clear();
        queuedOrderLoad = null;
        orderCapabilityOptions = null;
        orderCapabilityAccount = null;
        orderCapabilityOptionsAt = 0;
        orderCapabilityProbeFailures = 0;
        deniedOrderCompanyIds.clear();
        allOrdersRecoveryAttempted = false;
        orderCompanyOptionsLoaded = false;
        orderWarehouses.clear();
        orderRepresentatives.clear();
        orderPurchaseRoutes.clear();
        orderPurchaseRoute = "representative";
        orderCategories.clear();
        orderOptions.clear();
        orderSummaries.clear();
        receiptSummaries.clear();
        orderCart.clear();
        orderRenderedKey = null;
        finishOrderLoading();
        lastRemovedOrderLine = null;
        invalidateOrderQuote();
        ordersAvailable = false;
        ordersDenied = false;
        orderAccess = "";
        orderCanView = orderCanCreate = orderCanReceive = false;
        lastOrderCapabilityProbeAt = 0;
        orderMine = false;
        orderReceiving = false;
        receiptBeforeId = 0;
        ++orderViewSerial;
        if (orderItems != null) orderItems.removeAllViews();
        if (orderNotice != null) orderNotice.setText("");
        if (orderSearch != null) orderSearch.setText("");
        if (orderPendingButton != null) orderPendingButton.setVisibility(View.GONE);
        if (receiptPendingButton != null) receiptPendingButton.setVisibility(View.GONE);
        if (receiptSharePendingButton != null) receiptSharePendingButton.setVisibility(View.GONE);
        if (taskPane != null) {
            taskPane.setVisibility(View.GONE);
            taskItems.removeAllViews();
            taskNotice.setText("");
            taskOlderButton.setVisibility(View.GONE);
        }
        taskRoomFilter = 0;
        renderedTaskRoomFilter = Long.MIN_VALUE;
        taskBeforeId = 0;
        taskStateFilter = "open";
        tasksAvailable = false;
        tasks.clear();
        ++taskViewSerial;
        taskCompanies.clear();
        if (taskPendingButton != null) taskPendingButton.setVisibility(View.GONE);
        renderBottomTabs();
        if (chatRoot != null) chatRoot.setVisibility(View.GONE);
    }

    /** Disk writes are serialized off the UI thread and invalidated on account/session change. */
    private void queueHistoryWrite(AccountScope scope, ConnectedHistoryCache cache, Runnable write) {
        if (scope == null || cache == null || closed) return;
        final int generation = historyWriteGeneration;
        final int globalGeneration = historyGlobalGeneration;
        historyWrites.execute(() -> {
            synchronized (historyStorageLock) {
                if (generation != historyWriteGeneration
                        || globalGeneration != historyGlobalGeneration || account != scope
                        || historyCache != cache) return;
                try { write.run(); }
                catch (RuntimeException storage) {
                    handler.post(() -> {
                        if (closed || generation != historyWriteGeneration
                                || globalGeneration != historyGlobalGeneration || account != scope
                                || historyCache != cache) return;
                        ++historyWriteGeneration;
                        preferences().edit().putBoolean(REMEMBER, false).commit();
                        synchronized (historyStorageLock) {
                            historyCache.close();
                            historyCache = null;
                        }
                    });
                }
            }
        });
    }

    private void toggleRoomSearch() {
        if (roomSearchSurface == null || roomSearchInput == null) return;
        boolean opening = roomSearchSurface.getVisibility() != View.VISIBLE;
        roomSearchSurface.setVisibility(opening ? View.VISIBLE : View.GONE);
        android.view.inputmethod.InputMethodManager keyboard =
                (android.view.inputmethod.InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (opening) {
            roomSearchInput.requestFocus();
            if (keyboard != null) roomSearchInput.post(() -> {
                if (roomSearchSurface.getVisibility() == View.VISIBLE
                        && roomListHeader.getVisibility() == View.VISIBLE)
                    keyboard.showSoftInput(roomSearchInput,
                            android.view.inputmethod.InputMethodManager.SHOW_IMPLICIT);
            });
        } else {
            roomSearchInput.setText("");
            roomSearchInput.clearFocus();
            if (keyboard != null)
                keyboard.hideSoftInputFromWindow(roomSearchInput.getWindowToken(), 0);
        }
    }

    private void showRooms() {
        if (!chatAllowed() && !offlineHistory) return;
        if (roomActionMenu != null) roomActionMenu.dismiss();
        if (mediaPreviewDialog != null) mediaPreviewDialog.dismiss();
        ++mediaSessionGeneration;
        pendingOrderShareRoom = null;
        stopInlineAudio();
        closeMediaUpload();
        closeMediaRead();
        if (connectedVoiceRecorder != null) {
            connectedVoiceRecorder.cancel(); connectedVoiceRecorder = null;
        }
        stopRecordingBadge();
        clearVoicePreview();
        mediaStageBusy = false;
        mediaPickerAccount = null;
        mediaPickerRoom = null;
        if (cameraCaptureFile != null) { cameraCaptureFile.delete(); cameraCaptureFile = null; }
        mediaThumbnailQueue.clear();
        flushDraftSave();
        selectedRoom = null;
        if (chatCompanyMenu != null) chatCompanyMenu.dismiss();
        pendingNotificationMessageId = 0;
        clearSelectedReply();
        nextBeforeId = 0;
        historicalWindow = false;
        if (chatRoot == null) return;
        switchSection("chats");
        brandBar.setVisibility(View.VISIBLE);
        bottomTabs.setVisibility(offlineHistory && !(offlineChatCacheAvailable && offlineTaskCacheAvailable)
                ? View.GONE : View.VISIBLE);
        chatTitle.setText(R.string.chat_v2_rooms);
        refreshRoomCompanySubtitle();
        chatTitleBar.setVisibility(View.GONE);
        roomListHeader.setVisibility(View.VISIBLE);
        roomScroll.setVisibility(View.VISIBLE);
        refreshHint.setVisibility(View.GONE);
        roomBackButton.setVisibility(View.GONE);
        roomTasksButton.setVisibility(View.GONE);
        olderControl.setVisibility(View.GONE);
        newerControl.setVisibility(View.GONE);
        messageFrame.setVisibility(View.GONE);
        composerRow.setVisibility(View.GONE);
        retryButton.setVisibility(View.GONE);
        mediaReviewButton.setVisibility(View.GONE);
        resolvePendingButton.setVisibility(View.GONE);
        stalePendingButton.setVisibility(View.GONE);
        renderRooms();
        refreshChatCompanySelector();
        if (offlineHistory) {
            chatNotice.setOnClickListener(null);
            chatNotice.setText(offlineNotice());
        }
        handler.post(this::flushLiveUi);
    }

    private void renderRooms() {
        if (roomItems == null) return;
        roomItems.removeAllViews();
        roomItems.setGravity(Gravity.TOP);
        try {
            boolean hasPending = sendAllowed() && verified && account != null && outbox != null
                    && !outbox.pageForAccount(account, 0).isEmpty();
            roomPendingButton.setVisibility(hasPending ? View.VISIBLE : View.GONE);
        } catch (Exception storage) {
            roomPendingButton.setVisibility(View.GONE);
            chatNotice.setText(R.string.chat_v2_save_failed);
            return;
        }
        if (rooms.isEmpty()) {
            chatNotice.setText("");
            roomItems.setGravity(Gravity.CENTER);
            roomItems.addView(Ui.emptyState(this, getString(R.string.chat_v2_no_rooms),
                    getString(R.string.chat_v2_rooms_empty_hint)),
                    new LinearLayout.LayoutParams(-1, -1));
            return;
        }
        chatNotice.setText("");
        String query = roomSearchInput == null ? "" : roomSearchInput.getText().toString().trim()
                .toLowerCase(Locale.ROOT);
        int shown = 0;
        boolean showCompany = v1Companies.size() > 1;
        for (Room room : rooms) {
            String companyName = showCompany ? companyNameForId(room.companyId, "") : "";
            if (!query.isEmpty() && !room.name.toLowerCase(Locale.ROOT).contains(query)
                    && !companyName.toLowerCase(Locale.ROOT).contains(query)) continue;
            shown++;
            LinearLayout entry = Ui.row(this);
            Ui.pad(entry, 14, 8);
            float fontScale = getResources().getConfiguration().fontScale;
            entry.setMinimumHeight(Ui.dp(this, Ui.ROOM_ROW_MIN_DP * Math.max(1f, fontScale)));
            entry.addView(roomAvatarView(room), new LinearLayout.LayoutParams(
                    dp(Ui.ROOM_AVATAR_DP), dp(Ui.ROOM_AVATAR_DP)));
            LinearLayout labelColumn = Ui.column(this);
            LinearLayout titleRow = Ui.row(this);
            TextView name = Ui.text(this, room.name, Ui.ROOM_TITLE_SP, Ui.INK, true);
            name.setMaxLines(2);
            name.setEllipsize(android.text.TextUtils.TruncateAt.END);
            titleRow.addView(name, new LinearLayout.LayoutParams(0, -2, 1));
            if (!room.lastMessageAt.isEmpty()) {
                TextView lastTime = Ui.text(this, formatRoomListTime(room.lastMessageAt),
                        Ui.CHAT_TIME_SP, Ui.MUTED, false);
                lastTime.setSingleLine(true);
                LinearLayout.LayoutParams timeSize = new LinearLayout.LayoutParams(-2, -2);
                timeSize.setMarginStart(dp(8));
                titleRow.addView(lastTime, timeSize);
            }
            labelColumn.addView(titleRow, new LinearLayout.LayoutParams(-1, -2));
            LinearLayout subtitleRow = Ui.row(this);
            String preview = room.lastMessagePreview.isEmpty()
                    ? (room.lastMessageKind.isEmpty()
                            ? getString(R.string.chat_v2_room_label)
                            : mediaKindDescription(room.lastMessageKind))
                    : room.lastMessagePreview;
            TextView subtitle = Ui.text(this, preview, Ui.CHAT_PREVIEW_SP, Ui.MUTED, false);
            subtitle.setSingleLine(true);
            subtitle.setEllipsize(android.text.TextUtils.TruncateAt.END);
            subtitleRow.addView(subtitle, new LinearLayout.LayoutParams(0, -2, 1));
            if (room.unreadCount > 0) {
                TextView badge = Ui.text(this, room.unreadCount > 99 ? "99+"
                        : String.valueOf(room.unreadCount), Ui.CHAT_META_SP, Color.WHITE, true);
                badge.setGravity(Gravity.CENTER);
                badge.setBackground(Ui.bg(Ui.GREEN, 20, this));
                badge.setMinWidth(dp(22));
                LinearLayout.LayoutParams badgeSize = new LinearLayout.LayoutParams(-2, dp(22));
                badgeSize.setMarginStart(dp(8));
                subtitleRow.addView(badge, badgeSize);
            }
            if (room.isGroup && room.hasActiveTask) {
                TextView taskChip = Ui.text(this, getString(R.string.bchat_room_has_tasks),
                        Ui.CHAT_META_SP, Ui.GREEN, true);
                taskChip.setSingleLine(true);
                taskChip.setBackground(Ui.bg(0xffe6f3fb, 14, this));
                LinearLayout.LayoutParams taskChipSize = new LinearLayout.LayoutParams(-2, dp(22));
                taskChipSize.setMarginStart(dp(8));
                subtitleRow.addView(taskChip, taskChipSize);
            }
            labelColumn.addView(subtitleRow, new LinearLayout.LayoutParams(-1, -2));
            if (showCompany && !companyName.isEmpty()) {
                TextView companyLabel = Ui.text(this, companyName, Ui.CHAT_META_SP,
                        Ui.MUTED, false);
                companyLabel.setSingleLine(true);
                companyLabel.setEllipsize(android.text.TextUtils.TruncateAt.END);
                LinearLayout.LayoutParams companySize = new LinearLayout.LayoutParams(-1, -2);
                companySize.topMargin = dp(2);
                labelColumn.addView(companyLabel, companySize);
            }
            LinearLayout.LayoutParams labelSize = new LinearLayout.LayoutParams(0, -2, 1);
            labelSize.setMarginStart(dp(10));
            entry.addView(labelColumn, labelSize);
            entry.setContentDescription(companyName.isEmpty() ? room.name
                    : room.name + ", " + companyName);
            Ui.clickable(entry);
            entry.setOnClickListener(v -> selectRoom(room));
            roomItems.addView(entry, new LinearLayout.LayoutParams(-1, -2));
            LinearLayout.LayoutParams dividerSize = new LinearLayout.LayoutParams(-1, dp(1));
            dividerSize.setMarginStart(dp(72));
            roomItems.addView(Ui.line(this), dividerSize);
        }
        if (shown == 0) {
            roomItems.setGravity(Gravity.CENTER);
            roomItems.addView(Ui.emptyState(this, getString(R.string.chat_v2_no_room_matches), ""),
                    new LinearLayout.LayoutParams(-1, -1));
        }
    }

    private void loadRooms() {
        if (!chatAllowed()) return;
        boolean initial = chatRoot.getVisibility() != View.VISIBLE;
        final int requestUnreadMetadataGeneration = unreadMetadataGeneration;
        if (initial) shellNotice.setText(R.string.chat_v2_loading);
        else chatNotice.setText(R.string.chat_v2_loading);
        fetchV2("GET", V2_ROOMS, null, (statusCode, result) -> {
            if (handleV2TransportFailure(statusCode)) return;
            try {
                if (statusCode != 200 || result == null || positiveId(result.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                if (requestUnreadMetadataGeneration != unreadMetadataGeneration) {
                    loadRooms();
                    return;
                }
                JSONArray list = result.getJSONArray("rooms");
                if (list.length() > 100) throw new IllegalArgumentException();
                List<Room> validated = new ArrayList<>();
                Set<Long> roomIds = new HashSet<>();
                for (int i = 0; i < list.length(); i++) {
                    JSONObject item = list.getJSONObject(i);
                    long id = positiveId(item.get("id"));
                    long company = positiveId(item.get("company_id"));
                    long membership = positiveId(item.get("membership_id"));
                    String name = item.getString("name");
                    if (!roomIds.add(id) || !v1Companies.contains(company) || name.trim().isEmpty()
                            || name.getBytes(StandardCharsets.UTF_8).length > 256
                            || name.indexOf('\n') >= 0 || name.indexOf('\r') >= 0)
                        throw new IllegalArgumentException();
                    String policy = item.getString("invoice_policy");
                    int version = item.getInt("invoice_policy_version");
                    if (!("off".equals(policy) || "select_on_upload".equals(policy)
                            || "invoice_default".equals(policy)) || version < 1)
                        throw new IllegalArgumentException();
                    Room room = new Room(id, company, membership, name, policy, version);
                    room.lastMessageId = nonnegativeCursor(item.get("last_message_id"));
                    room.lastMessagePreview = item.opt("last_message_preview") instanceof String
                            ? item.optString("last_message_preview") : "";
                    room.lastMessageAt = item.opt("last_message_at") instanceof String
                            ? item.optString("last_message_at") : "";
                    room.lastMessageKind = item.opt("last_message_kind") instanceof String
                            ? item.optString("last_message_kind") : "";
                    room.unreadCount = item.optInt("unread_count", 0);
                    room.avatarVersion = item.optInt("avatar_version", 0);
                    room.memberCount = item.optInt("member_count", 0);
                    room.groupAdmin = item.optBoolean("is_group_admin", false);
                    room.isGroup = item.optBoolean("is_group", false);
                    room.hasActiveTask = item.optBoolean("has_active_task", false);
                    if (room.lastMessagePreview.length() > 512 || room.unreadCount < 0
                            || room.avatarVersion < 0 || room.memberCount < 0)
                        throw new IllegalArgumentException();
                    if (!(room.lastMessageKind.isEmpty()
                            || "image".equals(room.lastMessageKind)
                            || "audio".equals(room.lastMessageKind)
                            || "file".equals(room.lastMessageKind)))
                        throw new IllegalArgumentException();
                    validated.add(room);
                }
                Room active = selectedRoom;
                Room refreshedActive = null;
                if (active != null) {
                    for (int i = 0; i < validated.size(); i++) {
                        Room candidate = validated.get(i);
                        if (active.sameMembership(candidate)) {
                            active.updateMetadata(candidate);
                            validated.set(i, active);
                            refreshedActive = active;
                            break;
                        }
                    }
                    if (refreshedActive == null) {
                        showRooms();
                        if (mediaStore != null && account != null) {
                            try {
                                BChatConnectedMediaStore.Entry stale = mediaStore.pending(account,
                                        active.id, active.membershipId);
                                if (stale != null) mediaStore.discard(account, stale);
                            } catch (IOException ignored) { /* The server still denies the stale membership. */ }
                        }
                    }
                    else {
                        chatTitle.setText(active.name);
                        refreshRoomCompanySubtitle();
                        roomAvatarSlot.removeAllViews();
                        roomAvatarSlot.addView(roomAvatarView(active),
                                new FrameLayout.LayoutParams(-1, -1));
                    }
                }
                rooms.clear();
                rooms.addAll(validated);
                ++roomMetadataGeneration;
                if (historyCache != null && account != null) {
                    List<ConnectedHistoryCache.RoomRecord> snapshot = new ArrayList<>();
                    for (Room room : validated)
                        snapshot.add(new ConnectedHistoryCache.RoomRecord(room.id, room.membershipId,
                                room.companyId, room.name, room.invoicePolicy, room.invoicePolicyVersion));
                    AccountScope scopedAccount = account;
                    ConnectedHistoryCache cache = historyCache;
                    boolean remembered = preferences().getBoolean(REMEMBER, false);
                    queueHistoryWrite(scopedAccount, cache,
                            () -> cache.reconcile(scopedAccount, remembered, snapshot));
                }
                if (initial) {
                    shell.setVisibility(View.GONE);
                    chatRoot.setVisibility(View.VISIBLE);
                    if (loginReleaseFooter != null) loginReleaseFooter.setVisibility(View.GONE);
                    layout.setPadding(0, 0, 0, 0);
                    showRooms();
                } else renderRooms();
                openDeferredPushRoomIfPresent();
                if (unresolvedSendNotice) {
                    chatNotice.setText(R.string.chat_v2_uncertain);
                    unresolvedSendNotice = false;
                }
                processPendingPush();
                // Resolve the orders capability before optional push registration can
                // occupy the single v2 request channel with a retry.
                maybeProbeOrderCapability();
                maybeRegisterPush();
                handler.post(this::refreshAttentionBadge);
                startLiveSync();
            } catch (Exception invalid) {
                if (statusCode == 403) {
                    purgeHistory();
                    clearChatView();
                    showShell();
                    shellNotice.setText(R.string.chat_v2_denied);
                    lastPermissionRefreshAt = 0;
                    refreshPermissionSet();
                    return;
                }
                boolean uncertain = unresolvedSendNotice;
                clearChatView();
                if (initial) {
                    releaseWeb();
                    showShell();
                    shellNotice.setText(uncertain ? R.string.chat_v2_uncertain
                            : R.string.chat_v2_load_failed);
                    shellRetry.setVisibility(View.VISIBLE);
                } else {
                    chatRoot.setVisibility(View.VISIBLE);
                    if (loginReleaseFooter != null) loginReleaseFooter.setVisibility(View.GONE);
                    showRooms();
                    chatNotice.setText(uncertain ? R.string.chat_v2_uncertain : R.string.chat_v2_load_failed);
                }
            }
        });
    }

    private void refreshAttentionBadge() {
        if (!verified || account == null || attentionLoading
                || (!permissionSet.chatView && !permissionSet.taskView)) return;
        if (v2Busy) {
            handler.postDelayed(this::refreshAttentionBadge, 350);
            return;
        }
        attentionLoading = true;
        fetchV2("GET", V2_ATTENTION, null, (statusCode, result) -> {
            attentionLoading = false;
            if (statusCode != 200 || result == null) return;
            try {
                updateAttentionBadge(result);
            } catch (Exception ignored) { /* Keep the last safe badge value. */ }
        });
    }

    private void updateAttentionBadge(JSONObject result) throws Exception {
        if (positiveId(result.get("api_version")) != 2) throw new IllegalArgumentException();
        int count = result.getInt("badge_count");
        boolean overflow = result.optBoolean("badge_overflow", false);
        if (count < 0 || count > 50 || headerAttentionBadge == null) throw new IllegalArgumentException();
        headerAttentionBadge.setText(count == 0 ? "" : overflow ? "50+" : String.valueOf(count));
        headerAttentionBadge.setVisibility(count == 0 ? View.GONE : View.VISIBLE);
        headerAttention.setContentDescription(getString(R.string.bchat_attention_count, count));
    }

    private void showAttentionCenter() {
        if (!verified || account == null || (!permissionSet.chatView && !permissionSet.taskView)) return;
        if (attentionDialog != null && attentionDialog.isShowing()) return;
        LinearLayout content = Ui.column(this);
        Ui.pad(content, 16, 6);
        TextView notice = Ui.text(this, getString(R.string.bchat_attention_loading), 14, Ui.MUTED, false);
        content.addView(notice, new LinearLayout.LayoutParams(-1, -2));
        attentionDialog = new AlertDialog.Builder(this)
                .setTitle(R.string.bchat_attention).setView(content)
                .setPositiveButton(R.string.bchat_attention_tasks, (dialog, which) -> switchSection("tasks"))
                .setNeutralButton(R.string.bchat_attention_messages, (dialog, which) -> switchSection("chats"))
                .setNegativeButton(R.string.task_close, null).create();
        attentionDialog.setOnDismissListener(dialog -> attentionDialog = null);
        attentionDialog.show();
        Ui.decorateDialog(attentionDialog);
        attentionDialog.getButton(AlertDialog.BUTTON_POSITIVE).setVisibility(
                permissionSet.taskView ? View.VISIBLE : View.GONE);
        attentionDialog.getButton(AlertDialog.BUTTON_NEUTRAL).setVisibility(
                permissionSet.chatView ? View.VISIBLE : View.GONE);
        loadAttentionPanel(content, notice, attentionDialog, 0);
    }

    private void loadAttentionPanel(LinearLayout content, TextView notice, AlertDialog dialog, int retry) {
        if (dialog == null || !dialog.isShowing()) return;
        if (v2Busy) {
            if (retry < 12) handler.postDelayed(() -> loadAttentionPanel(content, notice, dialog, retry + 1), 180);
            else notice.setText(R.string.bchat_attention_unavailable);
            return;
        }
        fetchV2("GET", V2_ATTENTION, null, (statusCode, result) -> {
            if (dialog != attentionDialog || !dialog.isShowing()) return;
            try {
                if (statusCode != 200 || result == null) throw new IllegalArgumentException();
                updateAttentionBadge(result);
                JSONArray messages = result.getJSONArray("messages");
                JSONArray taskRows = result.getJSONArray("tasks");
                if (messages.length() > 25 || taskRows.length() > 25) throw new IllegalArgumentException();
                content.removeAllViews();
                addAttentionSection(content, R.string.bchat_attention_messages, messages, true);
                addAttentionSection(content, R.string.bchat_attention_tasks, taskRows, false);
                if (content.getChildCount() == 0) {
                    content.addView(Ui.emptyState(this, getString(R.string.bchat_attention_empty), ""),
                            new LinearLayout.LayoutParams(-1, -2));
                }
            } catch (Exception invalid) { notice.setText(R.string.bchat_attention_unavailable); }
        });
    }

    private void addAttentionSection(LinearLayout content, int heading, JSONArray rows, boolean messages)
            throws Exception {
        if (rows.length() == 0) return;
        TextView title = Ui.text(this, getString(heading), 14, Ui.INK, true);
        LinearLayout.LayoutParams titleSize = new LinearLayout.LayoutParams(-1, -2);
        titleSize.setMargins(0, dp(8), 0, dp(6));
        content.addView(title, titleSize);
        for (int index = 0; index < rows.length(); index++) {
            JSONObject row = rows.getJSONObject(index);
            LinearLayout card = Ui.column(this);
            Ui.pad(card, 12, 10);
            card.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 12, this));
            String primary;
            String secondary;
            if (messages) {
                long companyId = positiveId(row.get("company_id"));
                positiveId(row.get("room_id")); positiveId(row.get("message_id"));
                int unread = row.getInt("unread_count");
                if (!v1Companies.contains(companyId) || unread < 1 || unread > 100000) throw new IllegalArgumentException();
                primary = boundedTaskText(row.getString("room_name"), 256, true);
                secondary = boundedTaskText(row.optString("author_name", ""), 256, false) + " · "
                        + boundedTaskText(row.optString("preview", ""), 160, false);
            } else {
                Task task = new Task(row);
                if (!v1Companies.contains(task.companyId)) throw new IllegalArgumentException();
                primary = task.title;
                secondary = getString(taskStateLabel(task.state)) + " · " + task.assigneeName;
            }
            TextView line1 = Ui.text(this, primary, 15, Ui.INK, true);
            line1.setSingleLine(true); line1.setEllipsize(android.text.TextUtils.TruncateAt.END);
            card.addView(line1, new LinearLayout.LayoutParams(-1, -2));
            TextView line2 = Ui.text(this, secondary, 12, Ui.MUTED, false);
            line2.setMaxLines(2); line2.setEllipsize(android.text.TextUtils.TruncateAt.END);
            LinearLayout.LayoutParams line2Size = new LinearLayout.LayoutParams(-1, -2);
            line2Size.topMargin = dp(4);
            card.addView(line2, line2Size);
            LinearLayout.LayoutParams cardSize = new LinearLayout.LayoutParams(-1, -2);
            cardSize.setMargins(0, 0, 0, dp(7));
            content.addView(card, cardSize);
        }
    }

    /** Complete a validated push after a one-time room-index refresh. */
    private void openDeferredPushRoomIfPresent() {
        if (pendingPushRoomId <= 0 || pendingPushRoomMessageId <= 0) return;
        long roomId = pendingPushRoomId;
        long messageId = pendingPushRoomMessageId;
        pendingPushRoomId = 0;
        pendingPushRoomMessageId = 0;
        for (Room room : rooms) {
            if (room.id == roomId) {
                selectRoom(room, messageId);
                return;
            }
        }
        pushUnavailable();
    }

    private void selectRoom(Room room) {
        if (!chatAllowed()) return;
        selectRoom(room, 0);
    }

    private void selectRoom(Room room, long notifiedMessageId) {
        if ((!chatAllowed() && !offlineHistory) || room == null || !rooms.contains(room)
                || v2Busy || (!offlineHistory && csrfToken == null)) return;
        ++mediaSessionGeneration;
        stopInlineAudio();
        closeMediaUpload();
        closeMediaRead();
        if (connectedVoiceRecorder != null) {
            connectedVoiceRecorder.cancel(); connectedVoiceRecorder = null;
        }
        stopRecordingBadge();
        clearVoicePreview();
        mediaStageBusy = false;
        mediaPickerAccount = null;
        mediaPickerRoom = null;
        if (cameraCaptureFile != null) { cameraCaptureFile.delete(); cameraCaptureFile = null; }
        mediaThumbnailQueue.clear();
        if (mediaPreviewDialog != null) mediaPreviewDialog.dismiss();
        selectedRoom = room;
        if (room.companyId != selectedChatCompanyId && v1Companies.contains(room.companyId)) {
            selectedChatCompanyId = room.companyId;
            refreshChatCompanySelector();
        }
        pendingNotificationMessageId = notifiedMessageId;
        mediaReplayAfterInitialHistory = true;
        clearSelectedReply();
        nextBeforeId = 0;
        historicalWindow = false;
        newerControl.setVisibility(View.GONE);
        switchSection("chats");
        brandBar.setVisibility(View.GONE);
        bottomTabs.setVisibility(View.GONE);
        roomListHeader.setVisibility(View.GONE);
        roomSearchSurface.setVisibility(View.GONE);
        if (roomSearchInput.length() > 0) roomSearchInput.setText("");
        roomSearchInput.clearFocus();
        android.view.inputmethod.InputMethodManager keyboard =
                (android.view.inputmethod.InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (keyboard != null) keyboard.hideSoftInputFromWindow(roomSearchInput.getWindowToken(), 0);
        chatTitle.setText(room.name);
        refreshRoomCompanySubtitle();
        roomAvatarSlot.removeAllViews();
        roomAvatarSlot.addView(roomAvatarView(room), new FrameLayout.LayoutParams(-1, -1));
        chatTitleBar.setVisibility(View.VISIBLE);
        roomScroll.setVisibility(View.GONE);
        refreshHint.setVisibility(View.GONE);
        roomBackButton.setVisibility(View.VISIBLE);
        roomTasksButton.setVisibility(View.VISIBLE);
        messageFrame.setVisibility(View.VISIBLE);
        olderButton.setText(offlineHistory ? R.string.chat_v2_older_saved : R.string.chat_v2_older);
        composerRow.setVisibility(View.VISIBLE);
        composerRow.setVisibility(sendAllowed() ? View.VISIBLE : View.GONE);
        mediaPickButton.setVisibility(CONNECTED_MEDIA_UI_ENABLED && mediaUploadAllowed() ? View.VISIBLE : View.GONE);
        mediaVoiceButton.setVisibility(CONNECTED_MEDIA_UI_ENABLED && mediaUploadAllowed() ? View.VISIBLE : View.GONE);
        displayedMessages.clear();
        olderPageLoading = false;
        olderPageFailed = false;
        messageAdapter.notifyDataSetChanged();
        ++messageRenderSerial;
        if (offlineHistory) {
            roomTasksButton.setVisibility(View.GONE);
            composerRow.setVisibility(View.GONE);
            showCachedMessages(room, 0, true);
            return;
        }
        String savedDraft = outbox == null || account == null ? null
                : outbox.draft(account, room.id, room.membershipId);
        suppressDraftChanges = true;
        messageInput.setText(savedDraft == null ? "" : savedDraft);
        suppressDraftChanges = false;
        draftActive = true; // Every new text is a draft until persisted into the outbox.
        updatePendingUi();
        showCachedMessages(room, 0, true);
        loadMessages(notifiedMessageId > 0 && notifiedMessageId < 2147483647L
                ? notifiedMessageId + 1 : 0);
    }

    private void clearSelectedReply() {
        selectedReplyMessageId = 0;
        if (replyPreview != null) replyPreview.setText("");
        if (replyTray != null) replyTray.setVisibility(View.GONE);
    }

    private void selectReply(Room room, long messageId, String author, String text) {
        if (room == null || selectedRoom != room || messageId <= 0) return;
        selectedReplyMessageId = messageId;
        String preview = text.replace('\n', ' ').replace('\r', ' ').trim();
        if (preview.isEmpty()) preview = getString(R.string.chat_v2_attachment_reply);
        if (preview.length() > 100) preview = preview.substring(0, 100) + "…";
        replyPreview.setText(getString(R.string.chat_v2_reply_preview, author, preview));
        replyTray.setVisibility(View.VISIBLE);
        messageInput.requestFocus();
    }

    private void updatePendingUi() {
        if (selectedRoom == null || outbox == null || account == null) return;
        if (!sendAllowed()) {
            retryButton.setVisibility(View.GONE);
            resolvePendingButton.setVisibility(View.GONE);
            pendingActionsRow.setVisibility(View.GONE);
            stalePendingButton.setVisibility(View.GONE);
            mediaReviewButton.setVisibility(View.GONE);
            sendButton.setEnabled(false);
            return;
        }
        BChatV2Outbox.Entry pending = outbox.first(account, selectedRoom.id, selectedRoom.membershipId);
        BChatV2Outbox.Entry stale = outbox.firstStale(account, selectedRoom.id, selectedRoom.membershipId);
        retryButton.setVisibility(pending == null || pending.reviewCode == 1 ? View.GONE : View.VISIBLE);
        resolvePendingButton.setVisibility(pending == null ? View.GONE : View.VISIBLE);
        pendingActionsRow.setVisibility(pending == null ? View.GONE : View.VISIBLE);
        stalePendingButton.setVisibility(stale == null ? View.GONE : View.VISIBLE);
        boolean mediaPending = false;
        boolean mediaPolicyChanged = false;
        try {
            List<BChatConnectedMediaStore.Entry> mediaEntries = mediaStore == null
                    ? Collections.emptyList() : mediaStore.pendingForRoom(account, selectedRoom.id,
                    selectedRoom.membershipId);
            mediaPending = !mediaEntries.isEmpty();
            for (BChatConnectedMediaStore.Entry mediaEntry : mediaEntries)
                if (mediaEntry.policyVersion != selectedRoom.invoicePolicyVersion)
                    mediaPolicyChanged = true;
        } catch (IOException damaged) { chatNotice.setText(R.string.chat_v2_save_failed); mediaPending = true; }
        boolean inFlight = mediaStageBusy || mediaUploadBusy || mediaConfirmBusy
                && mediaConfirmRoom != null && mediaConfirmRoom.sameMembership(selectedRoom);
        mediaReviewButton.setVisibility(CONNECTED_MEDIA_UI_ENABLED && mediaPending && !inFlight
                ? View.VISIBLE : View.GONE);
        sendButton.setEnabled(sendAllowed() && pending == null && !mediaPending && !v2Busy
                && !inFlight);
        // The actionable review controls already explain pending messages below the thread.
        // Keep the conversation area free of a duplicate, non-actionable banner.
        if (pending != null || stale != null) chatNotice.setText("");
        else if (inFlight) chatNotice.setText(mediaConfirmBusy
                ? R.string.bchat_media_sending : R.string.bchat_media_uploading);
        else if (mediaPending) chatNotice.setText(mediaPolicyChanged
                ? R.string.bchat_media_policy_changed : R.string.bchat_media_pending);
    }

    private void showPendingDialog(AlertDialog.Builder builder) {
        if (pendingDialog != null) pendingDialog.dismiss();
        AlertDialog dialog = builder.create();
        pendingDialog = dialog;
        dialog.setOnDismissListener(ignored -> { if (pendingDialog == dialog) pendingDialog = null; });
        dialog.show();
        Ui.decorateDialog(dialog);
    }

    private boolean stillAccount(AccountScope verifiedAccount) {
        return !closed && verified && account == verifiedAccount && selectedRoom == null
                && chatRoot.getVisibility() == View.VISIBLE && outbox != null;
    }

    private void showGlobalPending(long afterId) {
        AccountScope verifiedAccount = account;
        if (verifiedAccount == null || !stillAccount(verifiedAccount)) return;
        try {
            List<BChatV2Outbox.Entry> page = outbox.pageForAccount(verifiedAccount, afterId);
            if (page.isEmpty()) {
                showPendingDialog(new AlertDialog.Builder(this)
                        .setTitle(R.string.chat_v2_global_pending)
                        .setMessage(R.string.chat_v2_no_local_pending)
                        .setPositiveButton(R.string.chat_v2_cancel, null));
                return;
            }
            int count = Math.min(page.size(), 30);
            String[] labels = new String[count + (page.size() > 30 ? 1 : 0)];
            for (int i = 0; i < count; i++) {
                BChatV2Outbox.Entry entry = page.get(i);
                labels[i] = getString(R.string.chat_v2_local_request,
                        String.valueOf(entry.roomId), String.valueOf(entry.id));
            }
            if (page.size() > 30) labels[count] = getString(R.string.chat_v2_more_pending);
            showPendingDialog(new AlertDialog.Builder(this)
                    .setTitle(R.string.chat_v2_global_pending)
                    .setItems(labels, (dialog, which) -> {
                        if (!stillAccount(verifiedAccount)) return;
                        if (which == count) showGlobalPending(page.get(count - 1).id);
                        else showGlobalEntry(verifiedAccount, page.get(which));
                    })
                    .setNegativeButton(R.string.chat_v2_cancel, null));
        } catch (Exception storage) { chatNotice.setText(R.string.chat_v2_save_failed); }
    }

    private void showGlobalEntry(AccountScope verifiedAccount, BChatV2Outbox.Entry entry) {
        if (!stillAccount(verifiedAccount)) return;
        TextView text = new TextView(this);
        text.setText(entry.body);
        text.setTextSize(16);
        text.setTextColor(0xff243e54);
        text.setPadding(dp(18), dp(12), dp(18), dp(12));
        ScrollView scroll = new ScrollView(this);
        scroll.addView(text);
        AlertDialog.Builder builder = new AlertDialog.Builder(this)
                .setTitle(R.string.chat_v2_local_text)
                .setMessage(R.string.chat_v2_global_warning)
                .setView(scroll)
                .setNeutralButton(R.string.chat_v2_delete_local,
                        (dialog, which) -> confirmGlobalDiscard(verifiedAccount, entry))
                .setNegativeButton(R.string.chat_v2_cancel, null);
        if (!rooms.isEmpty()) builder.setPositiveButton(R.string.chat_v2_restore_draft,
                (dialog, which) -> chooseTargetRoom(verifiedAccount, entry));
        showPendingDialog(builder);
    }

    private void chooseTargetRoom(AccountScope verifiedAccount, BChatV2Outbox.Entry entry) {
        if (!stillAccount(verifiedAccount) || rooms.isEmpty()) return;
        List<Room> choices = new ArrayList<>(rooms);
        String[] labels = new String[choices.size()];
        for (int i = 0; i < choices.size(); i++) labels[i] = choices.get(i).name;
        showPendingDialog(new AlertDialog.Builder(this)
                .setTitle(R.string.chat_v2_choose_draft_room)
                .setItems(labels, (dialog, which) -> confirmGlobalConvert(verifiedAccount, entry, choices.get(which)))
                .setNegativeButton(R.string.chat_v2_cancel, null));
    }

    private void confirmGlobalConvert(AccountScope verifiedAccount, BChatV2Outbox.Entry entry, Room target) {
        if (!stillAccount(verifiedAccount) || !rooms.contains(target)) return;
        try {
            boolean replacing = outbox.draft(verifiedAccount, target.id, target.membershipId) != null;
            showPendingDialog(new AlertDialog.Builder(this)
                    .setTitle(R.string.chat_v2_restore_draft)
                    .setMessage(replacing ? R.string.chat_v2_global_replace_warning
                            : R.string.chat_v2_global_restore_warning)
                    .setPositiveButton(R.string.chat_v2_restore_draft, (dialog, which) -> {
                        if (!stillAccount(verifiedAccount) || !rooms.contains(target)) return;
                        try {
                            if (!outbox.convertToDraft(verifiedAccount, entry, target.id,
                                    target.membershipId, replacing)) throw new IllegalStateException("Pending changed");
                            renderRooms();
                            selectRoom(target);
                            chatNotice.setText(R.string.chat_v2_draft_restored);
                        } catch (Exception storage) { chatNotice.setText(R.string.chat_v2_save_failed); }
                    })
                    .setNegativeButton(R.string.chat_v2_cancel, null));
        } catch (Exception storage) { chatNotice.setText(R.string.chat_v2_save_failed); }
    }

    private void confirmGlobalDiscard(AccountScope verifiedAccount, BChatV2Outbox.Entry entry) {
        if (!stillAccount(verifiedAccount)) return;
        showPendingDialog(new AlertDialog.Builder(this)
                .setTitle(R.string.chat_v2_delete_local)
                .setMessage(R.string.chat_v2_delete_warning)
                .setPositiveButton(R.string.chat_v2_delete_local, (dialog, which) -> {
                    if (!stillAccount(verifiedAccount)) return;
                    try {
                        if (!outbox.discard(verifiedAccount, entry)) throw new IllegalStateException("Pending changed");
                        renderRooms();
                        chatNotice.setText(R.string.chat_v2_local_deleted);
                    } catch (Exception storage) { chatNotice.setText(R.string.chat_v2_save_failed); }
                })
                .setNegativeButton(R.string.chat_v2_cancel, null));
    }

    private void reviewPending(boolean oldMembership) {
        Room room = selectedRoom;
        AccountScope verifiedAccount = account;
        if (room == null || verifiedAccount == null || outbox == null || v2Busy) return;
        BChatV2Outbox.Entry entry = oldMembership
                ? outbox.firstStale(verifiedAccount, room.id, room.membershipId)
                : outbox.first(verifiedAccount, room.id, room.membershipId);
        if (entry == null) { updatePendingUi(); return; }
        showPendingDialog(new AlertDialog.Builder(this)
                .setTitle(oldMembership ? R.string.chat_v2_review_old_pending : R.string.chat_v2_review_pending)
                .setMessage(R.string.chat_v2_uncertain_explain)
                .setPositiveButton(R.string.chat_v2_restore_draft,
                        (dialog, which) -> confirmConvertToDraft(verifiedAccount, room, entry))
                .setNeutralButton(R.string.chat_v2_delete_local,
                        (dialog, which) -> confirmDiscard(verifiedAccount, room, entry))
                .setNegativeButton(R.string.chat_v2_cancel, null));
    }

    private boolean stillCurrent(AccountScope verifiedAccount, Room room) {
        return !closed && verified && account == verifiedAccount && selectedRoom == room
                && rooms.contains(room) && outbox != null;
    }

    private void confirmConvertToDraft(AccountScope verifiedAccount, Room room, BChatV2Outbox.Entry entry) {
        if (!stillCurrent(verifiedAccount, room)) return;
        boolean replacing = messageInput.length() > 0
                || outbox.draft(verifiedAccount, room.id, room.membershipId) != null;
        showPendingDialog(new AlertDialog.Builder(this)
                .setTitle(R.string.chat_v2_restore_draft)
                .setMessage(replacing ? R.string.chat_v2_restore_replace_warning
                        : R.string.chat_v2_restore_warning)
                .setPositiveButton(R.string.chat_v2_restore_draft, (dialog, which) -> {
                    if (!stillCurrent(verifiedAccount, room)) return;
                    try {
                        if (!outbox.convertToDraft(verifiedAccount, entry, room.id, room.membershipId, replacing))
                            throw new IllegalStateException("Pending changed");
                        suppressDraftChanges = true;
                        messageInput.setText(entry.body);
                        messageInput.setSelection(messageInput.length());
                        suppressDraftChanges = false;
                        draftActive = true;
                        updatePendingUi();
                        chatNotice.setText(R.string.chat_v2_draft_restored);
                    } catch (Exception invalid) {
                        suppressDraftChanges = false;
                        chatNotice.setText(R.string.chat_v2_save_failed);
                    }
                })
                .setNegativeButton(R.string.chat_v2_cancel, null));
    }

    private void confirmDiscard(AccountScope verifiedAccount, Room room, BChatV2Outbox.Entry entry) {
        if (!stillCurrent(verifiedAccount, room)) return;
        showPendingDialog(new AlertDialog.Builder(this)
                .setTitle(R.string.chat_v2_delete_local)
                .setMessage(R.string.chat_v2_delete_warning)
                .setPositiveButton(R.string.chat_v2_delete_local, (dialog, which) -> {
                    if (!stillCurrent(verifiedAccount, room)) return;
                    try {
                        if (!outbox.discard(verifiedAccount, entry)) throw new IllegalStateException("Pending changed");
                        chatNotice.setText(R.string.chat_v2_local_deleted);
                        updatePendingUi();
                    } catch (Exception invalid) { chatNotice.setText(R.string.chat_v2_save_failed); }
                })
                .setNegativeButton(R.string.chat_v2_cancel, null));
    }

    private static final class MediaRecord {
        final long id;
        final int size;
        final String kind, mime, name, sha256, documentType;
        final boolean thumbnailAvailable;
        MediaRecord(JSONObject value) throws Exception {
            id = positiveId(value.get("id"));
            kind = value.getString("kind");
            mime = value.getString("mime");
            name = value.getString("name");
            sha256 = value.getString("sha256");
            documentType = value.getString("document_type");
            thumbnailAvailable = value.getBoolean("thumbnail_available");
            size = value.getInt("size");
            int limit = "image".equals(kind) ? BChatConnectedMediaStore.IMAGE_LIMIT
                    : "audio".equals(kind) ? BChatConnectedMediaStore.AUDIO_LIMIT
                    : "file".equals(kind) ? BChatConnectedMediaStore.PDF_LIMIT : 0;
            if (value.length() != 8 || limit == 0 || size < 1 || size > limit
                    || !("image".equals(kind) ? "image/jpeg".equals(mime)
                    || "image/png".equals(mime) || "image/webp".equals(mime)
                    : "audio".equals(kind) ? "audio/mp4".equals(mime)
                    : "application/pdf".equals(mime)
                    || "application/vnd.openxmlformats-officedocument.wordprocessingml.document".equals(mime)
                    || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet".equals(mime)
                    || "text/plain".equals(mime))
                    || !("other".equals(documentType) || "invoice".equals(documentType)
                    || "payment_receipt".equals(documentType))
                    || name.trim().isEmpty() || name.getBytes(StandardCharsets.UTF_8).length > 160
                    || !sha256.matches("[0-9a-f]{64}") || ("file".equals(kind) && thumbnailAvailable))
                throw new IllegalArgumentException("Invalid media metadata");
            for (int i = 0; i < name.length(); i++)
                if (Character.isISOControl(name.charAt(i))) throw new IllegalArgumentException("Invalid media name");
        }
    }

    private static final class MediaThumbTarget {
        final Room room;
        final MediaRecord media;
        final ImageView image;
        MediaThumbTarget(Room room, MediaRecord media, ImageView image) {
            this.room = room; this.media = media; this.image = image;
        }
    }

    private String mediaThumbKey(Room room, MediaRecord media) {
        return account.key + ":" + room.id + ":" + media.id;
    }

    private void addConnectedMediaCard(LinearLayout bubble, Room room, MediaRecord media, int width) {
        if ("audio".equals(media.kind)) {
            addInlineAudioCard(bubble, room, media, width);
            return;
        }
        LinearLayout card = Ui.column(this);
        Ui.pad(card, 7, 7);
        card.setBackground(Ui.bg(Ui.LIGHT, 10, this));
        card.setMinimumWidth(Math.min(width, dp(180)));
        if ("image".equals(media.kind)) {
            ImageView picture = new ImageView(this);
            picture.setScaleType(ImageView.ScaleType.CENTER_CROP);
            picture.setBackground(Ui.bg(0xffe8edf2, 8, this));
            card.addView(picture, new LinearLayout.LayoutParams(Math.min(width, dp(240)), dp(132)));
        if (CONNECTED_MEDIA_UI_ENABLED && mediaAllowed() && media.thumbnailAvailable) {
                Bitmap cached = mediaThumbnailCache.get(mediaThumbKey(room, media));
                if (cached != null) picture.setImageBitmap(cached);
                else mediaThumbnailQueue.add(new MediaThumbTarget(room, media, picture));
            }
        }
        TextView label = Ui.text(this, media.name, 12, Ui.INK, true);
        label.setSingleLine(true);
        label.setEllipsize(android.text.TextUtils.TruncateAt.END);
        card.addView(label, new LinearLayout.LayoutParams(-1, -2));
        card.setContentDescription(media.name);
        if (CONNECTED_MEDIA_UI_ENABLED) {
            Ui.clickable(card);
            card.setOnClickListener(v -> openConnectedMedia(room, media));
        }
        bubble.addView(card, new LinearLayout.LayoutParams(-2, -2));
    }

    private void addInlineAudioCard(LinearLayout bubble, Room room, MediaRecord media, int width) {
        LinearLayout card = Ui.column(this);
        Ui.pad(card, 5, 3);
        card.setBackground(Ui.bg(Ui.LIGHT, 12, this));
        card.setMinimumWidth(Math.min(width, dp(210)));
        TextView title = Ui.text(this, getString(R.string.bchat_media_voice_message),
                Ui.CHAT_META_SP, Ui.MUTED, true);
        title.setSingleLine(true);
        LinearLayout controls = Ui.row(this);
        controls.setGravity(Gravity.CENTER_VERTICAL);
        controls.setLayoutDirection(View.LAYOUT_DIRECTION_LTR);
        TextView play = Ui.text(this, "▶", 22, Ui.GREEN, true);
        play.setGravity(Gravity.CENTER);
        play.setContentDescription(getString(R.string.bchat_media_play));
        Ui.styleIconAction(play, Ui.IconTone.TONAL);
        controls.addView(play, new LinearLayout.LayoutParams(dp(48), dp(48)));
        SeekBar seek = new SeekBar(this);
        seek.setMax(1000);
        seek.setEnabled(false);
        seek.setContentDescription(getString(R.string.bchat_media_audio_position));
        FrameLayout timeline = new FrameLayout(this);
        timeline.addView(seek, new FrameLayout.LayoutParams(-1, dp(48)));
        WaveformView wave = new WaveformView(this);
        wave.setVisibility(View.GONE);
        wave.setContentDescription(getString(R.string.bchat_media_audio_position));
        timeline.addView(wave, new FrameLayout.LayoutParams(-1, dp(48)));
        controls.addView(timeline, new LinearLayout.LayoutParams(0, dp(48), 1));
        TextView save = Ui.text(this, "↓", 20, Ui.GREEN, true);
        save.setGravity(Gravity.CENTER);
        save.setContentDescription(getString(R.string.bchat_media_save));
        Ui.styleIconAction(save, Ui.IconTone.PLAIN);
        controls.addView(save, new LinearLayout.LayoutParams(dp(48), dp(48)));
        card.addView(controls, new LinearLayout.LayoutParams(-1, -2));
        LinearLayout meta = Ui.row(this);
        meta.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        TextView time = Ui.text(this, "0:00 / --:--", Ui.CHAT_META_SP, Ui.MUTED, false);
        time.setTextDirection(View.TEXT_DIRECTION_LTR);
        time.setGravity(Gravity.END);
        meta.addView(time, new LinearLayout.LayoutParams(dp(82), -2));
        card.addView(meta, new LinearLayout.LayoutParams(-1, -2));
        play.setOnClickListener(v -> toggleInlineAudio(room, media, play, seek, wave, time));
        save.setOnClickListener(v -> saveConnectedAudio(room, media));
        if (inlineAudioRoom == room && inlineAudioAccount == account
                && inlineAudioMediaId == media.id) {
            inlineAudioPlay = play;
            inlineAudioSeek = seek;
            inlineAudioWave = wave;
            inlineAudioTime = time;
            if (inlineAudioFile != null) showMeasuredAudioWave(inlineAudioFile, media,
                    inlineAudioRequest, seek, wave);
            if (inlineAudioPlayer != null && inlineAudioPrepared) {
                try {
                    seek.setMax(Math.max(1, inlineAudioPlayer.getDuration()));
                    seek.setEnabled(true);
                    seek.setProgress(inlineAudioPlayer.getCurrentPosition());
                    wave.progress(inlineAudioPlayer.getCurrentPosition()
                            / (float)Math.max(1, inlineAudioPlayer.getDuration()));
                    time.setText(audioTime(inlineAudioPlayer.getCurrentPosition(),
                            inlineAudioPlayer.getDuration()));
                    boolean playing = inlineAudioPlayer.isPlaying();
                    play.setText(playing ? "Ⅱ" : "▶");
                    play.setContentDescription(getString(playing ? R.string.bchat_media_pause
                            : R.string.bchat_media_play));
                } catch (IllegalStateException invalid) { stopInlineAudio(); }
            } else {
                play.setText("×");
                play.setContentDescription(getString(R.string.bchat_media_cancel_audio));
                time.setText(R.string.bchat_media_loading_audio);
            }
        }
        seek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onStartTrackingTouch(SeekBar bar) {
                if (inlineAudioSeek == bar) inlineAudioSeeking = true;
            }
            @Override public void onStopTrackingTouch(SeekBar bar) {
                if (inlineAudioSeek == bar && inlineAudioPlayer != null && inlineAudioPrepared) {
                    try { inlineAudioPlayer.seekTo(bar.getProgress()); }
                    catch (IllegalStateException ignored) { stopInlineAudio(); }
                }
                inlineAudioSeeking = false;
            }
            @Override public void onProgressChanged(SeekBar bar, int progress, boolean user) {
                if (user && inlineAudioSeek == bar && inlineAudioPlayer != null && inlineAudioPrepared)
                    time.setText(audioTime(progress, inlineAudioPlayer.getDuration()));
            }
        });
        wave.setOnTouchListener((view, event) -> {
            if (inlineAudioWave != wave || inlineAudioPlayer == null || !inlineAudioPrepared)
                return false;
            if (event.getAction() == MotionEvent.ACTION_DOWN) inlineAudioSeeking = true;
            if (event.getAction() == MotionEvent.ACTION_DOWN
                    || event.getAction() == MotionEvent.ACTION_MOVE
                    || event.getAction() == MotionEvent.ACTION_UP) {
                float fraction = Math.max(0f, Math.min(1f,
                        event.getX() / Math.max(1, view.getWidth())));
                wave.progress(fraction);
                if (event.getAction() == MotionEvent.ACTION_UP) {
                    try { inlineAudioPlayer.seekTo((int)(fraction * inlineAudioPlayer.getDuration())); }
                    catch (IllegalStateException invalid) { stopInlineAudio(); }
                    inlineAudioSeeking = false;
                }
                return true;
            }
            if (event.getAction() == MotionEvent.ACTION_CANCEL) inlineAudioSeeking = false;
            return true;
        });
        bubble.addView(card, new LinearLayout.LayoutParams(Math.min(width, dp(300)), -2));
    }

    private static String audioTime(int position, int duration) {
        int seconds = Math.max(0, position) / 1000;
        int total = Math.max(0, duration) / 1000;
        return String.format(Locale.ROOT, "%d:%02d / %d:%02d",
                seconds / 60, seconds % 60, total / 60, total % 60);
    }

    private void stopInlineAudio() {
        ++inlineAudioRequest;
        if (inlineAudioTicker != null) { handler.removeCallbacks(inlineAudioTicker); inlineAudioTicker = null; }
        if (inlineAudioPlayer != null) {
            inlineAudioPlayer.release();
            inlineAudioPlayer = null;
        }
        if (inlineAudioFile != null) { inlineAudioFile.delete(); inlineAudioFile = null; }
        if (inlineAudioPlay != null) {
            inlineAudioPlay.setText("▶");
            inlineAudioPlay.setContentDescription(getString(R.string.bchat_media_play));
        }
        if (inlineAudioSeek != null) { inlineAudioSeek.setEnabled(false); inlineAudioSeek.setProgress(0); }
        if (inlineAudioWave != null) inlineAudioWave.progress(0f);
        if (inlineAudioTime != null) inlineAudioTime.setText("0:00 / --:--");
        inlineAudioRoom = null;
        inlineAudioAccount = null;
        inlineAudioMediaId = 0;
        inlineAudioPlay = null;
        inlineAudioSeek = null;
        inlineAudioWave = null;
        inlineAudioTime = null;
        inlineAudioPrepared = false;
        inlineAudioSeeking = false;
    }

    private void tickInlineAudio(int request) {
        inlineAudioTicker = () -> {
            if (request != inlineAudioRequest || inlineAudioPlayer == null || !inlineAudioPrepared
                    || !stillCurrent(inlineAudioAccount, inlineAudioRoom)) return;
            try {
                if (!inlineAudioSeeking) {
                    int position = inlineAudioPlayer.getCurrentPosition();
                    int duration = inlineAudioPlayer.getDuration();
                    if (inlineAudioSeek != null) inlineAudioSeek.setProgress(position);
                    if (inlineAudioWave != null) inlineAudioWave.progress(
                            position / (float)Math.max(1, duration));
                    if (inlineAudioTime != null)
                        inlineAudioTime.setText(audioTime(position, duration));
                }
                if (inlineAudioPlayer.isPlaying()) handler.postDelayed(inlineAudioTicker, 250);
            } catch (IllegalStateException invalid) { stopInlineAudio(); }
        };
        handler.post(inlineAudioTicker);
    }

    private void toggleInlineAudio(Room room, MediaRecord media, TextView play,
                                   SeekBar seek, WaveformView wave, TextView time) {
        if (!stillCurrent(account, room) || !mediaAllowed()) return;
        if (inlineAudioRoom == room && inlineAudioMediaId == media.id) {
            if (inlineAudioPlayer == null) { stopInlineAudio(); closeMediaRead(); return; }
            if (!inlineAudioPrepared) return;
            try {
                if (inlineAudioPlayer.isPlaying()) {
                    inlineAudioPlayer.pause();
                    play.setText("▶");
                    play.setContentDescription(getString(R.string.bchat_media_play));
                } else {
                    inlineAudioPlayer.start();
                    play.setText("Ⅱ");
                    play.setContentDescription(getString(R.string.bchat_media_pause));
                    tickInlineAudio(inlineAudioRequest);
                }
            } catch (IllegalStateException invalid) { stopInlineAudio(); }
            return;
        }
        stopInlineAudio();
        closeMediaRead(); // User playback takes priority over queued thumbnails.
        final AccountScope scopedAccount = account;
        final int request = inlineAudioRequest;
        inlineAudioRoom = room;
        inlineAudioAccount = scopedAccount;
        inlineAudioMediaId = media.id;
        inlineAudioPlay = play;
        inlineAudioSeek = seek;
        inlineAudioWave = wave;
        inlineAudioTime = time;
        play.setText("×");
        play.setContentDescription(getString(R.string.bchat_media_cancel_audio));
        time.setText(R.string.bchat_media_loading_audio);
        readConnectedMedia(room, media, false, (file, status) -> {
            if (request != inlineAudioRequest || !stillCurrent(scopedAccount, room)) {
                if (file != null) file.delete();
                return;
            }
            if (file == null) {
                stopInlineAudio();
                if (status == 403) { showRooms(); loadRooms(); }
                else chatNotice.setText(R.string.bchat_media_unavailable);
                return;
            }
            inlineAudioFile = file; // SHA-256 verified, private cache only; no Downloads copy.
            showMeasuredAudioWave(file, media, request, seek, wave);
            try {
                MediaPlayer player = new MediaPlayer();
                inlineAudioPlayer = player;
                try (FileInputStream source = new FileInputStream(file)) {
                    player.setDataSource(source.getFD(), 0, file.length());
                }
                player.setOnPreparedListener(ready -> {
                    if (request != inlineAudioRequest || inlineAudioPlayer != ready) return;
                    inlineAudioPrepared = true;
                    int duration = Math.max(1, ready.getDuration());
                    if (inlineAudioSeek != null) {
                        inlineAudioSeek.setMax(duration);
                        inlineAudioSeek.setEnabled(true);
                    }
                    if (inlineAudioTime != null) inlineAudioTime.setText(audioTime(0, duration));
                    ready.start();
                    if (inlineAudioPlay != null) {
                        inlineAudioPlay.setText("Ⅱ");
                        inlineAudioPlay.setContentDescription(getString(R.string.bchat_media_pause));
                    }
                    tickInlineAudio(request);
                });
                player.setOnCompletionListener(done -> {
                    if (request != inlineAudioRequest || inlineAudioPlayer != done) return;
                    if (inlineAudioPlay != null) {
                        inlineAudioPlay.setText("▶");
                        inlineAudioPlay.setContentDescription(getString(R.string.bchat_media_play));
                    }
                    if (inlineAudioSeek != null) inlineAudioSeek.setProgress(0);
                    if (inlineAudioWave != null) inlineAudioWave.progress(0f);
                    if (inlineAudioTime != null)
                        inlineAudioTime.setText(audioTime(0, done.getDuration()));
                });
                player.setOnErrorListener((failed, what, extra) -> {
                    if (request == inlineAudioRequest) {
                        stopInlineAudio();
                        chatNotice.setText(R.string.bchat_media_unavailable);
                    }
                    return true;
                });
                player.prepareAsync();
            } catch (Exception invalid) {
                stopInlineAudio();
                chatNotice.setText(R.string.bchat_media_unavailable);
            }
        });
    }

    private void showMeasuredAudioWave(File file, MediaRecord media, int request,
                                       SeekBar seek, WaveformView wave) {
        if (connectedWaveforms == null) connectedWaveforms = new AudioWaveforms(this);
        connectedWaveforms.load(file, "connected:" + media.sha256, result -> {
            if (request != inlineAudioRequest || inlineAudioWave != wave) return;
            if (result.peaks != null && result.peaks.length > 0) {
                wave.samples(result.peaks);
                wave.setVisibility(View.VISIBLE);
                seek.setVisibility(View.GONE);
            }
            // Unsupported or long audio retains the honest linear seek bar.
        });
    }

    private void saveConnectedAudio(Room room, MediaRecord media) {
        if (!stillCurrent(account, room) || !mediaAllowed()) return;
        stopInlineAudio();
        closeMediaRead();
        final AccountScope scopedAccount = account;
        readConnectedMedia(room, media, false, (file, status) -> {
            if (file != null && stillCurrent(scopedAccount, room)) prepareDocumentSave(file, room, media);
            else {
                if (file != null) file.delete();
                if (stillCurrent(scopedAccount, room)) chatNotice.setText(R.string.bchat_media_unavailable);
            }
        });
    }

    private void pumpMediaThumbnails() {
        if (mediaReadBusy || !CONNECTED_MEDIA_UI_ENABLED || !mediaAllowed()
                || account == null || selectedRoom == null
                || web == null || mediaThumbnailQueue.isEmpty()) return;
        for (int i = 0; i < mediaThumbnailQueue.size(); i++) {
            MediaThumbTarget target = mediaThumbnailQueue.get(i);
            if (target.room != selectedRoom || !target.image.isAttachedToWindow()) {
                mediaThumbnailQueue.remove(i--); continue;
            }
            Rect visible = new Rect();
            if (!target.image.getGlobalVisibleRect(visible) || visible.isEmpty()) continue;
            mediaThumbnailQueue.remove(i);
            readConnectedMedia(target.room, target.media, true, (file, status) -> {
                if (file == null) { pumpMediaThumbnails(); return; }
                mediaIo.execute(() -> {
                    Bitmap bitmap = null;
                    try {
                        BitmapFactory.Options bounds = new BitmapFactory.Options();
                        bounds.inJustDecodeBounds = true;
                        BitmapFactory.decodeFile(file.getAbsolutePath(), bounds);
                        int sample = 1;
                        while (bounds.outWidth / sample > 1024 || bounds.outHeight / sample > 1024)
                            sample *= 2;
                        BitmapFactory.Options scaled = new BitmapFactory.Options();
                        scaled.inSampleSize = sample;
                        bitmap = BitmapFactory.decodeFile(file.getAbsolutePath(), scaled);
                    } catch (RuntimeException ignored) {
                        // Corrupt media is shown as unavailable; later thumbnails still load.
                    } finally { file.delete(); }
                    Bitmap ready = bitmap;
                    handler.post(() -> {
                        if (ready != null && selectedRoom == target.room && account != null
                                && target.image.isAttachedToWindow()) {
                            mediaThumbnailCache.put(mediaThumbKey(target.room, target.media), ready);
                            target.image.setImageBitmap(ready);
                        } else if (ready != null) ready.recycle();
                        pumpMediaThumbnails();
                    });
                });
            });
            return;
        }
    }

    private void openConnectedMedia(Room room, MediaRecord media) {
        if (!CONNECTED_MEDIA_UI_ENABLED || room != selectedRoom || !mediaAllowed() || account == null) {
            chatNotice.setText(R.string.bchat_media_unavailable); return;
        }
        if (mediaPreviewDialog != null) mediaPreviewDialog.dismiss();
        closeMediaRead(); // A user request takes priority over a queued thumbnail.
        final AccountScope scopedAccount = account;
        final int request = ++mediaOpenNonce;
        if ("image".equals(media.kind)) showImageLoading(room, media, scopedAccount, request);
        readConnectedMedia(room, media, false, (file, status) -> {
            if (request != mediaOpenNonce || !stillCurrent(scopedAccount, room)) {
                if (file != null) file.delete();
                return;
            }
            if (file == null) {
                if (mediaPreviewDialog != null) {
                    AlertDialog loading = mediaPreviewDialog;
                    mediaPreviewDialog = null;
                    loading.dismiss();
                }
                if (status == 403) { showRooms(); loadRooms(); }
                else chatNotice.setText(R.string.bchat_media_unavailable);
                pumpMediaThumbnails();
                return;
            }
            if ("image".equals(media.kind)) showFullImage(file, media, room, scopedAccount, request);
            else prepareDocumentSave(file, room, media);
            pumpMediaThumbnails();
        });
    }

    private void showImageLoading(Room room, MediaRecord media,
                                  AccountScope scopedAccount, int request) {
        LinearLayout content = Ui.column(this);
        content.setBackgroundColor(Color.rgb(12, 18, 25));
        content.setGravity(Gravity.CENTER);
        Ui.pad(content, 16, 16);
        Bitmap thumbnail = mediaThumbnailCache.get(mediaThumbKey(room, media));
        if (thumbnail != null) {
            ImageView preview = new ImageView(this);
            preview.setImageBitmap(thumbnail);
            preview.setScaleType(ImageView.ScaleType.FIT_CENTER);
            content.addView(preview, new LinearLayout.LayoutParams(-1, dp(260)));
        }
        ProgressBar progress = new ProgressBar(this);
        LinearLayout.LayoutParams progressSize = new LinearLayout.LayoutParams(dp(32), dp(32));
        progressSize.gravity = Gravity.CENTER_HORIZONTAL;
        progressSize.topMargin = dp(16);
        content.addView(progress, progressSize);
        TextView loading = Ui.text(this, getString(R.string.bchat_media_loading_image),
                14, Color.WHITE, false);
        loading.setGravity(Gravity.CENTER);
        content.addView(loading, fieldSize(8));
        AlertDialog dialog = new AlertDialog.Builder(this).setView(content)
                .setNegativeButton(R.string.chat_v2_cancel, null).create();
        mediaPreviewDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (mediaPreviewDialog != dialog) return;
            mediaPreviewDialog = null;
            if (request == mediaOpenNonce && stillCurrent(scopedAccount, room)) {
                ++mediaOpenNonce;
                closeMediaRead();
                pumpMediaThumbnails();
            }
        });
        dialog.show();
        if (dialog.getWindow() != null) dialog.getWindow().setLayout(-1, -2);
    }

    private void showFullImage(File file, MediaRecord media, Room room,
                               AccountScope scopedAccount, int request) {
        new Thread(() -> {
            Bitmap bitmap = null;
            try {
                BitmapFactory.Options bounds = new BitmapFactory.Options();
                bounds.inJustDecodeBounds = true;
                BitmapFactory.decodeFile(file.getAbsolutePath(), bounds);
                int sample = 1;
                while (bounds.outWidth / sample > 2048 || bounds.outHeight / sample > 2048) sample *= 2;
                BitmapFactory.Options options = new BitmapFactory.Options();
                options.inSampleSize = sample;
                bitmap = BitmapFactory.decodeFile(file.getAbsolutePath(), options);
            } catch (Exception ignored) { }
            Bitmap decoded = bitmap;
            handler.post(() -> {
                if (request != mediaOpenNonce || !stillCurrent(scopedAccount, room)
                        || decoded == null) {
                    file.delete();
                    if (decoded != null) decoded.recycle();
                    if (request == mediaOpenNonce && mediaPreviewDialog != null) {
                        AlertDialog loading = mediaPreviewDialog;
                        mediaPreviewDialog = null;
                        loading.dismiss();
                    }
                    if (stillCurrent(scopedAccount, room)) chatNotice.setText(R.string.bchat_media_unavailable);
                    return;
                }
                displayFullImage(decoded, file, media, room, scopedAccount);
            });
        }, "bchat-media-decode").start();
    }

    private void displayFullImage(Bitmap bitmap, File file, MediaRecord media,
                                  Room room, AccountScope scopedAccount) {
        FrameLayout surface = new FrameLayout(this);
        surface.setBackgroundColor(Color.rgb(12, 18, 25));
        ZoomableImageView display = new ZoomableImageView(this);
        display.setImageBitmap(bitmap);
        display.setContentDescription(media.name);
        surface.addView(display, new FrameLayout.LayoutParams(-1, -1));
        LinearLayout toolbar = Ui.row(this);
        toolbar.setBackgroundColor(Color.argb(220, 12, 18, 25));
        Ui.pad(toolbar, 12, 8);
        TextView close = Ui.text(this, "×", 28, Color.WHITE, false);
        close.setGravity(Gravity.CENTER);
        close.setContentDescription(getString(R.string.bchat_media_close_viewer));
        toolbar.addView(close, new LinearLayout.LayoutParams(dp(48), dp(48)));
        TextView filename = Ui.text(this, media.name, 14, Color.WHITE, false);
        filename.setSingleLine(true);
        filename.setEllipsize(android.text.TextUtils.TruncateAt.END);
        toolbar.addView(filename, new LinearLayout.LayoutParams(0, dp(48), 1));
        TextView rotate = Ui.text(this, "↻", 25, Color.WHITE, false);
        rotate.setGravity(Gravity.CENTER);
        rotate.setContentDescription(getString(R.string.bchat_media_rotate));
        toolbar.addView(rotate, new LinearLayout.LayoutParams(dp(48), dp(48)));
        TextView save = Ui.text(this, getString(R.string.bchat_media_save), 14, Color.WHITE, true);
        save.setGravity(Gravity.CENTER);
        save.setContentDescription(getString(R.string.bchat_media_save));
        toolbar.addView(save, new LinearLayout.LayoutParams(dp(56), dp(48)));
        FrameLayout.LayoutParams toolbarSize = new FrameLayout.LayoutParams(-1, dp(64), Gravity.TOP);
        surface.addView(toolbar, toolbarSize);
        AlertDialog dialog = new AlertDialog.Builder(this).setView(surface).create();
        close.setOnClickListener(v -> dialog.dismiss());
        rotate.setOnClickListener(v -> display.rotateBy90());
        save.setOnClickListener(v -> {
            if (stillCurrent(scopedAccount, room)) prepareDocumentSave(file, room, media);
            dialog.dismiss();
        });
        if (mediaPreviewDialog != null) {
            AlertDialog previous = mediaPreviewDialog;
            mediaPreviewDialog = null;
            previous.dismiss();
        }
        mediaPreviewDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (mediaPreviewDialog == dialog) mediaPreviewDialog = null;
            display.setImageDrawable(null);
            bitmap.recycle();
            if (pendingPdfDownload != file) file.delete();
        });
        dialog.show();
        if (dialog.getWindow() != null) {
            dialog.getWindow().setBackgroundDrawableResource(android.R.color.transparent);
            dialog.getWindow().setLayout(-1, -1);
        }
    }

    private void prepareDocumentSave(File file, Room room, MediaRecord media) {
        clearPendingPdf();
        pendingPdfDownload = file;
        pendingPdfAccount = account;
        pendingPdfRoom = room;
        Intent destination = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        destination.addCategory(Intent.CATEGORY_OPENABLE);
        destination.setType(media.mime);
        destination.putExtra(Intent.EXTRA_TITLE, media.name);
        startActivityForResult(destination, MEDIA_SAVE_REQUEST);
    }

    private interface MediaReadCallback { void complete(File file, int status); }

    private File mediaReadCacheFile(int request) throws IOException {
        File root = new File(getCacheDir(), "bchat-v2-media-read");
        if (!root.isDirectory() && !root.mkdirs()) throw new IOException("Media cache unavailable");
        return new File(root, "read-" + request + ".bin");
    }

    private void clearMediaReadCache() {
        File folder = new File(getCacheDir(), "bchat-v2-media-read");
        File[] files = folder.listFiles();
        if (files == null) return;
        for (File file : files) if (file.isFile() && file.getName().matches("read-[0-9]+\\.bin")) file.delete();
    }

    private void clearPendingPdf() {
        if (pendingPdfDownload != null) { pendingPdfDownload.delete(); pendingPdfDownload = null; }
        pendingPdfAccount = null;
        pendingPdfRoom = null;
    }

    private void closeMediaRead() {
        ++mediaReadNonce;
        mediaReadBusy = false;
        mediaReadStarted = false;
        mediaReadChunkPending = false;
        if (mediaReadTimeout != null) { handler.removeCallbacks(mediaReadTimeout); mediaReadTimeout = null; }
        if (mediaReadPort != null) { mediaReadPort.close(); mediaReadPort = null; }
        if (mediaReadOutput != null) {
            try { mediaReadOutput.close(); } catch (IOException ignored) { }
            mediaReadOutput = null;
        }
        if (mediaReadFile != null) { mediaReadFile.delete(); mediaReadFile = null; }
        if (web != null && web.getUrl() != null && isBridgeUrl(Uri.parse(web.getUrl())))
            web.evaluateJavascript("if(window.__bchatMediaReadAbort){window.__bchatMediaReadAbort.abort();window.__bchatMediaReadAbort=null}", null);
    }

    private void mediaReadDeadline(int request, AccountScope scopedAccount, Room room,
                                   MediaReadCallback callback) {
        if (mediaReadTimeout != null) handler.removeCallbacks(mediaReadTimeout);
        mediaReadTimeout = () -> {
            if (request != mediaReadNonce || !mediaReadBusy) return;
            closeMediaRead();
            if (stillCurrent(scopedAccount, room)) callback.complete(null, 0);
        };
        handler.postDelayed(mediaReadTimeout, 60000);
    }

    private void requestNextMediaReadChunk(int request, AccountScope scopedAccount, Room room,
                                           MediaReadCallback callback) throws Exception {
        JSONObject next = new JSONObject();
        next.put("nonce", request);
        next.put("type", "next");
        next.put("seq", mediaReadSequence);
        mediaReadPort.postMessage(new WebMessage(next.toString()));
        mediaReadDeadline(request, scopedAccount, room, callback);
    }

    private void readConnectedMedia(Room room, MediaRecord media, boolean thumbnail,
                                    MediaReadCallback callback) {
        AccountScope scopedAccount = account;
        if (!stillCurrent(scopedAccount, room) || !mediaAllowed() || mediaReadBusy || web == null
                || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl()))) {
            callback.complete(null, 0); return;
        }
        int limit = thumbnail ? 128 * 1024 : media.size;
        String expectedMime = thumbnail ? "image/jpeg" : media.mime;
        String path = "/bchat/api/v2/media/" + media.id + (thumbnail ? "/thumbnail" : "/content");
        final int request = ++mediaReadNonce;
        final int currentWeb = webEpoch, currentPage = pageEpoch, currentEpoch = epoch;
        try {
            mediaReadFile = mediaReadCacheFile(request);
            mediaReadOutput = new FileOutputStream(mediaReadFile);
            mediaReadBytes = 0;
            mediaReadSequence = 0;
            mediaReadStarted = false;
            mediaReadBusy = true;
            WebMessagePort[] channel = web.createWebMessageChannel();
            mediaReadPort = channel[0];
            mediaReadPort.setWebMessageCallback(new WebMessagePort.WebMessageCallback() {
                @Override public void onMessage(WebMessagePort port, WebMessage message) {
                    if (closed || request != mediaReadNonce || !mediaReadBusy || port != mediaReadPort
                            || currentWeb != webEpoch || currentPage != pageEpoch || currentEpoch != epoch
                            || !stillCurrent(scopedAccount, room) || web == null || web.getUrl() == null
                            || !isBridgeUrl(Uri.parse(web.getUrl()))) return;
                    try {
                        String raw = message.getData();
                        if (raw == null || raw.length() > 90000) throw new IOException("Oversized media frame");
                        JSONObject value = new JSONObject(raw);
                        if (value.getInt("nonce") != request) throw new IOException("Stale media frame");
                        String type = value.getString("type");
                        if ("start".equals(type)) {
                            if (mediaReadStarted) throw new IOException("Duplicate media response");
                            mediaReadStarted = true;
                            int status = value.getInt("status");
                            if (status == 401) {
                                closeMediaRead();
                                handleV2TransportFailure(status);
                                callback.complete(null, status);
                                return;
                            }
                            if (status != 200) {
                                closeMediaRead(); callback.complete(null, status); return;
                            }
                            String mime = value.getString("mime").split(";", 2)[0].trim();
                            long advertised = value.getLong("length");
                            if (!(ORIGIN + path).equals(value.getString("url"))
                                    || !expectedMime.equals(mime) || advertised < 0 || advertised > limit)
                                throw new IOException("Unverified media response");
                            requestNextMediaReadChunk(request, scopedAccount, room, callback);
                        } else if ("chunk".equals(type)) {
                            if (!mediaReadStarted || mediaReadChunkPending
                                    || value.getInt("seq") != mediaReadSequence)
                                throw new IOException("Out-of-order media chunk");
                            String encoded = value.getString("data");
                            if (encoded.length() > 88000) throw new IOException("Oversized media chunk");
                            mediaReadChunkPending = true;
                            FileOutputStream output = mediaReadOutput;
                            int received = mediaReadBytes;
                            mediaIo.execute(() -> {
                                int count = 0;
                                boolean valid = false;
                                try {
                                    byte[] bytes = Base64.decode(encoded, Base64.NO_WRAP);
                                    count = bytes.length;
                                    if (count < 1 || count > MEDIA_READ_CHUNK_BYTES || received + count > limit)
                                        throw new IOException("Media read bound exceeded");
                                    output.write(bytes);
                                    valid = true;
                                } catch (Exception ignored) { }
                                int copied = count;
                                boolean completed = valid;
                                handler.post(() -> {
                                    if (request != mediaReadNonce || !mediaReadBusy) return;
                                    mediaReadChunkPending = false;
                                    if (!completed) {
                                        closeMediaRead();
                                        if (stillCurrent(scopedAccount, room)) callback.complete(null, 0);
                                        return;
                                    }
                                    mediaReadBytes += copied;
                                    ++mediaReadSequence;
                                    try { requestNextMediaReadChunk(request, scopedAccount, room, callback); }
                                    catch (Exception invalid) {
                                        closeMediaRead();
                                        if (stillCurrent(scopedAccount, room)) callback.complete(null, 0);
                                    }
                                });
                            });
                        } else if ("end".equals(type)) {
                            if (!mediaReadStarted || mediaReadChunkPending
                                    || value.getInt("size") != mediaReadBytes
                                    || mediaReadBytes < 1 || (!thumbnail && mediaReadBytes != media.size))
                                throw new IOException("Incomplete media response");
                            mediaReadChunkPending = true;
                            FileOutputStream output = mediaReadOutput;
                            File saved = mediaReadFile;
                            mediaIo.execute(() -> {
                                boolean synced = false;
                                try { output.getFD().sync(); output.close(); synced = true; }
                                catch (IOException ignored) { }
                                boolean complete = synced;
                                handler.post(() -> {
                                    if (request != mediaReadNonce || !mediaReadBusy) {
                                        saved.delete(); return;
                                    }
                                    mediaReadOutput = null;
                                    mediaReadFile = null;
                                    closeMediaRead();
                                    if (!complete) {
                                        saved.delete();
                                        if (stillCurrent(scopedAccount, room)) callback.complete(null, 0);
                                    } else if (thumbnail) callback.complete(saved, 200);
                                    else verifyDownloadedMedia(saved, media, scopedAccount, room, callback);
                                });
                            });
                        } else throw new IOException("Invalid media frame");
                    } catch (Exception invalid) {
                        closeMediaRead();
                        if (stillCurrent(scopedAccount, room)) callback.complete(null, 0);
                    }
                }
            });
            String script = BChatConnectedMediaBridge.readScript(ORIGIN, BRIDGE, path, request, limit);
            web.evaluateJavascript(script, ignored -> {
                if (request != mediaReadNonce || !mediaReadBusy || currentWeb != webEpoch
                        || currentPage != pageEpoch || currentEpoch != epoch || !stillCurrent(scopedAccount, room)
                        || web == null || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl()))) return;
                web.postWebMessage(new WebMessage("bchat-media-read",
                        new WebMessagePort[]{channel[1]}), Uri.parse(ORIGIN));
                mediaReadDeadline(request, scopedAccount, room, callback);
            });
        } catch (Exception invalid) {
            closeMediaRead();
            if (stillCurrent(scopedAccount, room)) callback.complete(null, 0);
        }
    }

    private void verifyDownloadedMedia(File file, MediaRecord media, AccountScope scopedAccount,
                                       Room room, MediaReadCallback callback) {
        new Thread(() -> {
            boolean matched = false;
            try (FileInputStream input = new FileInputStream(file)) {
                MessageDigest sha = MessageDigest.getInstance("SHA-256");
                byte[] bytes = new byte[32 * 1024];
                int count;
                while ((count = input.read(bytes)) != -1) sha.update(bytes, 0, count);
                StringBuilder hex = new StringBuilder(64);
                for (byte b : sha.digest()) hex.append(String.format(Locale.ROOT, "%02x", b & 255));
                matched = media.sha256.equals(hex.toString());
            } catch (Exception ignored) { }
            boolean verifiedDigest = matched;
            handler.post(() -> {
                if (!verifiedDigest || !stillCurrent(scopedAccount, room)) {
                    file.delete();
                    if (stillCurrent(scopedAccount, room)) callback.complete(null, 0);
                } else callback.complete(file, 200);
            });
        }, "bchat-media-digest").start();
    }

    private void loadMessages(long beforeId) {
        Room room = selectedRoom;
        if ((!chatAllowed() && !offlineHistory) || room == null || v2Busy) return;
        if (offlineHistory) { showCachedMessages(room, beforeId, false); return; }
        if (beforeId > 0) {
            if (olderPageLoading) return;
            olderPageLoading = true;
        }
        String path = V2_ROOMS + "/" + room.id + "/messages"
                + (beforeId > 0 ? "?before_id=" + beforeId : "");
        chatNotice.setText(R.string.chat_v2_loading);
        olderButton.setEnabled(false);
        fetchV2("GET", path, null, (statusCode, result) -> {
            if (selectedRoom != room) return;
            if (beforeId > 0) olderPageLoading = false;
            if (handleV2TransportFailure(statusCode)) return;
            try {
                if (statusCode != 200 || result == null || positiveId(result.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                JSONArray list = result.getJSONArray("messages");
                List<JSONObject> validated = validateMessageList(list, beforeId);
                // A media POST can reach Odoo while its one-shot bridge ACK is lost.  Never
                // retransmit it automatically: the authenticated history is the source of
                // truth.  A matching media ID is globally unique to one message, and this
                // helper also requires the current account to be that message's author.
                // Therefore it is safe to retire only that local staged copy.
                reconcilePendingMediaFromVerifiedHistory(account, room, validated);
                Object older = result.opt("next_before_id");
                long cursor = older == JSONObject.NULL || older == null ? 0 : positiveId(older);
                if (cursor > 0 && (list.length() == 0 || cursor != positiveId(list.getJSONObject(0).get("id"))))
                    throw new IllegalArgumentException();
                long notificationTarget = pendingNotificationMessageId;
                boolean focusedNotification = notificationTarget > 0;
                if (focusedNotification) {
                    boolean found = false;
                    for (JSONObject item : validated)
                        if (positiveId(item.get("id")) == pendingNotificationMessageId) found = true;
                    pendingNotificationMessageId = 0;
                    if (!found) throw new IllegalArgumentException("Notification message not in page");
                }
                if (historyCache != null && account != null) {
                    AccountScope scopedAccount = account;
                    ConnectedHistoryCache cache = historyCache;
                    queueHistoryWrite(scopedAccount, cache, () -> {
                        try { cache.savePage(scopedAccount, room.id, room.membershipId, validated); }
                        catch (Exception storage) { throw new IllegalStateException(storage); }
                    });
                }
                ScrollAnchor anchor = currentScrollAnchor();
                boolean ownSend = scrollAfterOwnSend;
                boolean olderWindowTransition = beforeId > 0
                        && displayedMessages.size() >= MAX_CONNECTED_MESSAGE_WINDOW;
                List<JSONObject> window = messageWindow(validated, beforeId, anchor.atBottom, ownSend);
                scrollAfterOwnSend = false;
                boolean followBottom = beforeId == 0 && (displayedMessages.isEmpty()
                        || (!historicalWindow && anchor.atBottom) || ownSend) && !focusedNotification;
                long focusId = focusedNotification ? notificationTarget : 0;
                boolean omittedOldest = beforeId > 0 && !window.isEmpty()
                        && !validated.isEmpty() && positiveId(window.get(0).get("id"))
                        > positiveId(validated.get(0).get("id"));
                nextBeforeId = (cursor > 0 || omittedOldest) && !window.isEmpty()
                        ? positiveId(window.get(0).get("id")) : 0;
                if (beforeId > 0) historicalWindow = historicalWindow || olderWindowTransition;
                else if (ownSend || (anchor.atBottom && !historicalWindow) || displayedMessages.isEmpty())
                    historicalWindow = false;
                olderPageFailed = false;
                renderMessageWindow(room, window, followBottom, focusId, anchor);
                updateOlderControl();
                updateOlderButtonAvailability();
                newerControl.setVisibility(historicalWindow ? View.VISIBLE : View.GONE);
                if (beforeId == 0 && (historicalWindow || !anchor.atBottom) && !displayedMessages.isEmpty()
                        && !window.isEmpty() && validated.size() > 0
                        && positiveId(validated.get(validated.size() - 1).get("id"))
                        > positiveId(window.get(window.size() - 1).get("id"))) {
                    chatNotice.setText(R.string.chat_v2_new_messages);
                    chatNotice.setOnClickListener(v -> jumpToLatest());
                } else {
                    chatNotice.setText("");
                    chatNotice.setOnClickListener(null);
                }
                updatePendingUi();
                // Read and reconcile authenticated history before any idempotent replay.
                // Posting first would occupy the single V2 transport and skip this initial
                // room page, even when the server already contains the media message.
                if (mediaReplayAfterInitialHistory) {
                    mediaReplayAfterInitialHistory = false;
                    AccountScope scopedAccount = account;
                    handler.post(() -> replayKnownConnectedMedia(scopedAccount, room));
                }
                if (pendingOrderShareRoom == room) {
                    pendingOrderShareRoom = null;
                    retryPending();
                }
                if (receiptsAvailable && !offlineHistory) {
                    for (JSONObject item : validated)
                        if (account != null && positiveId(item.opt("author_user_id")) != account.userId)
                            acknowledgeMessage(room, positiveId(item.opt("id")), "delivered");
                    messageScroll.post(this::scanVisibleMessageReceipts);
                }
            } catch (Exception invalid) {
                if (beforeId > 0) { olderPageFailed = true; updateOlderControl(); }
                if (statusCode == 403 && historyCache != null && account != null)
                    try { purgeCachedRoom(account, room.id); }
                    catch (RuntimeException storage) { purgeHistory(); }
                chatNotice.setText(statusCode == 403 ? R.string.chat_v2_denied : R.string.chat_v2_load_failed);
                if (statusCode == 403) { showRooms(); loadRooms(); }
            }
        });
    }

    /**
     * Retire a locally staged upload only after verified room history proves that this account
     * owns the sent message containing the exact server media ID.  This heals a lost write ACK
     * without issuing another POST (which could duplicate a message after an uncertain send).
     */
    private void reconcilePendingMediaFromVerifiedHistory(AccountScope scopedAccount, Room room,
                                                           List<JSONObject> messages) {
        if (!stillCurrent(scopedAccount, room) || mediaStore == null) return;
        try {
            List<BChatConnectedMediaStore.Entry> pending = mediaStore.pendingForRoom(scopedAccount,
                    room.id, room.membershipId);
            if (pending.isEmpty()) return;
            Set<Long> confirmedMediaIds = new HashSet<>();
            for (JSONObject message : messages) {
                if (positiveId(message.opt("author_user_id")) != scopedAccount.userId
                        || !message.has("media")) continue;
                MediaRecord serverMedia = new MediaRecord(message.getJSONObject("media"));
                confirmedMediaIds.add(serverMedia.id);
            }
            for (BChatConnectedMediaStore.Entry entry : pending)
                if (entry.mediaId > 0 && confirmedMediaIds.contains(entry.mediaId))
                    mediaStore.acknowledge(scopedAccount, entry);
        } catch (Exception ignored) {
            // Retaining the staged item is safer than hiding an uncertain send.  The next
            // verified history read will retry this idempotent reconciliation.
        }
    }

    private List<JSONObject> validateMessageList(JSONArray list, long beforeId) throws Exception {
        if (list.length() > 30) throw new IllegalArgumentException();
        List<JSONObject> validated = new ArrayList<>();
        long lastId = 0;
        for (int i = 0; i < list.length(); i++) {
            JSONObject item = list.getJSONObject(i);
            long id = positiveId(item.get("id"));
            positiveId(item.get("author_user_id"));
            String authorName = item.getString("author_name");
            String body = item.getString("text");
            String date = item.getString("created_at");
            if (item.has("media")) new MediaRecord(item.getJSONObject("media"));
            if (!item.has("media") || !body.isEmpty()) OutboxPolicy.requireText(body);
            if (id <= lastId || (beforeId > 0 && id >= beforeId) || date.length() > 64
                    || date.trim().isEmpty() || date.indexOf('\n') >= 0 || date.indexOf('\r') >= 0
                    || authorName.trim().isEmpty() || authorName.length() > 160
                    || authorName.indexOf('\n') >= 0 || authorName.indexOf('\r') >= 0)
                throw new IllegalArgumentException();
            if (item.has("reply")) {
                JSONObject reply = item.optJSONObject("reply");
                if (reply == null) throw new IllegalArgumentException();
                java.util.Set<String> replyFields = new java.util.HashSet<>();
                java.util.Iterator<String> replyKeys = reply.keys();
                while (replyKeys.hasNext()) replyFields.add(replyKeys.next());
                if (reply.has("unavailable")) {
                    ReplyWireContract.requireUnavailable(replyFields, reply.optBoolean("unavailable", false));
                } else {
                    long parentId = positiveId(reply.get("id"));
                    String parentAuthor = reply.getString("author_name");
                    String parentText = reply.getString("text");
                    String mediaKind = reply.has("media_kind") && !reply.isNull("media_kind")
                            ? reply.getString("media_kind") : null;
                    ReplyWireContract.requireAvailable(replyFields, id, parentId,
                            parentAuthor, parentText, mediaKind);
                }
            }
            lastId = id;
            validated.add(item);
        }
        return validated;
    }

    /** Fetch just the acknowledged row after send; avoid reloading/rebinding the entire timeline. */
    private void appendAcknowledgedMessage(AccountScope scopedAccount, Room room, long messageId) {
        if (!stillCurrent(scopedAccount, room)) return;
        fetchV2("GET", V2_ROOMS + "/" + room.id + "/messages/" + messageId, null,
                (statusCode, result) -> {
                    if (!stillCurrent(scopedAccount, room)) return;
                    if (handleV2TransportFailure(statusCode)) return;
                    try {
                        if (statusCode != 200 || result == null
                                || positiveId(result.get("api_version")) != 2)
                            throw new IllegalArgumentException();
                        JSONArray one = new JSONArray().put(result.getJSONObject("message"));
                        JSONObject message = validateMessageList(one, 0).get(0);
                        // A reply may be sent while viewing an older, bounded page.  Do not
                        // splice a newest row into that historical window: reload the latest
                        // page instead so there is no invisible gap in the timeline.
                        if (historicalWindow) {
                            // An own acknowledged send is intentional navigation back to the
                            // newest page, not an ordinary background refresh of old history.
                            scrollAfterOwnSend = true;
                            loadMessages(0);
                            return;
                        }
                        long id = positiveId(message.get("id"));
                        List<JSONObject> window = new ArrayList<>(displayedMessages);
                        boolean present = false;
                        for (int i = 0; i < window.size(); i++) {
                            long existing = positiveId(window.get(i).get("id"));
                            if (existing == id) { window.set(i, message); present = true; break; }
                            if (existing > id) throw new IllegalArgumentException();
                        }
                        if (!present) window.add(message);
                        boolean trimmedOldest = window.size() > MAX_CONNECTED_MESSAGE_WINDOW;
                        if (trimmedOldest)
                            window = new ArrayList<>(window.subList(window.size() - MAX_CONNECTED_MESSAGE_WINDOW,
                                    window.size()));
                        // The locally trimmed first row is a real pagination boundary.  Keep
                        // it as the cursor so the older row is never stranded after 500 rows.
                        if (trimmedOldest && !window.isEmpty())
                            nextBeforeId = positiveId(window.get(0).get("id"));
                        if (historyCache != null) {
                            // savePage accepts one bounded page only.  The thread may show a
                            // larger window after paging, while this just-acknowledged row is
                            // already fully verified and can be merged by the cache itself.
                            final List<JSONObject> saved = Collections.singletonList(message);
                            final ConnectedHistoryCache cache = historyCache;
                            queueHistoryWrite(scopedAccount, cache, () -> {
                                try { cache.savePage(scopedAccount, room.id, room.membershipId, saved); }
                                catch (Exception storage) { throw new IllegalStateException(storage); }
                            });
                        }
                        renderMessageWindow(room, window, true, 0, currentScrollAnchor());
                        updateOlderControl();
                        updateOlderButtonAvailability();
                        chatNotice.setText("");
                        chatNotice.setOnClickListener(null);
                    } catch (Exception invalid) {
                        // A normal paged refresh remains the safe fallback for an unexpected wire shape.
                        loadMessages(0);
                    }
                });
    }

    private static final class ScrollAnchor {
        final long messageId;
        final int offset;
        final boolean atBottom;
        ScrollAnchor(long messageId, int offset, boolean atBottom) {
            this.messageId = messageId;
            this.offset = offset;
            this.atBottom = atBottom;
        }
    }

    private ScrollAnchor currentScrollAnchor() {
        if (messageScroll == null || messageLayout == null || displayedMessages.isEmpty())
            return new ScrollAnchor(0, 0, true);
        boolean bottom = !messageScroll.canScrollVertically(1);
        int first = messageLayout.findFirstVisibleItemPosition();
        if (first < 0 || first >= displayedMessages.size()) return new ScrollAnchor(0, 0, bottom);
        View child = messageLayout.findViewByPosition(first);
        return new ScrollAnchor(displayedMessages.get(first).optLong("id"),
                child == null ? 0 : child.getTop() - messageScroll.getPaddingTop(), bottom);
    }

    /** Manual transitions are available at the top of a bounded or offline window. */
    private boolean olderCanLoad() {
        if (nextBeforeId <= 0 || olderPageLoading || messageLayout == null) return false;
        int first = messageLayout.findFirstVisibleItemPosition();
        return first >= 0 && first <= 1;
    }

    private void updateOlderButtonAvailability() {
        if (olderButton != null) olderButton.setEnabled(olderCanLoad());
    }

    private void updateOlderControl() {
        if (olderControl == null) return;
        boolean manual = offlineHistory || olderPageFailed
                || displayedMessages.size() >= MAX_CONNECTED_MESSAGE_WINDOW || historicalWindow;
        olderControl.setVisibility(nextBeforeId > 0 && manual ? View.VISIBLE : View.GONE);
        updateOlderButtonAvailability();
    }

    private void maybeLoadOlderMessages() {
        if (offlineHistory || olderPageLoading || olderPageFailed || v2Busy || nextBeforeId <= 0
                || displayedMessages.isEmpty() || displayedMessages.size() >= MAX_CONNECTED_MESSAGE_WINDOW
                || messageLayout.findFirstVisibleItemPosition() > 2) return;
        loadMessages(nextBeforeId);
    }

    private List<JSONObject> messageWindow(List<JSONObject> fetched, long beforeId,
                                             boolean wasAtBottom, boolean forceLatest) throws Exception {
        if (beforeId > 0 && !fetched.isEmpty()) {
            if (!offlineHistory && displayedMessages.size() < MAX_CONNECTED_MESSAGE_WINDOW) {
                Map<Long, JSONObject> byId = new LinkedHashMap<>();
                for (JSONObject item : fetched) byId.put(positiveId(item.get("id")), item);
                for (JSONObject item : displayedMessages) byId.put(positiveId(item.get("id")), item);
                List<JSONObject> connected = new ArrayList<>(byId.values());
                return connected.subList(Math.max(0, connected.size() - MAX_CONNECTED_MESSAGE_WINDOW),
                        connected.size());
            }
            List<JSONObject> window = new ArrayList<>();
            int reserve = displayedMessages.isEmpty() ? 0 : 1;
            window.addAll(fetched.subList(Math.max(0, fetched.size() - ConnectedHistoryCache.PAGE_SIZE + reserve),
                    fetched.size()));
            if (reserve > 0) window.add(displayedMessages.get(0));
            return window;
        }
        if (beforeId > 0) return new ArrayList<>(displayedMessages);
        if (!displayedMessages.isEmpty() && (historicalWindow || !wasAtBottom) && !forceLatest) {
            Map<Long, JSONObject> fresh = new LinkedHashMap<>();
            for (JSONObject item : fetched) fresh.put(positiveId(item.get("id")), item);
            List<JSONObject> preserved = new ArrayList<>();
            for (JSONObject item : displayedMessages) {
                long id = positiveId(item.get("id"));
                preserved.add(fresh.containsKey(id) ? fresh.get(id) : item);
            }
            return preserved;
        }
        return new ArrayList<>(fetched);
    }

    private void showCachedMessages(Room room, long beforeId, boolean firstOpen) {
        if (room != selectedRoom || historyCache == null || account == null) return;
        try {
            List<JSONObject> cached = historyCache.page(account, room.id, room.membershipId, beforeId);
            if (cached.isEmpty() && !firstOpen) {
                nextBeforeId = 0;
                updateOlderControl();
                return;
            }
            // The cache is written only after an authenticated, validated room read. It can
            // safely confirm the exact media ID before the next live fetch completes.
            reconcilePendingMediaFromVerifiedHistory(account, room, cached);
            ScrollAnchor anchor = currentScrollAnchor();
            List<JSONObject> window = messageWindow(cached, beforeId, anchor.atBottom, false);
            long first = window.isEmpty() ? 0 : positiveId(window.get(0).get("id"));
            nextBeforeId = first > 0 && historyCache.hasOlder(account, room.id, room.membershipId, first)
                    ? first : 0;
            if (beforeId > 0) historicalWindow = true;
            renderMessageWindow(room, window, firstOpen, 0, anchor);
            updatePendingUi();
            updateOlderControl();
            newerControl.setVisibility(historicalWindow ? View.VISIBLE : View.GONE);
            if (offlineHistory) chatNotice.setText(offlineNotice());
        } catch (Exception damaged) {
            if (offlineHistory) chatNotice.setText(R.string.chat_v2_load_failed);
        }
    }

    private void showNewerMessages() {
        Room room = selectedRoom;
        if (room == null || displayedMessages.isEmpty()) return;
        if (historyCache == null || account == null) { jumpToLatest(); return; }
        try {
            long last = positiveId(displayedMessages.get(displayedMessages.size() - 1).get("id"));
            List<JSONObject> newer = historyCache.pageAfter(account, room.id, room.membershipId, last);
            if (newer.isEmpty()) { jumpToLatest(); return; }
            List<JSONObject> window = new ArrayList<>();
            window.add(displayedMessages.get(displayedMessages.size() - 1));
            window.addAll(newer);
            long first = positiveId(window.get(0).get("id"));
            long newest = positiveId(window.get(window.size() - 1).get("id"));
            historicalWindow = historyCache.hasNewer(account, room.id, room.membershipId, newest);
            nextBeforeId = historyCache.hasOlder(account, room.id, room.membershipId, first) ? first : 0;
            renderMessageWindow(room, window, false, 0,
                    new ScrollAnchor(first, dp(12), false));
            updateOlderControl();
            newerControl.setVisibility(historicalWindow ? View.VISIBLE : View.GONE);
            chatNotice.setOnClickListener(null);
            chatNotice.setText(offlineHistory ? offlineNotice() : "");
        } catch (Exception damaged) {
            chatNotice.setText(R.string.chat_v2_load_failed);
        }
    }

    private void jumpToLatest() {
        Room room = selectedRoom;
        if (room == null || v2Busy) return;
        if (offlineHistory) {
            if (historyCache == null || account == null) return;
            try {
                List<JSONObject> latest = historyCache.page(account, room.id, room.membershipId, 0);
                if (latest.isEmpty()) return;
                historicalWindow = false;
                long first = positiveId(latest.get(0).get("id"));
                nextBeforeId = historyCache.hasOlder(account, room.id, room.membershipId, first) ? first : 0;
                renderMessageWindow(room, latest, true, 0, currentScrollAnchor());
                updateOlderControl();
                newerControl.setVisibility(View.GONE);
            } catch (Exception damaged) { chatNotice.setText(R.string.chat_v2_load_failed); }
            return;
        }
        scrollAfterOwnSend = true;
        loadMessages(0);
    }

    private void renderMessageWindow(Room room, List<JSONObject> window, boolean followBottom,
                                     long focusId, ScrollAnchor anchor) throws Exception {
        if (window.size() > MAX_CONNECTED_MESSAGE_WINDOW) throw new IllegalArgumentException("Too many bubbles");
        long priorId = 0;
        for (JSONObject item : window) {
            long id = positiveId(item.get("id"));
            if (id <= priorId) throw new IllegalArgumentException("Unsorted bubbles");
            priorId = id;
        }
        boolean keepPlaying = false;
        if (inlineAudioRoom == room && inlineAudioAccount == account && inlineAudioMediaId > 0) {
            for (JSONObject item : window) {
                JSONObject media = item.optJSONObject("media");
                if (media != null && positiveId(media.opt("id")) == inlineAudioMediaId) {
                    keepPlaying = true;
                    break;
                }
            }
        }
        if (!keepPlaying) stopInlineAudio();
        updateMessageRows(window);
        final int renderSerial = ++messageRenderSerial;
        messageScroll.post(() -> {
            if (selectedRoom != room || messageRenderSerial != renderSerial) return;
            int focus = messagePosition(focusId);
            int previous = messagePosition(anchor.messageId);
            if (focus >= 0) messageLayout.scrollToPositionWithOffset(focus, dp(32));
            else if (followBottom && !displayedMessages.isEmpty())
                messageLayout.scrollToPosition(displayedMessages.size() - 1);
            else if (previous >= 0)
                messageLayout.scrollToPositionWithOffset(previous, anchor.offset);
            updateOlderButtonAvailability();
            pumpMediaThumbnails();
            if (!offlineHistory) scanVisibleMessageReceipts();
            // A short first page cannot be scrolled (for example on a tablet), so fetch
            // until it fills the viewport or the server has no older page.
            messageScroll.postOnAnimation(() -> {
                if (selectedRoom == room && messageRenderSerial == renderSerial
                        && !messageScroll.canScrollVertically(-1)
                        && !messageScroll.canScrollVertically(1)) maybeLoadOlderMessages();
            });
        });
    }

    private int messagePosition(long id) {
        if (id <= 0) return -1;
        for (int i = 0; i < displayedMessages.size(); i++)
            if (displayedMessages.get(i).optLong("id") == id) return i;
        return -1;
    }

    /** Keep already attached bubbles intact when a poll changes no visible message. */
    private void updateMessageRows(List<JSONObject> window) {
        List<JSONObject> previous = new ArrayList<>(displayedMessages);
        int oldSize = previous.size();
        int newSize = window.size();
        int prepend = -1;
        if (oldSize > 0 && newSize >= oldSize) {
            long firstOldId = previous.get(0).optLong("id");
            for (int i = 0; i <= newSize - oldSize; i++) {
                if (window.get(i).optLong("id") == firstOldId) { prepend = i; break; }
            }
            if (prepend >= 0) {
                for (int i = 0; i < oldSize; i++) {
                    if (previous.get(i).optLong("id") != window.get(prepend + i).optLong("id")) {
                        prepend = -1;
                        break;
                    }
                }
            }
        }
        displayedMessages.clear();
        displayedMessages.addAll(window);
        if (prepend < 0) {
            messageAdapter.notifyDataSetChanged();
            return;
        }
        int append = newSize - prepend - oldSize;
        if (prepend > 0) messageAdapter.notifyItemRangeInserted(0, prepend);
        if (append > 0) messageAdapter.notifyItemRangeInserted(prepend + oldSize, append);
        for (int i = 0; i < oldSize; i++) {
            if (!previous.get(i).toString().equals(window.get(prepend + i).toString())
                    || (prepend > 0 && i == 0))
                messageAdapter.notifyItemChanged(prepend + i);
        }
    }

    private boolean isWithin(View child, View ancestor) {
        View current = child;
        while (current != null) {
            if (current == ancestor) return true;
            ViewParent parent = current.getParent();
            current = parent instanceof View ? (View) parent : null;
        }
        return false;
    }

    private void detachAudioControls(View bubble) {
        if (bubble != null && inlineAudioPlay != null && isWithin(inlineAudioPlay, bubble)) {
            // Playback belongs to the media ID, not to a recycled view. The next bind
            // for the same media attaches fresh controls at its current position.
            inlineAudioPlay = null;
            inlineAudioSeek = null;
            inlineAudioWave = null;
            inlineAudioTime = null;
        }
    }

    private final class MessageTimelineAdapter extends RecyclerView.Adapter<MessageTimelineAdapter.Holder> {
        MessageTimelineAdapter() { setHasStableIds(true); }

        final class Holder extends RecyclerView.ViewHolder {
            final FrameLayout container;
            View bubble;
            Holder(FrameLayout container) { super(container); this.container = container; }
        }

        @Override public long getItemId(int position) {
            return displayedMessages.isEmpty() ? Long.MIN_VALUE
                    : displayedMessages.get(position).optLong("id");
        }

        @Override public int getItemCount() { return Math.max(1, displayedMessages.size()); }

        @NonNull @Override public Holder onCreateViewHolder(@NonNull android.view.ViewGroup parent,
                                                            int viewType) {
            FrameLayout row = new FrameLayout(OdooIdentityActivity.this);
            row.setLayoutParams(new RecyclerView.LayoutParams(-1, -2));
            return new Holder(row);
        }

        @Override public void onBindViewHolder(@NonNull Holder holder, int position) {
            detachAudioControls(holder.bubble);
            holder.container.removeAllViews();
            holder.bubble = null;
            if (displayedMessages.isEmpty()) {
                holder.container.addView(Ui.emptyState(OdooIdentityActivity.this,
                        getString(offlineHistory ? R.string.chat_v2_empty_cache
                                : R.string.chat_v2_no_messages),
                        getString(offlineHistory ? R.string.chat_v2_empty_cache_hint
                                : R.string.chat_v2_messages_empty_hint)),
                        new FrameLayout.LayoutParams(-1, -2));
                return;
            }
            JSONObject item = displayedMessages.get(position);
            JSONObject prior = position > 0 ? displayedMessages.get(position - 1) : null;
            try {
                String stamp = item.getString("created_at");
                Date date = parseMessageStamp(stamp);
                String day = messageDayKey(date, stamp);
                Date priorDate = prior == null ? null : parseMessageStamp(prior.getString("created_at"));
                boolean showDate = prior == null || !day.equals(messageDayKey(priorDate,
                        prior.getString("created_at")));
                boolean sameSender = prior != null && !showDate
                        && positiveId(prior.get("author_user_id")) == positiveId(item.get("author_user_id"))
                        && date != null && priorDate != null
                        && date.getTime() >= priorDate.getTime()
                        && date.getTime() - priorDate.getTime() <= 5 * 60 * 1000L;
                View bubble = createMessageBubble(selectedRoom, item, sameSender, showDate);
                holder.bubble = bubble;
                holder.container.addView(bubble, new FrameLayout.LayoutParams(-1, -2));
            } catch (Exception invalid) {
                holder.container.addView(Ui.emptyState(OdooIdentityActivity.this,
                        getString(R.string.chat_v2_load_failed), ""),
                        new FrameLayout.LayoutParams(-1, -2));
            }
        }

        @Override public void onViewRecycled(@NonNull Holder holder) {
            detachAudioControls(holder.bubble);
            holder.container.removeAllViews();
            holder.bubble = null;
        }
    }

    private View createMessageBubble(Room room, JSONObject item,
                                     boolean sameSender, boolean showDate) throws Exception {
        long authorId = positiveId(item.get("author_user_id"));
        boolean mine = account != null && authorId == account.userId;
        long id = positiveId(item.get("id"));
        String authorName = item.getString("author_name");
        String body = item.getString("text");
        String replyBody = body.isEmpty() && item.has("media")
                ? mediaReplyDescription(item.optJSONObject("media")) : body;
        Ui.ReplySwipeLayout outer = new Ui.ReplySwipeLayout(this,
                getString(R.string.chat_v2_reply_action), offlineHistory ? null
                : () -> selectReply(room, id, authorName, replyBody));
        if (!offlineHistory) outer.setOnLongClickListener(v -> {
            showMessageActions(v, room, id, authorName, replyBody, body,
                    mine ? item : null);
            return true;
        });
        // Conversation side is physical, so it remains WhatsApp-like in either UI language.
        outer.setGravity(mine ? Gravity.RIGHT : Gravity.LEFT);
        if (showDate) {
            String label = formatMessageDay(item.getString("created_at"));
            if (!label.isEmpty()) {
                TextView dateChip = Ui.text(this, label, 12, Ui.MUTED, true);
                dateChip.setGravity(Gravity.CENTER);
                dateChip.setBackground(Ui.bg(Ui.CHAT_DATE, 11, this));
                Ui.pad(dateChip, 12, 5);
                LinearLayout.LayoutParams dateSize = new LinearLayout.LayoutParams(-2, -2);
                dateSize.gravity = Gravity.CENTER_HORIZONTAL;
                dateSize.topMargin = dp(12);
                dateSize.bottomMargin = dp(10);
                outer.addView(dateChip, dateSize);
            }
        }
        LinearLayout bubble = Ui.column(this);
        Ui.pad(bubble, 12, 8);
        bubble.setBackground(chatBubbleBackground(mine, sameSender));
        bubble.setElevation(dp(1));
        int screen = getResources().getDisplayMetrics().widthPixels;
        int maxWidth = Math.min(dp(520), Math.min((int) (screen * .84f), screen - dp(44)));
        int contentWidth = maxWidth - dp(24);
        if (!mine && !sameSender) {
            TextView author = Ui.text(this, authorName, 13, Ui.GREEN, true);
            author.setMaxWidth(contentWidth);
            bubble.addView(author, new LinearLayout.LayoutParams(-2, -2));
        }
        JSONObject quoted = item.optJSONObject("reply");
        if (quoted != null) {
            String quotedText = quoted.optString("text", "").trim();
            if (quotedText.isEmpty()) quotedText = mediaKindDescription(
                    quoted.optString("media_kind", ""));
            String label = quoted.has("unavailable")
                    ? getString(R.string.chat_v2_reply_unavailable)
                    : getString(R.string.chat_v2_reply_preview,
                            quoted.getString("author_name"), quotedText);
            TextView snippet = Ui.text(this, label, Ui.CHAT_PREVIEW_SP, Ui.MUTED, false);
            snippet.setMaxWidth(contentWidth);
            snippet.setMaxLines(2);
            snippet.setEllipsize(android.text.TextUtils.TruncateAt.END);
            snippet.setBackground(Ui.bg(Ui.LIGHT, 8, this));
            Ui.pad(snippet, 8, 5);
            bubble.addView(snippet, new LinearLayout.LayoutParams(-1, -2));
        }
        if (!body.isEmpty()) {
            // Keep offline text selection identical to ordinary saved messages.
            View orderCard = offlineHistory ? null : previousOrderShareCard(body, contentWidth);
            if (orderCard != null) {
                if (!offlineHistory) orderCard.setOnLongClickListener(v -> {
                    showMessageActions(v, room, id, authorName, replyBody, body,
                            mine ? item : null);
                    return true;
                });
                bubble.addView(orderCard, new LinearLayout.LayoutParams(contentWidth, -2));
            } else {
                TextView line = Ui.text(this, body, Ui.CHAT_BODY_SP, Ui.INK, false);
                line.setMaxWidth(contentWidth);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P)
                    line.setLineHeight(Math.max(line.getLineHeight(), dp(Ui.CHAT_TEXT_LINE_DP)));
                else line.setLineSpacing(dp(2), 1f);
                if (!offlineHistory) line.setOnLongClickListener(v -> {
                    showMessageActions(v, room, id, authorName, replyBody, body,
                            mine ? item : null);
                    return true;
                });
                else line.setTextIsSelectable(true);
                bubble.addView(line, new LinearLayout.LayoutParams(-2, -2));
            }
        }
        if (item.has("media")) {
            MediaRecord media = new MediaRecord(item.getJSONObject("media"));
            if (offlineHistory) {
                TextView unavailable = Ui.text(this,
                        getString(R.string.chat_v2_offline_media_unavailable), 12, Ui.MUTED, false);
                bubble.addView(unavailable, new LinearLayout.LayoutParams(-2, -2));
            } else addConnectedMediaCard(bubble, room, media, contentWidth);
        }
        if (!offlineHistory) bubble.setOnLongClickListener(v -> {
            showMessageActions(v, room, id, authorName, replyBody, body,
                    mine ? item : null);
            return true;
        });
        String sentClock = formatBubbleTime(item.getString("created_at"));
        TextView stamp = Ui.text(this, sentClock,
                Ui.CHAT_TIME_SP, Ui.MUTED, false);
        if (!mine) stamp.setContentDescription(getString(
                R.string.chat_v2_accessibility_sender_time, authorName,
                sentClock));
        stamp.setMaxWidth(contentWidth);
        stamp.setGravity(Gravity.END);
        LinearLayout.LayoutParams stampSize = new LinearLayout.LayoutParams(-2, -2);
        stampSize.gravity = Gravity.END;
        stampSize.topMargin = dp(3);
        bubble.addView(stamp, stampSize);
        if (mine && item.has("delivery_state")) {
            String delivery = item.getString("delivery_state");
            if (!("sent".equals(delivery) || "delivered".equals(delivery)
                    || "read".equals(delivery))) throw new IllegalArgumentException();
            String ticks = "sent".equals(delivery) ? "✓" : "✓✓";
            stamp.setText(sentClock + "  " + ticks);
            if ("read".equals(delivery)) stamp.setTextColor(Ui.GREEN);
            stamp.setOnClickListener(v -> showMessageDetails(item));
            stamp.post(() -> {
                Rect hit = new Rect();
                stamp.getHitRect(hit);
                if (hit.width() < dp(48)) {
                    hit.left = Math.max(0, hit.right - dp(48));
                    hit.right = Math.min(bubble.getWidth(), hit.left + dp(48));
                }
                if (hit.height() < dp(48)) {
                    hit.top = Math.max(0, hit.bottom - dp(48));
                    hit.bottom = Math.min(bubble.getHeight(), hit.top + dp(48));
                }
                bubble.setTouchDelegate(new TouchDelegate(hit, stamp));
            });
        }
        LinearLayout.LayoutParams bubbleSize = new LinearLayout.LayoutParams(-2, -2);
        bubbleSize.bottomMargin = sameSender ? dp(3) : dp(8);
        if (!mine && !sameSender) {
            LinearLayout incoming = Ui.row(this);
            // Ui.row inherits Arabic RTL.  Its match-parent wrapper must use physical
            // placement so an incoming avatar/bubble stays on the left in every locale.
            incoming.setLayoutDirection(View.LAYOUT_DIRECTION_LTR);
            incoming.setGravity(Gravity.BOTTOM);
            String avatarKey = account.key + ":room:" + room.id + ":member:" + authorId;
            String avatarPath = V2_ROOMS + "/" + room.id + "/members/" + authorId + "/avatar";
            View avatar = privateAvatarView(avatarKey, avatarPath, authorName,
                    (int) ((authorId * 47) % 360));
            LinearLayout.LayoutParams avatarSize = new LinearLayout.LayoutParams(dp(32), dp(32));
            avatarSize.rightMargin = dp(7);
            avatarSize.bottomMargin = dp(8);
            incoming.addView(avatar, avatarSize);
            incoming.addView(bubble, bubbleSize);
            outer.addView(incoming, new LinearLayout.LayoutParams(-1, -2));
        } else {
            bubbleSize.leftMargin = mine ? 0 : dp(39);
            bubbleSize.rightMargin = mine ? dp(18) : 0;
            outer.addView(bubble, bubbleSize);
        }
        return outer;
    }

    /** Presentation only: stored, copied, and replied-to text stays byte-for-byte unchanged. */
    private View previousOrderShareCard(String body, int contentWidth) {
        String[] lines = body.split("\\n", -1);
        if (lines.length < 2 || lines.length > 30) return null;
        Context arabic = AppLocale.withLanguage(this, "ar");
        Context english = AppLocale.withLanguage(this, "en");
        String heading = lines[0].trim();
        String arHeading = arabic.getString(R.string.order_share_heading, "").trim();
        String enHeading = english.getString(R.string.order_share_heading, "").trim();
        String prefix = heading.startsWith(arHeading) ? arHeading
                : heading.startsWith(enHeading) ? enHeading : null;
        if (prefix == null || heading.substring(prefix.length()).trim().isEmpty()) return null;
        String arTotal = arabic.getString(R.string.order_share_total, "", "").trim();
        String enTotal = english.getString(R.string.order_share_total, "", "").trim();
        // The total template contains placeholders separated by a space; match only its label.
        arTotal = arTotal.substring(0, arTotal.indexOf(':') + 1);
        enTotal = enTotal.substring(0, enTotal.indexOf(':') + 1);
        int totalIndex = -1;
        for (int i = 1; i < lines.length; i++) {
            String value = lines[i].trim();
            if (value.startsWith("• ") && totalIndex < 0) continue;
            if (i == lines.length - 1 && (value.startsWith(arTotal)
                    || value.startsWith(enTotal))) { totalIndex = i; continue; }
            return null;
        }
        if (totalIndex == 1) return null;

        LinearLayout card = Ui.column(this);
        LinearLayout headingRow = Ui.row(this);
        headingRow.setGravity(Gravity.CENTER_VERTICAL);
        TextView label = Ui.text(this, heading.substring(0, prefix.length() - 1),
                12, Ui.MUTED, false);
        headingRow.addView(label, new LinearLayout.LayoutParams(-2, -2));
        TextView reference = Ui.text(this, heading.substring(prefix.length()).trim(),
                14, Ui.INK, true);
        reference.setGravity((AppLocale.rtl(this) ? Gravity.RIGHT : Gravity.LEFT)
                | Gravity.CENTER_VERTICAL);
        LinearLayout.LayoutParams referenceSize = new LinearLayout.LayoutParams(0, -2, 1);
        referenceSize.setMarginStart(dp(6));
        headingRow.addView(reference, referenceSize);
        card.addView(headingRow, new LinearLayout.LayoutParams(-1, -2));
        View topRule = Ui.line(this);
        LinearLayout.LayoutParams topRuleSize = new LinearLayout.LayoutParams(-1, dp(1));
        topRuleSize.topMargin = dp(5);
        topRuleSize.bottomMargin = dp(3);
        card.addView(topRule, topRuleSize);
        for (int i = 1; i < (totalIndex < 0 ? lines.length : totalIndex); i++) {
            TextView product = Ui.text(this, lines[i].trim(), 14, Ui.INK, false);
            product.setMaxWidth(contentWidth);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P)
                product.setLineHeight(Math.max(product.getLineHeight(), dp(20)));
            LinearLayout.LayoutParams productSize = new LinearLayout.LayoutParams(-1, -2);
            productSize.topMargin = i == 1 ? 0 : dp(2);
            card.addView(product, productSize);
        }
        if (totalIndex >= 0) {
            View totalRule = Ui.line(this);
            LinearLayout.LayoutParams totalRuleSize = new LinearLayout.LayoutParams(-1, dp(1));
            totalRuleSize.topMargin = dp(5);
            totalRuleSize.bottomMargin = dp(4);
            card.addView(totalRule, totalRuleSize);
            TextView total = Ui.text(this, lines[totalIndex].trim(), 15, Ui.INK, true);
            total.setMaxWidth(contentWidth);
            card.addView(total, new LinearLayout.LayoutParams(-1, -2));
        }
        return card;
    }

    private String mediaReplyDescription(JSONObject media) {
        if (media == null) return getString(R.string.chat_v2_attachment_reply);
        String kind = media.optString("kind", "");
        if ("audio".equals(kind) || "image".equals(kind))
            return mediaKindDescription(kind);
        String name = media.optString("name", "").trim();
        return name.isEmpty() ? getString(R.string.chat_v2_attachment_reply) : name;
    }

    private String mediaKindDescription(String kind) {
        if ("audio".equals(kind)) return getString(R.string.bchat_media_voice_message);
        if ("image".equals(kind)) return getString(R.string.chat_v2_photo_reply);
        return getString(R.string.chat_v2_attachment_reply);
    }

    private void showMessageActions(View anchor, Room room, long id,
                                    String authorName, String replyBody, String body,
                                    JSONObject mine) {
        if (room != selectedRoom || offlineHistory) return;
        PopupMenu menu = new PopupMenu(this, anchor);
        menu.getMenu().add(0, 1, 0, R.string.chat_v2_reply_action);
        if (mine != null) menu.getMenu().add(0, 2, 1, R.string.chat_v2_message_details);
        if (!body.isEmpty()) menu.getMenu().add(0, 3, 2, R.string.chat_v2_copy_message);
        menu.setOnMenuItemClickListener(item -> {
            if (item.getItemId() == 2) showMessageDetails(mine);
            else if (item.getItemId() == 3) {
                ClipboardManager clipboard = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                if (clipboard != null)
                    clipboard.setPrimaryClip(ClipData.newPlainText("BChat", body));
            }
            else selectReply(room, id, authorName, replyBody);
            return true;
        });
        menu.show();
    }

    private void showMessageDetails(JSONObject item) {
        if (item == null) return;
        String state = item.optString("delivery_state", "");
        Object readAt = item.opt("read_at");
        Ui.decorateDialog(new AlertDialog.Builder(this)
                .setTitle(R.string.chat_v2_message_details)
                .setMessage(getString(R.string.chat_v2_message_sent_at,
                        formatMessageTime(item.optString("created_at")))
                        + ("read".equals(state) && readAt instanceof String
                        ? "\n" + getString(R.string.chat_v2_message_read_at,
                                formatMessageTime((String) readAt)) : ""))
                .setPositiveButton(R.string.bchat_group_ok, null).show());
    }

    private GradientDrawable chatBubbleBackground(boolean mine, boolean sameSender) {
        GradientDrawable background = new GradientDrawable();
        background.setColor(mine ? Ui.CHAT_SENT : Ui.CHAT_RECEIVED);
        float large = dp(17);
        float small = dp(6);
        boolean smallLeft = !mine;
        float left = !sameSender && smallLeft ? small : large;
        float right = !sameSender && !smallLeft ? small : large;
        background.setCornerRadii(new float[]{left, left, right, right,
                large, large, large, large});
        return background;
    }

    private Date parseMessageStamp(String serverStamp) {
        try {
            String normalized = serverStamp.replace('T', ' ').replace("Z", "");
            if (normalized.length() < 19) return null;
            SimpleDateFormat parser = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US);
            parser.setLenient(false);
            parser.setTimeZone(TimeZone.getTimeZone("UTC"));
            return parser.parse(normalized.substring(0, 19));
        } catch (Exception invalid) {
            return null;
        }
    }

    private String messageDayKey(Date date, String serverStamp) {
        if (date == null) return serverStamp.length() >= 10
                ? serverStamp.substring(0, 10) : serverStamp;
        Calendar local = Calendar.getInstance();
        local.setTime(date);
        return local.get(Calendar.YEAR) + "-" + local.get(Calendar.DAY_OF_YEAR);
    }

    private String formatMessageDay(String serverStamp) {
        Date date = parseMessageStamp(serverStamp);
        if (date == null) return serverStamp.length() >= 10
                ? asciiDigits(serverStamp.substring(0, 10)) : asciiDigits(serverStamp);
        Calendar local = Calendar.getInstance();
        local.setTime(date);
        Calendar today = Calendar.getInstance();
        if (today.get(Calendar.YEAR) == local.get(Calendar.YEAR)
                && today.get(Calendar.DAY_OF_YEAR) == local.get(Calendar.DAY_OF_YEAR))
            return getString(R.string.chat_v2_today);
        today.add(Calendar.DAY_OF_YEAR, -1);
        if (today.get(Calendar.YEAR) == local.get(Calendar.YEAR)
                && today.get(Calendar.DAY_OF_YEAR) == local.get(Calendar.DAY_OF_YEAR))
            return getString(R.string.chat_v2_yesterday);
        return asciiDigits(android.text.format.DateFormat.getDateFormat(this).format(date));
    }

    private void acknowledgeMessage(Room room, long messageId, String kind) {
        AccountScope scope = account;
        if (!receiptsAvailable || !liveReady(scope) || room == null || selectedRoom != room
                || messageId <= 0 || !("delivered".equals(kind) || "read".equals(kind))) return;
        String key = room.id + ":" + messageId + ":" + kind;
        if (acknowledgedMessages.contains(key) || !pendingAcknowledgements.add(key)) return;
        final int requestRoomMetadataGeneration = roomMetadataGeneration;
        String path = V2_ROOMS + "/" + room.id + "/messages/" + messageId + "/receipts";
        enqueueLive("POST", path, "kind", kind, (statusCode, result) -> {
            pendingAcknowledgements.remove(key);
            if (!liveReady(scope)) return;
            if (statusCode == 401) { logout(); return; }
            try {
                if (statusCode != 200 || result == null
                        || nonnegativeCursor(result.get("api_version")) != 2
                        || positiveId(result.get("message_id")) != messageId
                        || !(result.opt("delivered_at") instanceof String)
                        || ("read".equals(kind) && !(result.opt("read_at") instanceof String)))
                    throw new IllegalArgumentException();
                long unread = nonnegativeCursor(result.get("unread_count"));
                long responseLastMessageId = nonnegativeCursor(result.get("last_message_id"));
                if (unread > Integer.MAX_VALUE) throw new IllegalArgumentException();
                acknowledgedMessages.add(key);
                if ("read".equals(kind)) {
                    acknowledgedMessages.add(room.id + ":" + messageId + ":delivered");
                    // The server committed this exact read receipt. Apply its
                    // count only to the same active membership and only if a
                    // newer room snapshot has not arrived while it was in flight.
                    boolean refreshUnreadMetadata = false;
                    for (Room candidate : rooms) {
                        if (!candidate.sameMembership(room)) continue;
                        if (requestRoomMetadataGeneration != roomMetadataGeneration
                                || candidate.lastMessageId != responseLastMessageId) {
                            // A list response may have replaced the badge with data fetched
                            // before this receipt committed. It is not safe to merge the ACK
                            // into that snapshot; fence every in-flight list and fetch a fresh one.
                            refreshUnreadMetadata = true;
                            break;
                        }
                        candidate.unreadCount = (int) unread;
                        if (selectedRoom == candidate) selectedRoom.unreadCount = (int) unread;
                        ++unreadMetadataGeneration;
                        if (selectedRoom == null && "chats".equals(visibleSection)) renderRooms();
                        break;
                    }
                    if (refreshUnreadMetadata) {
                        ++unreadMetadataGeneration;
                        // The receipt runs on the live queue while a v2 request may still be
                        // active. Defer the refresh through the existing v2-idle pump so a
                        // synthetic busy status cannot be mistaken for a transport failure.
                        liveRoomsDirty = true;
                        handler.post(this::flushLiveUi);
                    }
                }
            } catch (Exception invalid) {
                if (statusCode == 0 || statusCode >= 500) handler.postDelayed(() -> {
                    if (selectedRoom == room && liveReady(scope)) {
                        if ("read".equals(kind)) scanVisibleMessageReceipts();
                        else acknowledgeMessage(room, messageId, "delivered");
                    }
                }, 3000);
            }
        });
    }

    /** A read ACK is emitted only while the message bubble is actually on screen. */
    private void scanVisibleMessageReceipts() {
        Room room = selectedRoom;
        if (!receiptsAvailable || !liveReady(account) || room == null || messageFrame == null
                || messageFrame.getVisibility() != View.VISIBLE
                || !"chats".equals(visibleSection) || messageScroll == null
                || !messageScroll.isShown()) return;
        Rect viewport = new Rect();
        if (!messageScroll.getGlobalVisibleRect(viewport)) return;
        for (int i = 0; i < messageScroll.getChildCount(); i++) {
            View rowView = messageScroll.getChildAt(i);
            RecyclerView.ViewHolder rowHolder = messageScroll.getChildViewHolder(rowView);
            if (!(rowHolder instanceof MessageTimelineAdapter.Holder)) continue;
            int position = rowHolder.getBindingAdapterPosition();
            if (position < 0 || position >= displayedMessages.size()) continue;
            JSONObject item = displayedMessages.get(position);
            if (account == null || positiveId(item.opt("author_user_id")) == account.userId) continue;
            View bubble = ((MessageTimelineAdapter.Holder) rowHolder).bubble;
            if (bubble == null) continue;
            Rect visible = new Rect();
            if (!bubble.isShown() || !bubble.getGlobalVisibleRect(visible)) continue;
            if (!visible.intersect(viewport)) continue;
            int threshold = Math.min(Math.max(1, bubble.getHeight() / 2), dp(96));
            if (visible.height() >= threshold) acknowledgeMessage(room, positiveId(item.opt("id")), "read");
        }
    }

    private String formatMessageTime(String serverStamp) {
        try {
            String normalized = serverStamp.replace('T', ' ').replace("Z", "");
            if (normalized.length() < 19) return asciiDigits(serverStamp);
            SimpleDateFormat parser = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US);
            parser.setLenient(false);
            parser.setTimeZone(TimeZone.getTimeZone("UTC"));
            Date date = parser.parse(normalized.substring(0, 19));
            if (date == null) return asciiDigits(serverStamp);
            Calendar now = Calendar.getInstance();
            Calendar sent = Calendar.getInstance();
            sent.setTime(date);
            String time = android.text.format.DateFormat.getTimeFormat(this).format(date);
            if (now.get(Calendar.YEAR) == sent.get(Calendar.YEAR)
                    && now.get(Calendar.DAY_OF_YEAR) == sent.get(Calendar.DAY_OF_YEAR)) return asciiDigits(time);
            return asciiDigits(android.text.format.DateFormat.getDateFormat(this).format(date)
                    + " " + time);
        } catch (Exception invalid) {
            return asciiDigits(serverStamp);
        }
    }

    /** Bubble metadata shows a clock only; the day belongs to the date separator. */
    private String formatBubbleTime(String serverStamp) {
        Date date = parseMessageStamp(serverStamp);
        if (date == null) return "—";
        return asciiDigits(android.text.format.DateFormat.getTimeFormat(this).format(date));
    }

    private String formatRoomListTime(String serverStamp) {
        Date date = parseMessageStamp(serverStamp);
        if (date == null) return "";
        Calendar then = Calendar.getInstance();
        then.setTime(date);
        Calendar now = Calendar.getInstance();
        if (then.get(Calendar.YEAR) == now.get(Calendar.YEAR)
                && then.get(Calendar.DAY_OF_YEAR) == now.get(Calendar.DAY_OF_YEAR))
            return formatBubbleTime(serverStamp);
        return formatMessageDay(serverStamp);
    }

    private static String asciiDigits(String value) {
        StringBuilder normalized = new StringBuilder(value.length());
        for (int i = 0; i < value.length(); i++) {
            char symbol = value.charAt(i);
            int digit = Character.digit(symbol, 10);
            normalized.append(digit >= 0 && Character.isDigit(symbol)
                    ? (char) ('0' + digit) : symbol);
        }
        return normalized.toString();
    }

    private void sendText() {
        Room room = selectedRoom;
        if (!sendAllowed() || room == null || v2Busy || account == null
                || outbox == null || mediaStageBusy) return;
        try {
            if (mediaStore != null && mediaStore.pending(account, room.id, room.membershipId) != null) {
                chatNotice.setText(R.string.bchat_media_pending); return;
            }
        } catch (IOException damaged) { chatNotice.setText(R.string.chat_v2_save_failed); return; }
        String body = messageInput.getText().toString();
        try {
            OutboxPolicy.requireText(body);
            flushDraftSave();
            outbox.enqueue(account, room.id, room.membershipId, body, selectedReplyMessageId);
            clearSelectedReply();
            draftActive = false;
            messageInput.setText("");
            draftActive = true;
            updatePendingUi();
            retryPending();
        } catch (IllegalArgumentException invalid) {
            chatNotice.setText(R.string.chat_v2_invalid_text);
        } catch (Exception storage) {
            chatNotice.setText(R.string.chat_v2_save_failed);
        }
    }

    private void toggleConnectedVoice() {
        if (connectedVoiceRecorder != null && connectedVoiceRecorder.isRecording()) {
            finishConnectedVoice(); return;
        }
        Room room = selectedRoom;
        if (!CONNECTED_MEDIA_UI_ENABLED || !mediaUploadAllowed() || !stillCurrent(account, room)
                || mediaStageBusy || voicePreviewFile != null || mediaUploadBusy || v2Busy) return;
        try {
            if (mediaStore.pending(account, room.id, room.membershipId) != null
                    || outbox.first(account, room.id, room.membershipId) != null) {
                chatNotice.setText(R.string.bchat_media_pending); return;
            }
        } catch (Exception invalid) { chatNotice.setText(R.string.chat_v2_save_failed); return; }
        mediaPickerAccount = account;
        mediaPickerRoom = room;
        mediaPickerGeneration = mediaSessionGeneration;
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, MEDIA_RECORD_PERMISSION_REQUEST);
            return;
        }
        startConnectedVoice(account, room);
    }

    private void startRecordingBadge() {
        if (recordingBadge == null) return;
        stopRecordingBadge();
        recordingStartedAt = SystemClock.elapsedRealtime();
        recordingBadge.setVisibility(View.VISIBLE);
        Ui.styleIconAction(mediaVoiceButton, Ui.IconTone.RECORDING);
        recordingTicker = new Runnable() {
            @Override public void run() {
                if (connectedVoiceRecorder == null || !connectedVoiceRecorder.isRecording()) return;
                long elapsed = (SystemClock.elapsedRealtime() - recordingStartedAt) / 1000;
                String timer = String.format(Locale.ROOT, "%d:%02d", elapsed / 60, elapsed % 60);
                recordingBadge.setText(getString(R.string.bchat_media_recording_timer, timer));
                recordingBadge.setContentDescription(recordingBadge.getText());
                handler.postDelayed(this, 1000);
            }
        };
        handler.post(recordingTicker);
    }

    private void stopRecordingBadge() {
        if (recordingTicker != null) { handler.removeCallbacks(recordingTicker); recordingTicker = null; }
        if (recordingBadge != null) recordingBadge.setVisibility(View.GONE);
        if (mediaVoiceButton != null) Ui.styleIconAction(mediaVoiceButton, Ui.IconTone.PLAIN);
    }

    private void startConnectedVoice(AccountScope scopedAccount, Room room) {
        if (!stillCurrent(scopedAccount, room) || !mediaUploadAllowed() || connectedVoiceRecorder != null
                || voicePreviewFile != null) return;
        final VoiceRecorder[] current = new VoiceRecorder[1];
        VoiceRecorder recorder = new VoiceRecorder(this, new VoiceRecorder.Listener() {
            @Override public void onLimitReached() {
                if (connectedVoiceRecorder == current[0]) finishConnectedVoice();
            }
            @Override public void onError(String ignored) {
                if (connectedVoiceRecorder == current[0]) {
                    connectedVoiceRecorder = null;
                    mediaStageBusy = false;
                    stopRecordingBadge();
                    mediaVoiceButton.setContentDescription(getString(R.string.bchat_media_record));
                    updatePendingUi();
                    if (stillCurrent(scopedAccount, room)) chatNotice.setText(R.string.bchat_media_record_failed);
                }
            }
        });
        current[0] = recorder;
        try {
            recorder.start();
            connectedVoiceRecorder = recorder;
            mediaStageBusy = true;
            mediaVoiceButton.setContentDescription(getString(R.string.bchat_media_stop_record));
            chatNotice.setText("");
            startRecordingBadge();
            updatePendingUi();
        } catch (Exception failure) { chatNotice.setText(R.string.bchat_media_record_failed); }
    }

    private void finishConnectedVoice() {
        VoiceRecorder recorder = connectedVoiceRecorder;
        AccountScope scopedAccount = mediaPickerAccount;
        Room room = mediaPickerRoom;
        int generation = mediaPickerGeneration;
        connectedVoiceRecorder = null;
        mediaPickerAccount = null;
        mediaPickerRoom = null;
        mediaStageBusy = false;
        stopRecordingBadge();
        mediaVoiceButton.setContentDescription(getString(R.string.bchat_media_record));
        updatePendingUi();
        if (recorder == null) return;
        try {
            ChatStore.Attachment recorded = recorder.finish();
            File source = AttachmentSupport.requirePrivateFile(this, recorded);
            if (!stillCurrent(scopedAccount, room) || generation != mediaSessionGeneration) {
                source.delete(); return;
            }
            showVoicePreview(scopedAccount, room, generation, source);
        } catch (Exception invalid) { recorder.cancel(); chatNotice.setText(R.string.bchat_media_record_failed); }
    }

    private void clearVoicePreview() {
        AlertDialog dialog = voicePreviewDialog;
        voicePreviewDialog = null;
        if (dialog != null) dialog.dismiss();
        if (voicePreviewPlayer != null) {
            voicePreviewPlayer.release();
            voicePreviewPlayer = null;
        }
        if (voicePreviewFile != null) { voicePreviewFile.delete(); voicePreviewFile = null; }
        mediaStageBusy = false;
        if (selectedRoom != null) updatePendingUi();
    }

    private void showVoicePreview(AccountScope scopedAccount, Room room, int generation, File source) {
        clearVoicePreview();
        voicePreviewFile = source;
        mediaStageBusy = true;
        updatePendingUi();
        TextView play = Ui.text(this, "▶  " + getString(R.string.bchat_media_preview_play),
                16, Ui.GREEN, true);
        Ui.styleAction(play, Ui.ActionTone.SECONDARY);
        play.setTextSize(16);
        play.setGravity(Gravity.CENTER);
        play.setMinHeight(dp(56));
        play.setContentDescription(getString(R.string.bchat_media_preview_play));
        play.setOnClickListener(v -> {
            if (voicePreviewFile != source || !stillCurrent(scopedAccount, room)
                    || generation != mediaSessionGeneration) return;
            try {
                if (voicePreviewPlayer != null) {
                    if (voicePreviewPlayer.isPlaying()) {
                        voicePreviewPlayer.pause();
                        play.setText("▶  " + getString(R.string.bchat_media_preview_play));
                    } else {
                        voicePreviewPlayer.start();
                        play.setText("Ⅱ  " + getString(R.string.bchat_media_pause));
                    }
                    return;
                }
                MediaPlayer player = new MediaPlayer();
                voicePreviewPlayer = player;
                try (FileInputStream input = new FileInputStream(source)) {
                    player.setDataSource(input.getFD(), 0, source.length());
                }
                play.setText(R.string.bchat_media_loading_audio);
                player.setOnPreparedListener(ready -> {
                    if (voicePreviewPlayer != ready || voicePreviewFile != source) return;
                    ready.start();
                    play.setText("Ⅱ  " + getString(R.string.bchat_media_pause));
                });
                player.setOnCompletionListener(done -> {
                    if (voicePreviewPlayer != done) return;
                    play.setText("▶  " + getString(R.string.bchat_media_preview_play));
                });
                player.setOnErrorListener((failed, what, extra) -> {
                    if (voicePreviewPlayer == failed) {
                        failed.release();
                        voicePreviewPlayer = null;
                        play.setText("▶  " + getString(R.string.bchat_media_preview_play));
                    }
                    return true;
                });
                player.prepareAsync();
            } catch (Exception failure) {
                if (voicePreviewPlayer != null) {
                    voicePreviewPlayer.release();
                    voicePreviewPlayer = null;
                }
                play.setText("▶  " + getString(R.string.bchat_media_preview_play));
                chatNotice.setText(R.string.bchat_media_unavailable);
            }
        });
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(R.string.bchat_media_preview_title)
                .setView(play)
                .setPositiveButton(R.string.bchat_media_preview_send, (ignored, which) -> {
                    if (voicePreviewFile != source) return;
                    voicePreviewFile = null;
                    clearVoicePreview();
                    if (!stillCurrent(scopedAccount, room) || generation != mediaSessionGeneration) {
                        source.delete(); return;
                    }
                    Uri uri = new Uri.Builder().scheme("content")
                            .authority(getPackageName() + ".files")
                            .appendPath(source.getName()).build();
                    stageConnectedMedia(scopedAccount, room, generation, uri, source, "other", 0);
                })
                .setNeutralButton(R.string.bchat_media_preview_again, (ignored, which) -> {
                    clearVoicePreview();
                    if (stillCurrent(scopedAccount, room) && generation == mediaSessionGeneration) {
                        mediaPickerAccount = scopedAccount;
                        mediaPickerRoom = room;
                        mediaPickerGeneration = generation;
                        startConnectedVoice(scopedAccount, room);
                    }
                })
                .setNegativeButton(R.string.bchat_media_preview_delete,
                        (ignored, which) -> clearVoicePreview()).create();
        voicePreviewDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (voicePreviewDialog == dialog) clearVoicePreview();
        });
        dialog.show();
        Ui.decorateDialog(dialog);
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions,
                                                      int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == PUSH_PERMISSION_REQUEST) {
            maybeRegisterPush();
            return;
        }
        if (requestCode != MEDIA_RECORD_PERMISSION_REQUEST) return;
        AccountScope scopedAccount = mediaPickerAccount;
        Room room = mediaPickerRoom;
        if (grantResults.length == 1 && grantResults[0] == PackageManager.PERMISSION_GRANTED
                && stillCurrent(scopedAccount, room)
                && mediaPickerGeneration == mediaSessionGeneration) startConnectedVoice(scopedAccount, room);
        else {
            mediaPickerAccount = null; mediaPickerRoom = null;
            if (stillCurrent(scopedAccount, room)) chatNotice.setText(R.string.bchat_media_mic_permission);
        }
    }

    private void chooseConnectedMedia() {
        Room room = selectedRoom;
        if (!CONNECTED_MEDIA_UI_ENABLED || !mediaUploadAllowed() || room == null || account == null
                || mediaStore == null || mediaUploadBusy || mediaStageBusy || v2Busy) return;
        try {
            if (mediaStore.pending(account, room.id, room.membershipId) != null
                    || outbox.first(account, room.id, room.membershipId) != null) {
                chatNotice.setText(R.string.bchat_media_pending); return;
            }
        } catch (Exception error) { chatNotice.setText(R.string.chat_v2_save_failed); return; }
        int generation = mediaSessionGeneration;
        Ui.decorateDialog(new AlertDialog.Builder(this).setTitle(R.string.bchat_media_attach)
                .setItems(new String[]{getString(R.string.bchat_media_pick_file),
                        getString(R.string.bchat_media_camera)}, (dialog, which) -> {
                    if (!stillCurrent(account, room) || generation != mediaSessionGeneration) return;
                    if (which == 0) openConnectedFilePicker(room);
                    else captureConnectedPhoto(room);
                }).show());
    }

    private void openConnectedFilePicker(Room room) {
        Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        picker.addCategory(Intent.CATEGORY_OPENABLE);
        picker.setType("*/*");
        picker.putExtra(Intent.EXTRA_MIME_TYPES,
                new String[]{"image/jpeg", "image/png", "image/webp", "application/pdf",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/plain"});
        mediaPickerAccount = account;
        mediaPickerRoom = room;
        mediaPickerGeneration = mediaSessionGeneration;
        try { startActivityForResult(picker, MEDIA_PICK_REQUEST); }
        catch (RuntimeException unavailable) {
            mediaPickerAccount = null; mediaPickerRoom = null;
            chatNotice.setText(R.string.bchat_media_invalid);
        }
    }

    private void captureConnectedPhoto(Room room) {
        try {
            File folder = new File(getFilesDir(), "attachments");
            if (!folder.isDirectory() && !folder.mkdirs()) throw new IOException("Camera directory unavailable");
            String name = "bchat-" + account.key.substring(0, 16) + "-" + room.id
                    + "-" + UUID.randomUUID() + ".jpg";
            File output = new File(folder, name);
            if (!output.createNewFile()) throw new IOException("Camera file unavailable");
            Uri uri = new Uri.Builder().scheme("content")
                    .authority(getPackageName() + ".files").appendPath(name).build();
            Intent camera = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            camera.putExtra(MediaStore.EXTRA_OUTPUT, uri);
            camera.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            if (camera.resolveActivity(getPackageManager()) == null) {
                output.delete(); chatNotice.setText(R.string.bchat_media_camera_unavailable); return;
            }
            cameraCaptureFile = output;
            mediaPickerAccount = account;
            mediaPickerRoom = room;
            mediaPickerGeneration = mediaSessionGeneration;
            startActivityForResult(camera, MEDIA_CAMERA_REQUEST);
        } catch (Exception failure) {
            if (cameraCaptureFile != null) { cameraCaptureFile.delete(); cameraCaptureFile = null; }
            mediaPickerAccount = null; mediaPickerRoom = null;
            chatNotice.setText(R.string.bchat_media_camera_unavailable);
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == GROUP_PHOTO_REQUEST) {
            AccountScope scoped = groupPhotoAccount;
            Room room = groupPhotoRoom;
            groupPhotoAccount = null; groupPhotoRoom = null;
            if (resultCode == RESULT_OK && data != null && data.getData() != null
                    && scoped != null && account == scoped && verified && room != null
                    && currentGroupRoom(room) != null)
                prepareGroupPhoto(scoped, room, data.getData());
            return;
        }
        if (requestCode == MEDIA_SAVE_REQUEST) {
            File source = pendingPdfDownload;
            AccountScope scopedAccount = pendingPdfAccount;
            Room room = pendingPdfRoom;
            pendingPdfDownload = null;
            pendingPdfAccount = null;
            pendingPdfRoom = null;
            if (source == null) return;
            if (resultCode != RESULT_OK || data == null || data.getData() == null
                    || !stillCurrent(scopedAccount, room)) { source.delete(); return; }
            Uri destination = data.getData();
            new Thread(() -> {
                boolean saved = false;
                try (FileInputStream input = new FileInputStream(source);
                     OutputStream output = getContentResolver().openOutputStream(destination, "w")) {
                    if (output == null) throw new IOException("Selected document is unavailable");
                    byte[] chunk = new byte[32 * 1024];
                    int count;
                    while ((count = input.read(chunk)) != -1) output.write(chunk, 0, count);
                    output.flush();
                    saved = true;
                } catch (Exception ignored) { }
                source.delete();
                boolean completed = saved;
                handler.post(() -> {
                    if (stillCurrent(scopedAccount, room)) chatNotice.setText(completed
                            ? R.string.bchat_media_saved : R.string.bchat_media_unavailable);
                });
            }, "bchat-media-export").start();
            return;
        }
        if (requestCode != MEDIA_PICK_REQUEST && requestCode != MEDIA_CAMERA_REQUEST) return;
        AccountScope scopedAccount = mediaPickerAccount;
        Room room = mediaPickerRoom;
        int generation = mediaPickerGeneration;
        mediaPickerAccount = null;
        mediaPickerRoom = null;
        File captured = cameraCaptureFile;
        cameraCaptureFile = null;
        Uri selected = requestCode == MEDIA_CAMERA_REQUEST && captured != null
                ? new Uri.Builder().scheme("content").authority(getPackageName() + ".files")
                    .appendPath(captured.getName()).build()
                : data == null ? null : data.getData();
        if (resultCode != RESULT_OK || selected == null
                || !stillCurrent(scopedAccount, room) || generation != mediaSessionGeneration
                || !mediaUploadAllowed()) {
            if (captured != null) captured.delete();
            return;
        }
        classifyConnectedMedia(scopedAccount, room, generation, selected, captured);
    }

    private void classifyConnectedMedia(AccountScope scopedAccount, Room room, int generation, Uri selected,
                                        File temporary) {
        String mime;
        try { mime = getContentResolver().getType(selected); }
        catch (RuntimeException unreadable) {
            if (temporary != null) temporary.delete();
            chatNotice.setText(R.string.bchat_media_invalid); return;
        }
        boolean eligible = "image/jpeg".equals(mime) || "image/png".equals(mime)
                || "image/webp".equals(mime) || "application/pdf".equals(mime);
        if (!eligible || "off".equals(room.invoicePolicy)) {
            stageConnectedMedia(scopedAccount, room, generation, selected, temporary, "other", 0); return;
        }
        Ui.decorateDialog(new AlertDialog.Builder(this).setTitle(R.string.bchat_media_classify)
                .setSingleChoiceItems(new String[]{getString(R.string.bchat_media_other),
                        getString(R.string.bchat_media_invoice),
                        getString(R.string.bchat_media_receipt)},
                        "invoice_default".equals(room.invoicePolicy) ? 1 : 0,
                        (dialog, which) -> {
                    dialog.dismiss();
                    if (!stillCurrent(scopedAccount, room) || generation != mediaSessionGeneration) {
                        if (temporary != null) temporary.delete(); return;
                    }
                    if (which == 2) chooseInvoiceCase(scopedAccount, room, generation, selected, temporary);
                    else stageConnectedMedia(scopedAccount, room, generation, selected, temporary,
                            which == 1 ? "invoice" : "other", 0);
                }).setNegativeButton(R.string.chat_v2_cancel,
                        (dialog, which) -> { if (temporary != null) temporary.delete(); }).show());
    }

    private void chooseInvoiceCase(AccountScope scopedAccount, Room room, int generation, Uri selected,
                                   File temporary) {
        fetchV2("GET", V2_ROOMS + "/" + room.id + "/invoice-cases", null, (status, response) -> {
            if (!stillCurrent(scopedAccount, room) || generation != mediaSessionGeneration) {
                if (temporary != null) temporary.delete(); return;
            }
            try {
                if (status != 200 || response == null || positiveId(response.get("api_version")) != 2)
                    throw new IOException("Invoice cases unavailable");
                JSONArray cases = response.getJSONArray("invoice_cases");
                if (cases.length() > 100) throw new IOException("Too many invoice cases");
                if (cases.length() == 0) {
                    if (temporary != null) temporary.delete();
                    chatNotice.setText(R.string.bchat_media_no_invoice_case); return;
                }
                long[] ids = new long[cases.length()];
                String[] names = new String[cases.length()];
                for (int i = 0; i < cases.length(); i++) {
                    JSONObject item = cases.getJSONObject(i);
                    ids[i] = positiveId(item.get("id"));
                    positiveId(item.get("source_message_id"));
                    names[i] = item.getString("source_name");
                    if (names[i].trim().isEmpty() || names[i].length() > 160)
                        throw new IOException("Invalid invoice case");
                }
                Ui.decorateDialog(new AlertDialog.Builder(this).setTitle(R.string.bchat_media_choose_invoice)
                        .setItems(names, (dialog, which) -> stageConnectedMedia(scopedAccount,
                                room, generation, selected, temporary, "payment_receipt", ids[which]))
                        .setNegativeButton(R.string.chat_v2_cancel,
                                (dialog, which) -> { if (temporary != null) temporary.delete(); }).show());
            } catch (Exception invalid) {
                if (temporary != null) temporary.delete();
                chatNotice.setText(R.string.bchat_media_no_invoice_case);
            }
        });
    }

    private void stageConnectedMedia(AccountScope scopedAccount, Room room, int generation, Uri selected,
                                     File temporary, String documentType, long invoiceCaseId) {
        if (!stillCurrent(scopedAccount, room) || generation != mediaSessionGeneration
                || !mediaUploadAllowed()) {
            if (temporary != null) temporary.delete(); return;
        }
        String text = messageInput.getText().toString();
        long replyId = selectedReplyMessageId;
        String captureName = null;
        if (temporary != null) {
            String stamp = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date());
            captureName = temporary.getName().endsWith(".m4a")
                    ? "voice-" + stamp + ".m4a" : "photo-" + stamp + ".jpg";
        }
        final String stagedName = captureName;
        mediaStageBusy = true;
        updatePendingUi();
        chatNotice.setText(R.string.bchat_media_uploading);
        new Thread(() -> {
            BChatConnectedMediaStore.Entry staged = null;
            try {
                if (generation == mediaSessionGeneration) {
                    staged = mediaStore.stage(getContentResolver(), scopedAccount, room.id, room.companyId,
                            room.membershipId, selected, text, replyId, documentType,
                            room.invoicePolicyVersion, invoiceCaseId, stagedName);
                }
            } catch (Exception ignored) { /* The user sees a bounded, non-sensitive error. */ }
            finally { if (temporary != null) temporary.delete(); }
            BChatConnectedMediaStore.Entry finalStaged = staged;
            handler.post(() -> {
                if (generation != mediaSessionGeneration || !stillCurrent(scopedAccount, room)) {
                    if (finalStaged != null) {
                        try { mediaStore.discard(scopedAccount, finalStaged); }
                        catch (IOException ignored) { /* The old membership cannot upload. */ }
                    }
                    return;
                }
                mediaStageBusy = false;
                if (!mediaUploadAllowed()) {
                    if (finalStaged != null) try { mediaStore.discard(scopedAccount, finalStaged); }
                    catch (IOException ignored) { /* Sending was revoked after staging. */ }
                    return;
                }
                if (finalStaged == null) { chatNotice.setText(R.string.bchat_media_invalid); return; }
                flushDraftSave();
                if (text.equals(messageInput.getText().toString())) {
                    try { outbox.saveDraft(scopedAccount, room.id, room.membershipId, ""); }
                    catch (Exception ignored) { chatNotice.setText(R.string.chat_v2_save_failed); }
                    suppressDraftChanges = true;
                    messageInput.setText("");
                    suppressDraftChanges = false;
                }
                if (selectedReplyMessageId == replyId) clearSelectedReply();
                retryConnectedMedia();
                updatePendingUi();
            });
        }, "bchat-media-stage").start();
    }

    private void reviewConnectedMedia() {
        Room room = selectedRoom;
        AccountScope scopedAccount = account;
        if (!CONNECTED_MEDIA_UI_ENABLED || !stillCurrent(scopedAccount, room) || mediaStore == null) return;
        try {
            List<BChatConnectedMediaStore.Entry> entries = mediaStore.pendingForRoom(scopedAccount,
                    room.id, room.membershipId);
            if (entries.isEmpty()) { updatePendingUi(); return; }
            BChatConnectedMediaStore.Entry entry = entries.get(0);
            boolean policyChanged = entry.policyVersion != room.invoicePolicyVersion;
            boolean uploadBlocked = !entry.uploadBlockCode.isEmpty();
            boolean hasUploadedRecord = false;
            StringBuilder detail = new StringBuilder(getString(R.string.bchat_media_review_intro,
                    entries.size()));
            for (BChatConnectedMediaStore.Entry candidate : entries) {
                detail.append("\n\n").append(candidate.name).append("\n")
                        .append(connectedMediaPendingStatus(candidate, room));
                if (candidate.mediaId > 0 && candidate.policyVersion == room.invoicePolicyVersion
                        && candidate.uploadBlockCode.isEmpty()) hasUploadedRecord = true;
            }
            AlertDialog.Builder review = new AlertDialog.Builder(this)
                    .setTitle(R.string.bchat_media_pending)
                    .setMessage(detail)
                    .setNeutralButton(R.string.chat_v2_delete_local, (dialog, which) ->
                            showPendingDialog(new AlertDialog.Builder(this)
                                    .setTitle(R.string.chat_v2_delete_local)
                                    .setMessage(R.string.chat_v2_delete_warning)
                                    .setPositiveButton(R.string.chat_v2_delete_local, (confirm, accepted) -> {
                                        if (!stillCurrent(scopedAccount, room)) return;
                                        discardConnectedMedia(scopedAccount, room, entry, 0);
                                    }).setNegativeButton(R.string.chat_v2_cancel, null)))
                    .setNegativeButton(R.string.chat_v2_cancel, null);
            if (hasUploadedRecord) review.setPositiveButton(R.string.bchat_media_check_now,
                    (dialog, which) -> checkConnectedMediaStatus(scopedAccount, room));
            else if (!policyChanged && !uploadBlocked && mediaUploadAllowed())
                review.setPositiveButton(R.string.chat_v2_retry, (dialog, which) -> retryConnectedMedia());
            showPendingDialog(review);
        } catch (IOException invalid) { chatNotice.setText(R.string.chat_v2_save_failed); }
    }

    private String connectedMediaPendingStatus(BChatConnectedMediaStore.Entry entry, Room room) {
        if (entry.policyVersion != room.invoicePolicyVersion)
            return getString(R.string.bchat_media_policy_changed);
        if (!entry.uploadBlockCode.isEmpty())
            return getString(R.string.bchat_media_status_rejected, entry.uploadBlockCode);
        if (entry.mediaId <= 0) return getString(R.string.bchat_media_status_upload_pending);
        return getString(R.string.bchat_media_status_message_pending, entry.mediaId);
    }

    /** Re-reads verified room history only; it never uploads or posts a media message. */
    private void checkConnectedMediaStatus(AccountScope scopedAccount, Room room) {
        if (!stillCurrent(scopedAccount, room) || mediaStore == null) return;
        try {
            boolean hasUploadedRecord = false;
            for (BChatConnectedMediaStore.Entry entry : mediaStore.pendingForRoom(scopedAccount,
                    room.id, room.membershipId))
                if (entry.mediaId > 0 && entry.policyVersion == room.invoicePolicyVersion
                        && entry.uploadBlockCode.isEmpty()) hasUploadedRecord = true;
            if (!hasUploadedRecord) {
                chatNotice.setText(R.string.bchat_media_status_upload_pending);
                return;
            }
            chatNotice.setText(R.string.bchat_media_checking);
            recoverUncertainMediaConfirmation(scopedAccount, room);
        } catch (IOException unavailable) { chatNotice.setText(R.string.chat_v2_save_failed); }
    }

    private void discardConnectedMedia(AccountScope scope, Room room,
                                       BChatConnectedMediaStore.Entry entry, int attempt) {
        if (scope != account || mediaStore == null || entry == null || mediaCancelBusy) return;
        if (mediaUploadBusy) closeMediaUpload();
        if (entry.mediaId <= 0) {
            // This is an explicit user-confirmed local deletion. The warning states that
            // an upload may still exist on the server; never imply remote cancellation.
            discardLocalMediaAfterReview(scope, room, entry, true);
            return;
        }
        if (!liveReady(scope)) {
            discardLocalMediaAfterReview(scope, room, entry, true);
            return;
        }
        mediaCancelBusy = true;
        enqueueLive("POST", "/bchat/api/v2/uploads/" + entry.mediaId + "/cancel", "", null,
                (statusCode, result) -> {
                    mediaCancelBusy = false;
                    if (scope != account || mediaStore == null) return;
                    try {
                        if (statusCode == 200 && result != null
                                && nonnegativeCursor(result.get("api_version")) == 2
                                && positiveId(result.get("media_id")) == entry.mediaId
                                && "cancelled".equals(result.getString("state"))) {
                            discardLocalMediaAfterReview(scope, room, entry, false);
                            return;
                        }
                    } catch (Exception invalid) { /* Keep local upload for a safe retry. */ }
                    if (statusCode == 401) { logout(); return; }
                    if ((statusCode == 0 || statusCode >= 500) && attempt < 3) {
                        handler.postDelayed(() -> {
                            if (scope != account) return;
                            if (liveReady(scope)) discardConnectedMedia(scope, room, entry, attempt + 1);
                            else discardLocalMediaAfterReview(scope, room, entry, true);
                        }, 1000L * (attempt + 1));
                        return;
                    }
                    // Cancellation may be impossible after attachment, or its outcome may be
                    // unknown. The user explicitly chose to delete the local copy only.
                    discardLocalMediaAfterReview(scope, room, entry, true);
                });
    }

    private void discardLocalMediaAfterReview(AccountScope scope, Room room,
                                              BChatConnectedMediaStore.Entry entry, boolean remoteUncertain) {
        if (scope != account || mediaStore == null) return;
        try {
            mediaStore.discard(scope, entry);
            if (stillCurrent(scope, room)) {
                updatePendingUi();
                if (remoteUncertain) chatNotice.setText(R.string.bchat_media_local_removed_only);
            }
        } catch (IOException invalid) {
            if (stillCurrent(scope, room)) chatNotice.setText(R.string.chat_v2_save_failed);
        }
    }

    private void retryConnectedMedia() {
        AccountScope scopedAccount = account;
        Room room = selectedRoom;
        if (!stillCurrent(scopedAccount, room) || !mediaUploadAllowed() || mediaStore == null
                || mediaUploadBusy || v2Busy || csrfToken == null) return;
        try {
            BChatConnectedMediaStore.Entry entry = mediaStore.pending(scopedAccount, room.id, room.membershipId);
            if (entry == null) return;
            if (entry.policyVersion != room.invoicePolicyVersion) {
                chatNotice.setText(R.string.bchat_media_policy_changed);
                return;
            }
            if (!entry.uploadBlockCode.isEmpty()) {
                chatNotice.setText(R.string.bchat_media_upload_blocked);
                return;
            }
            if (outbox.first(scopedAccount, room.id, room.membershipId) != null) {
                chatNotice.setText(R.string.chat_v2_pending); return;
            }
            // media_id means upload was already acknowledged.  Replaying its immutable
            // client UUID is idempotent and must not upload the original bytes again.
            if (entry.mediaId > 0) {
                sendConnectedMedia(scopedAccount, room, entry);
                return;
            }
            // No server media identity exists yet, so this is a genuine upload retry.
            uploadConnectedMedia(scopedAccount, room, entry);
        } catch (Exception invalid) { chatNotice.setText(R.string.chat_v2_save_failed); }
    }

    /**
     * Recover the narrow crash/transport gap after upload acknowledgement but before the
     * message acknowledgement reached local storage.  V2 deduplicates client_uuid, so this
     * sends no file bytes and cannot create a duplicate message.
     */
    private void replayKnownConnectedMedia(AccountScope scopedAccount, Room room) {
        if (!stillCurrent(scopedAccount, room) || mediaStore == null || outbox == null
                || mediaStageBusy || mediaUploadBusy || mediaConfirmBusy || v2Busy) return;
        try {
            BChatConnectedMediaStore.Entry entry = mediaStore.pending(scopedAccount, room.id,
                    room.membershipId);
            if (entry == null || entry.mediaId <= 0
                    || entry.policyVersion != room.invoicePolicyVersion
                    || !entry.uploadBlockCode.isEmpty()
                    || outbox.first(scopedAccount, room.id, room.membershipId) != null) return;
            sendConnectedMedia(scopedAccount, room, entry);
        } catch (IOException ignored) {
            // Keep the explicit recovery action if local storage itself cannot be read.
        }
    }

    private void closeMediaUpload() {
        ++mediaUploadNonce;
        mediaUploadBusy = false;
        if (mediaUploadTimeout != null) { handler.removeCallbacks(mediaUploadTimeout); mediaUploadTimeout = null; }
        if (mediaNativeUpload != null) { mediaNativeUpload.cancel(); mediaNativeUpload = null; }
    }

    private void mediaUploadDeadline(int request, AccountScope scopedAccount, Room room) {
        if (mediaUploadTimeout != null) handler.removeCallbacks(mediaUploadTimeout);
        mediaUploadTimeout = () -> {
            if (request != mediaUploadNonce || !mediaUploadBusy) return;
            closeMediaUpload();
            if (stillCurrent(scopedAccount, room)) chatNotice.setText(R.string.chat_v2_uncertain);
        };
        handler.postDelayed(mediaUploadTimeout, 90000);
    }

    private void uploadConnectedMedia(AccountScope scopedAccount, Room room,
                                      BChatConnectedMediaStore.Entry entry) throws IOException {
        if (!stillCurrent(scopedAccount, room) || !mediaUploadAllowed() || mediaUploadBusy || web == null
                || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl()))) return;
        File staged = mediaStore.file(scopedAccount, entry);
        mediaUploadBusy = true;
        updatePendingUi();
        final int request = ++mediaUploadNonce;
        final String path = V2_ROOMS + "/" + room.id + "/mobile-upload-grants";
        chatNotice.setText(R.string.bchat_media_uploading);
        mediaUploadDeadline(request, scopedAccount, room);
        if (!postSmallFormDirectlyInWebView(path, "metadata", entry.uploadMetadata().toString(),
                (statusCode, result) -> beginNativeMediaUpload(request, scopedAccount, room, entry,
                        staged, statusCode, result))) {
            closeMediaUpload();
            if (stillCurrent(scopedAccount, room)) chatNotice.setText(R.string.chat_v2_uncertain);
        }
    }

    private void beginNativeMediaUpload(int request, AccountScope scopedAccount, Room room,
                                        BChatConnectedMediaStore.Entry entry, File staged,
                                        int statusCode, JSONObject result) {
        if (closed || request != mediaUploadNonce || !mediaUploadBusy
                || !stillCurrent(scopedAccount, room)) return;
        try {
            if (statusCode != 200 || result == null || positiveId(result.get("api_version")) != 2)
                throw new IOException("Native grant rejected");
            String grantId = result.getString("grant_id");
            String secret = result.getString("secret");
            if (!grantId.matches("[0-9a-f-]{36}") || !secret.matches("[A-Za-z0-9_-]{43,128}"))
                throw new IOException("Invalid native grant");
            BChatNativeMediaUploader.Call call = new BChatNativeMediaUploader.Call();
            mediaNativeUpload = call;
            mediaIo.execute(() -> {
                BChatNativeMediaUploader.Result response = BChatNativeMediaUploader.upload(
                        call, ORIGIN, grantId, secret, staged, entry.size, entry.mime);
                handler.post(() -> finishNativeMediaUpload(request, scopedAccount, room, entry,
                        grantId, secret, response));
            });
        } catch (Exception invalid) {
            closeMediaUpload();
            if (stillCurrent(scopedAccount, room)) chatNotice.setText(R.string.chat_v2_uncertain);
        }
    }

    private void finishNativeMediaUpload(int request, AccountScope scopedAccount, Room room,
                                         BChatConnectedMediaStore.Entry entry, String grantId,
                                         String secret, BChatNativeMediaUploader.Result response) {
        if (closed || request != mediaUploadNonce || !mediaUploadBusy
                || !stillCurrent(scopedAccount, room)) return;
        if (response.isTransportFailure() || response.status == 202) {
            checkNativeMediaUpload(request, scopedAccount, room, entry, grantId, secret, 0);
            return;
        }
        applyNativeMediaResult(request, scopedAccount, room, entry, response, 0);
    }

    private void checkNativeMediaUpload(int request, AccountScope scopedAccount, Room room,
                                        BChatConnectedMediaStore.Entry entry, String grantId,
                                        String secret, int attempt) {
        if (closed || request != mediaUploadNonce || !mediaUploadBusy
                || !stillCurrent(scopedAccount, room)) return;
        BChatNativeMediaUploader.Call call = new BChatNativeMediaUploader.Call();
        mediaNativeUpload = call;
        mediaIo.execute(() -> {
            BChatNativeMediaUploader.Result response = BChatNativeMediaUploader.status(call, ORIGIN, grantId, secret);
            handler.post(() -> {
                if (closed || request != mediaUploadNonce || !mediaUploadBusy
                        || !stillCurrent(scopedAccount, room)) return;
                if (response.status == 202 && attempt < 4) {
                    handler.postDelayed(() -> checkNativeMediaUpload(request, scopedAccount, room, entry,
                            grantId, secret, attempt + 1), 500);
                } else applyNativeMediaResult(request, scopedAccount, room, entry, response, attempt);
            });
        });
    }

    private void applyNativeMediaResult(int request, AccountScope scopedAccount, Room room,
                                        BChatConnectedMediaStore.Entry entry,
                                        BChatNativeMediaUploader.Result response, int statusAttempt) {
        if (closed || request != mediaUploadNonce || !mediaUploadBusy
                || !stillCurrent(scopedAccount, room)) return;
        try {
            JSONObject result = new JSONObject(response.body);
            if (response.status == 200 && positiveId(result.get("api_version")) == 2
                    && entry.networkUploadUuid().equals(result.getString("upload_uuid"))
                    && ("staged".equals(result.getString("state"))
                    || "attached".equals(result.getString("state")))) {
                closeMediaUpload();
                BChatConnectedMediaStore.Entry saved = mediaStore.markUploaded(scopedAccount, entry,
                        positiveId(result.get("media_id")));
                sendConnectedMedia(scopedAccount, room, saved);
                return;
            }
            JSONObject error = result.optJSONObject("error");
            String code = error == null ? "native_upload_unconfirmed"
                    : error.optString("code", "native_upload_unconfirmed");
            if (!code.matches("[a-z_]{1,64}")) code = "native_upload_unconfirmed";
            closeMediaUpload();
            if (response.status == 400 || response.status == 409 || response.status == 413
                    || response.status == 415) {
                mediaStore.markUploadBlocked(scopedAccount, entry, code);
                if (response.status == 409) loadRooms();
                updatePendingUi();
                chatNotice.setText(R.string.bchat_media_upload_blocked);
            } else if (response.status == 429) {
                chatNotice.setText(R.string.bchat_media_rejected);
                updatePendingUi();
            } else chatNotice.setText(R.string.chat_v2_uncertain);
        } catch (Exception invalid) {
            closeMediaUpload();
            if (stillCurrent(scopedAccount, room)) chatNotice.setText(R.string.chat_v2_uncertain);
        }
    }

    private void sendConnectedMedia(AccountScope scopedAccount, Room room,
                                    BChatConnectedMediaStore.Entry entry) {
        if (!stillCurrent(scopedAccount, room) || !mediaUploadAllowed()
                || entry.mediaId <= 0 || v2Busy) return;
        try {
            JSONObject payload = new JSONObject();
            payload.put("api_version", 2);
            payload.put("membership_id", room.membershipId);
            payload.put("client_uuid", entry.clientUuid);
            payload.put("text", entry.text);
            payload.put("media_id", entry.mediaId);
            payload.put("document_type", entry.documentType);
            payload.put("policy_version", entry.policyVersion);
            if (entry.invoiceCaseId > 0) payload.put("invoice_case_id", entry.invoiceCaseId);
            if (entry.replyToMessageId > 0) payload.put("reply_to_message_id", entry.replyToMessageId);
            mediaConfirmBusy = true;
            mediaConfirmRoom = room;
            updatePendingUi();
            fetchV2("POST", V2_ROOMS + "/" + room.id + "/messages", payload.toString(),
                    (statusCode, result) -> {
                        mediaConfirmBusy = false;
                        mediaConfirmRoom = null;
                        // The POST may have committed on Odoo while this Android WebView loses
                        // its transferred reply port.  The existing media ID is a verified
                        // server receipt, so read the room history once before the generic
                        // transport path clears the chat.  This never retries the POST.
                        if (statusCode == 0) {
                            recoverUncertainMediaConfirmation(scopedAccount, room);
                            return;
                        }
                        if (handleV2TransportFailure(statusCode, true)) return;
                        try {
                            if (statusCode != 200 && statusCode != 201) throw new IOException("Media send denied");
                            if (result == null || positiveId(result.get("api_version")) != 2
                                    || positiveId(result.get("room_id")) != room.id
                                    || positiveId(result.get("membership_id")) != room.membershipId
                                    || positiveId(result.get("media_id")) != entry.mediaId
                                    || !entry.clientUuid.equals(result.getString("client_uuid"))
                                    || !"sent".equals(result.getString("state")))
                                throw new IOException("Unverified media ACK");
                            long sentMessageId = positiveId(result.get("message_id"));
                            // The server receipt is enough to retire this exact local request.
                            // Do this before testing the current screen: a room reload or a
                            // quick navigation must not leave an already-sent image blocking
                            // the next message on the device.
                            mediaStore.acknowledge(scopedAccount, entry);
                            if (!stillCurrent(scopedAccount, room)) return;
                            chatNotice.setText(R.string.chat_v2_sent);
                            updatePendingUi();
                            appendAcknowledgedMessage(scopedAccount, room, sentMessageId);
                        } catch (Exception invalid) {
                            // A 2xx response whose one-shot bridge body was truncated or malformed
                            // is still an uncertain write.  The verified history path can retire
                            // every matching staged media record without repeating the POST.
                            if (statusCode >= 200 && statusCode < 300) {
                                recoverUncertainMediaConfirmation(scopedAccount, room);
                                return;
                            }
                            if (!stillCurrent(scopedAccount, room)) return;
                            JSONObject error = result == null ? null : result.optJSONObject("error");
                            boolean policyChanged = statusCode == 409 && error != null
                                    && "document_policy_changed".equals(error.optString("code"));
                            chatNotice.setText(policyChanged ? R.string.bchat_media_policy_changed
                                    : statusCode == 400 || statusCode == 409 || statusCode == 413
                                    || statusCode == 429 ? R.string.bchat_media_rejected
                                    : R.string.chat_v2_uncertain);
                            updatePendingUi();
                            if (statusCode == 403) loadRooms();
                            else if (statusCode == 409) loadRooms();
                        }
                    });
        } catch (Exception invalid) {
            mediaConfirmBusy = false;
            mediaConfirmRoom = null;
            chatNotice.setText(R.string.chat_v2_uncertain);
            updatePendingUi();
        }
    }

    /**
     * A media send with a lost response is an uncertain write: retain the local file until
     * authenticated history proves the exact media ID belongs to this account.  Unlike the
     * generic failure path this keeps the visible room alive long enough for the direct GET
     * fallback to reconcile it; it never sends another message.
     */
    private void recoverUncertainMediaConfirmation(AccountScope scopedAccount, Room room) {
        final int recovery = ++mediaConfirmRecoveryGeneration;
        recoverUncertainMediaConfirmation(scopedAccount, room, recovery, 0);
    }

    private void recoverUncertainMediaConfirmation(AccountScope scopedAccount, Room room,
                                                    int recovery, int attempt) {
        handler.postDelayed(() -> {
            if (recovery != mediaConfirmRecoveryGeneration || !stillCurrent(scopedAccount, room)
                    || mediaStore == null) return;
            try {
                List<BChatConnectedMediaStore.Entry> pending = mediaStore.pendingForRoom(scopedAccount,
                        room.id, room.membershipId);
                boolean hasUploadedRecord = false;
                for (BChatConnectedMediaStore.Entry entry : pending)
                    if (entry.mediaId > 0) hasUploadedRecord = true;
                if (!hasUploadedRecord) return;
            } catch (IOException unavailable) {
                return;
            }
            if (v2Busy) {
                if (attempt < 2)
                    recoverUncertainMediaConfirmation(scopedAccount, room, recovery, attempt + 1);
                return;
            }
            // loadMessages validates the authenticated history and reconciles every exact media
            // ID in this room.  Retry only the read: an absent message remains pending for
            // explicit review and this method never repeats the POST.
            loadMessages(0);
            if (attempt < 2)
                recoverUncertainMediaConfirmation(scopedAccount, room, recovery, attempt + 1);
        }, attempt == 0 ? 180L : 360L);
    }

    private void retryPending() {
        Room room = selectedRoom;
        if (!sendAllowed() || room == null || v2Busy || account == null || outbox == null) return;
        BChatV2Outbox.Entry entry = outbox.first(account, room.id, room.membershipId);
        if (entry == null) { updatePendingUi(); return; }
        try {
            JSONObject payload = new JSONObject();
            payload.put("api_version", 2);
            payload.put("membership_id", room.membershipId);
            payload.put("client_uuid", entry.uuid);
            payload.put("text", entry.body);
            if (entry.replyToMessageId > 0) payload.put("reply_to_message_id", entry.replyToMessageId);
            String path = V2_ROOMS + "/" + room.id + "/messages";
            chatNotice.setText(R.string.chat_v2_sending);
            retryButton.setEnabled(false);
            fetchV2("POST", path, payload.toString(), (statusCode, result) -> {
                if (handleV2TransportFailure(statusCode, true)) return;
                try {
                    if (statusCode != 200 && statusCode != 201) throw new IllegalArgumentException();
                    if (result == null || positiveId(result.get("api_version")) != 2
                            || positiveId(result.get("room_id")) != room.id
                            || positiveId(result.get("membership_id")) != room.membershipId
                            || !entry.uuid.equals(result.getString("client_uuid"))
                            || !"sent".equals(result.getString("state"))) throw new IllegalArgumentException();
                    long sentMessageId = positiveId(result.get("message_id"));
                    if (!outbox.acknowledge(account, entry)) throw new IllegalArgumentException();
                    if (selectedRoom == room) {
                        chatNotice.setText(R.string.chat_v2_sent);
                        appendAcknowledgedMessage(account, room, sentMessageId);
                    }
                } catch (Exception invalid) {
                    if (statusCode == 400 || statusCode == 413) {
                        try { outbox.recordRejected(account, entry); }
                        catch (Exception storage) { chatNotice.setText(R.string.chat_v2_save_failed); }
                    }
                    if (selectedRoom == room) {
                        chatNotice.setText(statusCode == 400 || statusCode == 413
                                ? R.string.chat_v2_rejected_review : R.string.chat_v2_uncertain);
                        if (statusCode == 403 || statusCode == 409) {
                            unresolvedSendNotice = true;
                            displayedMessages.clear();
                            messageAdapter.notifyDataSetChanged();
                            showRooms();
                            loadRooms();
                        }
                    }
                } finally { if (selectedRoom == room) { retryButton.setEnabled(true); updatePendingUi(); } }
            });
        } catch (Exception invalid) { chatNotice.setText(R.string.chat_v2_uncertain); }
    }

    private static final class TaskChoice {
        final long id;
        final String name;
        TaskChoice(long id, String name) { this.id = id; this.name = name; }
    }

    private static final class Task {
        final long id, companyId, roomId, creatorId, assigneeId, revision;
        final String title, description, dueAt, state, creatorName, assigneeName, createdAt, lastNote;
        Task(JSONObject item) throws Exception {
            id = positiveId(item.get("id"));
            companyId = positiveId(item.get("company_id"));
            Object room = item.get("room_id");
            roomId = room == JSONObject.NULL ? 0 : positiveId(room);
            title = boundedTaskText(item.getString("title"), 160, true);
            description = boundedTaskText(item.getString("description"), 4096, false);
            Object due = item.get("due_at");
            dueAt = due == JSONObject.NULL ? null : taskDate(due);
            state = item.getString("state");
            if (!("new".equals(state) || "in_progress".equals(state)
                    || "done".equals(state) || "cancelled".equals(state))) throw new IllegalArgumentException();
            creatorId = positiveId(item.get("creator_id"));
            assigneeId = positiveId(item.get("assignee_id"));
            creatorName = boundedTaskText(item.getString("creator_name"), 256, true);
            assigneeName = boundedTaskText(item.getString("assignee_name"), 256, true);
            lastNote = boundedTaskText(item.optString("last_note", ""), 512, false);
            createdAt = taskDate(item.get("created_at"));
            taskDate(item.get("updated_at"));
            Object lastChanged = item.get("last_changed_at");
            if (lastChanged != JSONObject.NULL) taskDate(lastChanged);
            Object lastActor = item.get("last_actor_id");
            if (lastActor != JSONObject.NULL) positiveId(lastActor);
            revision = positiveId(item.get("revision"));
        }
    }

    private static String boundedTaskText(String text, int limit, boolean required) {
        if (text == null || text.getBytes(StandardCharsets.UTF_8).length > limit
                || text.indexOf('\0') >= 0 || (required && text.trim().isEmpty()))
            throw new IllegalArgumentException();
        return text;
    }

    private static String taskDate(Object raw) {
        if (!(raw instanceof String) || !((String) raw).matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"))
            throw new IllegalArgumentException();
        return (String) raw;
    }

    private List<TaskChoice> choices(JSONArray array, int maximum, boolean companies) throws Exception {
        if (array.length() > maximum) throw new IllegalArgumentException();
        List<TaskChoice> list = new ArrayList<>();
        Set<Long> ids = new HashSet<>();
        for (int i = 0; i < array.length(); i++) {
            JSONObject item = array.getJSONObject(i);
            long id = positiveId(item.get("id"));
            String name = boundedTaskText(item.getString("name"), 256, true);
            if (!ids.add(id) || (companies && !v1Companies.contains(id))) throw new IllegalArgumentException();
            list.add(new TaskChoice(id, name));
        }
        return list;
    }

    private JSONArray cachedTaskCompanies() throws Exception {
        JSONArray value = new JSONArray();
        for (TaskChoice company : taskCompanies) {
            JSONObject item = new JSONObject();
            item.put("id", company.id);
            item.put("name", company.name);
            value.put(item);
        }
        return value;
    }

    private void cacheVerifiedTaskPage(AccountScope scope, long roomId, String stateFilter,
                                       JSONArray page, long nextBeforeId) {
        if (scope == null || taskOfflineCache == null || page == null) return;
        try {
            final JSONArray taskCopy = new JSONArray(page.toString());
            final JSONArray companyCopy = cachedTaskCompanies();
            final Set<Long> companyScope = new HashSet<>(v1Companies);
            final TaskOfflineCache cache = taskOfflineCache;
            final boolean remembered = preferences().getBoolean(REMEMBER, false);
            final long verifiedAt = System.currentTimeMillis();
            final int generation = historyWriteGeneration;
            final int globalGeneration = historyGlobalGeneration;
            historyWrites.execute(() -> {
                synchronized (historyStorageLock) {
                    if (closed || generation != historyWriteGeneration
                            || globalGeneration != historyGlobalGeneration || account != scope
                            || taskOfflineCache != cache) return;
                    try {
                        cache.save(scope, companyScope, roomId, stateFilter, taskCopy, companyCopy,
                                nextBeforeId, remembered, verifiedAt);
                    } catch (Exception storage) {
                        handler.post(() -> {
                            if (closed || account != scope || taskOfflineCache != cache) return;
                            preferences().edit().putBoolean(REMEMBER, false).commit();
                            synchronized (historyStorageLock) {
                                cache.close();
                                if (taskOfflineCache == cache) taskOfflineCache = null;
                            }
                        });
                    }
                }
            });
        } catch (Exception ignored) {
            // The network response remains valid even if a non-authoritative local copy cannot be made.
        }
    }

    private void openTasks(long roomId) {
        if (!permissionSet.taskView) return;
        ++taskViewSerial;
        if (taskRoomFilter != roomId) taskStateFilter = "open";
        taskRoomFilter = roomId;
        if ("tasks".equals(visibleSection)) discoverTasks();
        else switchSection("tasks");
    }

    private void discoverTasks() {
        if (!permissionSet.taskView || !"tasks".equals(visibleSection) || !verified) return;
        final int serial = ++taskViewSerial;
        final AccountScope scopedAccount = account;
        updatePendingTaskUi();
        if (v2Busy) {
            taskNotice.setText(R.string.task_loading);
            handler.postDelayed(() -> { if ("tasks".equals(visibleSection) && verified) discoverTasks(); }, 500);
            return;
        }
        // Keeping a list is pleasant during a refresh of the same room, but showing
        // another room's tasks under a new heading is misleading.  Clear that stale
        // scope immediately and leave the stable task shell/notice in place.
        boolean keepCurrentList = (tasksAvailable || !tasks.isEmpty())
                && renderedTaskRoomFilter == taskRoomFilter;
        tasksAvailable = false;
        if (!keepCurrentList) {
            tasks.clear();
            taskBeforeId = 0;
            taskNewButton.setVisibility(View.GONE);
            setTaskTabsVisibility(View.GONE);
            taskOlderButton.setVisibility(View.GONE);
            taskItems.removeAllViews();
        } else {
            taskNewButton.setEnabled(false);
            taskOlderButton.setEnabled(false);
        }
        taskNotice.setText(R.string.task_loading);
        final long roomFilter = taskRoomFilter;
        fetchV2("GET", V2_TASKS + "/options", null, (statusCode, result) -> {
            if (handleV2TransportFailure(statusCode)) return;
            if (scopedAccount != account || serial != taskViewSerial
                    || roomFilter != taskRoomFilter || !"tasks".equals(visibleSection)) return;
            if (statusCode == 404 || statusCode == 503) {
                taskNotice.setText(R.string.task_unavailable);
                return;
            }
            if (statusCode == 403) {
                clearDeniedTaskList();
                taskNotice.setText(R.string.task_denied);
                lastPermissionRefreshAt = 0;
                refreshPermissionSet();
                return;
            }
            try {
                if (statusCode != 200 || result == null || positiveId(result.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                List<TaskChoice> companies = choices(result.getJSONArray("companies"), 100, true);
                if (result.getJSONArray("assignees").length() != 0) throw new IllegalArgumentException();
                taskCompanies.clear();
                taskCompanies.addAll(companies);
                tasksAvailable = true;
                taskNewButton.setVisibility(permissionSet.taskManage && !companies.isEmpty()
                        ? View.VISIBLE : View.GONE);
                setTaskTabsVisibility(View.VISIBLE);
                updateTaskTabs();
                updatePendingTaskUi();
                taskHeading.setText(roomFilter > 0 ? R.string.task_room_tasks : R.string.chat_v2_tasks);
                taskHeading.setVisibility(roomFilter > 0 ? View.VISIBLE : View.GONE);
                if (pendingNotificationTaskId > 0) {
                    long notifiedTask = pendingNotificationTaskId;
                    pendingNotificationTaskId = 0;
                    loadTaskDetail(notifiedTask);
                } else loadTasks(0);
            } catch (Exception invalid) { taskNotice.setText(R.string.task_load_failed); }
        });
    }

    private void loadTasks(long beforeId) {
        if (!tasksAvailable || v2Busy || !verified || !"tasks".equals(visibleSection)) return;
        final long roomFilter = taskRoomFilter;
        final int serial = taskViewSerial;
        final AccountScope scopedAccount = account;
        String path = V2_TASKS + (roomFilter > 0 ? "?room_id=" + roomFilter : "");
        if (beforeId > 0) path += (path.contains("?") ? "&" : "?") + "before_id=" + beforeId;
        if (taskStateFilter != null) path += (path.contains("?") ? "&" : "?") + "state=" + taskStateFilter;
        taskNotice.setText(R.string.task_loading);
        headerRefresh.setEnabled(false);
        taskOlderButton.setEnabled(false);
        fetchV2("GET", path, null, (statusCode, result) -> {
            headerRefresh.setEnabled(true);
            if (handleV2TransportFailure(statusCode)) return;
            if (scopedAccount != account || serial != taskViewSerial
                    || roomFilter != taskRoomFilter || !"tasks".equals(visibleSection)) return;
            try {
                if (statusCode != 200 || result == null || positiveId(result.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                JSONArray items = result.getJSONArray("tasks");
                if (items.length() > 30) throw new IllegalArgumentException();
                List<Task> page = new ArrayList<>();
                long previous = beforeId > 0 ? beforeId : Long.MAX_VALUE;
                for (int i = 0; i < items.length(); i++) {
                    Task task = new Task(items.getJSONObject(i));
                    if (task.id >= previous || !v1Companies.contains(task.companyId)
                            || (roomFilter > 0 && task.roomId != roomFilter)
                            || (taskStateFilter != null && !("open".equals(taskStateFilter)
                            ? ("new".equals(task.state) || "in_progress".equals(task.state))
                            : taskStateFilter.equals(task.state))))
                        throw new IllegalArgumentException();
                    previous = task.id;
                    page.add(task);
                }
                Object next = result.opt("next_before_id");
                long cursor = next == null || next == JSONObject.NULL ? 0 : positiveId(next);
                if (cursor > 0 && (page.isEmpty() || cursor != page.get(page.size() - 1).id))
                    throw new IllegalArgumentException();
                if (beforeId == 0) cacheVerifiedTaskPage(scopedAccount, roomFilter,
                        taskStateFilter, items, cursor);
                if (beforeId == 0) tasks.clear();
                tasks.addAll(page);
                taskBeforeId = cursor;
                if (beforeId == 0) renderedTaskRoomFilter = roomFilter;
                renderTasks();
                handler.post(this::refreshAttentionBadge);
                taskOlderButton.setVisibility(cursor > 0 ? View.VISIBLE : View.GONE);
                taskOlderButton.setEnabled(cursor > 0);
                taskNotice.setText("");
            } catch (Exception invalid) {
                taskNotice.setText(statusCode == 403 ? R.string.task_denied : R.string.task_load_failed);
                if (statusCode == 403) clearDeniedTaskList();
            }
        });
    }

    /** Offline tasks are a complete previously verified first page, never a partial network merge. */
    private void showCachedTasks() {
        if (!offlineHistory || taskOfflineCache == null || account == null || !permissionSet.taskView) return;
        taskNewButton.setVisibility(View.GONE);
        setTaskTabsVisibility(View.VISIBLE);
        taskOlderButton.setVisibility(View.GONE);
        taskOlderButton.setEnabled(false);
        try {
            TaskOfflineCache.Page cached = taskOfflineCache.page(account, v1Companies,
                    taskRoomFilter, taskStateFilter);
            tasks.clear();
            taskCompanies.clear();
            taskBeforeId = 0;
            renderedTaskRoomFilter = taskRoomFilter;
            if (cached == null) {
                tasksAvailable = true;
                renderTasks();
                taskNotice.setText(offlineNotice(true));
                return;
            }
            List<TaskChoice> companies = choices(cached.companies, 100, true);
            Set<Long> companyIds = new HashSet<>();
            for (TaskChoice company : companies) companyIds.add(company.id);
            if (!companyIds.equals(v1Companies) || cached.tasks.length() > TaskOfflineCache.PAGE_SIZE)
                throw new IllegalArgumentException();
            long previous = Long.MAX_VALUE;
            for (int index = 0; index < cached.tasks.length(); index++) {
                Task task = new Task(cached.tasks.getJSONObject(index));
                if (task.id >= previous || !v1Companies.contains(task.companyId)
                        || (taskRoomFilter > 0 && task.roomId != taskRoomFilter)
                        || (taskStateFilter != null && !("open".equals(taskStateFilter)
                        ? ("new".equals(task.state) || "in_progress".equals(task.state))
                        : taskStateFilter.equals(task.state))))
                    throw new IllegalArgumentException();
                previous = task.id;
                tasks.add(task);
            }
            taskCompanies.addAll(companies);
            tasksAvailable = true;
            updateTaskTabs();
            taskHeading.setText(taskRoomFilter > 0 ? R.string.task_room_tasks : R.string.chat_v2_tasks);
            taskHeading.setVisibility(taskRoomFilter > 0 ? View.VISIBLE : View.GONE);
            renderTasks();
            taskNotice.setText(offlineNotice(true));
        } catch (Exception invalid) {
            tasks.clear();
            taskCompanies.clear();
            tasksAvailable = true;
            renderTasks();
            taskNotice.setText(R.string.task_load_failed);
        }
    }

    private void clearDeniedTaskList() {
        tasks.clear();
        renderedTaskRoomFilter = Long.MIN_VALUE;
        taskBeforeId = 0;
        taskItems.removeAllViews();
        taskOlderButton.setVisibility(View.GONE);
        taskOlderButton.setEnabled(false);
    }

    private void selectTaskState(String state) {
        if (!tasksAvailable || v2Busy || (state != null && !"open".equals(state)
                && !"done".equals(state) && !"cancelled".equals(state))) return;
        if (java.util.Objects.equals(taskStateFilter, state)) return;
        ++taskViewSerial;
        taskStateFilter = state;
        updateTaskTabs();
        if (offlineHistory) showCachedTasks(); else loadTasks(0);
    }

    private void setTaskTabsVisibility(int visibility) {
        if (taskAllButton == null || taskOpenButton == null || taskDoneButton == null) return;
        taskAllButton.setVisibility(visibility);
        taskOpenButton.setVisibility(visibility);
        taskDoneButton.setVisibility(visibility);
        if (taskAllLine != null) taskAllLine.setVisibility(visibility);
        if (taskOpenLine != null) taskOpenLine.setVisibility(visibility);
        if (taskDoneLine != null) taskDoneLine.setVisibility(visibility);
    }

    private void updateTaskTabs() {
        if (taskAllLine == null || taskOpenLine == null || taskDoneLine == null) return;
        boolean closed = "cancelled".equals(taskStateFilter);
        Ui.styleSegment(taskAllButton, closed);
        Ui.styleSegment(taskOpenButton, "open".equals(taskStateFilter));
        Ui.styleSegment(taskDoneButton, "done".equals(taskStateFilter));
        taskAllLine.setBackgroundColor(closed ? Ui.GREEN : Color.TRANSPARENT);
        taskOpenLine.setBackgroundColor("open".equals(taskStateFilter) ? Ui.GREEN : Color.TRANSPARENT);
        taskDoneLine.setBackgroundColor("done".equals(taskStateFilter) ? Ui.GREEN : Color.TRANSPARENT);
    }

    private int taskStateLabel(String state) {
        if ("new".equals(state)) return R.string.task_state_new;
        if ("in_progress".equals(state)) return R.string.task_state_progress;
        if ("done".equals(state)) return R.string.task_state_done;
        return R.string.task_state_cancelled;
    }

    private String taskCompanyName(long companyId) {
        for (TaskChoice choice : taskCompanies) if (choice.id == companyId) return choice.name;
        return String.valueOf(companyId);
    }

    private int taskStateColor(String state) {
        if ("done".equals(state)) return Ui.TASK_DONE;
        if ("cancelled".equals(state)) return Ui.TASK_CLOSED;
        return Ui.TASK_ACTIVE;
    }

    private int taskStateTint(String state) {
        if ("done".equals(state)) return Ui.TASK_DONE_TINT;
        if ("cancelled".equals(state)) return Ui.TASK_CLOSED_TINT;
        return Ui.TASK_ACTIVE_TINT;
    }

    private void renderTasks() {
        taskItems.removeAllViews();
        taskItems.setGravity(tasks.isEmpty() ? Gravity.CENTER : Gravity.TOP);
        if (tasks.isEmpty()) {
            LinearLayout empty = Ui.column(this);
            empty.setGravity(Gravity.CENTER);
            Ui.pad(empty, 16, 28);
            Ui.Icon icon = new Ui.Icon(this, "clock", Ui.MUTED);
            empty.addView(icon, new LinearLayout.LayoutParams(dp(30), dp(30)));
            TextView title = Ui.text(this, getString(R.string.task_empty), 16, Ui.INK, true);
            title.setGravity(Gravity.CENTER);
            empty.addView(title, fieldSize(10));
            taskItems.addView(empty);
            return;
        }
        for (Task task : tasks) {
            int accent = taskStateColor(task.state);
            LinearLayout entry = Ui.column(this);
            entry.setMinimumHeight(dp(116));
            entry.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 14, this));
            LinearLayout heading = Ui.row(this);
            heading.setGravity(Gravity.CENTER_VERTICAL);
            Ui.pad(heading, 13, 9);
            heading.setBackground(Ui.bg(taskStateTint(task.state), 14, this));
            TextView stateIcon = Ui.text(this, "•", 24, accent, true);
            stateIcon.setGravity(Gravity.CENTER);
            heading.addView(stateIcon, new LinearLayout.LayoutParams(dp(22), dp(28)));
            TextView title = Ui.text(this, task.title, 16, Ui.INK, true);
            title.setMaxLines(2);
            title.setEllipsize(android.text.TextUtils.TruncateAt.END);
            LinearLayout.LayoutParams titleSize = new LinearLayout.LayoutParams(0, -2, 1);
            titleSize.setMarginStart(dp(5));
            heading.addView(title, titleSize);
            TextView state = Ui.text(this, getString(taskStateLabel(task.state)), 12, accent, true);
            Ui.pad(state, 8, 4);
            state.setBackground(Ui.outline(taskStateTint(task.state), accent, 10, this));
            LinearLayout.LayoutParams stateSize = new LinearLayout.LayoutParams(-2, -2);
            stateSize.setMarginStart(dp(8));
            heading.addView(state, stateSize);
            entry.addView(heading, new LinearLayout.LayoutParams(-1, -2));
            LinearLayout content = Ui.column(this);
            Ui.pad(content, 13, 10);
            TextView company = Ui.text(this, taskCompanyName(task.companyId), 12, Ui.MUTED, true);
            company.setSingleLine(true);
            company.setEllipsize(android.text.TextUtils.TruncateAt.END);
            content.addView(company);
            TextView people = Ui.text(this, getString(R.string.bchat_task_people,
                    taskCompanyName(task.companyId), task.assigneeName), 13, Ui.INK, false);
            people.setMaxLines(1);
            people.setEllipsize(android.text.TextUtils.TruncateAt.END);
            LinearLayout.LayoutParams peopleSize = fieldSize(3);
            peopleSize.topMargin = dp(3);
            content.addView(people, peopleSize);
            if (task.dueAt != null) {
                TextView due = Ui.text(this, getString(R.string.task_due_value,
                        displayTaskDue(task.dueAt)), 12, Ui.MUTED, false);
                LinearLayout.LayoutParams dueSize = fieldSize(5);
                dueSize.setMargins(0, dp(5), 0, 0);
                content.addView(due, dueSize);
            }
            if (!task.lastNote.trim().isEmpty()) {
                TextView note = Ui.text(this, getString(R.string.task_last_note, task.lastNote),
                        12, Ui.INK, false);
                note.setMaxLines(2);
                note.setEllipsize(android.text.TextUtils.TruncateAt.END);
                note.setBackground(Ui.bg(taskStateTint(task.state), 8, this));
                Ui.pad(note, 9, 6);
                LinearLayout.LayoutParams noteSize = new LinearLayout.LayoutParams(-1, -2);
                noteSize.setMargins(0, dp(8), 0, 0);
                content.addView(note, noteSize);
            }
            entry.addView(content, new LinearLayout.LayoutParams(-1, -2));
            entry.setContentDescription(task.title + ", " + getString(taskStateLabel(task.state)));
            Ui.clickable(entry);
            entry.setOnClickListener(v -> {
                if (offlineHistory) showCachedTaskDetail(task); else loadTaskDetail(task.id);
            });
            LinearLayout.LayoutParams cardSize = new LinearLayout.LayoutParams(-1, -2);
            cardSize.setMargins(dp(10), dp(7), dp(10), dp(4));
            taskItems.addView(entry, cardSize);
        }
    }

    private void showCachedTaskDetail(Task task) {
        StringBuilder detail = new StringBuilder();
        if (!task.description.trim().isEmpty()) detail.append(task.description.trim()).append("\n\n");
        detail.append(getString(R.string.bchat_task_people,
                taskCompanyName(task.companyId), task.assigneeName));
        if (task.dueAt != null) detail.append("\n").append(getString(R.string.task_due_value,
                displayTaskDue(task.dueAt)));
        if (!task.lastNote.trim().isEmpty()) detail.append("\n\n")
                .append(getString(R.string.task_last_note, task.lastNote));
        detail.append("\n\n").append(offlineNotice(true));
        new AlertDialog.Builder(this).setTitle(task.title).setMessage(detail.toString())
                .setPositiveButton(R.string.task_close, null).show();
    }

    private interface TaskChoicesCallback { void ready(List<TaskChoice> choices); }
    private interface TaskOptionsFailure { void failed(int statusCode); }

    private void loadTaskAssignees(long companyId, long roomId,
                                   TaskChoicesCallback callback, TaskOptionsFailure onFailure) {
        if (v2Busy) return;
        final int serial = taskViewSerial;
        final AccountScope scopedAccount = account;
        final long roomFilter = taskRoomFilter;
        String path = V2_TASKS + "/options?company_id=" + companyId
                + (roomId > 0 ? "&room_id=" + roomId : "");
        taskNotice.setText(R.string.task_loading);
        fetchV2("GET", path, null, (statusCode, result) -> {
            if (handleV2TransportFailure(statusCode)) return;
            if (scopedAccount != account || serial != taskViewSerial
                    || roomFilter != taskRoomFilter || !"tasks".equals(visibleSection)) return;
            try {
                if (statusCode != 200 || result == null || positiveId(result.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                List<TaskChoice> companies = choices(result.getJSONArray("companies"), 100, true);
                boolean companyFound = false;
                for (TaskChoice choice : companies) if (choice.id == companyId) companyFound = true;
                if (!companyFound) throw new IllegalArgumentException();
                List<TaskChoice> assignees = choices(result.getJSONArray("assignees"), 100, false);
                taskNotice.setText("");
                callback.ready(assignees);
            } catch (Exception invalid) {
                taskNotice.setText(statusCode == 403 ? R.string.task_denied
                        : statusCode == 404 || statusCode == 503 ? R.string.task_unavailable
                        : R.string.task_load_failed);
                if (onFailure != null) onFailure.failed(statusCode);
            }
        });
    }

    private void createTaskDialog() {
        if (!permissionSet.taskManage || !tasksAvailable || v2Busy || taskCompanies.isEmpty()) return;
        if (hasPendingTaskCreate()) { reviewPendingTaskCreate(); return; }
        if (taskRoomFilter > 0) {
            for (Room room : rooms) if (room.id == taskRoomFilter) {
                showTaskForm(room.companyId, room.id);
                return;
            }
            taskNotice.setText(R.string.task_denied);
            return;
        }
        String[] labels = new String[taskCompanies.size()];
        for (int i = 0; i < taskCompanies.size(); i++)
            labels[i] = companyNameForId(taskCompanies.get(i).id, taskCompanies.get(i).name);
        showChoiceDialog(getString(R.string.task_choose_company), labels, "company",
                index -> showTaskForm(taskCompanies.get(index).id, 0));
    }

    private void showTaskForm(long companyId, long roomId) {
        loadTaskAssignees(companyId, roomId, assignees -> {
            if (!"tasks".equals(visibleSection) || taskRoomFilter != roomId) return;
            if (assignees.isEmpty()) { taskNotice.setText(R.string.task_no_assignees); return; }
            LinearLayout fields = Ui.column(this);
            Ui.pad(fields, 18, 4);
            fields.addView(Ui.text(this, getString(R.string.task_title), 13, Ui.MUTED, true), fieldSize(4));
            EditText title = new EditText(this);
            title.setSingleLine(true);
            title.setHint(R.string.task_title);
            title.setMaxLines(1);
            title.setTextSize(16);
            title.setMinHeight(dp(48));
            title.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 12, this));
            Ui.pad(title, 12, 6);
            fields.addView(title, fieldSize(3));
            fields.addView(Ui.text(this, getString(R.string.task_description), 13, Ui.MUTED, true), fieldSize(12));
            EditText description = new EditText(this);
            description.setHint(R.string.task_description);
            description.setMinLines(2);
            description.setMaxLines(4);
            description.setTextSize(15);
            description.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 12, this));
            Ui.pad(description, 12, 8);
            fields.addView(description, fieldSize(3));
            final TaskChoice[] selected = {null};
            Button assigneeButton = new Button(this);
            assigneeButton.setText(R.string.task_choose_assignee);
            styleAction(assigneeButton, false);
            assigneeButton.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 12, this));
            assigneeButton.setOnClickListener(v -> chooseTaskAssignee(assignees, choice -> {
                selected[0] = choice;
                assigneeButton.setText(choice.name);
            }));
            fields.addView(assigneeButton, fieldSize(12));
            final Calendar[] due = {null};
            Button dueButton = new Button(this);
            dueButton.setText(R.string.task_due_optional);
            styleAction(dueButton, false);
            dueButton.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 12, this));
            Button clearDue = new Button(this);
            clearDue.setText(R.string.task_clear_due);
            styleAction(clearDue, false);
            clearDue.setVisibility(View.GONE);
            clearDue.setOnClickListener(v -> {
                due[0] = null;
                dueButton.setText(R.string.task_due_optional);
                clearDue.setVisibility(View.GONE);
            });
            dueButton.setOnClickListener(v -> pickTaskDue(dueButton, due,
                    () -> clearDue.setVisibility(View.VISIBLE)));
            fields.addView(dueButton, fieldSize(6));
            fields.addView(clearDue, fieldSize(4));
            TextView error = Ui.text(this, "", 13, Ui.MUTED, false);
            collapseWhenEmpty(error);
            fields.addView(error, fieldSize(6));
            ScrollView scroll = new ScrollView(this);
            scroll.addView(fields);
            AlertDialog dialog = new AlertDialog.Builder(this).setTitle(R.string.task_new)
                    .setView(scroll).setPositiveButton(R.string.task_create, null)
                    .setNegativeButton(R.string.chat_v2_cancel, null).create();
            dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                try {
                    String taskTitle = boundedTaskText(title.getText().toString().trim(), 160, true);
                    String taskDescription = boundedTaskText(description.getText().toString(), 4096, false);
                    if (selected[0] == null) throw new IllegalArgumentException();
                    String dueAt = due[0] == null ? null : formatTaskDue(due[0]);
                    if (submitTask(companyId, roomId, selected[0].id,
                            taskTitle, taskDescription, dueAt)) dialog.dismiss();
                    else error.setText(R.string.task_pending_or_save_failed);
                } catch (Exception invalid) { error.setText(R.string.task_invalid); }
            }));
            dialog.show();
            Ui.decorateDialog(dialog);
        }, null);
    }

    private interface TaskChoiceCallback { void selected(TaskChoice choice); }

    private interface ChoiceIndexCallback { void selected(int index); }

    /** A compact, scrollable selection sheet shared by company, task and catalogue pickers. */
    private void showChoiceDialog(String title, String[] labels, String iconKind,
                                  ChoiceIndexCallback callback) {
        showChoiceDialog(title, labels, iconKind, -1, callback);
    }

    private void showChoiceDialog(String title, String[] labels, String iconKind,
                                  int selectedIndex, ChoiceIndexCallback callback) {
        final AccountScope scopedAccount = account;
        if (scopedAccount == null || labels == null || labels.length == 0) return;
        LinearLayout content = Ui.column(this);
        content.setBackgroundColor(Color.WHITE);
        content.setPadding(dp(16), dp(16), dp(16), 0);

        LinearLayout heading = Ui.row(this);
        FrameLayout headingBadge = new FrameLayout(this);
        headingBadge.setBackground(Ui.bg(Ui.LIME, 12, this));
        headingBadge.addView(new Ui.Icon(this, iconKind, Ui.GREEN),
                new FrameLayout.LayoutParams(dp(22), dp(22), Gravity.CENTER));
        heading.addView(headingBadge, new LinearLayout.LayoutParams(dp(40), dp(40)));
        TextView headingText = Ui.text(this, title, 17, Ui.INK, true);
        LinearLayout.LayoutParams headingLabelSize = new LinearLayout.LayoutParams(0, -2, 1);
        headingLabelSize.setMarginStart(dp(12));
        heading.addView(headingText, headingLabelSize);
        content.addView(heading, new LinearLayout.LayoutParams(-1, dp(44)));

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(false);
        scroll.setVerticalScrollBarEnabled(true);
        scroll.setOverScrollMode(View.OVER_SCROLL_NEVER);
        LinearLayout rows = Ui.column(this);
        rows.setPadding(0, dp(8), 0, dp(4));
        scroll.addView(rows, new FrameLayout.LayoutParams(-1, -2));
        int maxListHeight = Math.min(dp(440),
                (int) (getResources().getDisplayMetrics().heightPixels * 0.62f));
        content.addView(scroll, new LinearLayout.LayoutParams(-1,
                Math.min(maxListHeight, dp(12 + labels.length * 68))));

        AlertDialog dialog = new AlertDialog.Builder(this).setView(content)
                .setNegativeButton(R.string.chat_v2_cancel, null).create();
        for (int i = 0; i < labels.length; i++) {
            final int index = i;
            LinearLayout row = Ui.row(this);
            row.setMinimumHeight(dp(56));
            row.setPadding(dp(10), dp(8), dp(10), dp(8));
            boolean selected = i == selectedIndex;
            row.setBackground(selected ? Ui.outline(Ui.LIME, Ui.GREEN, 12, this)
                    : Ui.bg(i % 2 == 0 ? Ui.LIGHT : Color.WHITE, 12, this));
            Ui.clickable(row);
            FrameLayout badge = new FrameLayout(this);
            badge.setBackground(Ui.bg(Ui.LIME, 20, this));
            badge.addView(new Ui.Icon(this, iconKind, Ui.GREEN),
                    new FrameLayout.LayoutParams(dp(18), dp(18), Gravity.CENTER));
            row.addView(badge, new LinearLayout.LayoutParams(dp(34), dp(34)));
            TextView label = Ui.text(this, labels[i], 14, Ui.INK, false);
            label.setMaxLines(3);
            label.setEllipsize(android.text.TextUtils.TruncateAt.END);
            LinearLayout.LayoutParams labelSize = new LinearLayout.LayoutParams(0, -2, 1);
            labelSize.setMarginStart(dp(10));
            row.addView(label, labelSize);
            if (selected) {
                TextView check = Ui.text(this, "✓", 17, Ui.GREEN, true);
                check.setGravity(Gravity.CENTER);
                check.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
                row.addView(check, new LinearLayout.LayoutParams(dp(24), dp(32)));
                row.setContentDescription(getString(R.string.menu_item_selected, labels[i]));
            }
            row.setOnClickListener(v -> {
                dialog.dismiss();
                if (account == scopedAccount && verified) callback.selected(index);
            });
            LinearLayout.LayoutParams rowSize = new LinearLayout.LayoutParams(-1, -2);
            rowSize.bottomMargin = dp(4);
            rows.addView(row, rowSize);
        }
        showSensitiveDetail(dialog, scopedAccount);
    }

    private void chooseTaskAssignee(List<TaskChoice> choices, TaskChoiceCallback callback) {
        String[] names = new String[choices.size()];
        for (int i = 0; i < choices.size(); i++) names[i] = choices.get(i).name;
        showChoiceDialog(getString(R.string.task_choose_assignee), names, "person",
                index -> callback.selected(choices.get(index)));
    }

    private void pickTaskDue(Button button, Calendar[] due, Runnable onSelected) {
        Calendar now = Calendar.getInstance();
        DatePickerDialog date = new DatePickerDialog(this, (picker, year, month, day) -> {
            TimePickerDialog time = new TimePickerDialog(this, (clock, hour, minute) -> {
                Calendar chosen = Calendar.getInstance();
                chosen.set(year, month, day, hour, minute, 0);
                chosen.set(Calendar.MILLISECOND, 0);
                due[0] = chosen;
                button.setText(new SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US).format(chosen.getTime()));
                onSelected.run();
            }, now.get(Calendar.HOUR_OF_DAY), now.get(Calendar.MINUTE), true);
            time.show();
        }, now.get(Calendar.YEAR), now.get(Calendar.MONTH), now.get(Calendar.DAY_OF_MONTH));
        date.show();
    }

    private String formatTaskDue(Calendar calendar) {
        SimpleDateFormat formatter = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        formatter.setTimeZone(TimeZone.getTimeZone("UTC"));
        return formatter.format(calendar.getTime());
    }

    private String displayTaskDue(String utc) {
        if (utc == null) return getString(R.string.task_no_due);
        try {
            SimpleDateFormat parser = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
            parser.setLenient(false);
            parser.setTimeZone(TimeZone.getTimeZone("UTC"));
            Date date = parser.parse(utc);
            if (date == null) return utc;
            SimpleDateFormat local = new SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US);
            return local.format(date);
        } catch (Exception invalid) { return utc; }
    }

    private static final class PendingTaskCreate {
        final String scope, raw, uuid, title, description, dueAt;
        final long companyId, roomId, assigneeId;
        PendingTaskCreate(AccountScope account, String raw) throws Exception {
            if (account == null || raw == null || raw.length() > 12000) throw new IllegalArgumentException();
            JSONObject payload = new JSONObject(raw);
            if (payload.length() != 8 || positiveId(payload.get("api_version")) != 2)
                throw new IllegalArgumentException();
            scope = account.key;
            this.raw = raw;
            uuid = payload.getString("client_uuid");
            if (!UUID.fromString(uuid).toString().equals(uuid) || UUID.fromString(uuid).version() != 4)
                throw new IllegalArgumentException();
            companyId = positiveId(payload.get("company_id"));
            Object room = payload.get("room_id");
            roomId = room == JSONObject.NULL ? 0 : positiveId(room);
            assigneeId = positiveId(payload.get("assignee_id"));
            title = boundedTaskText(payload.getString("title"), 160, true);
            description = boundedTaskText(payload.getString("description"), 4096, false);
            Object due = payload.get("due_at");
            dueAt = due == JSONObject.NULL ? null : taskDate(due);
        }
    }

    private boolean hasPendingTaskCreate() {
        return account != null && taskCreatePreferences().contains(account.key);
    }

    private void updatePendingTaskUi() {
        boolean pending = hasPendingTaskCreate();
        if (taskPendingButton != null) taskPendingButton.setVisibility(pending ? View.VISIBLE : View.GONE);
        if (taskNewButton != null) taskNewButton.setEnabled(!pending && !v2Busy);
    }

    private boolean submitTask(long companyId, long roomId, long assigneeId,
                               String title, String description, String dueAt) {
        if (v2Busy || !verified || account == null || hasPendingTaskCreate()) return false;
        try {
            JSONObject payload = new JSONObject();
            payload.put("api_version", 2);
            payload.put("company_id", companyId);
            payload.put("room_id", roomId > 0 ? roomId : JSONObject.NULL);
            payload.put("client_uuid", UUID.randomUUID().toString());
            payload.put("title", title);
            payload.put("description", description);
            payload.put("due_at", dueAt == null ? JSONObject.NULL : dueAt);
            payload.put("assignee_id", assigneeId);
            PendingTaskCreate pending = new PendingTaskCreate(account, payload.toString());
            // Synchronous private-store commit is the write-ahead boundary before network I/O.
            if (!taskCreatePreferences().edit().putString(account.key, pending.raw).commit()) return false;
            updatePendingTaskUi();
            sendPendingTaskCreate(pending);
            return true;
        } catch (Exception invalid) { return false; }
    }

    private void sendPendingTaskCreate(PendingTaskCreate pending) {
        if (v2Busy || !verified || account == null || !account.key.equals(pending.scope)
                || !pending.raw.equals(taskCreatePreferences().getString(pending.scope, null))) return;
        taskNotice.setText(R.string.task_saving);
        taskPendingButton.setEnabled(false);
        fetchV2("POST", V2_TASKS, pending.raw, (statusCode, result) -> {
            taskPendingButton.setEnabled(true);
            if (handleV2TransportFailure(statusCode, true)) return;
            try {
                if (statusCode != 200 || result == null || positiveId(result.get("api_version")) != 2
                        || !(result.get("replayed") instanceof Boolean)
                        || !pending.uuid.equals(result.getString("client_uuid")))
                    throw new IllegalArgumentException();
                boolean replayed = result.getBoolean("replayed");
                Task created = new Task(result.getJSONObject("task"));
                if (created.companyId != pending.companyId || created.roomId != pending.roomId
                        || created.creatorId != account.userId) throw new IllegalArgumentException();
                if (!replayed && (created.assigneeId != pending.assigneeId
                        || !pending.title.equals(created.title)
                        || !pending.description.equals(created.description)
                        || !(pending.dueAt == null ? created.dueAt == null
                                : pending.dueAt.equals(created.dueAt)))) throw new IllegalArgumentException();
                if (!pending.raw.equals(taskCreatePreferences().getString(pending.scope, null))
                        || !taskCreatePreferences().edit().remove(pending.scope).commit())
                    throw new IllegalArgumentException();
                updatePendingTaskUi();
                taskNotice.setText(replayed ? R.string.task_confirmed : R.string.task_created);
                if ("tasks".equals(visibleSection)) loadTasks(0);
            } catch (Exception invalid) {
                updatePendingTaskUi();
                taskNotice.setText(R.string.task_create_uncertain);
            }
        });
    }

    private void reviewPendingTaskCreate() {
        if (!hasPendingTaskCreate() || account == null) return;
        if (v2Busy) { taskNotice.setText(R.string.task_saving); return; }
        AccountScope scopedAccount = account;
        String raw = taskCreatePreferences().getString(scopedAccount.key, null);
        try {
            PendingTaskCreate pending = new PendingTaskCreate(scopedAccount, raw);
            new AlertDialog.Builder(this).setTitle(R.string.task_review_pending)
                    .setMessage(getString(R.string.task_pending_detail, pending.title,
                            taskCompanyName(pending.companyId),
                            pending.description.isEmpty() ? getString(R.string.task_no_description)
                                    : pending.description,
                            displayTaskDue(pending.dueAt),
                            String.valueOf(pending.assigneeId)))
                    .setPositiveButton(R.string.task_retry_same, (dialog, which) ->
                            sendPendingTaskCreate(pending))
                    .setNeutralButton(R.string.task_delete_local, (dialog, which) ->
                            confirmDiscardPendingTask(scopedAccount, raw))
                    .setNegativeButton(R.string.task_close, null).show();
        } catch (Exception invalid) {
            new AlertDialog.Builder(this).setTitle(R.string.task_review_pending)
                    .setMessage(R.string.task_pending_unreadable)
                    .setPositiveButton(R.string.task_delete_local, (dialog, which) ->
                            confirmDiscardPendingTask(scopedAccount, raw))
                    .setNegativeButton(R.string.task_close, null).show();
        }
    }

    private void confirmDiscardPendingTask(AccountScope scopedAccount, String raw) {
        new AlertDialog.Builder(this).setTitle(R.string.task_delete_local)
                .setMessage(R.string.task_delete_warning)
                .setPositiveButton(R.string.task_delete_local, (dialog, which) -> {
                    if (account == null || !account.key.equals(scopedAccount.key)
                            || v2Busy || !taskCreatePreferences().contains(scopedAccount.key)) return;
                    try {
                        String current = taskCreatePreferences().getString(scopedAccount.key, null);
                        if (!(raw == null ? current == null : raw.equals(current))
                                || !taskCreatePreferences().edit().remove(scopedAccount.key).commit())
                            throw new IllegalArgumentException();
                        updatePendingTaskUi();
                        taskNotice.setText(R.string.task_local_deleted);
                        if (tasksAvailable) loadTasks(0);
                    } catch (Exception invalid) { taskNotice.setText(R.string.task_pending_or_save_failed); }
                }).setNegativeButton(R.string.chat_v2_cancel, null).show();
    }

    private void loadTaskDetail(long taskId) {
        if (v2Busy || !tasksAvailable) return;
        final int serial = taskViewSerial;
        final AccountScope scopedAccount = account;
        final long roomFilter = taskRoomFilter;
        taskNotice.setText(R.string.task_loading);
        fetchV2("GET", V2_TASKS + "/" + taskId, null, (statusCode, result) -> {
            if (handleV2TransportFailure(statusCode)) return;
            if (scopedAccount != account || serial != taskViewSerial
                    || roomFilter != taskRoomFilter || !"tasks".equals(visibleSection)) return;
            try {
                if (statusCode != 200 || result == null || positiveId(result.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                Task task = new Task(result.getJSONObject("task"));
                if (task.id != taskId || !v1Companies.contains(task.companyId))
                    throw new IllegalArgumentException();
                if (task.roomId > 0) {
                    loadTaskAssignees(task.companyId, task.roomId,
                            choices -> showTaskActions(task, choices), failedStatus -> {
                                if (failedStatus == 403) {
                                    clearDeniedTaskList();
                                    taskNotice.setText(R.string.task_denied);
                                } else showTaskActions(task, null);
                            });
                } else showTaskActions(task, null);
            } catch (Exception invalid) {
                taskNotice.setText(statusCode == 403 ? R.string.task_denied : R.string.task_load_failed);
                if (statusCode == 403) clearDeniedTaskList();
            }
        });
    }

    private void showTaskActions(Task task, List<TaskChoice> roomMembers) {
        if (!verified || !tasksAvailable || account == null || !"tasks".equals(visibleSection)) return;
        final AccountScope scopedAccount = account;
        taskNotice.setText("");
        List<String> actions = new ArrayList<>();
        List<String> labels = new ArrayList<>();
        boolean active = !"done".equals(task.state) && !"cancelled".equals(task.state);
        if (active && task.assigneeId == account.userId) {
            if ("new".equals(task.state)) { actions.add("start"); labels.add(getString(R.string.task_start)); }
            if ("in_progress".equals(task.state)) { actions.add("done"); labels.add(getString(R.string.task_done)); }
        }
        if (active && task.creatorId == account.userId) {
            actions.add("reassign"); labels.add(getString(R.string.task_reassign));
            actions.add("cancel"); labels.add(getString(R.string.task_cancel));
        }
        if (active && task.roomId > 0 && roomMembers != null) {
            boolean currentMember = false, creatorCanAct = false, assigneeCanAct = false;
            for (TaskChoice member : roomMembers) {
                if (member.id == account.userId) currentMember = true;
                if (member.id == task.creatorId) creatorCanAct = true;
                if (member.id == task.assigneeId) assigneeCanAct = true;
            }
            if (currentMember && (!creatorCanAct || !assigneeCanAct)) {
                actions.add("rescue"); labels.add(getString(R.string.task_rescue));
            }
        }
        String detail = getString(R.string.task_detail, getString(taskStateLabel(task.state)),
                task.creatorName, task.assigneeName, task.description.isEmpty()
                        ? getString(R.string.task_no_description) : task.description,
                displayTaskDue(task.dueAt));
        if (!task.lastNote.trim().isEmpty())
            detail += "\n\n" + getString(R.string.task_last_note, task.lastNote);
        AlertDialog.Builder builder = new AlertDialog.Builder(this).setTitle(task.title).setMessage(detail)
                .setNegativeButton(R.string.task_close, null);
        if (permissionSet.taskManage && !actions.isEmpty())
            builder.setPositiveButton(R.string.task_actions,
                (dialog, which) -> {
                    if (account == scopedAccount && verified) showTaskActionMenu(task, actions, labels);
                });
        showSensitiveDetail(builder.create(), scopedAccount);
    }

    private void showTaskActionMenu(Task task, List<String> actions, List<String> labels) {
        final AccountScope scopedAccount = account;
        showSensitiveDetail(new AlertDialog.Builder(this).setTitle(task.title)
                .setItems(labels.toArray(new String[0]), (dialog, index) -> {
            if (account != scopedAccount || !verified) return;
            String action = actions.get(index);
            if ("reassign".equals(action) || "rescue".equals(action)) {
                showTaskAssignment(task, action);
            } else showTaskNote(task, action, 0, "rescue".equals(action));
        }).setNegativeButton(R.string.chat_v2_cancel, null).create(), scopedAccount);
    }

    private void showTaskAssignment(Task task, String action) {
        loadTaskAssignees(task.companyId, task.roomId, choices -> {
            List<TaskChoice> available = new ArrayList<>();
            for (TaskChoice choice : choices) if (choice.id != task.assigneeId) available.add(choice);
            if (available.isEmpty()) { taskNotice.setText(R.string.task_no_assignees); return; }
            chooseTaskAssignee(available, selected -> {
                showTaskNote(task, action, selected.id, "rescue".equals(action));
            });
        }, null);
    }

    private void showTaskNote(Task task, String action, long assigneeId, boolean required) {
        final AccountScope scopedAccount = account;
        EditText note = new EditText(this);
        note.setHint(required ? R.string.task_rescue_reason : R.string.task_note_optional);
        note.setMinLines(2);
        note.setMaxLines(4);
        note.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
                | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        int title = "cancel".equals(action) ? R.string.task_cancel
                : "done".equals(action) ? R.string.task_done
                : "start".equals(action) ? R.string.task_start
                : "reassign".equals(action) ? R.string.task_reassign : R.string.task_rescue;
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(title)
                .setMessage("cancel".equals(action) ? getString(R.string.task_cancel_confirm) : null)
                .setView(note).setPositiveButton(title, null)
                .setNegativeButton(R.string.chat_v2_cancel, null).create();
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE)
                .setOnClickListener(v -> {
                    try {
                        String text = boundedTaskText(note.getText().toString().trim(), 512, required);
                        dialog.dismiss();
                        if (account == scopedAccount && verified)
                            transitionTask(task, action, assigneeId, text.isEmpty() ? null : text);
                    } catch (Exception invalid) { note.setError(getString(R.string.task_invalid)); }
                }));
        showSensitiveDetail(dialog, scopedAccount);
    }

    private void transitionTask(Task task, String action, long assigneeId, String reason) {
        if (!permissionSet.taskManage || v2Busy || !tasksAvailable) return;
        try {
            JSONObject payload = new JSONObject();
            payload.put("api_version", 2);
            payload.put("client_uuid", UUID.randomUUID().toString());
            payload.put("expected_revision", task.revision);
            payload.put("action", action);
            payload.put("assignee_id", assigneeId > 0 ? assigneeId : JSONObject.NULL);
            payload.put("reason", reason == null ? JSONObject.NULL : reason);
            taskNotice.setText(R.string.task_saving);
            fetchV2("POST", V2_TASKS + "/" + task.id + "/transition", payload.toString(),
                    (statusCode, result) -> {
                if (handleV2TransportFailure(statusCode, true)) return;
                try {
                    if (statusCode != 200 || result == null || positiveId(result.get("api_version")) != 2
                            || !(result.get("replayed") instanceof Boolean)
                            || positiveId(result.get("operation_revision")) != task.revision + 1)
                        throw new IllegalArgumentException();
                    Task changed = new Task(result.getJSONObject("task"));
                    if (changed.id != task.id || changed.companyId != task.companyId
                            || changed.revision < task.revision + 1) throw new IllegalArgumentException();
                    taskNotice.setText(R.string.task_updated);
                    loadTasks(0);
                } catch (Exception invalid) {
                    taskNotice.setText(statusCode == 403 ? R.string.task_denied
                            : statusCode == 409 ? R.string.task_changed : R.string.task_write_uncertain);
                    if (statusCode == 403 || statusCode == 409) loadTasks(0);
                }
            });
        } catch (Exception invalid) { taskNotice.setText(R.string.task_invalid); }
    }

    private static final class OrderImageTarget {
        final String path;
        final ImageView view;
        final int serial;
        OrderImageTarget(String path, ImageView view, int serial) {
            this.path = path;
            this.view = view;
            this.serial = serial;
        }
    }

    private void cancelOrderImageFetch() {
        int previous = orderImageNonce;
        boolean active = orderImageBusy;
        ++orderImageNonce;
        orderImageBusy = false;
        if (orderImagePort != null) {
            orderImagePort.close();
            orderImagePort = null;
        }
        if (active && web != null && web.getUrl() != null
                && isBridgeUrl(Uri.parse(web.getUrl())))
            web.evaluateJavascript("(function(){if(window.__bchatOrderImageCancel)"
                    + "window.__bchatOrderImageCancel(" + previous + ");})();", null);
    }

    private void resetOrderImages(boolean clearCache) {
        cancelOrderImageFetch();
        for (OrderImageTarget target : orderImageTargets)
            target.view.setImageDrawable(null);
        orderImageTargets.clear();
        if (clearCache) {
            orderImageCache.evictAll();
            orderImageFailedKeys.clear();
        }
    }

    private void scheduleOrderImagePump() {
        if (orderImagePumpScheduled) return;
        orderImagePumpScheduled = true;
        handler.post(() -> {
            orderImagePumpScheduled = false;
            pumpVisibleOrderImages();
        });
    }

    private void pumpVisibleOrderImages() {
        if (closed || !verified || account == null || web == null
                || !ordersAvailable || orderMine || orderReceiving || !"orders".equals(visibleSection)
                || orderCompanyId == 0 || orderScroll == null || !orderScroll.isShown()) return;
        Rect visible = new Rect();
        // Always release every off-screen drawable before starting another fetch.
        for (OrderImageTarget target : orderImageTargets) {
            boolean onScreen = target.serial == orderViewSerial && target.view.isShown()
                    && target.view.getGlobalVisibleRect(visible) && visible.height() >= dp(12);
            if (!onScreen && target.view.getDrawable() != null)
                target.view.setImageDrawable(null);
        }
        if (v2Busy || orderImageBusy) return;
        for (OrderImageTarget target : orderImageTargets) {
            boolean onScreen = target.serial == orderViewSerial && target.view.isShown()
                    && target.view.getGlobalVisibleRect(visible) && visible.height() >= dp(12);
            if (!onScreen) continue;
            Bitmap cached = orderImageCache.get(target.path);
            if (cached != null) {
                if (target.view.getDrawable() == null) target.view.setImageBitmap(cached);
                continue;
            }
            if (!orderImageFailedKeys.contains(target.path)) {
                fetchOrderImage(target);
                return;
            }
        }
    }

    private static boolean validOrderImageSignature(String mime, byte[] bytes) {
        if ("image/png".equals(mime))
            return bytes.length >= 8 && (bytes[0] & 255) == 137
                    && bytes[1] == 80 && bytes[2] == 78 && bytes[3] == 71
                    && bytes[4] == 13 && bytes[5] == 10 && bytes[6] == 26 && bytes[7] == 10;
        if ("image/jpeg".equals(mime))
            return bytes.length >= 4 && (bytes[0] & 255) == 255
                    && (bytes[1] & 255) == 216 && (bytes[2] & 255) == 255;
        return "image/webp".equals(mime) && bytes.length >= 12
                && bytes[0] == 82 && bytes[1] == 73 && bytes[2] == 70 && bytes[3] == 70
                && bytes[8] == 87 && bytes[9] == 69 && bytes[10] == 66 && bytes[11] == 80;
    }

    private static Bitmap decodeOrderThumbnail(String mime, String encoded) {
        if (encoded == null || encoded.length() > 174764
                || (encoded.length() & 3) != 0
                || !encoded.matches("[A-Za-z0-9+/]*={0,2}"))
            return null;
        byte[] bytes;
        try { bytes = Base64.decode(encoded, Base64.NO_WRAP); }
        catch (Exception invalid) { return null; }
        if (bytes.length == 0 || bytes.length > MAX_ORDER_IMAGE_BYTES
                || !validOrderImageSignature(mime, bytes)) return null;
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(bytes, 0, bytes.length, options);
        if (options.outWidth <= 0 || options.outHeight <= 0
                || options.outWidth > 2048 || options.outHeight > 2048
                || (long) options.outWidth * options.outHeight > 2000000L) return null;
        options.inJustDecodeBounds = false;
        options.inSampleSize = 1;
        while (options.outWidth / options.inSampleSize > 256
                || options.outHeight / options.inSampleSize > 256)
            options.inSampleSize *= 2;
        try { return BitmapFactory.decodeByteArray(bytes, 0, bytes.length, options); }
        catch (OutOfMemoryError invalid) { return null; }
    }

    private void fetchOrderImage(OrderImageTarget target) {
        if (web == null || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl()))
                || !target.path.matches("/bchat/api/v2/orders/image/[1-9][0-9]*\\?company_id="
                        + orderCompanyId)) return;
        orderImageBusy = true;
        final int request = ++orderImageNonce;
        final AccountScope scopedAccount = account;
        final int currentWeb = webEpoch, currentPage = pageEpoch, serial = orderViewSerial;
        final String path = target.path;
        WebMessagePort[] channel = web.createWebMessageChannel();
        orderImagePort = channel[0];
        orderImagePort.setWebMessageCallback(new WebMessagePort.WebMessageCallback() {
            @Override public void onMessage(WebMessagePort port, WebMessage message) {
                if (closed || !orderImageBusy || request != orderImageNonce
                        || port != orderImagePort || scopedAccount != account
                        || currentWeb != webEpoch || currentPage != pageEpoch || serial != orderViewSerial
                        || !"orders".equals(visibleSection) || web == null
                        || web.getUrl() == null || !isBridgeUrl(Uri.parse(web.getUrl()))) return;
                int statusCode = 0;
                Bitmap bitmap = null;
                try {
                    String raw = message.getData();
                    if (raw == null || raw.length() > 180000) throw new IllegalArgumentException();
                    JSONObject response = new JSONObject(raw);
                    if (response.getInt("nonce") != request
                            || !(ORIGIN + path).equals(response.getString("url")))
                        throw new IllegalArgumentException();
                    statusCode = response.getInt("status");
                    if (statusCode == 200) {
                        String mime = response.getString("type").toLowerCase(Locale.ROOT)
                                .split(";", 2)[0].trim();
                        bitmap = decodeOrderThumbnail(mime, response.getString("body"));
                    }
                } catch (Exception invalid) { statusCode = 0; }
                orderImagePort.close();
                orderImagePort = null;
                orderImageBusy = false;
                if (statusCode == 401) { logout(); return; }
                if (bitmap == null) orderImageFailedKeys.add(path);
                else orderImageCache.put(path, bitmap);
                scheduleOrderImagePump();
            }
        });
        String script = "(function(){"
                + "if(window.__bchatOrderImageHandler)return;"
                + "window.__bchatOrderImageCancel=function(n){var a=window.__bchatOrderImageActive;"
                + "if(a&&a.nonce===n){a.controller.abort();window.__bchatOrderImageActive=null;}};"
                + "window.__bchatOrderImageHandler=function(e){"
                + "var prefix='bchat-order-image:',s=e.data;"
                + "if(typeof s!=='string'||s.slice(0,prefix.length)!==prefix)return;"
                + "var p=e.ports&&e.ports[0],v=s.slice(prefix.length),i=v.indexOf(':');"
                + "if(!p||i<1)return;var n=Number(v.slice(0,i)),path=v.slice(i+1);"
                + "if(!Number.isSafeInteger(n)||n<1||"
                + "!/^\\/bchat\\/api\\/v2\\/orders\\/image\\/[1-9][0-9]*\\?company_id=[1-9][0-9]*$/.test(path)"
                + "||location.href!==" + JSONObject.quote(BRIDGE)
                + "){p.postMessage('{}');return;}"
                + "var c=new AbortController();window.__bchatOrderImageActive={nonce:n,controller:c};"
                + "var u=new URL(path,location.origin);"
                + "fetch(u.href,{credentials:'same-origin',redirect:'manual',cache:'no-store',"
                + "headers:{Accept:'image/png,image/jpeg,image/webp'},signal:c.signal})"
                + ".then(function(r){if(r.type==='opaqueredirect')"
                + "return {nonce:n,status:401,type:'',url:u.href,body:''};"
                + "var t=(r.headers.get('content-type')||'').toLowerCase().split(';')[0].trim();"
                + "if(r.status!==200||!['image/png','image/jpeg','image/webp'].includes(t)"
                + "||r.url!==u.href||!r.body||!r.body.getReader)"
                + "return {nonce:n,status:r.status,type:t,url:r.url,body:''};"
                + "var rd=r.body.getReader(),parts=[],size=0;"
                + "function read(){return rd.read().then(function(x){"
                + "if(x.done){var all=new Uint8Array(size),at=0;"
                + "parts.forEach(function(a){all.set(a,at);at+=a.length;});"
                + "var b='';for(var j=0;j<all.length;j+=8192)"
                + "b+=String.fromCharCode.apply(null,all.subarray(j,j+8192));"
                + "return {nonce:n,status:r.status,type:t,url:r.url,body:btoa(b)};}"
                + "size+=x.value.byteLength;if(size>" + MAX_ORDER_IMAGE_BYTES
                + "){rd.cancel();throw Error('size');}parts.push(x.value);return read();});}"
                + "return read();})"
                + ".then(function(x){p.postMessage(JSON.stringify(x));})"
                + ".catch(function(){p.postMessage(JSON.stringify({nonce:n,status:0,url:u.href}));})"
                + ".finally(function(){var a=window.__bchatOrderImageActive;"
                + "if(a&&a.nonce===n)window.__bchatOrderImageActive=null;});};"
                + "window.addEventListener('message',window.__bchatOrderImageHandler);})();";
        web.evaluateJavascript(script, ignored -> {
            if (closed || !orderImageBusy || request != orderImageNonce || web == null
                    || scopedAccount != account || currentWeb != webEpoch || currentPage != pageEpoch
                    || serial != orderViewSerial || web.getUrl() == null
                    || !isBridgeUrl(Uri.parse(web.getUrl()))) return;
            web.postWebMessage(new WebMessage("bchat-order-image:" + request + ":" + path,
                    new WebMessagePort[]{channel[1]}), Uri.parse(ORIGIN));
        });
        handler.postDelayed(() -> {
            if (orderImageBusy && request == orderImageNonce) {
                orderImageFailedKeys.add(path);
                cancelOrderImageFetch();
                scheduleOrderImagePump();
            }
        }, 8000);
    }

    private static final class OrderOption {
        final long id, productId, categoryId;
        final String product, option, uom, packaging, category, lastPrice, currency, imagePath;
        OrderOption(JSONObject item, long companyId) throws Exception {
            id = positiveId(item.get("id"));
            productId = positiveId(item.get("product_id"));
            product = boundedTaskText(item.getString("product_name"), 256, true);
            option = boundedTaskText(item.getString("option_name"), 256, true);
            uom = boundedTaskText(item.getString("uom_name"), 128, true);
            Object packageValue = item.opt("packaging_note");
            packaging = packageValue == null || packageValue == JSONObject.NULL ? ""
                    : boundedTaskText(item.getString("packaging_note"), 160, false);
            categoryId = positiveId(item.get("category_id"));
            category = boundedTaskText(item.getString("category_name"), 256, true);
            Object price = item.opt("last_price");
            lastPrice = price == null || price == JSONObject.NULL ? null : price.toString();
            if (lastPrice != null && !lastPrice.matches("[0-9]{1,12}(\\.[0-9]{1,2})?"))
                throw new IllegalArgumentException();
            currency = boundedTaskText(item.optString("currency_symbol", ""), 16, false);
            Object image = item.opt("image_url");
            if (image != null && image != JSONObject.NULL
                    && (!(image instanceof String) || ((String) image).length() > 1024))
                throw new IllegalArgumentException();
            String expected = "/bchat/api/v2/orders/image/" + productId
                    + "?company_id=" + companyId;
            imagePath = expected.equals(image) ? expected : null;
        }
    }

    private static final class OrderCartLine {
        final OrderOption option;
        final String quantity;
        OrderCartLine(OrderOption option, String quantity) {
            this.option = option;
            this.quantity = quantity;
        }
    }

    private static final class OrderSummary {
        final long id, representativeId, roomId, companyId, requesterId;
        final String name, state, representative, purchaseRoute, total, currency, submittedAt,
                companyName, requesterName;
        OrderSummary(JSONObject item) throws Exception { this(item, false); }
        OrderSummary(JSONObject item, boolean allScope) throws Exception {
            id = positiveId(item.get("id"));
            companyId = allScope ? positiveId(item.get("company_id")) : 0;
            requesterId = allScope ? positiveId(item.get("requester_id")) : 0;
            companyName = allScope ? boundedTaskText(item.getString("company_name"), 256, true) : "";
            requesterName = allScope ? boundedTaskText(item.getString("requester_name"), 256, true) : "";
            name = boundedTaskText(item.getString("name"), 160, true);
            state = boundedTaskText(item.getString("state"), 40, true);
            if (!("draft".equals(state) || "sent".equals(state) || "received".equals(state)
                    || "purchased".equals(state) || "cancel".equals(state)))
                throw new IllegalArgumentException();
            representative = boundedTaskText(item.optString("representative_name", ""), 256, false);
            purchaseRoute = item.optString("purchase_route", "representative");
            if (!("representative".equals(purchaseRoute) || "cash".equals(purchaseRoute)
                    || "bank_transfer".equals(purchaseRoute))) throw new IllegalArgumentException();
            Object repId = item.opt("representative_id");
            representativeId = repId == null || repId == JSONObject.NULL ? 0 : positiveId(repId);
            Object rawRoom = item.opt("room_id");
            roomId = rawRoom == null || rawRoom == JSONObject.NULL ? 0 : positiveId(rawRoom);
            Object rawTotal = item.opt("requested_total");
            total = rawTotal == null || rawTotal == JSONObject.NULL ? "" : rawTotal.toString();
            if (!total.isEmpty() && !total.matches("[0-9]{1,14}(\\.[0-9]{1,2})?"))
                throw new IllegalArgumentException();
            currency = boundedTaskText(item.optString("currency_symbol", ""), 16, false);
            Object time = item.opt("submitted_at");
            submittedAt = time == null || time == JSONObject.NULL ? ""
                    : boundedTaskText(item.getString("submitted_at"), 40, false);
        }
    }

    private static final class ReceiptSummary {
        final long id, companyId;
        final String name, state, requester, warehouse, submittedAt, total, currency;
        ReceiptSummary(JSONObject item) throws Exception {
            id = positiveId(item.get("id"));
            companyId = positiveId(item.get("company_id"));
            name = boundedTaskText(item.getString("name"), 160, true);
            state = boundedTaskText(item.getString("state"), 40, true);
            if (!"sent".equals(state) && !"received".equals(state))
                throw new IllegalArgumentException();
            requester = boundedTaskText(item.getString("requester_name"), 256, true);
            warehouse = boundedTaskText(item.getString("warehouse_name"), 256, true);
            submittedAt = boundedTaskText(item.optString("submitted_at", ""), 40, false);
            total = boundedTaskText(item.optString("requested_total", ""), 32, false);
            if (!total.isEmpty() && !total.matches("[0-9]{1,14}(\\.[0-9]{1,2})?"))
                throw new IllegalArgumentException();
            currency = boundedTaskText(item.optString("currency_symbol", ""), 16, false);
        }
    }

    private static final class ReceiptLine {
        final long id;
        final String product, option, uom, requestedQty, managerQty;
        ReceiptLine(JSONObject item) throws Exception {
            id = positiveId(item.get("line_id"));
            product = boundedTaskText(item.getString("product_name"), 256, true);
            option = boundedTaskText(item.getString("option_name"), 256, false);
            uom = boundedTaskText(item.getString("uom_name"), 128, true);
            requestedQty = boundedTaskText(item.getString("requested_qty"), 24, true);
            if (!requestedQty.matches("[0-9]{1,14}(\\.[0-9]{1,2})?"))
                throw new IllegalArgumentException();
            Object manager = item.opt("manager_received_qty");
            managerQty = manager == null || manager == JSONObject.NULL ? "" :
                    boundedTaskText(manager.toString(), 24, false);
            if (!managerQty.isEmpty() && !managerQty.matches("[0-9]{1,14}(\\.[0-9]{1,2})?"))
                throw new IllegalArgumentException();
        }
    }

    private static final class ReceiptInputLine {
        final ReceiptLine line;
        final EditText quantity, price;
        ReceiptInputLine(ReceiptLine line, EditText quantity, EditText price) {
            this.line = line;
            this.quantity = quantity;
            this.price = price;
        }
    }

    private static final class PreviousOrderLine {
        final long id, optionId;
        final String product, option, quantity;
        PreviousOrderLine(JSONObject item) throws Exception {
            id = positiveId(item.get("line_id"));
            optionId = positiveId(item.get("option_id"));
            product = boundedTaskText(item.getString("product_name"), 256, true);
            option = boundedTaskText(item.getString("option_name"), 256, true);
            quantity = boundedTaskText(item.getString("requested_qty"), 24, true);
            if (!quantity.matches("[0-9]{1,14}(\\.[0-9]{1,2})?"))
                throw new IllegalArgumentException();
        }
    }

    private interface OrderChoiceCallback { void selected(TaskChoice choice); }

    private void chooseOrderChoice(List<TaskChoice> options, int title, OrderChoiceCallback callback) {
        if (options.isEmpty()) { orderNotice.setText(R.string.order_no_options); return; }
        String[] names = new String[options.size()];
        for (int i = 0; i < options.size(); i++) names[i] = options.get(i).name;
        long selectedId = title == R.string.order_choose_company ? orderCompanyId
                : title == R.string.order_choose_warehouse ? orderWarehouseId
                : title == R.string.order_choose_representative ? orderRepresentativeId
                : title == R.string.order_category ? orderCategoryId : -1;
        int selectedIndex = -1;
        for (int i = 0; i < options.size(); i++)
            if (options.get(i).id == selectedId) { selectedIndex = i; break; }
        showChoiceDialog(getString(title), names, "company", selectedIndex,
                index -> callback.selected(options.get(index)));
    }

    private String orderChoiceName(List<TaskChoice> choices, long id, int fallback) {
        for (TaskChoice choice : choices) if (choice.id == id) return choice.name;
        return getString(fallback);
    }

    private String orderCartFingerprint() {
        StringBuilder fingerprint = new StringBuilder();
        for (OrderCartLine line : orderCart.values())
            fingerprint.append(line.option.id).append(':').append(line.quantity).append(';');
        return fingerprint.toString();
    }

    private String orderQuoteLabel() {
        if (orderCart.isEmpty()) return getString(R.string.order_empty_cart);
        if (orderQuoteTotal != null)
            return getString(R.string.order_estimated_total, orderQuoteTotal, orderQuoteCurrency);
        return getString(orderQuoteLoading ? R.string.order_total_loading
                : R.string.order_total_unavailable);
    }

    private void refreshOrderQuoteLabels() {
        if (orderCartSummary != null) {
            String menuTotal = orderQuoteTotal == null ? orderQuoteLabel()
                    : getString(R.string.order_quote_short, orderQuoteTotal, orderQuoteCurrency);
            orderCartSummary.setText(orderCart.isEmpty()
                    ? getString(R.string.order_cart_count, "0")
                    : getString(R.string.order_cart_bar,
                            String.valueOf(orderCart.size()), menuTotal));
        }
        if (orderCartTotalView != null) orderCartTotalView.setText(orderQuoteLabel());
    }

    private void invalidateOrderQuote() {
        if (orderCartRevision == Integer.MAX_VALUE) orderCartRevision = 1;
        else ++orderCartRevision;
        orderQuoteTotal = orderQuoteCurrency = null;
        orderQuoteLoading = !orderCart.isEmpty();
        refreshOrderQuoteLabels();
        scheduleOrderQuote();
    }

    private void scheduleOrderQuote() {
        if (orderQuoteTask != null) handler.removeCallbacks(orderQuoteTask);
        orderQuoteTask = null;
        if (!verified || !ordersAvailable || orderMine || orderReceiving || orderCart.isEmpty()
                || orderCompanyId == 0 || orderWarehouseId == 0
                || !"orders".equals(visibleSection) || hasPendingOrder()) {
            if (orderQuoteLoading && (orderCompanyId == 0 || orderWarehouseId == 0)) {
                orderQuoteLoading = false;
                refreshOrderQuoteLabels();
            }
            return;
        }
        orderQuoteTask = () -> { orderQuoteTask = null; requestOrderQuote(); };
        handler.postDelayed(orderQuoteTask, 350);
    }

    private void requestOrderQuote() {
        if (!verified || orderMine || orderReceiving || orderCart.isEmpty() || hasPendingOrder()
                || !"orders".equals(visibleSection)) return;
        if (v2Busy) { scheduleOrderQuote(); return; }
        final AccountScope scopedAccount = account;
        final long companyId = orderCompanyId, warehouseId = orderWarehouseId;
        final int revision = orderCartRevision, viewSerial = orderViewSerial;
        final String fingerprint = orderCartFingerprint();
        try {
            JSONArray lines = new JSONArray();
            for (OrderCartLine cartLine : orderCart.values()) {
                JSONObject line = new JSONObject();
                line.put("option_id", cartLine.option.id);
                line.put("quantity", normalizeOrderQuantity(cartLine.quantity));
                lines.put(line);
            }
            JSONObject payload = new JSONObject();
            payload.put("api_version", 2);
            payload.put("company_id", companyId);
            payload.put("warehouse_id", warehouseId);
            payload.put("cart_revision", revision);
            payload.put("lines", lines);
            fetchV2("POST", V2_ORDERS + "/quote", payload.toString(), (status, body) -> {
                if (status == 401) { logout(); return; }
                if (scopedAccount != account || companyId != orderCompanyId
                        || warehouseId != orderWarehouseId || revision != orderCartRevision
                        || viewSerial != orderViewSerial || orderMine || orderReceiving
                        || !"orders".equals(visibleSection)
                        || !fingerprint.equals(orderCartFingerprint())) return;
                if (status == 403) { recoverOrderCompanyAccess(companyId); return; }
                orderQuoteLoading = false;
                orderQuoteTotal = orderQuoteCurrency = null;
                try {
                    if (status != 200 || body == null
                            || positiveId(body.get("api_version")) != 2
                            || positiveId(body.get("company_id")) != companyId
                            || positiveId(body.get("cart_revision")) != revision)
                        throw new IllegalArgumentException();
                    JSONArray priced = body.getJSONArray("lines");
                    if (priced.length() != lines.length()) throw new IllegalArgumentException();
                    Set<Long> seen = new HashSet<>();
                    for (int i = 0; i < priced.length(); i++) {
                        JSONObject pricedLine = priced.getJSONObject(i);
                        long id = positiveId(pricedLine.get("option_id"));
                        OrderCartLine local = orderCart.get(id);
                        if (local == null || !seen.add(id)
                                || new BigDecimal(local.quantity).compareTo(
                                        new BigDecimal(pricedLine.getString("quantity"))) != 0
                                || !pricedLine.getString("unit_price").matches("[0-9]{1,14}\\.[0-9]{2}")
                                || !pricedLine.getString("line_total").matches("[0-9]{1,14}\\.[0-9]{2}"))
                            throw new IllegalArgumentException();
                    }
                    String total = body.getString("estimated_total");
                    String code = body.getString("currency_code");
                    String symbol = body.getString("currency_symbol");
                    if (!total.matches("[0-9]{1,14}\\.[0-9]{2}")
                            || !code.matches("[A-Z]{3}") || symbol.length() > 16)
                        throw new IllegalArgumentException();
                    orderQuoteTotal = total;
                    orderQuoteCurrency = symbol.isEmpty() ? code : symbol;
                } catch (Exception invalid) {
                    // A failed or partial quote must never become a client-side estimate.
                }
                refreshOrderQuoteLabels();
            });
        } catch (Exception invalid) {
            orderQuoteLoading = false;
            refreshOrderQuoteLabels();
        }
    }

    private void updateOrderSelectors() {
        boolean companyChoice = orderCompanies.size() > 1;
        String companyName = companyNameForId(orderCompanyId,
                orderChoiceName(orderCompanies, orderCompanyId, R.string.order_choose_company));
        orderHeaderCompanyButton.setText(companyName + (companyChoice ? " ⌄" : ""));
        orderHeaderCompanyButton.setContentDescription(companyName);
        orderHeaderCompanyButton.setEnabled(companyChoice);
        orderHeaderCompanyButton.setVisibility((orderCanCreate || orderCanReceive) && !orderCompanies.isEmpty()
                && "orders".equals(visibleSection) ? View.VISIBLE : View.GONE);
        orderWarehouseButton.setText(orderChoiceName(orderWarehouses, orderWarehouseId,
                R.string.order_choose_warehouse));
        boolean warehouseChoice = orderCompanyId > 0 && orderWarehouses.size() > 1;
        orderWarehouseButton.setVisibility(warehouseChoice ? View.VISIBLE : View.GONE);
        orderRepresentativeButton.setText(orderRepresentatives.size() == 1
                ? getString(R.string.order_auto_representative, orderRepresentatives.get(0).name)
                : orderChoiceName(orderRepresentatives, orderRepresentativeId,
                        R.string.order_choose_representative));
        boolean representativeChoice = orderCompanyId > 0
                && "representative".equals(orderPurchaseRoute) && orderRepresentatives.size() > 1;
        orderRepresentativeButton.setVisibility(representativeChoice ? View.VISIBLE : View.GONE);
        orderRepresentativeButton.setEnabled(orderRepresentatives.size() > 1);
        orderDetailsButton.setVisibility(warehouseChoice || representativeChoice
                ? View.VISIBLE : View.GONE);
        if (orderDetailsButton.getVisibility() == View.GONE)
            orderDetailsPanel.setVisibility(View.GONE);
        orderDetailsButton.setContentDescription(warehouseChoice && orderWarehouseId == 0
                ? getString(R.string.order_choose_warehouse)
                : representativeChoice && orderRepresentativeId == 0
                ? getString(R.string.order_choose_representative)
                : getString(R.string.order_details));
        refreshOrderCartRoute();
        orderCategoryButton.setText(orderChoiceName(orderCategories, orderCategoryId,
                R.string.order_all_categories));
        orderCategoryButton.setContentDescription(orderChoiceName(orderCategories, orderCategoryId,
                R.string.order_all_categories));
        boolean catalog = !orderMine && !orderReceiving;
        boolean operator = orderCanCreate;
        ((View) orderCatalogButton.getParent()).setVisibility(orderCanCreate ? View.VISIBLE : View.GONE);
        ((View) orderReceiptButton.getParent()).setVisibility(orderCanReceive ? View.VISIBLE : View.GONE);
        Ui.styleSegment(orderCatalogButton, catalog);
        Ui.styleSegment(orderMineButton, orderMine);
        Ui.styleSegment(orderReceiptButton, orderReceiving);
        orderCatalogLine.setBackgroundColor(catalog ? Ui.GREEN : Color.TRANSPARENT);
        orderMineLine.setBackgroundColor(orderMine ? Ui.GREEN : Color.TRANSPARENT);
        orderReceiptLine.setBackgroundColor(orderReceiving ? Ui.GREEN : Color.TRANSPARENT);
        orderFiltersRow.setVisibility(catalog && operator ? View.VISIBLE : View.GONE);
        orderPreviousButton.setVisibility(catalog && !orderPageHistory.isEmpty()
                ? View.VISIBLE : View.GONE);
        orderCartBar.setVisibility(catalog && operator ? View.VISIBLE : View.GONE);
        refreshOrderQuoteLabels();
        orderCartButton.setEnabled(!orderCart.isEmpty() && !hasPendingOrder());
        orderPendingButton.setVisibility(catalog && operator && hasPendingOrder() ? View.VISIBLE : View.GONE);
        receiptPendingButton.setVisibility(orderCanReceive && orderReceiving && hasPendingReceipt()
                ? View.VISIBLE : View.GONE);
        receiptSharePendingButton.setVisibility(orderCanReceive && hasPendingReceiptShare()
                ? View.VISIBLE : View.GONE);
    }

    private void recoverOrderCompanyAccess(long deniedCompanyId) {
        if (!verified || !ordersAvailable || deniedCompanyId != orderCompanyId
                || !"orders".equals(visibleSection)) return;
        boolean firstFailure = deniedOrderCompanyIds.add(deniedCompanyId);
        ++orderViewSerial;
        if (receiptFlowDialog != null) receiptFlowDialog.dismiss();
        if (orderCartDialog != null) orderCartDialog.dismiss();
        resetOrderImages(true);
        finishOrderLoading();
        clearOrderRetry();
        ordersAvailable = false;
        orderCompanyOptionsLoaded = false;
        orderCompanyId = orderWarehouseId = orderRepresentativeId = orderCategoryId = 0;
        orderCompanies.clear();
        orderWarehouses.clear();
        orderRepresentatives.clear();
        orderPurchaseRoutes.clear();
        orderPurchaseRoute = "representative";
        orderCategories.clear();
        orderOptions.clear();
        orderSummaries.clear();
        receiptSummaries.clear();
        orderCart.clear();
        lastRemovedOrderLine = null;
        orderCatalogAfterId = orderListBeforeId = orderCurrentPageStartId = receiptBeforeId = 0;
        orderPageHistory.clear();
        orderRenderedKey = null;
        orderItems.removeAllViews();
        orderOlderButton.setVisibility(View.GONE);
        orderPreviousButton.setVisibility(View.GONE);
        orderCompanyPreferences().edit().remove(ORDER_COMPANY_SELECTED).apply();
        if (orderSearchTask != null) handler.removeCallbacks(orderSearchTask);
        orderSearchTask = null;
        orderSearch.setText("");
        invalidateOrderQuote();
        updateOrderSelectors();
        if (firstFailure) discoverOrders();
        else showOrderLoadError(R.string.order_denied, () -> {
            deniedOrderCompanyIds.clear();
            discoverOrders();
        });
    }

    private void recoverAllOrdersAccess() {
        if (!verified || !orderMine || !"orders".equals(visibleSection)) return;
        ++orderViewSerial;
        finishOrderLoading();
        clearOrderRetry();
        ordersAvailable = false;
        orderSummaries.clear();
        orderListBeforeId = 0;
        orderRenderedKey = null;
        renderOrderSummaries();
        orderOlderButton.setVisibility(View.GONE);
        if (!allOrdersRecoveryAttempted) {
            allOrdersRecoveryAttempted = true;
            discoverOrders();
        } else {
            showOrderLoadError(R.string.order_denied, () -> {
                allOrdersRecoveryAttempted = false;
                discoverOrders();
            });
        }
    }

    private void applyOrderRights(JSONObject options, AccountScope scope) throws Exception {
        String access = options.getString("access");
        if (!"viewer".equals(access) && !"operator".equals(access))
            throw new IllegalArgumentException("Invalid order access");
        boolean hasView = options.has("can_view");
        boolean hasCreate = options.has("can_create");
        boolean hasReceive = options.has("can_receive");
        if ((hasView || hasCreate || hasReceive) && !(hasView && hasCreate && hasReceive))
            throw new IllegalArgumentException("Incomplete order permissions");
        boolean view, create, receive;
        if (hasView) {
            if (!(options.get("can_view") instanceof Boolean)
                    || !(options.get("can_create") instanceof Boolean)
                    || !(options.get("can_receive") instanceof Boolean))
                throw new IllegalArgumentException("Invalid order permissions");
            view = options.getBoolean("can_view");
            create = options.getBoolean("can_create");
            receive = options.getBoolean("can_receive");
        } else {
            String saved = getSharedPreferences(ORDER_PERMISSION_PREFS, MODE_PRIVATE)
                    .getString(scope.key, null);
            if (saved != null) {
                JSONObject old = new JSONObject(saved);
                view = old.getBoolean("can_view");
                create = old.getBoolean("can_create");
                receive = old.getBoolean("can_receive");
            } else {
                view = true;
                create = receive = "operator".equals(access);
            }
        }
        if (!view && (create || receive))
            throw new IllegalArgumentException("Write permission without view");
        if (hasView) {
            JSONObject saved = new JSONObject().put("can_view", view)
                    .put("can_create", create).put("can_receive", receive);
            getSharedPreferences(ORDER_PERMISSION_PREFS, MODE_PRIVATE).edit()
                    .putString(scope.key, saved.toString()).commit();
        }
        if (permissionSet.revision >= 0) {
            view &= permissionSet.orderView;
            create &= permissionSet.orderCreate;
            receive &= permissionSet.orderReceive;
        }
        orderAccess = access;
        setOrderRights(scope, view, create, receive);
    }

    private void setOrderRights(AccountScope scope, boolean view, boolean create,
            boolean receive) {
        boolean lostView = orderCanView && !view;
        orderCanView = view;
        orderCanCreate = view && create;
        orderCanReceive = view && receive;
        boolean modeRevoked = (!orderMine && !orderReceiving && !orderCanCreate)
                || (orderReceiving && !orderCanReceive);
        if (modeRevoked) {
            orderReceiving = !orderMine && orderCanReceive;
            orderMine = !orderReceiving;
            ++orderViewSerial;
            orderRenderedKey = null;
            if (orderItems != null) orderItems.removeAllViews();
        }
        if (!orderCanCreate || lostView) {
            orderCreatePreferences().edit().remove(scope.key).commit();
            orderCart.clear();
            orderOptions.clear();
            invalidateOrderQuote();
            if (orderCartDialog != null) orderCartDialog.dismiss();
        }
        if (!orderCanReceive || lostView) {
            receiptConfirmPreferences().edit().remove(scope.key).commit();
            if (receiptFlowDialog != null) receiptFlowDialog.dismiss();
            SharedPreferences shares = receiptSharePreferences();
            SharedPreferences.Editor edit = shares.edit();
            for (String key : shares.getAll().keySet())
                if (key.startsWith(scope.key + ":")) edit.remove(key);
            edit.commit();
        }
        if (lostView) {
            orderSummaries.clear();
            receiptSummaries.clear();
            orderOptions.clear();
            if (orderItems != null) orderItems.removeAllViews();
            resetOrderImages(true);
            if ("orders".equals(visibleSection)) {
                if (chatAllowed()) showRooms();
                else if (permissionSet.taskView) switchSection("tasks");
                else { showShell(); shellNotice.setText(R.string.order_denied); }
            }
        } else if ("orders".equals(visibleSection)) updateOrderSelectors();
        if (modeRevoked && view && "orders".equals(visibleSection)) {
            orderCapabilityOptions = null;
            orderCapabilityAccount = null;
            handler.post(() -> { if (verified && "orders".equals(visibleSection)) discoverOrders(); });
        }
    }

    private void denyOrdersForSession() {
        if (ordersDenied) return;
        ordersDenied = true;
        ordersAvailable = false;
        orderAccess = "";
        orderCanView = orderCanCreate = orderCanReceive = false;
        ++orderViewSerial;
        if (orderCartDialog != null) orderCartDialog.dismiss();
        if (receiptFlowDialog != null) receiptFlowDialog.dismiss();
        if (orderCompanyMenu != null) orderCompanyMenu.dismiss();
        resetOrderImages(true);
        orderCompanies.clear();
        deniedOrderCompanyIds.clear();
        allOrdersRecoveryAttempted = false;
        orderCompanyOptionsLoaded = false;
        orderWarehouses.clear();
        orderRepresentatives.clear();
        orderPurchaseRoutes.clear();
        orderPurchaseRoute = "representative";
        orderCategories.clear();
        orderOptions.clear();
        orderSummaries.clear();
        receiptSummaries.clear();
        orderCart.clear();
        lastRemovedOrderLine = null;
        orderCompanyId = orderWarehouseId = orderRepresentativeId = orderCategoryId = 0;
        orderCatalogAfterId = orderListBeforeId = orderCurrentPageStartId = receiptBeforeId = 0;
        orderPageHistory.clear();
        orderMine = false;
        orderReceiving = false;
        orderRenderedKey = null;
        finishOrderLoading();
        invalidateOrderQuote();
        orderItems.removeAllViews();
        orderNotice.setText("");
        orderHeaderCompanyButton.setVisibility(View.GONE);
        orderPendingButton.setVisibility(View.GONE);
        receiptPendingButton.setVisibility(View.GONE);
        receiptSharePendingButton.setVisibility(View.GONE);
        if ("orders".equals(visibleSection)) {
            if (chatAllowed()) showRooms();
            else if (permissionSet.taskView) switchSection("tasks");
            else { showShell(); shellNotice.setText(R.string.order_denied); }
        } else renderBottomTabs();
        android.widget.Toast.makeText(this, R.string.order_operator_only,
                android.widget.Toast.LENGTH_LONG).show();
    }

    private void maybeProbeOrderCapability() {
        if (!verified || account == null || offlineHistory) return;
        // The v2 completion callback wakes this probe once the shared channel is free.
        if (v2Busy) return;
        long now = android.os.SystemClock.elapsedRealtime();
        if (lastOrderCapabilityProbeAt > 0
                && now - lastOrderCapabilityProbeAt < 15000) return;
        lastOrderCapabilityProbeAt = now;
        final AccountScope scopedAccount = account;
        fetchV2("GET", V2_ORDERS + "/options", null, (status, body) -> {
            if (scopedAccount != account || !verified) return;
            if (status == 401) { logout(); return; }
            if (status == 403) {
                orderCapabilityOptions = null;
                orderCapabilityAccount = null;
                if (orderCanView || "orders".equals(visibleSection)) denyOrdersForSession();
                else {
                    orderAccess = "";
                    orderCanView = orderCanCreate = orderCanReceive = false;
                    ordersAvailable = false;
                    ordersDenied = true;
                    renderBottomTabs();
                }
                return;
            }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                String access = body.getString("access");
                if (!"viewer".equals(access) && !"operator".equals(access))
                    throw new IllegalArgumentException();
                List<TaskChoice> companies = choices(body.getJSONArray("companies"), 100, true);
                for (TaskChoice choice : companies)
                    if (!v1Companies.contains(choice.id)) throw new IllegalArgumentException();
                orderCapabilityOptions = body;
                orderCapabilityAccount = scopedAccount;
                orderCapabilityOptionsAt = android.os.SystemClock.elapsedRealtime();
                orderCapabilityProbeFailures = 0;
                applyOrderRights(body, scopedAccount);
                ordersDenied = false;
                renderBottomTabs();
                if (!chatAllowed() && !permissionSet.taskView && orderCanView
                        && chatRoot.getVisibility() != View.VISIBLE) {
                    shell.setVisibility(View.GONE);
                    chatRoot.setVisibility(View.VISIBLE);
                    if (loginReleaseFooter != null) loginReleaseFooter.setVisibility(View.GONE);
                    layout.setPadding(0, 0, 0, 0);
                    switchSection("orders");
                }
            } catch (Exception invalid) {
                if (status != 0 && status != 429 && status < 500)
                    return;
                if (orderCapabilityProbeFailures >= 3 || orderCapabilityProbeScheduled) return;
                int backoff = 500 << orderCapabilityProbeFailures++;
                orderCapabilityProbeScheduled = true;
                handler.postDelayed(() -> {
                    orderCapabilityProbeScheduled = false;
                    if (scopedAccount != account || !verified) return;
                    lastOrderCapabilityProbeAt = 0;
                    maybeProbeOrderCapability();
                }, backoff);
            }
        });
    }

    private void discoverOrders() {
        if (!verified || ordersDenied || !"orders".equals(visibleSection)) return;
        final AccountScope scopedAccount = account;
        final int serial = ++orderViewSerial;
        updateOrderSelectors();
        if (v2Busy) {
            beginOrderLoading(serial, R.string.order_loading);
            queueOrderLoadWhenIdle(() -> {
                if (scopedAccount == account && serial == orderViewSerial)
                    discoverOrders();
            });
            return;
        }
        beginOrderLoading(serial, R.string.order_loading);
        V2Callback discovery = (status, body) -> {
            if (handleV2TransportFailure(status)) return;
            if (scopedAccount != account || serial != orderViewSerial
                    || !"orders".equals(visibleSection)) return;
            finishOrderLoading();
            if (status == 403) { denyOrdersForSession(); return; }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                String access = body.getString("access");
                if (!"viewer".equals(access) && !"operator".equals(access))
                    throw new IllegalArgumentException();
                applyOrderRights(body, scopedAccount);
                if (serial != orderViewSerial) return;
                List<TaskChoice> companies = choices(body.getJSONArray("companies"), 100, true);
                companies.sort((first, second) -> Long.compare(first.id, second.id));
                orderCompanies.clear();
                orderCompanies.addAll(companies);
                ordersAvailable = true;
                renderBottomTabs();
                if (!orderCanCreate && !orderCanReceive) {
                    orderMine = true;
                    orderReceiving = false;
                } else if (!orderCanCreate && !orderMine) {
                    orderReceiving = true;
                } else if (!orderCanReceive && orderReceiving) {
                    orderReceiving = false;
                    orderMine = !orderCanCreate;
                }
                if (!orderCanCreate) {
                    orderCompanyOptionsLoaded = false;
                    orderWarehouses.clear();
                    orderRepresentatives.clear();
                    orderPurchaseRoutes.clear();
                    orderPurchaseRoute = "representative";
                    orderCategories.clear();
                    orderOptions.clear();
                    orderCart.clear();
                    invalidateOrderQuote();
                }
                boolean stillAllowed = false;
                for (TaskChoice choice : companies)
                    if (choice.id == orderCompanyId) stillAllowed = true;
                if (!stillAllowed) {
                    orderCompanyId = 0;
                    orderCompanyOptionsLoaded = false;
                    orderCompanyPreferences().edit().remove(ORDER_COMPANY_SELECTED).apply();
                    orderWarehouseId = orderRepresentativeId = orderCategoryId = 0;
                    orderPurchaseRoutes.clear();
                    orderPurchaseRoute = "representative";
                    orderCart.clear();
                    lastRemovedOrderLine = null;
                    invalidateOrderQuote();
                    orderOptions.clear();
                    orderSummaries.clear();
                    receiptSummaries.clear();
                    receiptBeforeId = 0;
                    orderPageHistory.clear();
                    orderCurrentPageStartId = orderCatalogAfterId = 0;
                    orderItems.removeAllViews();
                    resetOrderImages(true);
                    orderRenderedKey = null;
                }
                if (orderCompanyId == 0 && !companies.isEmpty()) {
                    for (TaskChoice choice : companies)
                        if (choice.id == selectedChatCompanyId
                                && !deniedOrderCompanyIds.contains(choice.id))
                            orderCompanyId = choice.id;
                    if (orderCompanyId == 0) for (TaskChoice choice : companies)
                        if (!deniedOrderCompanyIds.contains(choice.id)) {
                            orderCompanyId = choice.id;
                            break;
                        }
                }
                updateOrderSelectors();
                if (orderMine) loadOrderSummaries(0);
                else if (orderCompanyId > 0) {
                    saveOrderCompany(orderCompanyId);
                    if (orderReceiving) loadReceipts(0);
                    else if (orderCompanyOptionsLoaded) loadOrderCatalog(0);
                    else loadOrderCompanyOptions();
                }
                else {
                    orderItems.removeAllViews();
                    orderRenderedKey = null;
                    if (companies.isEmpty()) orderNotice.setText(R.string.order_no_companies);
                    else if (!deniedOrderCompanyIds.isEmpty())
                        showOrderLoadError(R.string.order_denied, () -> {
                            deniedOrderCompanyIds.clear();
                            discoverOrders();
                        });
                    else orderNotice.setText("");
                }
            } catch (Exception invalid) {
                ordersAvailable = false;
                orderItems.removeAllViews();
                orderRenderedKey = null;
                showOrderLoadError(status == 404 || status == 503
                        ? R.string.order_unavailable : R.string.order_load_failed,
                        this::discoverOrders);
            }
        };
        JSONObject cached = orderCapabilityAccount == scopedAccount
                && android.os.SystemClock.elapsedRealtime() - orderCapabilityOptionsAt < 30000
                ? orderCapabilityOptions : null;
        orderCapabilityOptions = null;
        orderCapabilityAccount = null;
        if (cached != null) discovery.complete(200, cached);
        else fetchV2("GET", V2_ORDERS + "/options", null, discovery);
    }

    private void selectOrderCompany(long companyId) {
        boolean allowed = false;
        for (TaskChoice choice : orderCompanies) if (choice.id == companyId) allowed = true;
        if (!verified || !allowed) return;
        if (receiptFlowDialog != null) receiptFlowDialog.dismiss();
        orderDetailsPanel.setVisibility(View.GONE);
        if (orderMine) {
            if (orderCompanyId == companyId) return;
            resetOrderImages(true);
            orderCompanyId = companyId;
            orderCompanyOptionsLoaded = false;
            orderWarehouseId = orderRepresentativeId = orderCategoryId = 0;
            orderCart.clear();
            lastRemovedOrderLine = null;
            invalidateOrderQuote();
            orderOptions.clear();
            receiptSummaries.clear();
            receiptBeforeId = orderCurrentPageStartId = orderCatalogAfterId = 0;
            orderPageHistory.clear();
            orderSearch.setText("");
            if (orderSearchTask != null) handler.removeCallbacks(orderSearchTask);
            orderSearchTask = null;
            saveOrderCompany(companyId);
            updateOrderSelectors();
            return;
        }
        if (orderCompanyId == companyId && orderCompanyOptionsLoaded) return;
        if (orderCompanyId != companyId) {
            resetOrderImages(true);
            orderCompanyId = companyId;
            orderCompanyOptionsLoaded = false;
            orderWarehouseId = orderRepresentativeId = orderCategoryId = 0;
            orderPurchaseRoute = "representative";
            orderPurchaseRoutes.clear();
            orderCart.clear();
            lastRemovedOrderLine = null;
            invalidateOrderQuote();
            orderOptions.clear();
            orderSummaries.clear();
            receiptSummaries.clear();
            orderRenderedKey = null;
            finishOrderLoading();
            receiptBeforeId = 0;
            orderPageHistory.clear();
            orderCurrentPageStartId = orderCatalogAfterId = 0;
            orderSearch.setText("");
            if (orderSearchTask != null) {
                handler.removeCallbacks(orderSearchTask);
                orderSearchTask = null;
            }
            orderItems.removeAllViews();
        }
        saveOrderCompany(companyId);
        ++orderViewSerial;
        updateOrderSelectors();
        if (orderReceiving) loadReceipts(0);
        else loadOrderCompanyOptions();
    }

    private void loadOrderCompanyOptions() {
        if (!verified || orderCompanyId == 0 || !"orders".equals(visibleSection)) return;
        if (v2Busy) {
            final AccountScope scopedAccount = account;
            final int serial = orderViewSerial;
            final long companyId = orderCompanyId;
            queueOrderLoadWhenIdle(() -> {
                if (scopedAccount == account && serial == orderViewSerial
                        && companyId == orderCompanyId && !orderReceiving)
                    loadOrderCompanyOptions();
            });
            return;
        }
        final AccountScope scopedAccount = account;
        final int serial = orderViewSerial;
        final long companyId = orderCompanyId;
        beginOrderLoading(serial, R.string.order_loading);
        fetchV2("GET", V2_ORDERS + "/options?company_id=" + companyId, null, (status, body) -> {
            if (handleV2TransportFailure(status)) return;
            if (scopedAccount != account || serial != orderViewSerial
                    || companyId != orderCompanyId || !"orders".equals(visibleSection)) return;
            finishOrderLoading();
            if (status == 403) { recoverOrderCompanyAccess(companyId); return; }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                List<TaskChoice> warehouses = choices(body.getJSONArray("warehouses"), 100, false);
                List<TaskChoice> representatives = choices(body.getJSONArray("representatives"), 100, false);
                List<TaskChoice> categories = choices(body.getJSONArray("categories"), 100, false);
                List<String> routes = new ArrayList<>();
                JSONArray advertisedRoutes = body.optJSONArray("purchase_routes");
                if (body.has("purchase_routes") && advertisedRoutes == null)
                    throw new IllegalArgumentException();
                if (advertisedRoutes == null) {
                    routes.add("representative"); // Older BChat servers only support this route.
                } else {
                    if (advertisedRoutes.length() < 1 || advertisedRoutes.length() > 3)
                        throw new IllegalArgumentException();
                    for (int i = 0; i < advertisedRoutes.length(); i++) {
                        JSONObject route = advertisedRoutes.getJSONObject(i);
                        if (route.length() != 2 || !route.has("name"))
                            throw new IllegalArgumentException();
                        String code = route.getString("code");
                        boundedTaskText(route.getString("name"), 80, true);
                        if (!("representative".equals(code) || "cash".equals(code)
                                || "bank_transfer".equals(code)) || routes.contains(code))
                            throw new IllegalArgumentException();
                        routes.add(code);
                    }
                }
                orderCompanyOptionsLoaded = true;
                orderWarehouses.clear();
                orderWarehouses.addAll(warehouses);
                orderRepresentatives.clear();
                orderRepresentatives.addAll(representatives);
                orderPurchaseRoutes.clear();
                orderPurchaseRoutes.addAll(routes);
                if (!orderPurchaseRoutes.contains(orderPurchaseRoute)) {
                    orderPurchaseRoute = orderPurchaseRoutes.contains("representative")
                            ? "representative" : orderPurchaseRoutes.get(0);
                    orderRepresentativeId = 0;
                }
                orderCategories.clear();
                orderCategories.addAll(categories);
                boolean warehouseValid = false, representativeValid = false, categoryValid = false;
                for (TaskChoice choice : warehouses) if (choice.id == orderWarehouseId) warehouseValid = true;
                for (TaskChoice choice : representatives)
                    if (choice.id == orderRepresentativeId) representativeValid = true;
                for (TaskChoice choice : categories) if (choice.id == orderCategoryId) categoryValid = true;
                if (!warehouseValid) orderWarehouseId = warehouses.size() == 1 ? warehouses.get(0).id : 0;
                if (!warehouseValid) invalidateOrderQuote();
                if (!representativeValid) orderRepresentativeId = 0;
                if (!categoryValid) orderCategoryId = 0;
                updateOrderSelectors();
                if (!orderCart.isEmpty() && orderQuoteTotal == null) scheduleOrderQuote();
                if (warehouses.isEmpty()) orderNotice.setText(R.string.order_no_warehouse);
                else if ("representative".equals(orderPurchaseRoute) && representatives.isEmpty())
                    orderNotice.setText(R.string.order_no_representative);
                else orderNotice.setText("");
                if (orderReceiving) loadReceipts(0);
                else if (orderMine) loadOrderSummaries(0);
                else loadOrderCatalog(0);
            } catch (Exception invalid) {
                orderCompanyOptionsLoaded = false;
                orderItems.removeAllViews();
                orderRenderedKey = null;
                showOrderLoadError(status == 403 ? R.string.order_denied : R.string.order_load_failed,
                        this::loadOrderCompanyOptions);
                if (status == 403) {
                    orderCart.clear();
                    lastRemovedOrderLine = null;
                    invalidateOrderQuote();
                    updateOrderSelectors();
                }
            }
        });
    }

    private void chooseOrderCategory() {
        if (!ordersAvailable || orderCompanyId == 0 || orderMine || orderReceiving) return;
        List<TaskChoice> options = new ArrayList<>();
        options.add(new TaskChoice(0, getString(R.string.order_all_categories)));
        options.addAll(orderCategories);
        chooseOrderChoice(options, R.string.order_category, choice -> {
            orderCategoryId = choice.id;
            updateOrderSelectors();
            prepareOrderContent(orderContentKey("catalog", orderCompanyId,
                    orderCategoryId, orderSearch.getText().toString().trim(), 0));
            loadOrderCatalog(0);
        });
    }

    private void showOrderMode(boolean mine) {
        if (!mine && !orderCanCreate) return;
        if (!ordersAvailable || (!orderReceiving && orderMine == mine)) return;
        resetOrderImages(false);
        orderMine = mine;
        orderReceiving = false;
        ++orderViewSerial;
        if (!mine && !orderCart.isEmpty()) invalidateOrderQuote();
        queuedOrderLoad = null;
        prepareOrderContent(orderContentKey(mine ? "all" : "catalog", mine ? 0 : orderCompanyId,
                mine ? 0 : orderCategoryId,
                mine ? "" : orderSearch.getText().toString().trim(), 0));
        orderOlderButton.setVisibility(View.GONE);
        updateOrderSelectors();
        if (mine) loadOrderSummaries(0);
        else if (orderCompanyId > 0) {
            if (orderCompanyOptionsLoaded) loadOrderCatalog(0);
            else loadOrderCompanyOptions();
        }
    }

    private void showReceiptMode() {
        if (!orderCanReceive) return;
        if (!ordersAvailable || orderReceiving) return;
        resetOrderImages(false);
        orderReceiving = true;
        orderMine = false;
        queuedOrderLoad = null;
        ++orderViewSerial;
        prepareOrderContent(orderContentKey("receiving", orderCompanyId, 0, "", 0));
        orderOlderButton.setVisibility(View.GONE);
        updateOrderSelectors();
        if (orderCompanyId > 0) loadReceipts(0);
    }

    private void loadOrderCatalog(long afterId) {
        loadOrderCatalog(afterId, afterId == 0 ? 0 : 1);
    }

    private void loadOrderCatalog(long afterId, int navigation) {
        if (!verified || !ordersAvailable || !orderCanCreate || orderCompanyId == 0
                || orderMine || orderReceiving
                || !"orders".equals(visibleSection)) return;
        if (v2Busy) {
            beginOrderLoading(orderViewSerial, R.string.order_loading);
            final AccountScope scopedAccount = account;
            final int serial = orderViewSerial;
            final long companyId = orderCompanyId;
            queueOrderLoadWhenIdle(() -> {
                if (scopedAccount == account && serial == orderViewSerial
                        && companyId == orderCompanyId && !orderMine && !orderReceiving)
                    loadOrderCatalog(afterId, navigation);
            });
            return;
        }
        final AccountScope scopedAccount = account;
        final int serial = ++orderViewSerial;
        final long companyId = orderCompanyId;
        final long categoryId = orderCategoryId;
        final String query = orderSearch.getText().toString().trim();
        if (afterId == 0) orderImageFailedKeys.clear();
        if (query.getBytes(StandardCharsets.UTF_8).length > 80) {
            orderNotice.setText(R.string.order_search_too_long);
            return;
        }
        final String contentKey = orderContentKey("catalog", companyId, categoryId, query, afterId);
        prepareOrderContent(contentKey);
        String path = V2_ORDERS + "/catalog?company_id=" + companyId;
        if (!query.isEmpty()) path += "&q=" + Uri.encode(query);
        if (categoryId > 0) path += "&category_id=" + categoryId;
        if (afterId > 0) path += "&after_id=" + afterId;
        beginOrderLoading(serial, R.string.order_loading);
        orderOlderButton.setEnabled(false);
        orderPreviousButton.setEnabled(false);
        fetchV2("POST", path, "{\"api_version\":2}", (status, body) -> {
            if (handleV2TransportFailure(status)) return;
            if (scopedAccount != account || serial != orderViewSerial || orderMine || orderReceiving
                    || companyId != orderCompanyId || categoryId != orderCategoryId
                    || !query.equals(orderSearch.getText().toString().trim())
                    || !"orders".equals(visibleSection)) return;
            finishOrderLoading();
            if (status == 403) { recoverOrderCompanyAccess(companyId); return; }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                JSONArray array = body.getJSONArray("items");
                if (array.length() > 24) throw new IllegalArgumentException();
                List<OrderOption> page = new ArrayList<>();
                Set<Long> ids = new HashSet<>();
                long previousProduct = afterId, previousOption = 0;
                for (int i = 0; i < array.length(); i++) {
                    OrderOption option = new OrderOption(array.getJSONObject(i), companyId);
                    if (option.productId <= afterId || option.productId < previousProduct
                            || (option.productId == previousProduct && option.id <= previousOption)
                            || !ids.add(option.id)
                            || (categoryId > 0 && option.categoryId != categoryId))
                        throw new IllegalArgumentException();
                    previousProduct = option.productId;
                    previousOption = option.id;
                    page.add(option);
                }
                Object cursorValue = body.opt("next_after_id");
                long cursor = cursorValue == null || cursorValue == JSONObject.NULL
                        ? 0 : positiveId(cursorValue);
                if (cursor > 0 && (page.isEmpty() || cursor != previousProduct))
                    throw new IllegalArgumentException();
                if (navigation == 0) orderPageHistory.clear();
                else if (navigation > 0) orderPageHistory.add(orderCurrentPageStartId);
                else if (!orderPageHistory.isEmpty())
                    orderPageHistory.remove(orderPageHistory.size() - 1);
                orderCurrentPageStartId = afterId;
                orderOptions.clear();
                orderOptions.addAll(page);
                orderCatalogAfterId = cursor;
                renderOrderCatalog();
                orderRenderedKey = contentKey;
                orderOlderButton.setText(R.string.order_more_products);
                orderOlderButton.setVisibility(cursor > 0 ? View.VISIBLE : View.GONE);
                orderOlderButton.setEnabled(cursor > 0);
                orderPreviousButton.setVisibility(orderPageHistory.isEmpty()
                        ? View.GONE : View.VISIBLE);
                orderPreviousButton.setEnabled(!orderPageHistory.isEmpty());
                orderScroll.post(() -> orderScroll.scrollTo(0, 0));
                orderNotice.setText("");
            } catch (Exception invalid) {
                if (status == 403) {
                    orderOptions.clear();
                    orderCart.clear();
                    lastRemovedOrderLine = null;
                    invalidateOrderQuote();
                    orderPageHistory.clear();
                    orderCurrentPageStartId = orderCatalogAfterId = 0;
                    renderOrderCatalog();
                    updateOrderSelectors();
                }
                orderOlderButton.setEnabled(orderCatalogAfterId > 0);
                orderPreviousButton.setEnabled(!orderPageHistory.isEmpty());
                showOrderLoadError(status == 403 ? R.string.order_denied : R.string.order_load_failed,
                        () -> loadOrderCatalog(afterId, navigation));
            }
        });
    }

    private void renderOrderCatalog() {
        resetOrderImages(false);
        orderItems.setBackgroundColor(Color.WHITE);
        orderItems.removeAllViews();
        if (orderOptions.isEmpty()) {
            TextView empty = Ui.text(this, getString(R.string.order_empty_catalog), 15, Ui.MUTED, false);
            Ui.pad(empty, 16, 22);
            orderItems.addView(empty);
            orderItems.addView(orderPagingRow);
            return;
        }
        String lastCategory = null;
        final int viewportWidthDp = orderScroll.getWidth() > 0
                ? Math.round(orderScroll.getWidth() / getResources().getDisplayMetrics().density)
                : getResources().getConfiguration().screenWidthDp;
        final boolean tablet = viewportWidthDp >= 600;
        GridLayout grid = null;
        final int cardWidthDp = Math.max(220, (viewportWidthDp - 56) / 2);
        final int cardWidth = dp(cardWidthDp);
        for (int index = 0; index < orderOptions.size();) {
            List<OrderOption> choices = new ArrayList<>();
            OrderOption option = orderOptions.get(index);
            long productId = option.productId;
            do { choices.add(orderOptions.get(index++)); }
            while (index < orderOptions.size() && orderOptions.get(index).productId == productId);
            if (!option.category.equals(lastCategory)) {
                TextView category = Ui.text(this, option.category, 15, Ui.GREEN, true);
                Ui.pad(category, 10, 4);
                orderItems.addView(category);
                lastCategory = option.category;
                if (tablet) {
                    grid = new GridLayout(this);
                    grid.setColumnCount(2);
                    orderItems.addView(grid, new LinearLayout.LayoutParams(-1, -2));
                }
            }
            LinearLayout card = Ui.column(this);
            Ui.pad(card, 10, 5);
            card.setMinimumHeight(dp(76));
            LinearLayout cardTop = Ui.row(this);
            if (option.imagePath != null) {
                ImageView thumbnail = new ImageView(this);
                thumbnail.setScaleType(ImageView.ScaleType.CENTER_CROP);
                thumbnail.setBackgroundColor(Ui.LIGHT);
                thumbnail.setContentDescription(getString(R.string.order_product_image,
                        option.product));
                LinearLayout.LayoutParams thumbnailSize = new LinearLayout.LayoutParams(dp(52), dp(52));
                thumbnailSize.setMarginEnd(dp(8));
                cardTop.addView(thumbnail, thumbnailSize);
                orderImageTargets.add(new OrderImageTarget(option.imagePath, thumbnail,
                        orderViewSerial));
            }
            LinearLayout details = Ui.column(this);
            TextView productName = Ui.text(this, option.product, 15, Ui.INK, true);
            productName.setMaxLines(2);
            productName.setEllipsize(android.text.TextUtils.TruncateAt.END);
            details.addView(productName);
            TextView optionLabel = Ui.text(this, choices.size() == 1
                    ? orderOptionLabel(option)
                    : getString(R.string.order_option_count, String.valueOf(choices.size())),
                    12, Ui.MUTED, false);
            optionLabel.setSingleLine(true);
            optionLabel.setEllipsize(android.text.TextUtils.TruncateAt.END);
            details.addView(optionLabel);
            if (choices.size() == 1 && option.lastPrice != null)
                details.addView(Ui.text(this, getString(R.string.order_last_price,
                        option.lastPrice, option.currency), 11, Ui.MUTED, false));
            OrderCartLine selected = orderLineForProduct(option.productId);
            if (selected != null && choices.size() > 1)
                details.addView(Ui.text(this, orderOptionLabel(selected.option), 12, Ui.GREEN, true));
            cardTop.addView(details, new LinearLayout.LayoutParams(0, -2, 1));
            LinearLayout stepper = selected == null ? null : orderQuantityStepper(selected);
            int availableNameDp = (tablet ? cardWidthDp : viewportWidthDp) - 20
                    - (option.imagePath == null ? 0 : 60) - 154;
            boolean compactStepper = selected != null && availableNameDp < 168;
            if (stepper != null && !compactStepper)
                cardTop.addView(stepper, new LinearLayout.LayoutParams(-2, dp(48)));
            if (selected == null) {
                Button add = new Button(this);
                add.setText(choices.size() == 1 ? "+" : "⋯");
                Ui.styleIconAction(add, Ui.IconTone.TONAL);
                add.setTextSize(21);
                add.setTextColor(Ui.GREEN);
                add.setContentDescription(getString(choices.size() == 1
                        ? R.string.order_add : R.string.order_choose_product_option) + " " + option.product);
                add.setOnClickListener(v -> chooseOrAddOrderProduct(choices));
                cardTop.addView(add, new LinearLayout.LayoutParams(dp(48), dp(48)));
            }
            card.addView(cardTop);
            if (compactStepper) {
                LinearLayout.LayoutParams stepperSize = new LinearLayout.LayoutParams(-2, dp(48));
                stepperSize.gravity = Gravity.END;
                stepperSize.topMargin = dp(4);
                card.addView(stepper, stepperSize);
            }
            card.setContentDescription(option.product + ", " + (choices.size() == 1
                    ? orderOptionLabel(option)
                    : getString(R.string.order_option_count, String.valueOf(choices.size()))));
            Ui.clickable(cardTop);
            cardTop.setOnClickListener(v -> chooseOrAddOrderProduct(choices));
            if (tablet && grid != null) {
                card.setBackground(Ui.bg(Ui.LIGHT, 12, this));
                GridLayout.LayoutParams size = new GridLayout.LayoutParams();
                size.width = cardWidth;
                size.height = -2;
                size.setMargins(dp(8), dp(4), dp(8), dp(4));
                grid.addView(card, size);
            } else {
                orderItems.addView(card);
                orderItems.addView(Ui.line(this));
            }
        }
        orderItems.addView(orderPagingRow);
        scheduleOrderImagePump();
    }

    private String orderOptionLabel(OrderOption option) {
        String label = option.option;
        if (!option.packaging.isEmpty() && !option.packaging.equals(option.option))
            label += " · " + option.packaging;
        return option.uom.equals(option.option) || option.uom.equals(option.packaging)
                ? label : label + " · " + option.uom;
    }

    private LinearLayout orderQuantityStepper(OrderCartLine selected) {
        LinearLayout stepper = Ui.row(this);
        stepper.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 12, this));
        stepper.setClipToOutline(true);
        stepper.addView(orderStepperAction("−", 19, R.string.order_decrease,
                selected.option.product, () -> stepOrderQuantity(selected.option, -1)),
                new LinearLayout.LayoutParams(dp(48), dp(48)));
        View firstDivider = new View(this);
        firstDivider.setBackgroundColor(Ui.LINE);
        LinearLayout.LayoutParams dividerSize = new LinearLayout.LayoutParams(dp(1), dp(24));
        dividerSize.gravity = Gravity.CENTER_VERTICAL;
        stepper.addView(firstDivider, dividerSize);
        TextView quantity = orderStepperAction(selected.quantity, 14,
                R.string.order_change_quantity, selected.option.product,
                () -> editOrderQuantity(selected.option));
        quantity.setContentDescription(getString(R.string.order_change_quantity)
                + " " + selected.option.product + ": " + selected.quantity);
        quantity.setSingleLine(true);
        quantity.setEllipsize(android.text.TextUtils.TruncateAt.MIDDLE);
        stepper.addView(quantity, new LinearLayout.LayoutParams(dp(56), dp(48)));
        View secondDivider = new View(this);
        secondDivider.setBackgroundColor(Ui.LINE);
        LinearLayout.LayoutParams secondDividerSize = new LinearLayout.LayoutParams(dp(1), dp(24));
        secondDividerSize.gravity = Gravity.CENTER_VERTICAL;
        stepper.addView(secondDivider, secondDividerSize);
        stepper.addView(orderStepperAction("+", 19, R.string.order_increase,
                selected.option.product, () -> stepOrderQuantity(selected.option, 1)),
                new LinearLayout.LayoutParams(dp(48), dp(48)));
        return stepper;
    }

    private TextView orderStepperAction(String label, int textSize, int accessibilityLabel,
            String product, Runnable action) {
        TextView button = Ui.text(this, label, textSize, Ui.GREEN, true);
        button.setGravity(Gravity.CENTER);
        button.setMinWidth(dp(48));
        button.setMinHeight(dp(48));
        button.setContentDescription(getString(accessibilityLabel) + " " + product);
        Ui.clickable(button);
        button.setOnClickListener(v -> action.run());
        return button;
    }

    private OrderCartLine orderLineForProduct(long productId) {
        for (OrderCartLine line : orderCart.values())
            if (line.option.productId == productId) return line;
        return null;
    }

    private Button orderQuantityAction(String label, int accessibilityLabel,
            String product, Runnable action) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextSize(17);
        button.setAllCaps(false);
        button.setMinHeight(dp(48));
        button.setContentDescription(getString(accessibilityLabel) + " " + product);
        styleAction(button, false);
        button.setTextSize(16);
        if (label.length() == 1 && "+−×✓".contains(label)) {
            button.setPadding(0, 0, 0, 0);
            Ui.styleIconAction(button, "×".equals(label)
                    ? Ui.IconTone.PLAIN : Ui.IconTone.TONAL);
        }
        button.setOnClickListener(v -> action.run());
        return button;
    }

    private void afterOrderCartChange(boolean redrawMenu) {
        invalidateOrderQuote();
        updateOrderSelectors();
        if (redrawMenu && !orderMine && !orderReceiving) renderOrderCatalogKeepingPosition();
        if (orderCartDialog != null && orderCartDialog.isShowing()) renderOrderCartLines();
    }

    private void removeOrderOption(long optionId) {
        if (!verified || hasPendingOrder()) return;
        lastRemovedOrderLine = orderCart.remove(optionId);
        if (lastRemovedOrderLine == null) return;
        afterOrderCartChange(true);
    }

    private void stepOrderQuantity(OrderOption option, int delta) {
        if (!verified || hasPendingOrder() || delta == 0) return;
        OrderCartLine line = orderCart.get(option.id);
        if (line == null) return;
        try {
            BigDecimal changed = new BigDecimal(line.quantity).add(BigDecimal.valueOf(delta));
            if (changed.signum() <= 0) lastRemovedOrderLine = orderCart.remove(option.id);
            else {
                lastRemovedOrderLine = null;
                orderCart.put(option.id, new OrderCartLine(option,
                        normalizeOrderQuantity(changed.stripTrailingZeros().toPlainString())));
            }
            afterOrderCartChange(true);
        } catch (IllegalArgumentException invalid) {
            orderNotice.setText(R.string.order_invalid_quantity);
        }
    }

    private void chooseOrAddOrderProduct(List<OrderOption> choices) {
        if (!ordersAvailable || orderMine || orderReceiving || hasPendingOrder()) {
            orderNotice.setText(R.string.order_pending_blocks_new);
            return;
        }
        if (choices.size() == 1) {
            addOneOrderOption(choices.get(0));
            return;
        }
        String[] labels = new String[choices.size()];
        for (int i = 0; i < choices.size(); i++) {
            OrderOption choice = choices.get(i);
            labels[i] = orderOptionLabel(choice) + (choice.lastPrice == null ? ""
                    : " · " + getString(R.string.order_last_price, choice.lastPrice, choice.currency));
        }
        new AlertDialog.Builder(this).setTitle(getString(R.string.order_choose_product_option)
                + " · " + choices.get(0).product).setItems(labels,
                (dialog, index) -> addOneOrderOption(choices.get(index)))
                .setNegativeButton(R.string.chat_v2_cancel, null).show();
    }

    private void addOneOrderOption(OrderOption option) {
        if (!verified || !ordersAvailable || orderMine || orderReceiving || hasPendingOrder()
                || !orderOptions.contains(option)) return;
        OrderCartLine existing = orderLineForProduct(option.productId);
        if (existing != null && existing.option.id != option.id) {
            new AlertDialog.Builder(this).setTitle(R.string.order_replace_option_action)
                    .setMessage(getString(R.string.order_replace_option_message,
                            existing.quantity, orderOptionLabel(existing.option), orderOptionLabel(option)))
                    .setPositiveButton(R.string.order_replace_option_action, (dialog, which) -> {
                        if (!verified || !ordersAvailable || orderMine || orderReceiving || hasPendingOrder()
                                || !orderOptions.contains(option) ||
                                orderLineForProduct(option.productId) != existing) return;
                        orderCart.remove(existing.option.id);
                        orderCart.put(option.id, new OrderCartLine(option, "1"));
                        lastRemovedOrderLine = null;
                        afterOrderCartChange(true);
                    }).setNegativeButton(R.string.chat_v2_cancel, null).show();
            return;
        }
        if (existing == null && orderCart.size() >= 100) {
            orderNotice.setText(R.string.order_cart_limit);
            return;
        }
        try {
            String quantity = existing == null ? "1" : normalizeOrderQuantity(
                    new BigDecimal(existing.quantity).add(BigDecimal.ONE)
                            .stripTrailingZeros().toPlainString());
            orderCart.put(option.id, new OrderCartLine(option, quantity));
            lastRemovedOrderLine = null;
            afterOrderCartChange(true);
        } catch (IllegalArgumentException invalid) {
            orderNotice.setText(R.string.order_invalid_quantity);
        }
    }

    private void renderOrderCatalogKeepingPosition() {
        int scrollY = orderScroll.getScrollY();
        renderOrderCatalog();
        orderScroll.post(() -> orderScroll.scrollTo(0, scrollY));
    }

    private static String normalizeOrderQuantity(String raw) {
        if (raw == null || raw.length() > 16) throw new IllegalArgumentException();
        StringBuilder western = new StringBuilder();
        String input = raw.trim();
        for (int i = 0; i < input.length(); i++) {
            char c = input.charAt(i);
            if (c >= '0' && c <= '9') western.append(c);
            else if (c >= '\u0660' && c <= '\u0669') western.append((char) ('0' + c - '\u0660'));
            else if (c >= '\u06f0' && c <= '\u06f9') western.append((char) ('0' + c - '\u06f0'));
            else if (c == '\u066b' || c == '.') western.append('.');
            else throw new IllegalArgumentException();
        }
        String quantity = western.toString();
        if (!quantity.matches("(?:[1-9][0-9]{0,5}|0)(?:\\.[0-9]{1,2})?")
                || quantity.matches("0(?:\\.0{1,2})?"))
            throw new IllegalArgumentException();
        return quantity;
    }

    private void editOrderQuantity(OrderOption option) {
        if (!ordersAvailable || orderMine || orderReceiving || hasPendingOrder()) {
            orderNotice.setText(R.string.order_pending_blocks_new);
            return;
        }
        if (!orderCart.containsKey(option.id) && orderCart.size() >= 100) {
            orderNotice.setText(R.string.order_cart_limit);
            return;
        }
        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        input.setHint(R.string.order_quantity);
        OrderCartLine existing = orderCart.get(option.id);
        input.setText(existing == null ? "1" : existing.quantity);
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(option.product + " · " + option.option)
                .setView(input).setPositiveButton(R.string.order_add, null)
                .setNegativeButton(R.string.chat_v2_cancel, null).create();
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE)
                .setOnClickListener(v -> {
                    try {
                        String quantity = normalizeOrderQuantity(input.getText().toString());
                        orderCart.put(option.id, new OrderCartLine(option, quantity));
                        lastRemovedOrderLine = null;
                        afterOrderCartChange(true);
                        orderNotice.setText(R.string.order_added);
                        dialog.dismiss();
                    } catch (Exception invalid) { input.setError(getString(R.string.order_invalid_quantity)); }
                }));
        dialog.show();
    }

    private void loadOrderSummaries(long beforeId) {
        if (!verified || !ordersAvailable || !orderMine
                || !"orders".equals(visibleSection)) return;
        if (v2Busy) {
            final AccountScope scopedAccount = account;
            final int serial = orderViewSerial;
            queueOrderLoadWhenIdle(() -> {
                if (scopedAccount == account && serial == orderViewSerial && orderMine)
                    loadOrderSummaries(beforeId);
            });
            return;
        }
        final AccountScope scopedAccount = account;
        final int serial = ++orderViewSerial;
        final String contentKey = orderContentKey("all", 0, 0, "", beforeId);
        prepareOrderContent(contentKey);
        String path = V2_ORDERS + "?scope=all";
        if (beforeId > 0) path += "&before_id=" + beforeId;
        beginOrderLoading(serial, R.string.order_loading);
        orderOlderButton.setEnabled(false);
        fetchV2("GET", path, null, (status, body) -> {
            if (handleV2TransportFailure(status)) return;
            if (scopedAccount != account || serial != orderViewSerial || !orderMine
                    || !"orders".equals(visibleSection)) return;
            finishOrderLoading();
            if (status == 403 || status == 404) { recoverAllOrdersAccess(); return; }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                JSONArray array = body.getJSONArray("orders");
                if (array.length() > 30) throw new IllegalArgumentException();
                List<OrderSummary> page = new ArrayList<>();
                long previous = beforeId == 0 ? Long.MAX_VALUE : beforeId;
                for (int i = 0; i < array.length(); i++) {
                    OrderSummary order = new OrderSummary(array.getJSONObject(i), true);
                    if (order.id >= previous || !v1Companies.contains(order.companyId))
                        throw new IllegalArgumentException();
                    previous = order.id;
                    page.add(order);
                }
                Object cursorValue = body.opt("next_before_id");
                long cursor = cursorValue == null || cursorValue == JSONObject.NULL
                        ? 0 : positiveId(cursorValue);
                if (cursor > 0 && (page.isEmpty() || cursor != previous))
                    throw new IllegalArgumentException();
                if (beforeId == 0) orderSummaries.clear();
                orderSummaries.addAll(page);
                if (orderSummaries.size() > 200)
                    orderSummaries.subList(0, orderSummaries.size() - 200).clear();
                orderListBeforeId = cursor;
                renderOrderSummaries();
                orderRenderedKey = contentKey;
                orderOlderButton.setText(R.string.order_older);
                orderOlderButton.setVisibility(cursor > 0 ? View.VISIBLE : View.GONE);
                orderOlderButton.setEnabled(cursor > 0);
                orderNotice.setText("");
                allOrdersRecoveryAttempted = false;
            } catch (Exception invalid) {
                orderOlderButton.setEnabled(orderListBeforeId > 0);
                showOrderLoadError(R.string.order_load_failed, () -> loadOrderSummaries(beforeId));
            }
        });
    }

    private void renderOrderSummaries() {
        orderItems.setBackgroundColor(Ui.LIGHT);
        orderItems.removeAllViews();
        if (orderSummaries.isEmpty()) {
            TextView empty = Ui.text(this, getString(R.string.order_empty_mine), 15, Ui.MUTED, false);
            Ui.pad(empty, 16, 22);
            orderItems.addView(empty);
            orderItems.addView(orderPagingRow);
            return;
        }
        for (OrderSummary order : orderSummaries) {
            LinearLayout card = Ui.column(this);
            Ui.pad(card, 12, 10);
            card.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 14, this));
            LinearLayout heading = Ui.row(this);
            TextView number = Ui.text(this, order.name, 15, Ui.INK, true);
            number.setSingleLine(true);
            number.setEllipsize(android.text.TextUtils.TruncateAt.END);
            heading.addView(number, new LinearLayout.LayoutParams(0, -2, 1));
            TextView state = Ui.text(this, getString(orderStateLabel(order.state)), 11,
                    Ui.GREEN, true);
            Ui.pad(state, 8, 4);
            state.setBackground(Ui.bg(Ui.LIME, 10, this));
            LinearLayout.LayoutParams stateSize = new LinearLayout.LayoutParams(-2, -2);
            stateSize.setMarginStart(dp(8));
            heading.addView(state, stateSize);
            card.addView(heading, new LinearLayout.LayoutParams(-1, -2));
            card.addView(Ui.text(this, getString(R.string.order_summary_company,
                    companyNameForId(order.companyId, order.companyName)), 12, Ui.MUTED, false));
            card.addView(Ui.text(this, getString(R.string.order_summary_requester,
                    order.requesterName), 12, Ui.MUTED, false));
            card.addView(Ui.text(this, getString(R.string.order_purchase_route_value,
                    orderRouteLabel(order.purchaseRoute)), 12, Ui.MUTED, false));
            if (!order.representative.isEmpty()) {
                TextView representative = Ui.text(this,
                        getString(R.string.order_summary_representative, order.representative),
                        12, Ui.MUTED, false);
                LinearLayout.LayoutParams lineSize = new LinearLayout.LayoutParams(-1, -2);
                lineSize.topMargin = dp(5);
                card.addView(representative, lineSize);
            }
            if (!order.submittedAt.isEmpty())
                card.addView(Ui.text(this, formatMessageTime(order.submittedAt),
                        11, Ui.MUTED, false));
            if (!order.total.isEmpty()) {
                TextView total = Ui.text(this, getString(R.string.order_total,
                        order.total, order.currency), 13, Ui.GREEN, true);
                LinearLayout.LayoutParams totalSize = new LinearLayout.LayoutParams(-1, -2);
                totalSize.topMargin = dp(7);
                card.addView(total, totalSize);
            }
            card.setContentDescription(getString(R.string.order_view_previous, order.name)
                    + " · " + getString(orderStateLabel(order.state)));
            Ui.clickable(card);
            card.setOnClickListener(v -> loadPreviousOrder(order));
            LinearLayout.LayoutParams cardSize = new LinearLayout.LayoutParams(-1, -2);
            cardSize.setMargins(dp(8), dp(4), dp(8), dp(4));
            orderItems.addView(card, cardSize);
        }
        orderItems.addView(orderPagingRow);
    }

    private boolean receiptContext(AccountScope scopedAccount, long companyId, int serial) {
        return verified && scopedAccount == account && ordersAvailable && !ordersDenied
                && orderCanReceive
                && orderReceiving && "orders".equals(visibleSection)
                && orderCompanyId == companyId && orderViewSerial == serial;
    }

    private void loadReceipts(long beforeId) {
        if (!verified || !ordersAvailable || ordersDenied || !orderCanReceive || !orderReceiving
                || orderCompanyId == 0 || !"orders".equals(visibleSection)) return;
        if (v2Busy) {
            beginOrderLoading(orderViewSerial, R.string.receipt_loading);
            final AccountScope scopedAccount = account;
            final int serial = orderViewSerial;
            final long companyId = orderCompanyId;
            queueOrderLoadWhenIdle(() -> {
                if (scopedAccount == account && serial == orderViewSerial
                        && companyId == orderCompanyId && orderReceiving)
                    loadReceipts(beforeId);
            });
            return;
        }
        final AccountScope scopedAccount = account;
        final long companyId = orderCompanyId;
        final int serial = ++orderViewSerial;
        final String contentKey = orderContentKey("receiving", companyId, 0, "", beforeId);
        prepareOrderContent(contentKey);
        String path = V2_ORDERS + "/receipts?company_id=" + companyId;
        if (beforeId > 0) path += "&before_id=" + beforeId;
        beginOrderLoading(serial, R.string.receipt_loading);
        orderOlderButton.setEnabled(false);
        fetchV2("GET", path, null, (status, body) -> {
            if (handleV2TransportFailure(status)) return;
            if (!receiptContext(scopedAccount, companyId, serial)) return;
            finishOrderLoading();
            if (status == 403) { recoverOrderCompanyAccess(companyId); return; }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                JSONArray raw = body.getJSONArray("orders");
                if (raw.length() > 30) throw new IllegalArgumentException();
                List<ReceiptSummary> page = new ArrayList<>();
                long previous = beforeId == 0 ? Long.MAX_VALUE : beforeId;
                for (int i = 0; i < raw.length(); i++) {
                    ReceiptSummary order = new ReceiptSummary(raw.getJSONObject(i));
                    if (order.companyId != companyId || order.id >= previous)
                        throw new IllegalArgumentException();
                    previous = order.id;
                    page.add(order);
                }
                Object cursorValue = body.opt("next_before_id");
                long cursor = cursorValue == null || cursorValue == JSONObject.NULL
                        ? 0 : positiveId(cursorValue);
                if (cursor > 0 && (page.isEmpty() || cursor != previous))
                    throw new IllegalArgumentException();
                if (beforeId == 0) receiptSummaries.clear();
                receiptSummaries.addAll(page);
                if (receiptSummaries.size() > 200)
                    receiptSummaries.subList(0, receiptSummaries.size() - 200).clear();
                receiptBeforeId = cursor;
                renderReceipts();
                orderRenderedKey = contentKey;
                orderOlderButton.setText(R.string.receipt_older);
                orderOlderButton.setVisibility(cursor > 0 ? View.VISIBLE : View.GONE);
                orderOlderButton.setEnabled(cursor > 0);
                orderNotice.setText("");
            } catch (Exception invalid) {
                orderOlderButton.setEnabled(receiptBeforeId > 0);
                showOrderLoadError(R.string.receipt_load_failed,
                        () -> loadReceipts(beforeId));
            }
        });
    }

    private void renderReceipts() {
        orderItems.setBackgroundColor(Ui.LIGHT);
        orderItems.removeAllViews();
        if (receiptSummaries.isEmpty()) {
            TextView empty = Ui.text(this, getString(R.string.receipt_empty), 15, Ui.MUTED, false);
            Ui.pad(empty, 16, 22);
            orderItems.addView(empty);
        }
        for (ReceiptSummary receipt : receiptSummaries) {
            LinearLayout card = Ui.column(this);
            Ui.pad(card, 12, 10);
            card.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 14, this));
            LinearLayout heading = Ui.row(this);
            TextView name = Ui.text(this, receipt.name, 15, Ui.INK, true);
            name.setSingleLine(true);
            name.setEllipsize(android.text.TextUtils.TruncateAt.END);
            heading.addView(name, new LinearLayout.LayoutParams(0, -2, 1));
            TextView state = Ui.text(this, getString(orderStateLabel(receipt.state)), 11,
                    Ui.GREEN, true);
            Ui.pad(state, 8, 4);
            state.setBackground(Ui.bg(Ui.LIME, 10, this));
            heading.addView(state);
            card.addView(heading);
            card.addView(Ui.text(this, getString(R.string.receipt_requester,
                    receipt.requester), 12, Ui.MUTED, false));
            card.addView(Ui.text(this, getString(R.string.receipt_warehouse,
                    receipt.warehouse), 12, Ui.MUTED, false));
            if (!receipt.submittedAt.isEmpty())
                card.addView(Ui.text(this, formatMessageTime(receipt.submittedAt),
                        11, Ui.MUTED, false));
            card.setContentDescription(getString(R.string.receipt_open, receipt.name));
            Ui.clickable(card);
            card.setOnClickListener(v -> loadReceiptDetail(receipt));
            LinearLayout.LayoutParams cardSize = new LinearLayout.LayoutParams(-1, -2);
            cardSize.setMargins(dp(8), dp(4), dp(8), dp(4));
            orderItems.addView(card, cardSize);
        }
        orderPreviousButton.setVisibility(View.GONE);
        orderItems.addView(orderPagingRow);
    }

    private void loadReceiptDetail(ReceiptSummary selected) {
        if (!verified || !orderReceiving || hasPendingReceipt()) {
            if (hasPendingReceipt()) reviewPendingReceipt();
            return;
        }
        if (v2Busy) { orderNotice.setText(R.string.receipt_loading); return; }
        final AccountScope scopedAccount = account;
        final long companyId = orderCompanyId;
        final int serial = orderViewSerial;
        orderNotice.setText(R.string.receipt_loading);
        fetchV2("GET", V2_ORDERS + "/receipts/" + selected.id
                + "?company_id=" + companyId, null, (status, body) -> {
            if (handleV2TransportFailure(status)) return;
            if (!receiptContext(scopedAccount, companyId, serial)) return;
            if (status == 403) { recoverOrderCompanyAccess(companyId); return; }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                ReceiptSummary detail = new ReceiptSummary(body.getJSONObject("order"));
                if (detail.id != selected.id || detail.companyId != companyId)
                    throw new IllegalArgumentException();
                JSONArray rawLines = body.getJSONArray("lines");
                if (rawLines.length() == 0 || rawLines.length() > 100)
                    throw new IllegalArgumentException();
                List<ReceiptLine> lines = new ArrayList<>();
                Set<Long> seen = new HashSet<>();
                for (int i = 0; i < rawLines.length(); i++) {
                    ReceiptLine line = new ReceiptLine(rawLines.getJSONObject(i));
                    if (!seen.add(line.id)) throw new IllegalArgumentException();
                    lines.add(line);
                }
                orderNotice.setText("");
                showReceiptForm(detail, lines, scopedAccount, companyId, serial);
            } catch (Exception invalid) {
                orderNotice.setText(status == 404 ? R.string.receipt_unavailable
                        : R.string.receipt_load_failed);
            }
        });
    }

    private static String normalizeReceiptValue(String raw, int integerDigits) {
        if (raw == null || raw.length() > integerDigits + 4) throw new IllegalArgumentException();
        StringBuilder western = new StringBuilder();
        String input = raw.trim();
        for (int i = 0; i < input.length(); i++) {
            char c = input.charAt(i);
            if (c >= '0' && c <= '9') western.append(c);
            else if (c >= '\u0660' && c <= '\u0669') western.append((char) ('0' + c - '\u0660'));
            else if (c >= '\u06f0' && c <= '\u06f9') western.append((char) ('0' + c - '\u06f0'));
            else if (c == '\u066b' || c == '.') western.append('.');
            else throw new IllegalArgumentException();
        }
        if (!western.toString().matches("(?:0|[1-9][0-9]{0," + (integerDigits - 1)
                + "})(?:\\.[0-9]{1,2})?")) throw new IllegalArgumentException();
        return new BigDecimal(western.toString()).setScale(2).toPlainString();
    }

    private EditText receiptNumberInput(int hint) {
        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setTextSize(14);
        input.setHint(hint);
        input.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        input.setMinHeight(dp(48));
        input.setSelectAllOnFocus(true);
        return input;
    }

    private void showReceiptForm(ReceiptSummary detail, List<ReceiptLine> lines,
            AccountScope scopedAccount, long companyId, int serial) {
        showReceiptForm(detail, lines, scopedAccount, companyId, serial, null);
    }

    private void showReceiptForm(ReceiptSummary detail, List<ReceiptLine> lines,
            AccountScope scopedAccount, long companyId, int serial, PendingReceipt replacing) {
        Map<Long, String[]> previousValues = new LinkedHashMap<>();
        if (replacing != null) {
            try {
                JSONArray previous = new JSONObject(replacing.raw).getJSONArray("lines");
                if (previous.length() != lines.size()) throw new IllegalArgumentException();
                for (int i = 0; i < previous.length(); i++) {
                    JSONObject value = previous.getJSONObject(i);
                    previousValues.put(positiveId(value.get("line_id")), new String[] {
                            value.getString("actual_qty"), value.getString("actual_price")});
                }
                for (ReceiptLine line : lines)
                    if (!previousValues.containsKey(line.id)) throw new IllegalArgumentException();
            } catch (Exception changed) {
                orderNotice.setText(R.string.receipt_conflict);
                return;
            }
        }
        LinearLayout content = Ui.column(this);
        Ui.pad(content, 12, 4);
        content.addView(Ui.text(this, getString(R.string.receipt_context,
                detail.requester, detail.warehouse), 12, Ui.MUTED, false));
        TextView warning = Ui.text(this, getString(R.string.receipt_final_warning),
                13, Ui.INK, true);
        Ui.pad(warning, 10, 10);
        warning.setBackground(Ui.bg(Ui.LIME, 10, this));
        LinearLayout.LayoutParams warningSize = new LinearLayout.LayoutParams(-1, -2);
        warningSize.topMargin = dp(10);
        content.addView(warning, warningSize);
        ScrollView scroll = new ScrollView(this);
        LinearLayout list = Ui.column(this);
        List<ReceiptInputLine> inputs = new ArrayList<>();
        for (ReceiptLine line : lines) {
            LinearLayout row = Ui.column(this);
            Ui.pad(row, 8, 9);
            row.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 10, this));
            row.addView(Ui.text(this, line.product, 14, Ui.INK, true));
            if (!line.option.isEmpty())
                row.addView(Ui.text(this, line.option, 12, Ui.MUTED, false));
            row.addView(Ui.text(this, getString(R.string.receipt_requested,
                    line.requestedQty, line.uom), 12, Ui.MUTED, false));
            if (!line.managerQty.isEmpty())
                row.addView(Ui.text(this, getString(R.string.receipt_manager_qty,
                        line.managerQty, line.uom), 12, Ui.MUTED, false));
            LinearLayout fields = Ui.row(this);
            EditText quantity = receiptNumberInput(R.string.receipt_actual_qty);
            quantity.setContentDescription(getString(R.string.receipt_actual_qty) + " " + line.product);
            if (replacing != null) quantity.setText(previousValues.get(line.id)[0]);
            fields.addView(quantity, new LinearLayout.LayoutParams(0, dp(48), 1));
            EditText price = receiptNumberInput(R.string.receipt_actual_price);
            price.setContentDescription(getString(R.string.receipt_actual_price) + " " + line.product);
            if (replacing != null) price.setText(previousValues.get(line.id)[1]);
            LinearLayout.LayoutParams priceSize = new LinearLayout.LayoutParams(0, dp(48), 1);
            priceSize.setMarginStart(dp(8));
            fields.addView(price, priceSize);
            row.addView(fields);
            LinearLayout.LayoutParams rowSize = new LinearLayout.LayoutParams(-1, -2);
            rowSize.topMargin = dp(8);
            list.addView(row, rowSize);
            inputs.add(new ReceiptInputLine(line, quantity, price));
        }
        scroll.addView(list);
        int screen = getResources().getDisplayMetrics().heightPixels;
        LinearLayout.LayoutParams scrollSize = new LinearLayout.LayoutParams(-1,
                Math.min(dp(400), Math.max(dp(150), (int) (screen * 0.55f))));
        scrollSize.topMargin = dp(8);
        content.addView(scroll, scrollSize);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(detail.name)
                .setView(content).setPositiveButton(R.string.receipt_review, null)
                .setNegativeButton(R.string.chat_v2_cancel, null).create();
        dialog.setOnShowListener(ignored -> {
            Ui.decorateDialog(dialog);
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                if (!receiptContext(scopedAccount, companyId, serial)) {
                    dialog.dismiss();
                    orderNotice.setText(R.string.order_previous_context_changed);
                    return;
                }
                if (replacing == null && hasPendingReceipt()) {
                    dialog.dismiss();
                    reviewPendingReceipt();
                    return;
                }
                if (replacing != null && !replacing.stored.equals(receiptConfirmPreferences()
                        .getString(replacing.scope, null))) {
                    dialog.dismiss();
                    orderNotice.setText(R.string.order_previous_context_changed);
                    return;
                }
                JSONArray payloadLines = new JSONArray();
                StringBuilder review = new StringBuilder(getString(R.string.receipt_final_warning));
                try {
                    for (ReceiptInputLine item : inputs) {
                        String qty, price;
                        try { qty = normalizeReceiptValue(item.quantity.getText().toString(), 6); }
                        catch (Exception invalid) {
                            item.quantity.setError(getString(R.string.receipt_invalid_value));
                            return;
                        }
                        try { price = normalizeReceiptValue(item.price.getText().toString(), 9); }
                        catch (Exception invalid) {
                            item.price.setError(getString(R.string.receipt_invalid_value));
                            return;
                        }
                        if ("0.00".equals(qty) && !"0.00".equals(price)) {
                            item.price.setError(getString(R.string.receipt_zero_price));
                            return;
                        }
                        JSONObject line = new JSONObject();
                        line.put("line_id", item.line.id);
                        line.put("actual_qty", qty);
                        line.put("actual_price", price);
                        payloadLines.put(line);
                        review.append('\n').append(item.line.product).append(": ")
                                .append(qty).append(" × ").append(price);
                    }
                    dialog.dismiss();
                    confirmReceiptReview(detail, payloadLines, review.toString(),
                            scopedAccount, companyId, serial, replacing);
                } catch (Exception invalid) {
                    orderNotice.setText(R.string.receipt_invalid_value);
                }
            });
        });
        receiptFlowDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (receiptFlowDialog == dialog) receiptFlowDialog = null;
        });
        dialog.show();
    }

    private void confirmReceiptReview(ReceiptSummary detail, JSONArray lines, String review,
            AccountScope scopedAccount, long companyId, int serial, PendingReceipt replacing) {
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(R.string.receipt_confirm)
                .setMessage(review)
                .setPositiveButton(R.string.receipt_confirm, (ignoredDialog, which) -> {
                    if (!receiptContext(scopedAccount, companyId, serial)
                            || (replacing == null ? hasPendingReceipt()
                            : !replacing.stored.equals(receiptConfirmPreferences()
                                    .getString(replacing.scope, null)))) {
                        orderNotice.setText(R.string.order_previous_context_changed);
                        return;
                    }
                    try {
                        JSONObject payload = new JSONObject();
                        payload.put("api_version", 2);
                        payload.put("company_id", companyId);
                        // A validation-rejected attempt is edited under its original UUID;
                        // a later replay can never create a second receipt for this operation.
                        payload.put("client_uuid", replacing == null
                                ? UUID.randomUUID().toString() : replacing.uuid);
                        payload.put("lines", lines);
                        PendingReceipt pending = new PendingReceipt(scopedAccount,
                                detail.id, payload.toString());
                        if (!receiptConfirmPreferences().edit()
                                .putString(scopedAccount.key, pending.stored).commit()) {
                            orderNotice.setText(R.string.receipt_save_failed);
                            return;
                        }
                        updateOrderSelectors();
                        sendPendingReceipt(pending);
                    } catch (Exception invalid) {
                        orderNotice.setText(R.string.receipt_invalid_value);
                    }
                }).setNegativeButton(R.string.chat_v2_cancel, null).create();
        receiptFlowDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (receiptFlowDialog == dialog) receiptFlowDialog = null;
        });
        dialog.show();
    }

    private void loadPreviousOrder(OrderSummary selected) {
        if (!verified || account == null || !ordersAvailable || !orderMine
                || selected == null || !v1Companies.contains(selected.companyId)
                || !"orders".equals(visibleSection)) return;
        if (v2Busy) {
            orderNotice.setText(R.string.order_previous_loading);
            return;
        }
        final AccountScope scopedAccount = account;
        final int serial = orderViewSerial;
        final long companyId = selected.companyId;
        orderNotice.setText(R.string.order_previous_loading);
        fetchV2("GET", V2_ORDERS + "/" + selected.id + "?company_id=" + companyId
                        + "&scope=all",
                null, (status, body) -> {
            if (handleV2TransportFailure(status)) return;
            if (scopedAccount != account || serial != orderViewSerial || !orderMine
                    || !"orders".equals(visibleSection)) return;
            if (status == 403) { recoverAllOrdersAccess(); return; }
            if (status == 404) {
                recoverAllOrdersAccess();
                return;
            }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                JSONObject rawOrder = body.getJSONObject("order");
                OrderSummary detail = new OrderSummary(rawOrder, true);
                if (detail.id != selected.id || detail.companyId != companyId
                        || detail.requesterId != selected.requesterId
                        || !v1Companies.contains(detail.companyId))
                    throw new IllegalArgumentException();
                JSONArray rawLines = body.getJSONArray("lines");
                if (rawLines.length() == 0 || rawLines.length() > 100)
                    throw new IllegalArgumentException();
                List<PreviousOrderLine> lines = new ArrayList<>();
                Set<Long> lineIds = new HashSet<>();
                for (int i = 0; i < rawLines.length(); i++) {
                    PreviousOrderLine line = new PreviousOrderLine(rawLines.getJSONObject(i));
                    if (!lineIds.add(line.id)) throw new IllegalArgumentException();
                    lines.add(line);
                }
                orderNotice.setText("");
                showPreviousOrder(detail, lines, scopedAccount, companyId, serial);
            } catch (Exception invalid) {
                orderNotice.setText(status == 403 || status == 404
                        ? R.string.order_previous_denied : R.string.order_previous_failed);
            }
        });
    }

    private void showPreviousOrder(OrderSummary detail,
            List<PreviousOrderLine> lines, AccountScope scopedAccount,
            long companyId, int serial) {
        LinearLayout content = Ui.column(this);
        Ui.pad(content, 14, 4);
        TextView summary = Ui.text(this, getString(orderStateLabel(detail.state)),
                13, Ui.GREEN, true);
        content.addView(summary);
        content.addView(Ui.text(this, getString(R.string.order_summary_company,
                companyNameForId(detail.companyId, detail.companyName)), 12, Ui.MUTED, false));
        content.addView(Ui.text(this, getString(R.string.order_summary_requester,
                detail.requesterName), 12, Ui.MUTED, false));
        content.addView(Ui.text(this, getString(R.string.order_purchase_route_value,
                orderRouteLabel(detail.purchaseRoute)), 12, Ui.MUTED, false));
        if (!detail.submittedAt.isEmpty()) {
            TextView date = Ui.text(this, formatMessageTime(detail.submittedAt),
                    12, Ui.MUTED, false);
            content.addView(date);
        }
        if (!detail.total.isEmpty()) {
            TextView oldTotal = Ui.text(this,
                    getString(R.string.order_previous_total, detail.total, detail.currency),
                    13, Ui.MUTED, false);
            LinearLayout.LayoutParams totalSize = new LinearLayout.LayoutParams(-1, -2);
            totalSize.topMargin = dp(8);
            content.addView(oldTotal, totalSize);
        }
        content.addView(Ui.line(this));
        ScrollView scroll = new ScrollView(this);
        LinearLayout list = Ui.column(this);
        for (PreviousOrderLine line : lines) {
            LinearLayout item = Ui.column(this);
            Ui.pad(item, 10, 10);
            item.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 10, this));
            item.addView(Ui.text(this, line.product, 14, Ui.INK, true));
            item.addView(Ui.text(this, line.option + " · "
                    + getString(R.string.order_previous_quantity, line.quantity),
                    12, Ui.MUTED, false));
            LinearLayout.LayoutParams itemSize = new LinearLayout.LayoutParams(-1, -2);
            itemSize.topMargin = dp(7);
            list.addView(item, itemSize);
        }
        scroll.addView(list);
        int screen = getResources().getDisplayMetrics().heightPixels;
        LinearLayout.LayoutParams scrollSize = new LinearLayout.LayoutParams(-1,
                Math.min(dp(390), Math.max(dp(140), (int) (screen * 0.52f))));
        scrollSize.topMargin = dp(10);
        content.addView(scroll, scrollSize);
        String shareText = null;
        try {
            shareText = previousOrderShareText(detail, lines);
            OutboxPolicy.requireText(shareText);
        } catch (IllegalArgumentException tooLong) { /* Detail remains readable. */ }
        final String readyText = shareText;
        boolean ownOrder = detail.requesterId == scopedAccount.userId && orderCanCreate;
        TextView hint = Ui.text(this, getString(!ownOrder
                        ? R.string.order_other_requester_readonly : readyText == null
                        ? R.string.order_share_too_long : R.string.order_share_history_notice),
                12, Ui.MUTED, false);
        Ui.pad(hint, 0, 10);
        content.addView(hint);
        AlertDialog.Builder builder = new AlertDialog.Builder(this).setTitle(detail.name)
                .setView(content).setNegativeButton(R.string.task_close, null);
        if (ownOrder) builder.setPositiveButton(R.string.order_share_chat, null);
        AlertDialog dialog = builder.create();
        dialog.setOnShowListener(ignored -> {
            Ui.decorateDialog(dialog);
            if (!ownOrder) return;
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(readyText != null);
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                if (!validPreviousOrderContext(scopedAccount, companyId,
                        detail.requesterId, serial)) {
                    dialog.dismiss();
                    orderNotice.setText(R.string.order_previous_context_changed);
                    return;
                }
                dialog.dismiss();
                choosePreviousOrderRoom(readyText, scopedAccount, companyId,
                        detail.requesterId, serial);
            });
        });
        dialog.show();
    }

    private boolean validPreviousOrderContext(AccountScope scopedAccount,
            long companyId, long requesterId, int serial) {
        return verified && account == scopedAccount && ordersAvailable && orderMine
                && orderCanCreate
                && "orders".equals(visibleSection) && v1Companies.contains(companyId)
                && requesterId == scopedAccount.userId
                && orderViewSerial == serial;
    }

    private String previousOrderShareText(OrderSummary detail, List<PreviousOrderLine> lines) {
        StringBuilder text = new StringBuilder(getString(R.string.order_share_heading, detail.name));
        text.append('\n').append(getString(R.string.order_purchase_route_value,
                orderRouteLabel(detail.purchaseRoute)));
        for (PreviousOrderLine line : lines)
            text.append('\n').append(getString(R.string.order_share_line,
                    line.product, line.option, line.quantity));
        if (!detail.total.isEmpty())
            text.append('\n').append(getString(R.string.order_share_total,
                    detail.total, detail.currency));
        return text.toString();
    }

    private void choosePreviousOrderRoom(String shareText, AccountScope scopedAccount,
            long companyId, long requesterId, int serial) {
        if (!validPreviousOrderContext(scopedAccount, companyId, requesterId, serial) || v2Busy) {
            orderNotice.setText(R.string.order_previous_context_changed);
            return;
        }
        orderNotice.setText(R.string.order_room_loading);
        fetchV2("GET", V2_ROOMS, null, (status, body) -> {
            if (handleV2TransportFailure(status)) return;
            if (!validPreviousOrderContext(scopedAccount, companyId, requesterId, serial)) return;
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                JSONArray listed = body.getJSONArray("rooms");
                if (listed.length() > 100) throw new IllegalArgumentException();
                List<Room> fresh = new ArrayList<>(), eligible = new ArrayList<>();
                Set<Long> seen = new HashSet<>();
                for (int i = 0; i < listed.length(); i++) {
                    JSONObject item = listed.getJSONObject(i);
                    long id = positiveId(item.get("id"));
                    long roomCompany = positiveId(item.get("company_id"));
                    long membership = positiveId(item.get("membership_id"));
                    String name = item.getString("name");
                    String policy = item.getString("invoice_policy");
                    int version = item.getInt("invoice_policy_version");
                    if (!seen.add(id) || !v1Companies.contains(roomCompany)
                            || name.trim().isEmpty()
                            || name.getBytes(StandardCharsets.UTF_8).length > 256
                            || name.indexOf('\n') >= 0 || name.indexOf('\r') >= 0
                            || !("off".equals(policy) || "select_on_upload".equals(policy)
                                    || "invoice_default".equals(policy)) || version < 1)
                        throw new IllegalArgumentException();
                    Room room = new Room(id, roomCompany, membership, name, policy, version);
                    fresh.add(room);
                    if (roomCompany == companyId) eligible.add(room);
                }
                if (eligible.isEmpty()) {
                    orderNotice.setText(R.string.order_share_no_room);
                    return;
                }
                String[] names = new String[eligible.size()];
                for (int i = 0; i < eligible.size(); i++) names[i] = eligible.get(i).name;
                orderNotice.setText("");
                new AlertDialog.Builder(this).setTitle(R.string.order_share_choose_room)
                        .setItems(names, (dialog, index) -> {
                            if (!validPreviousOrderContext(scopedAccount, companyId,
                                    requesterId, serial)) {
                                orderNotice.setText(R.string.order_previous_context_changed);
                                return;
                            }
                            Room chosen = eligible.get(index);
                            try {
                                OutboxPolicy.requireText(shareText);
                                if (outbox == null) throw new IllegalStateException();
                                if (outbox.first(scopedAccount, chosen.id, chosen.membershipId) != null
                                        || (mediaStore != null && mediaStore.pending(scopedAccount,
                                                chosen.id, chosen.membershipId) != null)) {
                                    orderNotice.setText(R.string.order_share_pending);
                                    return;
                                }
                                outbox.enqueuePreservingDraft(scopedAccount, chosen.id,
                                        chosen.membershipId, shareText);
                                rooms.clear();
                                rooms.addAll(fresh);
                                pendingOrderShareRoom = chosen;
                                selectRoom(chosen);
                            } catch (Exception storage) {
                                orderNotice.setText(R.string.chat_v2_save_failed);
                            }
                        }).setNegativeButton(R.string.chat_v2_cancel, null).show();
            } catch (Exception invalid) {
                orderNotice.setText(R.string.order_room_load_failed);
            }
        });
    }

    private int orderStateLabel(String state) {
        if ("draft".equals(state)) return R.string.order_state_draft;
        if ("sent".equals(state)) return R.string.order_state_sent;
        if ("received".equals(state)) return R.string.order_state_received;
        if ("purchased".equals(state)) return R.string.order_state_purchased;
        return R.string.order_state_cancel;
    }

    private String orderRouteLabel(String route) {
        if ("cash".equals(route)) return getString(R.string.order_route_cash);
        if ("bank_transfer".equals(route)) return getString(R.string.order_route_bank_transfer);
        return getString(R.string.order_route_representative);
    }

    private void refreshOrderCartRoute() {
        if (orderCartRouteButton != null) {
            // This is already a selectable route control; a compact value avoids repeating its label.
            orderCartRouteButton.setText(orderRouteLabel(orderPurchaseRoute));
            orderCartRouteButton.setVisibility(orderPurchaseRoutes.size() > 1
                    ? View.VISIBLE : View.GONE);
        }
        if (orderCartRepresentativeButton != null) {
            boolean chooseRepresentative = "representative".equals(orderPurchaseRoute)
                    && orderRepresentatives.size() > 1;
            orderCartRepresentativeButton.setVisibility(chooseRepresentative
                    ? View.VISIBLE : View.GONE);
            if (chooseRepresentative) orderCartRepresentativeButton.setText(
                    orderChoiceName(orderRepresentatives, orderRepresentativeId,
                            R.string.order_choose_representative));
        }
    }

    private void chooseOrderPurchaseRoute() {
        if (orderPurchaseRoutes.size() < 2) return;
        String[] labels = new String[orderPurchaseRoutes.size()];
        for (int i = 0; i < labels.length; i++)
            labels[i] = orderRouteLabel(orderPurchaseRoutes.get(i));
        int selected = orderPurchaseRoutes.indexOf(orderPurchaseRoute);
        new AlertDialog.Builder(this).setTitle(R.string.order_purchase_route)
                .setSingleChoiceItems(labels, selected, (dialog, which) -> {
                    orderPurchaseRoute = orderPurchaseRoutes.get(which);
                    if (!"representative".equals(orderPurchaseRoute)) orderRepresentativeId = 0;
                    orderDetailsPanel.setVisibility(View.GONE);
                    updateOrderSelectors();
                    if ("representative".equals(orderPurchaseRoute)
                            && orderRepresentatives.isEmpty())
                        orderNotice.setText(R.string.order_no_representative);
                    else if (getString(R.string.order_no_representative)
                            .contentEquals(orderNotice.getText())) orderNotice.setText("");
                    dialog.dismiss();
                }).setNegativeButton(R.string.chat_v2_cancel, null).show();
    }

    private void reviewOrderCart() {
        if (orderMine || orderReceiving) return;
        if (orderCart.isEmpty()) { orderNotice.setText(R.string.order_empty_cart); return; }
        if (hasPendingOrder()) { reviewPendingOrder(); return; }
        if (orderCartDialog != null && orderCartDialog.isShowing()) return;
        LinearLayout content = Ui.column(this);
        Ui.pad(content, 14, 6);
        orderCartRouteButton = orderChoiceButton(R.string.order_purchase_route,
                this::chooseOrderPurchaseRoute);
        content.addView(orderCartRouteButton, fieldSize(4));
        orderCartRepresentativeButton = orderChoiceButton(R.string.order_choose_representative,
                () -> chooseOrderChoice(orderRepresentatives, R.string.order_choose_representative,
                        choice -> { orderRepresentativeId = choice.id; updateOrderSelectors(); }));
        content.addView(orderCartRepresentativeButton, fieldSize(4));
        refreshOrderCartRoute();
        ScrollView scroll = new ScrollView(this);
        orderCartLinesView = Ui.column(this);
        scroll.addView(orderCartLinesView);
        int visibleHeight = Math.min(400, Math.max(130,
                getResources().getConfiguration().screenHeightDp - 300));
        int desiredHeight = Math.min(visibleHeight, Math.max(150, orderCart.size() * 146));
        content.addView(scroll, new LinearLayout.LayoutParams(-1, dp(desiredHeight)));
        orderCartTotalView = Ui.text(this, orderQuoteLabel(), 17, Ui.INK, true);
        Ui.pad(orderCartTotalView, 10, 10);
        orderCartTotalView.setBackground(Ui.bg(Ui.TASK_ACTIVE_TINT, 10, this));
        content.addView(orderCartTotalView);
        TextView disclaimer = Ui.text(this, getString(R.string.order_quote_disclaimer),
                12, Ui.MUTED, false);
        content.addView(disclaimer);
        orderCartDialog = new AlertDialog.Builder(this).setTitle(R.string.order_cart)
                .setView(content)
                .setPositiveButton(R.string.order_submit, (dialog, which) -> chooseOrderRoom())
                .setNeutralButton(R.string.order_add_more, (dialog, which) -> { })
                .setNegativeButton(R.string.task_close, null).create();
        orderCartDialog.setOnDismissListener(dialog -> {
            orderCartDialog = null;
            orderCartLinesView = null;
            orderCartTotalView = null;
            orderCartRouteButton = null;
            orderCartRepresentativeButton = null;
        });
        renderOrderCartLines();
        orderCartDialog.show();
        Ui.decorateDialog(orderCartDialog);
        if (orderCartDialog.getWindow() != null) {
            orderCartDialog.getWindow().setGravity(Gravity.BOTTOM);
            orderCartDialog.getWindow().setLayout(-1, -2);
        }
        orderCartDialog.getButton(AlertDialog.BUTTON_POSITIVE)
                .setEnabled(!orderCart.isEmpty() && !hasPendingOrder());
    }

    private void renderOrderCartLines() {
        if (orderCartLinesView == null) return;
        orderCartLinesView.removeAllViews();
        if (lastRemovedOrderLine != null && orderCart.size() < 100
                && orderLineForProduct(lastRemovedOrderLine.option.productId) == null) {
            LinearLayout undo = Ui.row(this);
            TextView removed = Ui.text(this, getString(R.string.order_removed_product,
                    lastRemovedOrderLine.option.product), 12, Ui.MUTED, false);
            undo.addView(removed, new LinearLayout.LayoutParams(0, -2, 1));
            Button restore = orderQuantityAction(getString(R.string.order_undo),
                    R.string.order_undo, lastRemovedOrderLine.option.product, () -> {
                        OrderCartLine line = lastRemovedOrderLine;
                        if (line == null || orderLineForProduct(line.option.productId) != null) return;
                        orderCart.put(line.option.id, line);
                        lastRemovedOrderLine = null;
                        afterOrderCartChange(true);
                    });
            undo.addView(restore, new LinearLayout.LayoutParams(dp(80), dp(48)));
            orderCartLinesView.addView(undo);
        }
        if (orderCart.isEmpty()) {
            orderCartLinesView.addView(Ui.text(this, getString(R.string.order_empty_cart),
                    14, Ui.MUTED, false));
        }
        for (OrderCartLine line : new ArrayList<>(orderCart.values())) {
            LinearLayout row = Ui.column(this);
            Ui.pad(row, 10, 9);
            row.setBackground(Ui.outline(Color.WHITE, Ui.LINE, 12, this));
            LinearLayout heading = Ui.row(this);
            TextView product = Ui.text(this, line.option.product, 15, Ui.INK, true);
            product.setMaxLines(2);
            product.setEllipsize(android.text.TextUtils.TruncateAt.END);
            heading.addView(product, new LinearLayout.LayoutParams(0, -2, 1));
            FrameLayout remove = Ui.iconButton(this, "close", getString(R.string.order_remove)
                    + " " + line.option.product);
            remove.setOnClickListener(v -> removeOrderOption(line.option.id));
            heading.addView(remove, new LinearLayout.LayoutParams(dp(48), dp(48)));
            row.addView(heading);
            row.addView(Ui.text(this, orderOptionLabel(line.option), 12, Ui.MUTED, false));
            LinearLayout controls = Ui.row(this);
            controls.setGravity(Gravity.END);
            controls.addView(orderQuantityStepper(line), new LinearLayout.LayoutParams(-2, dp(48)));
            row.addView(controls);
            LinearLayout.LayoutParams rowSize = new LinearLayout.LayoutParams(-1, -2);
            rowSize.setMargins(0, 0, 0, dp(8));
            orderCartLinesView.addView(row, rowSize);
        }
        if (orderCartDialog != null && orderCartDialog.isShowing())
            orderCartDialog.getButton(AlertDialog.BUTTON_POSITIVE)
                    .setEnabled(!orderCart.isEmpty() && !hasPendingOrder());
        refreshOrderQuoteLabels();
    }

    private void chooseOrderRoom() {
        if (!orderCanCreate || !verified || account == null || hasPendingOrder() || orderCompanyId == 0
                || orderMine || orderReceiving || orderCart.isEmpty()
                || !"orders".equals(visibleSection)) {
            orderNotice.setText(R.string.order_pending_blocks_new);
            return;
        }
        if (v2Busy) {
            orderNotice.setText(R.string.order_room_loading);
            final AccountScope scopedAccount = account;
            final int revision = orderCartRevision;
            handler.postDelayed(() -> {
                if (scopedAccount == account && revision == orderCartRevision)
                    chooseOrderRoom();
            }, 400);
            return;
        }
        final AccountScope scopedAccount = account;
        final long companyId = orderCompanyId;
        orderNotice.setText(R.string.order_room_loading);
        fetchV2("GET", V2_ROOMS, null, (status, body) -> {
            if (handleV2TransportFailure(status)) return;
            if (scopedAccount != account || companyId != orderCompanyId) return;
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                JSONArray listed = body.getJSONArray("rooms");
                if (listed.length() > 100) throw new IllegalArgumentException();
                List<Room> available = new ArrayList<>();
                Set<Long> seen = new HashSet<>();
                for (int i = 0; i < listed.length(); i++) {
                    JSONObject item = listed.getJSONObject(i);
                    long id = positiveId(item.get("id"));
                    long roomCompany = positiveId(item.get("company_id"));
                    long membership = positiveId(item.get("membership_id"));
                    String name = item.getString("name");
                    if (!seen.add(id) || !v1Companies.contains(roomCompany)
                            || name.trim().isEmpty()
                            || name.getBytes(StandardCharsets.UTF_8).length > 256
                            || name.indexOf('\n') >= 0 || name.indexOf('\r') >= 0)
                        throw new IllegalArgumentException();
                    if (roomCompany == companyId)
                        available.add(new Room(id, roomCompany, membership, name));
                }
                String[] names = new String[available.size() + 1];
                names[0] = getString(R.string.order_without_room);
                for (int i = 0; i < available.size(); i++) names[i + 1] = available.get(i).name;
                orderNotice.setText("");
                new AlertDialog.Builder(this).setTitle(R.string.order_choose_room)
                        .setItems(names, (dialog, index) -> {
                            if (scopedAccount != account || companyId != orderCompanyId
                                    || orderMine || orderReceiving) return;
                            submitOrder(index == 0 ? 0 : available.get(index - 1).id);
                        }).setNegativeButton(R.string.chat_v2_cancel, null).show();
            } catch (Exception invalid) {
                orderNotice.setText(status == 403 ? R.string.order_denied
                        : R.string.order_room_load_failed);
            }
        });
    }

    private static final class PendingOrder {
        final String scope, raw, uuid, purchaseRoute;
        final long companyId, warehouseId, representativeId, roomId;
        PendingOrder(AccountScope account, String raw) throws Exception {
            if (account == null || raw == null || raw.length() > 24000)
                throw new IllegalArgumentException();
            JSONObject payload = new JSONObject(raw);
            boolean hasRoom = payload.has("room_id");
            boolean hasRoute = payload.has("purchase_route");
            if (payload.length() != 6 + (hasRoom ? 1 : 0) + (hasRoute ? 1 : 0)
                    || positiveId(payload.get("api_version")) != 2)
                throw new IllegalArgumentException();
            scope = account.key;
            this.raw = raw;
            uuid = payload.getString("client_uuid");
            if (!UUID.fromString(uuid).toString().equals(uuid) || UUID.fromString(uuid).version() != 4)
                throw new IllegalArgumentException();
            companyId = positiveId(payload.get("company_id"));
            warehouseId = positiveId(payload.get("warehouse_id"));
            Object rep = payload.get("representative_partner_id");
            representativeId = rep == JSONObject.NULL ? 0 : positiveId(rep);
            purchaseRoute = hasRoute ? payload.getString("purchase_route") : "representative";
            if (!("representative".equals(purchaseRoute) || "cash".equals(purchaseRoute)
                    || "bank_transfer".equals(purchaseRoute))
                    || (!"representative".equals(purchaseRoute) && representativeId != 0))
                throw new IllegalArgumentException();
            Object room = hasRoom ? payload.get("room_id") : JSONObject.NULL;
            roomId = room == JSONObject.NULL ? 0 : positiveId(room);
            JSONArray lines = payload.getJSONArray("lines");
            if (lines.length() < 1 || lines.length() > 100) throw new IllegalArgumentException();
            Set<Long> ids = new HashSet<>();
            for (int i = 0; i < lines.length(); i++) {
                JSONObject line = lines.getJSONObject(i);
                if (line.length() != 2 || !ids.add(positiveId(line.get("option_id"))))
                    throw new IllegalArgumentException();
                normalizeOrderQuantity(line.getString("quantity"));
            }
        }
    }

    private static final class PendingReceipt {
        final String scope, raw, stored, uuid;
        final long orderId, companyId;
        PendingReceipt(AccountScope account, long orderId, String raw) throws Exception {
            if (account == null || raw == null || raw.length() > 24000)
                throw new IllegalArgumentException();
            this.scope = account.key;
            this.orderId = positiveId(orderId);
            this.raw = raw;
            stored = orderId + "\n" + raw;
            JSONObject payload = new JSONObject(raw);
            if (payload.length() != 4 || positiveId(payload.get("api_version")) != 2)
                throw new IllegalArgumentException();
            companyId = positiveId(payload.get("company_id"));
            uuid = payload.getString("client_uuid");
            UUID parsed = UUID.fromString(uuid);
            if (!parsed.toString().equals(uuid) || parsed.version() != 4)
                throw new IllegalArgumentException();
            JSONArray lines = payload.getJSONArray("lines");
            if (lines.length() == 0 || lines.length() > 100)
                throw new IllegalArgumentException();
            Set<Long> ids = new HashSet<>();
            for (int i = 0; i < lines.length(); i++) {
                JSONObject line = lines.getJSONObject(i);
                if (line.length() != 3 || !ids.add(positiveId(line.get("line_id")))
                        || !line.getString("actual_qty").matches("[0-9]{1,6}\\.[0-9]{2}")
                        || !line.getString("actual_price").matches("[0-9]{1,12}\\.[0-9]{2}"))
                    throw new IllegalArgumentException();
            }
        }
        PendingReceipt(AccountScope account, String stored) throws Exception {
            this(account, parseStoredOrderId(stored), parseStoredPayload(stored));
            if (!this.stored.equals(stored)) throw new IllegalArgumentException();
        }
        private static long parseStoredOrderId(String stored) {
            if (stored == null || stored.length() > 24100) throw new IllegalArgumentException();
            int split = stored.indexOf('\n');
            if (split < 1 || split > 10) throw new IllegalArgumentException();
            return positiveId(Long.valueOf(stored.substring(0, split)));
        }
        private static String parseStoredPayload(String stored) {
            int split = stored.indexOf('\n');
            if (split < 1) throw new IllegalArgumentException();
            return stored.substring(split + 1);
        }
    }

    private boolean hasPendingReceipt() {
        return account != null && receiptConfirmPreferences().contains(account.key);
    }

    private String receiptShareKey(AccountScope scope, long orderId) {
        return scope.key + ":" + orderId;
    }

    private long pendingReceiptShareCompany(AccountScope scope, long orderId) {
        try { return receiptSharePreferences().getLong(receiptShareKey(scope, orderId), 0); }
        catch (ClassCastException invalid) { return 0; }
    }

    private boolean hasPendingReceiptShare() {
        if (account == null) return false;
        String prefix = account.key + ":";
        for (Map.Entry<String, ?> entry : receiptSharePreferences().getAll().entrySet()) {
            if (!entry.getKey().startsWith(prefix)) continue;
            try {
                positiveId(Long.parseLong(entry.getKey().substring(prefix.length())));
                if (entry.getValue() instanceof Long) {
                    positiveId(entry.getValue());
                    return true;
                }
            } catch (Exception invalid) { /* Ignore malformed local marker. */ }
        }
        return false;
    }

    private void reviewPendingReceiptShares() {
        if (account == null || !verified || !orderCanReceive) return;
        final AccountScope scopedAccount = account;
        String prefix = scopedAccount.key + ":";
        List<long[]> pending = new ArrayList<>();
        for (Map.Entry<String, ?> entry : receiptSharePreferences().getAll().entrySet()) {
            if (!entry.getKey().startsWith(prefix)) continue;
            try {
                long orderId = positiveId(Long.parseLong(entry.getKey().substring(prefix.length())));
                if (!(entry.getValue() instanceof Long)) continue;
                long companyId = positiveId(entry.getValue());
                pending.add(new long[] {orderId, companyId});
            } catch (Exception invalid) { /* Corrupt local marker is never sent. */ }
        }
        pending.sort((first, second) -> Long.compare(first[0], second[0]));
        if (pending.isEmpty()) {
            orderNotice.setText(R.string.receipt_share_failed);
            return;
        }
        String[] labels = new String[pending.size()];
        for (int i = 0; i < pending.size(); i++)
            labels[i] = getString(R.string.receipt_share_pending_item,
                    String.valueOf(pending.get(i)[0]));
        Ui.decorateDialog(new AlertDialog.Builder(this)
                .setTitle(R.string.receipt_share_review_pending)
                .setItems(labels, (dialog, index) -> {
                    if (account != scopedAccount) return;
                    long[] selected = pending.get(index);
                    shareConfirmedReceipt(selected[0], selected[1], scopedAccount);
                }).setNegativeButton(R.string.task_close, null).show());
    }

    private static String receiptErrorCode(int status, JSONObject body) {
        JSONObject error = status == 409 && body != null ? body.optJSONObject("error") : null;
        return error == null ? "" : error.optString("code", "");
    }

    private int receiptFailureMessage(int status, String code) {
        if (status != 409) return R.string.receipt_uncertain;
        if ("invalid_quantity".equals(code)) return R.string.receipt_invalid_quantity;
        if ("receipt_invalid".equals(code)) return R.string.receipt_invalid_odoo;
        if ("receipt_closed".equals(code)) return R.string.receipt_closed;
        if ("retry".equals(code)) return R.string.receipt_retry_same;
        if ("receipt_unavailable".equals(code)) return R.string.receipt_unavailable_state;
        return R.string.receipt_conflict;
    }

    private void editRejectedPendingReceipt(PendingReceipt pending, AccountScope scopedAccount) {
        if (!verified || account != scopedAccount || !orderCanReceive
                || !orderReceiving || orderCompanyId != pending.companyId || v2Busy
                || !pending.stored.equals(receiptConfirmPreferences()
                        .getString(pending.scope, null))) return;
        final int serial = orderViewSerial;
        orderNotice.setText(R.string.receipt_loading);
        fetchV2("GET", V2_ORDERS + "/receipts/" + pending.orderId
                + "?company_id=" + pending.companyId, null, (status, body) -> {
            if (handleV2TransportFailure(status)) return;
            if (!receiptContext(scopedAccount, pending.companyId, serial)
                    || !pending.stored.equals(receiptConfirmPreferences()
                            .getString(pending.scope, null))) return;
            if (status == 403) { recoverOrderCompanyAccess(pending.companyId); return; }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2)
                    throw new IllegalArgumentException();
                ReceiptSummary detail = new ReceiptSummary(body.getJSONObject("order"));
                if (detail.id != pending.orderId || detail.companyId != pending.companyId)
                    throw new IllegalArgumentException();
                JSONArray raw = body.getJSONArray("lines");
                if (raw.length() == 0 || raw.length() > 100) throw new IllegalArgumentException();
                List<ReceiptLine> lines = new ArrayList<>();
                Set<Long> seen = new HashSet<>();
                for (int i = 0; i < raw.length(); i++) {
                    ReceiptLine line = new ReceiptLine(raw.getJSONObject(i));
                    if (!seen.add(line.id)) throw new IllegalArgumentException();
                    lines.add(line);
                }
                orderNotice.setText("");
                showReceiptForm(detail, lines, scopedAccount, pending.companyId, serial, pending);
            } catch (Exception unavailable) {
                orderNotice.setText(status == 404 || status == 409
                        ? R.string.receipt_conflict : R.string.receipt_load_failed);
            }
        });
    }

    private void sendPendingReceipt(PendingReceipt pending) {
        if (!verified || account == null || v2Busy || ordersDenied
                || !orderCanReceive
                || !account.key.equals(pending.scope)
                || !pending.stored.equals(receiptConfirmPreferences()
                        .getString(pending.scope, null))) return;
        orderNotice.setText(R.string.receipt_sending);
        receiptPendingButton.setEnabled(false);
        final AccountScope scopedAccount = account;
        fetchV2("POST", V2_ORDERS + "/receipts/" + pending.orderId + "/confirm",
                pending.raw, (status, body) -> {
            receiptPendingButton.setEnabled(true);
            if (handleV2TransportFailure(status, true)) return;
            if (scopedAccount != account) return;
            if (status == 403) {
                orderCapabilityOptions = null;
                orderCapabilityAccount = null;
                discoverOrders();
                return;
            }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2
                        || !pending.uuid.equals(body.getString("client_uuid"))
                        || !(body.get("replayed") instanceof Boolean))
                    throw new IllegalArgumentException();
                JSONObject receipt = body.getJSONObject("receipt");
                if (positiveId(receipt.get("order_id")) != pending.orderId
                        || positiveId(receipt.get("company_id")) != pending.companyId
                        || !"purchased".equals(receipt.getString("state")))
                    throw new IllegalArgumentException();
                String total = receipt.getString("actual_total");
                String currency = boundedTaskText(receipt.getString("currency_symbol"), 16, false);
                if (!total.matches("[0-9]{1,14}\\.[0-9]{2}")
                        || !pending.stored.equals(receiptConfirmPreferences()
                                .getString(pending.scope, null))
                        || !receiptSharePreferences().edit()
                                .putLong(receiptShareKey(scopedAccount, pending.orderId),
                                        pending.companyId).commit()
                        || !receiptConfirmPreferences().edit().remove(pending.scope).commit())
                    throw new IllegalArgumentException();
                updateOrderSelectors();
                String message = getString(R.string.receipt_confirmed,
                        boundedTaskText(receipt.getString("name"), 160, true), total, currency);
                orderNotice.setText(message);
                new AlertDialog.Builder(this).setTitle(R.string.receipt_confirm)
                        .setMessage(message)
                        .setPositiveButton(R.string.receipt_share_result,
                                (dialog, which) -> shareConfirmedReceipt(pending.orderId,
                                        pending.companyId, scopedAccount))
                        .setNegativeButton(R.string.task_close, null).show();
                if (orderReceiving && "orders".equals(visibleSection)) loadReceipts(0);
            } catch (Exception invalid) {
                String code = receiptErrorCode(status, body);
                int message = receiptFailureMessage(status, code);
                orderNotice.setText(message);
                updateOrderSelectors();
                if (status == 409 && ("invalid_quantity".equals(code)
                        || "receipt_invalid".equals(code))) {
                    Ui.decorateDialog(new AlertDialog.Builder(this)
                            .setTitle(R.string.receipt_review_pending)
                            .setMessage(message)
                            .setPositiveButton(R.string.receipt_edit_values,
                                    (dialog, which) -> editRejectedPendingReceipt(pending, scopedAccount))
                            .setNegativeButton(R.string.task_close, null).show());
                }
            }
        });
    }

    private void shareConfirmedReceipt(long orderId, long companyId,
            AccountScope scopedAccount) {
        if (!verified || account != scopedAccount || !orderCanReceive
                || !v1Companies.contains(companyId) || v2Busy
                || pendingReceiptShareCompany(scopedAccount, orderId) != companyId) {
            showReceiptShareRetry(orderId, companyId, scopedAccount,
                    R.string.receipt_share_failed);
            return;
        }
        try {
            JSONObject payload = new JSONObject();
            payload.put("api_version", 2);
            payload.put("company_id", companyId);
            orderNotice.setText(R.string.receipt_share_sending);
            fetchV2("POST", V2_ORDERS + "/receipts/" + orderId + "/share",
                    payload.toString(), (status, body) -> {
                if (account != scopedAccount) return;
                if (status == 401) { logout(); return; }
                if (status == 0) handleV2TransportFailure(status, true);
                try {
                    if (status != 200 || body == null
                            || positiveId(body.get("api_version")) != 2
                            || positiveId(body.get("order_id")) != orderId
                            || positiveId(body.get("room_id")) <= 0
                            || positiveId(body.get("message_id")) <= 0
                            || !body.getBoolean("shared")
                            || !(body.get("replayed") instanceof Boolean)
                            || pendingReceiptShareCompany(scopedAccount, orderId) != companyId
                            || !receiptSharePreferences().edit()
                                    .remove(receiptShareKey(scopedAccount, orderId)).commit())
                        throw new IllegalArgumentException();
                    updateOrderSelectors();
                    orderNotice.setText(R.string.receipt_share_sent);
                    Ui.decorateDialog(new AlertDialog.Builder(this)
                            .setMessage(R.string.receipt_share_sent)
                            .setPositiveButton(R.string.task_close, null).show());
                } catch (Exception failed) {
                    JSONObject error = body == null ? null : body.optJSONObject("error");
                    String code = error == null ? "" : error.optString("code", "");
                    showReceiptShareRetry(orderId, companyId, scopedAccount,
                            "room_unavailable".equals(code)
                                    ? R.string.receipt_share_room_unavailable
                                    : R.string.receipt_share_failed);
                }
            });
        } catch (Exception invalid) {
            showReceiptShareRetry(orderId, companyId, scopedAccount,
                    R.string.receipt_share_failed);
        }
    }

    private void showReceiptShareRetry(long orderId, long companyId,
            AccountScope scopedAccount, int messageId) {
        if (account != scopedAccount) return;
        if (orderNotice != null) orderNotice.setText(messageId);
        Ui.decorateDialog(new AlertDialog.Builder(this).setTitle(R.string.receipt_share_result)
                .setMessage(messageId)
                .setPositiveButton(R.string.receipt_share_retry,
                        (dialog, which) -> shareConfirmedReceipt(orderId,
                                companyId, scopedAccount))
                .setNegativeButton(R.string.task_close, null).show());
    }

    private void reviewPendingReceipt() {
        if (!hasPendingReceipt() || account == null) return;
        final AccountScope scopedAccount = account;
        final String stored = receiptConfirmPreferences().getString(scopedAccount.key, null);
        try {
            PendingReceipt pending = new PendingReceipt(scopedAccount, stored);
            new AlertDialog.Builder(this).setTitle(R.string.receipt_review_pending)
                    .setMessage(getString(R.string.receipt_pending_detail,
                            String.valueOf(pending.orderId), pending.uuid))
                    .setPositiveButton(R.string.task_retry_same,
                            (dialog, which) -> sendPendingReceipt(pending))
                    .setNeutralButton(R.string.task_delete_local,
                            (dialog, which) -> discardPendingReceipt(scopedAccount, stored))
                    .setNegativeButton(R.string.task_close, null).show();
        } catch (Exception invalid) {
            new AlertDialog.Builder(this).setTitle(R.string.receipt_review_pending)
                    .setMessage(R.string.receipt_pending_unreadable)
                    .setPositiveButton(R.string.task_delete_local,
                            (dialog, which) -> discardPendingReceipt(scopedAccount, stored))
                    .setNegativeButton(R.string.task_close, null).show();
        }
    }

    private void discardPendingReceipt(AccountScope scopedAccount, String stored) {
        new AlertDialog.Builder(this).setTitle(R.string.task_delete_local)
                .setMessage(R.string.receipt_delete_warning)
                .setPositiveButton(R.string.task_delete_local, (dialog, which) -> {
                    if (account != scopedAccount || v2Busy || !stored.equals(
                            receiptConfirmPreferences().getString(scopedAccount.key, null))) return;
                    if (!receiptConfirmPreferences().edit().remove(scopedAccount.key).commit()) {
                        orderNotice.setText(R.string.receipt_save_failed);
                        return;
                    }
                    updateOrderSelectors();
                    orderNotice.setText(R.string.receipt_local_deleted);
                    if (orderReceiving && "orders".equals(visibleSection)) loadReceipts(0);
                }).setNegativeButton(R.string.chat_v2_cancel, null).show();
    }

    private boolean hasPendingOrder() {
        return account != null && orderCreatePreferences().contains(account.key);
    }

    private void submitOrder(long roomId) {
        if (!orderCanCreate || !verified || v2Busy || account == null || hasPendingOrder()
                || orderMine || orderReceiving) {
            orderNotice.setText(R.string.order_pending_blocks_new);
            return;
        }
        if (orderCompanyId == 0 || orderWarehouseId == 0 || orderCart.isEmpty()) {
            orderNotice.setText(R.string.order_missing_fields);
            return;
        }
        if (!orderPurchaseRoutes.contains(orderPurchaseRoute)) {
            orderNotice.setText(R.string.order_load_failed);
            return;
        }
        if ("representative".equals(orderPurchaseRoute) && orderRepresentatives.isEmpty()) {
            orderNotice.setText(R.string.order_no_representative);
            return;
        }
        if ("representative".equals(orderPurchaseRoute)
                && orderRepresentatives.size() > 1 && orderRepresentativeId == 0) {
            orderNotice.setText(R.string.order_choose_representative);
            return;
        }
        try {
            JSONArray lines = new JSONArray();
            for (OrderCartLine line : orderCart.values()) {
                JSONObject item = new JSONObject();
                item.put("option_id", line.option.id);
                item.put("quantity", normalizeOrderQuantity(line.quantity));
                lines.put(item);
            }
            JSONObject payload = new JSONObject();
            payload.put("api_version", 2);
            payload.put("company_id", orderCompanyId);
            payload.put("warehouse_id", orderWarehouseId);
            payload.put("representative_partner_id",
                    !"representative".equals(orderPurchaseRoute)
                            || orderRepresentatives.size() == 1
                            ? JSONObject.NULL : orderRepresentativeId);
            if (!"representative".equals(orderPurchaseRoute))
                payload.put("purchase_route", orderPurchaseRoute);
            payload.put("client_uuid", UUID.randomUUID().toString());
            payload.put("lines", lines);
            payload.put("room_id", roomId == 0 ? JSONObject.NULL : roomId);
            PendingOrder pending = new PendingOrder(account, payload.toString());
            if (!orderCreatePreferences().edit().putString(account.key, pending.raw).commit()) {
                orderNotice.setText(R.string.order_save_failed);
                return;
            }
            updateOrderSelectors();
            sendPendingOrder(pending);
        } catch (Exception invalid) { orderNotice.setText(R.string.order_invalid); }
    }

    private void sendPendingOrder(PendingOrder pending) {
        if (!orderCanCreate || !verified || v2Busy || account == null || !account.key.equals(pending.scope)
                || !pending.raw.equals(orderCreatePreferences().getString(pending.scope, null))) return;
        orderNotice.setText(R.string.order_sending);
        orderPendingButton.setEnabled(false);
        final AccountScope scopedAccount = account;
        fetchV2("POST", V2_ORDERS, pending.raw, (status, body) -> {
            orderPendingButton.setEnabled(true);
            if (handleV2TransportFailure(status, true)) return;
            if (scopedAccount != account) return;
            if (status == 403) {
                orderCapabilityOptions = null;
                orderCapabilityAccount = null;
                discoverOrders();
                return;
            }
            try {
                if (status != 200 || body == null || positiveId(body.get("api_version")) != 2
                        || !(body.get("replayed") instanceof Boolean)
                        || !pending.uuid.equals(body.getString("client_uuid")))
                    throw new IllegalArgumentException();
                OrderSummary created = new OrderSummary(body.getJSONObject("order"));
                if ((!body.getBoolean("replayed") && !"sent".equals(created.state))
                        || !pending.purchaseRoute.equals(created.purchaseRoute)
                        || (pending.representativeId > 0
                                && created.representativeId != pending.representativeId)
                        || created.roomId != pending.roomId
                        || created.total.isEmpty()
                        || !pending.raw.equals(orderCreatePreferences()
                                .getString(pending.scope, null))
                        || !orderCreatePreferences().edit().remove(pending.scope).commit())
                    throw new IllegalArgumentException();
                orderCart.clear();
                lastRemovedOrderLine = null;
                invalidateOrderQuote();
                updateOrderSelectors();
                String message = getString(body.getBoolean("replayed")
                        ? R.string.order_confirmed : R.string.order_sent, created.name)
                        + "\n" + getString(R.string.order_total, created.total, created.currency);
                if (pending.roomId != 0)
                    message += "\n" + getString(R.string.order_room_posted);
                orderNotice.setText(message);
                new AlertDialog.Builder(this).setTitle(R.string.chat_v2_orders)
                        .setMessage(message).setPositiveButton(R.string.task_close, null).show();
                if ("orders".equals(visibleSection)) {
                    orderMine = true;
                    orderReceiving = false;
                    updateOrderSelectors();
                    loadOrderSummaries(0);
                }
            } catch (Exception invalid) {
                updateOrderSelectors();
                JSONObject error = body == null ? null : body.optJSONObject("error");
                String code = error == null ? "" : error.optString("code", "");
                if (("room_unavailable".equals(code) || "membership_changed".equals(code)
                        || "room_message_too_long".equals(code))
                        && pending.raw.equals(orderCreatePreferences().getString(pending.scope, null))) {
                    if (!orderCreatePreferences().edit().remove(pending.scope).commit()) {
                        orderNotice.setText(R.string.order_save_failed);
                        return;
                    }
                    updateOrderSelectors();
                    orderNotice.setText("room_message_too_long".equals(code)
                            ? R.string.order_room_message_long : R.string.order_room_unavailable);
                    return;
                }
                orderNotice.setText("no_representative".equals(code)
                        ? R.string.order_no_representative
                        : "representative_required".equals(code)
                        ? R.string.order_choose_representative
                        : status == 403 ? R.string.order_denied
                        : R.string.order_create_uncertain);
            }
        });
    }

    private void reviewPendingOrder() {
        if (!hasPendingOrder() || account == null) return;
        if (v2Busy) { orderNotice.setText(R.string.order_sending); return; }
        final AccountScope scopedAccount = account;
        final String raw = orderCreatePreferences().getString(scopedAccount.key, null);
        try {
            PendingOrder pending = new PendingOrder(scopedAccount, raw);
            new AlertDialog.Builder(this).setTitle(R.string.order_review_pending)
                    .setMessage(getString(R.string.order_pending_detail,
                            orderChoiceName(orderCompanies, pending.companyId,
                                    R.string.order_choose_company),
                            String.valueOf(pending.warehouseId),
                            orderRouteLabel(pending.purchaseRoute),
                            pending.uuid))
                    .setPositiveButton(R.string.task_retry_same, (dialog, which) ->
                            sendPendingOrder(pending))
                    .setNeutralButton(R.string.task_delete_local, (dialog, which) ->
                            confirmDiscardPendingOrder(scopedAccount, raw))
                    .setNegativeButton(R.string.task_close, null).show();
        } catch (Exception invalid) {
            new AlertDialog.Builder(this).setTitle(R.string.order_review_pending)
                    .setMessage(R.string.order_pending_unreadable)
                    .setPositiveButton(R.string.task_delete_local, (dialog, which) ->
                            confirmDiscardPendingOrder(scopedAccount, raw))
                    .setNegativeButton(R.string.task_close, null).show();
        }
    }

    private void confirmDiscardPendingOrder(AccountScope scopedAccount, String raw) {
        new AlertDialog.Builder(this).setTitle(R.string.task_delete_local)
                .setMessage(R.string.order_delete_warning)
                .setPositiveButton(R.string.task_delete_local, (dialog, which) -> {
                    if (account == null || !account.key.equals(scopedAccount.key) || v2Busy) return;
                    String current = orderCreatePreferences().getString(scopedAccount.key, null);
                    if (!(raw == null ? current == null : raw.equals(current))
                            || !orderCreatePreferences().edit().remove(scopedAccount.key).commit()) {
                        orderNotice.setText(R.string.order_save_failed);
                        return;
                    }
                    updateOrderSelectors();
                    orderNotice.setText(R.string.order_local_deleted);
                    if (orderMine) loadOrderSummaries(0);
                }).setNegativeButton(R.string.chat_v2_cancel, null).show();
    }

    private void showLoginForm() {
        verified = false;
        BChatPushState.clearAccount(this);
        clearChatView();
        layout.setPadding(dp(20), dp(16), dp(20), dp(16));
        account = null;
        v1Companies.clear();
        csrfToken = null;
        nativeForm.setVisibility(View.VISIBLE);
        if (loginReleaseFooter != null) loginReleaseFooter.setVisibility(View.VISIBLE);
        shell.setVisibility(View.GONE);
        chatRoot.setVisibility(View.GONE);
        status.setVisibility(View.VISIBLE);
        localExit.setVisibility(View.GONE);
        hideWeb();
    }

    private void showShell() {
        layout.setPadding(dp(20), dp(16), dp(20), dp(16));
        nativeForm.setVisibility(View.GONE);
        if (loginReleaseFooter != null) loginReleaseFooter.setVisibility(View.GONE);
        shell.setVisibility(View.VISIBLE);
        chatRoot.setVisibility(View.GONE);
        status.setVisibility(View.GONE);
        localExit.setVisibility(View.GONE);
        shellNotice.setText(shareUnavailablePending ? R.string.auth_share_unavailable : R.string.auth_shell_unavailable);
        shellRetry.setVisibility(View.GONE);
    }

    private void showShareNotice(Intent intent) {
        if (intent == null || !(isExternalShare(intent)
                || intent.getBooleanExtra(EXTRA_SHARE_UNAVAILABLE, false))) return;
        // A shared URI is never read, imported, saved, or sent to the old demo.
        shareUnavailablePending = true;
        if (verified && chatRoot != null && chatRoot.getVisibility() == View.VISIBLE)
            chatNotice.setText(R.string.auth_share_unavailable);
        else if (verified && shellNotice != null) shellNotice.setText(R.string.auth_share_unavailable);
        else if (status != null) status.setText(R.string.auth_share_unavailable);
        setIntent(new Intent(Intent.ACTION_MAIN).setClass(this, OdooIdentityActivity.class));
    }

    private void fail(int message) {
        if (closed) return;
        if (loggingOut) {
            loggingOut = false;
            status.setVisibility(View.VISIBLE);
            status.setText(R.string.auth_logout_unconfirmed);
            nativeForm.setVisibility(View.GONE);
            if (loginReleaseFooter != null) loginReleaseFooter.setVisibility(View.GONE);
            shell.setVisibility(View.GONE);
            hideWeb();
            localExit.setVisibility(View.VISIBLE);
            return;
        }
        ++epoch;
        probing = false;
        submitting = false;
        closePort();
        closeV2Port();
        passwordInput.setText("");
        showLoginForm();
        signIn.setEnabled(true); // If the page is unavailable, the next tap retries loading it.
        status.setText(message);
    }

    private void logout() {
        if (closed || loggingOut) return;
        purgeHistory();
        pendingPush = null;
        pendingNotificationTaskId = 0;
        String pushInstallation = BChatPushState.accountKey(this) != null
                ? BChatPushState.installationId(this) : null;
        String pushCsrf = csrfToken;
        BChatPushState.clearAccount(this);
        final boolean[] navigationStarted = {false};
        Runnable navigate = () -> {
            if (navigationStarted[0] || closed) return;
            navigationStarted[0] = true;
            openWeb(LOGOUT);
        };
        ++epoch;
        probing = false;
        submitting = false;
        verified = false;
        closePort();
        closeV2Port();
        clearChatView();
        account = null;
        v1Companies.clear();
        csrfToken = null;
        loggingOut = true;
        layout.setPadding(dp(20), dp(16), dp(20), dp(16));
        localExit.setVisibility(View.GONE);
        nativeForm.setVisibility(View.GONE);
        if (loginReleaseFooter != null) loginReleaseFooter.setVisibility(View.GONE);
        shell.setVisibility(View.GONE);
        chatRoot.setVisibility(View.GONE);
        status.setVisibility(View.VISIBLE);
        status.setText(R.string.auth_logging_out);
        unregisterPushBestEffort(pushInstallation, pushCsrf, navigate);
        // openWeb preserves loggingOut; cookies are cleared only after the server redirects to login.
    }

    private void closePort() {
        if (replyPort != null) { replyPort.close(); replyPort = null; }
    }

    private void releaseWeb() {
        cancelBridgeNavigationTimeout();
        closeLiveSync();
        closeMediaUpload();
        closeMediaRead();
        ++webEpoch;
        ++pageEpoch;
        closePort();
        closeV2Port();
        if (web != null) {
            layout.removeView(web);
            web.stopLoading();
            web.destroy();
            web = null;
        }
    }

    private void clearCookies(Runnable next) {
        CookieManager.getInstance().removeAllCookies(removed -> {
            CookieManager.getInstance().flush();
            next.run();
        });
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        capturePushTarget(intent);
        setIntent(intent);
        showShareNotice(intent);
        if (!recheckOnResume) processPendingPush();
    }

    @Override protected void onPause() {
        liveForeground = false;
        closeLiveSync();
        if (inlineAudioRoom != null && inlineAudioPlayer == null) closeMediaRead();
        stopInlineAudio();
        if (voicePreviewPlayer != null) {
            try { if (voicePreviewPlayer.isPlaying()) voicePreviewPlayer.pause(); }
            catch (IllegalStateException ignored) { }
        }
        if (mediaPreviewDialog != null) mediaPreviewDialog.dismiss();
        if (connectedVoiceRecorder != null) {
            connectedVoiceRecorder.cancel(); connectedVoiceRecorder = null;
            stopRecordingBadge();
            mediaStageBusy = false;
            mediaPickerAccount = null; mediaPickerRoom = null;
            if (mediaVoiceButton != null)
                mediaVoiceButton.setContentDescription(getString(R.string.bchat_media_record));
            if (chatNotice != null) chatNotice.setText(R.string.bchat_media_record_cancelled);
            updatePendingUi();
        }
        flushDraftSave();
        super.onPause();
    }

    @Override protected void onStop() {
        flushDraftSave();
        if (verified && mediaPickerAccount == null && groupPhotoAccount == null
                && pendingPdfDownload == null)
            recheckOnResume = true;
        super.onStop();
    }

    @Override protected void onResume() {
        super.onResume();
        liveForeground = true;
        if (recheckOnResume && verified && !closed) {
            recheckOnResume = false;
            verified = false;
            // Keep the local route during this same-account bridge recheck. If authentication
            // fails, the login and failure paths clear it; if it succeeds, verifiedAccount
            // preserves the prior confirmed route without a notification-delivery gap.
            bridgeRecoveryUsed = false;
            clearChatView();
            account = null;
            v1Companies.clear();
            csrfToken = null;
            status.setVisibility(View.VISIBLE);
            status.setText(R.string.auth_verifying);
            shell.setVisibility(View.GONE);
            chatRoot.setVisibility(View.GONE);
            openWeb(BRIDGE);
        } else {
            processPendingPush();
            if (verified) {
                lastPermissionRefreshAt = 0;
                handler.post(this::refreshPermissionSet);
            }
            if (verified && chatRoot != null && chatRoot.getVisibility() == View.VISIBLE) {
                startLiveSync();
                messageScroll.post(this::scanVisibleMessageReceipts);
            }
        }
    }

    @Override public void onBackPressed() {
        if (accountMenu != null && accountMenu.dismiss()) return;
        if (orderCompanyMenu != null && orderCompanyMenu.dismiss()) return;
        if (offlineHistory && selectedRoom != null) { showRooms(); return; }
        if (offlineHistory) { moveTaskToBack(true); return; }
        if (localExit.getVisibility() == View.VISIBLE) localExit.performClick();
        else if (verified && chatRoot.getVisibility() == View.VISIBLE && !"chats".equals(visibleSection))
            switchSection("chats");
        else if (verified && chatRoot.getVisibility() == View.VISIBLE && selectedRoom != null) showRooms();
        else if (verified && chatRoot.getVisibility() == View.VISIBLE) moveTaskToBack(true);
        else if (verified || loggingOut || (web != null && web.getUrl() != null
                && Uri.parse(web.getUrl()).getPath().endsWith("/web/login/totp"))) logout();
        else finish();
    }

    @Override protected void onDestroy() {
        stopInlineAudio();
        if (connectedWaveforms != null) connectedWaveforms.close();
        clearVoicePreview();
        flushDraftSave();
        closed = true;
        if (BuildConfig.BCHAT_PUSH_ENABLED) BChatPushState.stopObserving(this, pushTokenListener);
        ++epoch;
        if (profileDialog != null) { profileDialog.dismiss(); profileDialog = null; }
        if (groupCreateDialog != null) { groupCreateDialog.dismiss(); groupCreateDialog = null; }
        if (groupInfoDialog != null) { groupInfoDialog.dismiss(); groupInfoDialog = null; }
        if (sensitiveDetailDialog != null) { sensitiveDetailDialog.dismiss(); sensitiveDetailDialog = null; }
        if (mediaPreviewDialog != null) { mediaPreviewDialog.dismiss(); mediaPreviewDialog = null; }
        clearPendingPdf();
        clearMediaReadCache();
        releaseWeb();
        if (outbox != null) outbox.close();
        // A verified room snapshot queued just before a language change or activity close
        // must commit before this helper closes. No disk wait occurs on the UI thread.
        ConnectedHistoryCache closingCache = historyCache;
        TaskOfflineCache closingTaskCache = taskOfflineCache;
        historyWrites.execute(() -> {
            synchronized (historyStorageLock) {
                if (closingCache != null) closingCache.close();
                if (closingTaskCache != null) closingTaskCache.close();
            }
        });
        historyWrites.shutdown();
        mediaIo.shutdown();
        handler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }
}
