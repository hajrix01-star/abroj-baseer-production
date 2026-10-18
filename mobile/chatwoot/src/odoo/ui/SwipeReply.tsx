import React, { useEffect, useRef } from 'react';
import { PanResponder, View, type StyleProp, type ViewStyle } from 'react-native';
import { colors, Icon } from './components';
import type { Language } from './dictionary';

/** Direct finger feedback only; no animation, timer, or takeover of vertical history scrolling. */
export function SwipeReply({ children, enabled, language, onReply, gestureKey, style }: {
  children: React.ReactNode; enabled: boolean; language: Language; onReply: () => void; gestureKey: string; style?: StyleProp<ViewStyle>;
}) {
  const view = useRef<View>(null);
  const indicator = useRef<View>(null);
  const cancelled = useRef(false);
  const gesture = useRef<{ key: string; language: Language } | null>(null);
  const current = useRef({ enabled, language, onReply, gestureKey }); current.current = { enabled, language, onReply, gestureKey };
  const sign = () => current.current.language === 'ar' ? -1 : 1;
  const reset = () => {
    view.current?.setNativeProps({ style: { transform: [{ translateX: 0 }] } });
    indicator.current?.setNativeProps({ style: { opacity: 0 } });
  };
  useEffect(() => { cancelled.current = true; gesture.current = null; reset(); }, [gestureKey, enabled, language]);
  const shouldClaim = (_event: unknown, motion: { numberActiveTouches: number; dx: number; dy: number }) =>
    current.current.enabled && motion.numberActiveTouches === 1
      && motion.dx * sign() > 12 && Math.abs(motion.dx) > Math.abs(motion.dy) * 1.5;
  const responder = useRef(PanResponder.create({
    onStartShouldSetPanResponder: () => false,
    // Negotiate moves before Pressability consumes the message as a tap. Never capture starts or vertical history gestures.
    onMoveShouldSetPanResponderCapture: shouldClaim,
    onMoveShouldSetPanResponder: shouldClaim,
    onPanResponderGrant: () => { cancelled.current = false; gesture.current = { key: current.current.gestureKey, language: current.current.language }; },
    onPanResponderMove: (_event, gesture) => {
      if (!current.current.enabled || gesture.numberActiveTouches > 1) { cancelled.current = true; reset(); return; }
      const distance = Math.min(72, Math.max(0, gesture.dx * sign()));
      view.current?.setNativeProps({ style: { transform: [{ translateX: sign() * distance }] } });
      indicator.current?.setNativeProps({ style: { opacity: Math.min(1, distance / 56) } });
    },
    onPanResponderRelease: (_event, motion) => {
      reset();
      if (!cancelled.current && current.current.enabled && gesture.current?.key === current.current.gestureKey
        && gesture.current.language === current.current.language && motion.dx * sign() >= 56 && Math.abs(motion.dx) > Math.abs(motion.dy) * 1.5)
        current.current.onReply();
      gesture.current = null;
    },
    onPanResponderTerminate: () => { cancelled.current = true; gesture.current = null; reset(); },
    onPanResponderTerminationRequest: () => true,
  })).current;
  return <View {...responder.panHandlers} style={style}>
    <View ref={indicator} pointerEvents="none" style={{ position: 'absolute', top: '40%', opacity: 0,
      ...(language === 'ar' ? { right: 8 } : { left: 8 }) }}><Icon icon="reply" size={20} color={colors.blue} /></View>
    <View ref={view}>{children}</View>
  </View>;
}
