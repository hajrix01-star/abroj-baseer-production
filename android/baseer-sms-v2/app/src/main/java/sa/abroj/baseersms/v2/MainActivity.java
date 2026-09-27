package sa.abroj.baseersms.v2;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.widget.TextView;
import com.google.android.gms.tasks.Task;
import com.google.mlkit.vision.barcode.common.Barcode;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanner;
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning;
import java.text.DateFormat;
import java.util.Date;

public final class MainActivity extends Activity {
    private TextView connection, heartbeat, lastAck, queue, error; private final Handler handler=new Handler();
    private final Runnable refreshTask=new Runnable(){@Override public void run(){refresh();handler.postDelayed(this,2000);}};
    @Override public void onCreate(Bundle state){super.onCreate(state);setContentView(R.layout.activity_main);connection=findViewById(R.id.connection);heartbeat=findViewById(R.id.heartbeat);lastAck=findViewById(R.id.last_ack);queue=findViewById(R.id.queue);error=findViewById(R.id.error);
        findViewById(R.id.permission).setOnClickListener(v->requestPermissions(new String[]{Manifest.permission.RECEIVE_SMS},11));findViewById(R.id.pair).setOnClickListener(v->scan());findViewById(R.id.test_connection).setOnClickListener(v->{SyncWorker.enqueue(this);refresh();});refresh();}
    @Override protected void onResume(){super.onResume();handler.post(refreshTask);} @Override protected void onPause(){handler.removeCallbacks(refreshTask);super.onPause();}
    private void refresh(){boolean permission=checkSelfPermission(Manifest.permission.RECEIVE_SMS)==PackageManager.PERMISSION_GRANTED; long hb=StatusStore.heartbeatAt(this);long now=System.currentTimeMillis();boolean live=SecureSettings.isPaired(this)&&permission&&hb>0&&now-hb<=120000;
        if(!SecureSettings.isPaired(this)){connection.setText("غير مربوط");connection.setTextColor(Color.rgb(155,28,28));}
        else if(!permission){connection.setText("يلزم إذن استقبال الرسائل");connection.setTextColor(Color.rgb(180,83,9));}
        else if(live){connection.setText("متصل الآن");connection.setTextColor(Color.rgb(21,128,61));}
        else {connection.setText("لا يوجد اتصال حي مؤكد");connection.setTextColor(Color.rgb(180,83,9));}
        heartbeat.setText(hb==0?"لم يصل تأكيد من QA بعد":"آخر تأكيد من QA: "+format(hb));long ack=StatusStore.lastAckAt(this);lastAck.setText(ack==0?"لم تُؤكد أي رسالة بعد":"آخر رسالة تم تحويلها إلى QA: "+format(ack));SmsOutbox outbox=new SmsOutbox(this);queue.setText("رسائل بانتظار التسليم: "+outbox.countOpen());String issue=StatusStore.error(this);error.setText(issue.isEmpty()?"":("يحتاج انتباه: "+issue));}
    private String format(long time){return DateFormat.getDateTimeInstance(DateFormat.MEDIUM,DateFormat.SHORT).format(new Date(time));}
    private void scan(){GmsBarcodeScanner scanner=GmsBarcodeScanning.getClient(this,new GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build());Task<Barcode> task=scanner.startScan();task.addOnSuccessListener(code->{String raw=code.getRawValue();if(raw==null||raw.isEmpty())return;try{String url=new org.json.JSONObject(raw).getString("url");new AlertDialog.Builder(this).setTitle("تأكيد الربط").setMessage("سيُرسل التطبيق الرسائل المسموح بها إلى:\n"+url).setNegativeButton("إلغاء",null).setPositiveButton("ربط",(d,w)->PairingWorker.enqueue(this,raw)).show();}catch(Exception e){StatusStore.error(this,"invalid_pairing_qr");refresh();}});}
}
