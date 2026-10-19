import React, { useEffect, useRef, useState } from 'react';
import { ScrollView, Text, View, useWindowDimensions } from 'react-native';
import type { Room } from '../../core/ChatEngine';
import { Button, colors, direction, Field, Icon, IconButton, Label } from '../../ui/components';
import type { Language } from '../../ui/dictionary';
import type { OrdersEngine } from '../core/OrdersEngine';
import type { CatalogItem, CreateResult, OrdersOptions, PurchaseRoute, QuoteResult } from '../core/types';
import { displayNumber, orderTranslator } from '../dictionary';
import { Busy, Choice, Empty, Failure, Heading, KeyValue, Note, NumberText, ordersStyles as s, rowDirection, useAlive } from './OrdersPrimitives';

interface CartItem { item: CatalogItem; quantity: string }
export const validQuantity = (text: string) => /^(?:[1-9][0-9]{0,5}|0)(?:\.[0-9]{1,2})?$/.test(text) && Number(text) > 0;
/** Change whole units only; preserve the user's fractional digits without decimal arithmetic. */
export function stepQuantity(text: string, step: 1 | -1): string {
  if (!validQuantity(text)) return text;
  const [whole, fraction] = text.split('.');
  if (step === 1 && whole === '999999') return text;
  if (step === -1 && whole === '0') return '0';
  // Six-digit whole quantities are exact integers; the fractional string is never parsed.
  const nextWhole = String(Number(whole) + step);
  if (nextWhole === '0' && (fraction === undefined || /^0+$/.test(fraction))) return '0';
  return fraction === undefined ? nextWhole : `${nextWhole}.${fraction}`;
}

export function OrderComposer({ engine, companyId, language, rooms, onResult, onPending, blocked, header }: {
  engine: OrdersEngine; companyId: number; language: Language; rooms: Room[]; onResult: (result: CreateResult) => void; onPending: () => Promise<void>; blocked: boolean;
  header?: React.ReactNode;
}) {
  const t = orderTranslator(language), alive = useAlive();
  const width = useWindowDimensions().width;
  const [options, setOptions] = useState<OrdersOptions | null>(null), [items, setItems] = useState<CatalogItem[]>([]);
  const [cursor, setCursor] = useState<number | null>(null), [search, setSearch] = useState(''), [category, setCategory] = useState(0);
  const [warehouse, setWarehouse] = useState(0), [representative, setRepresentative] = useState(0);
  const [route, setRoute] = useState<PurchaseRoute | null>(null), [roomId, setRoomId] = useState(0);
  const [cart, setCart] = useState<CartItem[]>([]), [removed, setRemoved] = useState<CartItem | null>(null);
  const cartRef = useRef<CartItem[]>([]), revision = useRef(0), catalogGeneration = useRef(0), quoteGeneration = useRef(0);
  const [quote, setQuote] = useState<QuoteResult | null>(null), [page, setPage] = useState<'catalog' | 'cart' | 'review'>('catalog');
  const [loading, setLoading] = useState(false), [optionBusy, setOptionBusy] = useState(false), [quoting, setQuoting] = useState(false), [writing, setWriting] = useState(false);
  const [error, setError] = useState<unknown>(null), [catalogError, setCatalogError] = useState<unknown>(null);
  const [writeUnknown, setWriteUnknown] = useState(false), [invalid, setInvalid] = useState(false), [reload, setReload] = useState(0);
  const writeGate = useRef(false), optionGate = useRef(false), catalogGate = useRef(false);
  const latest = useRef({ rooms, blocked }); latest.current = { rooms, blocked };
  const invalidate = () => { engine.invalidateQuote(); quoteGeneration.current++; revision.current++; setQuote(null); setInvalid(false); };
  const updateCart = (next: CartItem[]) => { if (!alive() || writeGate.current) return; invalidate(); cartRef.current = next; setCart(next); };
  useEffect(() => {
    let current = true; setOptionBusy(true); optionGate.current = true;
    void engine.options(companyId).then(next => {
      if (!current || !alive()) return;
      setOptions(next);
      setWarehouse(next.warehouses?.find(item => item.id === next.default_warehouse_id)?.id ?? next.warehouses?.[0]?.id ?? 0);
      setRepresentative(next.representatives?.[0]?.id ?? 0);
      setRoute(next.purchase_routes?.[0]?.code ?? null);
    }).catch(failure => { if (current && alive()) setError(failure); }).finally(() => { optionGate.current = false; if (current && alive()) setOptionBusy(false); });
    return () => { current = false; engine.invalidateQuote(); };
  }, [reload]);
  const loadCatalog = async (more: boolean, request: number) => {
    if (!alive() || (more && (catalogGate.current || cursor === null || items.length >= 200))) return;
    catalogGate.current = true; setLoading(true); setCatalogError(null);
    try {
      const next = await engine.catalog(companyId, { q: search.trim(), ...(category ? { categoryId: category } : {}), ...(more ? { afterId: cursor! } : {}) });
      if (!alive() || request !== catalogGeneration.current) return;
      setItems(previous => (more ? [...previous, ...next.items] : next.items).filter((item, index, list) => list.findIndex(other => other.id === item.id) === index).slice(0, 200));
      setCursor(next.next_after_id);
    } catch (failure) { if (alive() && request === catalogGeneration.current) setCatalogError(failure); }
    finally { if (request === catalogGeneration.current) { catalogGate.current = false; if (alive()) setLoading(false); } }
  };
  useEffect(() => {
    const request = ++catalogGeneration.current; catalogGate.current = false; setItems([]); setCursor(null); setLoading(true);
    // No automatic POST retries: this timer only coalesces deliberate catalog input changes.
    const timer = setTimeout(() => { void loadCatalog(false, request); }, 350);
    return () => { clearTimeout(timer); catalogGeneration.current++; };
  }, [search, category, reload]);
  const changeQuantity = (item: CatalogItem, quantity: string) => {
    const current = cartRef.current, existing = current.find(line => line.item.id === item.id);
    if (existing?.quantity === quantity) return;
    if (!existing && current.length >= 100) { setError({ code: 'cart_limit' }); return; }
    if (/^0(?:\.0{1,2})?$/.test(quantity)) { if (existing) { setRemoved(existing); updateCart(current.filter(line => line.item.id !== item.id)); } return; }
    updateCart(existing ? current.map(line => line.item.id === item.id ? { ...line, quantity } : line) : [...current, { item, quantity }]);
  };
  const validCart = cart.length > 0 && cart.every(line => validQuantity(line.quantity));
  const selectionValid = !!warehouse && !!route && !!options?.warehouses?.some(item => item.id === warehouse)
    && !!options?.purchase_routes?.some(item => item.code === route)
    && (route !== 'representative' || !!options?.representatives?.some(item => item.id === representative))
    && (!roomId || rooms.some(room => room.id === roomId && room.company_id === companyId && room.membership_id > 0));
  const quoteValid = !!quote && quote.company_id === companyId && quote.cart_revision === revision.current && validCart;
  const getQuote = async () => {
    if (!alive() || !validCart || !warehouse || quoting || writeGate.current) return;
    const request = ++quoteGeneration.current, cartRevision = revision.current;
    setQuoting(true); setError(null);
    try {
      const result = await engine.quote({ company_id: companyId, warehouse_id: warehouse, cart_revision: cartRevision, lines: cartRef.current.map(line => ({ option_id: line.item.id, quantity: line.quantity })) });
      if (alive() && request === quoteGeneration.current && cartRevision === revision.current) setQuote(result);
    } catch (failure) { if (alive() && request === quoteGeneration.current) setError(failure); }
    finally { if (alive()) setQuoting(false); }
  };
  const submit = async () => {
    if (!alive() || writeGate.current || latest.current.blocked || writeUnknown || page !== 'review' || !quoteValid || !selectionValid || !route) return;
    if (roomId && !latest.current.rooms.some(room => room.id === roomId && room.company_id === companyId && room.membership_id > 0)) return;
    writeGate.current = true; setWriting(true); setError(null);
    try {
      const result = await engine.create({ company_id: companyId, warehouse_id: warehouse, representative_partner_id: route === 'representative' ? representative : null,
        purchase_route: route, ...(roomId ? { room_id: roomId } : {}), lines: cartRef.current.map(line => ({ option_id: line.item.id, quantity: line.quantity })) });
      if (alive()) { cartRef.current = []; setCart([]); onResult(result); }
    } catch (failure) {
      if (alive()) { setError(failure); if (typeof failure === 'object' && failure !== null && 'code' in failure && failure.code === 'unknown') setWriteUnknown(true); await onPending(); }
    } finally { writeGate.current = false; if (alive()) setWriting(false); }
  };
  const rows = (showCart: boolean, review = false) => {
    const source = showCart ? cart.map(line => line.item) : items;
    return <View style={[s.row, { alignItems: 'stretch' }]}>{source.map(item => {
      const line = cart.find(row => row.item.id === item.id);
      return <View key={item.id} testID={`catalog-option-${item.id}`} style={[s.card, { width: !showCart && width >= 650 ? '48.8%' : '100%' }]}>
        <View style={[s.row, rowDirection(language), { alignItems: 'flex-start' }]}>
          <View style={{ width: 36, minHeight: 44, borderRadius: 8, backgroundColor: colors.pale, alignItems: 'center', justifyContent: 'center' }}><Icon icon="file" size={20} color={colors.blue} /></View>
          <View style={s.flexible}><Text style={[s.strong, direction(language)]}>{item.product_name}</Text><Label muted language={language}>{item.option_name} · {item.uom_name}</Label>
            {!!item.packaging_note && <Label muted language={language}>{item.packaging_note}</Label>}
          </View>
        </View>
        {!review && <KeyValue language={language} label={t('lastPrice')}><NumberText value={item.last_price} suffix={item.currency_symbol} /></KeyValue>}
        {review ? <KeyValue language={language} label={t('quantity')}><NumberText value={line?.quantity} /></KeyValue>
          : line ? <View style={[s.row, rowDirection(language)]}>
            <IconButton icon="trash" label={`${t('remove')} ${item.product_name} ${item.option_name}`} disabled={writing} onPress={() => changeQuantity(item, '0')} />
            <Button quiet title="−" accessibilityLabel={`${t('quantity')} − ${item.product_name} ${item.option_name}`} busy={false} disabled={writing} onPress={() => changeQuantity(item, stepQuantity(line.quantity, -1))} />
            <Field language={language} testID={`cart-quantity-${item.id}`} accessibilityLabel={`${t('quantity')} ${item.product_name} ${item.option_name}`}
              value={line.quantity} onChangeText={text => changeQuantity(item, displayNumber(text).replace('٫', '.'))} keyboardType="decimal-pad" maxLength={9} editable={!writing}
              style={{ flex: 1, minWidth: 72, minHeight: 44, textAlign: 'center', writingDirection: 'ltr' }} />
            <IconButton icon="plus" label={`${t('add')} ${item.product_name} ${item.option_name}`} disabled={writing} onPress={() => changeQuantity(item, stepQuantity(line.quantity, 1))} />
          </View>
            : <Button quiet title={t('add')} accessibilityLabel={`${t('add')} ${item.product_name} ${item.option_name}`} onPress={() => changeQuantity(item, '1')} busy={false} disabled={cart.length >= 100 || writing} />}
      </View>;
    })}</View>;
  };
  return <View style={s.fill} testID="orders-composer">
    <ScrollView testID="orders-composer-body" style={{ flex: 1, minHeight: 0 }} keyboardShouldPersistTaps="handled" contentContainerStyle={[s.content, { paddingBottom: 24 }]}>
    {header}
    <View style={s.stack}>
    {optionBusy && !options && <Busy language={language} />}
    {page !== 'catalog' && <Button quiet title={t('back')} busy={false} disabled={writing} onPress={() => { setPage(page === 'review' ? 'cart' : 'catalog'); setError(null); }} />}
    {page !== 'catalog' && <Heading language={language} word={page === 'review' ? 'reviewOrder' : 'cart'} />}
      {!!error && (typeof error === 'object' && error !== null && 'code' in error && error.code === 'cart_limit'
        ? <Note text={t('cartLimit')} language={language} warning />
        : <Failure error={error} language={language} retry={!options ? () => setReload(value => value + 1) : undefined} />)}
    {cart.length >= 100 && <Note text={t('cartLimit')} language={language} />}
    {(blocked || writeUnknown) && <Note text={t('pendingBlock')} language={language} warning />}
    <Choice label={t('warehouse')} testID="orders-warehouse" options={options?.warehouses ?? []} value={warehouse} language={language} disabled={writing || page === 'review'}
      onSelect={id => { invalidate(); setWarehouse(id); }} />
    {page === 'catalog' ? <>
      <Label language={language} muted>{t('search')}</Label><Field language={language} testID="catalog-search" accessibilityLabel={t('search')} placeholder={t('searchHint')} value={search} onChangeText={setSearch} maxLength={80} />
      <Choice label={t('all')} testID="catalog-category" options={[{ id: 0, name: t('all') }, ...(options?.categories ?? [])]} value={category} onSelect={setCategory} language={language} />
      {!!catalogError && <Failure error={catalogError} language={language} retry={() => void loadCatalog(false, ++catalogGeneration.current)} />}
      {rows(false)}{loading && <Busy language={language} />}
      {!loading && !catalogError && !items.length && <Empty title={t('noResults')} help={t('noResultsHelp')} language={language} />}
      {cursor !== null && items.length < 200 && <Button title={t('loadMore')} quiet onPress={() => void loadCatalog(true, catalogGeneration.current)} busy={false} disabled={loading} />}
      <Note text={t('estimateNote')} language={language} />
    </> : !cart.length ? <Empty title={t('cartEmpty')} help={t('cartEmptyHelp')} language={language} /> : <>
      {rows(true, page === 'review')}
      {removed && page === 'cart' && <Button quiet title={t('undo')} busy={false} disabled={cart.length >= 100 || writing} onPress={() => { if (!cartRef.current.some(line => line.item.id === removed.item.id) && cartRef.current.length < 100) updateCart([...cartRef.current, removed]); setRemoved(null); }} />}
      {page === 'cart' ? <>
        <Label language={language} muted>{t('method')}</Label>
        <View style={[s.row, rowDirection(language)]}>{(options?.purchase_routes ?? []).map(item => <Button key={item.code} title={t(item.code)} quiet={route !== item.code} busy={false} disabled={writing}
          onPress={() => { setRoute(item.code); invalidate(); }} />)}</View>
        {route === 'representative' && <Choice label={t('representativeLabel')} testID="orders-representative" options={options?.representatives ?? []} value={representative} onSelect={setRepresentative} language={language} disabled={writing} />}
        <Note text={t('routeNote')} language={language} />
        <Choice label={t('conversation')} testID="orders-room" value={roomId} onSelect={setRoomId} language={language} disabled={writing}
          options={[{ id: 0, name: t('none') }, ...rooms.filter(room => room.company_id === companyId && room.membership_id > 0).map(room => ({ id: room.id, name: room.name }))]} />
      </> : <View style={s.card}>
        <KeyValue label={t('method')} language={language}><Label language={language}>{route ? t(route) : ''}</Label></KeyValue>
        {route === 'representative' && <KeyValue label={t('representativeLabel')} language={language}><Label language={language}>{options?.representatives?.find(item => item.id === representative)?.name}</Label></KeyValue>}
        <KeyValue label={t('conversation')} language={language}><Label language={language}>{rooms.find(room => room.id === roomId)?.name ?? t('none')}</Label></KeyValue>
      </View>}
      {!roomId && <Note text={t('noRoomNote')} language={language} />}
      <Note text={t('estimateNote')} language={language} />
      {!validCart && <Note text={t('quantityValidation')} language={language} warning />}
      {invalid && !selectionValid && <Note text={t('missingSelection')} language={language} warning />}
      <View style={s.card}><KeyValue label={t('estimated')} language={language}>{quoteValid ? <NumberText value={quote!.estimated_total} suffix={quote!.currency_symbol} /> : <Label language={language}>{t('pendingQuote')}</Label>}</KeyValue></View>
      {!quoteValid && <><Note text={t('quoteRequired')} language={language} warning /><Button title={t('quote')} busy={quoting} disabled={!validCart || !warehouse || writing} onPress={() => void getQuote()} /></>}
      <Button title={t(page === 'review' ? 'sendOrder' : 'reviewOrder')} busy={writing} disabled={!validCart || !quoteValid || blocked || writeUnknown || quoting || (page === 'review' && !selectionValid)}
        onPress={() => { if (!alive()) return; if (page === 'review') void submit(); else { setInvalid(true); if (selectionValid) setPage('review'); } }} />
    </>}
    </View>
    </ScrollView>
    {page === 'catalog' && <View testID="orders-catalog-footer" style={[s.footer, { width: '100%', maxWidth: 940, alignSelf: 'center', flexShrink: 0 }]}>
      <KeyValue language={language} label={t('estimated')}>{quoteValid ? <NumberText value={quote!.estimated_total} suffix={quote!.currency_symbol} /> : <Label language={language} muted>{t('pendingQuote')}</Label>}</KeyValue>
      <Button title={`${t('reviewCart')} (${cart.length})`} busy={false} onPress={() => { if (alive()) setPage('cart'); }}
        disabled={!cart.length || loading || optionBusy || !options || blocked || writeUnknown || writing} />
    </View>}
  </View>;
}
