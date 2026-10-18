package android.app;
public final class NotificationChannel {
    public final String id;public final CharSequence name;
    public int importance,visibility=1,lightColor;public Object sound="default",attributes="default-attributes",effect;
    public boolean vibration=true,badge=true,lights=true,bypass=true,registered;public long[] pattern={0,100};
    public int mutations;
    public NotificationChannel(String id,CharSequence name,int importance){this.id=id;this.name=name;this.importance=importance;}
    private void setter(){if(registered)throw new AssertionError("Existing registered channel was reconfigured");++mutations;}
    public int getImportance(){return importance;}
    public Object getSound(){return sound;}public Object getAudioAttributes(){return attributes;}
    public long[] getVibrationPattern(){return pattern;}
    public Object getVibrationEffect(){if(android.os.Build.VERSION.SDK_INT<35)throw new AssertionError("API35 called on26");return effect;}
    public boolean shouldVibrate(){return vibration;}
    public boolean canShowBadge(){return badge;}
    public boolean shouldShowLights(){return lights;}
    public int getLightColor(){return lightColor;}
    public int getLockscreenVisibility(){return visibility;}
    public void setSound(Object sound,Object attributes){setter();this.sound=sound;this.attributes=attributes;}
    public void setVibrationPattern(long[] pattern){setter();this.pattern=pattern;vibration=pattern!=null&&pattern.length>0;}
    public void setVibrationEffect(Object effect){setter();this.effect=effect;vibration=effect!=null;}
    public void enableVibration(boolean enabled){setter();vibration=enabled;}
    public void setShowBadge(boolean enabled){setter();badge=enabled;}
    public void enableLights(boolean enabled){setter();lights=enabled;}
    public void setLightColor(int color){setter();lightColor=color;}
    public void setLockscreenVisibility(int visibility){setter();this.visibility=visibility;}
    public void setBypassDnd(boolean enabled){setter();bypass=enabled;}
}
