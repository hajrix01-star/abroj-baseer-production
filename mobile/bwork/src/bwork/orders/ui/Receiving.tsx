import React, { useEffect, useRef, useState } from 'react';
import { Pressable, View } from 'react-native';
import { Button, Field, Label } from '../../ui/components';
import type { Language } from '../../ui/dictionary';
import type { OrdersEngine } from '../core/OrdersEngine';
import type { ConfirmResult, PendingAttempt, ReceiptDetail, ReceiptLineInput, ReceiptSummary, Selection } from '../core/types';
import { displayNumber, orderTranslator } from '../dictionary';
import { Busy, Empty, Failure, Heading, KeyValue, Note, NumberText, ordersStyles as s, rowDirection, useAlive, useResumeRead } from './OrdersPrimitives';

const decimal = (value: string, digits: number) => new RegExp(`^(?:[1-9][0-9]{0,${digits - 1}}|0)(?:\\.[0-9]{1,2})?$`).test(value);
export function validReceipt(lines: ReceiptLineInput[]): boolean {
  return lines.length > 0 && lines.every(line => decimal(line.actual_qty, 6) && decimal(line.actual_price, 9)
    && (Number(line.actual_qty) === 0 ? Number(line.actual_price) === 0 : Number(line.actual_price) > 0))
    && lines.some(line => Number(line.actual_qty) > 0 && Number(line.actual_price) > 0);
}

export function Receiving({ engine, companyId, companies, language, initialTarget, onResult, onPending, blockedAttempts }: {
  engine: OrdersEngine; companyId: number; companies: Selection[]; language: Language; initialTarget?: { companyId: number; orderId: number }; onResult: (result: ConfirmResult) => void;
  onPending: () => Promise<void>; blockedAttempts: PendingAttempt[];
}) {
  const t = orderTranslator(language), alive = useAlive();
  const [orders, setOrders] = useState<ReceiptSummary[]>([]), [cursor, setCursor] = useState<number | null>(null);
  const [detail, setDetail] = useState<ReceiptDetail | null>(null), [lines, setLines] = useState<ReceiptLineInput[]>([]);
  const [review, setReview] = useState(false), [busy, setBusy] = useState(false), [writing, setWriting] = useState(false);
  const [error, setError] = useState<unknown>(null), [unknown, setUnknown] = useState(false), [attempted, setAttempted] = useState(false);
  const gate = useRef(false), writeGate = useRef(false), generation = useRef(0);
  const interrupted = useRef<() => void>(() => {}), resumeRead = useResumeRead(() => interrupted.current());
  const latest = useRef({ blockedAttempts, companies }); latest.current = { blockedAttempts, companies };
  const authorized = (id: number) => latest.current.companies.some(company => company.id === id);
  const companyName = (id: number) => companies.find(company => company.id === id)?.name ?? '';
  const load = async (more = false) => {
    if (!alive() || gate.current || (more && (cursor === null || orders.length >= 200))) return;
    gate.current = true; const request = ++generation.current; setBusy(true); setError(null);
    try {
      const page = await engine.receipts(companyId || undefined, more ? cursor! : undefined);
      if (!alive() || request !== generation.current) return;
      setOrders(previous => (more ? [...previous, ...page.orders] : page.orders).filter((item, index, all) => authorized(item.company_id)
        && (!companyId || item.company_id === companyId) && all.findIndex(other => other.id === item.id && other.company_id === item.company_id) === index).slice(0, 200));
      setCursor(page.next_before_id);
    } catch (failure) { if (alive() && request === generation.current) { interrupted.current = () => void load(more); if (!resumeRead(failure)) setError(failure); } }
    finally { gate.current = false; if (alive() && request === generation.current) setBusy(false); }
  };
  const open = async (rowCompanyId: number, id: number) => {
    if (!alive() || gate.current || !authorized(rowCompanyId)) return;
    gate.current = true; const request = ++generation.current; setBusy(true); setError(null);
    try {
      const next = await engine.receiptDetail(rowCompanyId, id);
      if (!alive() || request !== generation.current) return;
      setDetail(next); setLines(next.lines.map(line => ({ line_id: line.line_id, actual_qty: line.requested_qty, actual_price: '' })));
      setReview(false); setUnknown(false); setAttempted(false);
    } catch (failure) { if (alive() && request === generation.current) { interrupted.current = () => void open(rowCompanyId, id); if (!resumeRead(failure)) setError(failure); } }
    finally { gate.current = false; if (alive() && request === generation.current) setBusy(false); }
  };
  useEffect(() => { if (initialTarget) void open(initialTarget.companyId, initialTarget.orderId); else void load(); }, []);
  const isBlocked = (orderId: number, rowCompanyId: number) => latest.current.blockedAttempts.some(attempt => attempt.companyId === rowCompanyId && attempt.orderId === orderId);
  const valid = validReceipt(lines), blocked = !!detail && isBlocked(detail.order.id, detail.order.company_id);
  const edit = (id: number, key: 'actual_qty' | 'actual_price', value: string) => {
    if (!alive() || writeGate.current || review || unknown) return;
    setLines(previous => previous.map(line => line.line_id === id ? { ...line, [key]: displayNumber(value).replace('٫', '.') } : line));
  };
  const confirm = async () => {
    if (!alive() || writeGate.current || !detail || !review || !valid || unknown || !authorized(detail.order.company_id) || isBlocked(detail.order.id, detail.order.company_id)) return;
    writeGate.current = true; setWriting(true); setError(null);
    try {
      const result = await engine.confirm(detail.order.id, { company_id: detail.order.company_id, lines: lines.map(line => ({ ...line })) }, detail.lines.map(line => line.line_id));
      if (alive()) onResult(result);
    } catch (failure) {
      if (alive()) { setError(failure); if (typeof failure === 'object' && failure !== null && 'code' in failure && failure.code === 'unknown') setUnknown(true); await onPending(); }
    } finally { writeGate.current = false; if (alive()) setWriting(false); }
  };
  return <View style={s.stack}>
    <Note text={t('receiptsScope')} language={language} />
    {!!error && <Failure error={error} language={language} retry={!detail ? () => initialTarget ? void open(initialTarget.companyId, initialTarget.orderId) : void load() : undefined} />}
    {busy && <Busy language={language} />}
    {detail ? <>
      <Button quiet title={t('back')} busy={false} disabled={writing} onPress={() => { if (!alive() || writeGate.current) return; if (review) setReview(false); else { setDetail(null); setError(null); void load(); } }} />
      <Heading language={language} word={review ? 'reviewReceipt' : 'receiptTitle'} />
      <View style={s.card}><NumberText value={detail.order.name} /><Label language={language}>{companyName(detail.order.company_id)}</Label><KeyValue language={language} label={t('warehouse')}><Label language={language}>{detail.order.warehouse_name}</Label></KeyValue></View>
      {detail.lines.map(line => {
        const input = lines.find(item => item.line_id === line.line_id)!;
        return <View key={line.line_id} testID={`receipt-line-${line.line_id}`} style={s.card}>
          <Label language={language}>{line.product_name}</Label><Label language={language} muted>{line.option_name} · {line.uom_name}</Label>
          <KeyValue language={language} label={t('requested')}><NumberText value={line.requested_qty} /></KeyValue>
          {review ? <><KeyValue language={language} label={t('actualQty')}><NumberText value={input.actual_qty} /></KeyValue>
            <KeyValue language={language} label={t('actualPrice')}><NumberText value={input.actual_price} suffix={detail.order.currency_symbol} /></KeyValue></>
            : <View style={[s.row, rowDirection(language), { alignItems: 'flex-start' }]}>
              <View style={{ flex: 1, minWidth: 100, gap: 5 }}><Label language={language} muted>{t('actualQty')}</Label>
                <Field language={language} testID={`receipt-quantity-${line.line_id}`} accessibilityLabel={`${t('actualQty')} ${line.product_name} ${line.option_name}`} value={input.actual_qty}
                  onChangeText={value => edit(line.line_id, 'actual_qty', value)} keyboardType="decimal-pad" maxLength={9} editable={!writing && !unknown && !blocked} style={{ writingDirection: 'ltr', minHeight: 44 }} />
              </View>
              <View style={{ flex: 1, minWidth: 100, gap: 5 }}><Label language={language} muted>{t('actualPrice')}</Label>
                <Field language={language} testID={`receipt-price-${line.line_id}`} accessibilityLabel={`${t('actualPrice')} ${line.product_name} ${line.option_name}`} value={input.actual_price}
                  onChangeText={value => edit(line.line_id, 'actual_price', value)} keyboardType="decimal-pad" maxLength={12} editable={!writing && !unknown && !blocked} style={{ writingDirection: 'ltr', minHeight: 44 }} />
              </View>
            </View>}
        </View>;
      })}
      {review && <View style={s.card}><KeyValue language={language} label={t('actualTotal')}><Label language={language} muted>{t('afterOdoo')}</Label></KeyValue></View>}
      <Note text={t('receiptWarning')} language={language} warning />
      {attempted && !valid && <Note text={t('validation')} language={language} warning />}
      {(blocked || unknown) && <Note text={t('pendingBlock')} language={language} warning />}
      <Button title={t(review ? 'confirmReceipt' : 'reviewReceipt')} busy={writing} disabled={unknown || blocked || (review && !valid)}
        onPress={() => { if (!alive()) return; setAttempted(true); if (review) void confirm(); else if (valid) setReview(true); }} />
    </> : <>
      {orders.map(order => <Pressable testID={`receipt-row-${order.id}`} key={`${order.company_id}/${order.id}`} accessibilityRole="button" accessibilityLabel={`${t('openReceipt')} ${order.name} ${companyName(order.company_id)}`}
        disabled={busy} onPress={() => void open(order.company_id, order.id)} style={({ pressed }) => [s.card, pressed && { opacity: .75 }]}>
        <View style={[s.row, s.spread, rowDirection(language)]}><NumberText value={order.name} /><Label language={language} muted>{t(order.state)}</Label></View>
        <Label language={language}>{companyName(order.company_id)}</Label><Label language={language}>{order.requester_name}</Label><Label language={language} muted>{order.warehouse_name}</Label>
        <KeyValue language={language} label={t('requestedTotal')}><NumberText value={order.requested_total} suffix={order.currency_symbol} /></KeyValue>
      </Pressable>)}
      {!busy && !error && !orders.length && <Empty title={t('noReceipts')} help={t('noReceiptsHelp')} language={language} />}
      {cursor !== null && orders.length < 200 && <Button quiet title={t('loadMore')} onPress={() => void load(true)} busy={false} disabled={busy} />}
      {orders.length >= 200 && <Note text={t('listLimit')} language={language} />}
      {!initialTarget && <Button quiet title={t('refresh')} onPress={() => void load()} busy={false} disabled={busy} />}
    </>}
  </View>;
}
