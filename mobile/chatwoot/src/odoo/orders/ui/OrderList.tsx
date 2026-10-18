import React, { useEffect, useRef, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { Button, colors, direction, Label } from '../../ui/components';
import type { Language } from '../../ui/dictionary';
import type { OrdersEngine } from '../core/OrdersEngine';
import type { OrderDetail, OrderState, OrderSummary, Selection } from '../core/types';
import { orderTranslator } from '../dictionary';
import { Busy, Choice, Empty, Failure, Heading, KeyValue, Note, NumberText, ordersStyles as s, rowDirection, useAlive } from './OrdersPrimitives';

export function OrderList({ engine, language, companies, canReceive, onReceive }: {
  engine: OrdersEngine; language: Language; companies: Selection[]; canReceive: boolean; onReceive: (companyId: number, orderId: number) => void;
}) {
  const t = orderTranslator(language), alive = useAlive();
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(null);
  const [company, setCompany] = useState(0), [state, setState] = useState<OrderState | 'all'>('all');
  const [detail, setDetail] = useState<OrderDetail | null>(null), [detailBusy, setDetailBusy] = useState(false);
  const gate = useRef(false), generation = useRef(0);
  const load = async (more = false) => {
    if (!alive() || gate.current || (more && (cursor === null || orders.length >= 200))) return;
    gate.current = true; const request = ++generation.current; setBusy(true); setError(null);
    try {
      const page = await engine.list(more ? cursor! : undefined);
      if (!alive() || request !== generation.current) return;
      setOrders(previous => {
        const merged = more ? [...previous, ...page.orders] : page.orders;
        return merged.filter((item, index) => companies.some(company => company.id === item.company_id) && merged.findIndex(other => other.id === item.id && other.company_id === item.company_id) === index).slice(0, 200);
      });
      setCursor(page.next_before_id);
    } catch (failure) { if (alive() && request === generation.current) setError(failure); }
    finally { gate.current = false; if (alive() && request === generation.current) setBusy(false); }
  };
  useEffect(() => { void load(); }, []);
  const open = async (order: OrderSummary) => {
    if (!alive() || gate.current || !companies.some(company => company.id === order.company_id)) return;
    gate.current = true; const request = ++generation.current; setError(null); setDetailBusy(true);
    try {
      const next = await engine.detail(order.company_id, order.id);
      if (alive() && request === generation.current) setDetail(next);
    } catch (failure) { if (alive() && request === generation.current) setError(failure); }
    finally { gate.current = false; if (alive() && request === generation.current) setDetailBusy(false); }
  };
  const visible = orders.filter(order => (company === 0 || company === order.company_id) && (state === 'all' || state === order.state));
  if (detail) return <View style={s.stack} testID="orders-detail">
    <Button quiet title={t('back')} onPress={() => { setDetail(null); setError(null); }} /><Heading language={language} word="details" />
    <View style={s.card}>
      <NumberText value={detail.order.name} /><Label language={language}>{t(detail.order.state)}</Label>
      <KeyValue language={language} label={t('company')}><Label language={language}>{companies.find(item => item.id === detail.order.company_id)?.name ?? detail.order.company_name}</Label></KeyValue>
      <KeyValue language={language} label={t('requester')}><Label language={language}>{detail.order.requester_name}</Label></KeyValue>
      <KeyValue language={language} label={t('orderDate')}><NumberText value={detail.order.submitted_at} /></KeyValue>
      <KeyValue language={language} label={t('method')}><Label language={language}>{t(detail.order.purchase_route)}</Label></KeyValue>
    </View>
    {detail.lines.map(line => <View style={s.card} key={line.line_id}><Label language={language}>{line.product_name}</Label><Label language={language} muted>{line.option_name}</Label>
      <KeyValue language={language} label={t('requested')}><NumberText value={line.requested_qty} /></KeyValue>
    </View>)}
    <View style={s.card}><KeyValue language={language} label={t('requestedTotal')}><NumberText value={detail.order.requested_total} suffix={detail.order.currency_symbol} /></KeyValue></View>
    <Note text={t('historical')} language={language} />
    {canReceive && ['sent', 'received'].includes(detail.order.state) && <Button title={t('openReceipt')} onPress={() => { if (alive()) onReceive(detail.order.company_id, detail.order.id); }} />}
  </View>;
  return <View style={s.stack}>
    <Choice label={t('company')} testID="orders-list-company" options={[{ id: 0, name: t('allCompanies') }, ...companies]} value={company} onSelect={setCompany} language={language} />
    <Note text={t('orderScope')} language={language} />
    <View style={[s.row, rowDirection(language)]}>{(['all', 'sent', 'purchased'] as const).map(item => <Button key={item} title={t(item)} quiet={state !== item} onPress={() => setState(item)} />)}</View>
    {!!error && <Failure language={language} error={error} retry={() => void load()} />}
    {detailBusy && <Busy language={language} />}
    {visible.map(order => <Pressable key={`${order.company_id}-${order.id}`} testID={`orders-row-${order.id}`} accessibilityRole="button"
      accessibilityLabel={`${t('details')} ${order.name} ${order.company_name}`} disabled={detailBusy} onPress={() => void open(order)}
      style={({ pressed }) => [s.card, pressed && { opacity: .75 }]}>
      <View style={[s.row, s.spread, rowDirection(language)]}><NumberText value={order.name} /><Text style={[s.strong, direction(language), { fontSize: 12, color: colors.blue }]}>{t(order.state)}</Text></View>
      <Label language={language}>{companies.find(item => item.id === order.company_id)?.name ?? order.company_name}</Label>
      <Label language={language} muted>{order.requester_name} · {t(order.purchase_route)}</Label>
      <KeyValue language={language} label={t('requestedTotal')}><NumberText value={order.requested_total} suffix={order.currency_symbol} /></KeyValue>
      <NumberText value={order.submitted_at} />
    </Pressable>)}
    {!busy && !error && !visible.length && <Empty language={language} title={t('empty')} help={t('emptyHelp')} />}
    {busy && <Busy language={language} />}
    {cursor !== null && orders.length < 200 && <Button title={t('loadMore')} onPress={() => void load(true)} disabled={busy || detailBusy} quiet />}
    {orders.length >= 200 && <Note text={t('listLimit')} language={language} />}
    <Button title={t('refresh')} onPress={() => void load()} disabled={busy || detailBusy} quiet />
  </View>;
}
