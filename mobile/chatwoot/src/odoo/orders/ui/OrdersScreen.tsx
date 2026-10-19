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
import { PostCreateSharePanel, ReceiptSharePanel } from './OrderSharing';
import { Busy, Choice, Empty, Failure, Heading, Note, NumberText, ordersStyles as s, rowDirection, useAlive } from './OrdersPrimitives';

export interface OrdersScreenProps {
  engine: OrdersEngine; identity: Bootstrap; language: Language; online: boolean; rooms?: Room[];
  selectedCompanyId: number; onCompanyChange: (id: number) => void;
  /** Session owner can include origin/verification epoch without exposing credentials. */
  scopeKey?: string | number;
  onBack?: () => void; onMenu?: () => void;
}

export function OrdersScreen(props: OrdersScreenProps) {
  const { identity, online, language } = props;
  const t = orderTranslator(language);
  const alive = useAlive();
  const frame = useRef<View | null>(null);
  const measurement = useRef(0);
  const [keyboardOffset, setKeyboardOffset] = useState(0);
  const measureOffset = () => {
    const request = ++measurement.current;
    frame.current?.measureInWindow((_x, top) => {
      if (alive() && request === measurement.current && Number.isFinite(top)) setKeyboardOffset(Math.max(0, top));
    });
  };
  const engineScope = useRef({ engine: props.engine, revision: 0 });
  if (engineScope.current.engine !== props.engine) engineScope.current = { engine: props.engine, revision: engineScope.current.revision + 1 };
  // A key clears every in-memory order and closure before another scope can render it.
  const scope = JSON.stringify([props.scopeKey, engineScope.current.revision, identity.database, identity.user_id, identity.company_ids, identity.permissions, online]);
  // Keyboard events use screen coordinates; KAV's layout is relative to this
  // page below the shell header. Include that offset without remounting drafts.
  return <View ref={frame} collapsable={false} testID="orders-workspace-frame" onLayout={measureOffset} style={s.fill}>
    <View style={{ paddingHorizontal: 14, paddingVertical: 10, backgroundColor: colors.white }}>
      <View style={[s.row, rowDirection(language)]}>
        {props.onMenu && <IconButton icon="menu" label={t('menu')} onPress={props.onMenu} />}
        {!props.onMenu && props.onBack && <IconButton icon="back" label={t('back')} onPress={props.onBack} />}
        <View style={s.flexible}><Heading word="orders" language={language} /><Label language={language} muted>{t('purchaseRequests')}</Label></View>
      </View>
    </View>
    {!identity.permissions.order_view ? <Empty title={t('noAccess')} help={t('permissionHelp')} language={language} />
      : !online ? <Empty title={t('offline')} help={t('offlineHelp')} language={language} />
        : <Workspace key={scope} {...props} keyboardOffset={keyboardOffset} />}
  </View>;
}

type Tab = 'catalog' | 'allOrders' | 'receiving';
function Workspace({ engine, identity, language, selectedCompanyId, onCompanyChange, keyboardOffset }: OrdersScreenProps & { keyboardOffset: number }) {
  const t = orderTranslator(language);
  const alive = useAlive();
  const [options, setOptions] = useState<OrdersOptions | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const loading = useRef(false);
  const [tab, setTab] = useState<Tab>(identity.permissions.order_create ? 'catalog' : 'allOrders');
  const company = options?.companies.some(item => item.id === selectedCompanyId && identity.company_ids.includes(item.id)) ? selectedCompanyId : 0;
  const [pending, setPending] = useState<PendingAttempt[]>([]);
  const [savedOutcome, setOutcome] = useState<{ selection: number; value: WriteResult } | null>(null);
  const outcome = savedOutcome?.selection === selectedCompanyId ? savedOutcome.value : null;
  const [receiptTarget, setReceiptTarget] = useState<{ companyId: number; orderId: number } | null>(null);
  const receiptId = receiptTarget?.companyId === company ? receiptTarget.orderId : undefined;
  const selection = useRef(selectedCompanyId); selection.current = selectedCompanyId;
  const [refresh, setRefresh] = useState(0);
  const load = async () => {
    if (!alive() || loading.current) return;
    loading.current = true; setBusy(true); setError(null);
    try {
      const next = await engine.options();
      if (!alive()) return;
      setOptions(next);
      const attempts = await engine.pending();
      if (alive()) setPending(attempts);
    } catch (failure) { if (alive()) setError(failure); }
    finally { loading.current = false; if (alive()) setBusy(false); }
  };
  useEffect(() => { void load(); }, []);
  useEffect(() => () => { engine.cancelReads(); }, [engine, selectedCompanyId]);
  useEffect(() => { setOutcome(null); setReceiptTarget(previous => previous?.companyId === selectedCompanyId ? previous : null); }, [selectedCompanyId]);
  const reloadPending = async () => { try { const next = await engine.pending(); if (alive()) setPending(next); } catch (failure) { if (alive()) setError(failure); } };
  const result = (value: WriteResult) => { if (!alive()) return; setOutcome({ selection: selectedCompanyId, value }); void reloadPending(); };
  const changedCompany = (id: number) => { if (!alive() || selection.current !== selectedCompanyId || (id !== 0 && !options?.companies.some(item => item.id === id && identity.company_ids.includes(id)))) return; engine.invalidateQuote(); onCompanyChange(id); setReceiptTarget(null); setOutcome(null); };
  const companies = (options?.companies ?? []).filter(item => identity.company_ids.includes(item.id)).map(item => {
    const profile = identity.profile?.companies.find(company => company.id === item.id);
    return { ...item, name: profile ? companyDisplayName(profile, language, item.id) : item.name };
  });
  const canView = options?.can_view === true && identity.permissions.order_view === true;
  const canCreate = canView && options?.can_create === true && identity.permissions.order_create === true;
  const canReceive = canView && options?.can_receive === true && identity.permissions.order_receive === true;
  const tabs: Tab[] = [...(canCreate ? ['catalog' as const] : []), ...(canView ? ['allOrders' as const] : []), ...(canReceive ? ['receiving' as const] : [])];
  const activeTab = tabs.includes(tab) ? tab : 'allOrders';
  const pendingHeader = !!pending.length && <PendingPanel key={`pending-${selectedCompanyId}`} engine={engine} attempts={pending} language={language} onResult={result} onChanged={reloadPending} />;
  return <>
    <View style={[s.tabs, rowDirection(language)]}>{tabs.map(item => <Pressable key={item} accessibilityRole="tab" accessibilityLabel={t(item)}
      accessibilityState={{ selected: activeTab === item }} testID={`orders-tab-${item}`} onPress={() => { if (alive()) { setOutcome(null); setTab(item); } }}
      style={[s.tab, activeTab === item && s.selectedTab]}><Text numberOfLines={2} style={[s.strong, direction(language), { fontSize: 14, color: activeTab === item ? colors.blue : colors.muted }]}>{t(item)}</Text></Pressable>)}</View>
    {busy ? <Busy language={language} /> : error ? <View style={s.content}><Failure error={error} language={language} retry={() => void load()} /></View>
      : !canView ? <Empty title={t('noAccess')} help={t('permissionHelp')} language={language} />
        : <KeyboardAvoidingView style={s.fill} keyboardVerticalOffset={keyboardOffset} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
          {selectedCompanyId !== 0 && !company ? <View style={s.content}><Choice label={t('company')} testID="orders-company" options={companies} value={0} onSelect={changedCompany} language={language} /><Empty title={t('chooseCompany')} language={language} /></View>
          : !outcome && activeTab === 'catalog' && company ? <OrderComposer key={`compose-${company}`} engine={engine} companyId={company} language={language}
            header={<>{pendingHeader}<Choice label={t('company')} testID="orders-company" options={companies} value={company} onSelect={changedCompany} language={language} /></>}
            onResult={result} onPending={reloadPending} blocked={pending.some(item => item.companyId === company && item.kind === 'create')} /> :
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={[s.content, { paddingBottom: 24 }]}>
            {pendingHeader}
            {outcome ? <ResultPanel key={'receipt' in outcome ? outcome.client_uuid : `${outcome.order.company_id}/${outcome.order.id}`} engine={engine} result={outcome} language={language} canSend={identity.permissions.chat_send === true} workflowReady={options?.workflow_version === 1}
              close={() => { setOutcome(null); setRefresh(value => value + 1); setTab('allOrders'); }} />
              : activeTab === 'allOrders' ? <OrderList key={`list-${refresh}-${selectedCompanyId}`} engine={engine} language={language} companies={companies} canReceive={canReceive} companyId={company}
                actorId={identity.user_id} canCreate={canCreate} canSend={identity.permissions.chat_send === true} workflowReady={options?.workflow_version === 1}
                onCompanyChange={changedCompany}
                onReceive={(id, orderId) => { changedCompany(id); setReceiptTarget({ companyId: id, orderId }); setTab('receiving'); }} />
                : <>
                  <Choice label={t(activeTab === 'receiving' ? 'receiptCompany' : 'company')} testID="orders-company" options={companies} value={company} onSelect={changedCompany} language={language} />
                  {!company ? <Empty title={t('chooseCompany')} language={language} />
                    : <Receiving key={`receive-${company}-${receiptId ?? 'list'}`} engine={engine} companyId={company} initialOrderId={receiptId} language={language}
                        onResult={result} onPending={reloadPending} blockedOrderIds={pending.filter(item => item.kind === 'confirm' && item.companyId === company).map(item => item.orderId ?? 0)} />}
                </>}
          </ScrollView>}
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

function ResultPanel({ engine, result, language, canSend, close, workflowReady }: { engine: OrdersEngine; result: WriteResult; language: Language; canSend: boolean; close: () => void; workflowReady: boolean }) {
  const t = orderTranslator(language);
  const receipt = 'receipt' in result ? result.receipt : null;
  return <View style={s.stack} testID="orders-write-result"><Heading language={language} word={receipt ? 'confirmed' : 'created'} />
    <View style={s.card}><Label language={language}>{receipt?.name ?? ('order' in result ? result.order.name : '')}</Label>
      {receipt && <><Label language={language} muted>{t('actualTotal')}</Label><NumberText value={receipt.actual_total} suffix={receipt.currency_symbol} /></>}
    </View>
    {receipt ? <ReceiptSharePanel engine={engine} companyId={receipt.company_id} orderId={receipt.order_id} language={language} canSend={canSend} auto />
      : 'order' in result && !result.order.room_id && <PostCreateSharePanel engine={engine} companyId={result.order.company_id} orderId={result.order.id} language={language} canSend={canSend} workflowReady={workflowReady} />}
    <Button quiet title={t('returnOrders')} onPress={close} />
  </View>;
}
