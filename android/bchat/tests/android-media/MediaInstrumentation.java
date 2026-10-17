package com.baseer.freshchat;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.BroadcastReceiver;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.media.ExifInterface;
import android.media.MediaPlayer;
import android.os.Bundle;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Real Android codecs/EXIF/files; only external audio-focus results use a declared port. */
public final class MediaInstrumentation extends Instrumentation {
    private int assertions;
    private boolean disposable;
    private Throwable mainFailure;
    private File cache;
    private void check(boolean value, String label) {
        assertions++;
        if (!value) throw new AssertionError(label);
    }
    @Override public void onCreate(Bundle args) {
        super.onCreate(args);
        disposable = args != null && "true".equals(args.getString("disposable"));
        start();
    }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            if (!disposable) throw new IllegalStateException("Disposable opt-in required");
            cache = new File(getTargetContext().getCacheDir(), "bchat-v2-media-read");
            check(cache.mkdirs() || cache.isDirectory(), "private test cache");
            images();
            detailCallbacks();
            tiledViewer();
            onMain(this::audio);
            File audioFolder = new File(getTargetContext().getFilesDir(), "fixture-audio");
            check(audioFolder.mkdirs() || audioFolder.isDirectory(), "synthetic audio fixture folder");
            File audioFile = new File(audioFolder, "fixture.bin");
            Files.write(audioFile.toPath(), new byte[]{1, 2, 3, 4});
            onMain(() -> playbackPreparationRace(audioFile));
            boolean refused = false;
            try { new AudioFocusLease(new FakeAudio()).acquire(attributes(), false, reason -> { }); }
            catch (IllegalStateException correctThreadFence) { refused = true; }
            check(refused, "off-main audio ownership refused");
            result.putString("stream", "PASS actual Android EXIF/decoding and audio ownership: " + assertions
                    + " assertions; focus grant/loss injected, no OEM-call/Bluetooth/auth/FPS claim\n");
            finish(Activity.RESULT_OK, result);
        } catch (Throwable failure) {
            result.putString("stream", android.util.Log.getStackTraceString(failure));
            finish(Activity.RESULT_CANCELED, result);
        }
    }
    private void onMain(Runnable action) throws Exception {
        mainFailure = null;
        runOnMainSync(() -> { try { action.run(); } catch (Throwable failure) { mainFailure = failure; } });
        if (mainFailure != null) throw new AssertionError(mainFailure);
    }
    private byte[] digest(File source) throws Exception {
        return MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(source.toPath()));
    }
    private File fixture(int id, int orientation, int width, int height) throws Exception {
        Bitmap raw = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(raw);
        Paint paint = new Paint();
        int[] colors = {Color.RED, Color.GREEN, Color.BLUE, Color.YELLOW};
        for (int q = 0; q < 4; q++) {
            paint.setColor(colors[q]);
            canvas.drawRect((q % 2) * width / 2f, (q / 2) * height / 2f,
                    (q % 2 + 1) * width / 2f, (q / 2 + 1) * height / 2f, paint);
        }
        File file = new File(cache, "read-" + id + ".bin");
        try (FileOutputStream out = new FileOutputStream(file)) {
            check(raw.compress(Bitmap.CompressFormat.JPEG, 98, out), "fixture encoded");
        } finally { raw.recycle(); }
        ExifInterface exif = new ExifInterface(file.getPath());
        exif.setAttribute(ExifInterface.TAG_ORIENTATION, Integer.toString(orientation));
        exif.saveAttributes();
        return file;
    }
    private void colors(Bitmap bitmap, int[] expected, String label) {
        for (int q = 0; q < 4; q++) {
            int actual = bitmap.getPixel((q % 2 == 0 ? 1 : 3) * bitmap.getWidth() / 4,
                    (q < 2 ? 1 : 3) * bitmap.getHeight() / 4);
            check(Math.abs(Color.red(actual) - Color.red(expected[q])) < 35
                    && Math.abs(Color.green(actual) - Color.green(expected[q])) < 35
                    && Math.abs(Color.blue(actual) - Color.blue(expected[q])) < 35, label + " quadrant " + q);
        }
    }
    private void images() throws Exception {
        int r = Color.RED, g = Color.GREEN, b = Color.BLUE, y = Color.YELLOW;
        int[][] expected = {{r,g,b,y}, {g,r,y,b}, {y,b,g,r}, {b,y,r,g},
                {r,b,g,y}, {b,r,y,g}, {y,g,b,r}, {g,y,r,b}};
        for (int orientation = 1; orientation <= 8; orientation++) {
            File file = fixture(orientation, orientation, 96, 64);
            byte[] before = digest(file);
            Bitmap modern = ImagePreviews.decodeConnectedCache(getTargetContext(), file, 1400);
            Bitmap legacy = ImagePreviews.decodeLegacy(file, 1400);
            int width = orientation >= 5 ? 64 : 96, height = orientation >= 5 ? 96 : 64;
            check(modern.getWidth() == width && modern.getHeight() == height, "modern EXIF dimensions " + orientation);
            check(legacy.getWidth() == width && legacy.getHeight() == height, "fallback EXIF dimensions " + orientation);
            colors(modern, expected[orientation - 1], "modern EXIF " + orientation);
            colors(legacy, expected[orientation - 1], "legacy EXIF " + orientation);
            modern.recycle(); legacy.recycle();
            check(Arrays.equals(before, digest(file)), "original bytes unchanged " + orientation);
        }
        File large = fixture(90, 6, 3600, 1800);
        byte[] original = digest(large);
        Bitmap preview = ImagePreviews.decodeConnectedCache(getTargetContext(), large, 2048);
        check(preview.getWidth() <= 1400 && preview.getHeight() <= 1400, "overview capped at existing 1400px");
        check(preview.getAllocationByteCount() <= 8 * 1024 * 1024, "overview allocation capped");
        preview.recycle();
        check(Arrays.equals(original, digest(large)), "large original never rewritten");
        File broken = new File(cache, "read-91.bin");
        Files.write(broken.toPath(), new byte[]{1, 2, 3, 4});
        expectRejected(broken, "invalid codec");
        expectRejected(new File(cache, "read-999.bin"), "missing source");
        File outside = new File(getTargetContext().getCacheDir(), "read-92.bin");
        Files.copy(large.toPath(), outside.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        expectRejected(outside, "parent path escape");
        File invalidName = new File(cache, "other.bin");
        Files.copy(large.toPath(), invalidName.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        expectRejected(invalidName, "noncanonical filename");
        File symlink = new File(cache, "read-93.bin");
        Files.deleteIfExists(symlink.toPath());
        Files.createSymbolicLink(symlink.toPath(), outside.toPath());
        expectRejected(symlink, "canonical symlink escape");
        Thread.currentThread().interrupt();
        try { expectRejected(large, "interrupted decode"); }
        finally { Thread.interrupted(); }
        onMain(() -> {
            boolean rejected = false;
            try { ImagePreviews.decodeConnectedCache(getTargetContext(), large, 1400); }
            catch (IllegalStateException correct) { rejected = true; }
            catch (IOException incorrect) { throw new AssertionError(incorrect); }
            check(rejected, "main-thread decode prohibited");
        });
    }
    private void expectRejected(File source, String label) throws Exception {
        boolean rejected = false;
        try {
            Bitmap unexpected = ImagePreviews.decodeConnectedCache(getTargetContext(), source, 1400);
            if (unexpected != null) unexpected.recycle();
        } catch (IOException expected) { rejected = true; }
        check(rejected, label);
    }
    private void detailCallbacks() throws Exception {
        ImagePreviews[] decoder = new ImagePreviews[1];
        ImagePreviews.DetailResult[] result = new ImagePreviews.DetailResult[1];
        CountDownLatch done = new CountDownLatch(1);
        onMain(() -> {
            decoder[0] = new ImagePreviews(getTargetContext());
            decoder[0].loadConnectedDetail(new File(cache, "read-90.bin"), new Rect(100, 100, 2500, 1500), 1,
                    ready -> { result[0] = ready; done.countDown(); });
        });
        check(done.await(15, TimeUnit.SECONDS), "detail callback deadline");
        check(result[0].info != null && result[0].info.orientation == 6, "detail source EXIF retained");
        check(result[0].bitmap != null && result[0].bitmap.getWidth() <= 1400
                && result[0].bitmap.getHeight() <= 1400, "detail tile bounded");
        check(result[0].region.equals(new Rect(100, 100, 2500, 1500)), "exact original tile coordinates");
        check(result[0].bitmap.getAllocationByteCount() <= 8 * 1024 * 1024, "detail tile allocation capped");
        result[0].bitmap.recycle();
        int[] callbacks = {0};
        onMain(() -> {
            ImagePreviews.Request request = decoder[0].loadConnectedDetail(new File(cache, "read-90.bin"), null, 1,
                    stale -> { callbacks[0]++; });
            request.cancel();
            decoder[0].close();
        });
        waitForIdleSync();
        check(callbacks[0] == 0, "cancelled/closed detail never delivered");
    }
    private void tiledViewer() throws Exception {
        MediaTestActivity activity = (MediaTestActivity)startActivitySync(
                new Intent(getTargetContext(), MediaTestActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        ZoomableImageView[] view = new ZoomableImageView[1];
        ImagePreviews[] decoder = new ImagePreviews[1];
        boolean[] allowed = {true};
        int r = Color.RED, g = Color.GREEN, b = Color.BLUE, y = Color.YELLOW;
        int[][] expected = {{r,g,b,y}, {g,r,y,b}, {y,b,g,r}, {b,y,r,g},
                {r,b,g,y}, {b,r,y,g}, {y,g,b,r}, {g,y,r,b}};
        try {
            onMain(() -> {
                decoder[0] = new ImagePreviews(getTargetContext());
                view[0] = new ZoomableImageView(activity);
                activity.root.addView(view[0], new android.widget.FrameLayout.LayoutParams(400, 400));
            });
            for (int orientation = 1; orientation <= 8; orientation++) {
                File source = new File(cache, "read-" + orientation + ".bin");
                Bitmap overview = ImagePreviews.decodeConnectedCache(getTargetContext(), source, 1400);
                final int index = orientation - 1;
                onMain(() -> {
                    view[0].setImageBitmap(overview);
                    view[0].measure(android.view.View.MeasureSpec.makeMeasureSpec(400, android.view.View.MeasureSpec.EXACTLY),
                            android.view.View.MeasureSpec.makeMeasureSpec(400, android.view.View.MeasureSpec.EXACTLY));
                    view[0].layout(0, 0, 400, 400);
                    view[0].setConnectedDetailSource(decoder[0], source, () -> allowed[0]);
                    view[0].zoomBy(2, 200, 200);
                });
                long deadline = android.os.SystemClock.elapsedRealtime() + 15_000;
                boolean[] loaded = {false};
                do {
                    onMain(() -> {
                        try {
                            java.lang.reflect.Field tile = ZoomableImageView.class.getDeclaredField("detailBitmap");
                            tile.setAccessible(true);
                            loaded[0] = tile.get(view[0]) != null;
                        } catch (ReflectiveOperationException failure) { throw new AssertionError(failure); }
                    });
                    if (!loaded[0]) android.os.SystemClock.sleep(40);
                } while (!loaded[0] && android.os.SystemClock.elapsedRealtime() < deadline);
                check(loaded[0], "attached viewer decoded tile for EXIF " + orientation);
                onMain(() -> {
                    Bitmap frame = Bitmap.createBitmap(400, 400, Bitmap.Config.ARGB_8888);
                    view[0].draw(new Canvas(frame));
                    colors(frame, expected[index], "tile composed EXIF " + (index + 1));
                    frame.recycle();
                    view[0].clearDetailSource();
                    view[0].setImageBitmap(null);
                });
                overview.recycle();
            }
            Bitmap overview = ImagePreviews.decodeConnectedCache(getTargetContext(), new File(cache, "read-6.bin"), 1400);
            onMain(() -> {
                view[0].setImageBitmap(overview);
                view[0].setConnectedDetailSource(decoder[0], new File(cache, "read-6.bin"), () -> allowed[0]);
                activity.root.removeView(view[0]);
                allowed[0] = false;
                activity.root.addView(view[0], new android.widget.FrameLayout.LayoutParams(400, 400));
                for (int draw = 0; draw < 2; draw++) {
                    Bitmap frame = Bitmap.createBitmap(400, 400, Bitmap.Config.ARGB_8888);
                    view[0].draw(new Canvas(frame));
                    check(Color.alpha(frame.getPixel(200, 200)) == 0,
                            "detach then revoke/account-change then reattach never paints old original, frame " + draw);
                    frame.recycle();
                }
                view[0].setImageBitmap(null);
            });
            overview.recycle();
        } finally {
            onMain(() -> { decoder[0].close(); activity.finish(); });
        }
    }
    private static AudioAttributes attributes() {
        return new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build();
    }
    private void audio() {
        FakeAudio port = new FakeAudio();
        AudioFocusLease coordinator = new AudioFocusLease(port);
        int[] stopped = {0};
        port.grant = false;
        check(coordinator.acquire(attributes(), false, reason -> stopped[0]++) == null, "focus denied => no owner");
        check(stopped[0] == 0 && port.receiver == null, "denial does not start/register a player");
        port.grant = true;
        AudioFocusLease.Lease first = coordinator.acquire(attributes(), false, reason -> stopped[0]++);
        check(first != null && first.active(), "first audio owns focus");
        AudioFocusLease.Lease second = coordinator.acquire(attributes(), true, reason -> stopped[0]++);
        check(!first.active() && second.active() && stopped[0] == 1, "new owner stops old before acquiring");
        check(port.last.getFocusGain() == AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE, "recording exclusive focus");
        int abandoned = port.abandoned;
        first.close();
        first.onAudioFocusChange(AudioManager.AUDIOFOCUS_LOSS);
        check(second.active() && port.abandoned == abandoned && stopped[0] == 1, "stale close/loss cannot interrupt new owner");
        second.onAudioFocusChange(AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK);
        check(!second.active() && stopped[0] == 2, "duck pauses speech/recording instead of overlapping");
        second.onAudioFocusChange(AudioManager.AUDIOFOCUS_GAIN);
        check(!second.active() && stopped[0] == 2, "gain does not auto-resume");
        AudioFocusLease.Lease routed = coordinator.acquire(attributes(), false, reason -> {
            check(reason == AudioFocusLease.ROUTE_LOST, "route reason"); stopped[0]++;
        });
        BroadcastReceiver noisy = port.receiver;
        noisy.onReceive(getTargetContext(), new Intent(AudioManager.ACTION_AUDIO_BECOMING_NOISY));
        check(!routed.active() && port.receiver == null && stopped[0] == 3, "route loss clears owner and receiver");
        noisy.onReceive(getTargetContext(), new Intent(AudioManager.ACTION_AUDIO_BECOMING_NOISY));
        check(stopped[0] == 3, "stale route callback harmless");
        port.call = true;
        check(coordinator.acquire(attributes(), true, reason -> { }) == null, "recording blocked during active communication");
        port.call = false;
        port.throwRequest = true;
        check(coordinator.acquire(attributes(), false, reason -> { }) == null, "platform request failure fails closed");
        port.throwRequest = false; port.throwRegister = true;
        check(coordinator.acquire(attributes(), false, reason -> { }) == null && port.receiver == null,
                "receiver failure releases focus");
        port.throwRegister = false;
        AudioFocusLease.Lease[] nested = new AudioFocusLease.Lease[1];
        coordinator.acquire(attributes(), false, reason -> nested[0] = coordinator.acquire(attributes(), false, why -> { }));
        check(coordinator.acquire(attributes(), false, reason -> { }) == null && nested[0].active(),
                "reentrant old callback does not overwrite replacement owner");
        coordinator.stop();
        check(!nested[0].active() && port.receiver == null, "Activity stop releases current owner");
        coordinator.acquire(attributes(), false, reason -> { throw new IllegalStateException("Synthetic cleanup failure"); });
        int requests = port.requested;
        check(coordinator.acquire(attributes(), false, reason -> { }) == null && port.requested == requests,
                "failed old-owner cleanup cannot start another player");
    }
    private static final class FakeAudio implements AudioFocusLease.Platform {
        boolean grant = true, call, throwRequest, throwRegister;
        int requested, abandoned;
        AudioFocusRequest last;
        BroadcastReceiver receiver;
        public boolean callActive() { return call; }
        public boolean request(AudioFocusRequest request) {
            requested++; last = request;
            if (throwRequest) throw new IllegalStateException("Synthetic denied service");
            return grant;
        }
        public void abandon(AudioFocusRequest request) { abandoned++; }
        public void register(BroadcastReceiver value) {
            if (throwRegister) throw new IllegalStateException("Synthetic receiver failure");
            receiver = value;
        }
        public void unregister(BroadcastReceiver value) { if (receiver == value) receiver = null; }
    }
    private void playbackPreparationRace(File audioFile) {
        FakeAudio port = new FakeAudio();
        AudioFocusLease coordinator = new AudioFocusLease(port);
        DelayedPlayer[] created = new DelayedPlayer[1];
        int[] errors = {0};
        AudioPlayback playback = new AudioPlayback(getTargetContext(), text -> errors[0]++, coordinator,
                () -> { created[0] = new DelayedPlayer(); return created[0]; });
        ChatStore.Attachment fixture = new ChatStore.Attachment();
        fixture.id = "fixture"; fixture.path = audioFile.getPath(); fixture.size = 4; fixture.mime = "audio/ogg";
        AudioPlayback.Target target = (phase, position, duration, speed) -> { };
        playback.toggle(fixture, target);
        check(created[0] != null && created[0].preparedCallback != null, "actual AudioPlayback awaiting prepare");
        DelayedPlayer stalePlayer = created[0];
        MediaPlayer.OnPreparedListener staleCallback = stalePlayer.preparedCallback;
        int[] stoppedRecording = {0};
        AudioFocusLease.Lease recording = coordinator.acquire(attributes(), true, reason -> stoppedRecording[0]++);
        check(recording != null && recording.active() && stalePlayer.released,
                "recording revokes preparer immediately, without waiting for prepared");
        staleCallback.onPrepared(stalePlayer);
        check(recording.active() && stoppedRecording[0] == 0 && stalePlayer.starts == 0,
                "late actual AudioPlayback callback cannot steal recording focus or start");
        check(errors[0] == 0, "owner replacement is not a user-facing codec error");
        recording.close();
        playback.toggle(fixture, target);
        DelayedPlayer normal = created[0];
        normal.preparedCallback.onPrepared(normal);
        check(normal.starts == 1, "fresh user playback starts once after preparation and focus");
        coordinator.stop();
        check(normal.pauses == 1, "owner stop pauses actual AudioPlayback");
        playback.stop();
        check(normal.released, "playback stop releases native instance");
    }
    /** Native object, deterministic asynchronous callback ordering. Does not decode an audio codec. */
    private static final class DelayedPlayer extends MediaPlayer {
        MediaPlayer.OnPreparedListener preparedCallback;
        int starts, pauses;
        boolean released;
        @Override public void setOnPreparedListener(MediaPlayer.OnPreparedListener listener) { preparedCallback = listener; }
        @Override public void setDataSource(java.io.FileDescriptor descriptor, long offset, long length) { }
        @Override public void setAudioAttributes(AudioAttributes attributes) { }
        @Override public void prepareAsync() { }
        @Override public int getDuration() { return 1000; }
        @Override public int getCurrentPosition() { return 10; }
        @Override public void start() { starts++; }
        @Override public void pause() { pauses++; }
        @Override public void release() { released = true; super.release(); }
    }
}
