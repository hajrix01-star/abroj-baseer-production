package com.baseer.freshchat;

/** Pure playback ownership model. A stale callback can never change a newer clip. */
public final class PlaybackState {
    public enum Phase { IDLE, PREPARING, PLAYING, PAUSED, COMPLETE }
    private long generation;
    private String clip;
    private Phase phase = Phase.IDLE;
    private int duration, position;
    private float speed = 1f;

    public long select(String id) {
        if (id == null || id.isEmpty()) throw new IllegalArgumentException("Clip required");
        stop(); clip = id; phase = Phase.PREPARING; return generation;
    }
    public boolean prepared(long token, int millis) {
        if (!owns(token) || phase != Phase.PREPARING || millis <= 0) return false;
        duration = millis; phase = Phase.PLAYING; return true;
    }
    public boolean pause(long token) {
        if (!owns(token) || phase != Phase.PLAYING) return false;
        phase = Phase.PAUSED; return true;
    }
    public boolean resume(long token) {
        if (!owns(token) || (phase != Phase.PAUSED && phase != Phase.COMPLETE)) return false;
        if (phase == Phase.COMPLETE) position = 0;
        phase = Phase.PLAYING; return true;
    }
    public boolean complete(long token) {
        if (!owns(token) || phase == Phase.PREPARING) return false;
        position = duration; phase = Phase.COMPLETE; return true;
    }
    public boolean seek(long token, int millis) {
        if (!owns(token) || phase == Phase.PREPARING) return false;
        position = Math.max(0, Math.min(duration, millis));
        if (phase == Phase.COMPLETE) phase = Phase.PAUSED;
        return true;
    }
    public void progress(long token, int millis) {
        if (owns(token) && phase == Phase.PLAYING) position = Math.max(0, Math.min(duration, millis));
    }
    public void speed(float value) {
        if (value != 1f && value != 1.5f && value != 2f) throw new IllegalArgumentException("Unsupported speed");
        speed = value;
    }
    public void stop() { ++generation; clip = null; phase = Phase.IDLE; duration = 0; position = 0; speed = 1f; }
    public boolean owns(long token) { return clip != null && token == generation; }
    public long token() { return generation; }
    public Phase phase() { return phase; }
    public int duration() { return duration; }
    public int position() { return position; }
    public float speed() { return speed; }
    public String clip() { return clip; }
}
