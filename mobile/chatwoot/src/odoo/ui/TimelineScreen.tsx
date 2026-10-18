import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AppState,
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
import { Button, colors, direction, Field, Icon, IconButton, Label, styles } from './components';
import { companyDisplayName } from './companyNames';
import { MessageQuote, MessageStatus } from './MessagePresentation';
import { TimelineFollow } from './timelineFollow';
import { errorWord, type Language, type Translate, type Word } from './dictionary';
import { AttachmentTools, MediaTile, useVoiceSession } from './MediaTools';
import type { ChatView } from './useChat';
import {
  canViewMedia,
  conversationAccess,
  messageTime,
  presentationKey,
  visibleReadIds,
} from './viewModel';

type Row = { key: string; message?: Message; pending?: Pending };
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
  const voice = useVoiceSession(mediaKey, setLocalError, viewMedia, canAttach);
  const sendBusy = useRef(false);
  const draftRevision = useRef(0);
  const replyRevision = useRef(0);
  const list = useRef<FlashListRef<Row>>(null);
  const input = useRef<TextInput>(null);
  const follow = useRef(new TimelineFollow());
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
        if (!live.current || dragging.current || !follow.current.following) return;
        let { content, viewport, offset } = scrollGeometry.current;
        const current = list.current;
        try {
          if (current?.getChildContainerDimensions && current.getWindowSize && current.getAbsoluteLastScrollOffset) {
            content = current.getChildContainerDimensions().height + current.getFirstItemOffset();
            viewport = current.getWindowSize().height;
            offset = current.getAbsoluteLastScrollOffset();
          }
        } catch { /* Before FlashList initializes, use the latest native measurements. */ }
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
      shown.remove(); hidden.remove();
      if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
    };
  }, [followGeometry]);
  const chooseReply = (message: Message) => {
    if (!latestAccess.current || !live.current) return;
    setActionsFor(null);
    replyRevision.current++;
    setReply(message);
    input.current?.focus();
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
        viewableItems.filter(item => item.isViewable).map(item => item.item),
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
      follow.current.ownEnqueued();
      setShowLatest(false);
      if (submittedDraft === draftRevision.current) setText('');
      if (submittedReply === replyRevision.current) setReply(null);
      setActionsFor(null);
      chat.capture();
      scrollLatest();
      // The durable local queue owns retry/ACK. Network latency must not hold the composer lock.
      if (!chat.offline) void chat.sync().catch(() => undefined);
    } catch (e) {
      setLocalError(errorWord(e));
    } finally {
      sendBusy.current = false;
      setSending(false);
    }
  };
  const rows: Row[] = [
    ...chat.history.messages.map(message => ({ key: `message-${message.id}`, message })),
    ...chat.pending
      .filter(item => item.room_id === room.id)
      .map(pending => ({ key: pending.client_uuid, pending })),
  ];
  const lastKey = rows[rows.length - 1]?.key;
  useEffect(() => {
    if (follow.current.rows(lastKey)) scrollLatest();
    else if (lastKey && !follow.current.following) setShowLatest(true);
  }, [lastKey, scrollLatest]);
  const companyName = companyDisplayName(
    chat.identity?.profile?.companies.find(company => company.id === room.company_id), language, room.company_id,
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
              { flexWrap: 'nowrap', flexDirection: language === 'ar' ? 'row-reverse' : 'row' },
            ]}>
            {back && (
              <IconButton
                icon="back"
                label={t('back')}
                onPress={back}
                style={language === 'ar' ? { transform: [{ rotate: '180deg' }] } : undefined}
              />
            )}
            {onMenu && <IconButton icon="menu" label={t('menu')} onPress={onMenu} />}
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
          </View>
        </View>
        <View style={{ flex: 1, minHeight: 0 }}>
          <FlashList
            ref={list}
            extraData={mediaKey}
            data={rows}
            viewabilityConfig={{ minimumViewTime: 600, viewAreaCoveragePercentThreshold: 75 }}
            onViewableItemsChanged={visibleChanged}
            keyExtractor={row => row.key}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="none"
            onLoad={followGeometry}
            onCommitLayoutEffect={followGeometry}
            onLayout={event => {
              if (event?.nativeEvent?.layout) scrollGeometry.current.viewport = event.nativeEvent.layout.height;
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
            onScrollEndDrag={() => { dragging.current = false; }}
            onMomentumScrollBegin={() => {
              dragging.current = true;
              if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
              scrollFrame.current = null;
            }}
            onMomentumScrollEnd={() => { dragging.current = false; }}
            onScroll={event => {
              const { contentSize, layoutMeasurement, contentOffset } = event.nativeEvent;
              scrollGeometry.current = { content: contentSize.height, viewport: layoutMeasurement.height, offset: contentOffset.y };
              // Only gestures change reader intent in either direction. Expanding the viewport
              // may expose the last row, but must not re-arm following when IME opens again.
              if (!dragging.current) return;
              const atBottom = follow.current.scroll(contentSize.height, layoutMeasurement.height, contentOffset.y);
              setShowLatest(!atBottom);
            }}
            contentContainerStyle={{ paddingHorizontal: 12, paddingVertical: 10 }}
            maintainVisibleContentPosition={{ startRenderingFromBottom: true }}
            ListHeaderComponent={
              chat.history.next_before_id ? (
                <Button
                  quiet
                  title={t('older')}
                  disabled={chat.offline || chat.busy}
                  onPress={() => {
                    void chat.older().catch(() => undefined);
                  }}
                />
              ) : null
            }
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
              return (
                <Pressable
                  accessibilityLabel={message ? `${message.author_name}: ${message.text}` : pending?.text}
                  accessibilityActions={message && canSend ? [{ name: 'reply', label: t('reply') }] : []}
                  onAccessibilityAction={event => { if (event.nativeEvent.actionName === 'reply' && message) chooseReply(message); }}
                  onPress={() => { if (message && canSend) setActionsFor(actionsFor === message.id ? null : message.id); }}
                  onLongPress={() => { if (message) chooseReply(message); }}
                  style={{
                    alignSelf: own
                      ? language === 'ar'
                        ? 'flex-start'
                        : 'flex-end'
                      : language === 'ar'
                        ? 'flex-end'
                        : 'flex-start',
                    width: 'auto',
                    maxWidth: '86%',
                    minWidth: 100,
                    marginVertical: 4,
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
                      <MessageQuote language={language}
                        author={String(message?.reply?.author_name ?? chat.history.messages.find(m => m.id === pending?.reply_to_message_id)?.author_name ?? '')}
                        text={message?.reply?.unavailable ? t('unavailable') : String(message?.reply?.text ?? chat.history.messages.find(m => m.id === pending?.reply_to_message_id)?.text ?? t('unavailable'))} />
                    )}
                    {!!(message?.text || pending?.text) && (
                      <Text selectable style={[styles.text, direction(language)]}>
                        {message?.text ?? pending?.text}
                      </Text>
                    )}
                    {viewMedia && message?.media && (
                      <MediaTile
                        key={`${mediaKey}/${message.id}/${String(message.media.id)}`}
                        scopeKey={`${chat.identity?.database}/${mediaKey}`}
                        room={room}
                        media={message.media}
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
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4,
                      alignSelf: language === 'ar' ? 'flex-start' : 'flex-end' }}>
                      {message?.created_at && (
                        <Text style={[styles.muted, { fontSize: 11, lineHeight: 16 }]}>
                          {messageTime(message.created_at)}
                        </Text>
                      )}
                      {own && <MessageStatus state={state} t={t} />}
                    </View>
                  </View>
                  {message && canSend && actionsFor === message.id && (
                    <View style={{ backgroundColor: colors.white, alignSelf: 'flex-start', borderRadius: 16,
                      flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8, marginTop: 4 }}>
                      <IconButton icon="reply" label={t('reply')} onPress={() => chooseReply(message)} />
                      <Text style={styles.muted}>{t('reply')}</Text>
                    </View>
                  )}
                </Pressable>
              );
            }}
          />
          {showLatest && (
            <View style={{ position: 'absolute', bottom: 8, right: 12, backgroundColor: colors.white,
              borderRadius: 24, borderWidth: 1, borderColor: colors.border }}>
              <IconButton icon="down" label={t('latest')} onPress={() => {
                follow.current.ownEnqueued(); setShowLatest(false); scrollLatest();
              }} />
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
                <View style={[styles.row, { flexWrap: 'nowrap', flexDirection: language === 'ar' ? 'row-reverse' : 'row', backgroundColor: colors.pale, borderRadius: 12, paddingHorizontal: 4 }]}>
                  <Icon icon="reply" size={18} color={colors.blue} />
                  <View style={styles.fill}>
                    <MessageQuote author={reply.author_name} text={reply.text} language={language} />
                  </View>
                  <IconButton icon="close" label={t('cancel')} onPress={() => { replyRevision.current++; setReply(null); }} />
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
                  onChangeText={value => { draftRevision.current++; setText(value); }}
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
    </View>
  );
}
