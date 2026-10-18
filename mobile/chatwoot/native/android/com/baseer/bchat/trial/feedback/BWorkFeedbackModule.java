package com.baseer.bchat.trial.feedback;

import android.app.NotificationManager;
import android.content.Context;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.Handler;
import android.os.Looper;
import com.facebook.react.bridge.LifecycleEventListener;
import com.facebook.react.bridge.Promise;
import com.facebook.react.bridge.ReactApplicationContext;
import com.facebook.react.bridge.ReactContextBaseJavaModule;
import com.facebook.react.bridge.ReactMethod;
import com.facebook.react.common.LifecycleState;

/** No service, audio focus, volume mutation, network, credentials or message inputs. */
public final class BWorkFeedbackModule extends ReactContextBaseJavaModule implements LifecycleEventListener {
    private final Handler main = new Handler(Looper.getMainLooper());
    private final FeedbackController controller = new FeedbackController(() -> {
        final ToneGenerator tone = new ToneGenerator(AudioManager.STREAM_NOTIFICATION, 25);
        return new FeedbackController.Player() {
            public boolean start(String kind, int duration) {
                return tone.startTone("send".equals(kind) ? ToneGenerator.TONE_PROP_BEEP : ToneGenerator.TONE_PROP_ACK, duration);
            }
            public void release() { try { tone.stopTone(); } finally { tone.release(); } }
        };
    });
    public BWorkFeedbackModule(ReactApplicationContext context) { super(context); context.addLifecycleEventListener(this); }
    @Override public String getName() { return "BWorkFeedback"; }
    @ReactMethod public void play(String kind, Promise promise) {
        main.post(() -> {
            boolean accepted = false;
            try {
                ReactApplicationContext context = getReactApplicationContext();
                AudioManager audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
                NotificationManager notifications = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
                accepted = controller.play(kind,
                    context.getLifecycleState() == LifecycleState.RESUMED && getCurrentActivity() != null,
                    audio != null && audio.getRingerMode() == AudioManager.RINGER_MODE_NORMAL
                        && audio.getMode() == AudioManager.MODE_NORMAL && !audio.isMusicActive(),
                    audio == null ? 0 : audio.getStreamVolume(AudioManager.STREAM_NOTIFICATION),
                    notifications != null && notifications.getCurrentInterruptionFilter() == NotificationManager.INTERRUPTION_FILTER_ALL);
                if (accepted) {
                    final int revision = controller.revision();
                    main.postDelayed(() -> controller.stopIfRevision(revision), 200);
                }
            } catch (RuntimeException denied) { controller.stop(); }
            promise.resolve(accepted);
        });
    }
    @ReactMethod public void stop() { main.post(controller::stop); }
    @Override public void onHostResume() {}
    @Override public void onHostPause() { controller.stop(); }
    @Override public void onHostDestroy() { controller.stop(); }
    @Override public void invalidate() {
        main.removeCallbacksAndMessages(null); controller.stop();
        getReactApplicationContext().removeLifecycleEventListener(this); super.invalidate();
    }
}
