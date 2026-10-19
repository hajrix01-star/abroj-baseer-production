import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import NetInfo from '@react-native-community/netinfo';
import type { Bootstrap, ChatEngine, History, Pending, Room } from '../core/ChatEngine';
import { errorWord, type Word } from './dictionary';
import {
  createMessageSounds,
  soundActor,
  soundRoom,
  type MessageSounds,
  type SoundState,
} from './messageSounds';

const emptyHistory: History = { api_version: 2, messages: [], next_before_id: null };
export function useChat(engine: ChatEngine) {
  const [identity, setIdentity] = useState<Bootstrap | null>(null);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [selected, setSelected] = useState<Room | null>(null);
  const [history, setHistory] = useState<History>(emptyHistory);
  const [pending, setPending] = useState<Pending[]>([]);
  const [error, setError] = useState<Word | null>(null);
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(true);
  const [presentationReady, setPresentationReady] = useState(false);
  // Retained pixels are not authority. A same-account, TTL-valid snapshot may
  // remain visible while foreground authority is being checked again.
  const [displayReady, setDisplayReady] = useState(false);
  const [foreground, setForeground] = useState(AppState.currentState === 'active');
  const displayedScope = useRef<string | null>(null);
  const retainedAllowed = useRef(false);
  const [soundState, setSoundState] = useState<SoundState>({
    actor: '',
    ready: false,
    enabled: false,
  });
  const sounds = useRef<MessageSounds | null>(null);
  if (!sounds.current) sounds.current = createMessageSounds(setSoundState);
  const soundBaselineReady = useRef(false);
  const soundEpoch = useRef(0);
  const presentation = useRef(presentationReady);
  presentation.current = presentationReady;
  const selectedRef = useRef<Room | null>(null);
  const active = useRef(AppState.currentState === 'active');
  const online = useRef(true);
  const generation = useRef(0);
  const pollBusy = useRef(false);
  const mounted = useRef(true);
  const foregroundEpoch = useRef(0);
  const displayScope = () => engine.identity ? `${engine.accountScope ?? ''}/${soundActor(engine.identity)}` : null;
  const reveal = () => {
    if (!mounted.current) return;
    try { engine.rooms(); } catch {
      presentation.current = false; retainedAllowed.current = false;
      setDisplayReady(false); setPresentationReady(false); return;
    }
    presentation.current = true;
    retainedAllowed.current = true;
    displayedScope.current = displayScope();
    setPresentationReady(true);
    setDisplayReady(!!displayedScope.current && active.current);
  };
  const capture = useCallback(() => {
    if (!mounted.current) return;
    let rows: Room[] = [];
    let queue: Pending[] = [];
    let readable = false;
    try {
      rows = engine.rooms();
      queue = engine.pending();
      readable = true;
    } catch {
      /* TTL/identity blocks display. */
    }
    const account = engine.status === 'offline_expired' ? null : engine.identity;
    const scope = account ? `${engine.accountScope ?? ''}/${soundActor(account)}` : null;
    const leased = presentation.current || (Number.isFinite(engine.leaseRemainingMs) && engine.leaseRemainingMs > 0);
    setDisplayReady(active.current && retainedAllowed.current && leased && readable && !!scope && scope === displayedScope.current);
    sounds.current!.account(soundActor(account));
    if (engine.status === 'offline_expired') setError('expired');
    setIdentity(account);
    setRooms(rows);
    setPending(queue);
    setOffline(engine.offline || !online.current);
    const old = selectedRef.current;
    if (
      old &&
      !rows.some(
        r =>
          r.id === old.id &&
          r.membership_id === old.membership_id &&
          r.company_id === old.company_id,
      )
    ) {
      selectedRef.current = null;
      setSelected(null);
      setHistory(emptyHistory);
      soundBaselineReady.current = false;
      sounds.current!.reset();
    } else if (old) {
      const fresh = rows.find(
        r =>
          r.id === old.id &&
          r.company_id === old.company_id &&
          r.membership_id === old.membership_id,
      );
      if (fresh && (fresh.name !== old.name || fresh.avatar_version !== old.avatar_version)) {
        selectedRef.current = fresh;
        setSelected(fresh);
      }
    }
  }, [engine]);
  const select = useCallback(
    async (room: Room | null) => {
      const g = ++generation.current;
      const soundContext = soundEpoch.current;
      const foreground = foregroundEpoch.current;
      soundBaselineReady.current = false;
      sounds.current!.reset();
      selectedRef.current = room;
      setSelected(room);
      setHistory(emptyHistory);
      setError(null);
      if (!room) return;
      try {
        const page = await (engine.latest ? engine.latest(room) : engine.history(room));
        if (mounted.current && g === generation.current) {
          setHistory(page);
          const account = engine.identity;
          if (soundContext === soundEpoch.current && foreground === foregroundEpoch.current && active.current) {
            sounds.current!.account(soundActor(account));
            sounds.current!.observe(
              soundRoom(soundActor(account), room),
              page.messages,
              account?.user_id ?? 0,
              true,
            );
            soundBaselineReady.current = online.current && !engine.offline && presentation.current;
          }
        }
      } catch (e) {
        if (mounted.current && g === generation.current) setError(errorWord(e));
      } finally {
        capture();
      }
    },
    [capture, engine],
  );
  const sync = useCallback(async () => {
    if (pollBusy.current || !active.current || !online.current || !engine.identity) {
      capture();
      return;
    }
    pollBusy.current = true;
    const g = generation.current;
    const foreground = foregroundEpoch.current;
    const syncIdentity = engine.identity;
    const soundWasReady = soundBaselineReady.current;
    const soundContext = soundEpoch.current;
    try {
      if (engine.pending().some(p => p.state !== 'failed')) await engine.flush();
      else await engine.refresh();
      const room = selectedRef.current;
      if (room) {
        const page = await engine.history(room);
        if (mounted.current && generation.current === g) {
          setHistory(page);
          const account = engine.identity;
          if (
            !page.archive?.browsing &&
            active.current &&
            foreground === foregroundEpoch.current &&
            soundContext === soundEpoch.current &&
            soundActor(account) === soundActor(syncIdentity)
          ) {
            sounds.current!.account(soundActor(account));
            sounds.current!.observe(
              soundRoom(soundActor(account), room),
              page.messages,
              account?.user_id ?? 0,
              !soundWasReady || engine.offline || !online.current,
            );
            soundBaselineReady.current = !engine.offline && online.current;
          } else if (page.archive?.browsing) soundBaselineReady.current = false;
        }
      }
      if (mounted.current) setError(null);
      if (mounted.current && active.current && foreground === foregroundEpoch.current)
        reveal();
    } catch (e) {
      if (mounted.current) setError(errorWord(e));
      soundBaselineReady.current = false;
      sounds.current!.reset();
      if (mounted.current && foreground === foregroundEpoch.current) {
        retainedAllowed.current = false;
        presentation.current = false;
        setPresentationReady(false);
        setDisplayReady(false);
      }
      const failure = e as { code?: string; status?: number };
      const unavailable =
        (failure.code === 'connection_failed' && !failure.status) ||
        (failure.status === 503 &&
          !['forbidden', 'identity_mismatch', 'session_expired', 'stale_session'].includes(
            failure.code ?? '',
          ));
      if (
        unavailable &&
        engine.offline &&
        mounted.current &&
        active.current &&
        foreground === foregroundEpoch.current &&
        g === generation.current &&
        syncIdentity
      ) {
        try {
          // NetInfo measures internet access, not this Odoo/VPN route. The
          // engine's scoped cache read is also the authoritative TTL guard.
          engine.rooms();
          const current = engine.identity;
          if (
            current?.user_id === syncIdentity.user_id &&
            current?.database === syncIdentity.database &&
            current.permissions.chat_view === true
          )
            reveal();
        } catch {
          /* Expired/revoked cache stays behind the foreground mask. */
        }
      }
    } finally {
      pollBusy.current = false;
      capture();
    }
  }, [capture, engine]);
  useEffect(() => {
    mounted.current = true;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      if (stopped) return;
      await sync();
      if (!stopped) timer = setTimeout(tick, engine.backoffMs);
    };
    const stopNetwork = NetInfo.addEventListener(state => {
      const wasOnline = online.current;
      online.current = state.isConnected !== false && state.isInternetReachable !== false;
      if (!wasOnline && online.current) { presentation.current = false; setPresentationReady(false); }
      if (wasOnline !== online.current) {
        soundEpoch.current++;
        soundBaselineReady.current = false;
        sounds.current!.reset();
      }
      if (!online.current) engine.markDisconnected();
      capture();
      if (!online.current && active.current) reveal();
      if (online.current && active.current) void sync();
    });
    const subscription = AppState.addEventListener('change', state => {
      active.current = state === 'active';
      setForeground(active.current);
      foregroundEpoch.current++;
      soundEpoch.current++;
      soundBaselineReady.current = false;
      sounds.current!.reset();
      presentation.current = false;
      setPresentationReady(false);
      // Enforce the existing offline lease before retained display is allowed;
      // an online flag must not turn an old background snapshot into authority.
      engine.markDisconnected();
      capture();
      if (active.current) {
        if (!online.current) {
          engine.markDisconnected();
          capture();
          reveal();
        } else void sync();
      }
    });
    void engine
      .restoreOffline()
      .then(() => {
        capture();
        if (!online.current && active.current) reveal();
        void tick();
      })
      .catch(() => {
        capture();
        void tick();
      });
    return () => {
      stopped = true;
      mounted.current = false;
      generation.current++;
      clearTimeout(timer);
      stopNetwork();
      subscription.remove();
      sounds.current!.close();
    };
  }, [capture, engine, sync]);
  useEffect(() => {
    if (!displayReady || presentationReady || !foreground) return;
    const scope = displayScope(), epoch = foregroundEpoch.current;
    let stopped = false, timer: ReturnType<typeof setTimeout>;
    const current = () => !stopped && mounted.current && active.current && !presentation.current
      && epoch === foregroundEpoch.current && scope === displayScope();
    const schedule = () => {
      if (!current()) return;
      const remaining = engine.leaseRemainingMs;
      if (!Number.isFinite(remaining) || remaining <= 0) {
        retainedAllowed.current = false; setDisplayReady(false); capture(); return;
      }
      // One local deadline, not polling. If verification renewed the lease
      // while history is still pending, schedule its new deadline instead.
      timer = setTimeout(schedule, remaining + 1);
    };
    schedule();
    return () => { stopped = true; clearTimeout(timer); };
  }, [capture, engine, displayReady, presentationReady, foreground]);
  const run = useCallback(
    async (operation: () => Promise<unknown>) => {
      setBusy(true);
      setError(null);
      try {
        await operation();
      } catch (e) {
        if (mounted.current) setError(errorWord(e));
        throw e;
      } finally {
        if (mounted.current) setBusy(false);
        capture();
        if (mounted.current && active.current && engine.identity) {
          if (online.current) void sync();
          else reveal();
        }
      }
    },
    [capture, engine, sync],
  );
  const logout = useCallback(async () => {
    generation.current++;
    soundBaselineReady.current = false;
    sounds.current!.account('');
    selectedRef.current = null;
    setSelected(null);
    setHistory(emptyHistory);
    await run(() => engine.logout());
  }, [engine, run]);
  const older = useCallback(async () => {
    const room = selectedRef.current;
    if (!room || !history.next_before_id) return;
    const g = ++generation.current; soundBaselineReady.current = false;
    await run(async () => {
      const page = await engine.history(room, history.next_before_id!);
      if (mounted.current && g === generation.current) setHistory(page);
    });
  }, [engine, history.next_before_id, run]);
  const newer = useCallback(async () => {
    const room = selectedRef.current; if (!room) return;
    const g = ++generation.current; soundBaselineReady.current = false;
    await run(async () => { const page = await engine.newer(room); if (mounted.current && g === generation.current) setHistory(page); });
  }, [engine, run]);
  const latest = useCallback(async () => {
    const room = selectedRef.current; if (!room) return;
    const g = ++generation.current; soundBaselineReady.current = false;
    await run(async () => { const page = await engine.latest(room); if (mounted.current && g === generation.current) setHistory(page); });
  }, [engine, run]);
  const jump = useCallback(async (messageId: number) => {
    const room = selectedRef.current; if (!room) return;
    const g = ++generation.current; soundBaselineReady.current = false;
    await run(async () => {
      const page = await engine.jumpToMessage(room, messageId);
      if (mounted.current && g === generation.current) setHistory(page);
    });
  }, [engine, run]);
  return {
    identity,
    rooms,
    selected,
    history,
    pending,
    error,
    busy,
    offline,
    presentationReady,
    displayReady,
    retainedDisplay: !!displayedScope.current && displayedScope.current === displayScope(),
    foreground,
    run,
    select,
    sync,
    capture,
    logout,
    older,
    newer,
    latest,
    jump,
    soundsEnabled:
      soundState.actor === soundActor(identity) && soundState.ready && soundState.enabled,
    soundsReady: soundState.actor === soundActor(identity) && soundState.ready,
    setSoundsEnabled: (enabled: boolean) => {
      if (
        active.current &&
        presentation.current &&
        soundActor(engine.identity) === soundState.actor
      )
        sounds.current!.enabled(enabled);
    },
    soundSent: (room: Room) => {
      const actor = soundActor(engine.identity);
      if (
        active.current &&
        presentation.current &&
        actor &&
        actor === sounds.current!.snapshot().actor &&
        soundRoom(actor, selectedRef.current) === soundRoom(actor, room)
      )
        sounds.current!.sent(soundRoom(actor, room));
    },
  };
}
export type ChatView = ReturnType<typeof useChat>;
