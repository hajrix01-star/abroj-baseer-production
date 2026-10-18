import React from 'react';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Path } from 'react-native-svg';
import type { Language, Translate } from './dictionary';

export const colors = {
  ink: '#101b36',
  muted: '#54697b',
  blue: '#1256da',
  border: '#dce5ec',
  background: '#f4f7fd',
  white: '#ffffff',
  pale: '#edf2fc',
  accent: '#25bdec',
  violet: '#7556f5',
  warning: '#fff4d6',
  danger: '#a12a32',
  chatBackground: '#f1f3f5',
  chatSent: '#dff0ff',
  chatQuote: '#d4e8fc',
  composerBackground: '#ffffff',
};

const iconPaths = {
  menu: 'M4 6h16M4 12h16M4 18h16',
  back: 'M15 5l-7 7 7 7',
  chevronDown: 'M6 9l6 6 6-6',
  check: 'M5 12l4 4L19 6',
  doubleCheck: 'M18 6 7 17l-5-5M22 6 11 17l-2-2',
  clock: 'M12 8v4l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',
  alert: 'M12 8v4M12 16h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',
  down: 'M12 5v14M5 12l7 7 7-7',
  zoomIn: 'M21 21l-4.3-4.3M11 8v6M8 11h6M18 11a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z',
  zoomOut: 'M21 21l-4.3-4.3M8 11h6M18 11a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z',
  maximize: 'M8 3H3v5M16 3h5v5M21 16v5h-5M8 21H3v-5',
  building: 'M6 22V3h12v19M3 22h18M9 7h1M14 7h1M9 11h1M14 11h1M10 22v-6h4v6',
  send: 'M4 4l17 8-17 8 3-8-3-8ZM7 12h14',
  mic: 'M9 5a3 3 0 0 1 6 0v6a3 3 0 0 1-6 0V5ZM5 10v1a7 7 0 0 0 14 0v-1M12 18v4M8 22h8',
  stop: 'M7 7h10v10H7Z',
  close: 'M6 6l12 12M6 18L18 6',
  more: 'M12 5h.01M12 12h.01M12 19h.01',
  plus: 'M12 5v14M5 12h14',
  attach: 'M8 12l7-7a4 4 0 0 1 6 6L10 22a6 6 0 0 1-8-8L13 3M6 16l10-10',
  image: 'M4 4h16v16H4ZM4 16l5-5 4 4 3-3 4 4M15 8h.01',
  file: 'M5 3h9l5 5v13H5ZM14 3v6h5M8 13h8M8 17h6',
  members:
    'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM18 4a4 4 0 0 1 0 7M22 21v-2a4 4 0 0 0-3-4',
  reply: 'M9 10 4 15l5 5M4 15h11a5 5 0 0 0 0-10h-2',
  settings: 'M4 7h16M4 17h16M9 4v6M15 14v6',
  user: 'M20 21v-2a6 6 0 0 0-6-6h-4a6 6 0 0 0-6 6v2M12 9a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z',
  refresh: 'M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 14 6M18 18a8 8 0 0 1-14-6',
  logout: 'M9 3H4v18h5M14 8l5 4-5 4M8 12h11',
  globe:
    'M3 12h18M12 2a18 18 0 0 1 0 20 18 18 0 0 1 0-20ZM12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z',
} as const;
export type IconName = keyof typeof iconPaths;
export function Icon({
  icon,
  size = 22,
  color = colors.ink,
}: {
  icon: IconName;
  size?: number;
  color?: string;
}) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" accessible={false}>
      <Path
        d={iconPaths[icon]}
        stroke={color}
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

export function IconButton({
  icon,
  label,
  onPress,
  disabled,
  busy,
  tone = 'quiet',
  size,
  style,
}: {
  icon: IconName;
  label: string;
  onPress: () => void;
  disabled?: boolean;
  busy?: boolean;
  tone?: 'quiet' | 'primary' | 'danger';
  size?: number;
  style?: StyleProp<ViewStyle>;
}) {
  const color = tone === 'primary' ? colors.white : tone === 'danger' ? colors.danger : colors.ink;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !!(disabled || busy), busy: !!busy }}
      disabled={disabled || busy}
      onPress={onPress}
      style={({ pressed }) => [
        {
          minWidth: 44,
          minHeight: 44,
          width: 44,
          height: 44,
          borderRadius: 24,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: tone === 'primary' ? colors.blue : 'transparent',
        },
        (disabled || busy) && styles.disabled,
        pressed && { opacity: 0.65 },
        style,
      ]}>
      {busy ? <ActivityIndicator color={color} /> : <Icon icon={icon} size={size} color={color} />}
    </Pressable>
  );
}
export const styles = StyleSheet.create({
  fill: { flex: 1 },
  page: { flex: 1, backgroundColor: colors.background },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  header: {
    padding: 16,
    gap: 10,
    backgroundColor: colors.white,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  title: { color: colors.ink, fontSize: 22, fontWeight: '700' },
  text: { color: colors.ink, fontSize: 16, lineHeight: 24 },
  muted: { color: colors.muted, fontSize: 13, lineHeight: 20 },
  card: { backgroundColor: colors.white, borderRadius: 14, padding: 16, gap: 12 },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.white,
    borderRadius: 12,
    minHeight: 48,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 16,
    color: colors.ink,
  },
  listRow: { padding: 16, borderBottomWidth: 1, borderBottomColor: colors.border, gap: 5 },
  button: {
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 11,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.blue,
  },
  quiet: { backgroundColor: colors.pale },
  disabled: { opacity: 0.45 },
  buttonLabel: { color: colors.white, fontSize: 14, fontWeight: '600' },
  banner: { paddingHorizontal: 16, paddingVertical: 10, backgroundColor: colors.warning },
  modal: { flex: 1, backgroundColor: '#00000055', justifyContent: 'center', padding: 16 },
  panel: {
    width: '100%',
    maxWidth: 620,
    maxHeight: '90%',
    alignSelf: 'center',
    backgroundColor: colors.white,
    borderRadius: 18,
    padding: 16,
    gap: 14,
  },
});
export const direction = (language: Language) =>
  ({
    textAlign: language === 'ar' ? 'right' : 'left',
    writingDirection: language === 'ar' ? 'rtl' : 'ltr',
  }) as const;
export function Label({
  children,
  language,
  muted = false,
}: {
  children: React.ReactNode;
  language: Language;
  muted?: boolean;
}) {
  return <Text style={[muted ? styles.muted : styles.text, direction(language)]}>{children}</Text>;
}
export function Button({
  title,
  onPress,
  disabled,
  quiet,
  busy,
  accessibilityLabel,
}: {
  title: string;
  onPress: () => void;
  disabled?: boolean;
  quiet?: boolean;
  busy?: boolean;
  accessibilityLabel?: string;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? title}
      disabled={disabled || busy}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        quiet && styles.quiet,
        (disabled || busy) && styles.disabled,
        pressed && { opacity: 0.78 },
      ]}>
      {busy ? (
        <ActivityIndicator color={quiet ? colors.blue : colors.white} />
      ) : (
        <Text style={[styles.buttonLabel, quiet && { color: colors.blue }]}>{title}</Text>
      )}
    </Pressable>
  );
}
export const Field = React.forwardRef<TextInput, TextInputProps & { language: Language }>(function Field({ language, ...props }, ref) {
  return (
    <TextInput
      ref={ref}
      placeholderTextColor={colors.muted}
      {...props}
      style={[styles.input, direction(language), props.style]}
    />
  );
});
export function Sheet({
  title,
  close,
  children,
  t,
  style,
  compact = false,
  language = 'en',
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
  t: Translate;
  style?: StyleProp<ViewStyle>;
  compact?: boolean;
  language?: Language;
}) {
  return (
    <Modal visible transparent animationType="fade" onRequestClose={close}>
      <SafeAreaView style={styles.modal}>
        <View style={[styles.panel, compact && { padding: 12, gap: 8 }, style]}>
          <View style={compact ? { direction: 'ltr', flexDirection: language === 'ar' ? 'row-reverse' : 'row', alignItems: 'center', gap: 8 } : [styles.row, { justifyContent: 'space-between' }]}>
            <Text style={compact ? [styles.title, direction(language), { flex: 1, fontSize: 18 }] : styles.title}>{title}</Text>
            {compact ? <IconButton icon="close" label={t('close')} onPress={close} /> : <Button quiet title={t('close')} onPress={close} />}
          </View>
          <ScrollView
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={{ gap: compact ? 8 : 14, paddingBottom: 12 }}>
            {children}
          </ScrollView>
        </View>
      </SafeAreaView>
    </Modal>
  );
}
