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
import { tailwind } from '../../theme';
import type { Language, Translate } from './dictionary';

export const colors = {
  ink: tailwind.color('gray-950') ?? '#202124',
  muted: tailwind.color('gray-900') ?? '#64676b',
  blue: tailwind.color('blue-800') ?? '#087fdf',
  border: tailwind.color('gray-200') ?? '#eaecef',
  background: tailwind.color('gray-50') ?? '#f8f9fa',
  white: '#ffffff',
  pale: '#eaf4ff',
  warning: '#fff4d6',
  danger: '#a12a32',
};
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
export function Field({ language, ...props }: TextInputProps & { language: Language }) {
  return (
    <TextInput
      placeholderTextColor={colors.muted}
      {...props}
      style={[styles.input, direction(language), props.style]}
    />
  );
}
export function Sheet({
  title,
  close,
  children,
  t,
  style,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
  t: Translate;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <Modal visible transparent animationType="fade" onRequestClose={close}>
      <SafeAreaView style={styles.modal}>
        <View style={[styles.panel, style]}>
          <View style={[styles.row, { justifyContent: 'space-between' }]}>
            <Text style={styles.title}>{title}</Text>
            <Button quiet title={t('close')} onPress={close} />
          </View>
          <ScrollView
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={{ gap: 14, paddingBottom: 12 }}>
            {children}
          </ScrollView>
        </View>
      </SafeAreaView>
    </Modal>
  );
}
