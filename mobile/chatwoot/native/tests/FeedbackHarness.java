package com.baseer.bchat.trial.feedback;

public final class FeedbackHarness {
    static int created, released, started;
    static boolean fail;
    static String lastKind;
    static int duration;
    public static void main(String[] args) {
        FeedbackController owner = new FeedbackController(() -> {
            created++;
            return new FeedbackController.Player() {
                public boolean start(String kind, int milliseconds) {
                    started++; lastKind = kind; duration = milliseconds;
                    if (fail) throw new IllegalStateException("synthetic unavailable output");
                    return true;
                }
                public void release() { released++; }
            };
        });
        for (int gate = 0; gate < 4; gate++) {
            assert !owner.play("send", gate != 0, gate != 1, gate == 2 ? 0 : 5, gate != 3);
        }
        assert !owner.play("unknown", true, true, 5, true);
        assert created == 0;
        assert owner.play("send", true, true, 5, true);
        assert "send".equals(lastKind) && duration == 70;
        int first = owner.revision();
        assert owner.play("receive", true, true, 5, true);
        assert created == 2 && released == 1 && duration == 120;
        owner.stopIfRevision(first); assert released == 1;
        owner.stopIfRevision(owner.revision()); assert released == 2;
        owner.stop(); assert released == 2;
        assert owner.play("receive", true, true, 5, true);
        owner.stop(); assert released == 3; // host pause, destroy, mute and voice share this path
        fail = true;
        assert !owner.play("send", true, true, 5, true);
        assert released == 4 && created == 4 && started == 4;
        System.out.println("FeedbackController: silent/volume/DND/foreground/kind, duration, one resource, late timer, stop/release and failure PASS");
    }
}
