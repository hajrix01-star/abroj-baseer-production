package com.baseer.freshchat;
import android.app.Activity;
import android.os.Bundle;
import android.widget.FrameLayout;
/** Disposable host for real attached-view callbacks; never hosts the product. */
public final class MediaTestActivity extends Activity {
    FrameLayout root;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        root = new FrameLayout(this);
        setContentView(root);
    }
}
