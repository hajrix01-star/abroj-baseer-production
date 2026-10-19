import React, { useCallback, useEffect, useState } from 'react';
import { AppState, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import type { OrdersOnlySnapshot } from './OrdersOnlySession';
import { getEngine, getOrdersEngine, ordersOnlySnapshot, refreshOrdersOnlySession } from '../runtime';
import { OrdersScreen } from '../orders/ui/OrdersScreen';
import { Button, IconButton, Label, styles } from '../ui/components';
import { Brand } from '../ui/Brand';
import { NavigationDrawer, type DrawerAction } from '../ui/NavigationDrawer';
import { errorWord, translator, type Language } from '../ui/dictionary';

/** Orders-only scope never mounts useChat, room history or offline chat restore. */
export function OrdersOnlyShell({ snapshot, language, setLanguage, online }: {
  snapshot: OrdersOnlySnapshot; language: Language; setLanguage: (value: Language) => void; online: boolean;
}) {
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const close = useCallback(() => setMenu(false), []);
  const t = translator(language);
  const identity = snapshot.identity;
  const actor = JSON.stringify([identity?.database, identity?.user_id]);
  const [companySelection, setCompanySelection] = useState({ actor: '', id: 0 });
  const selectedCompanyId = companySelection.actor === actor && identity?.company_ids.includes(companySelection.id) ? companySelection.id : 0;
  const ready = snapshot.verified && online;
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
    {ready ? <OrdersScreen key={`${snapshot.generation}/${snapshot.revision}`} scopeKey={`${snapshot.generation}/${snapshot.revision}`} engine={getOrdersEngine()} identity={identity} language={language} online
      selectedCompanyId={selectedCompanyId} onCompanyChange={id => {
        if (current() && (id === 0 || identity.company_ids.includes(id))) setCompanySelection({ actor, id });
      }} />
      : <View style={[styles.fill, { padding: 24, justifyContent: 'center', gap: 16 }]}>
        <Label language={language}>{t(error ? errorWord(error) : online ? 'loading' : 'connectionError')}</Label>
        <Button title={t('refresh')} disabled={busy || !online} onPress={() => void refresh()} />
        <Button title={t('logout')} disabled={busy} onPress={() => action('logout')} />
      </View>}
    <NavigationDrawer visible={menu && ready} identity={ready ? identity : null} language={language} t={t} offline={!ready}
      pendingCount={0} busy={busy} canManage={false} close={close} onAction={action} />
  </SafeAreaView>;
}
