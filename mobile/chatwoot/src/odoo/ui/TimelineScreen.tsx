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
}: {
  engine: ChatEngine;
  chat: ChatView;
  language: Language;
  t: Translate;
  back?: () => void;
  manage: () => void;
  onMenu?: () => void;
}) {
  const room = chat.selected!;
  const [text, setText] = useState('');
  const [reply, setReply] = useState<Message | null>(null);
  const [localError, setLocalError] = useState<Word | null>(null);
  const [sending, setSending] = useState(false);
  const [keyboardOffset, setKeyboardOffset] = useState(0);
  const keyboardFrame = useRef<View>(null);
  const keyboardMeasure = useRef(0);
  const access = conversationAccess(chat.identity, room);
  const { directOff } = access;
  const canSend = chat.presentationReady && access.canSend;
  const canAttach = chat.presentationReady && access.canAttach;
  const viewMedia = chat.presentationReady && canViewMedia(chat.identity, room);
  const mediaKey = presentationKey(chat.identity, room);
  const previewScope = `${chat.identity?.database}/${mediaKey}`;
  const actionScope = `${engine.accountScope}/${previewScope}`;
  const currentActionScope = useRef(actionScope); currentActionScope.current = actionScope;
  const [hiddenState, setHiddenState] = useState<{ scope: string; ids: number[] } | null>(() => {
    try { const ids = engine.cachedHiddenMessages(room); return ids === null ? null : { scope: actionScope, ids }; }
    catch { return null; }
  });
  const hiddenReady = hiddenState?.scope === actionScope;
  const hiddenIds = useMemo(() => new Set(hiddenReady ? hiddenState.ids : []), [hiddenState, actionScope]);
  const hiddenRef = useRef({ ready: hiddenReady, ids: hiddenIds }); hiddenRef.current = { ready: hiddenReady, ids: hiddenIds };
  const [info, setInfo] = useState<{ scope: string; message: Message; cached: boolean } | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const actionOperation = useRef(0);
  const [jumpTarget, setJumpTarget] = useState<{ scope: string; id: number } | null>(null);
  useEffect(() => {
    let active = true;
    const requested = actionScope;
    setActionBusy(false); setInfo(null); setJumpTarget(null);
    void engine.hiddenMessages(room).then(ids => {
      if (active && currentActionScope.current === requested) setHiddenState({ scope: requested, ids });
    }).catch(e => { if (active && currentActionScope.current === requested) setLocalError(errorWord(e)); });
    return () => { active = false; actionOperation.current++; };
  }, [engine, actionScope]);
  const [visibleImages, setVisibleImages] = useState<{ scope: string; ids: number[] }>({
    scope: '',
    ids: [],
  });
  const previewChanged = useCallback(
    ({ viewableItems }: { viewableItems: ViewToken<Row>[] }) => {
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
  // Coalesce layout signals and let recycled cells commit before one correction.
  // Native onScroll can still describe the previous tail, so prefer FlashList's fresh layout.
  const scrollLatest = useCallback(() => {
    if (scrollFrame.current !== null) return;
    scrollFrame.current = requestAnimationFrame(() => {
      scrollFrame.current = requestAnimationFrame(() => {
        scrollFrame.current = null;
        if (!live.current || browsing.current || dragging.current || !follow.current.following) return;
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
    if (follow.current.following && !dragging.current) scrollLatest();
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
  const chooseReply = (message: Message) => {
    if (!latestAccess.current || !live.current || !hiddenRef.current.ready || hiddenRef.current.ids.has(message.id)) return;
    setActionsFor(null);
    replyRevision.current++;
    setReply(message);
    input.current?.focus();
  };
  const operationCurrent = (scope: string, operation: number) => live.current && currentActionScope.current === scope
    && actionOperation.current === operation && AppState.currentState === 'active';
  const showInfo = async (message: Message) => {
    if (currentActionScope.current !== actionScope || !live.current || !chat.presentationReady || AppState.currentState !== 'active') return;
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
    if (currentActionScope.current !== actionScope || !live.current || !chat.presentationReady || AppState.currentState !== 'active') return;
    const requested = actionScope, operation = ++actionOperation.current;
    setActionsFor(null); setActionBusy(true); setLocalError(null);
    try {
      const ids = await engine.setMessageHidden(room, messageId, hidden);
      if (operationCurrent(requested, operation)) {
        setHiddenState({ scope: requested, ids }); setInfo(null);
        if (hidden && reply?.id === messageId) { replyRevision.current++; setReply(null); }
      }
    } catch (e) { if (operationCurrent(requested, operation)) setLocalError(errorWord(e)); }
    finally { if (operationCurrent(requested, operation)) setActionBusy(false); }
  };
  const confirmHide = (messageId: number) => {
    if (currentActionScope.current !== actionScope || !live.current || !chat.presentationReady || AppState.currentState !== 'active') return;
    const requested = actionScope;
    Alert.alert(t('hideLocal'), t('hideLocalConfirm'), [
      { text: t('cancel'), style: 'cancel' },
      { text: t('hideLocal'), style: 'destructive', onPress: () => {
        if (currentActionScope.current === requested && live.current) void changeHidden(messageId, true);
      } },
    ]);
  };
  const openOriginal = async (messageId: number) => {
    if (currentActionScope.current !== actionScope || !live.current || !chat.presentationReady || AppState.currentState !== 'active') return;
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
      const active = AppState.currentState === 'active' && chat.presentationReady && !chat.offline;
      for (const id of visibleReadIds(
        viewableItems.filter(item => item.isViewable && hiddenRef.current.ready && !hiddenRef.current.ids.has(item.item.message?.id ?? 0)).map(item => item.item),
        chat.identity?.user_id ?? 0,
        active,
      )) {
        if (receiptBusy.current.has(id)) continue;
        receiptBusy.current.add(id);
        void engine
          .acknowledge(room, id, 'read')
          .then(ack => {
            if (ack && receiptLive.current) chat.capture();
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
    if (sendBusy.current || !canSend) return;
    sendBusy.current = true;
    const submittedDraft = draftRevision.current;
    const submittedReply = replyRevision.current;
    setSending(true);
    setLocalError(null);
    try {
      if (attachment) await engine.enqueueAttachment(room, attachment, text, reply?.id);
      else await engine.enqueue(room, text, reply?.id);
      if (!live.current || !latestAccess.current) return;
      chat.soundSent?.(room);
      if (!browsing.current) follow.current.ownEnqueued();
      setShowLatest(browsing.current);
      if (submittedDraft === draftRevision.current) setText('');
      if (submittedReply === replyRevision.current) setReply(null);
      setActionsFor(null);
      chat.capture();
      if (!browsing.current) scrollLatest();
      // The durable local queue owns retry/ACK. Network latency must not hold the composer lock.
      if (!chat.offline) void chat.sync().catch(() => undefined);
    } catch (e) {
      setLocalError(errorWord(e));
    } finally {
      sendBusy.current = false;
      setSending(false);
    }
  };
  const rows: Row[] = useMemo(() => [
    ...chat.history.messages.map(message => ({ key: `message-${message.id}`, message })),
    ...chat.pending
      .filter(item => item.room_id === room.id && item.company_id === room.company_id && item.membership_id === room.membership_id)
      .map(pending => ({ key: pending.client_uuid, pending })),
  ], [chat.history.messages, chat.pending, room.id, room.company_id, room.membership_id]);
  const rowPresentation = useMemo(() => ({ mediaKey, hiddenState, actionsFor, jumpTarget, actionBusy, visibleImages, language, canSend, viewMedia }),
    [mediaKey, hiddenState, actionsFor, jumpTarget, actionBusy, visibleImages, language, canSend, viewMedia]);
  useEffect(() => {
    if (jumpTarget?.scope !== actionScope) return;
    const index = rows.findIndex(row => row.message?.id === jumpTarget.id);
    if (index < 0) return;
    const requested = actionScope;
    const frame = requestAnimationFrame(() => {
      if (live.current && currentActionScope.current === requested)
        list.current?.scrollToIndex({ index, animated: false, viewPosition: 0.4 });
    });
    return () => cancelAnimationFrame(frame);
  }, [jumpTarget, actionScope, chat.history.messages]);
  const lastKey = rows[rows.length - 1]?.key;
  useEffect(() => {
    if (browsing.current) { follow.current.following = false; setShowLatest(true); return; }
    if (follow.current.rows(lastKey)) scrollLatest();
    else if (lastKey && !follow.current.following) setShowLatest(true);
  }, [lastKey, scrollLatest, chat.history.archive?.browsing]);
  const companyName = companyDisplayName(
    chat.identity?.profile?.companies.find(company => company.id === room.company_id),
    language,
    room.company_id,
  );
  // AppShell owns the blocked/verification view. Never reveal retained rows if this screen is
  // rendered during a scope transition or without the server-authorized company/view right.
  if (
    !chat.presentationReady ||
    !chat.identity?.company_ids.includes(room.company_id) ||
    chat.identity.permissions.chat_view !== true
  )
    return null;
  return (
    <View
      ref={keyboardFrame}
      style={[styles.fill, { minHeight: 0 }]}
      onLayout={() => {
        const requested = ++keyboardMeasure.current;
        keyboardFrame.current?.measureInWindow((_x, y) => {
          if (receiptLive.current && requested === keyboardMeasure.current) setKeyboardOffset(y);
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
            {onMenu && <IconButton icon="menu" label={t('menu')} onPress={onMenu} />}
            <GroupAvatar engine={engine} room={room} enabled={chat.presentationReady} size={38} />
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
                onPress={manage}
              />
            )}
            {back && (
              <IconButton
                icon="back"
                label={t('back')}
                onPress={back}
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
              if (event?.nativeEvent?.layout)
                scrollGeometry.current.viewport = event.nativeEvent.layout.height;
              followGeometry();
            }}
            onContentSizeChange={(_width, height) => {
              if (typeof height === 'number') scrollGeometry.current.content = height;
              followGeometry();
            }}
            scrollEventThrottle={16}
            onScrollBeginDrag={() => {
              dragging.current = true;
              if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
              scrollFrame.current = null;
            }}
            onScrollEndDrag={() => {
              dragging.current = false;
            }}
            onMomentumScrollBegin={() => {
              dragging.current = true;
              if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
              scrollFrame.current = null;
            }}
            onMomentumScrollEnd={() => {
              dragging.current = false;
            }}
            onScroll={event => {
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
                    follow.current.following = false; setShowLatest(true);
                    void chat.older().catch(() => undefined);
                  }}
                />
              ) : null}
              </View>
            }
            ListFooterComponent={chat.history.archive?.browsing && chat.history.archive.newer.kind === 'cached' ? <Button quiet title={t('newer')} disabled={chat.busy} onPress={() => { void chat.newer().catch(() => undefined); }} /> : null}
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
              if (message && (!hiddenReady || hiddenIds.has(message.id))) return (
                <View style={{ alignSelf: 'center', marginVertical: 5, padding: 10, borderRadius: 12, backgroundColor: colors.pale }}>
                  <Label language={language} muted>{t(hiddenReady ? 'locallyHidden' : 'loading')}</Label>
                  {hiddenReady && <Button quiet title={t('undoHide')} busy={actionBusy} onPress={() => { void changeHidden(message.id, false); }} />}
                </View>
              );
              return (
                <SwipeReply gestureKey={`${actionScope}/${message?.id ?? pending?.client_uuid}`} enabled={!!message && canSend} language={language} onReply={() => { if (message) chooseReply(message); }}
                  style={{
                    alignSelf: own
                      ? language === 'ar' ? 'flex-start' : 'flex-end'
                      : language === 'ar' ? 'flex-end' : 'flex-start',
                    width: 'auto', maxWidth: '86%', minWidth: 100, marginVertical: 4,
                  }}>
                <Pressable
                  accessibilityLabel={
                    message ? `${message.author_name}: ${message.text}` : pending?.text
                  }
                  accessibilityActions={
                    message ? [
                      ...(canSend ? [{ name: 'reply', label: t('reply') }] : []),
                      { name: 'info', label: t('messageInfo') }, { name: 'hide', label: t('hideLocal') },
                    ] : []
                  }
                  onAccessibilityAction={event => {
                    if (event.nativeEvent.actionName === 'reply' && message) chooseReply(message);
                    if (event.nativeEvent.actionName === 'info' && message) void showInfo(message);
                    if (event.nativeEvent.actionName === 'hide' && message) confirmHide(message.id);
                  }}
                  onPress={() => {
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
                        borderBottomLeftRadius: !!own === (language === 'ar') ? 5 : 18,
                        borderBottomRightRadius: !!own === (language === 'ar') ? 18 : 5,
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
                    {viewMedia && pending?.attachment && (
                      <Label language={language} muted>
                        {pending.attachment.name}
                      </Label>
                    )}
                    <View
                      style={{
                        flexDirection: 'row',
                        alignItems: 'center',
                        gap: 4,
                        alignSelf: language === 'ar' ? 'flex-start' : 'flex-end',
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
                      <IconButton icon="trash" label={t('hideLocal')} tone="danger" disabled={actionBusy} onPress={() => confirmHide(message.id)} />
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
                  const finish = () => { if (live.current) { follow.current.ownEnqueued(); setShowLatest(false); scrollLatest(); } };
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
          {!canSend ? (
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
                      replyRevision.current++;
                      setReply(null);
                    }}
                  />
                </View>
              )}
              <AttachmentTools
                room={room}
                disabled={sending}
                voice={voice}
                enqueue={send}
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
                  editable={!voice.recording}
                />
              </AttachmentTools>
            </>
          )}
        </View>
      </KeyboardAvoidingView>
      {info?.scope === actionScope && hiddenReady && !hiddenIds.has(info.message.id) && (
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
