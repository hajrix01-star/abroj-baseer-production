package android.app;
import java.util.*;
import com.baseer.freshchat.ChannelRoutingHarness;
public final class NotificationManager {
    public static final int IMPORTANCE_NONE=0,IMPORTANCE_MIN=1,IMPORTANCE_LOW=2,IMPORTANCE_DEFAULT=3,IMPORTANCE_HIGH=4;
    public final Map<String,NotificationChannel> channels=new HashMap<>();
    public int creates,reads;public boolean failRead,failCreate,dropCreate;
    public String failOnCreate;public Runnable beforeCreate;
    public NotificationChannel getNotificationChannel(String id){ChannelRoutingHarness.platform();++reads;if(failRead)throw new SecurityException("synthetic read failure");return channels.get(id);}
    public void createNotificationChannel(NotificationChannel channel){
        ChannelRoutingHarness.platform();if(beforeCreate!=null)beforeCreate.run();
        if(failCreate||channel.id.equals(failOnCreate))throw new SecurityException("synthetic create failure");
        ++creates;if(dropCreate)return;
        if(channels.containsKey(channel.id))throw new AssertionError("Existing channel was submitted again");
        channel.registered=true;channels.put(channel.id,channel);
    }
    public void deleteNotificationChannel(String id){throw new AssertionError("Channel deletion is forbidden");}
}
