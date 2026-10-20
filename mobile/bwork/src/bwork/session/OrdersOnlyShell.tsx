import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import type { OrdersOnlySnapshot } from './OrdersOnlySession';
import { getEngine, getOrdersEngine, getTasksEngine, getLeadershipEngine, getNotificationsEngine, ordersOnlySnapshot, refreshOrdersOnlySession } from '../runtime';
import { NotificationsHub } from '../notifications/NotificationsHub';
import { OrdersScreen } from '../orders/ui/OrdersScreen';
import { orderTranslator } from '../orders/dictionary';
import { TasksScreen, taskNotificationScope } from '../tasks/ui/TasksScreen';
import { LeadershipScreen } from '../leadership/ui/LeadershipScreen';
import { taskTranslator } from '../tasks/dictionary';
import { Button, colors, IconButton, Label, styles } from '../ui/components';
import { Brand } from '../ui/Brand';
import { NavigationDrawer, type DrawerAction } from '../ui/NavigationDrawer';
import { errorWord, translator, type Language } from '../ui/dictionary';

/** Non-chat scope never mounts useChat, room history or offline chat restore. */
export function OrdersOnlyShell({ snapshot, language, setLanguage, online }: {
  snapshot: OrdersOnlySnapshot; language: Language; setLanguage: (value: Language) => void; online: boolean;
}) {
  const [menu, setMenu] = useState(false);
  const [notificationsVisible,setNotificationsVisible]=useState(false);
  const [notificationTarget,setNotificationTarget]=useState<{companyId:number;taskId:number;nonce:number;authority:string}|undefined>();
  const closeNotifications=useCallback(()=>setNotificationsVisible(false),[]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const close = useCallback(() => setMenu(false), []);
  const t = translator(language);
  const identity = snapshot.identity;
  const hasOrders = identity?.permissions.order_view === true;
  const hasTasks = identity?.permissions.task_view === true;
  const hasLeadership = identity?.permissions.dashboard_view === true;
  const fallbackArea = hasOrders ? 'orders' : hasTasks ? 'tasks' : 'leadership';
  const [area, setArea] = useState<'orders' | 'tasks' | 'leadership'>(fallbackArea);
  const [tasksVisited, setTasksVisited] = useState(!hasOrders && hasTasks);
  const [leadershipVisited, setLeadershipVisited] = useState(!hasOrders && !hasTasks && hasLeadership);
  const visibleArea = (area === 'orders' && !hasOrders) || (area === 'tasks' && !hasTasks) || (area === 'leadership' && !hasLeadership) ? fallbackArea : area;
  const actor = JSON.stringify([identity?.database, identity?.user_id]);
  const [companySelection, setCompanySelection] = useState({ actor: '', id: 0 });
  const selectedCompanyId = companySelection.actor === actor && identity?.company_ids.includes(companySelection.id) ? companySelection.id : 0;
  const ready = snapshot.verified && online;
  // A verification revision fences old callbacks/requests, but is not a new
  // display authority. Keep the same workspace mounted behind a private cover.
  const displayScope = JSON.stringify([snapshot.generation, identity?.database, identity?.user_id,
    [...(identity?.company_ids ?? [])].sort((a, b) => a - b),
    Object.entries(identity?.permissions ?? {}).sort(([a], [b]) => a.localeCompare(b))]);
  const mountedScope = useRef<string | null>(null);
  if (ready) mountedScope.current = displayScope;
  const retainWorkspace = mountedScope.current === displayScope;
  useEffect(() => { if (!ready) setMenu(false); }, [ready]);
  const current = () => {
    const live = ordersOnlySnapshot();
    return AppState.currentState === 'active' && live.generation === snapshot.generation && live.revision === snapshot.revision;
  };
  const refresh = async () => {
    if (busy || !online || !current()) return;
    setBusy(true); setError(null);
    try { await refreshOrdersOnlySession(); } catch (failure) { setError(failure); }
    finally { setBusy(false); }
  };
  const action = (value: DrawerAction) => {
    if (!current()) return;
    if (value === 'ar' || value === 'en') { setLanguage(value); return; }
    setMenu(false);
    if (value === 'refresh') void refresh();
    if (value === 'logout' && !busy) {
      setBusy(true);
      void getEngine().logout().catch(setError).finally(() => setBusy(false));
    }
  };
  if (!identity) return null;
  return <SafeAreaView style={styles.page}>
    <View style={[styles.header, { direction: 'ltr', flexDirection: language === 'ar' ? 'row-reverse' : 'row', alignItems: 'center', gap: 8, paddingHorizontal: 8, paddingVertical: 6 }]}>
      {ready ? <IconButton icon="menu" label={t('menu')} onPress={() => { if (current()) setMenu(true); }} /> : <View style={{ width: 44 }} />}
      <View style={{ flex: 1, alignItems: language === 'ar' ? 'flex-end' : 'flex-start' }}><Brand /></View>
    </View>
    <View style={styles.fill}>
    {retainWorkspace && hasOrders && <View style={[styles.fill, { display: visibleArea === 'orders' ? 'flex' : 'none' }]} pointerEvents={visibleArea === 'orders' ? 'auto' : 'none'}
      accessibilityElementsHidden={visibleArea !== 'orders'} importantForAccessibility={visibleArea === 'orders' ? 'auto' : 'no-hide-descendants'}>
      <OrdersScreen key={displayScope} scopeKey={displayScope} engine={getOrdersEngine()} identity={identity} language={language} online={online} presented={ready && visibleArea === 'orders'}
      selectedCompanyId={selectedCompanyId} onCompanyChange={id => {
        if (current() && (id === 0 || identity.company_ids.includes(id))) setCompanySelection({ actor, id });
      }} /></View>}
    {retainWorkspace && hasTasks && (tasksVisited || visibleArea === 'tasks') && <View style={[styles.fill, { display: visibleArea === 'tasks' ? 'flex' : 'none' }]}
      pointerEvents={visibleArea === 'tasks' ? 'auto' : 'none'} accessibilityElementsHidden={visibleArea !== 'tasks'} importantForAccessibility={visibleArea === 'tasks' ? 'auto' : 'no-hide-descendants'}>
      <TasksScreen key={displayScope} engine={getTasksEngine()} identity={identity} language={language} scopeKey={displayScope} notificationTarget={notificationTarget} presented={ready && visibleArea === 'tasks'} />
    </View>}
    {retainWorkspace && hasLeadership && (leadershipVisited || visibleArea === 'leadership') && <View style={[styles.fill, { display: visibleArea === 'leadership' ? 'flex' : 'none' }]}
      pointerEvents={visibleArea === 'leadership' ? 'auto' : 'none'} accessibilityElementsHidden={visibleArea !== 'leadership'} importantForAccessibility={visibleArea === 'leadership' ? 'auto' : 'no-hide-descendants'}>
      <LeadershipScreen key={displayScope} engine={getLeadershipEngine()} identity={identity} language={language} scopeKey={displayScope} presented={ready && visibleArea === 'leadership'} />
    </View>}
    {!ready && <View testID="orders-session-privacy-cover" style={[styles.fill, {
      ...(retainWorkspace ? { position: 'absolute', top: 0, bottom: 0, left: 0, right: 0 } : {}),
      backgroundColor: colors.white, padding: 24, justifyContent: 'center', gap: 16,
    }]}>
        {(!!error || !online || !retainWorkspace) && <Label language={language}>{t(error ? errorWord(error) : online ? 'loading' : 'connectionError')}</Label>}
        <Button title={t('refresh')} disabled={busy || !online} onPress={() => void refresh()} />
        <Button title={t('logout')} disabled={busy} onPress={() => action('logout')} />
      </View>}
    </View>
    <NavigationDrawer visible={menu && ready} identity={ready ? identity : null} language={language} t={t} offline={!ready}
      pendingCount={0} busy={busy} canManage={false} close={close} onAction={action}
      onNotifications={hasTasks?()=>{if(ready&&current()){setMenu(false);setNotificationsVisible(true);}}:undefined}
      ordersLabel={orderTranslator(language)('orders')}
      onOrders={hasOrders ? () => { if (ready && current()) { setMenu(false); setArea('orders'); } } : undefined}
      leadershipLabel={t('leadership')}
      onLeadership={hasLeadership ? () => { if (ready && current()) { setMenu(false); setLeadershipVisited(true); setArea('leadership'); } } : undefined}
      tasksLabel={taskTranslator(language)('tasks')}
      onTasks={hasTasks ? () => { if (ready && current()) { setMenu(false); setTasksVisited(true); setArea('tasks'); } } : undefined} />
    <NotificationsHub engine={getNotificationsEngine()} language={language} ready={ready&&hasTasks} scopeKey={displayScope+':'+snapshot.revision} visible={notificationsVisible} close={closeNotifications}
      onDestination={destination=>{if(!ready||!current()||!hasTasks||destination.kind!=='task'||!identity.company_ids.includes(destination.companyId))return;
        setNotificationTarget({companyId:destination.companyId,taskId:destination.taskId,nonce:Date.now(),authority:taskNotificationScope(identity,displayScope)});setTasksVisited(true);setArea('tasks');setNotificationsVisible(false);}} />
  </SafeAreaView>;
}
