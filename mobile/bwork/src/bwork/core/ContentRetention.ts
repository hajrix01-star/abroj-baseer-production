/** Server-owned retention state. No cutoff, path, clock or deletion inference. */
import type {Message,Room} from './ChatEngine.ts';
import type {HistoryScope} from './HistoryArchive.ts';
export const CONTENT_LIMITS=Object.freeze({ids:200,cacheIds:5000,bytes:128*1024,cursor:256});
export type ContentStateItem={media_id:number;state:'removed'}|{media_id:number;state:'live';message:Message};
export interface ContentStatePage {api_version:2;retention_version:1;room_id:number;company_id:number;membership_id:number;content_revision:number;items:ContentStateItem[];next_cursor:string|null}
export interface ContentCache {
 quarantine(scope:HistoryScope,room:Room,revision:number,guard:()=>void):Promise<number[]>;
 apply(scope:HistoryScope,room:Room,revision:number,items:ContentStateItem[],guard:()=>void):Promise<void>;
 complete(scope:HistoryScope,room:Room,revision:number,guard:()=>void):Promise<void>;
}
export const contentRevision=(value:unknown):value is number=>Number.isSafeInteger(value)&&Number(value)>=0;
const positive=(v:unknown):v is number=>Number.isSafeInteger(v)&&Number(v)>0;
const record=(v:unknown):v is Record<string,any>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const opaque=(v:unknown):v is string=>typeof v==='string'&&v.length>0&&v.length<=CONTENT_LIMITS.cursor&&/^[A-Za-z0-9_-]+$/.test(v);
export function contentIds(ids:unknown):number[]{
 if(!Array.isArray(ids)||ids.length>CONTENT_LIMITS.ids||ids.some((id,i)=>!positive(id)||i>0&&id<=ids[i-1]))throw Error('invalid_content_state');
 return [...ids];
}
export function decodeContentState(raw:unknown,room:Room,revision:number,requested:number[],previousCursor?:string):ContentStatePage{
 contentIds(requested);
 if(!contentRevision(revision)||!record(raw)||Object.keys(raw).some(key=>!['api_version','retention_version','room_id','company_id','membership_id','content_revision','items','next_cursor'].includes(key))||new TextEncoder().encode(JSON.stringify(raw)).length>CONTENT_LIMITS.bytes||raw.api_version!==2||raw.retention_version!==1
  ||raw.room_id!==room.id||raw.company_id!==room.company_id||raw.membership_id!==room.membership_id||raw.content_revision!==revision
  ||!Array.isArray(raw.items)||raw.items.length>requested.length||raw.next_cursor!==null&&(!opaque(raw.next_cursor)||raw.next_cursor===previousCursor)
  ||requested.length>0&&raw.items.length===0)throw Error('invalid_content_state');
 const seen=new Set<number>();
 for(const item of raw.items){
  if(!record(item)||!positive(item.media_id)||!requested.includes(item.media_id)||seen.has(item.media_id)||!['removed','live'].includes(item.state))throw Error('invalid_content_state');
  seen.add(item.media_id);
  if(item.state==='removed'){if(Object.keys(item).some(key=>!['media_id','state'].includes(key)))throw Error('invalid_content_state');continue;}
  if(Object.keys(item).some(key=>!['media_id','state','message'].includes(key)))throw Error('invalid_content_state');
  const m=item.message,media=m?.media;
  if(!record(m)||m.content_removed===true||m.media_removed===true||!positive(m.id)||!positive(m.author_user_id)||typeof m.author_name!=='string'||m.author_name.length>1024||typeof m.text!=='string'
   ||new TextEncoder().encode(m.text).length>16384||typeof m.created_at!=='string'||!Number.isFinite(Date.parse(m.created_at))||!record(media)||media.id!==item.media_id
   ||!['image','file','audio'].includes(media.kind)||!positive(media.size)||media.size>10*1024*1024||typeof media.name!=='string'||media.name.length>1024
   ||typeof media.mime!=='string'||media.mime.length>128||typeof media.sha256!=='string'||!/^[a-f0-9]{64}$/.test(media.sha256))throw Error('invalid_content_state');
 }
 return JSON.parse(JSON.stringify(raw));
}
