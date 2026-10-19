import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AppState,
  Alert,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  Text,
  View,
  type TextInput,
  type ViewToken,
} from 'react-native';
import { FlashList, type FlashListRef } from '@shopify/flash-list';
import type { Attachment, ChatEngine, Message, Pending } from '../core/ChatEngine';
import { Button, colors, direction, Field, Icon, IconButton, Label, Sheet, styles } from './components';
import { companyDisplayName } from './companyNames';
import { MessageQuote, MessageStatus } from './MessagePresentation';
import { TimelineFollow } from './timelineFollow';
import { errorWord, type Language, type Translate, type Word } from './dictionary';
import { AttachmentTools, MediaTile, useVoiceSession } from './MediaTools';
import { GroupAvatar } from './GroupAvatar';
import { SwipeReply } from './SwipeReply';
import type { ChatView } from './useChat';
import { ChatError } from '../core/ChatEngine';
import { discardStagedAttachment, stageFile } from '../runtime';
import {
  canViewMedia,
  conversationAccess,
  messageTime,
  messageDateTime,
  presentationKey,
  visibleReadIds,
} from './viewModel';

type Row = { key: string; message?: Message; pending?: Pending };
const previewViewability = { minimumViewTime: 150, itemVisiblePercentThreshold: 10 };
export function TimelineScreen({
  engine,
  chat,
  language,
  t,
  back,
  manage,
  onMenu,
  presented = true,
}: {
  engine: ChatEngine;
  chat: ChatView;
  language: Language;
  t: Translate;
  back?: () => void;
  manage: () => void;
  onMenu?: () => void;
  presented?: boolean;
}) {
  const room = chat.selected!;
  // The shell may retain this exact conversation while another section is visible.
  // Native viewability/layout events and retained callbacks must consult current presentation.
  const presentedRef = useRef(presented); presentedRef.current = presented;
  const [text, setText] = useState('');
  const [reply, setReply] = useState<Message | null>(null);
  const [localError, setLocalError] = useState<Word | null>(null);
  const [sending, setSending] = useState(false);
  const [keyboardOffset, setKeyboardOffset] = useState(0);
  const keyboardFrame = useRef<View>(null);
  const keyboardMeasure = useRef(0);
  const access = conversationAccess(chat.identity, room);
  const { directOff } = access;
  const canSend = presented && chat.presentationReady && access.canSend;
  const showComposer = access.canSend && (chat.presentationReady || chat.retainedDisplay === true);
  const canAttach = presented && chat.presentationReady && access.canAttach;
  const viewMedia = presented && chat.presentationReady && canViewMedia(chat.identity, room);
  const retainedMedia = !viewMedia && chat.retainedDisplay === true && canViewMedia(chat.identity, room);
  const mediaKey = presentationKey(chat.identity, room);
  const previewScope = `${chat.identity?.database}/${mediaKey}`;
  const actionScope = `${engine.accountScope}/${previewScope}`;
  const currentActionScope = useRef(actionScope); currentActionScope.current = actionScope;
  const [hiddenState, setHiddenState] = useState<{ scope: string; ids: number[] } | null>(() => {
    try { const ids = engine.cachedHiddenMessages(room); return ids === null ? null : { scope: actionScope, ids }; }
    catch { return null; }
  });
  const hiddenReady = hiddenState?.scope === actionScope;
  const hiddenIds = useMemo(() => {
    const stored = new Set(hiddenReady ? hiddenState.ids : []);
    return new Set(chat.history.messages.filter(message => stored.has(message.id)
      && message.author_user_id === chat.identity?.user_id).map(message => message.id));
  }, [hiddenState, actionScope, chat.history.messages, chat.identity?.user_id]);
  const currentMessages = useRef({ messages: chat.history.messages, userId: chat.identity?.user_id });
  currentMessages.current = { messages: chat.history.messages, userId: chat.identity?.user_id };
  const ownsMessage = (messageId: number) => currentMessages.current.messages.some(message =>
    message.id === messageId && message.author_user_id === currentMessages.current.userId);
  const hiddenRef = useRef({ ready: hiddenReady, ids: hiddenIds }); hiddenRef.current = { ready: hiddenReady, ids: hiddenIds };
  const [info, setInfo] = useState<{ scope: string; message: Message; cached: boolean } | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const actionOperation = useRef(0);
  const hiddenMutation = useRef(0);
  const hiddenAuthority = useRef(false);
  hiddenAuthority.current = chat.presentationReady && chat.identity?.permissions.chat_view === true
    && chat.identity.company_ids.includes(room.company_id);
  const [jumpTarget, setJumpTarget] = useState<{ scope: string; id: number } | null>(null);
  useEffect(() => {
    let active = true;
    const requested = actionScope;
    const mutation = hiddenMutation.current;
    setActionBusy(false); setInfo(null); setJumpTarget(null);
    void engine.hiddenMessages(room).then(ids => {
      if (active && currentActionScope.current === requested && hiddenMutation.current === mutation) setHiddenState({ scope: requested, ids });
    }).catch(e => { if (active && currentActionScope.current === requested) setLocalError(errorWord(e)); });
    return () => { active = false; actionOperation.current++; hiddenMutation.current++; };
  }, [engine, actionScope]);
  const [visibleImages, setVisibleImages] = useState<{ scope: string; ids: number[] }>({
    scope: '',
    ids: [],
  });
  const previewChanged = useCallback(
    ({ viewableItems }: { viewableItems: ViewToken<Row>[] }) => {
      if (!presentedRef.current) return;
      const ids = viewableItems
        .filter(item => item.isViewable && ['image', 'audio'].includes(String(item.item.message?.media?.kind)))
        .map(item => item.item.message!.id)
        .sort((a, b) => a - b);
      setVisibleImages(previous =>
        previous.scope === previewScope && previous.ids.join(',') === ids.join(',')
          ? previous
          : { scope: previewScope, ids },
      );
    },
    [previewScope],
  );
  const voice = useVoiceSession(mediaKey, setLocalError, viewMedia, canAttach);
  const sendBusy = useRef(false);
  const draftRevision = useRef(0);
  const replyRevision = useRef(0);
  const list = useRef<FlashListRef<Row>>(null);
  const input = useRef<TextInput>(null);
  const follow = useRef(new TimelineFollow());
  const browsing = useRef(false); browsing.current = chat.history.archive?.browsing === true;
  const scrollFrame = useRef<number | null>(null);
  const scrollGeometry = useRef({ content: 0, viewport: 0, offset: 0 });
  const dragging = useRef(false);
  const [showLatest, setShowLatest] = useState(false);
  const [actionsFor, setActionsFor] = useState<number | null>(null);
  const live = useRef(true);
  const latestAccess = useRef(canSend);
  latestAccess.current = canSend;
  const latestSendAuthority = useRef(chat.presentationReady && access.canSend);
  latestSendAuthority.current = chat.presentationReady && access.canSend;
  const attachmentPresentation = useRef({ presented, ready: chat.presentationReady, offline: chat.offline });
  attachmentPresentation.current = { presented, ready: chat.presentationReady, offline: chat.offline };
  const attachmentIntents = useRef(new Set<{ wake(): void; cancel(): void }>());
  useEffect(() => {
    for (const intent of attachmentIntents.current) intent.wake();
  }, [actionScope, presented, chat.presentationReady, chat.offline, sending, access.canAttach, JSON.stringify(chat.identity?.company_ids)]);
  useEffect(() => {
    const subscription = AppState.addEventListener?.('change', () => {
      for (const intent of attachmentIntents.current) intent.wake();
    });
    return () => { subscription?.remove(); for (const intent of [...attachmentIntents.current]) intent.cancel(); };
  }, []);
  // Coalesce layout signals and let recycled cells commit before one correction.
  // Native onScroll can still describe the previous tail, so prefer FlashList's fresh layout.
  const scrollLatest = useCallback(() => {
    if (!presentedRef.current || scrollFrame.current !== null) return;
    scrollFrame.current = requestAnimationFrame(() => {
      scrollFrame.current = requestAnimationFrame(() => {
        scrollFrame.current = null;
        if (!presentedRef.current || !live.current || browsing.current || dragging.current || !follow.current.following) return;
        let { content, viewport, offset } = scrollGeometry.current;
        const current = list.current;
        try {
          if (
            current?.getChildContainerDimensions &&
            current.getWindowSize &&
            current.getAbsoluteLastScrollOffset
          ) {
            content = current.getChildContainerDimensions().height + current.getFirstItemOffset();
            viewport = current.getWindowSize().height;
            offset = current.getAbsoluteLastScrollOffset();
          }
        } catch {
          /* Before FlashList initializes, use the latest native measurements. */
        }
        if (viewport > 0 && Math.abs(Math.max(0, content - viewport) - offset) <= 1) return;
        current?.scrollToEnd({ animated: false });
      });
    });
  }, []);
  const followGeometry = useCallback(() => {
    if (presentedRef.current && follow.current.following && !dragging.current) scrollLatest();
  }, [scrollLatest]);
  useEffect(() => {
    live.current = true;
    const shown = Keyboard.addListener('keyboardDidShow', followGeometry);
    const hidden = Keyboard.addListener('keyboardDidHide', followGeometry);
    return () => {
      live.current = false;
      shown.remove();
      hidden.remove();
      if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
    };
  }, [followGeometry]);
  useEffect(() => {
    if (presented) return;
    actionOperation.current++;
    keyboardMeasure.current++;
    setInfo(null); setActionsFor(null); setActionBusy(false); setJumpTarget(null);
    setVisibleImages({ scope: '', ids: [] });
    dragging.current = false;
    if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
    scrollFrame.current = null;
    // Do not clear the draft/reply, change reader intent, or accept zero-sized hidden geometry.
  }, [presented]);
  const chooseReply = (message: Message) => {
    if (!latestAccess.current || !live.current || (message.author_user_id === currentMessages.current.userId
      && (!hiddenRef.current.ready || hiddenRef.current.ids.has(message.id)))) return;
    setActionsFor(null);
    replyRevision.current++;
    setReply(message);
    input.current?.focus();
  };
  const operationCurrent = (scope: string, operation: number) => presentedRef.current && live.current && currentActionScope.current === scope
    && actionOperation.current === operation && AppState.currentState === 'active';
  const showInfo = async (message: Message) => {
    if (!presentedRef.current || currentActionScope.current !== actionScope || !live.current || !chat.presentationReady || AppState.currentState !== 'active') return;
    const requested = actionScope, operation = ++actionOperation.current;
    setActionsFor(null); setActionBusy(true); setLocalError(null);
    setInfo({ scope: requested, message, cached: true });
    try {
      const result = await engine.messageInfo(room, message.id);
      if (operationCurrent(requested, operation)) setInfo({ scope: requested, message: result, cached: chat.offline });
    } catch (e) { if (operationCurrent(requested, operation)) { setInfo(null); setLocalError(errorWord(e)); } }
    finally { if (operationCurrent(requested, operation)) setActionBusy(false); }
  };
  const changeHidden = async (messageId: number, hidden: boolean) => {
    if (!presentedRef.current || currentActionScope.current !== actionScope || !live.current || !chat.presentationReady || AppState.currentState !== 'active') return;
    if (hidden && !ownsMessage(messageId)) return;
    const requested = actionScope, operation = ++actionOperation.current;
    const mutation = ++hiddenMutation.current;
    const submittedReply = replyRevision.current;
    setActionsFor(null); setActionBusy(true); setLocalError(null);
    try {
      const ids = await engine.setMessageHidden(room, messageId, hidden);
      if (live.current && receiptLive.current && currentActionScope.current === requested
        && hiddenMutation.current === mutation && hiddenAuthority.current) {
        setHiddenState({ scope: requested, ids });
        if (hidden && reply?.id === messageId && submittedReply === replyRevision.current) { replyRevision.current++; setReply(null); }
      }
      if (operationCurrent(requested, operation)) setInfo(null);
    } catch (e) { if (operationCurrent(requested, operation)) setLocalError(errorWord(e)); }
    finally { if (operationCurrent(requested, operation)) setActionBusy(false); }
  };
  const confirmHide = (messageId: number) => {
    if (!presentedRef.current || currentActionScope.current !== actionScope || !live.current || !chat.presentationReady || AppState.currentState !== 'active') return;
    if (!ownsMessage(messageId)) return;
    const requested = actionScope;
    Alert.alert(t('hideLocal'), t('hideLocalConfirm'), [
      { text: t('cancel'), style: 'cancel' },
      { text: t('hideLocal'), style: 'destructive', onPress: () => {
        if (presentedRef.current && currentActionScope.current === requested && live.current) void changeHidden(messageId, true);
      } },
    ]);
  };
  const openOriginal = async (messageId: number) => {
    if (!presentedRef.current || currentActionScope.current !== actionScope || !live.current || !chat.presentationReady || AppState.currentState !== 'active') return;
    const requested = actionScope, operation = ++actionOperation.current;
    follow.current.following = false; setShowLatest(true); setActionsFor(null); setActionBusy(true); setLocalError(null);
    try {
      await chat.jump(messageId);
      if (operationCurrent(requested, operation)) setJumpTarget({ scope: requested, id: messageId });
    } catch (e) { if (operationCurrent(requested, operation)) setLocalError(errorWord(e)); }
    finally { if (operationCurrent(requested, operation)) setActionBusy(false); }
  };
  useEffect(() => {
    setText('');
    setReply(null);
    setLocalError(null);
  }, [room.id, room.membership_id]);
  const receiptBusy = useRef(new Set<number>());
  const receiptLive = useRef(true);
  useEffect(
    () => () => {
      receiptLive.current = false;
      receiptBusy.current.clear();
    },
    [],
  );
  const visibleChanged = useCallback(
    ({ viewableItems }: { viewableItems: ViewToken<Row>[] }) => {
      if (!presentedRef.current) return;
      const active = AppState.currentState === 'active' && chat.presentationReady && !chat.offline;
      for (const id of visibleReadIds(
        viewableItems.filter(item => item.isViewable && (item.item.message?.author_user_id !== chat.identity?.user_id
          || hiddenRef.current.ready && !hiddenRef.current.ids.has(item.item.message?.id ?? 0))).map(item => item.item),
        chat.identity?.user_id ?? 0,
        active,
      )) {
        if (receiptBusy.current.has(id)) continue;
        receiptBusy.current.add(id);
        void engine
          .acknowledge(room, id, 'read')
          .then(ack => {
            if (ack && receiptLive.current && presentedRef.current) chat.capture();
          })
          .catch(() => {
            /* Retry only when it is actually visible again. */
          })
          .finally(() => receiptBusy.current.delete(id));
      }
    },
    [chat.identity?.user_id, chat.presentationReady, chat.offline, chat.capture, engine, room],
  );
  const send = async (attachment?: Attachment) => {
    if (!presentedRef.current || sendBusy.current || !latestAccess.current || !canSend) return;
    sendBusy.current = true;
    const submittedDraft = draftRevision.current;
    const submittedReply = replyRevision.current;
    const submittedScope = actionScope;
    setSending(true);
    setLocalError(null);
    try {
      if (attachment) await engine.enqueueAttachment(room, attachment, text, reply?.id);
      else await engine.enqueue(room, text, reply?.id);
      if (!live.current || !receiptLive.current || currentActionScope.current !== submittedScope || !latestSendAuthority.current) return;
      // Hiding a retained conversation is not revoking its authority. The durable
      // enqueue owns this exact submitted draft even when Orders is now visible.
      if (submittedDraft === draftRevision.current) setText('');
      if (submittedReply === replyRevision.current) setReply(null);
      chat.capture();
      if (presentedRef.current) {
        chat.soundSent?.(room);
        if (!browsing.current) follow.current.ownEnqueued();
        setShowLatest(browsing.current); setActionsFor(null);
        if (!browsing.current) scrollLatest();
      }
      // The durable local queue owns retry/ACK. Network latency must not hold the composer lock.
      if (!chat.offline) void chat.sync().catch(() => undefined);
    } catch (e) {
      setLocalError(errorWord(e));
    } finally {
      sendBusy.current = false;
      setSending(false);
    }
  };
  /** Only a user-started picker owns this bounded intent; hidden text callbacks
   * still use send's unchanged guards. Offline enqueue is local only; flush
   * retains its existing independent online verification. */
  const beginAttachment = () => {
    const fingerprint = () => {
      try {
        const identity = engine.identity, current = engine.rooms().find(value => value.id === room.id);
        if (!identity || !engine.accountScope || !current || current.company_id !== room.company_id || current.membership_id !== room.membership_id
          || !conversationAccess(identity, current).canAttach) return null;
        return JSON.stringify([engine.accountScope, identity.database, identity.user_id, [...identity.company_ids].sort((a, b) => a - b),
          identity.permissions.revision, room.company_id, room.id, room.membership_id]);
      } catch { return null; }
    };
    const original = fingerprint(), requested = actionScope;
    if (!original || !canAttach || !live.current || AppState.currentState !== 'active') throw new ChatError('stale_session');
    const submittedText = text, submittedReply = reply?.id, submittedDraft = draftRevision.current, submittedReplyRevision = replyRevision.current;
    const deadline = Date.now() + 5 * 60 * 1000;
    let cancelled = false, claimed = false, discarded = false, stageStarted = false, enqueueStarted = false, staged: Attachment | undefined;
    let waiter: { resolve(): void; reject(error: ChatError): void } | undefined;
    const valid = () => !cancelled && live.current && Date.now() < deadline && currentActionScope.current === requested && fingerprint() === original;
    const ready = () => {
      const current = attachmentPresentation.current;
      return current.presented && current.ready && AppState.currentState === 'active' && !sendBusy.current;
    };
    const dispose = () => { clearTimeout(timer); attachmentIntents.current.delete(intent); };
    const discard = () => {
      if (staged && !claimed && !discarded) { discarded = true; void discardStagedAttachment(staged).catch(() => undefined); }
    };
    const cancel = () => {
      if (cancelled) { discard(); return; }
      cancelled = true; dispose();
      waiter?.reject(new ChatError('stale_session')); waiter = undefined;
      discard();
    };
    const wake = () => {
      if (!valid()) { cancel(); return; }
      if (ready() && waiter) { const pending = waiter; waiter = undefined; pending.resolve(); }
    };
    const intent = { wake, cancel };
    const timer = setTimeout(cancel, 5 * 60 * 1000);
    attachmentIntents.current.add(intent);
    const wait = async () => {
      if (!valid()) { cancel(); throw new ChatError('stale_session'); }
      if (!ready()) await new Promise<void>((resolve, reject) => { waiter = { resolve, reject }; wake(); });
      if (!valid() || !ready()) throw new ChatError('stale_session');
    };
    return {
      stage: async (input: { uri: string; name: string; mime: string; kind: 'image' | 'file' }) => {
        if (stageStarted) throw new ChatError('stale_session');
        stageStarted = true;
        await wait();
        if (!valid() || !ready()) { cancel(); throw new ChatError('stale_session'); }
        const value = await stageFile(room, input); staged = value;
        if (!valid()) { cancel(); throw new ChatError('stale_session'); }
        return value;
      },
      enqueue: async (value: Attachment) => {
        if (enqueueStarted || !staged || value !== staged) throw new ChatError('stale_session');
        enqueueStarted = true;
        await wait();
        if (!valid() || !ready()) { cancel(); throw new ChatError('stale_session'); }
        claimed = true; dispose(); sendBusy.current = true; setSending(true); setLocalError(null);
        try {
          // Claim before awaiting: the existing outbox exclusively owns retry,
          // uncertain persistence and staged-file cleanup from this point on.
          await engine.enqueueAttachment(room, value, submittedText, submittedReply);
          if (!valid()) return;
          if (submittedDraft === draftRevision.current) setText('');
          if (submittedReplyRevision === replyRevision.current) setReply(null);
          chat.capture();
          if (presentedRef.current) {
            chat.soundSent?.(room); if (!browsing.current) follow.current.ownEnqueued();
            setShowLatest(browsing.current); setActionsFor(null); if (!browsing.current) scrollLatest();
          }
          if (!engine.offline) void chat.sync().catch(() => undefined);
        } finally { sendBusy.current = false; setSending(false); }
      },
      cancel,
    };
  };
  const rows: Row[] = useMemo(() => [
    ...chat.history.messages.map(message => ({ key: `message-${message.id}`, message })),
    ...chat.pending
      .filter(item => item.room_id === room.id && item.company_id === room.company_id && item.membership_id === room.membership_id)
      .map(pending => ({ key: pending.client_uuid, pending })),
  ], [chat.history.messages, chat.pending, room.id, room.company_id, room.membership_id]);
  const rowPresentation = useMemo(() => ({ mediaKey, hiddenState, actionsFor, jumpTarget, actionBusy, visibleImages, language, canSend, viewMedia, retainedMedia }),
    [mediaKey, hiddenState, actionsFor, jumpTarget, actionBusy, visibleImages, language, canSend, viewMedia, retainedMedia]);
  useEffect(() => {
    if (!presented || jumpTarget?.scope !== actionScope) return;
    const index = rows.findIndex(row => row.message?.id === jumpTarget.id);
    if (index < 0) return;
    const requested = actionScope;
    const frame = requestAnimationFrame(() => {
      if (presentedRef.current && live.current && currentActionScope.current === requested)
        list.current?.scrollToIndex({ index, animated: false, viewPosition: 0.4 });
    });
    return () => cancelAnimationFrame(frame);
  }, [presented, jumpTarget, actionScope, chat.history.messages]);
  const lastKey = rows[rows.length - 1]?.key;
  useEffect(() => {
    if (!presented) return;
    if (browsing.current) { follow.current.following = false; setShowLatest(true); return; }
    if (follow.current.rows(lastKey)) scrollLatest();
    else if (lastKey && !follow.current.following) setShowLatest(true);
  }, [presented, lastKey, scrollLatest, chat.history.archive?.browsing]);
  const companyName = companyDisplayName(
    chat.identity?.profile?.companies.find(company => company.id === room.company_id),
    language,
    room.company_id,
  );
  // A TTL-checked retained tree may stay mounted behind the shell privacy cover.
  // It is display-only until presentationReady; media/read/actions remain fenced above.
  if (
    (!chat.presentationReady && !chat.retainedDisplay) ||
    !chat.identity?.company_ids.includes(room.company_id) ||
    chat.identity.permissions.chat_view !== true
  )
    return null;
  return (
    <View
      ref={keyboardFrame}
      style={[styles.fill, { minHeight: 0, direction: 'ltr' }]}
      onLayout={() => {
        if (!presentedRef.current) return;
        const requested = ++keyboardMeasure.current;
        keyboardFrame.current?.measureInWindow((_x, y) => {
          if (presentedRef.current && receiptLive.current && requested === keyboardMeasure.current) setKeyboardOffset(y);
        });
      }}>
      <KeyboardAvoidingView
        style={[styles.fill, { minHeight: 0, backgroundColor: colors.chatBackground }]}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={keyboardOffset}>
        <View style={[styles.header, { paddingHorizontal: 8, paddingVertical: 6, gap: 0 }]}>
          <View
            style={[
              styles.row,
              {
                direction: 'ltr',
                flexWrap: 'nowrap',
                flexDirection: language === 'ar' ? 'row-reverse' : 'row',
              },
            ]}>
            {onMenu && <IconButton icon="menu" label={t('menu')} onPress={() => { if (presentedRef.current) onMenu(); }} />}
            <GroupAvatar engine={engine} room={room} enabled={presented && chat.presentationReady} size={38} />
            <View style={[styles.fill, { minWidth: 0 }]}>
              <Text
                numberOfLines={1}
                style={[styles.title, { fontSize: 17, lineHeight: 24 }, direction(language)]}>
                {room.name}
              </Text>
              <Text
                numberOfLines={1}
                style={[styles.muted, { fontSize: 12, lineHeight: 18 }, direction(language)]}>
                {companyName}
              </Text>
            </View>
            {room.is_group && (
              <IconButton
                icon="members"
                label={t('members')}
                disabled={chat.offline}
                onPress={() => { if (presentedRef.current) manage(); }}
              />
            )}
            {back && (
              <IconButton
                icon="back"
                label={t('back')}
                onPress={() => { if (presentedRef.current) back(); }}
                style={language === 'ar' ? { transform: [{ rotate: '180deg' }] } : undefined}
              />
            )}
          </View>
        </View>
        <View style={{ flex: 1, minHeight: 0 }}>
          <FlashList
            ref={list}
            extraData={rowPresentation}
            data={rows}
            viewabilityConfig={{ minimumViewTime: 600, viewAreaCoveragePercentThreshold: 75 }}
            onViewableItemsChanged={visibleChanged}
            viewabilityConfigCallbackPairs={[
              { viewabilityConfig: previewViewability, onViewableItemsChanged: previewChanged },
            ]}
            keyExtractor={row => row.key}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="none"
            onLoad={followGeometry}
            onCommitLayoutEffect={followGeometry}
            onLayout={event => {
              if (!presentedRef.current) return;
              if (event?.nativeEvent?.layout)
                scrollGeometry.current.viewport = event.nativeEvent.layout.height;
              followGeometry();
            }}
            onContentSizeChange={(_width, height) => {
              if (!presentedRef.current) return;
              if (typeof height === 'number') scrollGeometry.current.content = height;
              followGeometry();
            }}
            scrollEventThrottle={16}
            onScrollBeginDrag={() => {
              if (!presentedRef.current) return;
              dragging.current = true;
              if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
              scrollFrame.current = null;
            }}
            onScrollEndDrag={() => {
              if (!presentedRef.current) return;
              dragging.current = false;
            }}
            onMomentumScrollBegin={() => {
              if (!presentedRef.current) return;
              dragging.current = true;
              if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
              scrollFrame.current = null;
            }}
            onMomentumScrollEnd={() => {
              if (!presentedRef.current) return;
              dragging.current = false;
            }}
            onScroll={event => {
              if (!presentedRef.current) return;
              const { contentSize, layoutMeasurement, contentOffset } = event.nativeEvent;
              scrollGeometry.current = {
                content: contentSize.height,
                viewport: layoutMeasurement.height,
                offset: contentOffset.y,
              };
              // Only gestures change reader intent in either direction. Expanding the viewport
              // may expose the last row, but must not re-arm following when IME opens again.
              if (!dragging.current) return;
              const atBottom = follow.current.scroll(
                contentSize.height,
                layoutMeasurement.height,
                contentOffset.y,
              );
              setShowLatest(!atBottom);
            }}
            contentContainerStyle={{ paddingHorizontal: 12, paddingVertical: 10 }}
            maintainVisibleContentPosition={{ startRenderingFromBottom: true }}
            ListHeaderComponent={
              <View>
              {chat.history.archive?.partial && <Label language={language} muted>{t('archiveGap')}</Label>}
              {chat.history.next_before_id ? (
                <Button
                  quiet
                  title={t('older')}
                  disabled={chat.busy || chat.offline && chat.history.archive?.older.kind !== 'cached'}
                  onPress={() => {
                    if (!presentedRef.current) return;
                    follow.current.following = false; setShowLatest(true);
                    void chat.older().catch(() => undefined);
                  }}
                />
              ) : null}
              </View>
            }
            ListFooterComponent={chat.history.archive?.browsing && chat.history.archive.newer.kind === 'cached' ? <Button quiet title={t('newer')} disabled={chat.busy} onPress={() => { if (presentedRef.current) void chat.newer().catch(() => undefined); }} /> : null}
            ListEmptyComponent={
              <View style={{ padding: 24 }}>
                <Label language={language} muted>
                  {t('empty')}
                </Label>
              </View>
            }
            renderItem={({ item }) => {
              const own = item.pending || item.message?.author_user_id === chat.identity?.user_id;
              const message = item.message;
              const pending = item.pending;
              const state = pending?.state ?? message?.delivery_state;
              if (message && own && (!hiddenReady || hiddenIds.has(message.id))) return (
                <View style={{ alignSelf: 'center', marginVertical: 5, padding: 10, borderRadius: 12, backgroundColor: colors.pale }}>
                  <Label language={language} muted>{t(hiddenReady ? 'locallyHidden' : 'loading')}</Label>
                  {hiddenReady && <Button quiet title={t('undoHide')} busy={actionBusy} onPress={() => { void changeHidden(message.id, false); }} />}
                </View>
              );
              return (
                <SwipeReply gestureKey={`${actionScope}/${message?.id ?? pending?.client_uuid}`} enabled={!!message && canSend} language={language} onReply={() => { if (message) chooseReply(message); }}
                  style={{
                    alignSelf: own ? 'flex-end' : 'flex-start',
                    width: 'auto', maxWidth: '86%', minWidth: 100, marginVertical: 4,
                  }}>
                <Pressable
                  accessibilityLabel={
                    message ? `${message.author_name}: ${message.text}` : pending?.text
                  }
                  accessibilityActions={
                    message ? [
                      ...(canSend ? [{ name: 'reply', label: t('reply') }] : []),
                      { name: 'info', label: t('messageInfo') }, ...(own ? [{ name: 'hide', label: t('hideLocal') }] : []),
                    ] : []
                  }
                  onAccessibilityAction={event => {
                    if (event.nativeEvent.actionName === 'reply' && message) chooseReply(message);
                    if (event.nativeEvent.actionName === 'info' && message) void showInfo(message);
                    if (event.nativeEvent.actionName === 'hide' && message) confirmHide(message.id);
                  }}
                  onPress={() => {
                    if (!presentedRef.current) return;
                    if (message)
                      setActionsFor(actionsFor === message.id ? null : message.id);
                  }}
                  onLongPress={() => {
                    if (message) chooseReply(message);
                  }}>
                  <View
                    style={[
                      styles.card,
                      {
                        backgroundColor: own ? colors.chatSent : colors.white,
                        borderRadius: 18,
                        borderBottomLeftRadius: own ? 18 : 5,
                        borderBottomRightRadius: own ? 5 : 18,
                        gap: 4,
                        paddingHorizontal: 11,
                        paddingTop: 9,
                        paddingBottom: 7,
                        ...(jumpTarget?.scope === actionScope && jumpTarget.id === message?.id ? { borderWidth: 1, borderColor: colors.blue } : {}),
                      },
                    ]}>
                    {message && !own && (
                      <Text
                        style={[
                          styles.muted,
                          { color: colors.blue, fontWeight: '600' },
                          direction(language),
                        ]}>
                        {message.author_name}
                      </Text>
                    )}
                    {(message?.reply || pending?.reply_to_message_id) && (
                      <MessageQuote
                        language={language}
                        label={t('openOriginal')}
                        onPress={Number.isSafeInteger(message?.reply?.id ?? pending?.reply_to_message_id) && Number(message?.reply?.id ?? pending?.reply_to_message_id) > 0
                          ? () => { void openOriginal(Number(message?.reply?.id ?? pending?.reply_to_message_id)); } : undefined}
                        author={String(
                          message?.reply?.author_name ??
                            chat.history.messages.find(m => m.id === pending?.reply_to_message_id)
                              ?.author_name ??
                            '',
                        )}
                        text={
                          hiddenIds.has(Number(message?.reply?.id ?? pending?.reply_to_message_id))
                            ? t('locallyHidden') : message?.reply?.unavailable
                            ? t('unavailable')
                            : String(
                                message?.reply?.text ??
                                  chat.history.messages.find(
                                    m => m.id === pending?.reply_to_message_id,
                                  )?.text ??
                                  t('unavailable'),
                              )
                        }
                      />
                    )}
                    {!!(message?.text || pending?.text) && (
                      <Text selectable style={[styles.text, direction(language)]}>
                        {message?.text ?? pending?.text}
                      </Text>
                    )}
                    {viewMedia && message?.media && (
                      <MediaTile
                        key={`${mediaKey}/${message.id}/${String(message.media.id)}`}
                        scopeKey={previewScope}
                        previewVisible={
                          visibleImages.scope === previewScope &&
                          visibleImages.ids.includes(message.id)
                        }
                        room={room}
                        media={message.media}
                        senderName={message.author_name}
                        senderUserId={message.author_user_id}
                        voice={voice}
                        t={t}
                        language={language}
                        report={setLocalError}
                      />
                    )}
                    {retainedMedia && message?.media && <View testID="retained-media-placeholder" style={{ gap: 8 }}>
                      {message.media.kind !== 'audio' && <Label language={language} muted>{String(message.media.name ?? t('file'))}</Label>}
                      {message.media.kind === 'image' ? <View testID="retained-image-space" style={{ width: 240, maxWidth: '100%', height: 180,
                        borderRadius: 12, backgroundColor: colors.pale, alignItems: 'center', justifyContent: 'center' }}>
                        <Icon icon="image" size={34} color={colors.blue} />
                      </View> : message.media.kind === 'audio' ? <View testID="retained-audio-space" style={{ width: 240, maxWidth: '100%', minHeight: 60,
                        alignItems: 'center', justifyContent: 'center' }}><Icon icon="play" size={24} color={colors.blue} /></View>
                        : <Button quiet disabled title={t('open')} onPress={() => undefined} />}
                    </View>}
                    {(viewMedia || retainedMedia) && pending?.attachment && (
                      <Label language={language} muted>
                        {pending.attachment.name}
                      </Label>
                    )}
                    <View
                      style={{
                        flexDirection: 'row',
                        alignItems: 'center',
                        gap: 4,
                        alignSelf: 'flex-end',
                      }}>
                      {message?.created_at && (
                        <Text style={[styles.muted, { fontSize: 11, lineHeight: 16 }]}>
                          {messageTime(message.created_at)}
                        </Text>
                      )}
                      {own && <MessageStatus state={state} t={t} />}
                    </View>
                  </View>
                  {message && actionsFor === message.id && (
                    <View
                      style={{
                        backgroundColor: colors.white,
                        alignSelf: 'flex-start',
                        borderRadius: 16,
                        flexDirection: 'row',
                        alignItems: 'center',
                        paddingHorizontal: 8,
                        marginTop: 4,
                        flexWrap: 'wrap',
                      }}>
                      {canSend && <>
                      <IconButton
                        icon="reply"
                        label={t('reply')}
                        onPress={() => chooseReply(message)}
                      />
                      <Text style={styles.muted}>{t('reply')}</Text>
                      </>}
                      <IconButton icon="info" label={t('messageInfo')} disabled={actionBusy} onPress={() => { void showInfo(message); }} />
                      {own && <IconButton icon="trash" label={t('hideLocal')} tone="danger" disabled={actionBusy} onPress={() => confirmHide(message.id)} />}
                    </View>
                  )}
                </Pressable>
                </SwipeReply>
              );
            }}
          />
          {(showLatest || chat.history.archive?.browsing) && (
            <View
              style={{
                position: 'absolute',
                bottom: 8,
                right: 12,
                backgroundColor: colors.white,
                borderRadius: 24,
                borderWidth: 1,
                borderColor: colors.border,
              }}>
              <IconButton
                icon="down"
                label={chat.history.archive?.browsing ? t('newer') : t('latest')}
                disabled={chat.busy}
                onPress={() => {
                  if (!presentedRef.current) return;
                  const finish = () => { if (presentedRef.current && live.current) { follow.current.ownEnqueued(); setShowLatest(false); scrollLatest(); } };
                  if (chat.history.archive?.browsing) void chat.latest().then(finish).catch(() => undefined);
                  else finish();
                }}
              />
            </View>
          )}
        </View>
        <View
          onLayout={followGeometry}
          style={{
            paddingHorizontal: 8,
            paddingTop: 6,
            paddingBottom: 8,
            gap: 6,
            backgroundColor: colors.composerBackground,
            borderTopWidth: 1,
            borderTopColor: colors.border,
          }}>
          {(localError || chat.error) && (
            <Label language={language}>{t(localError || chat.error!)}</Label>
          )}
          {!showComposer ? (
            <Label language={language}>{t(directOff ? 'directOff' : 'readOnly')}</Label>
          ) : (
            <>
              {reply && (
                <View
                  style={[
                    styles.row,
                    {
                      flexWrap: 'nowrap',
                      flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                      backgroundColor: colors.pale,
                      borderRadius: 12,
                      paddingHorizontal: 4,
                    },
                  ]}>
                  <Icon icon="reply" size={18} color={colors.blue} />
                  <View style={styles.fill}>
                    <MessageQuote
                      author={reply.author_name}
                      text={reply.text}
                      language={language}
                    />
                  </View>
                  <IconButton
                    icon="close"
                    label={t('cancel')}
                    onPress={() => {
                      if (!presentedRef.current || !chat.presentationReady) return;
                      replyRevision.current++;
                      setReply(null);
                    }}
                  />
                </View>
              )}
              <AttachmentTools
                room={room}
                disabled={sending || !canSend}
                voice={voice}
                enqueue={send}
                beginAttachment={beginAttachment}
                language={language}
                t={t}
                report={setLocalError}
                hasText={!!text.trim()}
                onSendText={() => {
                  void send();
                }}
                allowAttachments={canAttach}>
                <Field
                  ref={input}
                  language={language}
                  multiline
                  value={text}
                  onChangeText={value => {
                    if (!presentedRef.current) return;
                    draftRevision.current++;
                    setText(value);
                  }}
                  placeholder={t('message')}
                  accessibilityLabel={t('message')}
                  maxLength={16000}
                  onContentSizeChange={followGeometry}
                  style={{
                    flex: 1,
                    minWidth: 0,
                    minHeight: 46,
                    maxHeight: 120,
                    borderWidth: 0,
                    borderRadius: 24,
                    paddingHorizontal: 10,
                  }}
                  editable={canSend && !voice.recording}
                />
              </AttachmentTools>
            </>
          )}
        </View>
      </KeyboardAvoidingView>
      {presented && info?.scope === actionScope && (info.message.author_user_id !== chat.identity?.user_id
        || hiddenReady && !hiddenIds.has(info.message.id)) && (
        <Sheet compact title={t('messageInfo')} language={language} t={t} close={() => {
          actionOperation.current++; setInfo(null); setActionBusy(false);
        }}>
          <View style={{ height: 20 }}><Label language={language} muted>{actionBusy ? t('loading') : info.cached ? t('cachedInfo') : ''}</Label></View>
          <Label language={language} muted>{t('sender')}</Label>
          <Text selectable style={[styles.text, direction(language)]}>{info.message.author_name}</Text>
          <Label language={language} muted>{t('sentAt')}</Label>
          <Text style={[styles.text, { writingDirection: 'ltr' }]}>{messageDateTime(info.message.created_at) || t('unknown')}</Text>
          {!!info.message.text && <Text selectable style={[styles.text, direction(language)]}>{info.message.text}</Text>}
          {info.message.media?.kind === 'audio' && <Label language={language}>{t('voiceMessage')}</Label>}
          {info.message.author_user_id === chat.identity.user_id && <>
            <Label language={language} muted>{t('messageState')}</Label>
            <View style={[styles.row, { flexDirection: language === 'ar' ? 'row-reverse' : 'row' }]}>
              <MessageStatus state={info.message.delivery_state} t={t} />
              <Label language={language}>{t(['sent', 'delivered', 'read'].includes(info.message.delivery_state ?? '') ? info.message.delivery_state as Word : 'unknown')}</Label>
            </View>
            {info.message.delivery_state === 'read' && !!info.message.read_at && <>
              <Label language={language} muted>{t('readCompletedAt')}</Label>
              <Text style={[styles.text, { writingDirection: 'ltr' }]}>{messageDateTime(info.message.read_at) || t('unknown')}</Text>
            </>}
            <Label language={language} muted>{t('receiptSummary')}</Label>
          </>}
        </Sheet>
      )}
    </View>
  );
}
