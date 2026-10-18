import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AppState,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  Text,
  View,
  type ViewToken,
} from 'react-native';
import { FlashList } from '@shopify/flash-list';
import type { Attachment, ChatEngine, Message, Pending } from '../core/ChatEngine';
import { Button, colors, direction, Field, IconButton, Label, styles } from './components';
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
    setSending(true);
    setLocalError(null);
    try {
      if (attachment) await engine.enqueueAttachment(room, attachment, text, reply?.id);
      else await engine.enqueue(room, text, reply?.id);
      setText('');
      setReply(null);
      chat.capture();
      if (!chat.offline) await chat.sync();
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
                {room.is_group ? t('members') : t('direct')}
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
            extraData={mediaKey}
            data={rows}
            viewabilityConfig={{ minimumViewTime: 600, viewAreaCoveragePercentThreshold: 75 }}
            onViewableItemsChanged={visibleChanged}
            keyExtractor={row => row.key}
            keyboardShouldPersistTaps="handled"
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
              const status: Word = [
                'queued',
                'sending',
                'unknown',
                'failed',
                'sent',
                'delivered',
                'read',
              ].includes(state ?? '')
                ? (state as Word)
                : 'sent';
              return (
                <Pressable
                  onLongPress={() => {
                    if (message && canSend) setReply(message);
                  }}
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
                        borderRadius: 16,
                        borderBottomLeftRadius: !!own === (language === 'ar') ? 5 : 16,
                        borderBottomRightRadius: !!own === (language === 'ar') ? 16 : 5,
                        gap: 4,
                        paddingHorizontal: 11,
                        paddingTop: 9,
                        paddingBottom: 2,
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
                    {message?.reply && (
                      <View
                        style={{
                          borderStartWidth: 3,
                          borderStartColor: colors.blue,
                          paddingStart: 9,
                        }}>
                        <Label language={language} muted>
                          {message.reply.unavailable
                            ? t('unavailable')
                            : `${String(message.reply.author_name ?? '')}: ${String(message.reply.text ?? '')}`}
                        </Label>
                      </View>
                    )}
                    {!!(message?.text || pending?.text) && (
                      <Text selectable style={[styles.text, direction(language)]}>
                        {message?.text ?? pending?.text}
                      </Text>
                    )}
                    {viewMedia && message?.media && (
                      <MediaTile
                        key={`${mediaKey}/${message.id}/${String(message.media.id)}`}
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
                    <View style={[styles.row, { justifyContent: 'space-between' }]}>
                      {message?.created_at && (
                        <Text style={[styles.muted, { fontSize: 11, lineHeight: 16 }]}>
                          {messageTime(message.created_at)}
                        </Text>
                      )}
                      {own && (
                        <Text
                          style={[
                            styles.muted,
                            { fontSize: 11, lineHeight: 16 },
                            pending?.state === 'failed' && { color: colors.danger },
                          ]}>
                          {t(status)}
                        </Text>
                      )}
                      {message && canSend && (
                        <IconButton
                          icon="reply"
                          size={16}
                          label={t('reply')}
                          onPress={() => setReply(message)}
                        />
                      )}
                    </View>
                  </View>
                </Pressable>
              );
            }}
          />
        </View>
        <View
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
                <View style={styles.row}>
                  <View style={styles.fill}>
                    <Label language={language} muted>
                      {t('replying')} {reply.author_name}: {reply.text.slice(0, 80)}
                    </Label>
                  </View>
                  <IconButton icon="close" label={t('cancel')} onPress={() => setReply(null)} />
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
                  language={language}
                  multiline
                  value={text}
                  onChangeText={setText}
                  placeholder={t('message')}
                  accessibilityLabel={t('message')}
                  maxLength={16000}
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
