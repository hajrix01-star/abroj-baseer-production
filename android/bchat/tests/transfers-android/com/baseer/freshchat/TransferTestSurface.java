package com.baseer.freshchat;
import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;
/** Visible synthetic user surface, no login/production data or network. */
public final class TransferTestSurface extends Activity{
    @Override public void onCreate(Bundle state){super.onCreate(state);TextView view=new TextView(this);
        view.setText("Synthetic UIDT acceptance — no production data");setContentView(view);}
}
