import React, { useEffect, useRef, useState } from 'react';
import { AppState, Linking, NativeModules, View } from 'react-native';
import { Button, Label, Sheet } from '../ui/components';
import { translator, type Language } from '../ui/dictionary';
import { notificationTranslator } from './dictionary';
import type { NotificationsEngine, NotificationDestination, NotificationStatus } from './NotificationsEngine';

/** Tap intents are hints. Only a foreground, verified server lookup may navigate. */
export function NotificationsHub({engine,language,ready,scopeKey,visible,close,onDestination}: {
  engine:NotificationsEngine;language:Language;ready:boolean;scopeKey:string;visible:boolean;close:()=>void;
  onDestination:(destination:NotificationDestination)=>void|Promise<void>;
}) {
  const [status,setStatus]=useState<NotificationStatus>('unavailable'),[busy,setBusy]=useState(false);
  const live=useRef({ready,scopeKey,visible,onDestination,close,alive:true});
  live.current={ready,scopeKey,visible,onDestination,close,alive:true};
  const serial=useRef(0);
  const run=async (action:'sync'|'enable'|'disable')=> {
    const ticket=++serial.current,scope=live.current.scopeKey;
    const current=()=>live.current.alive&&live.current.ready&&live.current.scopeKey===scope&&ticket===serial.current&&AppState.currentState==='active';
    if(!current())return;
    setBusy(true);
    try {
      const result=await engine[action]();if(!current())return;setStatus(result);
      if(action==='sync'&&result==='ready'){const destination=await engine.destination();if(current()&&destination)await live.current.onDestination(destination);}
    } catch {if(current())setStatus('unavailable');}
    finally {if(current())setBusy(false);}
  };
  useEffect(()=>{live.current.alive=true;return()=>{live.current.alive=false;serial.current++;};},[]);
  useEffect(()=>{NativeModules?.BWorkNotifications?.language(language);},[language]);
  useEffect(()=>{
    let alive=true;
    const intent=(url:unknown)=>{engine.intent(url);if(alive&&live.current.ready)void run('sync');};
    void Linking.getInitialURL().then(url=>{if(alive&&url)intent(url);}).catch(()=>undefined);
    const links=Linking.addEventListener('url',event=>intent(event.url));
    const state=AppState.addEventListener('change',value=>{if(value==='active'&&live.current.ready)void run('sync');else if(value!=='active'){serial.current++;live.current.close();}});
    return()=>{alive=false;links.remove();state.remove();};
  },[engine]);
  useEffect(()=>{serial.current++;setBusy(false);if(ready)void run('sync');else close();},[ready,scopeKey,visible]);
  const t=notificationTranslator(language);
  return visible&&ready ? <Sheet title={t('title')} close={close} t={translator(language)} language={language} compact>
    <View testID="notification-settings" style={{gap:12}}>
      <Label language={language}>{t(status)}</Label>
      <Label language={language} muted>{t('privacy')}</Label>
      <Label language={language} muted>{t('limits')}</Label>
      <Button title={t(status==='ready'?'disable':'enable')} disabled={busy||status==='unconfigured'}
        onPress={()=>{if(live.current.alive&&live.current.ready&&live.current.visible&&live.current.scopeKey===scopeKey&&!busy&&status!=='unconfigured')void run(status==='ready'?'disable':'enable');}} />
    </View>
  </Sheet> : null;
}
