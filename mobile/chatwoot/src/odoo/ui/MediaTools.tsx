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
import { launchCamera, launchImageLibrary } from 'react-native-image-picker';
import FileViewer from 'react-native-file-viewer';
import BlobUtil from 'react-native-blob-util';
import AudioRecorderPlayer, {
  AudioEncoderAndroidType,
  AudioSourceAndroidType,
  AVEncodingOption,
  OutputFormatAndroidType,
} from 'react-native-audio-recorder-player';
import type { Attachment, Room } from '../core/ChatEngine';
import { localMediaLease, stageFile, type LocalMediaLease } from '../runtime';
import { Button, colors, Icon, IconButton, Label, styles } from './components';
import { errorWord, type Language, type Translate, type Word } from './dictionary';
import { ImageViewer } from './ImageViewer';
import { setFeedbackVoice } from './messageSounds';
import { VoiceBubble } from './VoiceBubble';

// RecorderPlayer's native player is process-wide, including across keyed
// Timeline unmount/remount. A hook-local queue cannot protect a new room.
let nativeVoiceQueue: Promise<unknown> = Promise.resolve();
let nativeVoiceOwner: { id: object; stop(): Promise<void> } | null = null;
function serialNative<T>(operation: () => Promise<T>): Promise<T> {
  const result = nativeVoiceQueue.then(operation, operation);
  nativeVoiceQueue = result.catch(() => undefined); return result;
}

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
  const [paused, setPaused] = useState(false);
  const [activeUri, setActiveUri] = useState<string | null>(null);
  const playback = useRef({ uri: null as string | null, duration: 0 });
  const clock = useRef({ uri: null as string | null, positionMs: 0, durationMs: 0 });
  const clockListeners = useRef(new Set<() => void>());
  const progress = useRef({
    snapshot: () => clock.current,
    subscribe: (listener: () => void) => { clockListeners.current.add(listener); return () => { clockListeners.current.delete(listener); }; },
  });
  const publishProgress = (positionMs: number, durationMs: number, uri: string | null = playback.current.uri) => {
    clock.current = { uri, positionMs, durationMs };
    for (const listener of clockListeners.current) listener();
  };
  const nativeOwner = useRef({});
  const feedbackOwner = useRef({});
  const voiceActive = useRef(false);
  const playbackRelease = useRef<(() => void) | null>(null);
  const prepareCleanup = () => {
    const cleaning = ++token.current;
    const releasingPlayback = playbackRelease.current; playbackRelease.current = null;
    const path = temporary.current;
    temporary.current = null;
    playback.current = { uri: null, duration: 0 };
    return async () => {
      if (nativeVoiceOwner?.id === nativeOwner.current) {
        nativeVoiceOwner = null;
        player.removeRecordBackListener(); player.removePlayBackListener();
        try { await player.stopRecorder(); } catch { /* No recorder active. */ }
        try { await player.stopPlayer(); } catch { /* No player active. */ }
      }
      releasingPlayback?.();
      if (path) { try { await BlobUtil.fs.unlink(path.replace(/^file:\/\//, '')); } catch { /* Already removed. */ } }
      if (alive.current && cleaning === token.current) {
        setRecording(false); setPlaying(false); setPaused(false); setActiveUri(null); publishProgress(0, 0, null); setSeconds(0);
      }
      if (cleaning === token.current) {
        voiceActive.current = false;
        if (!starting.current) setFeedbackVoice(feedbackOwner.current, false);
      }
    };
  };
  const cleanup = () => serialNative(prepareCleanup());
  const claimNative = async () => {
    if (nativeVoiceOwner?.id !== nativeOwner.current) await nativeVoiceOwner?.stop();
    nativeVoiceOwner = { id: nativeOwner.current, stop: () => prepareCleanup()() };
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
    setFeedbackVoice(feedbackOwner.current, true);
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
        await serialNative(async () => {
          if (current !== token.current || !allowed.current.canRecord || !alive.current) return;
          await claimNative();
          return player.startRecorder(path, {
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
        });
        if (current !== token.current || !allowed.current.canRecord) {
          await cleanup();
          return;
        }
        setRecording(true);
        voiceActive.current = true;
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
      setFeedbackVoice(feedbackOwner.current, voiceActive.current);
    }
  };
  const finish = async (room: Room): Promise<Attachment | null> => {
    const current = token.current;
    try {
      const path = await serialNative(() => {
        if (nativeVoiceOwner?.id !== nativeOwner.current) throw new Error('stale_voice');
        return player.stopRecorder();
      });
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
  const play = async (uri: string, release?: () => void) => {
    if (!allowed.current.canPlay || !alive.current || AppState.currentState !== 'active') { release?.(); return; }
    const stopping = cleanup(); const requested = token.current;
    await stopping;
    if (requested !== token.current) { release?.(); return; }
    if (!allowed.current.canPlay || !alive.current || AppState.currentState !== 'active') { release?.(); return; }
    playbackRelease.current = release ?? null;
    setFeedbackVoice(feedbackOwner.current, true);
    const current = ++token.current;
    try {
      await serialNative(async () => {
        if (current !== token.current || !allowed.current.canPlay || !alive.current) return;
        await claimNative(); return player.startPlayer(uri);
      });
      if (current !== token.current || !allowed.current.canPlay || !alive.current) {
        return;
      }
      setPlaying(true);
      setPaused(false); setActiveUri(uri); publishProgress(0, 0, uri);
      playback.current = { uri, duration: 0 };
      voiceActive.current = true;
      player.addPlayBackListener(event => {
        if (current !== token.current || !alive.current) return;
        if (Number.isFinite(event.duration) && event.duration > 0) {
          playback.current.duration = event.duration;
          publishProgress(Number.isFinite(event.currentPosition) ? Math.max(0, Math.min(event.duration, event.currentPosition)) : 0, event.duration);
        }
        if (
          current === token.current &&
          event.currentPosition >= event.duration &&
          event.duration > 0
        )
          void cleanup();
      });
    } catch {
      if (current === token.current) { await cleanup(); report('error'); }
    }
  };
  const pause = async () => {
    const current = token.current;
    await serialNative(async () => {
      if (current !== token.current || nativeVoiceOwner?.id !== nativeOwner.current || !playback.current.uri || !allowed.current.canPlay || !alive.current) return;
      try { await player.pausePlayer(); if (current === token.current && alive.current) { setPlaying(false); setPaused(true); } }
      catch { if (current === token.current) report('error'); }
    });
  };
  const resume = async () => {
    const current = token.current;
    await serialNative(async () => {
      if (current !== token.current || nativeVoiceOwner?.id !== nativeOwner.current || !playback.current.uri || !allowed.current.canPlay || !alive.current || AppState.currentState !== 'active') return;
      try { await player.resumePlayer(); if (current === token.current && alive.current) { setPlaying(true); setPaused(false); } }
      catch { if (current === token.current) report('error'); }
    });
  };
  const seek = async (milliseconds: number) => {
    const current = token.current;
    await serialNative(async () => {
      if (current !== token.current || nativeVoiceOwner?.id !== nativeOwner.current || !playback.current.uri || !allowed.current.canPlay || !alive.current || AppState.currentState !== 'active' || !Number.isFinite(milliseconds) || playback.current.duration <= 0) return;
      const position = Math.max(0, Math.min(playback.current.duration, milliseconds));
      try { await player.seekToPlayer(position); if (current === token.current && alive.current) publishProgress(position, playback.current.duration); }
      catch { if (current === token.current) report('error'); }
    });
  };
  return { recording, seconds, playing, paused, activeUri, positionMs: clock.current.positionMs, durationMs: clock.current.durationMs, progress: progress.current, start, finish, play, pause, resume, seek, stop: cleanup };
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
  beginAttachment,
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
  beginAttachment?: () => {
    stage(input: { uri: string; name: string; mime: string; kind: 'image' | 'file' }): Promise<Attachment>;
    enqueue(attachment: Attachment): Promise<void>;
    cancel(): void;
  };
}) {
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const operation = useRef(false);
  useEffect(() => {
    if (disabled || !allowAttachments || voice.recording) setExpanded(false);
  }, [disabled, allowAttachments, voice.recording]);
  const attach = async (kind: 'image' | 'file' | 'camera') => {
    if (disabled || !allowAttachments || operation.current || voice.recording) return;
    operation.current = true;
    setExpanded(false);
    setBusy(true);
    let intent: ReturnType<NonNullable<typeof beginAttachment>> | undefined;
    try {
      // Capture the original conversation/draft BEFORE any native permission or
      // picker activity can background the app and start session revalidation.
      intent = beginAttachment?.();
      const stage = intent ? intent.stage : (input: Parameters<typeof stageFile>[1]) => stageFile(room, input);
      const submit = intent ? intent.enqueue : enqueue;
      if (kind === 'image' || kind === 'camera') {
        if (kind === 'camera' && Platform.OS === 'android') {
          const permission = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.CAMERA);
          if (permission !== PermissionsAndroid.RESULTS.GRANTED) { report('noCamera'); return; }
        }
        const result = await (kind === 'camera' ? launchCamera({
          mediaType: 'photo', cameraType: 'back', quality: 0.9, saveToPhotos: false,
        }) : launchImageLibrary({
          mediaType: 'photo',
          selectionLimit: 1,
          quality: 0.9,
        }));
        if (result.didCancel) return;
        if (result.errorCode) { report(kind === 'camera' ? result.errorCode === 'permission' ? 'noCamera' : 'cameraUnavailable' : 'error'); return; }
        const asset = result.assets?.[0];
        if (!asset?.uri) throw new Error('picker');
        const staged = await stage({
          uri: asset.uri,
          name: asset.fileName || 'image.jpg',
          mime: asset.type || 'image/jpeg',
          kind: 'image',
        });
        await submit(staged);
      } else {
        const [file] = await pick({
          type: [types.pdf, types.plainText, types.docx, types.xlsx],
          allowMultiSelection: false,
        });
        if (!file) return;
        const staged = await stage({
          uri: file.uri,
          name: file.name || 'attachment',
          mime: file.type || 'application/octet-stream',
          kind: 'file',
        });
        await submit(staged);
      }
    } catch (e) {
      if (!(isErrorWithCode(e) && e.code === errorCodes.OPERATION_CANCELED)) report(errorWord(e));
    } finally {
      intent?.cancel();
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
            { paddingHorizontal: 8, flexDirection: language === 'ar' ? 'row-reverse' : 'row', flexWrap: 'wrap' },
          ]}>
          <Button quiet title={t('camera')} disabled={disabled || busy} onPress={() => { void attach('camera'); }} />
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
  previewVisible = false,
  senderName = '',
  senderUserId,
}: {
  room: Room;
  media: Record<string, unknown>;
  voice: VoiceSession;
  t: Translate;
  language: Language;
  report: (word: Word) => void;
  scopeKey?: string;
  previewVisible?: boolean;
  senderName?: string;
  senderUserId?: number;
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
    media.thumbnail_available,
  ]);
  const [cached, setCached] = useState<{ key: string; uri: string } | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const [showing, setShowing] = useState<string | null>(null);
  const [full, setFull] = useState<{ key: string; uri: string } | null>(null);
  const leases = useRef<{ preview: LocalMediaLease | null; full: LocalMediaLease | null }>({ preview: null, full: null });
  const [foreground, setForeground] = useState(AppState.currentState === 'active');
  const live = useRef({
    key,
    revision: 0,
    serial: 0,
    active: true,
    busy: false,
    intentional: false,
    previewAttempted: false,
  });
  if (live.current.key !== key) {
    live.current = {
      key,
      revision: live.current.revision + 1,
      serial: live.current.serial + 1,
      active: true,
      busy: false,
      intentional: false,
      previewAttempted: false,
    };
  }
  const presentation = `${key}/${live.current.revision}`;
  const revision = live.current.revision;
  const uri = cached?.key === presentation ? cached.uri : null;
  const fullUri = full?.key === presentation ? full.uri : null;
  const busy = opening === presentation;
  useEffect(() => {
    live.current.active = AppState.currentState === 'active';
    const invalidate = () => {
      live.current.serial++;
      live.current.previewAttempted = false;
      live.current.busy = false;
      live.current.intentional = false;
      setShowing(null);
      setOpening(null);
      leases.current.preview?.release(); leases.current.full?.release();
      leases.current = { preview: null, full: null }; setCached(null); setFull(null);
    };
    const listener = AppState.addEventListener('change', state => {
      live.current.active = state === 'active';
      if (state !== 'active') invalidate();
      setForeground(state === 'active');
    });
    return () => {
      live.current.active = false;
      live.current.serial++;
      live.current.busy = false;
      leases.current.preview?.release(); leases.current.full?.release(); leases.current = { preview: null, full: null };
      listener.remove();
    };
  }, [key]);
  const resolve = async (intentional: boolean) => {
    if (
      !live.current.active ||
      live.current.key !== key ||
      live.current.revision !== revision ||
      AppState.currentState !== 'active'
    )
      return;
    if (live.current.busy) {
      // A deliberate tap joins an automatic thumbnail request. It must not queue
      // another download or be lost simply because the thumbnail is still loading.
      if (intentional && media.kind === 'image') live.current.intentional = true;
      return;
    }
    if (!intentional && (media.kind !== 'image' || live.current.previewAttempted || uri)) return;
    live.current.previewAttempted = true;
    live.current.busy = true;
    live.current.intentional = intentional;
    const serial = ++live.current.serial;
    const current = () =>
      live.current.active &&
      live.current.key === key &&
      live.current.revision === revision &&
      live.current.serial === serial &&
      AppState.currentState === 'active';
    setOpening(presentation);
    try {
      // The viewport receives a real protected thumbnail, never a full image.
      // Deliberate opening independently resolves the original with its SHA.
      let local = await localMediaLease(room, media, intentional || media.kind !== 'image' ? 'original' : 'preview');
      if (!current()) { local.release(); return; }
      if (media.kind === 'image') {
        if (!local.uri.startsWith('file://')) { local.release(); throw new Error('invalid_local_image'); }
        if (!intentional) {
          leases.current.preview?.release(); leases.current.preview = local;
          setCached({ key: presentation, uri: local.uri });
          if (!live.current.intentional) return;
          local = await localMediaLease(room, media, 'original');
          if (!current()) { local.release(); return; }
          if (!local.uri.startsWith('file://')) { local.release(); throw new Error('invalid_local_image'); }
        }
        leases.current.full?.release(); leases.current.full = local;
        setFull({ key: presentation, uri: local.uri }); setShowing(presentation);
      } else if (media.kind === 'audio') await voice.play(local.uri, local.release);
      else {
        // The native activity owns the file while the private timeline is masked.
        // Its dismiss callback survives this component's intentional unmount.
        try { await FileViewer.open(local.uri.replace(/^file:\/\//, ''), { showOpenWithDialog: true, onDismiss: local.release }); }
        catch (error) { local.release(); throw error; }
      }
    } catch (e) {
      // Off-line cache misses and other automatic failures stay local and quiet.
      // A deliberate retry still reports the normal actionable runtime error.
      if (current() && live.current.intentional) report(errorWord(e));
    } finally {
      if (current()) {
        live.current.busy = false;
        live.current.intentional = false;
        setOpening(null);
      }
    }
  };
  useEffect(() => {
    if (!previewVisible) {
      if (live.current.busy && !live.current.intentional) {
        live.current.serial++;
        live.current.busy = false;
        live.current.previewAttempted = false;
        setOpening(null);
      }
      if (leases.current.preview && showing !== presentation) {
        leases.current.preview.release(); leases.current.preview = null; setCached(null);
        // Permit a fresh scoped cache lookup when a virtualized row returns.
        live.current.previewAttempted = false;
      }
      return;
    }
    if (foreground && media.kind === 'image') void resolve(false);
    // Resolve is intentionally not a dependency: repeated history renders must
    // neither repeat failed automatic attempts nor restart in-flight downloads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presentation, previewVisible, foreground]);
  return (
    <View style={{ gap: 8 }}>
      {media.kind !== 'audio' && <Label language={language} muted>
        {String(media.name ?? t('file'))}
      </Label>}
      {media.kind === 'image' ? (
        <>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t('viewPhoto')}
            accessibilityHint={t('zoomPhoto')}
            accessibilityState={{ busy }}
            onPress={() => {
              void resolve(true);
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
            {uri || showing === presentation && fullUri ? (
              <Image
                source={{ uri: uri ?? fullUri! }}
                resizeMode="contain"
                resizeMethod="resize"
                accessible={false}
                style={{ width: '100%', height: '100%' }}
              />
            ) : (
              <View style={{ gap: 6, alignItems: 'center', padding: 12 }}>
                <Icon icon="image" size={34} color={colors.blue} />
                <Label language={language} muted>
                  {t(busy ? 'loading' : 'viewPhoto')}
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
          {showing === presentation && fullUri && (
            <ImageViewer
              key={`${presentation}/${fullUri}`}
              uri={fullUri}
              name={String(media.name ?? t('photo'))}
              language={language}
              t={t}
              onClose={() => {
                if (live.current.key !== key || live.current.revision !== revision) return;
                setShowing(null); setFull(null);
                if (!leases.current.preview && leases.current.full) {
                  leases.current.preview = leases.current.full;
                  setCached({ key: presentation, uri: leases.current.full.uri });
                } else leases.current.full?.release();
                leases.current.full = null;
                if (!previewVisible) {
                  leases.current.preview?.release(); leases.current.preview = null;
                  setCached(null); live.current.previewAttempted = false;
                }
              }}
            />
          )}
        </>
      ) : media.kind === 'audio' ? (
        <VoiceBubble room={room} media={media} voice={voice} t={t} language={language} report={report} scopeKey={scopeKey} visible={previewVisible && foreground} senderName={senderName} senderUserId={senderUserId} />
      ) : (
        <Button
          quiet
          title={media.kind === 'audio' ? t('play') : t('open')}
          busy={busy}
          onPress={() => {
            void resolve(true);
          }}
        />
      )}
    </View>
  );
}
