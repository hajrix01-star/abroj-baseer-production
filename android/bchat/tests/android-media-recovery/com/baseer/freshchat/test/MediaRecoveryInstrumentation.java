package com.baseer.freshchat.test;

import android.app.*;
import android.content.*;
import android.graphics.*;
import android.graphics.pdf.PdfDocument;
import android.media.AudioManager;
import android.media.ExifInterface;
import android.os.*;
import android.view.*;
import android.widget.*;
import com.baseer.freshchat.ChatStore;
import java.io.*;
import java.lang.reflect.*;
import java.nio.*;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;

/** Reconstructed after executor loss. Valid synthetic media only; no malformed or security probes. */
public final class MediaRecoveryInstrumentation extends Instrumentation {
    private boolean disposable;
    private volatile boolean uiAborted;
    private Activity activity;
    private LinearLayout host;
    private Object previews, player;
    private Class<?> loaderClass, viewClass, readyClass, pdfClass;
    private View inspector;
    private ImageView detail;
    private ThreadPoolExecutor worker;
    private CountDownLatch release;
    private Future<?> barrier;
    private final AtomicInteger validJobs = new AtomicInteger(), failedJobs = new AtomicInteger();
    private int jobsBefore;
    private final List<File> created = new ArrayList<>();
    private final List<String> results = new ArrayList<>();
    private ChatStore.Attachment image;
    private static final int[] COLORS={Color.RED,Color.GREEN,Color.BLUE,Color.YELLOW};

    @Override public void onCreate(Bundle args) {
        super.onCreate(args); disposable=args!=null&&"true".equals(args.getString("disposable"));start();
    }
    @Override public void onStart() {
        Bundle output=new Bundle();boolean passed=false;
        try { if(!disposable)throw new IllegalStateException("Requires -e disposable true on an authorized disposable install"); runChecks();passed=true; }
        catch(Throwable failure){output.putString("failure",summary(failure));}
        finally {
            if(release!=null)release.countDown();
            boolean safe=false;
            if(activity!=null&&!uiAborted)try{
                ui(()->{if(player!=null)call(player,"stop",new Class<?>[0]);if(host!=null)host.removeAllViews();if(previews!=null)call(previews,"close",new Class<?>[0]);activity.finish();});
                safe=worker==null||worker.awaitTermination(15,TimeUnit.SECONDS);
            }catch(Throwable ignored){}
            if(safe)for(File file:created)file.delete();
        }
        output.putString("stream","\n"+(passed?"PASS ":"FAILED after ")+results.size()+" recovered media checks\n"+String.join("\n",results)+"\n"+output.getString("failure","")+"\n");
        finish(passed?Activity.RESULT_OK:Activity.RESULT_CANCELED,output);
    }
    private void runChecks()throws Exception {
        ActivityMonitor monitor=addMonitor("com.baseer.freshchat.MainActivity",null,false);
        try{ui(()->getTargetContext().startActivity(new Intent(Intent.ACTION_MAIN).setComponent(new ComponentName("com.baseer.bchat.preview","com.baseer.freshchat.MainActivity")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)));activity=monitor.waitForActivityWithTimeout(45000);if(activity==null)throw new AssertionError("Launch timeout");}finally{removeMonitor(monitor);}
        await(()->!(boolean)field(activity,"initializing")&&field(activity,"store")!=null,15000,"Activity finishes asynchronous store initialization");
        loaderClass=type("ImagePreviews");viewClass=type("ImagePreviewView");readyClass=type("ImagePreviews$DetailReady");pdfClass=type("PdfPreviewView");
        ui(()->{previews=make(loaderClass,new Class<?>[]{Context.class},activity);worker=(ThreadPoolExecutor)field(previews,"worker");host=new LinearLayout(activity);host.setOrientation(LinearLayout.VERTICAL);activity.setContentView(host);});
        image=makeImage(1200,20000,true,1);byte[] before=digest(new File(image.path));
        Object result=decode(image,new Rect(100,7000,1100,7700));Bitmap tile=(Bitmap)field(result,"bitmap");
        check(tile.getWidth()==1000&&tile.getHeight()==700&&tile.getAllocationByteCount()<=8*1024*1024,"Tall image decodes original-resolution bounded viewport");check(tile.getPixel(100,100)==Color.RED,"Original viewport contains exact synthetic source pixels");tile.recycle();
        orientations();pdfPreview();openInspector();gestures();deadline();cancelAndRecover(false);cancelAndRecover(true);audioRoute();
        check(Arrays.equals(before,digest(new File(image.path))),"All viewing and queue exercises preserve original image bytes");
        results.add("INFO Valid synthetic PNG/JPEG/PDF/WAV only. Physical device, provider and route behavior remain separate acceptance.");
    }
    private ChatStore.Attachment makeImage(int width,int height,boolean png,int orientation)throws Exception {
        File file=fresh(png?".png":".jpg");
        // Tall valid PNG encoded row-by-row: avoids allocating a full 96 MiB source bitmap.
        if(png&&height>5000){
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            try(java.util.zip.DeflaterOutputStream encoded=new java.util.zip.DeflaterOutputStream(bytes)){
                byte[] row=new byte[width*3+1];
                for(int y=0;y<height;y++){for(int x=0;x<width;x++){int c=((x/3+y/5)&1)==0?COLORS[0]:COLORS[1];row[x*3+1]=(byte)Color.red(c);row[x*3+2]=(byte)Color.green(c);row[x*3+3]=(byte)Color.blue(c);}encoded.write(row);}
            }
            try(DataOutputStream output=new DataOutputStream(new FileOutputStream(file))){
                output.write(new byte[]{(byte)137,80,78,71,13,10,26,10});ByteArrayOutputStream header=new ByteArrayOutputStream();DataOutputStream h=new DataOutputStream(header);h.writeInt(width);h.writeInt(height);h.write(new byte[]{8,2,0,0,0});chunk(output,"IHDR",header.toByteArray());chunk(output,"IDAT",bytes.toByteArray());chunk(output,"IEND",new byte[0]);
            }
        }else{
            Bitmap bitmap=Bitmap.createBitmap(width,height,Bitmap.Config.ARGB_8888);Canvas canvas=new Canvas(bitmap);Paint paint=new Paint();
            for(int n=0;n<4;n++){paint.setColor(COLORS[n]);canvas.drawRect(n%2*width/2f,n/2*height/2f,(n%2+1)*width/2f,(n/2+1)*height/2f,paint);}
            try(FileOutputStream out=new FileOutputStream(file)){bitmap.compress(png?Bitmap.CompressFormat.PNG:Bitmap.CompressFormat.JPEG,100,out);}finally{bitmap.recycle();}
            if(!png){ExifInterface exif=new ExifInterface(file.getPath());exif.setAttribute(ExifInterface.TAG_ORIENTATION,""+orientation);exif.saveAttributes();}
        }
        return attachment(file,png?"image/png":"image/jpeg");
    }
    private static void chunk(DataOutputStream out,String type,byte[] bytes)throws Exception {
        byte[] name=type.getBytes("US-ASCII");out.writeInt(bytes.length);out.write(name);out.write(bytes);java.util.zip.CRC32 crc=new java.util.zip.CRC32();crc.update(name);crc.update(bytes);out.writeInt((int)crc.getValue());
    }
    private Object decode(ChatStore.Attachment file,Rect region)throws Exception {
        Method method=loaderClass.getDeclaredMethod("decodeDetail",Context.class,ChatStore.Attachment.class,Rect.class,int.class);method.setAccessible(true);return method.invoke(null,activity,file,region,1);
    }
    private void orientations()throws Exception {
        int[][] expected={{0,1,2,3},{1,0,3,2},{3,2,1,0},{2,3,0,1},{0,2,1,3},{2,0,3,1},{3,1,2,0},{1,3,0,2}};
        for(int n=1;n<=8;n++){
            ChatStore.Attachment file=makeImage(320,180,false,n);byte[] before=digest(new File(file.path));Object result=decode(file,new Rect(0,0,320,180));Object info=field(result,"info");Bitmap bitmap=(Bitmap)field(result,"bitmap");
            int w=(int)field(info,"displayWidth"),h=(int)field(info,"displayHeight");Bitmap upright=Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888);Canvas canvas=new Canvas(upright);canvas.concat((Matrix)call(info,"orientationMatrix",new Class<?>[0]));canvas.drawBitmap(bitmap,0,0,null);
            for(int corner=0;corner<4;corner++){int actual=upright.getPixel(corner%2==0?w/4:w*3/4,corner/2==0?h/4:h*3/4),wanted=COLORS[expected[n-1][corner]];check(Math.abs(Color.red(actual)-Color.red(wanted))<20&&Math.abs(Color.green(actual)-Color.green(wanted))<20&&Math.abs(Color.blue(actual)-Color.blue(wanted))<20,"EXIF "+n+" detail corner "+corner);}
            check(Arrays.equals(before,digest(new File(file.path))),"EXIF "+n+" leaves original unchanged");upright.recycle();bitmap.recycle();
        }
    }
    private void pdfPreview()throws Exception {
        File file=fresh(".pdf");PdfDocument document=new PdfDocument();
        try{for(int n=1;n<=2;n++){PdfDocument.Page page=document.startPage(new PdfDocument.PageInfo.Builder(600,800,n).create());Paint paint=new Paint();paint.setColor(Color.BLACK);paint.setTextSize(24);page.getCanvas().drawText("Ordinary synthetic page "+n,30,70,paint);document.finishPage(page);}try(FileOutputStream out=new FileOutputStream(file)){document.writeTo(out);}}finally{document.close();}
        ChatStore.Attachment attachment=attachment(file,"application/pdf");byte[] before=digest(file);View[] view={null};
        ui(()->{view[0]=(View)make(pdfClass,new Class<?>[]{Context.class,ChatStore.Attachment.class},activity,attachment);host.addView(view[0],new LinearLayout.LayoutParams(500,650));});
        await(()->field(view[0],"displayed")!=null,15000,"Valid two-page PDF previews asynchronously");
        ui(()->view[0].setVisibility(View.INVISIBLE));check(onUi(()->field(view[0],"displayed")==null&&field(view[0],"request")==null),"Hidden PDF releases bitmap and request");
        ui(()->view[0].setVisibility(View.VISIBLE));await(()->field(view[0],"displayed")!=null,15000,"PDF reloads when shown");
        ui(()->host.removeView(view[0]));check(onUi(()->field(view[0],"displayed")==null&&field(view[0],"request")==null),"PDF dismissal clears ownership");check(Arrays.equals(before,digest(file)),"PDF bytes unchanged");
    }
    private void openInspector(){
        ui(()->{inspector=(View)make(viewClass,new Class<?>[]{Context.class,ChatStore.Attachment.class,loaderClass,int.class,boolean.class},activity,image,previews,1400,false);host.addView(inspector,new LinearLayout.LayoutParams(Math.min(600,activity.getResources().getDisplayMetrics().widthPixels),700));detail=(ImageView)field(inspector,"image");});
        await(()->field(detail,"info")!=null,15000,"Inspector metadata and overview available");
    }
    private void zoomTo(float scale){ui(()->call(detail,"zoom",new Class<?>[]{float.class,float.class,float.class},scale/(float)field(detail,"scale"),detail.getWidth()/2f,detail.getHeight()/2f));}
    private void gestures(){
        float[] before={0};ui(()->{before[0]=(float)field(detail,"scale");pinch(detail);});check(onUi(()->(float)field(detail,"scale")>before[0]*1.4f),"Two-pointer view events change zoom");
        zoomTo(1f);await(()->field(detail,"tile")!=null&&(int)field(detail,"tileSample")==1,15000,"Pixel zoom decodes original-resolution tile");
        Rect[] previous={null};ui(()->{previous[0]=new Rect((Rect)field(detail,"tileRegion"));drag(detail);});await(()->!previous[0].equals(field(detail,"tileRegion")),15000,"Drag changes decoded source region");
        ui(()->call(detail,"fit",new Class<?>[0]));await(()->field(detail,"requestedRegion")==null,3000,"Fit cancels unnecessary detail ownership");
    }
    private void saturate()throws Exception {
        jobsBefore=validJobs.get();CountDownLatch started=new CountDownLatch(1);release=new CountDownLatch(1);CountDownLatch latch=release;
        barrier=worker.submit(()->{started.countDown();try{latch.await();}catch(InterruptedException stop){Thread.currentThread().interrupt();}});
        check(started.await(15,TimeUnit.SECONDS),"Controlled normal worker barrier acquired");
        ui(()->{
            Object callback=Proxy.newProxyInstance(readyClass.getClassLoader(),new Class<?>[]{readyClass},(proxy,method,args)->{if("show".equals(method.getName())){Bitmap bitmap=(Bitmap)field(args[0],"bitmap");if(bitmap!=null){validJobs.incrementAndGet();bitmap.recycle();}else failedJobs.incrementAndGet();}return null;});
            for(int n=0;n<32;n++)call(previews,"loadDetail",new Class<?>[]{ChatStore.Attachment.class,Rect.class,int.class,readyClass},image,new Rect(0,0,256,256),1,callback);
            check(pending()==32&&worker.getQueue().size()==32,"32 normal valid PNG jobs fill bounded decode slots");
        });
    }
    private int pending(){return ((Map<?,?>)field(previews,"pending")).size()+((Set<?>)field(previews,"detailPending")).size();}
    private void releaseResources()throws Exception {
        release.countDown();barrier.get(15,TimeUnit.SECONDS);barrier=null;
        await(()->pending()==0&&worker.getQueue().isEmpty(),15000,"Queue drains after releasing resources");
        check(validJobs.get()==jobsBefore+32&&failedJobs.get()==0,"All queued valid regions decode successfully");release=null;
    }
    private void deadline()throws Exception {
        saturate();zoomTo(1.1f);await(()->field(detail,"deadline")!=null&&field(detail,"requestedRegion")!=null,3000,"Saturated viewport begins one deadline");
        Object[] saved=new Object[2];ui(()->{saved[0]=field(detail,"deadline");saved[1]=field(detail,"detailGeneration");});int generation=(int)saved[1];long began=SystemClock.elapsedRealtime();Set<Object> retries=Collections.newSetFromMap(new IdentityHashMap<>());
        while(SystemClock.elapsedRealtime()-began<20000){
            if(onUi(()->field(detail,"deadline")==null))break;
            ui(()->{if(field(detail,"deadline")==null)return;ensure(field(detail,"deadline")==saved[0]&&(int)field(detail,"detailGeneration")==generation,"Busy/same-viewport update renewed deadline");Object retry=field(detail,"tileRetry");if(retry!=null)retries.add(retry);call(detail,"changed",new Class<?>[0]);});SystemClock.sleep(200);
        }
        long elapsed=SystemClock.elapsedRealtime()-began;
        check(onUi(()->field(detail,"deadline")==null&&field(detail,"tileRetry")==null&&(int)field(detail,"detailGeneration")==generation+1),"Overall timeout clears retry and fences its generation");
        check(elapsed>=13500&&elapsed<=20000&&retries.size()>=5,"Repeated busy retries expire once near 15s; observed "+elapsed+"ms, "+retries.size()+" retries");
        for(int n=0;n<4;n++){ui(()->call(detail,"changed",new Class<?>[0]));SystemClock.sleep(220);}
        check(onUi(()->field(detail,"deadline")==null&&field(detail,"tileRetry")==null&&(int)field(detail,"detailGeneration")==generation+1),"Same viewport cannot silently restart after timeout");
        releaseResources();Object[] previous={null};ui(()->previous[0]=field(detail,"tile"));zoomTo(1.25f);await(()->field(detail,"tile")!=null&&field(detail,"tile")!=previous[0]&&field(detail,"deadline")==null,15000,"New viewport recovers with a freshly decoded tile");
    }
    private void cancelAndRecover(boolean dismiss)throws Exception {
        ui(()->call(detail,"fit",new Class<?>[0]));await(()->field(detail,"requestedRegion")==null,3000,"Fit completes before next queue test");saturate();zoomTo(dismiss?1.75f:1.5f);
        await(()->field(detail,"deadline")!=null&&field(detail,"tileRetry")!=null,3000,"Saturated viewport retries before cancellation");Object[] stale=new Object[4];
        ui(()->{stale[0]=field(detail,"deadline");stale[1]=field(detail,"tileRetry");stale[2]=detail.getHandler();stale[3]=field(detail,"detailGeneration");if(dismiss)host.removeView(inspector);else call(detail,"fit",new Class<?>[0]);});
        await(()->field(detail,"deadline")==null&&field(detail,"tileRetry")==null&&field(detail,"requestedRegion")==null,3000,(dismiss?"Dismiss":"Fit")+" cancels deadline and retry");
        ui(()->{if(Build.VERSION.SDK_INT>=29)check(!((Handler)stale[2]).hasCallbacks((Runnable)stale[0])&&!((Handler)stale[2]).hasCallbacks((Runnable)stale[1]),"Actual queued callbacks were removed");int current=(int)field(detail,"detailGeneration");((Runnable)stale[0]).run();((Runnable)stale[1]).run();check(current>(int)stale[3]&&current==(int)field(detail,"detailGeneration")&&pending()==32,"Late canceled callbacks cannot queue or renew work");});
        releaseResources();if(dismiss)openInspector();Object[] old={null};ui(()->old[0]=field(detail,"tile"));zoomTo(dismiss?1f:1.6f);await(()->field(detail,"tile")!=null&&field(detail,"tile")!=old[0]&&field(detail,"deadline")==null,15000,"Detail decodes again after cancellation and resource release");
    }
    private void audioRoute()throws Exception {
        File wav=fresh(".wav");int rate=16000,samples=rate*4;ByteBuffer header=ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN);
        header.put(new byte[]{'R','I','F','F'}).putInt(samples*2+36).put(new byte[]{'W','A','V','E','f','m','t',' '}).putInt(16).putShort((short)1).putShort((short)1).putInt(rate).putInt(rate*2).putShort((short)2).putShort((short)16).put(new byte[]{'d','a','t','a'}).putInt(samples*2);
        try(OutputStream output=new BufferedOutputStream(new FileOutputStream(wav))){output.write(header.array());for(int n=0;n<samples;n++){short value=(short)(Math.sin(2*Math.PI*440*n/rate)*1000);output.write(value&255);output.write((value>>>8)&255);}}
        Class<?> audioClass=type("AudioPlayback"),errorClass=type("AudioPlayback$Error"),targetClass=type("AudioPlayback$Target");ChatStore.Attachment clip=attachment(wav,"audio/wav");List<String> failures=new ArrayList<>();Object target=Proxy.newProxyInstance(targetClass.getClassLoader(),new Class<?>[]{targetClass},(proxy,method,args)->null);
        ui(()->{Object error=Proxy.newProxyInstance(errorClass.getClassLoader(),new Class<?>[]{errorClass},(proxy,method,args)->{if("show".equals(method.getName()))failures.add(String.valueOf(args[0]));return null;});player=make(audioClass,new Class<?>[]{Context.class,errorClass},activity,error);call(player,"toggle",new Class<?>[]{ChatStore.Attachment.class,targetClass},clip,target);});
        await(()->"PLAYING".equals(String.valueOf(call(field(player,"state"),"phase",new Class<?>[0]))),15000,"Valid synthetic WAV starts normal native playback");
        ui(()->{check((boolean)field(player,"noisyRegistered"),"Playing registers route receiver");((BroadcastReceiver)field(player,"noisyReceiver")).onReceive(activity,new Intent(AudioManager.ACTION_AUDIO_BECOMING_NOISY));});
        check(onUi(()->"PAUSED".equals(String.valueOf(call(field(player,"state"),"phase",new Class<?>[0])))&&!(boolean)field(player,"noisyRegistered")),"Injected ordinary route loss pauses and unregisters");SystemClock.sleep(300);
        check(onUi(()->"PAUSED".equals(String.valueOf(call(field(player,"state"),"phase",new Class<?>[0])))&&failures.isEmpty()),"Route reconnection cannot automatically resume");ui(()->call(player,"stop",new Class<?>[0]));
    }
    private void pinch(View view){long t=SystemClock.uptimeMillis();float x=view.getWidth()/2f,y=view.getHeight()/2f;event(view,t,t,MotionEvent.ACTION_DOWN,new float[]{x-40},new float[]{y});event(view,t,t+20,MotionEvent.ACTION_POINTER_DOWN|(1<<8),new float[]{x-40,x+40},new float[]{y,y});for(int n=1;n<=12;n++)event(view,t,t+20+n*20,MotionEvent.ACTION_MOVE,new float[]{x-40-n*8,x+40+n*8},new float[]{y,y});event(view,t,t+280,MotionEvent.ACTION_POINTER_UP|(1<<8),new float[]{x-136,x+136},new float[]{y,y});event(view,t,t+300,MotionEvent.ACTION_UP,new float[]{x-136},new float[]{y});}
    private void drag(View view){long t=SystemClock.uptimeMillis();float x=view.getWidth()/2f,y=view.getHeight()/2f;event(view,t,t,MotionEvent.ACTION_DOWN,new float[]{x},new float[]{y});for(int n=1;n<=6;n++)event(view,t,t+n*25,MotionEvent.ACTION_MOVE,new float[]{x},new float[]{y-n*20});event(view,t,t+175,MotionEvent.ACTION_UP,new float[]{x},new float[]{y-120});}
    private void event(View view,long down,long time,int action,float[] x,float[] y){MotionEvent.PointerProperties[] properties=new MotionEvent.PointerProperties[x.length];MotionEvent.PointerCoords[] coords=new MotionEvent.PointerCoords[x.length];for(int n=0;n<x.length;n++){properties[n]=new MotionEvent.PointerProperties();properties[n].id=n;properties[n].toolType=MotionEvent.TOOL_TYPE_FINGER;coords[n]=new MotionEvent.PointerCoords();coords[n].x=x[n];coords[n].y=y[n];coords[n].pressure=1;coords[n].size=1;}MotionEvent event=MotionEvent.obtain(down,time,action,x.length,properties,coords,0,0,1,1,0,0,InputDevice.SOURCE_TOUCHSCREEN,0);try{view.dispatchTouchEvent(event);}finally{event.recycle();}}
    private Class<?> type(String name)throws Exception{return Class.forName("com.baseer.freshchat."+name,true,activity.getClassLoader());}
    private File fresh(String extension)throws Exception{File directory=new File(getTargetContext().getFilesDir(),"attachments");if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("Fixture directory unavailable");File file=new File(directory,UUID.randomUUID()+extension);created.add(file);return file;}
    private ChatStore.Attachment attachment(File file,String mime)throws Exception{return new ChatStore.Attachment(UUID.randomUUID().toString(),file.getCanonicalPath(),"ordinary-synthetic",mime,file.length());}
    private static byte[] digest(File file)throws Exception{return MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file.toPath()));}
    private void ui(Runnable action){if(uiAborted)throw new AssertionError("UI previously timed out");CountDownLatch done=new CountDownLatch(1);AtomicReference<Throwable> failure=new AtomicReference<>();Handler main=new Handler(Looper.getMainLooper());Runnable run=()->{if(uiAborted){done.countDown();return;}try{action.run();}catch(Throwable error){failure.set(error);}finally{done.countDown();}};main.post(run);try{if(!done.await(15,TimeUnit.SECONDS)){uiAborted=true;main.removeCallbacks(run);throw new AssertionError("UI timeout; no further mutation");}}catch(InterruptedException interrupted){Thread.currentThread().interrupt();uiAborted=true;throw new AssertionError(interrupted);}if(failure.get()!=null)throw new AssertionError("UI operation",failure.get());}
    private boolean onUi(BooleanSupplier test){boolean[] result={false};ui(()->result[0]=test.getAsBoolean());return result[0];}
    private void await(BooleanSupplier test,long timeout,String label){long end=SystemClock.elapsedRealtime()+timeout;while(SystemClock.elapsedRealtime()<end){if(onUi(test)){check(true,label);return;}SystemClock.sleep(40);}throw new AssertionError("Timeout: "+label);}
    private void check(boolean value,String label){ensure(value,label);results.add("PASS "+label);}
    private static void ensure(boolean value,String label){if(!value)throw new AssertionError(label);}
    private static Object field(Object owner,String name){try{Field field=owner.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(owner);}catch(Exception e){throw new AssertionError(name,e);}}
    private static Object call(Object owner,String name,Class<?>[] types,Object...args){try{Method method=owner.getClass().getDeclaredMethod(name,types);method.setAccessible(true);return method.invoke(owner,args);}catch(Exception e){throw new AssertionError(name,e);}}
    private static Object make(Class<?> type,Class<?>[] types,Object...args){try{Constructor<?> constructor=type.getDeclaredConstructor(types);constructor.setAccessible(true);return constructor.newInstance(args);}catch(Exception e){throw new AssertionError(type.getName(),e);}}
    private static String summary(Throwable failure){StringBuilder text=new StringBuilder();for(int n=0;failure!=null&&n<6;n++,failure=failure.getCause()){if(text.length()>0)text.append(" <- ");text.append(failure.getClass().getSimpleName()).append(": ").append(failure.getMessage());}return text.toString();}
}
