package com.baseer.freshchat;

import android.view.ViewGroup;
import androidx.recyclerview.widget.RecyclerView;
import java.util.List;
import org.json.JSONObject;

/** Test-only transparent proxy. Product owns holder creation/binding/IDs/lifecycle/payload semantics. */
final class CountingTimelineAdapter extends RecyclerView.Adapter<RecyclerView.ViewHolder> {
    final RecyclerView.Adapter<RecyclerView.ViewHolder> delegate;
    long creates,binds,payloadBinds,recycles,changed,rangeChanged,inserted,removed,moved,attached,detached;
    CountingTimelineAdapter(RecyclerView.Adapter<RecyclerView.ViewHolder> delegate){
        this.delegate=delegate;setHasStableIds(delegate.hasStableIds());setStateRestorationPolicy(delegate.getStateRestorationPolicy());
        delegate.registerAdapterDataObserver(new RecyclerView.AdapterDataObserver(){
            public void onChanged(){++changed;notifyDataSetChanged();}
            public void onItemRangeChanged(int start,int count){rangeChanged+=count;notifyItemRangeChanged(start,count);}
            public void onItemRangeChanged(int start,int count,Object payload){rangeChanged+=count;notifyItemRangeChanged(start,count,payload);}
            public void onItemRangeInserted(int start,int count){inserted+=count;notifyItemRangeInserted(start,count);}
            public void onItemRangeRemoved(int start,int count){removed+=count;notifyItemRangeRemoved(start,count);}
            public void onItemRangeMoved(int from,int to,int count){
                moved+=count;
                if(from<to)for(int i=count-1;i>=0;--i)notifyItemMoved(from+i,to+i);
                else for(int i=0;i<count;++i)notifyItemMoved(from+i,to+i);
            }
            public void onStateRestorationPolicyChanged(){setStateRestorationPolicy(delegate.getStateRestorationPolicy());}
        });
    }
    public int getItemCount(){return delegate.getItemCount();}
    public long getItemId(int position){return delegate.getItemId(position);}
    public int getItemViewType(int position){return delegate.getItemViewType(position);}
    public RecyclerView.ViewHolder onCreateViewHolder(ViewGroup parent,int type){++creates;return delegate.createViewHolder(parent,type);}
    public void onBindViewHolder(RecyclerView.ViewHolder holder,int position){++binds;delegate.bindViewHolder(holder,position);}
    public void onBindViewHolder(RecyclerView.ViewHolder holder,int position,List<Object> payloads){++binds;if(!payloads.isEmpty())++payloadBinds;delegate.bindViewHolder(holder,position);}
    public int findRelativeAdapterPositionIn(RecyclerView.Adapter<? extends RecyclerView.ViewHolder> adapter,RecyclerView.ViewHolder holder,int position){
        return adapter==this||adapter==delegate?position:delegate.findRelativeAdapterPositionIn(adapter,holder,position);
    }
    public void onViewRecycled(RecyclerView.ViewHolder holder){++recycles;delegate.onViewRecycled(holder);}
    public boolean onFailedToRecycleView(RecyclerView.ViewHolder holder){return delegate.onFailedToRecycleView(holder);}
    public void onViewAttachedToWindow(RecyclerView.ViewHolder holder){delegate.onViewAttachedToWindow(holder);}
    public void onViewDetachedFromWindow(RecyclerView.ViewHolder holder){delegate.onViewDetachedFromWindow(holder);}
    public void onAttachedToRecyclerView(RecyclerView view){++attached;delegate.onAttachedToRecyclerView(view);}
    public void onDetachedFromRecyclerView(RecyclerView view){++detached;delegate.onDetachedFromRecyclerView(view);}
    JSONObject counts()throws Exception{return new JSONObject().put("creates",creates).put("binds",binds).put("payload_binds",payloadBinds)
        .put("recycles",recycles).put("notify_all",changed).put("changed_rows",rangeChanged).put("inserted_rows",inserted)
        .put("removed_rows",removed).put("moved_rows",moved).put("attach_callbacks",attached).put("detach_callbacks",detached);}
}
