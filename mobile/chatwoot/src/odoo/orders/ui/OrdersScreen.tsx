import React, { useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, View } from 'react-native';
import type { Bootstrap, Room } from '../../core/ChatEngine';
import { Button, colors, direction, IconButton, Label } from '../../ui/components';
import type { Language } from '../../ui/dictionary';
import { companyDisplayName } from '../../ui/companyNames';
import type { OrdersEngine } from '../core/OrdersEngine';
import type { OrdersOptions, PendingAttempt, WriteResult } from '../core/types';
import { orderTranslator } from '../dictionary';
import { OrderComposer } from './OrderComposer';
import { OrderList } from './OrderList';
import { Receiving } from './Receiving';
import { Busy, Choice, Empty, Failure, Heading, Note, NumberText, ordersStyles as s, rowDirection, useAlive } from './OrdersPrimitives';

export interface OrdersScreenProps {
  engine: OrdersEngine; identity: Bootstrap; language: Language; online: boolean; rooms?: Room[];
  /** Session owner can include origin/verification epoch without exposing credentials. */
  scopeKey?: string | number;
  onBack?: () => void; onMenu?: () => void;
}

export function OrdersScreen(props: OrdersScreenProps) {
  const { identity, online, language } = props;
  const t = orderTranslator(language);
  const engineScope = useRef({ engine: props.engine, revision: 0 });
  if (engineScope.current.engine !== props.engine) engineScope.current = { engine: props.engine, revision: engineScope.current.revision + 1 };
  // A key clears every in-memory order and closure before another scope can render it.
  const scope = JSON.stringify([props.scopeKey, engineScope.current.revision, identity.database, identity.user_id, identity.company_ids, identity.permissions, online]);
  return <View style={s.fill}>
    <View style={{ paddingHorizontal: 14, paddingVertical: 10, backgroundColor: colors.white }}>
      <View style={[s.row, rowDirection(language)]}>
        {props.onMenu && <IconButton icon="menu" label={t('menu')} onPress={props.onMenu} />}
        {!props.onMenu && props.onBack && <IconButton icon="back" label={t('back')} onPress={props.onBack} />}
        <View style={s.flexible}><Heading word="orders" language={language} /><Label language={language} muted>{t('purchaseRequests')}</Label></View>
      </View>
    </View>
    {!identity.permissions.order_view ? <Empty title={t('noAccess')} help={t('permissionHelp')} language={language} />
      : !online ? <Empty title={t('offline')} help={t('offlineHelp')} language={language} />
        : <Workspace key={scope} {...props} />}
  </View>;
}

type Tab = 'catalog' | 'allOrders' | 'receiving';
function Workspace({ engine, identity, language, rooms = [] }: OrdersScreenProps) {
  const t = orderTranslator(language);
  const alive = useAlive();
  const [options, setOptions] = useState<OrdersOptions | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const loading = useRef(false);
  const [tab, setTab] = useState<Tab>(identity.permissions.order_create ? 'catalog' : 'allOrders');
  const [company, setCompany] = useState(0);
  const [pending, setPending] = useState<PendingAttempt[]>([]);
  const [outcome, setOutcome] = useState<WriteResult | null>(null);
  const [receiptId, setReceiptId] = useState<number | undefined>();
  const [refresh, setRefresh] = useState(0);
  const load = async () => {
    if (!alive() || loading.current) return;
    loading.current = true; setBusy(true); setError(null);
    try {
      const next = await engine.options();
      if (!alive()) return;
      setOptions(next);
      const companies = next.companies.filter(item => identity.company_ids.includes(item.id));
      setCompany(companies[0]?.id ?? 0);
      const attempts = await engine.pending();
      if (alive()) setPending(attempts);
    } catch (failure) { if (alive()) setError(failure); }
    finally { loading.current = false; if (alive()) setBusy(false); }
  };
  useEffect(() => { void load(); }, []);
  useEffect(() => () => { engine.cancelReads(); }, [engine]);
  const reloadPending = async () => { try { const next = await engine.pending(); if (alive()) setPending(next); } catch (failure) { if (alive()) setError(failure); } };
  const result = (value: WriteResult) => { if (!alive()) return; setOutcome(value); void reloadPending(); };
  const changedCompany = (id: number) => { engine.invalidateQuote(); setCompany(id); setReceiptId(undefined); setOutcome(null); };
  const companies = (options?.companies ?? []).filter(item => identity.company_ids.includes(item.id)).map(item => {
    const profile = identity.profile?.companies.find(company => company.id === item.id);
    return { ...item, name: profile ? companyDisplayName(profile, language, item.id) : item.name };
  });
  const canView = options?.can_view === true && identity.permissions.order_view === true;
  const canCreate = canView && options?.can_create === true && identity.permissions.order_create === true;
  const canReceive = canView && options?.can_receive === true && identity.permissions.order_receive === true;
  const tabs: Tab[] = [...(canCreate ? ['catalog' as const] : []), ...(canView ? ['allOrders' as const] : []), ...(canReceive ? ['receiving' as const] : [])];
  const activeTab = tabs.includes(tab) ? tab : 'allOrders';
  const safeRooms = identity.permissions.chat_send === true ? rooms.filter(room => identity.company_ids.includes(room.company_id) && room.membership_id > 0) : [];
  return <>
    <View style={[s.tabs, rowDirection(language)]}>{tabs.map(item => <Pressable key={item} accessibilityRole="tab" accessibilityLabel={t(item)}
      accessibilityState={{ selected: activeTab === item }} testID={`orders-tab-${item}`} onPress={() => { if (alive()) { setOutcome(null); setTab(item); } }}
      style={[s.tab, activeTab === item && s.selectedTab]}><Text numberOfLines={2} style={[s.strong, direction(language), { fontSize: 14, color: activeTab === item ? colors.blue : colors.muted }]}>{t(item)}</Text></Pressable>)}</View>
    {busy ? <Busy language={language} /> : error ? <View style={s.content}><Failure error={error} language={language} retry={() => void load()} /></View>
      : !canView ? <Empty title={t('noAccess')} help={t('permissionHelp')} language={language} />
        : <KeyboardAvoidingView style={s.fill} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={[s.content, { paddingBottom: 24 }]}>
            {!!pending.length && <PendingPanel engine={engine} attempts={pending} language={language} onResult={result} onChanged={reloadPending} />}
            {outcome ? <ResultPanel engine={engine} result={outcome} language={language} canSend={identity.permissions.chat_send === true}
              close={() => { setOutcome(null); setRefresh(value => value + 1); setTab('allOrders'); }} />
              : activeTab === 'allOrders' ? <OrderList key={`list-${refresh}`} engine={engine} language={language} companies={companies} canReceive={canReceive}
                onReceive={(id, orderId) => { changedCompany(id); setReceiptId(orderId); setTab('receiving'); }} />
                : <>
                  <Choice label={t(activeTab === 'receiving' ? 'receiptCompany' : 'company')} testID="orders-company" options={companies} value={company} onSelect={changedCompany} language={language} />
                  {!company ? <Empty title={t('noOptions')} language={language} />
                    : activeTab === 'catalog' ? <OrderComposer key={`compose-${company}`} engine={engine} companyId={company} language={language}
                      rooms={safeRooms.filter(room => room.company_id === company)} onResult={result} onPending={reloadPending} blocked={pending.some(item => item.companyId === company && item.kind === 'create')} />
                      : <Receiving key={`receive-${company}-${receiptId ?? 'list'}`} engine={engine} companyId={company} initialOrderId={receiptId} language={language}
                        onResult={result} onPending={reloadPending} blockedOrderIds={pending.filter(item => item.kind === 'confirm' && item.companyId === company).map(item => item.orderId ?? 0)} />}
                </>}
          </ScrollView>
        </KeyboardAvoidingView>}
  </>;
}

function PendingPanel({ engine, attempts, language, onResult, onChanged }: {
  engine: OrdersEngine; attempts: PendingAttempt[]; language: Language; onResult: (result: WriteResult) => void; onChanged: () => Promise<void>;
}) {
  const t = orderTranslator(language), alive = useAlive();
  const gate = useRef(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const retry = async (uuid: string) => {
    if (!alive() || gate.current) return;
    gate.current = true; setBusy(uuid); setError(null);
    try { const result = await engine.retry(uuid); if (alive()) { onResult(result); await onChanged(); } }
    catch (failure) { if (alive()) { setError(failure); await onChanged(); } }
    finally { gate.current = false; if (alive()) setBusy(null); }
  };
  return <View style={s.card}><Label language={language}>{t('pending')}</Label><Note text={t('unknown')} language={language} warning />
    {attempts.map(attempt => <View key={attempt.uuid} style={s.stack}>
      <Label language={language} muted>{t(attempt.kind === 'create' ? 'sendOrder' : 'confirmReceipt')} · {attempt.orderId ?? attempt.companyId}</Label>
      <Button title={t('retryAttempt')} accessibilityLabel={`${t('retryAttempt')} ${attempt.orderId ?? attempt.companyId}`} busy={busy === attempt.uuid} disabled={busy !== null} onPress={() => void retry(attempt.uuid)} />
    </View>)}
    {!!error && <Failure error={error} language={language} />}
  </View>;
}

function ResultPanel({ engine, result, language, canSend, close }: { engine: OrdersEngine; result: WriteResult; language: Language; canSend: boolean; close: () => void }) {
  const t = orderTranslator(language), alive = useAlive();
  const receipt = 'receipt' in result ? result.receipt : null;
  const receiptScope = receipt ? `${receipt.company_id}/${receipt.order_id}` : '';
  const [originalRoom, setOriginalRoom] = useState<{ scope: string; roomId: number | null } | null>(null);
  const [busy, setBusy] = useState(false), [shared, setShared] = useState(false);
  const [shareDenied, setShareDenied] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const gate = useRef(false);
  const denied = useRef(false);
  const latest = useRef({ canSend, receiptScope }); latest.current = { canSend, receiptScope };
  useEffect(() => {
    setOriginalRoom(null); setShared(false); setShareDenied(false); denied.current = false;
    if (!receipt || !canSend) return;
    let active = true;
    // Orders detail supplies the original room. Chat visibility/list loading is unrelated;
    // the explicit share endpoint verifies current membership and send permission.
    void engine.detail(receipt.company_id, receipt.order_id).then(detail => { if (active && alive()) setOriginalRoom({ scope: receiptScope, roomId: detail.order.room_id }); }).catch(failure => { if (active && alive()) setError(failure); });
    return () => { active = false; };
  }, [receiptScope, canSend]);
  const canShare = !!receipt && canSend && originalRoom?.scope === receiptScope && !!originalRoom.roomId && !shareDenied;
  const share = async () => {
    if (!alive() || !canShare || gate.current || shared || denied.current || !receipt || !latest.current.canSend || latest.current.receiptScope !== receiptScope) return;
    gate.current = true; setBusy(true); setError(null);
    try { await engine.share(receipt.company_id, receipt.order_id); if (alive() && latest.current.receiptScope === receiptScope && latest.current.canSend) setShared(true); }
    catch (failure) { if (alive() && latest.current.receiptScope === receiptScope && latest.current.canSend) {
      if (typeof failure === 'object' && failure !== null && (('status' in failure && failure.status === 403) || ('code' in failure && failure.code === 'forbidden'))) { denied.current = true; setShareDenied(true); }
      setError(failure);
    } }
    finally { gate.current = false; if (alive()) setBusy(false); }
  };
  return <View style={s.stack} testID="orders-write-result"><Heading language={language} word={receipt ? 'confirmed' : 'created'} />
    <View style={s.card}><Label language={language}>{receipt?.name ?? ('order' in result ? result.order.name : '')}</Label>
      {receipt && <><Label language={language} muted>{t('actualTotal')}</Label><NumberText value={receipt.actual_total} suffix={receipt.currency_symbol} /></>}
    </View>
    {receipt && <><Note text={t('shareNote')} language={language} />
      <Button title={t(shared ? 'shared' : 'shareReceipt')} onPress={() => void share()} busy={busy} disabled={!canShare || shared} />
      {!canShare && <Note text={t('shareHelp')} language={language} />}</>}
    {!!error && <Failure error={error} language={language} />}
    <Button quiet title={t('returnOrders')} onPress={close} />
  </View>;
}
