package com.baseer.freshchat;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;

/** One Activity coordinator for playback/preview/recording. Focus never authenticates media. */
final class AudioFocusLease {
    static final int OWNER_CHANGED = 1, FOCUS_LOST = 2, ROUTE_LOST = 3;
    interface Interrupted { void stop(int reason); }
    /** Narrow Android boundary. Tests replace only external focus/route decisions, not ownership. */
    interface Platform {
        boolean callActive();
        boolean request(AudioFocusRequest request);
        void abandon(AudioFocusRequest request);
        void register(BroadcastReceiver receiver);
        void unregister(BroadcastReceiver receiver);
    }
    private final Platform platform;
    private final Handler main = new Handler(Looper.getMainLooper());
    private Lease current;
    private long generation;

    AudioFocusLease(Context context) {
        this(new AndroidPlatform(context.getApplicationContext()));
    }

    AudioFocusLease(Platform platform) {
        if (platform == null) throw new IllegalArgumentException("Audio platform required");
        this.platform = platform;
    }

    /** Returns null on denial; no delayed focus or automatic start/resume is permitted. */
    Lease acquire(AudioAttributes attributes, boolean recording, Interrupted interrupted) {
        requireMain();
        if (interrupted == null || attributes == null) throw new IllegalArgumentException("Audio owner required");
        Lease next = reserve(interrupted);
        return next != null && next.gainFocus(attributes, recording) ? next : null;
    }

    /** Reserve at the user action, before asynchronous media preparation/download completes. */
    Lease reserve(Interrupted interrupted) {
        requireMain();
        if (interrupted == null) throw new IllegalArgumentException("Audio owner required");
        long request = ++generation;
        if (!interruptCurrent(OWNER_CHANGED)) return null;
        // The old owner's callback may itself have switched ownership.
        if (generation != request) return null;
        Lease next = new Lease(interrupted);
        current = next;
        return next;
    }

    void stop() {
        requireMain();
        ++generation;
        interruptCurrent(OWNER_CHANGED);
    }

    private boolean interruptCurrent(int reason) {
        Lease previous = current;
        if (previous == null) return true;
        previous.close(); // Clear ownership before a callback can acquire a replacement.
        try { previous.interrupted.stop(reason); return true; }
        catch (RuntimeException failedOwnerCleanup) { return false; } // Never start a second owner after failed cleanup.
    }

    private static void requireMain() {
        if (Looper.myLooper() != Looper.getMainLooper())
            throw new IllegalStateException("Audio focus ownership must stay on main");
    }

    final class Lease implements AutoCloseable, AudioManager.OnAudioFocusChangeListener {
        private final Interrupted interrupted;
        private AudioFocusRequest request;
        private boolean registered;
        private final BroadcastReceiver noisy = new BroadcastReceiver() {
            @Override public void onReceive(Context ignored, Intent intent) {
                if (current == Lease.this && intent != null
                        && AudioManager.ACTION_AUDIO_BECOMING_NOISY.equals(intent.getAction()))
                    interruptCurrent(ROUTE_LOST);
            }
        };
        private Lease(Interrupted interrupted) { this.interrupted = interrupted; }
        boolean gainFocus(AudioAttributes attributes, boolean recording) {
            requireMain();
            // An old prepared/download callback must never reserve itself again.
            if (current != this || attributes == null) return false;
            if (request != null) return registered;
            try {
                if (recording && platform.callActive()) { close(); return false; }
                request = new AudioFocusRequest.Builder(recording
                        ? AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE : AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                        .setAudioAttributes(attributes).setWillPauseWhenDucked(true)
                        .setOnAudioFocusChangeListener(this, main).build();
                if (!platform.request(request)) { close(); return false; }
                if (current != this) return false;
                registered = true;
                platform.register(noisy);
                return current == this;
            } catch (RuntimeException unavailable) { close(); return false; }
        }
        @Override public void onAudioFocusChange(int change) {
            requireMain();
            if (current == this && change < 0) interruptCurrent(FOCUS_LOST);
            // GAIN is deliberately not a resume instruction.
        }
        boolean active() { requireMain(); return current == this; }
        @Override public void close() {
            requireMain();
            // Stale releases cannot abandon a newer recording/player's focus.
            if (current != this) return;
            current = null;
            if (registered) {
                registered = false;
                try { platform.unregister(noisy); } catch (RuntimeException ignored) { }
            }
            AudioFocusRequest prior = request;
            request = null;
            if (prior != null)
                try { platform.abandon(prior); } catch (RuntimeException ignored) { }
        }
    }

    private static final class AndroidPlatform implements Platform {
        private final Context context;
        private final AudioManager manager;
        AndroidPlatform(Context context) {
            this.context = context;
            manager = context.getSystemService(AudioManager.class);
        }
        public boolean callActive() {
            return manager == null || manager.getMode() == AudioManager.MODE_IN_CALL
                    || manager.getMode() == AudioManager.MODE_IN_COMMUNICATION;
        }
        public boolean request(AudioFocusRequest request) {
            return manager != null && manager.requestAudioFocus(request) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
        }
        public void abandon(AudioFocusRequest request) {
            if (manager != null) manager.abandonAudioFocusRequest(request);
        }
        public void register(BroadcastReceiver receiver) {
            IntentFilter filter = new IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY);
            if (Build.VERSION.SDK_INT >= 33)
                context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
            else context.registerReceiver(receiver, filter);
        }
        public void unregister(BroadcastReceiver receiver) { context.unregisterReceiver(receiver); }
    }
}
