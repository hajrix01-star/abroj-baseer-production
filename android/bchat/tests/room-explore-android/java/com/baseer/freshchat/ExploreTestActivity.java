package com.baseer.freshchat;

import android.app.Activity;
import android.content.Context;
import android.content.res.Configuration;
import android.os.Bundle;
import android.widget.TextView;
import com.baseer.freshchat.sync.AccountScope;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** Only a native component Host. Not OdooIdentityActivity, authenticated HTTP, media, or receipt integration. */
public final class ExploreTestActivity extends Activity {
    static String language="ar";
    static boolean dark;
    static float scale=1;
    static final AccountScope ACCOUNT=new AccountScope("https://explore.invalid","synthetic",7);
    BChatRoomExplorePanel panel;
    FakeHost host;
    int pauses;
    @Override protected void attachBaseContext(Context base){
        Configuration c=new Configuration(base.getResources().getConfiguration());Locale locale=Locale.forLanguageTag(language);
        c.setLocale(locale);c.setLayoutDirection(locale);c.fontScale=scale;
        c.uiMode=(c.uiMode&~Configuration.UI_MODE_NIGHT_MASK)|(dark?Configuration.UI_MODE_NIGHT_YES:Configuration.UI_MODE_NIGHT_NO);
        super.attachBaseContext(base.createConfigurationContext(c));
    }
    @Override public void onCreate(Bundle state){
        setTheme(ChatAppearance.themeResource(this));super.onCreate(state);
        TextView root=new TextView(this);root.setText("Isolated C16 Host — synthetic auth/HTTP/formatter");
        root.setBackgroundColor(UiPalette.canvas(this));setContentView(root);
    }
    void open(boolean gallery,boolean media,boolean supported){
        if(panel!=null)panel.dismiss();host=new FakeHost();host.media=media;host.supported=supported;
        panel=new BChatRoomExplorePanel(this,host,ACCOUNT,12,41,9,gallery);panel.show();
    }
    @Override protected void onPause(){++pauses;if(panel!=null)panel.dismiss();super.onPause();}
    @Override protected void onDestroy(){if(panel!=null)panel.dismiss();super.onDestroy();}
    static final class Read {
        final RoomExploreProtocol.Query query;final BChatRoomExplorePanel.Reply reply;
        Read(RoomExploreProtocol.Query query,BChatRoomExplorePanel.Reply reply){this.query=query;this.reply=reply;}
    }
    static final class FakeHost implements BChatRoomExplorePanel.Host {
        AccountScope account=ACCOUNT;
        boolean active=true,media=true,supported=true,accept=true;
        long room=12,member=41,generation=9,opened;
        int attempts;
        final List<Read> reads=new ArrayList<>();
        public AccountScope account(){return account;}
        public boolean current(AccountScope scope,long room,long member,long generation){
            return active&&scope==account&&room==this.room&&member==this.member&&generation==this.generation;
        }
        public boolean supported(){return supported;}
        public boolean mediaAllowed(){return media;}
        public boolean read(RoomExploreProtocol.Query query,BChatRoomExplorePanel.Reply reply){
            ++attempts;
            if(!accept||!current(ACCOUNT,query.roomId,query.membershipId,9))return false;
            reads.add(new Read(query,reply));return true; // Deliberately held synthetic HTTP-shaped reply.
        }
        public void openMessage(long id){if(current(ACCOUNT,12,41,9))opened=id;}
        public String timeLabel(String utcStamp){return "12:34 · synthetic formatter";}
    }
    public static final class PauseActivity extends Activity {
        @Override public void onCreate(Bundle state){super.onCreate(state);TextView text=new TextView(this);text.setText("Native pause boundary");setContentView(text);}
    }
}
