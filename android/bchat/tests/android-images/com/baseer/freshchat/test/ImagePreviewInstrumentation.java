package com.baseer.freshchat.test;

import android.app.*;
import android.content.*;
import android.content.pm.ProviderInfo;
import android.graphics.*;
import android.graphics.drawable.BitmapDrawable;
import android.media.ExifInterface;
import android.net.Uri;
import android.os.*;
import android.test.mock.MockContentResolver;
import android.view.*;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.*;
import com.baseer.freshchat.AttachmentSupport;
import com.baseer.freshchat.ChatStore;
import java.io.*;
import java.lang.reflect.*;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;

/** Device-only synthetic fixtures. Requires explicit disposable=true; never use on a working install. */
public final class ImagePreviewInstrumentation extends Instrumentation {
    private Activity activity;
    private Object previews;
    private Class<?> previewsClass, viewClass, readyClass;
    private LinearLayout host;
    private ChatStore isolated;
    private File stateFile;
    private String company, conversation;
    private boolean disposable;
    private final List<File> created = new ArrayList<>();
    private final List<String> results = new ArrayList<>();
    private volatile boolean uiAborted;
    private int diagnosticSequence;
    private static final long UI_TIMEOUT_MS = 30000;
    private static final int[] COLORS = {Color.RED, Color.GREEN, Color.BLUE, Color.YELLOW};
    @Override public void onCreate(Bundle args) { super.onCreate(args); disposable = args != null && "true".equals(args.getString("disposable")); start(); }
    @Override public void onStart() {
        Bundle out = new Bundle(); boolean passed = false;
        try {
            if (!disposable) throw new IllegalStateException("Use only a disposable emulator/test install with -e disposable true");
            runChecks(); passed = true;
        } catch (Throwable error) {
            out.putString("failure", causeSummary(error));
            if (activity != null && !uiAborted) captureDiagnostics("failure");
        }
        finally {
            if (activity != null && !uiAborted) try { ui(() -> {
                if (previews != null) invoke(previews, "close", new Class<?>[0]);
                // Keep the isolated store selected through asynchronous onPause/onDestroy.
                // Restoring the original store here could write the test composer into real drafts.
                activity.finish();
            }); } catch (Throwable ignored) { }
            // A timed-out, in-flight action must not race further mutations or fixture deletion.
            if (!uiAborted) for (File file : created) if (file.exists()) file.delete();
        }
        out.putString("stream", "\n" + (passed ? "PASS" : "FAILED") + " image device suite\n" + String.join("\n", results)
                + "\n" + out.getString("failure", "") + "\n");
        finish(passed ? Activity.RESULT_OK : Activity.RESULT_CANCELED, out);
    }
    private void check(boolean value, String label) { if (!value) throw new AssertionError(label); results.add("PASS " + label); }
    private static String causeSummary(Throwable error) {
        StringBuilder out = new StringBuilder();
        for (int i = 0; error != null && i < 6; i++, error = error.getCause()) {
            if (out.length() > 0) out.append(" <- ");
            out.append(error.getClass().getSimpleName()).append(": ").append(error.getMessage());
        }
        return out.toString();
    }
    private void ui(Runnable action) {
        if (uiAborted) throw new AssertionError("Main-thread handoff already aborted");
        Handler handler = new Handler(Looper.getMainLooper());
        CountDownLatch done = new CountDownLatch(1);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        AtomicInteger gate = new AtomicInteger(); // queued=0, running=1, complete=2, cancelled=3
        Runnable delivery = () -> {
            if (uiAborted || !gate.compareAndSet(0, 1)) { done.countDown(); return; }
            try { action.run(); } catch (Throwable error) { failure.set(error); }
            finally { gate.set(2); done.countDown(); }
        };
        if (!handler.post(delivery)) { uiAborted = true; throw new AssertionError("Main handler rejected test action"); }
        boolean finished;
        try { finished = done.await(UI_TIMEOUT_MS, TimeUnit.MILLISECONDS); }
        catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); finished = false; }
        if (!finished) {
            uiAborted = true;
            boolean cancelled = gate.compareAndSet(0, 3);
            handler.removeCallbacks(delivery);
            throw new AssertionError("Main-thread action exceeded " + UI_TIMEOUT_MS + " ms; "
                    + (cancelled ? "queued action cancelled" : "in-flight action; no further app mutations"));
        }
        if (failure.get() != null) throw new AssertionError("UI operation", failure.get());
        // Do not waitForIdleSync: the live chat's cursor/animation callbacks can prevent global idle.
        // Each asynchronous result below has its own bounded semantic condition.
    }
    private boolean onUi(BooleanSupplier condition) { boolean[] value = {false}; ui(() -> value[0] = condition.getAsBoolean()); return value[0]; }
    private void await(BooleanSupplier condition, String label) {
        long deadline = SystemClock.elapsedRealtime() + 10000;
        while (SystemClock.elapsedRealtime() < deadline) { if (onUi(condition)) { check(true, label); return; } SystemClock.sleep(40); }
        throw new AssertionError("Timed out: " + label);
    }
    private static Object field(Object object, String name) {
        try { Field f = object.getClass().getDeclaredField(name); f.setAccessible(true); return f.get(object); }
        catch (ReflectiveOperationException error) { throw new AssertionError("Missing field " + name, error); }
    }
    private static void setField(Object object, String name, Object value) {
        try { Field f = object.getClass().getDeclaredField(name); f.setAccessible(true); f.set(object, value); }
        catch (ReflectiveOperationException error) { throw new AssertionError("Cannot set test field " + name, error); }
    }
    private static Object invoke(Object object, String name, Class<?>[] types, Object... arguments) {
        try {
            Class<?> type = object.getClass(); Method method = null;
            while (type != null && method == null) {
                try { method = type.getDeclaredMethod(name, types); } catch (NoSuchMethodException absent) { type = type.getSuperclass(); }
            }
            if (method == null) throw new NoSuchMethodException(name);
            method.setAccessible(true); return method.invoke(object, arguments);
        } catch (ReflectiveOperationException error) { throw new AssertionError("Invocation " + name, error); }
    }
    private Bitmap decode(ChatStore.Attachment file, int target, boolean legacy) throws Exception {
        Method method = previewsClass.getDeclaredMethod(legacy ? "decodeLegacy" : "decode",
                legacy ? new Class<?>[]{File.class,int.class} : new Class<?>[]{Context.class,ChatStore.Attachment.class,int.class});
        method.setAccessible(true);
        try { return (Bitmap)(legacy ? method.invoke(null, new File(file.path), target) : method.invoke(null, activity, file, target)); }
        catch (InvocationTargetException error) {
            if (error.getCause() instanceof Exception) throw (Exception)error.getCause();
            throw new AssertionError("Native decoder failed", error.getCause());
        }
    }
    private View preview(ChatStore.Attachment file) {
        try {
            Constructor<?> c = viewClass.getDeclaredConstructor(Context.class,ChatStore.Attachment.class,previewsClass,int.class,boolean.class);
            c.setAccessible(true); View view = (View)c.newInstance(activity,file,previews,650,false);
            view.setLayoutParams(new LinearLayout.LayoutParams(280,220)); return view;
        } catch (ReflectiveOperationException error) { throw new AssertionError("Preview construction",error); }
    }
    private ImageView image(View view) { return (ImageView)field(view,"image"); }
    private Bitmap pixels(View view) { return image(view).getDrawable() instanceof BitmapDrawable ? ((BitmapDrawable)image(view).getDrawable()).getBitmap() : null; }
    private void newHost() { host = new LinearLayout(activity); host.setOrientation(LinearLayout.VERTICAL); activity.setContentView(host); }
    private void runChecks() throws Exception {
        String target = "com.baseer.freshchat.MainActivity";
        ActivityMonitor monitor = addMonitor(target, null, false);
        try {
            ui(() -> getTargetContext().startActivity(new Intent(Intent.ACTION_MAIN)
                    .setComponent(new ComponentName("com.baseer.bchat.preview", target)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)));
            activity = monitor.waitForActivityWithTimeout(45000);
            if (activity == null) throw new AssertionError("Activity launch exceeded 45000 ms");
        } finally { removeMonitor(monitor); }
        enterDemoIfPresent();
        previewsClass = Class.forName("com.baseer.freshchat.ImagePreviews",true,activity.getClassLoader());
        viewClass = Class.forName("com.baseer.freshchat.ImagePreviewView",true,activity.getClassLoader());
        readyClass = Class.forName("com.baseer.freshchat.ImagePreviews$Ready",true,activity.getClassLoader());
        Constructor<?> factory = previewsClass.getDeclaredConstructor(Context.class); factory.setAccessible(true); previews = factory.newInstance(activity);
        stateFile = privateState(); isolated = new ChatStore(stateFile);
        company = isolated.companies().get(0).id; conversation = isolated.conversations(company).get(0).id;
        ui(() -> { setField(activity,"store",isolated); setField(activity,"companyId",company); setField(activity,"conversationId",conversation); newHost(); });
        ChatStore.Attachment landscape = generated(1600,900,false,1), portrait = generated(900,1600,true,1);
        testNativeDecode(landscape,portrait); testOrientation(); testFailures(landscape); testProviderAndPersistence(landscape);
        testRequests(landscape); testViewLifecycle(); testBubbleGeometry(landscape,portrait); testCameraResult(); testActions(); testOptionalHeic();
    }
    private void testNativeDecode(ChatStore.Attachment landscape, ChatStore.Attachment portrait) throws Exception {
        for (ChatStore.Attachment file : new ChatStore.Attachment[]{landscape,portrait}) for (boolean legacy : new boolean[]{false,true}) {
            byte[] before = digest(new File(file.path)); Bitmap decoded = decode(file,650,legacy);
            check(decoded != null && decoded.getWidth() > 0 && decoded.getHeight() > 0 && Math.max(decoded.getWidth(),decoded.getHeight()) <= 650,
                    (legacy ? "Forced legacy" : "Platform") + " native JPEG/PNG decode is nonzero and bounded");
            check((decoded.getWidth() > decoded.getHeight()) == (file == landscape), "Native portrait/landscape orientation retained");
            check(decoded.getConfig() != Bitmap.Config.HARDWARE && decoded.getAllocationByteCount() <= 8*1024*1024, "Software preview allocation bounded");
            check(Arrays.equals(before,digest(new File(file.path))), "Native decode leaves original bytes unchanged"); decoded.recycle();
        }
        ChatStore.Attachment large = generated(6000,3200,false,1); Bitmap downsampled = decode(large,1400,false);
        check(Math.max(downsampled.getWidth(),downsampled.getHeight()) <= 1400 && downsampled.getAllocationByteCount() <= 8*1024*1024, "19.2MP image is downsampled within display memory cap"); downsampled.recycle();
        final boolean[] rejected = {false}; ui(() -> { try { decode(landscape,650,false); } catch (Exception error) { rejected[0] = error instanceof IllegalStateException; } });
        check(rejected[0], "Full decoder explicitly rejects main-thread use");
        results.add("INFO platform decoder branch: " + (Build.VERSION.SDK_INT >= 28 ? "ImageDecoder" : "BitmapFactory + EXIF") + "; API " + Build.VERSION.SDK_INT);
    }
    private void testOrientation() throws Exception {
        int[][] expected = {{0,1,2,3},{1,0,3,2},{3,2,1,0},{2,3,0,1},{0,2,1,3},{2,0,3,1},{3,1,2,0},{1,3,0,2}};
        for (int orientation=1; orientation<=8; orientation++) {
            ChatStore.Attachment file = generated(320,180,false,orientation);
            for (boolean legacy : new boolean[]{false,true}) {
                Bitmap bitmap = decode(file,650,legacy);
                check((bitmap.getWidth() > bitmap.getHeight()) == (orientation <= 4), "EXIF " + orientation + " dimensions, legacy=" + legacy);
                int w=bitmap.getWidth(),h=bitmap.getHeight(); int[] got={bitmap.getPixel(w/4,h/4),bitmap.getPixel(w*3/4,h/4),bitmap.getPixel(w/4,h*3/4),bitmap.getPixel(w*3/4,h*3/4)};
                for(int corner=0;corner<4;corner++) check(closeColor(got[corner],COLORS[expected[orientation-1][corner]]), "EXIF " + orientation + " corner " + corner + ", legacy=" + legacy);
                bitmap.recycle();
            }
        }
    }
    private void expectDecodeFailure(ChatStore.Attachment file, String label) throws Exception {
        try { Bitmap bitmap=decode(file,650,false); if(bitmap!=null)bitmap.recycle(); throw new AssertionError(label); }
        catch(IOException | IllegalArgumentException expected) { check(true,label); }
    }
    private void testFailures(ChatStore.Attachment valid) throws Exception {
        ChatStore.Attachment corrupt = bytes(new byte[]{1,2,3,4,5,6},"image/png"); expectDecodeFailure(corrupt,"Malformed image is rejected without claiming codec support");
        expectDecodeFailure(bytes(new byte[0],"image/jpeg"),"Empty image fails safely");
        expectDecodeFailure(bytes(new byte[]{1,2,3},"image/heic"),"Malformed HEIC fails safely; this is not a valid HEIC codec test");
        expectDecodeFailure(new ChatStore.Attachment(valid.id,valid.path,valid.name,valid.mime,valid.size+1),"Size mismatch rejected before decoding");
        File outside=new File(activity.getCacheDir(),"synthetic-outside-"+UUID.randomUUID()); created.add(outside); Files.copy(new File(valid.path).toPath(),outside.toPath());
        expectDecodeFailure(attachment(outside,"image/jpeg"),"Outside-private-attachment path rejected");
        expectDecodeFailure(new ChatStore.Attachment(valid.id,valid.path,valid.name,"application/octet-stream",valid.size),"Nonimage MIME does not enter image decoder");
        final View[] bad={null}; ui(() -> {newHost();bad[0]=preview(corrupt);host.addView(bad[0]);});
        await(() -> ((TextView)field(bad[0],"status")).getText().toString().equals(resource("ui_308")),"Malformed visible preview displays persistent unavailable state");
        check(onUi(() -> pixels(bad[0])==null && bad[0].getWidth()>0 && bad[0].getHeight()>0),"Unavailable preview retains visible sized card");
    }
    private Object callback(java.util.function.Consumer<Object> handler) {
        return Proxy.newProxyInstance(activity.getClassLoader(),new Class<?>[]{readyClass},(proxy,method,args)->{
            if(method.getDeclaringClass()==Object.class) {
                if("equals".equals(method.getName()))return proxy==args[0]; if("hashCode".equals(method.getName()))return System.identityHashCode(proxy);return "SyntheticImageCallback";
            }
            handler.accept(args[0]);return null;
        });
    }
    private Object load(ChatStore.Attachment file,Object callback) { return invoke(previews,"load",new Class<?>[]{ChatStore.Attachment.class,int.class,readyClass},file,650,callback); }
    private void cancel(Object request) {
        try { Class<?> requestType=Class.forName("com.baseer.freshchat.ImagePreviews$Request",true,activity.getClassLoader());Method method=requestType.getDeclaredMethod("cancel");method.setAccessible(true);method.invoke(request); }
        catch(ReflectiveOperationException error){throw new AssertionError(error);}
    }
    private void testRequests(ChatStore.Attachment file) throws Exception {
        CountDownLatch held=new CountDownLatch(1),release=new CountDownLatch(1); ThreadPoolExecutor worker=(ThreadPoolExecutor)field(previews,"worker");
        worker.submit(()->{held.countDown();try{release.await();}catch(InterruptedException ignored){Thread.currentThread().interrupt();}});check(held.await(2,TimeUnit.SECONDS),"Test worker barrier installed");
        final int[] called={0}; final Object[] first={null}; final Bitmap[] delivered={null};
        Object one=callback(result->{called[0]+=100;});Object two=callback(result->{check(Looper.myLooper()==Looper.getMainLooper(),"Decode result delivered on main thread");delivered[0]=(Bitmap)field(result,"bitmap");called[0]++;});
        ui(()->{first[0]=load(file,one);load(file,two);check(((Map<?,?>)field(previews,"pending")).size()==1,"Same attachment/target requests deduplicate");cancel(first[0]);});
        release.countDown();await(()->called[0]>0,"Remaining deduplicated listener completes");
        check(called[0]==1 && delivered[0]!=null,"Cancelled listener never receives stale decode result");
        CountDownLatch queueHeld=new CountDownLatch(1),queueRelease=new CountDownLatch(1); worker.submit(()->{queueHeld.countDown();try{queueRelease.await();}catch(InterruptedException ignored){Thread.currentThread().interrupt();}});
        check(queueHeld.await(2,TimeUnit.SECONDS),"Queue bound barrier installed"); List<Object> requests=new ArrayList<>();final int[] busy={0};
        ui(()->{for(int i=0;i<40;i++){ChatStore.Attachment distinct=new ChatStore.Attachment(UUID.randomUUID().toString(),file.path,file.name,file.mime,file.size);requests.add(load(distinct,callback(result->{if((boolean)field(result,"busy"))busy[0]++;})));}
            check(((Map<?,?>)field(previews,"pending")).size()<=32 && worker.getQueue().size()<=32,"Pending decode work is bounded at 32");for(Object request:requests)cancel(request);});
        queueRelease.countDown();check(busy[0]>=8,"Overflow returns retryable busy result instead of unbounded work");
        check((int)invoke(field(previews,"cache"),"maxSize",new Class<?>[0])==16*1024*1024,"Preview cache configured to 16 MiB");
    }
    private void testViewLifecycle() throws Exception {
        ChatStore.Attachment first=generated(400,200,false,1),replacement=generated(200,400,true,1);final View[] view={null};
        ui(()->{newHost();view[0]=preview(first);check(!(boolean)field(view[0],"previewRequested"),"Unattached view requests no decode");host.addView(view[0]);invoke(view[0],"bind",new Class<?>[]{ChatStore.Attachment.class},replacement);});
        await(()->pixels(view[0])!=null,"Rebound visible preview loads");
        check(onUi(()->pixels(view[0]).getHeight()>pixels(view[0]).getWidth()),"Old landscape decode cannot overwrite rebound portrait");
        ui(()->view[0].setVisibility(View.INVISIBLE));await(()->pixels(view[0])==null && !(boolean)field(view[0],"previewRequested"),"Hidden preview releases displayed pixels and request");
        ui(()->view[0].setVisibility(View.VISIBLE));await(()->pixels(view[0])!=null,"Visible replacement reloads from cache/native result");
        ui(()->host.removeView(view[0]));check(onUi(()->pixels(view[0])==null && !(boolean)field(view[0],"previewRequested")),"Detach clears pixels and cancels ownership");
        CountDownLatch held=new CountDownLatch(1),release=new CountDownLatch(1);((ThreadPoolExecutor)field(previews,"worker")).submit(()->{held.countDown();try{release.await();}catch(InterruptedException ignored){Thread.currentThread().interrupt();}});held.await(2,TimeUnit.SECONDS);
        ChatStore.Attachment pending=generated(420,200,false,1);ui(()->{view[0]=preview(pending);host.addView(view[0]);invoke(view[0],"refreshVisibility",new Class<?>[0]);host.removeView(view[0]);});release.countDown();SystemClock.sleep(250);
        check(onUi(()->pixels(view[0])==null && !(boolean)field(view[0],"previewRequested")),"Queued result cannot repopulate detached preview");
    }
    private void testBubbleGeometry(ChatStore.Attachment landscape,ChatStore.Attachment portrait) throws Exception {
        for(String caption:new String[]{"","synthetic caption"}) for(ChatStore.Attachment file:new ChatStore.Attachment[]{landscape,portrait}) {
            isolated.setDraft(company,conversation,caption,Collections.singletonList(file));ChatStore.Message message=isolated.send(company,conversation);
            isolated=new ChatStore(stateFile);ChatStore.Message restored=isolated.message(company,conversation,message.id);final View[] outer={null},card={null};
            ui(()->{setField(activity,"store",isolated);newHost();outer[0]=(View)invoke(activity,"messageBubble",new Class<?>[]{ChatStore.Message.class},restored);host.addView(outer[0]);card[0]=findPreview(outer[0]);});
            await(()->card[0]!=null && card[0].getWidth()>0 && card[0].getHeight()>0,"Restored image-only/captioned bubble has nonzero card geometry");
            check(onUi(()->card[0].getLayoutParams().width>0 && card[0].getLayoutParams().height>0 && card[0].getWidth()<=host.getWidth()),"OUTER image card has explicit bounded width and height");
            await(()->pixels(card[0])!=null,"Restored sent image renders actual bitmap");
            check(onUi(()->image(card[0]).getScaleType()==ImageView.ScaleType.FIT_CENTER),"Preview preserves complete image with FIT_CENTER");
        }
        final View[] large={null};ui(()->{newHost();large[0]=(View)invoke(activity,"attachmentCard",new Class<?>[]{ChatStore.Attachment.class,boolean.class},portrait,true);host.addView(large[0]);});
        await(()->pixels(large[0])!=null,"Larger inspection card renders");check(onUi(()->image(large[0]).getScaleType()==ImageView.ScaleType.FIT_CENTER),"Larger inspection uses FIT_CENTER");
    }
    private View findPreview(View view){if(viewClass.isInstance(view))return view;if(view instanceof ViewGroup)for(int i=0;i<((ViewGroup)view).getChildCount();i++){View found=findPreview(((ViewGroup)view).getChildAt(i));if(found!=null)return found;}return null;}
    private String resource(String name){int id=activity.getResources().getIdentifier(name,"string",activity.getPackageName());if(id==0)throw new AssertionError("Missing string "+name);return activity.getString(id);}
    @SuppressWarnings("unchecked")
    private List<View> processWindowRoots() {
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                Class<?> inspector = Class.forName("android.view.inspector.WindowInspector");
                return (List<View>)inspector.getMethod("getGlobalWindowViews").invoke(null);
            }
            // Older Android lacks public WindowInspector. Inspect only this test process's
            // already-existing windows; do not modify framework or hidden-API policy.
            Class<?> type = Class.forName("android.view.WindowManagerGlobal");
            Object manager = type.getDeclaredMethod("getInstance").invoke(null);
            Field views = type.getDeclaredField("mViews"); views.setAccessible(true);
            return new ArrayList<>((List<View>)views.get(manager));
        } catch (ReflectiveOperationException error) { throw new AssertionError("Test window inspection unavailable", error); }
    }
    private static final class ModalAction {
        final View root, label; final Rect bounds;
        ModalAction(View root, View label, Rect bounds) { this.root = root; this.label = label; this.bounds = bounds; }
    }
    private View exactVisibleText(View root, String text) {
        if (!root.isShown() || !root.isEnabled()) return null;
        if (root instanceof TextView && text.contentEquals(((TextView)root).getText())) {
            Rect visible = new Rect();
            if (root.getGlobalVisibleRect(visible) && visible.width() > 0 && visible.height() > 0) return root;
        }
        if (root instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)root).getChildCount(); i++) {
            View match = exactVisibleText(((ViewGroup)root).getChildAt(i), text); if (match != null) return match;
        }
        return null;
    }
    private ModalAction modalAction(String text) {
        for (View root : processWindowRoots()) {
            if (root == activity.getWindow().getDecorView() || !root.isAttachedToWindow() || !root.hasWindowFocus()) continue;
            View label = exactVisibleText(root, text); if (label == null) continue;
            // Accept only an actual dialog button or an actual enabled AdapterView row.
            View target = label;
            while (target != root && !(target instanceof Button)
                    && !(target.getParent() instanceof AdapterView)) {
                if (!(target.getParent() instanceof View)) break;
                target = (View)target.getParent();
            }
            boolean actionable = target instanceof Button && target.isClickable();
            if (target.getParent() instanceof AdapterView) {
                AdapterView<?> list = (AdapterView<?>)target.getParent();
                int position = list.getPositionForView(target);
                actionable = position != AdapterView.INVALID_POSITION && list.isEnabled();
                if (actionable && list.getAdapter() instanceof ListAdapter)
                    actionable = ((ListAdapter)list.getAdapter()).isEnabled(position);
            }
            Rect bounds = new Rect();
            if (actionable && target.isEnabled() && target.getLocalVisibleRect(bounds)
                    && bounds.width() > 0 && bounds.height() > 0) {
                // getGlobalVisibleRect uses root-view coordinates, not display coordinates.
                // Dialog windows are offset; input injection needs the visible rect on screen.
                int[] screen = new int[2]; target.getLocationOnScreen(screen);
                bounds.offset(screen[0], screen[1]); return new ModalAction(root, label, bounds);
            }
        }
        return null;
    }
    private boolean accessibilityClick(String text, Rect expectedBounds) {
        AccessibilityNodeInfo root = getUiAutomation().getRootInActiveWindow();
        if (root == null) { results.add("INFO action accessibility root unavailable: " + text); return false; }
        try {
            List<AccessibilityNodeInfo> matches = root.findAccessibilityNodeInfosByText(text);
            try {
                for (AccessibilityNodeInfo node : matches) {
                    if (!text.contentEquals(node.getText()) || !node.isVisibleToUser() || !node.isEnabled()) continue;
                    Rect bounds = new Rect(); node.getBoundsInScreen(bounds);
                    if (!expectedBounds.contains(bounds.centerX(), bounds.centerY())) continue;
                    AccessibilityNodeInfo target = AccessibilityNodeInfo.obtain(node);
                    try {
                        while (target != null && !target.isClickable()) {
                            AccessibilityNodeInfo parent = target.getParent(); target.recycle(); target = parent;
                        }
                        if (target != null && target.isEnabled() && target.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return true;
                    } finally { if (target != null) target.recycle(); }
                }
            } finally { for (AccessibilityNodeInfo node : matches) node.recycle(); }
        } finally { root.recycle(); }
        results.add("INFO accessibility did not click the expected visible modal target: " + text);
        return false;
    }
    private void clickText(String text) {
        long deadline = SystemClock.elapsedRealtime() + 5000;
        ModalAction[] selected = {null};
        while (SystemClock.elapsedRealtime() < deadline) {
            ui(() -> selected[0] = modalAction(text));
            if (selected[0] != null) break;
            SystemClock.sleep(60);
        }
        if (selected[0] == null) throw new AssertionError("Cannot find visible focused modal action: " + text);
        ModalAction original = selected[0];
        boolean clicked = accessibilityClick(text, original.bounds);
        if (!clicked) {
            // Capture the live failure BEFORE dismissal/teardown, then use actual touch input at
            // the freshly measured visible row/button. Never invoke app/store action methods.
            captureDiagnostics("accessibility-action-" + (++diagnosticSequence));
            ui(() -> selected[0] = modalAction(text));
            ModalAction current = selected[0];
            if (current == null || current.root != original.root) throw new AssertionError("Modal changed before touch action: " + text);
            float x = current.bounds.exactCenterX(), y = current.bounds.exactCenterY();
            long now = SystemClock.uptimeMillis();
            MotionEvent down = MotionEvent.obtain(now, now, MotionEvent.ACTION_DOWN, x, y, 0);
            down.setSource(android.view.InputDevice.SOURCE_TOUCHSCREEN);
            try {
                boolean pressed = getUiAutomation().injectInputEvent(down, true);
                SystemClock.sleep(80);
                MotionEvent up = MotionEvent.obtain(now, SystemClock.uptimeMillis(), MotionEvent.ACTION_UP, x, y, 0);
                up.setSource(android.view.InputDevice.SOURCE_TOUCHSCREEN);
                boolean released;
                try { released = getUiAutomation().injectInputEvent(up, true); }
                finally { up.recycle(); }
                if (!pressed || !released) throw new AssertionError("Real modal touch injection rejected: " + text);
            } finally { down.recycle(); }
            results.add("INFO real touch selected focused modal action after accessibility targeting failed: " + text);
        }
        await(() -> !original.root.isAttachedToWindow(), "Modal action dismisses its own dialog: " + text);
    }
    private void appendViewTree(View view, StringBuilder out, int depth, int[] remaining) {
        if (remaining[0]-- <= 0 || depth > 24) return;
        Rect bounds = new Rect(); view.getGlobalVisibleRect(bounds);
        out.append("VIEW depth=").append(depth).append(" class=").append(view.getClass().getName())
                .append(" shown=").append(view.isShown()).append(" enabled=").append(view.isEnabled())
                .append(" click=").append(view.isClickable()).append(" focus=").append(view.hasWindowFocus())
                .append(" bounds=").append(bounds).append(" text=")
                .append(view instanceof TextView ? ((TextView)view).getText() : "").append('\n');
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++)
            appendViewTree(((ViewGroup)view).getChildAt(i), out, depth + 1, remaining);
    }
    private void appendAccessibilityTree(AccessibilityNodeInfo node, StringBuilder out, int depth, int[] remaining) {
        if (node == null || remaining[0]-- <= 0 || depth > 24) return;
        Rect bounds = new Rect(); node.getBoundsInScreen(bounds);
        out.append("A11Y depth=").append(depth).append(" class=").append(node.getClassName())
                .append(" visible=").append(node.isVisibleToUser()).append(" enabled=").append(node.isEnabled())
                .append(" click=").append(node.isClickable()).append(" bounds=").append(bounds)
                .append(" text=").append(node.getText()).append('\n');
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            try { appendAccessibilityTree(child, out, depth + 1, remaining); }
            finally { if (child != null) child.recycle(); }
        }
    }
    private void captureDiagnostics(String label) {
        Bitmap screenshot = null;
        try {
            File directory = activity.getExternalFilesDir("image-test-diagnostics");
            if (directory == null || (!directory.isDirectory() && !directory.mkdirs())) throw new IOException("Diagnostic directory unavailable");
            String name = label + "-api" + Build.VERSION.SDK_INT;
            StringBuilder tree = new StringBuilder();
            ui(() -> { for (View root : processWindowRoots()) appendViewTree(root, tree, 0, new int[]{500}); });
            AccessibilityNodeInfo active = getUiAutomation().getRootInActiveWindow();
            try { tree.append("ACTIVE_ACCESSIBILITY_ROOT=").append(active != null).append('\n');
                appendAccessibilityTree(active, tree, 0, new int[]{500}); }
            finally { if (active != null) active.recycle(); }
            File hierarchy = new File(directory, name + ".txt");
            try (Writer output = new OutputStreamWriter(new FileOutputStream(hierarchy), "UTF-8")) { output.write(tree.toString()); }
            results.add("DIAGNOSTIC " + hierarchy.getAbsolutePath());
            screenshot = getUiAutomation().takeScreenshot();
            if (screenshot == null) throw new IOException("Screenshot unavailable");
            File pixels = new File(directory, name + ".png");
            try (OutputStream output = new FileOutputStream(pixels)) {
                if (!screenshot.compress(Bitmap.CompressFormat.PNG, 100, output)) throw new IOException("Screenshot encoding failed");
            }
            results.add("SCREENSHOT " + pixels.getAbsolutePath());
        } catch (Throwable error) { results.add("WARN failure-time diagnostics: " + causeSummary(error)); }
        finally { if (screenshot != null) screenshot.recycle(); }
    }
    private void testCameraResult() throws Exception {
        ChatStore.Attachment capture = generated(480,320,false,6); byte[] original = digest(new File(capture.path));
        ui(() -> {
            setField(activity,"store",isolated); setField(activity,"cameraPath",capture.path);
            setField(activity,"cameraCompany",company); setField(activity,"cameraConversation",conversation);
            invoke(activity,"onActivityResult",new Class<?>[]{int.class,int.class,Intent.class},403,Activity.RESULT_OK,null);
        });
        ChatStore.Draft draft = isolated.draft(company,conversation);
        check(draft.attachments.size()==1 && draft.attachments.get(0).path.equals(capture.path),
                "Synthetic camera result attaches original captured file without a second import");
        check(Arrays.equals(original,digest(new File(capture.path))),"Actual camera result handler preserves JPEG/EXIF bytes");
        isolated.send(company,conversation); isolated=new ChatStore(stateFile);
        check(isolated.lastMessage(company,conversation).attachments.get(0).path.equals(capture.path),
                "Camera-result image survives local send and store reload");
    }
    private void testActions() throws Exception {
        ChatStore.Message message = isolated.lastMessage(company, conversation);
        String originalPath = message.attachments.get(0).path;
        byte[] originalBytes = digest(new File(originalPath));
        final View[] card = {null};
        ui(() -> { setField(activity, "store", isolated);
            invoke(activity, "showChat", new Class<?>[]{String.class, String.class}, company, conversation);
            View bubble = ((Map<String, View>)field(activity, "messageViews")).get(message.id); card[0] = findPreview(bubble); });
        await(() -> card[0] != null && card[0].isAttachedToWindow() && card[0].getWidth() > 0,
                "Image action target is attached and laid out");
        ui(() -> check(card[0].performLongClick(), "Image long press invokes message actions"));
        clickText(resource("ui_167"));
        await(() -> message.id.equals(isolated.draft(company, conversation).replyToMessageId), "Long-press Reply persists original target");
        check(message.id.equals(new ChatStore(stateFile).draft(company, conversation).replyToMessageId), "Reply target survives store reload");
        ui(() -> { View bubble = ((Map<String, View>)field(activity, "messageViews")).get(message.id);
            check(findPreview(bubble).performLongClick(), "Image actions reopen before cancelled deletion"); });
        clickText(resource("ui_171"));
        check(!isolated.message(company, conversation, message.id).deleted, "Local delete action still requires confirmation");
        clickText(resource("ui_109"));
        check(!new ChatStore(stateFile).message(company, conversation, message.id).deleted, "Cancel delete preserves image message after reload");
        ui(() -> { View bubble = ((Map<String, View>)field(activity, "messageViews")).get(message.id);
            check(findPreview(bubble).performLongClick(), "Image actions reopen before confirmed deletion"); });
        clickText(resource("ui_171")); clickText(resource("ui_171"));
        await(() -> isolated.message(company, conversation, message.id).deleted, "Confirmed local deletion hides image message");
        ChatStore.Message tombstone = new ChatStore(stateFile).message(company, conversation, message.id);
        check(tombstone.deleted && tombstone.attachments.isEmpty(), "Persisted tombstone exposes no attachment");
        ui(() -> { View bubble = ((Map<String, View>)field(activity, "messageViews")).get(message.id);
            check(bubble != null && bubble.performLongClick(), "Deleted message long press opens real undo actions"); });
        clickText(resource("ui_170"));
        await(() -> !isolated.message(company, conversation, message.id).deleted, "Real Undo action restores image message");
        ChatStore.Message restored = new ChatStore(stateFile).message(company, conversation, message.id);
        check(!restored.deleted && restored.attachments.size() == 1 && originalPath.equals(restored.attachments.get(0).path),
                "Real Undo persists original image attachment after reload");
        check(Arrays.equals(originalBytes, digest(new File(originalPath))), "Reply/cancel/delete/Undo preserve exact original image bytes");
    }
    private void testProviderAndPersistence(ChatStore.Attachment original) throws Exception {
        ImageFixtureProvider provider=new ImageFixtureProvider();ProviderInfo info=new ProviderInfo();info.authority="bchat.synthetic.images";provider.attachInfo(activity,info);
        MockContentResolver resolver=new MockContentResolver();resolver.addProvider(info.authority,provider);
        Context context=new ContextWrapper(activity){@Override public Context getApplicationContext(){return this;}@Override public ContentResolver getContentResolver(){return resolver;}};
        ChatStore.Attachment imported=AttachmentSupport.importUri(context,provider.register(new File(original.path),"image/jpeg"),"image/*",AttachmentSupport.MAX_BATCH_BYTES);created.add(new File(imported.path));
        check(Arrays.equals(digest(new File(original.path)),digest(new File(imported.path))),"Provider import copies exact gallery/share image bytes");
        isolated.setDraft(company,conversation,"",Collections.singletonList(imported));isolated=new ChatStore(stateFile);
        check(isolated.draft(company,conversation).attachments.get(0).path.equals(imported.path),"Draft reload retains imported original source");
        ChatStore.Message sent=isolated.send(company,conversation);isolated=new ChatStore(stateFile);
        check(isolated.message(company,conversation,sent.id).attachments.get(0).size==imported.size,"Send/reload retains exact original size");
        ChatStore.PendingShare staged=isolated.stagePendingShare("",Collections.singletonList(imported));isolated=new ChatStore(stateFile);
        ChatStore.Message shared=isolated.sendPendingShare(staged.id,company,conversation,null,null,UUID.randomUUID().toString());
        check(shared.attachments.get(0).path.equals(imported.path),"Shared image staging/reload/send retains same source");
        File output=new File(activity.getCacheDir(),"synthetic-export-"+UUID.randomUUID());created.add(output);
        AttachmentSupport.saveToUri(context,imported,provider.register(output,"image/jpeg"));
        check(Arrays.equals(digest(new File(original.path)),digest(output)),"Explicit SAF-style provider export is byte exact");
        // Camera result hands off its original capture file. Here persistence is tested; external camera UI is manual acceptance.
        isolated.setDraft(company,conversation,"",Collections.singletonList(original));ChatStore.Message camera=isolated.send(company,conversation);
        check(camera.attachments.get(0).path.equals(original.path) && Arrays.equals(digest(new File(original.path)),digest(output)),"Camera-file-style local persistence never recompresses source");
    }
    private void testOptionalHeic() throws Exception {
        File file=newPrivate();
        try(InputStream input=getContext().getAssets().open("synthetic.heic");OutputStream output=new FileOutputStream(file)){byte[] buffer=new byte[4096];int count;while((count=input.read(buffer))!=-1)output.write(buffer,0,count);}
        catch(FileNotFoundException absent){results.add("SKIP valid HEIC codec acceptance: no synthetic HEIC fixture bundled; malformed HEIC safe failure covered");return;}
        ChatStore.Attachment heic=attachment(file,"image/heic");byte[] before=digest(file);
        // Raw platform decoder establishes device support independently of the app's bounded pipeline.
        Bitmap probe=null;try{if(Build.VERSION.SDK_INT>=28)probe=ImageDecoder.decodeBitmap(ImageDecoder.createSource(file));else probe=BitmapFactory.decodeFile(file.getPath());}catch(IOException|RuntimeException unsupported){ }
        if(probe==null){expectDecodeFailure(heic,"Device without HEIC decoder rejects preview safely");results.add("SKIP valid HEIC pixels: device decoder unavailable");}
        else{probe.recycle();Bitmap bitmap=decode(heic,650,false);check(bitmap!=null && Math.max(bitmap.getWidth(),bitmap.getHeight())<=650,"Device-supported HEIC produces bounded preview");bitmap.recycle();}
        check(Arrays.equals(before,digest(file)),"HEIC support/failure preserves original bytes");
    }
    private File privateState(){File file=new File(activity.getFilesDir(),"synthetic-images-"+UUID.randomUUID()+".bin");created.add(file);created.add(new File(file+".bak"));created.add(new File(file+".tmp"));return file;}
    private File newPrivate() throws IOException {File directory=new File(activity.getFilesDir(),"attachments");if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("Synthetic fixture directory unavailable");File file=new File(directory,UUID.randomUUID()+".bin");created.add(file);return file;}
    private ChatStore.Attachment attachment(File file,String mime)throws IOException{return new ChatStore.Attachment(UUID.randomUUID().toString(),file.getCanonicalPath(),"synthetic-image",mime,file.length());}
    private ChatStore.Attachment bytes(byte[] bytes,String mime)throws IOException{File file=newPrivate();try(OutputStream output=new FileOutputStream(file)){output.write(bytes);}return attachment(file,mime);}
    private ChatStore.Attachment generated(int width,int height,boolean png,int orientation)throws IOException{
        File file=newPrivate();Bitmap bitmap=Bitmap.createBitmap(width,height,Bitmap.Config.ARGB_8888);Canvas canvas=new Canvas(bitmap);Paint paint=new Paint();
        for(int i=0;i<4;i++){paint.setColor(COLORS[i]);canvas.drawRect((i%2)*width/2f,(i/2)*height/2f,(i%2+1)*width/2f,(i/2+1)*height/2f,paint);}
        try(OutputStream output=new FileOutputStream(file)){if(!bitmap.compress(png?Bitmap.CompressFormat.PNG:Bitmap.CompressFormat.JPEG,95,output))throw new IOException("Synthetic bitmap encoding failed");}finally{bitmap.recycle();}
        if(!png){ExifInterface exif=new ExifInterface(file.getPath());exif.setAttribute(ExifInterface.TAG_ORIENTATION,Integer.toString(orientation));exif.saveAttributes();}
        return attachment(file,png?"image/png":"image/jpeg");
    }
    private static boolean closeColor(int actual,int expected){return Math.abs(Color.red(actual)-Color.red(expected))<45&&Math.abs(Color.green(actual)-Color.green(expected))<45&&Math.abs(Color.blue(actual)-Color.blue(expected))<45;}
    private static byte[] digest(File file)throws Exception{MessageDigest digest=MessageDigest.getInstance("SHA-256");try(InputStream input=new FileInputStream(file)){byte[] buffer=new byte[8192];int count;while((count=input.read(buffer))!=-1)digest.update(buffer,0,count);}return digest.digest();}

    private void enterDemoIfPresent() {
        ui(() -> {
            View entry = activity.getWindow().getDecorView().findViewWithTag("bchat-explore-demo");
            if (entry != null && !entry.performClick()) throw new AssertionError("Demo entry was not clickable");
        });
    }
}
