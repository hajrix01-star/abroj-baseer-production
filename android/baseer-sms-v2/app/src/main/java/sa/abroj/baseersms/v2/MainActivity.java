package sa.abroj.baseersms.v2;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.DatePickerDialog;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.widget.Button;
import android.widget.TextView;
import com.google.android.gms.tasks.Task;
import com.google.mlkit.vision.barcode.common.Barcode;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanner;
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning;
import java.text.DateFormat;
import java.util.Date;
import java.util.Calendar;

public final class MainActivity extends Activity {
    private TextView connection, heartbeat, lastCaptured, lastAck, queue, blocked, error; private final Handler handler=new Handler();
    private final Runnable refreshTask=new Runnable(){@Override public void run(){refresh();handler.postDelayed(this,2000);}};
    @Override public void onCreate(Bundle state){super.onCreate(state);SecureSettings.retireLegacyV1Dispatchers(this);setContentView(R.layout.activity_main);((TextView)findViewById(R.id.environment)).setText(BuildConfig.ENVIRONMENT_LABEL+" · تطبيق الجسر الآمن · الإصدار "+BuildConfig.VERSION_NAME+"\nبُني: "+BuildConfig.BUILD_TIMESTAMP);connection=findViewById(R.id.connection);heartbeat=findViewById(R.id.heartbeat);lastCaptured=findViewById(R.id.last_captured);lastAck=findViewById(R.id.last_ack);queue=findViewById(R.id.queue);blocked=findViewById(R.id.blocked);error=findViewById(R.id.error);
        findViewById(R.id.permission).setOnClickListener(v->requestPermissions(new String[]{Manifest.permission.RECEIVE_SMS},11));findViewById(R.id.pair).setOnClickListener(v->scan());findViewById(R.id.retry_connection).setOnClickListener(v->retryConnection());findViewById(R.id.import_history).setOnClickListener(v->chooseImport());if(SecureSettings.isPaired(this)&&SecureSettings.enabled(this))SyncWorker.enqueue(this);refresh();}
    @Override protected void onResume(){super.onResume();handler.post(refreshTask);} @Override protected void onPause(){handler.removeCallbacks(refreshTask);super.onPause();}
    private void refresh(){boolean permission=checkSelfPermission(Manifest.permission.RECEIVE_SMS)==PackageManager.PERMISSION_GRANTED; long hb=StatusStore.heartbeatAt(this);long now=System.currentTimeMillis();boolean live=SecureSettings.isPaired(this)&&permission&&hb>0&&now-hb<=120000;
        if(!SecureSettings.isPaired(this)){connection.setText("غير مربوط");connection.setTextColor(Color.rgb(155,28,28));}
        else if(!permission){connection.setText("يلزم إذن استقبال الرسائل");connection.setTextColor(Color.rgb(180,83,9));}
        else if(live){connection.setText("متصل الآن");connection.setTextColor(Color.rgb(21,128,61));}
        else {connection.setText("لا يوجد اتصال حي مؤكد");connection.setTextColor(Color.rgb(180,83,9));}
        heartbeat.setText(hb==0?"لم يصل تأكيد من الخادم بعد":"آخر تأكيد من "+BuildConfig.ENVIRONMENT_LABEL+": "+format(hb));SmsOutbox outbox=new SmsOutbox(this);long captured=outbox.latestCapturedAt();int pending=outbox.countPending(), blockedCount=outbox.countBlocked();long ack=StatusStore.lastAckAt(this);lastCaptured.setText(captured==0?"لم يحفظ التطبيق أي رسالة بعد":"آخر رسالة حفظها التطبيق: "+format(captured));if(captured==0)lastAck.setText("لا توجد رسالة للمقارنة بعد");else if(pending==0&&ack>0)lastAck.setText(blockedCount==0?"المزامنة مكتملة حتى الرسالة أعلاه":"اكتملت الرسائل القابلة للتسليم");else lastAck.setText("المزامنة غير مكتملة: بانتظار تأكيد "+BuildConfig.ENVIRONMENT_LABEL);queue.setText("رسائل بانتظار التسليم: "+pending);blocked.setText(blockedCount==0?"":"رسائل تحتاج مراجعة: "+blockedCount+" — "+blockedReason(outbox.primaryBlockedReason()));((Button)findViewById(R.id.retry_connection)).setText(pending>0?"استئناف مزامنة "+pending+" رسالة معلقة":"فحص الاتصال وإعادة المحاولة");String issue=StatusStore.error(this);error.setText(issue.isEmpty()?"":("يحتاج انتباه: "+describe(issue)));}
    private String describe(String code){if("pairing_required".equals(code))return "يحتاج إعادة ربط الجهاز";if("manual_retry_started".equals(code))return "جارٍ اختبار الاتصال مع "+BuildConfig.ENVIRONMENT_LABEL+" الآن";if("qa_address_unreachable".equals(code))return "تعذر الوصول إلى الخادم؛ تحقق من الإنترنت";if("qa_timeout".equals(code))return "الخادم لم يرد خلال المهلة؛ ستتم إعادة المحاولة تلقائيًا";if("qa_secure_connection_failed".equals(code))return "تعذر إنشاء اتصال آمن مع الخادم";if("qa_connection_refused".equals(code))return "الخدمة رفضت الاتصال مؤقتًا";if("network_or_server_retry".equals(code))return "تعذر الوصول إلى الشبكة أو الخادم؛ ستتم إعادة المحاولة تلقائيًا";if("history_import_retry".equals(code))return "توقف الاستيراد مؤقتًا وسيُستأنف";return code;}
    private String blockedReason(String code){if("sender_not_allowed".equals(code))return "مرسل غير معتمد";if("rate_limit_exceeded".equals(code))return "سيُعاد تلقائيًا بعد حد السرعة";if(code==null||code.isEmpty())return "سبب غير محدد";return "تحتاج مراجعة";}
    private String format(long time){return DateFormat.getDateTimeInstance(DateFormat.MEDIUM,DateFormat.SHORT).format(new Date(time));}
    private void scan(){GmsBarcodeScanner scanner=GmsBarcodeScanning.getClient(this,new GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build());Task<Barcode> task=scanner.startScan();task.addOnSuccessListener(code->{String raw=code.getRawValue();if(raw==null||raw.isEmpty())return;try{String url=new org.json.JSONObject(raw).getString("url");new AlertDialog.Builder(this).setTitle("تأكيد الربط").setMessage("سيُرسل التطبيق الرسائل المسموح بها إلى:\n"+url).setNegativeButton("إلغاء",null).setPositiveButton("ربط",(d,w)->PairingWorker.enqueue(this,raw)).show();}catch(Exception e){StatusStore.error(this,"invalid_pairing_qr");refresh();}});}
    private void retryConnection(){if(!SecureSettings.isPaired(this)){StatusStore.error(this,"pairing_required");refresh();return;}new SmsOutbox(this).recoverTemporaryState();StatusStore.error(this,"manual_retry_started");SyncWorker.retryNow(this);refresh();}
    private void chooseImport(){if(!SecureSettings.isPaired(this)){StatusStore.error(this,"pairing_required");return;}if(checkSelfPermission(Manifest.permission.READ_SMS)!=PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{Manifest.permission.READ_SMS},12);return;}new AlertDialog.Builder(this).setTitle("استيراد رسائل سابقة").setItems(new String[]{"آخر 30 يومًا","آخر 60 يومًا","تاريخ بداية مخصص"},(d,w)->{long end=System.currentTimeMillis();if(w<2)HistoricalImportWorker.enqueue(this,end-(w==0?30L:60L)*86400000L,end);else pickStart(end);}).setNegativeButton("إلغاء",null).show();}
    private void pickStart(long end){Calendar c=Calendar.getInstance();new DatePickerDialog(this,(v,y,m,d)->{Calendar s=Calendar.getInstance();s.clear();s.set(y,m,d,0,0,0);HistoricalImportWorker.enqueue(this,s.getTimeInMillis(),end);},c.get(Calendar.YEAR),c.get(Calendar.MONTH),c.get(Calendar.DAY_OF_MONTH)).show();}
}
