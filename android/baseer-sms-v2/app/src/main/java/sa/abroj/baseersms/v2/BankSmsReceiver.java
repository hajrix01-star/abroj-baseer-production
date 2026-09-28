package sa.abroj.baseersms.v2;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.provider.Telephony;
import android.telephony.SmsMessage;

/** Captures only after explicit pairing/enablement and hands off promptly to persistent work. */
public final class BankSmsReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (!Telephony.Sms.Intents.SMS_RECEIVED_ACTION.equals(intent.getAction()) || !SecureSettings.isPaired(context) || !SecureSettings.enabled(context)) return;
        SmsMessage[] parts = Telephony.Sms.Intents.getMessagesFromIntent(intent); if (parts == null || parts.length == 0) return;
        String sender = parts[0].getOriginatingAddress(); if (!SecureSettings.isAllowedSender(context, sender)) return;
        StringBuilder body = new StringBuilder(); for (SmsMessage part : parts) body.append(part.getMessageBody());
        try { new SmsOutbox(context).capture(sender, body.toString(), parts[0].getTimestampMillis()); SyncWorker.enqueue(context); }
        catch (RuntimeException ignored) { StatusStore.error(context, "capture_failed"); }
    }
}
