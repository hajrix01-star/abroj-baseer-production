package com.baseer.freshchat;

import android.os.Handler;
import android.os.HandlerThread;
import android.view.FrameMetrics;
import android.view.Window;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

/** Bounded primitive copy on the metrics thread; no callback JSON, disk, or scenario lookup. */
final class FrameSamples implements Window.OnFrameMetricsAvailableListener {
    private static final int CAPACITY=8192;
    private static final int[] METRICS={FrameMetrics.INTENDED_VSYNC_TIMESTAMP,FrameMetrics.VSYNC_TIMESTAMP,
        FrameMetrics.TOTAL_DURATION,FrameMetrics.LAYOUT_MEASURE_DURATION,FrameMetrics.DRAW_DURATION,
        FrameMetrics.INPUT_HANDLING_DURATION,FrameMetrics.UNKNOWN_DELAY_DURATION,FrameMetrics.DEADLINE,
        FrameMetrics.FIRST_DRAW_FRAME};
    private final long[][] samples=new long[METRICS.length][CAPACITY];
    private final int[] dropped=new int[CAPACITY];
    private final HandlerThread thread=new HandlerThread("c26-frame-metrics");
    private Handler handler;
    private int size,overflow;
    private long lostReports;
    private final List<Stage> stages=new ArrayList<>();
    static final class Stage {
        final String name;final long start;long end;
        Stage(String name){this.name=name;start=System.nanoTime();}
    }
    void attach(Window window){thread.start();handler=new Handler(thread.getLooper());window.addOnFrameMetricsAvailableListener(this,handler);}
    Stage begin(String name){Stage stage=new Stage(name);stages.add(stage);return stage;}
    void end(Stage stage){stage.end=System.nanoTime();}
    @Override public void onFrameMetricsAvailable(Window window,FrameMetrics frame,int dropCountSinceLastInvocation){
        lostReports+=dropCountSinceLastInvocation;
        if(size==CAPACITY){++overflow;return;}
        for(int metric=0;metric<METRICS.length;++metric)samples[metric][size]=frame.getMetric(METRICS[metric]);
        dropped[size]=dropCountSinceLastInvocation;++size;
    }
    void finish()throws Exception{
        CountDownLatch drained=new CountDownLatch(1);handler.post(drained::countDown);
        if(!drained.await(5,TimeUnit.SECONDS))throw new IllegalStateException("Metrics drain timeout");
        thread.quitSafely();thread.join(5000);
        if(thread.isAlive())throw new IllegalStateException("Metrics thread did not finish");
    }
    JSONObject export()throws Exception{
        JSONArray raw=new JSONArray(),windows=new JSONArray(),summary=new JSONArray();
        for(Stage stage:stages)windows.put(new JSONObject().put("name",stage.name).put("start_ns",stage.start).put("end_ns",stage.end));
        for(int row=0;row<size;++row){
            String name="outside";
            for(Stage stage:stages)if(samples[0][row]>=stage.start&&samples[0][row]<stage.end){name=stage.name;break;}
            JSONArray values=new JSONArray();for(long[] metric:samples)values.put(metric[row]);
            raw.put(new JSONObject().put("scenario",name).put("values_ns_or_flag",values).put("lost_metric_reports",dropped[row]));
        }
        for(Stage stage:stages){
            JSONArray metrics=new JSONArray();int count=0,firstDraw=0,overDeadline=0,deadlineNA=0;
            for(int row=0;row<size;++row)if(samples[0][row]>=stage.start&&samples[0][row]<stage.end){
                if(samples[8][row]==1){++firstDraw;continue;}++count;
                if(samples[7][row]<0)++deadlineNA;else if(samples[2][row]>samples[7][row])++overDeadline;
            }
            for(int metric=2;metric<=7;++metric){
                List<Long> values=new ArrayList<>();int unavailable=0;
                for(int row=0;row<size;++row)if(samples[0][row]>=stage.start&&samples[0][row]<stage.end&&samples[8][row]!=1){
                    if(samples[metric][row]<0)++unavailable;else values.add(samples[metric][row]);
                }
                metrics.put(stats(values).put("metric_index",metric).put("unavailable",unavailable));
            }
            summary.put(new JSONObject().put("scenario",stage.name).put("samples",count).put("first_draw_samples",firstDraw)
                .put("over_actual_deadline_samples",overDeadline).put("deadline_unavailable",deadlineNA).put("metrics",metrics));
        }
        return new JSONObject().put("capacity",CAPACITY).put("sample_count",size).put("overflow",overflow)
            .put("lost_metric_reports",lostReports).put("comparison_valid",overflow==0&&lostReports==0)
            .put("columns",new JSONArray(java.util.Arrays.asList("intended_vsync","actual_vsync","total","layout_measure","draw","input_handling","unknown_delay","actual_deadline","first_draw_flag")))
            .put("raw",raw).put("windows",windows).put("summaries",summary)
            .put("note","Scenario attribution uses frame intended-vsync time, never callback-arrival time. Missing -1 is unavailable. Lost reports are NOT displayed dropped frames. First-draw separate. No fixed16ms assumption.");
    }
    static JSONObject stats(List<Long> values)throws Exception{
        java.util.Collections.sort(values);int count=values.size();
        return new JSONObject().put("count",count).put("p50",count==0?JSONObject.NULL:values.get((int)Math.ceil(.50*count)-1))
            .put("p95",count==0?JSONObject.NULL:values.get((int)Math.ceil(.95*count)-1))
            .put("max",count==0?JSONObject.NULL:values.get(count-1));
    }
}
