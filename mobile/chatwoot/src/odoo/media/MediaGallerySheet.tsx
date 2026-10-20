import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, AppState, Pressable, Text, View, type ViewToken } from 'react-native';
import { FlashList } from '@shopify/flash-list';
import { ChatError, type ChatEngine, type Message, type Room } from '../core/ChatEngine';
import { GALLERY_LIMITS, type GalleryKind, type GalleryOrder } from '../core/MediaGallery';
import { mediaOfflineState, setMediaOffline } from '../runtime';
import type { MediaOfflineState } from '../storage/MediaCacheContracts';
import { Button, colors, direction, Label, Sheet, styles } from '../ui/components';
import { MediaTile, useVoiceSession } from '../ui/MediaTools';
import { messageDateTime } from '../ui/viewModel';
import type { Language, Translate, Word } from '../ui/dictionary';
import { mediaTranslator, type MediaWord } from './dictionary';

function OfflineControl({ room, mediaId, scopeKey, language, visible }: {
  room: Room; mediaId: number; scopeKey: string; language: Language; visible: boolean;
}) {
  const mt = mediaTranslator(language), [value, setValue] = useState<MediaOfflineState | null>(null);
  const [busy, setBusy] = useState(false), [failed, setFailed] = useState(false);
  const owner = useRef({ key: '', active: false, working: false, serial: 0 });
  const key = `${scopeKey}/${mediaId}`;
  if (owner.current.key !== key) owner.current = { key, active: true, working: false, serial: 0 };
  useEffect(() => {
    const requested = owner.current; requested.active = true; const serial = ++requested.serial;
    if (visible && !requested.working) void mediaOfflineState(room, mediaId).then(result => {
      if (requested === owner.current && requested.serial === serial && requested.active) setValue(result);
    }).catch(() => undefined);
    return () => { requested.active = false; requested.serial++; };
  }, [key, visible]);
  return <View style={{ gap: 4 }}>
    {value?.kept && <Label language={language} muted>{mt(value.available ? 'kept' : 'missing')}</Label>}
    {failed && <Label language={language}>{mt('pinFailed')}</Label>}
    <Button quiet title={mt(value?.kept ? 'unkeep' : 'keep')} busy={busy} disabled={!visible || value === null || busy} onPress={() => {
      const requested = owner.current;
      if (requested.key !== key || !requested.active || requested.working || !value || AppState.currentState !== 'active') return;
      requested.working = true; const serial = ++requested.serial; setBusy(true); setFailed(false);
      const live = () => owner.current === requested && requested.serial === serial && requested.active && AppState.currentState === 'active';
      void setMediaOffline(room, mediaId, !value.kept).then(result => {
        if (live()) setValue(result);
      }).catch(() => { if (live()) setFailed(true); })
        .finally(() => {
          requested.working = false;
          if (owner.current !== requested || !requested.active || AppState.currentState !== 'active') return;
          setBusy(false);
          // A recycled row may have become visible again while the mutation ran.
          // Read fresh state instead of applying its obsolete completion.
          const refresh = ++requested.serial;
          void mediaOfflineState(room, mediaId).then(result => {
            if (owner.current === requested && requested.active && requested.serial === refresh) setValue(result);
          }).catch(() => undefined);
        });
    }} />
  </View>;
}

const viewabilityConfig = { minimumViewTime: 150, itemVisiblePercentThreshold: 10 };
export function MediaGallerySheet({ engine, room, scopeKey, language, t, close, onMessage }: {
  engine: ChatEngine; room: Room; scopeKey: string; language: Language; t: Translate;
  close(): void; onMessage(message: Message): Promise<void>;
}) {
  const mt = mediaTranslator(language), [kind, setKind] = useState<GalleryKind>('all'), [order, setOrder] = useState<GalleryOrder>('newest');
  const [rows, setRows] = useState<Message[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [cached, setCached] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<MediaWord | null>(null);
  const [mediaError, setMediaError] = useState<Word | null>(null), [visible, setVisible] = useState<Set<number>>(new Set());
  const key = JSON.stringify([scopeKey, room.company_id, room.id, room.membership_id, kind, order]);
  const owner = useRef({ key, active: true, serial: 0, working: false });
  if (owner.current.key !== key) owner.current = { key, active: AppState.currentState === 'active', serial: 0, working: false };
  const voice = useVoiceSession(key, setMediaError, true, false);
  const fetchPage = async (next?: string) => {
    const requested = owner.current;
    if (requested.key !== key || !requested.active || requested.working || AppState.currentState !== 'active') return;
    requested.working = true; const serial = ++requested.serial; setBusy(true); setError(null);
    const live = () => owner.current === requested && requested.active && requested.serial === serial && AppState.currentState === 'active';
    try {
      const page = await engine.mediaGallery(room, { kind, order, ...(next ? { cursor: next } : {}) });
      if (!live()) return;
      if (next && page.next_cursor === next) throw new ChatError('invalid_gallery');
      setRows(old => {
        const combined = next ? [...old, ...page.items] : page.items;
        return [...new Map(combined.map(item => [item.id, item])).values()].slice(-GALLERY_LIMITS.associations);
      });
      setCursor(page.next_cursor); setCached(page.cached === true);
    } catch (failure) {
      if (live()) {
        const denied = failure instanceof ChatError && (failure.status === 401 || failure.status === 403);
        if (denied) { setRows([]); setCursor(null); }
        setError(denied ? 'forbidden' : failure instanceof ChatError && failure.code === 'gallery_offline' ? 'unavailable' : 'failed');
      }
    } finally { requested.working = false; if (live()) setBusy(false); }
  };
  useEffect(() => {
    const requested = owner.current; requested.active = AppState.currentState === 'active';
    setRows([]); setCursor(null); setVisible(new Set()); setMediaError(null); void fetchPage();
    const listener = AppState.addEventListener('change', state => { if (state !== 'active') { requested.active = false; requested.serial++; close(); } });
    return () => { requested.active = false; requested.serial++; listener.remove(); };
    // Scope/filter changes invalidate every result and protected media component.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const choose = (value: GalleryKind | GalleryOrder, sorting = false) => {
    if (busy || owner.current.key !== key || !owner.current.active) return;
    if (sorting) setOrder(value as GalleryOrder); else setKind(value as GalleryKind);
  };
  return <Sheet title={mt('gallery')} close={close} language={language} t={t} compact scroll={false} style={{ height: '92%' }}>
    <View style={{ flexDirection: language === 'ar' ? 'row-reverse' : 'row', flexWrap: 'wrap', gap: 4, paddingVertical: 6 }}>
      {(['all', 'image', 'file', 'audio'] as GalleryKind[]).map(value => <Choice key={value} title={mt(value)} selected={kind === value} language={language} disabled={busy} press={() => choose(value)} />)}
    </View>
    <View style={{ flexDirection: language === 'ar' ? 'row-reverse' : 'row', flexWrap: 'wrap', gap: 4, paddingBottom: 8 }}>
      {(['newest', 'oldest', 'largest'] as GalleryOrder[]).map(value => <Choice key={value} title={mt(value)} selected={order === value} language={language} disabled={busy} press={() => choose(value, true)} />)}
    </View>
    {cached && <Label language={language} muted>{mt('cached')}</Label>}
    {error && <Label language={language}>{mt(error)}</Label>}
    {mediaError && <Label language={language}>{t(mediaError)}</Label>}
    <FlashList key={key} data={rows} keyExtractor={item => String(item.id)}
      viewabilityConfig={viewabilityConfig}
      onViewableItemsChanged={({ viewableItems }: { viewableItems: ViewToken[] }) => {
        if (owner.current.key === key && owner.current.active) setVisible(new Set(viewableItems.filter(item => item.isViewable).map(item => (item.item as Message).id)));
      }}
      contentContainerStyle={{ paddingBottom: 12 }}
      ListEmptyComponent={!busy && !error ? <Label language={language} muted>{mt('empty')}</Label> : null}
      renderItem={({ item }) => <View style={{ borderRadius: 12, backgroundColor: colors.pale, padding: 10, marginBottom: 8, gap: 6 }}>
        <Label language={language}>{item.author_name}</Label>
        <Text style={[styles.muted, direction(language)]}>{messageDateTime(item.created_at)} · {String(item.media?.size_label ?? '')}</Text>
        <MediaTile key={`${key}/${item.id}`} room={room} media={item.media!} voice={voice} t={t} language={language} report={setMediaError}
          scopeKey={key} previewVisible={visible.has(item.id)} senderName={item.author_name} senderUserId={item.author_user_id} />
        <OfflineControl key={`${key}/pin/${item.id}`} room={room} mediaId={Number(item.media!.id)} scopeKey={key} language={language} visible={visible.has(item.id)} />
        <Button quiet title={mt('message')} disabled={busy} onPress={() => {
          const requested = owner.current;
          if (requested.key !== key || !requested.active || requested.working || AppState.currentState !== 'active') return;
          requested.working = true; setBusy(true);
          void onMessage(item).catch(() => { if (requested === owner.current && requested.active) setError('failed'); })
            .finally(() => { requested.working = false; if (requested === owner.current && requested.active) setBusy(false); });
        }} />
      </View>}
      ListFooterComponent={<View style={{ gap: 6 }}>
        {busy && <ActivityIndicator color={colors.blue} accessibilityLabel={t('loading')} />}
        {!busy && (error || cursor) && <Button quiet title={mt(error ? 'refresh' : 'more')} onPress={() => void fetchPage(error ? undefined : cursor!)} />}
      </View>} />
  </Sheet>;
}
function Choice({ title, selected, disabled, language, press }: { title: string; selected: boolean; disabled: boolean; language: Language; press(): void }) {
  return <Pressable accessibilityRole="button" accessibilityState={{ selected, disabled }} disabled={disabled} onPress={press}
    style={{ minHeight: 44, justifyContent: 'center', paddingHorizontal: 12, borderRadius: 10, backgroundColor: selected ? colors.blue : colors.pale }}>
    <Text style={[styles.text, direction(language), { color: selected ? colors.white : colors.ink }]}>{title}</Text>
  </Pressable>;
}
