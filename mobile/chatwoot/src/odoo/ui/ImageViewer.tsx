import React, { useRef, useState } from 'react';
import { Image, Modal, PanResponder, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, IconButton } from './components';
import type { Language, Translate } from './dictionary';

type Geometry = { width: number; height: number; imageWidth: number; imageHeight: number };
type Position = { scale: number; x: number; y: number };

/** Local-only, bounded image inspection. No network, file mutation, or new dependencies. */
export function ImageViewer({
  uri,
  name,
  language,
  t,
  onClose,
}: {
  uri: string;
  name: string;
  language: Language;
  t: Translate;
  onClose: () => void;
}) {
  const geometry = useRef<Geometry>({ width: 1, height: 1, imageWidth: 1, imageHeight: 1 });
  const position = useRef<Position>({ scale: 1, x: 0, y: 0 });
  const dragStart = useRef({ x: 0, y: 0 });
  const [display, setDisplay] = useState(position.current);
  const update = (next: Position) => {
    const g = geometry.current;
    const scale = Math.min(4, Math.max(1, next.scale));
    const fit = Math.min(g.width / g.imageWidth, g.height / g.imageHeight);
    const boundX = Math.max(0, (g.imageWidth * fit * scale - g.width) / 2);
    const boundY = Math.max(0, (g.imageHeight * fit * scale - g.height) / 2);
    const value = {
      scale,
      x: Math.max(-boundX, Math.min(boundX, next.x)),
      y: Math.max(-boundY, Math.min(boundY, next.y)),
    };
    position.current = value;
    setDisplay(value);
  };
  const responder = useRef<ReturnType<typeof PanResponder.create> | null>(null);
  if (!responder.current)
    responder.current = PanResponder.create({
      onMoveShouldSetPanResponder: (event, gesture) =>
        position.current.scale > 1 &&
        event.nativeEvent.touches.length === 1 &&
        (Math.abs(gesture.dx) > 3 || Math.abs(gesture.dy) > 3),
      onPanResponderGrant: () => {
        dragStart.current = { x: position.current.x, y: position.current.y };
      },
      onPanResponderMove: (event, gesture) => {
        if (event.nativeEvent.touches.length !== 1) return;
        update({
          scale: position.current.scale,
          x: dragStart.current.x + gesture.dx,
          y: dragStart.current.y + gesture.dy,
        });
      },
      onPanResponderTerminationRequest: () => true,
    });
  if (!uri.startsWith('file://')) return null;
  return (
    <Modal visible animationType="none" presentationStyle="fullScreen" onRequestClose={onClose}>
      <SafeAreaView style={{ flex: 1, backgroundColor: '#101820' }}>
        <View
          style={{
            flexDirection: language === 'ar' ? 'row-reverse' : 'row',
            alignItems: 'center',
            paddingHorizontal: 8,
            gap: 6,
            backgroundColor: colors.white,
          }}>
          <IconButton icon="close" label={t('closePhoto')} onPress={onClose} />
          <Text
            numberOfLines={1}
            style={{
              flex: 1,
              color: colors.ink,
              fontSize: 14,
              textAlign: language === 'ar' ? 'right' : 'left',
            }}>
            {name}
          </Text>
          <IconButton
            icon="zoomOut"
            label={t('zoomOut')}
            disabled={display.scale <= 1}
            onPress={() => update({ ...position.current, scale: position.current.scale - 0.5 })}
          />
          <IconButton
            icon="zoomIn"
            label={t('zoomIn')}
            disabled={display.scale >= 4}
            onPress={() => update({ ...position.current, scale: position.current.scale + 0.5 })}
          />
        </View>
        <View
          {...responder.current.panHandlers}
          style={{ flex: 1, overflow: 'hidden' }}
          onLayout={event => {
            const { width, height } = event.nativeEvent.layout;
            geometry.current = {
              ...geometry.current,
              width: Math.max(1, width),
              height: Math.max(1, height),
            };
            update({ ...position.current, x: 0, y: 0 });
          }}>
          <Image
            accessibilityLabel={name}
            source={{ uri }}
            resizeMode="contain"
            onLoad={event => {
              const { width, height } = event.nativeEvent.source;
              geometry.current = {
                ...geometry.current,
                imageWidth: Math.max(1, width),
                imageHeight: Math.max(1, height),
              };
              update(position.current);
            }}
            style={{
              width: '100%',
              height: '100%',
              transform: [
                { translateX: display.x },
                { translateY: display.y },
                { scale: display.scale },
              ],
            }}
          />
        </View>
        <Text style={{ color: '#ffffff', fontSize: 13, textAlign: 'center', padding: 12 }}>
          {t('photoPanHint')} · {Math.round(display.scale * 100)}%
        </Text>
      </SafeAreaView>
    </Modal>
  );
}
