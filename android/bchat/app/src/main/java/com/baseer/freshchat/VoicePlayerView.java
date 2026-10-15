package com.baseer.freshchat;

import android.app.AlertDialog;
import android.content.Context;
import android.graphics.Color;
import android.text.TextUtils;
import android.view.*;
import android.widget.*;
import java.util.Locale;
import static com.baseer.freshchat.Ui.*;

/** Full-width voice control reused in a draft, message and attachment inspector. */
final class VoicePlayerView extends LinearLayout implements AudioPlayback.Target {
    private final AudioPlayback player;
    private final ChatStore.Attachment file;
    private final AudioWaveforms waves;
    private final Runnable details;
    private AudioDiagnostic.Event playbackFailure;
    private AlertDialog failureDialog;
    private PlaybackState.Phase displayedPhase = PlaybackState.Phase.IDLE;
    private String waveStatus = s(R.string.ui_363);
    private AudioWaveforms.Request analysis;
    private int analysisEpoch;
    private final Runnable analysisRetry = this::loadWaveform;
    private final TextView play, timer, speed, status;
    private final WaveformView waveform;
    private final SeekBar seek;
    private int knownDuration;
    private boolean dragging;
    VoicePlayerView(Context context, ChatStore.Attachment file, AudioPlayback player, AudioWaveforms waves, Runnable details, boolean compact) {
        super(context); this.player = player; this.file = file; this.waves = waves; this.details = details;
        setOrientation(VERTICAL); setLayoutDirection(AppLocale.direction(context)); pad(this, 8, compact ? 2 : 6); setBackground(bg(LIGHT, 14, context));
        TextView name = text(context, s(R.string.audio_clip_name, AppLocale.name(context, file.name)), 10, MUTED, false); name.setSingleLine(); name.setEllipsize(TextUtils.TruncateAt.MIDDLE);
        if (!compact) addView(name, lp(-1, -2));
        LinearLayout controls = row(context); controls.setLayoutDirection(LAYOUT_DIRECTION_LTR);
        play = text(context, "▶", 20, GREEN, true); play.setGravity(Gravity.CENTER); play.setContentDescription(s(R.string.ui_360)); clickable(play);
        play.setOnClickListener(v -> player.toggle(file, this)); controls.addView(play, lp(dp(context, 48), dp(context, 48)));
        LinearLayout track = column(context); waveform = new WaveformView(context); waveform.setLayoutDirection(LAYOUT_DIRECTION_LTR); track.addView(waveform, lp(-1, dp(context, 24)));
        seek = new SeekBar(context); seek.setLayoutDirection(LAYOUT_DIRECTION_LTR); seek.setMax(1000); seek.setEnabled(false); seek.setContentDescription(s(R.string.ui_361));
        seek.setPadding(dp(context, 10), 0, dp(context, 10), 0); track.addView(seek, lp(-1, dp(context, 24)));
        controls.addView(track, new LinearLayout.LayoutParams(0, -2, 1));
        speed = text(context, "1×", 12, GREEN, true); speed.setGravity(Gravity.CENTER); speed.setContentDescription(s(R.string.ui_362));
        speed.setEnabled(false); clickable(speed); speed.setOnClickListener(v -> player.changeSpeed(this)); controls.addView(speed, lp(dp(context, 44), dp(context, 48)));
        addView(controls, lp(-1, -2));
        LinearLayout meta = row(context); meta.setLayoutDirection(LAYOUT_DIRECTION_LTR); timer = text(context, "0:00 / --:--", 11, INK, false); timer.setTextDirection(TEXT_DIRECTION_LTR);
        meta.addView(timer); status = text(context, s(R.string.ui_363), 9, MUTED, false); status.setGravity(Gravity.END); status.setSingleLine(); status.setEllipsize(TextUtils.TruncateAt.END);
        status.setOnClickListener(v -> showPlaybackFailure());
        meta.addView(status, new LinearLayout.LayoutParams(0, -2, 1));
        if (details != null) { TextView more = text(context, "⋮", 20, MUTED, true); more.setGravity(Gravity.CENTER); more.setContentDescription(s(R.string.ui_364)); more.setOnClickListener(v -> details.run()); meta.addView(more, lp(dp(context, 40), dp(context, 32))); }
        addView(meta, lp(-1, -2));
        seek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onStartTrackingTouch(SeekBar bar) { dragging = true; }
            public void onStopTrackingTouch(SeekBar bar) { dragging = false; player.seek(VoicePlayerView.this, bar.getProgress()); }
            public void onProgressChanged(SeekBar bar, int value, boolean user) {
                if (user) { timer.setText(format(value) + " / " + format(knownDuration)); if (!dragging) player.seek(VoicePlayerView.this, value); }
            }
        });
    }
    protected void onAttachedToWindow() {
        super.onAttachedToWindow(); player.attached(file, this); loadWaveform();
    }
    private void loadWaveform() {
        removeCallbacks(analysisRetry);
        if (!isAttachedToWindow()) return;
        if (analysis != null) analysis.cancel();
        final int epoch = ++analysisEpoch;
        analysis = waves.load(file, result -> {
            if (!isAttachedToWindow() || epoch != analysisEpoch) return;
            if (result.busy) {
                waveStatus = s(R.string.ui_365); updateStatus();
                // One retry per attached view. Busy is not a permanent unsupported-file result.
                removeCallbacks(analysisRetry); postDelayed(analysisRetry, 750); return;
            }
            if (result.duration > 0 && knownDuration == 0) { knownDuration = result.duration; timer.setText("0:00 / " + format(knownDuration)); }
            waveform.samples(result.peaks);
            waveStatus = result.peaks == null ? s(R.string.ui_366) : s(R.string.ui_367); updateStatus();
        });
    }
    public void playback(PlaybackState.Phase phase, int position, int duration, float rate) {
        boolean preparing = phase == PlaybackState.Phase.PREPARING;
        boolean playing = phase == PlaybackState.Phase.PLAYING;
        displayedPhase = phase;
        if (preparing) { playbackFailure = null; status.setTextColor(MUTED); status.setContentDescription(null); }
        updateStatus();
        if (duration > 0) knownDuration = duration;
        play.setText(preparing ? "×" : playing ? "Ⅱ" : "▶"); play.setContentDescription(preparing ? s(R.string.ui_371) : playing ? s(R.string.ui_372) : s(R.string.ui_360));
        boolean available = phase != PlaybackState.Phase.IDLE && !preparing;
        seek.setEnabled(available); speed.setEnabled(available); speed.setAlpha(available ? 1f : .45f);
        speed.setText(String.format(Locale.ROOT, "%s×", rate == (int)rate ? String.valueOf((int)rate) : String.valueOf(rate)));
        if (!dragging) { seek.setMax(Math.max(1, knownDuration)); seek.setProgress(position); timer.setText(format(position) + " / " + (knownDuration > 0 ? format(knownDuration) : "--:--")); }
        waveform.progress(knownDuration > 0 ? position / (float)knownDuration : 0f);
    }
    private void updateStatus() {
        if (playbackFailure != null) return;
        switch (displayedPhase) {
            case PREPARING: status.setText(s(R.string.ui_368)); break;
            case PLAYING: status.setText(s(R.string.ui_370)); break;
            case PAUSED: status.setText(s(R.string.audio_paused)); break;
            case COMPLETE: status.setText(s(R.string.audio_complete)); break;
            default: status.setText(waveStatus);
        }
    }
    public void playbackError(AudioDiagnostic.Event event) {
        playbackFailure = event;
        status.setText(s(R.string.ui_373)); status.setTextColor(Color.rgb(153, 53, 40));
        if (event.stage == AudioDiagnostic.Stage.SPEED) status.setText(s(R.string.ui_374));
        status.setContentDescription(s(R.string.audio_diagnostic_accessibility, AppLocale.error(getContext(), event.guidance()), event.summary()));
    }
    private void showPlaybackFailure() {
        if (playbackFailure == null || !isAttachedToWindow()) return;
        if (failureDialog != null) failureDialog.dismiss();
        final AudioDiagnostic.Event shown = playbackFailure;
        final String safeSummary = shown.summary();
        AlertDialog.Builder dialog = new AlertDialog.Builder(getContext()).setTitle(s(R.string.ui_376))
                .setMessage(s(R.string.audio_diagnostic_body, AppLocale.error(getContext(), shown.guidance()), safeSummary))
                .setPositiveButton(s(R.string.ui_051), null)
                .setNegativeButton(s(R.string.audio_copy_code), (closed, which) -> {
                    if (!isAttachedToWindow()) return;
                    try {
                        android.content.ClipboardManager clipboard = (android.content.ClipboardManager)
                                getContext().getSystemService(Context.CLIPBOARD_SERVICE);
                        clipboard.setPrimaryClip(android.content.ClipData.newPlainText(s(R.string.audio_code_label), safeSummary));
                        Toast.makeText(getContext(), s(R.string.audio_code_copied), Toast.LENGTH_LONG).show();
                    } catch (RuntimeException unavailable) {
                        Toast.makeText(getContext(), s(R.string.audio_code_copy_failed), Toast.LENGTH_LONG).show();
                    }
                });
        if (details != null) dialog.setNeutralButton(s(R.string.ui_379), (d, which) -> { if (isAttachedToWindow()) details.run(); });
        failureDialog = dialog.create();
        failureDialog.setOnDismissListener(closed -> { if (failureDialog == closed) failureDialog = null; });
        failureDialog.show();
    }
    protected void onDetachedFromWindow() {
        if (failureDialog != null) { failureDialog.dismiss(); failureDialog = null; }
        ++analysisEpoch; removeCallbacks(analysisRetry);
        if (analysis != null) { analysis.cancel(); analysis = null; }
        player.detached(this); super.onDetachedFromWindow();
    }
    private String s(int resource, Object... arguments) { return arguments.length == 0 ? getContext().getString(resource) : getContext().getString(resource, arguments); }
    static String format(long millis) { long seconds = Math.max(0, millis) / 1000; return String.format(Locale.ROOT, "%d:%02d", seconds / 60, seconds % 60); }
}
