import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import NetInfo from '@react-native-community/netinfo';
import type { Bootstrap, ChatEngine, History, Pending, Room } from '../core/ChatEngine';
import { errorWord, type Word } from './dictionary';

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
  const selectedRef = useRef<Room | null>(null);
  const active = useRef(AppState.currentState === 'active');
  const online = useRef(true);
  const generation = useRef(0);
  const pollBusy = useRef(false);
  const mounted = useRef(true);
  const foregroundEpoch = useRef(0);
  const capture = useCallback(() => {
    if (!mounted.current) return;
    let rows: Room[] = [];
    let queue: Pending[] = [];
    try {
      rows = engine.rooms();
      queue = engine.pending();
    } catch {
      /* TTL/identity blocks display. */
    }
    const account = engine.status === 'offline_expired' ? null : engine.identity;
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
    }
  }, [engine]);
  const select = useCallback(
    async (room: Room | null) => {
      const g = ++generation.current;
      selectedRef.current = room;
      setSelected(room);
      setHistory(emptyHistory);
      setError(null);
      if (!room) return;
      try {
        const page = await engine.history(room);
        if (mounted.current && g === generation.current) setHistory(page);
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
    try {
      if (engine.pending().some(p => p.state !== 'failed')) await engine.flush();
      else await engine.refresh();
      const room = selectedRef.current;
      if (room) {
        const page = await engine.history(room);
        if (mounted.current && generation.current === g) setHistory(page);
      }
      if (mounted.current) setError(null);
      if (mounted.current && active.current && foreground === foregroundEpoch.current)
        setPresentationReady(true);
    } catch (e) {
      if (mounted.current) setError(errorWord(e));
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
            setPresentationReady(true);
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
      if (!wasOnline && online.current) setPresentationReady(false);
      if (!online.current) engine.markDisconnected();
      capture();
      if (!online.current && active.current) setPresentationReady(true);
      if (online.current && active.current) void sync();
    });
    const subscription = AppState.addEventListener('change', state => {
      active.current = state === 'active';
      foregroundEpoch.current++;
      setPresentationReady(false);
      if (active.current) {
        if (!online.current) {
          engine.markDisconnected();
          capture();
          setPresentationReady(true);
        } else void sync();
      }
    });
    void engine
      .restoreOffline()
      .then(() => {
        capture();
        if (!online.current && active.current) setPresentationReady(true);
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
    };
  }, [capture, engine, sync]);
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
          else setPresentationReady(true);
        }
      }
    },
    [capture, engine, sync],
  );
  const logout = useCallback(async () => {
    generation.current++;
    selectedRef.current = null;
    setSelected(null);
    setHistory(emptyHistory);
    await run(() => engine.logout());
  }, [engine, run]);
  const older = useCallback(async () => {
    const room = selectedRef.current;
    const g = generation.current;
    if (!room || !history.next_before_id) return;
    await run(async () => {
      const page = await engine.history(room, history.next_before_id!);
      if (g === generation.current) setHistory(page);
    });
  }, [engine, history.next_before_id, run]);
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
    run,
    select,
    sync,
    capture,
    logout,
    older,
  };
}
export type ChatView = ReturnType<typeof useChat>;
