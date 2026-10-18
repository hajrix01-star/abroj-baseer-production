import React, { useEffect, useRef, useState } from 'react';
import { AppState, Image, PermissionsAndroid, Platform, View } from 'react-native';
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
import { Button, Label, styles } from './components';
import { errorWord, type Language, type Translate, type Word } from './dictionary';

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
}: {
  room: Room;
  disabled: boolean;
  voice: VoiceSession;
  enqueue: (attachment: Attachment) => Promise<void>;
  language: Language;
  t: Translate;
  report: (word: Word) => void;
}) {
  const [busy, setBusy] = useState(false);
  const attach = async (kind: 'image' | 'file') => {
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
      setBusy(false);
    }
  };
  return (
    <View style={{ gap: 8 }}>
      {voice.recording ? (
        <View style={styles.row}>
          <Label language={language}>
            {t('recording')} · {String(Math.floor(voice.seconds / 60)).padStart(2, '0')}:
            {String(voice.seconds % 60).padStart(2, '0')}
          </Label>
          <Button
            title={t('stopSend')}
            disabled={busy || disabled}
            onPress={() => {
              setBusy(true);
              void voice
                .finish(room)
                .then(async attachment => {
                  if (attachment) await enqueue(attachment);
                })
                .catch(e => report(errorWord(e)))
                .finally(() => setBusy(false));
            }}
          />
          <Button
            quiet
            title={t('cancel')}
            onPress={() => {
              void voice.stop();
            }}
          />
        </View>
      ) : (
        <View style={[styles.row, { flexDirection: language === 'ar' ? 'row-reverse' : 'row' }]}>
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
          <Button
            quiet
            title={t('voice')}
            disabled={disabled || busy}
            onPress={() => {
              void voice.start();
            }}
          />
        </View>
      )}
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
}: {
  room: Room;
  media: Record<string, unknown>;
  voice: VoiceSession;
  t: Translate;
  language: Language;
  report: (word: Word) => void;
}) {
  const [uri, setUri] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const live = useRef(true);
  useEffect(
    () => () => {
      live.current = false;
    },
    [],
  );
  const open = async () => {
    setBusy(true);
    try {
      const local = await localMedia(room, media);
      if (!live.current) return;
      if (media.kind === 'image') setUri(local);
      else if (media.kind === 'audio') await voice.play(local);
      else await FileViewer.open(local.replace(/^file:\/\//, ''), { showOpenWithDialog: true });
    } catch (e) {
      if (live.current) report(errorWord(e));
    } finally {
      if (live.current) setBusy(false);
    }
  };
  return (
    <View style={{ gap: 8 }}>
      <Label language={language} muted>
        {String(media.name ?? t('file'))}
      </Label>
      {uri && (
        <Image
          accessibilityLabel={String(media.name ?? t('photo'))}
          source={{ uri }}
          resizeMode="contain"
          style={{ width: 240, maxWidth: '100%', height: 180, borderRadius: 12 }}
        />
      )}
      <Button
        quiet
        title={media.kind === 'audio' ? t('play') : t('open')}
        busy={busy}
        onPress={() => {
          void open();
        }}
      />
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
