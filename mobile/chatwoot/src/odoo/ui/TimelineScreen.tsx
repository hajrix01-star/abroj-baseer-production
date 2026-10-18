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
import { Button, colors, direction, Field, Label, styles } from './components';
import { errorWord, type Language, type Translate, type Word } from './dictionary';
import { AttachmentTools, MediaTile, useVoiceSession } from './MediaTools';
import type { ChatView } from './useChat';
import { canViewMedia, conversationAccess, messageTime, presentationKey, visibleReadIds } from './viewModel';

type Row = { key: string; message?: Message; pending?: Pending };
export function TimelineScreen({
  engine,
  chat,
  language,
  t,
  back,
  manage,
}: {
  engine: ChatEngine;
  chat: ChatView;
  language: Language;
  t: Translate;
  back?: () => void;
  manage: () => void;
}) {
  const room = chat.selected!;
  const [text, setText] = useState('');
  const [reply, setReply] = useState<Message | null>(null);
  const [localError, setLocalError] = useState<Word | null>(null);
  const [sending, setSending] = useState(false);
  const { directOff, canSend, canAttach } = conversationAccess(chat.identity, room);
  const viewMedia = canViewMedia(chat.identity, room);
  const mediaKey = presentationKey(chat.identity, room);
  const voice = useVoiceSession(mediaKey, setLocalError, viewMedia, canAttach);
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
    if (sending) return;
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
      setSending(false);
    }
  };
  const rows: Row[] = [
    ...chat.history.messages.map(message => ({ key: `message-${message.id}`, message })),
    ...chat.pending
      .filter(item => item.room_id === room.id)
      .map(pending => ({ key: pending.client_uuid, pending })),
  ];
  return (
    <KeyboardAvoidingView
      style={styles.fill}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={styles.header}>
        <View style={[styles.row, { flexDirection: language === 'ar' ? 'row-reverse' : 'row' }]}>
          {back && <Button quiet title={t('back')} onPress={back} />}
          <View style={styles.fill}>
            <Text style={[styles.title, direction(language)]}>{room.name}</Text>
            <Label language={language} muted>
              {room.is_group ? t('members') : t('direct')}
            </Label>
          </View>
          {room.is_group && (
            <Button quiet title={t('members')} disabled={chat.offline} onPress={manage} />
          )}
        </View>
      </View>
      <FlashList
        extraData={mediaKey}
        data={rows}
        viewabilityConfig={{ minimumViewTime: 600, viewAreaCoveragePercentThreshold: 75 }}
        onViewableItemsChanged={visibleChanged}
        keyExtractor={row => row.key}
        contentContainerStyle={{ padding: 16 }}
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
                maxWidth: '88%',
                minWidth: 100,
                marginVertical: 6,
              }}>
              <View
                style={[
                  styles.card,
                  {
                    backgroundColor: own ? colors.pale : colors.white,
                    borderWidth: 1,
                    borderColor: colors.border,
                    gap: 6,
                    padding: 12,
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
                    style={{ borderStartWidth: 3, borderStartColor: colors.blue, paddingStart: 9 }}>
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
                    <Text style={styles.muted}>{messageTime(message.created_at)}</Text>
                  )}
                  {own && (
                    <Text
                      style={[
                        styles.muted,
                        pending?.state === 'failed' && { color: colors.danger },
                      ]}>
                      {t(status)}
                    </Text>
                  )}
                  {message && canSend && (
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={t('reply')}
                      hitSlop={8}
                      onPress={() => setReply(message)}>
                      <Text style={{ color: colors.blue, fontSize: 12 }}>{t('reply')}</Text>
                    </Pressable>
                  )}
                </View>
              </View>
            </Pressable>
          );
        }}
      />
      <View style={[styles.header, { borderTopWidth: 1, borderTopColor: colors.border }]}>
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
                <Button quiet title={t('cancel')} onPress={() => setReply(null)} />
              </View>
            )}
            <View
              style={[
                styles.row,
                {
                  flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                  flexWrap: 'nowrap',
                  alignItems: 'flex-end',
                },
              ]}>
              <Field
                language={language}
                multiline
                value={text}
                onChangeText={setText}
                placeholder={t('message')}
                accessibilityLabel={t('message')}
                maxLength={16000}
                style={{ flex: 1, maxHeight: 140 }}
                editable={!voice.recording}
              />
              <Button
                title={t('send')}
                disabled={!text.trim() || voice.recording}
                busy={sending}
                onPress={() => {
                  void send();
                }}
              />
            </View>
            {canAttach && (
              <AttachmentTools
                room={room}
                disabled={sending}
                voice={voice}
                enqueue={send}
                language={language}
                t={t}
                report={setLocalError}
              />
            )}
          </>
        )}
      </View>
    </KeyboardAvoidingView>
  );
}
