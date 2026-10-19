import type { Request } from '../core/ChatEngine.ts';
export type NotificationStatus = 'unconfigured' | 'disabled' | 'denied' | 'ready' | 'unavailable';
export interface NotificationAuthority { origin: string; db: string; uid: number; epoch: string | number; companyIds: number[]; revision: number; chat: boolean; task: boolean; csrf: string }
export interface NativePush {
  status(): Promise<{configured: boolean; enabled: boolean; granted: boolean; scope?: string; accountKey?: string; installationId?: string}>;
  enable(): Promise<boolean>; disable(): Promise<void>; clear(): Promise<void>;
  token(): Promise<{installationId: string; token: string; nativeEpoch?: number} | null>;
  bind(scope: string, installation: string, token: string, key: string, nativeEpoch?: number): Promise<boolean>;
}
export type NotificationDestination = {kind:'chat';companyId:number;roomId:number;messageId:number} | {kind:'task';companyId:number;taskId:number};
const uuid = (v: unknown): v is string => typeof v === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(v);
const id = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v > 0 && v <= 2147483647;
const object = (v: unknown): Record<string, any> => v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, any> : {};
export function notificationScope(a: NotificationAuthority): string { return JSON.stringify([a.origin,a.db,a.uid,[...a.companyIds].sort((x,y)=>x-y),a.revision,a.chat,a.task]); }
const stamp = (a: NotificationAuthority | null) => a ? JSON.stringify([notificationScope(a),a.epoch]) : '';
type Hint = {accountKey:string;kind:'chat'|'task';eventId:number};
export function parseIntent(value: unknown): Hint | null {
  if (typeof value !== 'string' || value.length > 256) return null;
  const match = /^bchat-trial:\/\/notification\/([^/]+)\/(chat|task)\/([1-9][0-9]{0,9})$/.exec(value);
  return match && uuid(match[1]) && id(Number(match[3])) ? {accountKey:match[1],kind:match[2] as Hint['kind'],eventId:Number(match[3])} : null;
}
/** No cookie access, background network, financial cache or legacy-registration fallback. */
export class NotificationsEngine {
  private readonly native: NativePush; private readonly current: () => NotificationAuthority | null; private readonly request: (r:Request)=>Promise<unknown>;
  private serial: Promise<unknown> = Promise.resolve(); private generation = 0; private hint: Hint | null = null; private abort: AbortController | null = null;
  constructor(ports:{native:NativePush;current:()=>NotificationAuthority|null;request:(r:Request)=>Promise<unknown>}) { this.native=ports.native;this.current=ports.current;this.request=ports.request; }
  intent(url: unknown): void { const value=parseIntent(url);if(value)this.hint=value; }
  private fenced(a:NotificationAuthority, ticket:number): boolean { return this.generation===ticket && stamp(this.current())===stamp(a); }
  private run<T>(work:()=>Promise<T>):Promise<T> { const result=this.serial.then(work,work);this.serial=result.catch(()=>undefined);return result; }
  sync():Promise<NotificationStatus> { const a=this.current(),ticket=this.generation;return this.run(()=>this.enroll(false,a,ticket)); }
  enable():Promise<NotificationStatus> { const a=this.current(),ticket=this.generation;return this.run(()=>this.enroll(true,a,ticket)); }
  private async enroll(optIn:boolean,a:NotificationAuthority|null,ticket:number):Promise<NotificationStatus> {
    try {
      const state=await this.native.status();
      if(!state.configured)return 'unconfigured';
      if(!a || !(a.chat||a.task) || !this.fenced(a,ticket))return 'unavailable';
      const scope=notificationScope(a);
      if(state.scope && state.scope!==scope){await this.native.clear();if(!this.fenced(a,ticket))return 'unavailable';state.enabled=false;state.accountKey='';}
      if(optIn){if(!await this.native.enable())return 'denied';if(!this.fenced(a,ticket)){await this.native.clear();return 'unavailable';}}
      else if(!state.enabled)return 'disabled';
      else if(!state.granted)return 'denied';
      else if(state.scope===scope && uuid(state.accountKey))return 'ready';
      const token=await this.native.token();
      if(!this.fenced(a,ticket)||!token||!uuid(token.installationId)||!/^\S{32,4096}$/.test(token.token)||!/^[\x21-\x7e]+$/.test(token.token))return 'unavailable';
      const ack=object(await this.post('register',a,{installation_id:token.installationId,fcm_token:token.token,client:'bwork'}));
      if(!this.fenced(a,ticket)||ack.api_version!==2||ack.installation_id!==token.installationId||!uuid(ack.account_key)||ack.push_enabled!==true||ack.client!=='bwork'||ack.preview_enabled!==false)return 'unavailable';
      return await this.native.bind(scope,token.installationId,token.token,ack.account_key,token.nativeEpoch) && this.fenced(a,ticket) ? 'ready' : 'unavailable';
    }catch{return 'unavailable';}
  }
  private post(operation:'register'|'unregister',a:NotificationAuthority,payload:Record<string,unknown>):Promise<unknown> {
    if(!a.csrf || a.csrf.length>1024)throw new Error('push_unavailable');
    const form={csrf_token:a.csrf,payload:JSON.stringify({api_version:2,...payload})};
    if(encodeURIComponent(form.payload).length+encodeURIComponent(a.csrf).length+32>8192)throw new Error('push_unavailable');
    return this.request({method:'POST',path:`/bchat/api/v2/notifications/${operation}`,form});
  }
  async disable():Promise<NotificationStatus> { const a=this.current();this.generation++;this.hint=null;this.abort?.abort();await this.native.disable();await this.unregister(a);return 'disabled'; }
  /** Native clear starts synchronously before login/logout can replace authority. */
  async invalidate():Promise<void> { const a=this.current();this.generation++;this.abort?.abort();await this.native.clear();await this.unregister(a); }
  private async unregister(a:NotificationAuthority|null):Promise<void> {
    try { const state=await this.native.status();if(a&&stamp(this.current())===stamp(a)&&state.configured&&uuid(state.installationId))await this.post('unregister',a,{installation_id:state.installationId}); }
    catch {/* Local binding is already cleared; offline cannot revoke through another actor. */}
  }
  async destination():Promise<NotificationDestination|null> {
    const a=this.current(),hint=this.hint,ticket=this.generation;if(!a||!hint)return null;
    try {
      const state=await this.native.status();
      if(!this.fenced(a,ticket)||this.hint!==hint||!state.configured||!state.enabled||!state.granted||state.scope!==notificationScope(a)||state.accountKey!==hint.accountKey)return null;
      this.hint=null;this.abort?.abort();const abort=new AbortController();this.abort=abort;
      const raw=object(await this.request({method:'GET',path:`/bchat/api/v2/notifications/${hint.eventId}`,signal:abort.signal}));
      const n=object(raw.notification),s=object(n.source_ref);
      if(!this.fenced(a,ticket)||abort.signal.aborted||raw.api_version!==2||n.id!==hint.eventId||n.kind!==hint.kind||!id(s.company_id)||!a.companyIds.includes(s.company_id))return null;
      if(n.kind==='chat'&&a.chat&&s.destination==='room_message'&&id(s.room_id)&&id(s.message_id))return {kind:'chat',companyId:s.company_id,roomId:s.room_id,messageId:s.message_id};
      if(n.kind==='task'&&a.task&&s.destination==='task'&&id(s.task_id))return {kind:'task',companyId:s.company_id,taskId:s.task_id};
    }catch{/* Unavailable/legacy targets never guess a company, path or identity. */}
    return null;
  }
}
