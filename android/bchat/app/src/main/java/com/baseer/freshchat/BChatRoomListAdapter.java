package com.baseer.freshchat;

import android.content.Context;
import android.graphics.Color;
import android.os.Looper;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import androidx.annotation.NonNull;
import androidx.recyclerview.widget.AsyncDifferConfig;
import androidx.recyclerview.widget.AsyncListDiffer;
import androidx.recyclerview.widget.DiffUtil;
import androidx.recyclerview.widget.ListUpdateCallback;
import androidx.recyclerview.widget.RecyclerView;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Executor;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** One owner per adapter. Deactivated instances may finish a diff, but can never publish it. */
final class BChatRoomListAdapter extends RecyclerView.Adapter<BChatRoomListAdapter.Holder> {
    interface Host {
        boolean current();
        boolean current(BChatRoomRow row);
        void open(BChatRoomRow.Key key);
        Runnable avatar(BChatRoomRow row, FrameLayout slot);
        void committed(int count);
    }
    /** One bounded lane per Activity, shared by its successive owners, never between Activities. */
    static final class Lane implements Executor, AutoCloseable {
        private final ThreadPoolExecutor worker=new ThreadPoolExecutor(1,1,10,TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(1), runnable -> {
                Thread thread=new Thread(runnable,"bchat-room-diff"); thread.setDaemon(true); return thread;
            },new ThreadPoolExecutor.DiscardOldestPolicy());
        Lane() { worker.allowCoreThreadTimeOut(true); }
        @Override public void execute(Runnable work) { worker.execute(work); }
        @Override public void close() { worker.shutdownNow(); }
    }
    private final Host host;
    private final AsyncListDiffer<BChatRoomRow> differ;
    private final java.util.Set<Holder> holders=java.util.Collections.newSetFromMap(new java.util.WeakHashMap<>());
    private boolean active=true;
    BChatRoomListAdapter(Host host, Executor worker) {
        this.host=host;
        // Compound identity is compared exactly. No collision-prone long hash as a stable ID.
        setHasStableIds(false);
        differ=new AsyncListDiffer<>(new ListUpdateCallback() {
            public void onInserted(int start,int count) { if(usable())notifyItemRangeInserted(start,count); }
            public void onRemoved(int start,int count) { if(usable())notifyItemRangeRemoved(start,count); }
            public void onMoved(int from,int to) { if(usable())notifyItemMoved(from,to); }
            public void onChanged(int start,int count,Object payload) { if(usable())notifyItemRangeChanged(start,count,payload); }
        },new AsyncDifferConfig.Builder<>(new DiffUtil.ItemCallback<BChatRoomRow>() {
            public boolean areItemsTheSame(@NonNull BChatRoomRow a,@NonNull BChatRoomRow b) { return a.key.equals(b.key); }
            public boolean areContentsTheSame(@NonNull BChatRoomRow a,@NonNull BChatRoomRow b) { return a.sameContent(b); }
        }).setBackgroundThreadExecutor(worker).build());
        differ.addListListener((previous,current) -> { if(usable())host.committed(current.size()); });
    }
    private static void main() { if(Looper.myLooper()!=Looper.getMainLooper())throw new IllegalStateException("Room UI requires MAIN"); }
    private boolean usable() { return active && host.current(); }
    void submit(List<BChatRoomRow> rows) {
        main(); if(!usable())return;
        if(rows==null || rows.size()>BChatRoomRow.MAX_ROOMS)throw new IllegalArgumentException("Room row capacity");
        differ.submitList(java.util.Collections.unmodifiableList(new ArrayList<>(rows)));
    }
    /** Caller detaches this adapter synchronously; neither a diff callback nor a disk callback clears rights. */
    void invalidateNow() {
        main(); active=false;
        for(Holder holder:new ArrayList<>(holders))holder.scrub();
        differ.submitList(null);
    }
    @Override public int getItemCount() { return usable()?differ.getCurrentList().size():0; }
    @NonNull @Override public Holder onCreateViewHolder(@NonNull ViewGroup parent,int type) {
        Holder holder=new Holder(parent.getContext()); holders.add(holder); return holder;
    }
    @Override public void onBindViewHolder(@NonNull Holder holder,int position) {
        holder.scrub(); if(!usable())return;
        BChatRoomRow row=differ.getCurrentList().get(position);if(!host.current(row))return;
        holder.bound=row; holder.entry.setEnabled(true);holder.entry.setVisibility(View.VISIBLE);
        holder.name.setText(row.name);holder.time.setText(row.time);holder.time.setVisibility(row.time.isEmpty()?View.GONE:View.VISIBLE);
        holder.preview.setText(row.preview);holder.company.setText(row.companyName);holder.company.setVisibility(row.companyName.isEmpty()?View.GONE:View.VISIBLE);
        holder.badge.setText(row.unread>99?"99+":String.valueOf(row.unread));holder.badge.setVisibility(row.unread>0?View.VISIBLE:View.GONE);
        holder.task.setText(row.taskLabel);holder.task.setVisibility(row.group&&row.task?View.VISIBLE:View.GONE);
        holder.entry.setContentDescription(row.companyName.isEmpty()?row.name:row.name+", "+row.companyName);
        holder.avatarCancel=host.avatar(row,holder.avatar);
    }
    @Override public void onViewAttachedToWindow(@NonNull Holder holder) {
        BChatRoomRow row=holder.bound;
        if(row!=null && usable() && host.current(row)) {
            if(holder.avatarCancel==null)holder.avatarCancel=host.avatar(row,holder.avatar);
        } else holder.scrub();
    }
    @Override public void onViewDetachedFromWindow(@NonNull Holder holder) { holder.releaseAvatar(); }
    @Override public void onViewRecycled(@NonNull Holder holder) { holder.scrub(); }
    final class Holder extends RecyclerView.ViewHolder {
        final LinearLayout entry;
        final FrameLayout avatar;
        final TextView name,time,preview,badge,task,company;
        BChatRoomRow bound; Runnable avatarCancel;
        Holder(Context context) {
            super(Ui.column(context)); LinearLayout outer=(LinearLayout)itemView;
            outer.setLayoutParams(new RecyclerView.LayoutParams(-1,-2));
            entry=Ui.row(context);Ui.pad(entry,14,8);
            entry.setMinimumHeight(Ui.dp(context,Ui.ROOM_ROW_MIN_DP*Math.max(1f,context.getResources().getConfiguration().fontScale)));
            avatar=new FrameLayout(context);entry.addView(avatar,new LinearLayout.LayoutParams(Ui.dp(context,Ui.ROOM_AVATAR_DP),Ui.dp(context,Ui.ROOM_AVATAR_DP)));
            LinearLayout labels=Ui.column(context),title=Ui.row(context),subtitle=Ui.row(context);
            name=Ui.text(context,"",Ui.ROOM_TITLE_SP,Ui.INK,true);name.setMaxLines(2);name.setEllipsize(TextUtils.TruncateAt.END);
            title.addView(name,new LinearLayout.LayoutParams(0,-2,1));
            time=Ui.text(context,"",Ui.CHAT_TIME_SP,Ui.MUTED,false);time.setSingleLine(true);time.setMaxWidth(Ui.dp(context,88));time.setEllipsize(TextUtils.TruncateAt.END);
            LinearLayout.LayoutParams timeSize=new LinearLayout.LayoutParams(-2,-2);timeSize.setMarginStart(Ui.dp(context,8));title.addView(time,timeSize);
            labels.addView(title,new LinearLayout.LayoutParams(-1,-2));
            preview=Ui.text(context,"",Ui.CHAT_PREVIEW_SP,Ui.MUTED,false);preview.setSingleLine(true);preview.setEllipsize(TextUtils.TruncateAt.END);
            subtitle.addView(preview,new LinearLayout.LayoutParams(0,-2,1));
            badge=Ui.text(context,"",Ui.CHAT_META_SP,Color.WHITE,true);badge.setGravity(Gravity.CENTER);badge.setBackground(Ui.bg(Ui.GREEN,20,context));
            badge.setMinWidth(Ui.dp(context,22));badge.setMinHeight(Ui.dp(context,22));badge.setPadding(Ui.dp(context,4),0,Ui.dp(context,4),0);
            LinearLayout.LayoutParams badgeSize=new LinearLayout.LayoutParams(-2,-2);badgeSize.setMarginStart(Ui.dp(context,8));subtitle.addView(badge,badgeSize);
            task=Ui.text(context,"",Ui.CHAT_META_SP,Ui.GREEN,true);task.setSingleLine(true);task.setMinHeight(Ui.dp(context,22));task.setGravity(Gravity.CENTER_VERTICAL);
            task.setBackground(Ui.bg(Ui.ACTION_TONAL,14,context));task.setPadding(Ui.dp(context,4),0,Ui.dp(context,4),0);
            LinearLayout.LayoutParams taskSize=new LinearLayout.LayoutParams(-2,-2);taskSize.setMarginStart(Ui.dp(context,8));subtitle.addView(task,taskSize);
            labels.addView(subtitle,new LinearLayout.LayoutParams(-1,-2));
            company=Ui.text(context,"",Ui.CHAT_META_SP,Ui.MUTED,false);company.setSingleLine(true);company.setEllipsize(TextUtils.TruncateAt.END);
            LinearLayout.LayoutParams companySize=new LinearLayout.LayoutParams(-1,-2);companySize.topMargin=Ui.dp(context,2);labels.addView(company,companySize);
            LinearLayout.LayoutParams labelSize=new LinearLayout.LayoutParams(0,-2,1);labelSize.setMarginStart(Ui.dp(context,10));entry.addView(labels,labelSize);
            Ui.clickable(entry);entry.setOnClickListener(view -> {
                int position=getBindingAdapterPosition();BChatRoomRow row=bound;
                if(position!=RecyclerView.NO_POSITION && row!=null && usable() && position<differ.getCurrentList().size()
                        && row.key.equals(differ.getCurrentList().get(position).key) && host.current(row))host.open(row.key);
            });
            outer.addView(entry,new LinearLayout.LayoutParams(-1,-2));
            LinearLayout.LayoutParams divider=new LinearLayout.LayoutParams(-1,Ui.dp(context,1));divider.setMarginStart(Ui.dp(context,72));outer.addView(Ui.line(context),divider);
        }
        void releaseAvatar() { if(avatarCancel!=null){avatarCancel.run();avatarCancel=null;}avatar.removeAllViews(); }
        void scrub() {
            releaseAvatar();bound=null;name.setText("");time.setText("");preview.setText("");company.setText("");badge.setText("");task.setText("");
            entry.setContentDescription(null);entry.setEnabled(false);entry.setVisibility(View.INVISIBLE);
        }
    }
}
