import React, { useContext, useEffect, useRef, useState } from 'react';
import { Pressable, View } from 'react-native';
import { Button, Field, Label, Sheet } from '../../ui/components';
import { translator, type Language } from '../../ui/dictionary';
import type { OrdersEngine } from '../core/OrdersEngine';
import type { Selection } from '../core/types';
import { orderTranslator } from '../dictionary';
import { Busy, Failure, Note, OrdersPresentation, ordersStyles as s, useAlive } from './OrdersPrimitives';

/** This panel starts only after a documented create ACK; it never calls create. */
export function PostCreateSharePanel({ engine, companyId, orderId, language, canSend, workflowReady }: {
  engine: OrdersEngine; companyId: number; orderId: number; language: Language; canSend: boolean; workflowReady: boolean;
}) {
  const t = orderTranslator(language), alive = useAlive();
  const presented = useContext(OrdersPresentation), visible = useRef(presented); visible.current = presented;
  const [rooms, setRooms] = useState<Selection[]>([]), [preferred, setPreferred] = useState<Selection | null>(null);
  const [savedId, setSavedId] = useState<number | null>(null), [selected, setSelected] = useState<Selection | null>(null);
  const [cursor, setCursor] = useState<number | null>(null), [query, setQuery] = useState(''), [opened, setOpened] = useState(false);
  const [busy, setBusy] = useState(false), [sharing, setSharing] = useState(false), [saving, setSaving] = useState(false), [shared, setShared] = useState(false);
  const [error, setError] = useState<unknown>(null), [roomError, setRoomError] = useState<unknown>(null), [preferenceError, setPreferenceError] = useState<unknown>(null);
  const [missingDefault, setMissingDefault] = useState(false), [reload, setReload] = useState(0);
  const [invalidPreference, setInvalidPreference] = useState(false);
  const generation = useRef(0), loading = useRef(false), shareGate = useRef(false), saveGate = useRef(false);
  const preference = useRef<number | null>(null), selection = useRef<Selection | null>(null);
  const count = useRef(0); count.current = rooms.length + (preferred && !rooms.some(item => item.id === preferred.id) ? 1 : 0);
  const latest = useRef({ canSend, workflowReady }); latest.current = { canSend, workflowReady };
  const eligible = () => alive() && latest.current.canSend && latest.current.workflowReady;
  const load = async (more: boolean, request: number) => {
    if (!eligible() || !visible.current || (more && (loading.current || cursor === null || count.current >= 200))) return;
    loading.current = true; setBusy(true); setRoomError(null);
    try {
      if (!more) {
        // A broken optional preference must not block the authorized room picker.
        try { preference.current = await engine.savedRoom(companyId); if (!eligible() || request !== generation.current) return; setSavedId(preference.current); }
        catch (failure) {
          if (!eligible() || request !== generation.current) return;
          preference.current = null; setSavedId(null); setPreferenceError(failure); setInvalidPreference(true);
        }
      }
      if (!visible.current) return;
      const preferredId = selection.current?.id ?? preference.current;
      const page = await engine.rooms(companyId, { ...(query.trim() ? { q: query.trim() } : {}), ...(more ? { afterId: cursor! } : {}),
        ...(preferredId ? { preferredRoomId: preferredId } : {}) });
      if (!eligible() || request !== generation.current) return;
      setRooms(previous => {
        const merged = (more ? [...previous, ...page.rooms] : page.rooms).filter((item, index, all) => all.findIndex(other => other.id === item.id) === index);
        return merged.slice(0, 200 - (page.preferred_room && !merged.some(item => item.id === page.preferred_room!.id) ? 1 : 0));
      });
      setPreferred(page.preferred_room); setCursor(page.next_after_id);
      if (preferredId === preference.current) setMissingDefault(!!preference.current && !page.preferred_room);
      // Selection is accepted only when present in this fresh authorized response.
      const validSelection = selection.current && [...page.rooms, ...(page.preferred_room ? [page.preferred_room] : [])].find(item => item.id === selection.current!.id);
      selection.current = validSelection || (!query.trim() && !selection.current ? page.preferred_room : null) || null;
      setSelected(selection.current);
    } catch (failure) { if (eligible() && request === generation.current) setRoomError(failure); }
    finally { if (request === generation.current) { loading.current = false; if (alive()) setBusy(false); } }
  };
  useEffect(() => {
    if (!presented) return;
    const request = ++generation.current; loading.current = false; setRooms([]); setCursor(null);
    if (!canSend || !workflowReady || shared) return;
    const timer = setTimeout(() => { void load(false, request); }, 350);
    return () => { clearTimeout(timer); generation.current++; };
  }, [query, reload, canSend, workflowReady, shared, presented]);
  const save = async (roomId: number | null) => {
    if (!eligible() || !visible.current || saveGate.current || shareGate.current || loading.current || (roomId !== null && roomId !== selection.current?.id)) return;
    saveGate.current = true; setSaving(true); setPreferenceError(null);
    try { await engine.saveRoom(companyId, roomId); if (eligible()) { preference.current = roomId; setSavedId(roomId); setMissingDefault(false); setInvalidPreference(false); } }
    catch (failure) { if (eligible()) setPreferenceError(failure); }
    finally { saveGate.current = false; if (alive()) setSaving(false); }
  };
  const share = async () => {
    const room = selection.current;
    if (!eligible() || !visible.current || !room || shareGate.current || shared || busy || !!roomError) return;
    shareGate.current = true; setSharing(true); setError(null);
    try { await engine.shareOrder(companyId, orderId, room.id); if (eligible()) setShared(true); }
    catch (failure) { if (eligible()) {
      setError(failure);
      if (typeof failure === 'object' && failure !== null && 'code' in failure && failure.code === 'room_unavailable') {
        selection.current = null; setSelected(null); setPreferred(null); setMissingDefault(!!preference.current); setReload(value => value + 1);
      }
    } }
    finally { shareGate.current = false; if (alive()) setSharing(false); }
  };
  if (!workflowReady) return <Note text={t('serverUpdateRequired')} language={language} warning />;
  if (!canSend) return <Note text={t('sharePermission')} language={language} />;
  return <View style={s.stack} testID="orders-post-create-share">
    <Note text={t(shared ? 'orderShared' : 'orderSavedShare')} language={language} />
    {!shared && <>
      <Button quiet title={selected?.name ?? t('chooseRoom')} busy={false} disabled={sharing || saving} onPress={() => { if (eligible() && visible.current && !shareGate.current && !saveGate.current) setOpened(true); }} />
      {missingDefault && <Note text={t('defaultUnavailable')} language={language} warning />}
      {busy && <Busy language={language} />}
      {!!roomError && <Failure error={roomError} language={language} retry={() => setReload(value => value + 1)} />}
      <Button title={t(error ? 'retryShare' : 'shareOrder')} busy={sharing} disabled={!selected || busy || !!roomError || saving} onPress={() => void share()} />
      {selected && savedId !== selected.id && <Button quiet title={t('rememberRoom')} busy={saving} disabled={sharing || busy} onPress={() => void save(selected.id)} />}
      {(!!savedId || invalidPreference) && <Button quiet title={t('clearDefault')} busy={saving} disabled={sharing || busy} onPress={() => void save(null)} />}
    </>}
    {!!error && <><Note text={t('orderShareFailed')} language={language} warning /><Failure error={error} language={language} /></>}
    {!!preferenceError && <Failure error={preferenceError} language={language} />}
    {opened && presented && !shared && <Sheet compact language={language} title={t('conversation')} t={translator(language)} close={() => setOpened(false)}>
      <Field language={language} testID="orders-room-search" accessibilityLabel={t('searchRooms')} value={query} onChangeText={setQuery} maxLength={80} placeholder={t('searchRooms')} />
      {[...(preferred && !rooms.some(item => item.id === preferred.id) ? [preferred] : []), ...rooms].map(room => <Pressable key={room.id} testID={`orders-share-room-${room.id}`}
        accessibilityRole="button" accessibilityLabel={room.name} accessibilityState={{ selected: selected?.id === room.id, disabled: busy }} disabled={busy}
        style={[s.compactCard, { minHeight: 44, justifyContent: 'center' }]}
        onPress={() => { if (!eligible() || !visible.current || loading.current || shareGate.current || saveGate.current || ![...rooms, ...(preferred ? [preferred] : [])].some(item => item.id === room.id)) return; selection.current = room; setSelected(room); setOpened(false); setError(null); }}>
        <Label language={language}>{room.name}</Label>
      </Pressable>)}
      {!busy && !roomError && !rooms.length && !preferred && <Label language={language}>{t('noRooms')}</Label>}
      {cursor !== null && rooms.length + (preferred && !rooms.some(item => item.id === preferred.id) ? 1 : 0) < 200 && <Button quiet title={t('loadMore')} busy={busy} onPress={() => void load(true, generation.current)} />}
      {rooms.length + (preferred && !rooms.some(item => item.id === preferred.id) ? 1 : 0) >= 200 && <Note text={t('roomsLimit')} language={language} />}
    </Sheet>}
  </View>;
}

/** Receipt sharing is independent from confirm, including automatic post-ACK sharing. */
export function ReceiptSharePanel({ engine, companyId, orderId, language, canSend, auto = false, roomId }: {
  engine: OrdersEngine; companyId: number; orderId: number; language: Language; canSend: boolean; auto?: boolean; roomId?: number | null;
}) {
  const t = orderTranslator(language), alive = useAlive();
  const presented = useContext(OrdersPresentation), visible = useRef(presented); visible.current = presented;
  const [originalRoom, setOriginalRoom] = useState<number | null>(null), [busy, setBusy] = useState(false), [shared, setShared] = useState(false);
  const [denied, setDenied] = useState(false), [error, setError] = useState<unknown>(null);
  const [detailReload, setDetailReload] = useState(0);
  const gate = useRef(false), autoStarted = useRef(false), revoked = useRef(false);
  const latest = useRef(canSend); latest.current = canSend;
  useEffect(() => {
    if (!canSend || !presented) return;
    if (roomId !== undefined) { setOriginalRoom(roomId); return; }
    let current = true;
    setError(null);
    void engine.detail(companyId, orderId).then(detail => { if (current && alive() && latest.current) setOriginalRoom(detail.order.room_id); })
      .catch(failure => { if (current && alive() && latest.current) setError(failure); });
    return () => { current = false; };
  }, [canSend, roomId, detailReload, presented]);
  const share = async () => {
    if (!alive() || !visible.current || !latest.current || !originalRoom || gate.current || revoked.current || shared) return;
    gate.current = true; setBusy(true); setError(null);
    try { await engine.share(companyId, orderId); if (alive() && latest.current) setShared(true); }
    catch (failure) { if (alive() && latest.current) {
      if (typeof failure === 'object' && failure !== null && (('status' in failure && failure.status === 403) || ('code' in failure && failure.code === 'forbidden'))) { revoked.current = true; setDenied(true); }
      setError(failure);
    } }
    finally { gate.current = false; if (alive()) setBusy(false); }
  };
  useEffect(() => {
    if (!presented || !auto || !originalRoom || !canSend || autoStarted.current) return;
    autoStarted.current = true; void share();
  }, [auto, originalRoom, canSend, presented]);
  return <View style={s.stack} testID="orders-receipt-share">
    <Note text={t(error ? 'receiptShareFailed' : 'shareNote')} language={language} warning={!!error} />
    <Button title={t(shared ? 'shared' : error ? 'retryShare' : 'shareReceipt')} busy={busy} disabled={!canSend || !originalRoom || denied || shared} onPress={() => void share()} />
    {(!canSend || !originalRoom) && <Note text={t('shareHelp')} language={language} />}
    {!!error && <Failure error={error} language={language} retry={!originalRoom && roomId === undefined ? () => setDetailReload(value => value + 1) : undefined} />}
  </View>;
}
