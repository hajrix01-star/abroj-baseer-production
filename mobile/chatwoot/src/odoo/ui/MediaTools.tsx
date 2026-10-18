import React, { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  AppState,
  Image,
  PermissionsAndroid,
  Platform,
  Pressable,
  View,
} from 'react-native';
import { pick, types, isErrorWithCode, errorCodes } from '@react-native-documents/picker';
import { launchImageLibrary } from 'react-native-image-picker';
import FileViewer from 'react-native-file-viewer';
import BlobUtil from 'react-native-blob-util';
import AudioRecorderPlayer, {
  AudioEncoderAndroidType,
  AudioSourceAndroidType,
  AVEncodingOption,
  OutputFormatAndroidType,
} from 'react-native-audio-recorder-player';
import type { Attachment, Room } from '../core/ChatEngine';
import { localMedia, stageFile } from '../runtime';
import { Button, colors, Icon, IconButton, Label, styles } from './components';
import { errorWord, type Language, type Translate, type Word } from './dictionary';
import { ImageViewer } from './ImageViewer';

export function useVoiceSession(
  scope: string,
  report: (word: Word) => void,
  canPlay: boolean,
  canRecord: boolean,
) {
  const [player] = useState(() => new AudioRecorderPlayer());
  const allowed = useRef({ canPlay, canRecord });
  allowed.current = { canPlay, canRecord };
  const starting = useRef(false);
  const alive = useRef(true);
  const token = useRef(0);
  const temporary = useRef<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [playing, setPlaying] = useState(false);
  const cleanup = async () => {
    token.current++;
    player.removeRecordBackListener();
    player.removePlayBackListener();
    try {
      await player.stopRecorder();
    } catch {
      /* No recorder active. */
    }
    try {
      await player.stopPlayer();
    } catch {
      /* No player active. */
    }
    const path = temporary.current;
    temporary.current = null;
    if (path) {
      try {
        await BlobUtil.fs.unlink(path.replace(/^file:\/\//, ''));
      } catch {
        /* Already staged or deleted. */
      }
    }
    if (alive.current) {
      setRecording(false);
      setPlaying(false);
      setSeconds(0);
    }
  };
  useEffect(() => {
    alive.current = true;
    const listener = AppState.addEventListener('change', state => {
      if (state !== 'active') void cleanup();
    });
    return () => {
      alive.current = false;
      listener.remove();
      void cleanup();
    };
    // The room/account scope owns the native session and temporary bytes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, canPlay, canRecord]);
  const start = async () => {
    if (starting.current || recording || !allowed.current.canRecord) return;
    starting.current = true;
    try {
      const requested = ++token.current;
      if (Platform.OS === 'android') {
        const result = await PermissionsAndroid.request(
          PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,
        );
        if (requested !== token.current || !alive.current) return;
        if (result !== PermissionsAndroid.RESULTS.GRANTED) {
          report('noMicrophone');
          return;
        }
      }
      if (
        !alive.current ||
        !allowed.current.canRecord ||
        AppState.currentState !== 'active' ||
        requested !== token.current
      )
        return;
      await cleanup();
      const current = ++token.current;
      const path = `${BlobUtil.fs.dirs.CacheDir}/odoo-voice-${Date.now()}.m4a`;
      temporary.current = path;
      try {
        await player.startRecorder(path, {
          AudioSourceAndroid: AudioSourceAndroidType.MIC,
          OutputFormatAndroid: OutputFormatAndroidType.MPEG_4,
          AudioEncoderAndroid: AudioEncoderAndroidType.AAC,
          AudioSamplingRateAndroid: 44100,
          AudioEncodingBitRateAndroid: 96000,
          AudioChannelsAndroid: 1,
          AVFormatIDKeyIOS: AVEncodingOption.aac,
          AVNumberOfChannelsKeyIOS: 1,
          AVSampleRateKeyIOS: 44100,
        });
        if (current !== token.current || !allowed.current.canRecord) {
          await cleanup();
          return;
        }
        setRecording(true);
        player.addRecordBackListener(event => {
          if (current === token.current) setSeconds(Math.floor(event.currentPosition / 1000));
        });
      } catch {
        await cleanup();
        report('error');
      }
    } catch {
      report('error');
    } finally {
      starting.current = false;
    }
  };
  const finish = async (room: Room): Promise<Attachment | null> => {
    const current = token.current;
    try {
      const path = await player.stopRecorder();
      player.removeRecordBackListener();
      if (current !== token.current || !allowed.current.canRecord || !alive.current) return null;
      setRecording(false);
      const attachment = await stageFile(room, {
        uri: path.startsWith('file://') ? path : `file://${path}`,
        name: `voice-${Date.now()}.m4a`,
        mime: 'audio/mp4',
        kind: 'audio',
      });
      if (current !== token.current || !allowed.current.canRecord || !alive.current) return null;
      await cleanup();
      return attachment;
    } catch (e) {
      await cleanup();
      report(errorWord(e));
      return null;
    }
  };
  const play = async (uri: string) => {
    if (!allowed.current.canPlay || !alive.current || AppState.currentState !== 'active') return;
    await cleanup();
    const current = ++token.current;
    try {
      await player.startPlayer(uri);
      if (current !== token.current || !allowed.current.canPlay || !alive.current) {
        await player.stopPlayer();
        return;
      }
      setPlaying(true);
      player.addPlayBackListener(event => {
        if (
          current === token.current &&
          event.currentPosition >= event.duration &&
          event.duration > 0
        )
          void cleanup();
      });
    } catch {
      await cleanup();
      report('error');
    }
  };
  return { recording, seconds, playing, start, finish, play, stop: cleanup };
}
export type VoiceSession = ReturnType<typeof useVoiceSession>;

export function AttachmentTools({
  room,
  disabled,
  voice,
  enqueue,
  language,
  t,
  report,
  children,
  hasText,
  onSendText,
  allowAttachments = true,
}: {
  room: Room;
  disabled: boolean;
  voice: VoiceSession;
  enqueue: (attachment: Attachment) => Promise<void>;
  language: Language;
  t: Translate;
  report: (word: Word) => void;
  children?: React.ReactNode;
  hasText: boolean;
  onSendText: () => void;
  allowAttachments?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const operation = useRef(false);
  useEffect(() => {
    if (disabled || !allowAttachments || voice.recording) setExpanded(false);
  }, [disabled, allowAttachments, voice.recording]);
  const attach = async (kind: 'image' | 'file') => {
    if (disabled || !allowAttachments || operation.current || voice.recording) return;
    operation.current = true;
    setExpanded(false);
    setBusy(true);
    try {
      if (kind === 'image') {
        const result = await launchImageLibrary({
          mediaType: 'photo',
          selectionLimit: 1,
          quality: 0.9,
        });
        if (result.didCancel) return;
        const asset = result.assets?.[0];
        if (!asset?.uri || result.errorCode) throw new Error('picker');
        const staged = await stageFile(room, {
          uri: asset.uri,
          name: asset.fileName || 'image.jpg',
          mime: asset.type || 'image/jpeg',
          kind: 'image',
        });
        await enqueue(staged);
      } else {
        const [file] = await pick({
          type: [types.pdf, types.plainText, types.docx, types.xlsx],
          allowMultiSelection: false,
        });
        if (!file) return;
        const staged = await stageFile(room, {
          uri: file.uri,
          name: file.name || 'attachment',
          mime: file.type || 'application/octet-stream',
          kind: 'file',
        });
        await enqueue(staged);
      }
    } catch (e) {
      if (!(isErrorWithCode(e) && e.code === errorCodes.OPERATION_CANCELED)) report(errorWord(e));
    } finally {
      operation.current = false;
      setBusy(false);
    }
  };
  const voiceAction = async () => {
    if (disabled || !allowAttachments || operation.current) return;
    operation.current = true;
    setExpanded(false);
    setBusy(true);
    try {
      if (voice.recording) {
        const attachment = await voice.finish(room);
        if (attachment) await enqueue(attachment);
      } else await voice.start();
    } catch (e) {
      report(errorWord(e));
    } finally {
      operation.current = false;
      setBusy(false);
    }
  };
  return (
    <View style={{ gap: 8, width: '100%' }}>
      {expanded && allowAttachments && !voice.recording && (
        <View
          style={[
            styles.row,
            { paddingHorizontal: 8, flexDirection: language === 'ar' ? 'row-reverse' : 'row' },
          ]}>
          <Button
            quiet
            title={t('photo')}
            disabled={disabled || busy}
            onPress={() => {
              void attach('image');
            }}
          />
          <Button
            quiet
            title={t('file')}
            disabled={disabled || busy}
            onPress={() => {
              void attach('file');
            }}
          />
        </View>
      )}
      <View
        style={{
          flexDirection: language === 'ar' ? 'row-reverse' : 'row',
          alignItems: 'flex-end',
          gap: 8,
        }}>
        <View
          style={{
            flex: 1,
            minWidth: 0,
            minHeight: 48,
            borderRadius: 25,
            backgroundColor: colors.white,
            flexDirection: language === 'ar' ? 'row-reverse' : 'row',
            alignItems: 'center',
            paddingHorizontal: 2,
            borderWidth: 1,
            borderColor: colors.border,
          }}>
          {voice.recording ? (
            <>
              <IconButton
                icon="close"
                tone="danger"
                label={t('cancel')}
                onPress={() => {
                  void voice.stop();
                }}
              />
              <View style={{ flex: 1, minWidth: 0, paddingHorizontal: 6, paddingVertical: 5 }}>
                <Label language={language} muted>
                  {t('recording')} · {String(Math.floor(voice.seconds / 60)).padStart(2, '0')}:
                  {String(voice.seconds % 60).padStart(2, '0')}
                </Label>
                <Label language={language} muted>
                  {t('stopSend')}
                </Label>
              </View>
            </>
          ) : (
            <>
              {allowAttachments && (
                <IconButton
                  icon="attach"
                  label={t('attachments')}
                  disabled={disabled || busy}
                  onPress={() => {
                    if (!operation.current && !disabled) setExpanded(!expanded);
                  }}
                />
              )}
              {children}
            </>
          )}
        </View>
        <IconButton
          icon={voice.recording ? 'stop' : hasText ? 'send' : 'mic'}
          label={voice.recording ? t('stopSend') : hasText ? t('send') : t('voice')}
          tone="primary"
          size={22}
          style={{ width: 48, height: 48, borderRadius: 24 }}
          busy={busy}
          disabled={disabled || busy || (!hasText && !allowAttachments)}
          onPress={() => {
            if (disabled || operation.current) return;
            if (!voice.recording && hasText) onSendText();
            else void voiceAction();
          }}
        />
      </View>
    </View>
  );
}

export function MediaTile({
  room,
  media,
  voice,
  t,
  language,
  report,
  scopeKey = '',
}: {
  room: Room;
  media: Record<string, unknown>;
  voice: VoiceSession;
  t: Translate;
  language: Language;
  report: (word: Word) => void;
  scopeKey?: string;
}) {
  // FlashList may recycle the same component for another attachment. Tag every
  // presentation and pending result, so an old image cannot flash in a new row.
  const key = JSON.stringify([
    scopeKey,
    room.company_id,
    room.id,
    room.membership_id,
    media.id,
    media.kind,
    media.mime,
    media.size,
    media.sha256,
    media.name,
  ]);
  const [cached, setCached] = useState<{ key: string; uri: string } | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const [showing, setShowing] = useState<string | null>(null);
  const live = useRef({ key, revision: 0, serial: 0, active: true, busy: false });
  if (live.current.key !== key) {
    live.current = {
      key,
      revision: live.current.revision + 1,
      serial: live.current.serial + 1,
      active: true,
      busy: false,
    };
  }
  const presentation = `${key}/${live.current.revision}`;
  const uri = cached?.key === presentation ? cached.uri : null;
  const busy = opening === presentation;
  useEffect(() => {
    live.current.active = AppState.currentState === 'active';
    const invalidate = () => {
      live.current.serial++;
      live.current.busy = false;
      setShowing(null);
      setOpening(null);
    };
    const listener = AppState.addEventListener('change', state => {
      live.current.active = state === 'active';
      if (state !== 'active') invalidate();
    });
    return () => {
      live.current.active = false;
      live.current.serial++;
      live.current.busy = false;
      listener.remove();
    };
  }, [key]);
  const open = async () => {
    if (
      !live.current.active ||
      live.current.key !== key ||
      live.current.busy ||
      AppState.currentState !== 'active'
    )
      return;
    live.current.busy = true;
    const serial = ++live.current.serial;
    const current = () =>
      live.current.active &&
      live.current.key === key &&
      live.current.serial === serial &&
      AppState.currentState === 'active';
    setOpening(presentation);
    try {
      // Keep runtime's association, identity, permission, hash and session fences.
      // No effect automatically downloads history images, and no remote URI is rendered.
      const local = await localMedia(room, media);
      if (!current()) return;
      if (media.kind === 'image') {
        if (!local.startsWith('file://')) throw new Error('invalid_local_image');
        setCached({ key: presentation, uri: local });
        setShowing(presentation);
      } else if (media.kind === 'audio') await voice.play(local);
      else await FileViewer.open(local.replace(/^file:\/\//, ''), { showOpenWithDialog: true });
    } catch (e) {
      if (current()) report(errorWord(e));
    } finally {
      if (current()) {
        live.current.busy = false;
        setOpening(null);
      }
    }
  };
  return (
    <View style={{ gap: 8 }}>
      <Label language={language} muted>
        {String(media.name ?? t('file'))}
      </Label>
      {media.kind === 'image' ? (
        <>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t('viewPhoto')}
            accessibilityHint={t('zoomPhoto')}
            accessibilityState={{ busy, disabled: busy }}
            disabled={busy}
            onPress={() => {
              void open();
            }}
            style={({ pressed }) => ({
              width: 240,
              maxWidth: '100%',
              height: 180,
              borderRadius: 12,
              overflow: 'hidden',
              backgroundColor: colors.pale,
              alignItems: 'center',
              justifyContent: 'center',
              opacity: pressed ? 0.8 : 1,
            })}>
            {uri ? (
              <Image
                source={{ uri }}
                resizeMode="contain"
                accessible={false}
                style={{ width: '100%', height: '100%' }}
              />
            ) : (
              <View style={{ gap: 6, alignItems: 'center', padding: 12 }}>
                <Icon icon="image" size={34} color={colors.blue} />
                <Label language={language} muted>
                  {t('viewPhoto')}
                </Label>
              </View>
            )}
            <View
              pointerEvents="none"
              style={{
                position: 'absolute',
                bottom: 8,
                right: 8,
                width: 36,
                height: 36,
                borderRadius: 18,
                backgroundColor: colors.white,
                alignItems: 'center',
                justifyContent: 'center',
              }}>
              {busy ? (
                <ActivityIndicator color={colors.blue} />
              ) : (
                <Icon icon="maximize" size={20} color={colors.blue} />
              )}
            </View>
          </Pressable>
          {showing === presentation && uri && (
            <ImageViewer
              key={`${presentation}/${uri}`}
              uri={uri}
              name={String(media.name ?? t('photo'))}
              language={language}
              t={t}
              onClose={() => setShowing(null)}
            />
          )}
        </>
      ) : (
        <Button
          quiet
          title={media.kind === 'audio' ? t('play') : t('open')}
          busy={busy}
          onPress={() => {
            void open();
          }}
        />
      )}
      {media.kind === 'audio' && voice.playing && (
        <Button
          quiet
          title={t('stop')}
          onPress={() => {
            void voice.stop();
          }}
        />
      )}
    </View>
  );
}
