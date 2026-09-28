package sa.abroj.baseersms.v2;

import android.content.Context;
import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.HashMap;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

/** One persistent dispatcher. Server ACKs, never a locally empty queue, establish delivery. */
public final class SyncWorker extends Worker {
    private static final String UNIQUE_WORK = "baseer-sms-v2-dispatch";
    public SyncWorker(Context context, WorkerParameters params) { super(context, params); }
    static void enqueue(Context context) {
        schedule(context, ExistingWorkPolicy.KEEP);
    }
    /** User-initiated retry: safely replaces only the scheduler, never the encrypted outbox. */
    static void retryNow(Context context) {
        schedule(context, ExistingWorkPolicy.REPLACE);
    }
    private static void schedule(Context context, ExistingWorkPolicy policy) {
        Constraints network = new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(SyncWorker.class).setConstraints(network)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build();
        WorkManager.getInstance(context).enqueueUniqueWork(UNIQUE_WORK, policy, request);
    }
    @Override public Result doWork() {
        Context context = getApplicationContext();
        if (!SecureSettings.isPaired(context) || !SecureSettings.enabled(context)) { StatusStore.error(context, "not_paired_or_disabled"); return Result.success(); }
        SmsOutbox outbox = new SmsOutbox(context);
        List<SmsOutbox.Item> claimed = null;
        try {
            refreshAllowedSenders(context);
            outbox.recoverTemporaryState();
            while (!(claimed = outbox.claimBatch(50)).isEmpty()) {
                if (deliver(context, outbox, claimed)) { heartbeat(context, outbox); return Result.retry(); }
                claimed = null;
            }
            heartbeat(context, outbox);
            return Result.success();
        } catch (PermanentAuthException error) { outbox.releaseClaimed(claimed, "pairing_required"); StatusStore.error(context, "pairing_required"); return Result.failure(); }
        catch (PermanentRequestException error) { outbox.releaseClaimed(claimed, error.code); StatusStore.error(context, error.code); return Result.failure(); }
        catch (java.net.UnknownHostException error) { outbox.releaseClaimed(claimed, "qa_address_unreachable"); StatusStore.error(context, "qa_address_unreachable"); return Result.retry(); }
        catch (java.net.SocketTimeoutException error) { outbox.releaseClaimed(claimed, "qa_timeout"); StatusStore.error(context, "qa_timeout"); return Result.retry(); }
        catch (javax.net.ssl.SSLException error) { outbox.releaseClaimed(claimed, "qa_secure_connection_failed"); StatusStore.error(context, "qa_secure_connection_failed"); return Result.retry(); }
        catch (java.net.ConnectException error) { outbox.releaseClaimed(claimed, "qa_connection_refused"); StatusStore.error(context, "qa_connection_refused"); return Result.retry(); }
        catch (Exception error) { outbox.releaseClaimed(claimed, "network_or_server_retry"); StatusStore.error(context, "network_or_server_retry"); return Result.retry(); }
    }
    /** @return true when a temporary server response requires WorkManager backoff. */
    private boolean deliver(Context context, SmsOutbox outbox, List<SmsOutbox.Item> items) throws Exception {
        JSONArray messages = new JSONArray();
        for (SmsOutbox.Item item : items) { JSONObject value = new JSONObject(); value.put("idempotency_key", item.token); value.put("sender", item.sender); value.put("body", item.body); value.put("received_at", Instant.ofEpochMilli(item.receivedAt).toString()); messages.put(value); }
        JSONObject payload = new JSONObject(); payload.put("device_code", SecureSettings.code(context)); payload.put("messages", messages);
        HttpResult response = request(context, "/baseer-bank-sms/v2/messages", payload);
        if (response.status == 401 || response.status == 403) throw new PermanentAuthException();
        if (response.status == 429 || response.status >= 500) throw new Exception("retryable_http_" + response.status);
        if (response.status != 200) throw new PermanentRequestException("http_" + response.status);
        HashMap<String, SmsOutbox.Item> claimed = new HashMap<>(); for (SmsOutbox.Item item : items) claimed.put(item.token, item);
        JSONArray acknowledgements = new JSONObject(response.body).getJSONArray("acknowledgements");
        boolean retryScheduled=false; Set<String> processed = new HashSet<>(); for (int i=0;i<acknowledgements.length();i++) { JSONObject ack=acknowledgements.getJSONObject(i); String token=ack.optString("idempotency_key"); SmsOutbox.Item item=claimed.get(token); if (item == null) continue; processed.add(token); String state=ack.optString("status");
            if ("accepted".equals(state) || "duplicate".equals(state)) { outbox.acknowledge(item.id); StatusStore.acknowledged(context, System.currentTimeMillis()); }
            else if ("blocked".equals(state)) outbox.block(item.id, ack.optString("reason", "rejected"));
            else { outbox.retry(item.id, ack.optString("reason", "retryable")); retryScheduled=true; }
        }
        for (SmsOutbox.Item item : items) if (!processed.contains(item.token)) { outbox.retry(item.id, "missing_acknowledgement"); retryScheduled=true; }
        return retryScheduled;
    }
    /** A server policy update applies before any queued or historical message leaves the device. */
    private void refreshAllowedSenders(Context context) throws Exception {
        HttpURLConnection connection=(HttpURLConnection)new URL(SecureSettings.url(context)+"/baseer-bank-sms/v2/device/config?device_code="+ URLEncoder.encode(SecureSettings.code(context), "UTF-8")).openConnection();
        connection.setConnectTimeout(15_000); connection.setReadTimeout(20_000); connection.setRequestMethod("GET"); connection.setRequestProperty("Authorization", "Bearer "+SecureSettings.secret(context));
        int status=connection.getResponseCode(); if (status == 401 || status == 403) throw new PermanentAuthException(); if (status != 200) return;
        JSONArray senders = new JSONObject(new String(readFully(connection.getInputStream()), StandardCharsets.UTF_8)).optJSONArray("senders"); if (senders == null || senders.length() == 0) return;
        List<String> values = new ArrayList<>(); for (int i=0;i<senders.length();i++) { String sender=senders.optString(i).trim(); if (!sender.isEmpty()) values.add(sender); }
        if (!values.isEmpty()) SecureSettings.saveAllowedSenders(context, values.toArray(new String[0]));
    }
    private void heartbeat(Context context, SmsOutbox outbox) throws Exception {
        JSONObject payload = new JSONObject(); payload.put("device_code", SecureSettings.code(context)); payload.put("app_version", BuildConfig.VERSION_NAME); payload.put("protocol_version", "2"); payload.put("monitoring_enabled", false);
        payload.put("queued_count", outbox.count("state IN ('queued','sending','retry_scheduled')")); payload.put("retry_count", outbox.count("state='retry_scheduled'")); payload.put("blocked_count", outbox.count("state IN ('blocked_policy','needs_repair')")); payload.put("last_error_code", StatusStore.error(context));
        HttpResult response = request(context, "/baseer-bank-sms/v2/device/heartbeat", payload);
        if (response.status == 401 || response.status == 403) throw new PermanentAuthException();
        if (response.status != 200) throw new Exception("heartbeat_" + response.status);
        StatusStore.heartbeat(context, System.currentTimeMillis());
    }
    private HttpResult request(Context context, String path, JSONObject payload) throws Exception {
        HttpURLConnection connection=(HttpURLConnection)new URL(SecureSettings.url(context)+path).openConnection(); connection.setConnectTimeout(15_000); connection.setReadTimeout(20_000); connection.setRequestMethod("POST"); connection.setRequestProperty("Content-Type","application/json"); connection.setRequestProperty("Authorization","Bearer "+SecureSettings.secret(context)); connection.setDoOutput(true);
        try(OutputStream output=connection.getOutputStream()){output.write(payload.toString().getBytes(StandardCharsets.UTF_8));}
        int status=connection.getResponseCode(); InputStream stream=status >= 400 ? connection.getErrorStream() : connection.getInputStream(); return new HttpResult(status,stream == null ? "" : new String(readFully(stream),StandardCharsets.UTF_8));
    }
    private static byte[] readFully(InputStream input) throws Exception { try (InputStream stream=input; ByteArrayOutputStream output=new ByteArrayOutputStream()) { byte[] buffer=new byte[1024]; for(int n;(n=stream.read(buffer))!=-1;)output.write(buffer,0,n); return output.toByteArray(); } }
    private static final class HttpResult { final int status; final String body; HttpResult(int status,String body){this.status=status;this.body=body;} }
    private static final class PermanentAuthException extends Exception { }
    private static final class PermanentRequestException extends Exception { final String code; PermanentRequestException(String code){this.code=code;} }
}
