package com.baseer.freshchat;

import android.content.Context;
import android.media.*;
import android.os.*;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import static com.baseer.freshchat.AudioDiagnostic.Stage;
import static com.baseer.freshchat.AudioDiagnostic.Kind;

/** Activity-scoped single player; every MediaPlayer call and callback stays on main. */
final class AudioPlayback {
    interface Target {
        void playback(PlaybackState.Phase phase, int position, int duration, float speed);
        default void playbackError(AudioDiagnostic.Event event) { }
    }
    interface Error { void show(String text); }
    interface Players { MediaPlayer create(); }
    private static final long PREPARE_TIMEOUT_MS = 15_000;
    private final Context context;
    private final Error error;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final PlaybackState state = new PlaybackState();
    private final AudioDiagnostic diagnostics = new AudioDiagnostic();
    private final AudioFocusLease audioFocus;
    private final Players players;
    private MediaPlayer player;
    private Target target;
    private ChatStore.Attachment selected;
    private boolean targetDetached;
    private Runnable prepareTimeout, detachStop;
    private AudioFocusLease.Lease focus;
    private float appliedSpeed = 1f;
    private Stage stage = Stage.SOURCE;
    private final Runnable ticker = new Runnable() {
        public void run() {
            if (player == null || state.phase() != PlaybackState.Phase.PLAYING) return;
            try { state.progress(state.token(), player.getCurrentPosition()); notifyTarget(); main.postDelayed(this, 150); }
            catch (RuntimeException failure) { fail(diagnostics.exception(Stage.PROGRESS, failure)); }
        }
    };
    AudioPlayback(Context context, Error error) {
        this(context, error, new AudioFocusLease(context));
    }
    AudioPlayback(Context context, Error error, AudioFocusLease audioFocus) {
        this(context, error, audioFocus, MediaPlayer::new);
    }
    AudioPlayback(Context context, Error error, AudioFocusLease audioFocus, Players players) {
        this.context = AppLocale.wrap(context.getApplicationContext()); this.error = error;
        this.audioFocus = audioFocus; this.players = players;
    }
    void toggle(ChatStore.Attachment file, Target view) {
        if (view == target && player != null) {
            try {
                if (state.phase() == PlaybackState.Phase.PREPARING) { stop(); return; }
                if (state.phase() == PlaybackState.Phase.PLAYING) { pause(); return; }
                if (!gainFocus()) return;
                stage = Stage.START;
                if (state.phase() == PlaybackState.Phase.COMPLETE) player.seekTo(0);
                if (state.resume(state.token())) {
                    player.start(); applySpeedSafely(); notifyTarget(); main.removeCallbacks(ticker); main.post(ticker);
                }
            } catch (RuntimeException failure) { fail(diagnostics.exception(stage, failure)); }
            return;
        }
        stop(); target = view; selected = file;
        focus = audioFocus.reserve(reason -> {
            if (state.phase() == PlaybackState.Phase.PREPARING) stop();
            else try { pause(); } catch (RuntimeException failure) { fail(diagnostics.exception(Stage.PAUSE, failure)); }
        });
        if (focus == null) { fail(diagnostics.record(Stage.FOCUS, Kind.DENIED, 0, 0)); return; }
        stage = Stage.SOURCE;
        try {
            File source = AttachmentSupport.requirePrivateFile(context, file);
            if (source.length() <= 0) throw new IOException("Empty local audio");
            long token = state.select(file.id);
            stage = Stage.SETUP;
            MediaPlayer next = players.create(); player = next;
            // Install listeners before setup so native setup errors are not silently discarded.
            next.setOnPreparedListener(ready -> prepared(ready, token));
            next.setOnCompletionListener(done -> {
                if (done != player || !state.owns(token)) return;
                state.complete(token); main.removeCallbacks(ticker); abandonFocus(); notifyTarget();
            });
            next.setOnErrorListener((failed, what, extra) -> {
                if (failed == player && state.owns(token)) fail(diagnostics.record(stage, Kind.NATIVE, what, extra));
                return true;
            });
            stage = Stage.SOURCE;
            // Private paths need not be readable by Android's separate media process. Pass an
            // app-opened read-only descriptor, never expose the file or loosen its permissions.
            // MediaPlayer duplicates the descriptor; closing our copy after setDataSource is safe.
            try (FileInputStream input = new FileInputStream(source)) {
                next.setDataSource(input.getFD(), 0, source.length());
            }
            stage = Stage.SETUP;
            next.setAudioAttributes(attributes());
            stage = Stage.PREPARE;
            notifyTarget();
            prepareTimeout = () -> {
                if (next == player && state.owns(token) && state.phase() == PlaybackState.Phase.PREPARING)
                    fail(diagnostics.record(Stage.PREPARE, Kind.TIMEOUT, 0, 0));
            };
            main.postDelayed(prepareTimeout, PREPARE_TIMEOUT_MS);
            next.prepareAsync();
        } catch (AttachmentSupport.SourceUnavailableException failure) {
            fail(diagnostics.record(stage, failure.reason == AttachmentSupport.SourceUnavailableException.Reason.MISSING ? Kind.MISSING : Kind.IO, 0, 0));
        } catch (IOException | RuntimeException failure) { fail(diagnostics.exception(stage, failure)); }
    }
    private void prepared(MediaPlayer ready, long token) {
        if (ready != player || !state.owns(token)) return;
        removePrepareTimeout();
        try {
            stage = Stage.DURATION;
            if (!state.prepared(token, ready.getDuration())) { fail(diagnostics.record(stage, Kind.INVALID, 0, 0)); return; }
            if (focus == null || !focus.active()) { stop(); return; }
            if (!focus.gainFocus(attributes(), false)) {
                fail(diagnostics.record(Stage.FOCUS, Kind.DENIED, 0, 0)); return;
            }
            stage = Stage.START;
            ready.start(); notifyTarget(); main.post(ticker);
        } catch (RuntimeException failure) { fail(diagnostics.exception(stage, failure)); }
    }
    void seek(Target view, int position) {
        if (view != target || player == null || !state.seek(state.token(), position)) return;
        stage = Stage.SEEK;
        try { player.seekTo(state.position(), MediaPlayer.SEEK_CLOSEST); notifyTarget(); }
        catch (RuntimeException failure) { fail(diagnostics.exception(stage, failure)); }
    }
    void changeSpeed(Target view) {
        if (view != target || player == null || state.phase() == PlaybackState.Phase.PREPARING) return;
        float previous = state.speed(); state.speed(previous == 1f ? 1.5f : previous == 1.5f ? 2f : 1f);
        if (state.phase() == PlaybackState.Phase.PLAYING) applySpeedSafely();
        notifyTarget();
    }
    private void applySpeedSafely() {
        if (state.speed() == appliedSpeed) return;
        try { player.setPlaybackParams(new PlaybackParams().setSpeed(state.speed()).setPitch(1f)); appliedSpeed = state.speed(); }
        catch (RuntimeException unsupported) {
            state.speed(appliedSpeed);
            AudioDiagnostic.Event event = diagnostics.exception(Stage.SPEED, unsupported);
            if (target != null) target.playbackError(event);
            error.show(AppLocale.error(context, event.guidance()) + "\n" + event.code());
        }
    }
    private void pause() {
        if (player == null || state.phase() != PlaybackState.Phase.PLAYING) return;
        stage = Stage.PAUSE;
        // Read the actual position before pausing rather than losing up to one ticker interval.
        state.progress(state.token(), player.getCurrentPosition());
        player.pause(); state.pause(state.token()); main.removeCallbacks(ticker); abandonFocus(); notifyTarget();
    }
    private boolean gainFocus() {
        abandonFocus(); stage = Stage.FOCUS;
        focus = audioFocus.acquire(attributes(), false, reason -> {
            try { pause(); } catch (RuntimeException failure) { fail(diagnostics.exception(Stage.PAUSE, failure)); }
        });
        if (focus != null && focus.active()) return true;
        fail(diagnostics.record(stage, Kind.DENIED, 0, 0)); return false;
    }
    private AudioAttributes attributes() { return new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build(); }
    private void abandonFocus() {
        AudioFocusLease.Lease old = focus; focus = null;
        if (old != null) old.close();
    }
    private void notifyTarget() { if (target != null && !targetDetached) target.playback(state.phase(), state.position(), state.duration(), state.speed()); }
    private void fail(AudioDiagnostic.Event event) {
        Target failed = target; stop();
        if (failed != null) failed.playbackError(event);
        error.show(AppLocale.error(context, event.guidance()) + "\n" + event.summary());
    }
    String diagnosticSummary() { return diagnostics.summary(); }
    private void removePrepareTimeout() { if (prepareTimeout != null) main.removeCallbacks(prepareTimeout); prepareTimeout = null; }
    void stop() {
        main.removeCallbacks(ticker); removePrepareTimeout();
        if (detachStop != null) main.removeCallbacks(detachStop); detachStop = null;
        state.stop(); appliedSpeed = 1f;
        MediaPlayer old = player; player = null;
        if (old != null) {
            try { old.setOnPreparedListener(null); old.setOnCompletionListener(null); old.setOnErrorListener(null); } catch (RuntimeException ignored) { }
            try { old.release(); } catch (RuntimeException ignored) { }
        }
        abandonFocus();
        if (target != null) target.playback(state.phase(), state.position(), state.duration(), state.speed());
        target = null; selected = null; targetDetached = false;
    }
    void attached(ChatStore.Attachment file, Target view) {
        if (!targetDetached || selected == null || player == null || !selected.id.equals(file.id)
                || selected.size != file.size || !selected.path.equals(file.path)) return;
        // A synchronous layout rebuild replaces a view, not the selected recording. Transfer
        // its UI ownership before the deferred detach check without restarting native playback.
        if (detachStop != null) main.removeCallbacks(detachStop); detachStop = null;
        Target previous = target; target = view; targetDetached = false;
        if (previous != view) previous.playback(PlaybackState.Phase.IDLE, 0, 0, 1f);
        notifyTarget();
    }
    void detached(Target view) {
        if (view != target) return;
        targetDetached = true;
        final long token = state.token();
        if (detachStop != null) main.removeCallbacks(detachStop);
        detachStop = () -> { if (targetDetached && target == view && state.owns(token)) stop(); };
        main.post(detachStop);
    }
}
