import React from 'react';
import { Pressable, Text, View } from 'react-native';
import { colors, direction, Icon, styles, type IconName } from './components';
import type { Language, Translate, Word } from './dictionary';

export function MessageStatus({ state, t }: { state: string | undefined; t: Translate }) {
  const key: Word = ['queued', 'sending', 'unknown', 'failed', 'sent', 'delivered', 'read'].includes(state ?? '')
    ? state as Word : 'unknown';
  const icon: IconName = key === 'failed' ? 'alert' : key === 'sent' ? 'check'
    : key === 'delivered' || key === 'read' ? 'doubleCheck' : 'clock';
  return (
    <View accessible accessibilityLabel={t(key)} testID={`message-status-${key}`}>
      <Icon icon={icon} size={16} color={key === 'read' ? colors.blue : key === 'failed' ? colors.danger : colors.muted} />
    </View>
  );
}

export function MessageQuote({ author, text, language, onPress, label }: { author: string; text: string; language: Language; onPress?: () => void; label?: string }) {
  const Container = onPress ? Pressable : View;
  return (
    <Container onPress={onPress} accessibilityRole={onPress ? 'button' : undefined} accessibilityLabel={onPress ? label : undefined}
      style={{ borderRightWidth: language === 'ar' ? 3 : 0, borderLeftWidth: language === 'en' ? 3 : 0,
      borderColor: colors.blue, backgroundColor: colors.chatQuote, borderRadius: 8,
      paddingHorizontal: 9, paddingVertical: 6, gap: 2, minWidth: 0, flexShrink: 1 }}>
      {!!author && <Text numberOfLines={1} style={[styles.muted, direction(language), { color: colors.blue, fontWeight: '600' }]}>{author}</Text>}
      <Text numberOfLines={2} style={[styles.muted, direction(language)]}>{text}</Text>
    </Container>
  );
}
