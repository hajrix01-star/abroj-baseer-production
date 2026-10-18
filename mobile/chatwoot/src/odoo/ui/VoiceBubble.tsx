import React, { useEffect, useRef, useState } from 'react';
import { AppState, Image, NativeModules, Text, View, type GestureResponderEvent } from 'react-native';
import type { Room } from '../core/ChatEngine';
import { clearMemberAvatars, localMediaLease, readMemberAvatar, type LocalMediaLease } from '../runtime';
import { colors, Icon, IconButton } from './components';
import { errorWord, type Language, type Translate, type Word } from './dictionary';
import type { VoiceSession } from './MediaTools';

type Envelope = { durationMs: number; peaks: number[] };
let nextAnalysis = 0;
export const audioTime = (milliseconds: number) => {
  const seconds = Number.isFinite(milliseconds) ? Math.max(0, Math.floor(milliseconds / 1000)) : 0;
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
};
export function validEnvelope(value: unknown): value is Envelope {
  const item = value as Envelope | null;
  return !!item && Number.isFinite(item.durationMs) && item.durationMs > 0 && item.durationMs <= 600000 && Array.isArray(item.peaks)
    && item.peaks.length === 40 && item.peaks.every(peak => Number.isFinite(peak) && peak >= 0 && peak <= 1);
}

/** Local audio controls. A neutral rail means unknown waveform, not fake audio. */
export function VoiceBubble({ room, media, voice, t, language, report, scopeKey, visible, senderName, senderUserId }: {
  room: Room; media: Record<string, unknown>; voice: VoiceSession; t: Translate; language: Language;
  report: (word: Word) => void; scopeKey: string; visible: boolean; senderName: string; senderUserId?: number;
}) {
  const token = JSON.stringify([scopeKey, room.company_id, room.id, room.membership_id, media.id, media.sha256, media.size, senderUserId]);
  const [local, setLocal] = useState<{ token: string; uri: string; envelope: Envelope | null } | null>(null);
  const [avatar, setAvatar] = useState<{ token: string; uri: string } | null>(null);
  const [busyToken, setBusyToken] = useState<string | null>(null);
  const [foreground, setForeground] = useState(AppState.currentState === 'active');
  const live = useRef({ token, revision: 0, alive: true, busy: false });
  if (live.current.token !== token) live.current = { token, revision: live.current.revision + 1, alive: true, busy: false };
  const revision = live.current.revision;
  const analysis = useRef<string | null>(null);
  const width = useRef(1);
  const [scrub, setScrub] = useState<number | null>(null);
  const [clock, setClock] = useState<{ token: string; uri: string | null; positionMs: number; durationMs: number } | null>(null);
  const current = () => live.current.alive && live.current.token === token && live.current.revision === revision && AppState.currentState === 'active';
  const analyze = async (uri: string) => {
    if (!NativeModules.BWorkWaveform?.analyze || !current()) return;
    const id = `wave-${Date.now()}-${++nextAnalysis}`;
    analysis.current && NativeModules.BWorkWaveform.cancel(analysis.current);
    analysis.current = id;
    try {
      const result: unknown = await NativeModules.BWorkWaveform.analyze(uri, id);
      if (current() && analysis.current === id && validEnvelope(result)) setLocal({ token, uri, envelope: result });
    } catch { /* Unsupported/long audio still plays; never display invented/partial peaks. */ }
    finally { if (analysis.current === id) analysis.current = null; }
  };
  useEffect(() => {
    live.current.alive = true;
    const listener = AppState.addEventListener('change', state => {
      if (state !== 'active') {
        live.current.revision++; live.current.busy = false;
        if (analysis.current) NativeModules.BWorkWaveform?.cancel(analysis.current);
        analysis.current = null; clearMemberAvatars(); setLocal(null); setAvatar(null); setBusyToken(null); setScrub(null);
      }
      setForeground(state === 'active');
    });
    return () => {
      if (live.current.token === token) { live.current.alive = false; live.current.revision++; }
      listener.remove();
      if (analysis.current) NativeModules.BWorkWaveform?.cancel(analysis.current);
      analysis.current = null;
    };
  }, [token]);
  useEffect(() => {
    if (!visible || !foreground) return;
    let cancelled = false;
    let lease: LocalMediaLease | null = null;
    void (async () => {
      try {
        lease = await localMediaLease(room, media, 'original', true);
        if (cancelled || !current()) return;
        const retained = local?.token === token && local.uri === lease.uri ? local.envelope : null;
        setLocal({ token, uri: lease.uri, envelope: retained });
        if (!retained) await analyze(lease.uri);
      } catch { /* A viewport never downloads audio. */ }
      finally { lease?.release(); }
    })();
    if (senderUserId) void readMemberAvatar(room, senderUserId).then(uri => { if (!cancelled && current()) setAvatar({ token, uri }); }).catch(() => undefined);
    return () => { cancelled = true; if (analysis.current) NativeModules.BWorkWaveform?.cancel(analysis.current); analysis.current = null; };
    // Descriptor/scope identity is encoded in token; history repaint is not a download/analysis trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, visible, foreground, revision]);
  const uri = local?.token === token && foreground ? local.uri : null;
  const active = !!uri && voice.activeUri === uri;
  useEffect(() => {
    if (!active || !voice.progress) return;
    const update = () => {
      const value = voice.progress.snapshot();
      if (current() && value.uri === uri) setClock({ token, ...value });
    };
    update(); return voice.progress.subscribe(update);
    // Only the active row subscribes to playback progress, never the Timeline.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, active, voice.progress]);
  const activeClock = clock?.token === token && clock.uri === uri ? clock : null;
  const envelope = local?.token === token && foreground ? local.envelope : null;
  const nativeDuration = activeClock?.durationMs ?? voice.durationMs;
  const duration = active && nativeDuration > 0 ? nativeDuration : envelope?.durationMs ?? 0;
  const position = active ? activeClock?.positionMs ?? voice.positionMs : 0;
  const progress = scrub ?? (duration > 0 ? Math.max(0, Math.min(1, position / duration)) : 0);
  const busy = busyToken === token;
  const play = async () => {
    if (!current() || live.current.busy) return;
    if (active && voice.playing) { await voice.pause(); return; }
    if (active && voice.paused) { await voice.resume(); return; }
    live.current.busy = true; setBusyToken(token);
    let lease: LocalMediaLease | null = null;
    try {
      lease = await localMediaLease(room, media, 'original');
      if (!current()) { lease.release(); return; }
      const localUri = lease.uri;
      setLocal({ token, uri: localUri, envelope });
      // The player owns a distinct lease. Waveform work only starts under a
      // second scoped lease, so stopping/recycling cannot expose unpinned bytes.
      const playerLease = lease; lease = null;
      await voice.play(localUri, playerLease.release);
      if (current()) { live.current.busy = false; setBusyToken(null); }
      if (current() && !envelope) {
        lease = await localMediaLease(room, media, 'original', true);
        if (current()) await analyze(lease.uri);
      }
    } catch (error) { if (current()) report(errorWord(error)); }
    finally { lease?.release(); if (current()) { live.current.busy = false; setBusyToken(null); } }
  };
  const fraction = (event: GestureResponderEvent) => Math.max(0, Math.min(1, event.nativeEvent.locationX / width.current));
  const seekable = active && duration > 0;
  return <View accessibilityLabel={t('voiceMessage')} style={{ width: 240, maxWidth: '100%', minHeight: 60, flexDirection: language === 'ar' ? 'row-reverse' : 'row', direction: 'ltr', alignItems: 'center', gap: 6 }}>
    <IconButton icon={active && voice.playing ? 'pause' : 'play'} label={active && voice.playing ? t('pause') : active && voice.paused ? t('resume') : t('play')} size={24} busy={busy} onPress={() => { void play(); }} style={{ width: 44, height: 44, borderRadius: 22 }} />
    <View style={{ flex: 1, minWidth: 0 }}>
      <View accessible accessibilityRole="adjustable" accessibilityLabel={t('seekAudio')} accessibilityState={{ disabled: !seekable }} accessibilityValue={{ min: 0, max: Math.round(duration / 1000), now: Math.round(position / 1000), text: `${audioTime(position)} / ${audioTime(duration)}` }}
        accessibilityActions={seekable ? [{ name: 'increment' }, { name: 'decrement' }] : []}
        onAccessibilityAction={event => { if (seekable) void voice.seek(position + (event.nativeEvent.actionName === 'increment' ? 5000 : -5000)); }}
        onLayout={event => { width.current = Math.max(1, event.nativeEvent.layout.width); }}
        onStartShouldSetResponder={() => seekable}
        onResponderGrant={event => setScrub(fraction(event))}
        onResponderMove={event => setScrub(fraction(event))}
        onResponderRelease={event => { if (seekable) void voice.seek(fraction(event) * duration); setScrub(null); }}
        onResponderTerminate={() => setScrub(null)}
        style={{ height: 44, justifyContent: 'center' }}>
        {envelope ? <View pointerEvents="none" style={{ height: 28, flexDirection: 'row', alignItems: 'center', gap: 1 }}>
          {envelope.peaks.map((peak, index) => <View key={index} style={{ flex: 1, minWidth: 1, height: Math.max(2, Math.sqrt(peak) * 28), borderRadius: 2, backgroundColor: index / 40 < progress ? colors.blue : colors.muted, opacity: index / 40 < progress ? 1 : 0.45 }} />)}
        </View> : <View pointerEvents="none" style={{ height: 3, borderRadius: 2, backgroundColor: colors.border }}><View style={{ height: 3, width: `${progress * 100}%`, backgroundColor: colors.blue }} /></View>}
        {seekable && <View pointerEvents="none" style={{ position: 'absolute', left: `${progress * 100}%`, marginLeft: -4, width: 8, height: 8, borderRadius: 4, backgroundColor: colors.blue }} />}
      </View>
      <Text style={{ fontSize: 11, lineHeight: 14, color: colors.muted, writingDirection: 'ltr', textAlign: 'left' }}>{duration > 0 ? `${audioTime(active ? position : duration)}${active ? ` / ${audioTime(duration)}` : ''}` : '—:—'}</Text>
    </View>
    <View accessible={false} style={{ width: 36, height: 36, borderRadius: 18, backgroundColor: colors.pale, alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      {avatar?.token === token && foreground ? <Image accessible={false} source={{ uri: avatar.uri }} onError={() => setAvatar(null)} resizeMode="cover" style={{ width: 36, height: 36, borderRadius: 18 }} /> : <Text accessible={false} style={{ color: colors.blue, fontSize: 17, fontWeight: '600' }}>{Array.from(senderName.trim())[0] ?? ''}</Text>}
      <View style={{ position: 'absolute', bottom: -3, right: -3, width: 18, height: 18, borderRadius: 9, backgroundColor: colors.chatSent, alignItems: 'center', justifyContent: 'center' }}><Icon icon="mic" size={14} color={colors.blue} /></View>
    </View>
  </View>;
}
