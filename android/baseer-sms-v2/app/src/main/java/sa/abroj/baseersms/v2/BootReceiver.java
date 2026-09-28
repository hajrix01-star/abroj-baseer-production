package sa.abroj.baseersms.v2;
import android.content.BroadcastReceiver; import android.content.Context; import android.content.Intent;
public final class BootReceiver extends BroadcastReceiver { @Override public void onReceive(Context context, Intent intent) { if (Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction()) && SecureSettings.isPaired(context) && SecureSettings.enabled(context)) SyncWorker.enableBackgroundWork(context); } }
