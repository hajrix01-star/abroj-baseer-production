import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { Button, colors, direction, Field, Icon, Label, Sheet } from '../../ui/components';
import { translator, type Language } from '../../ui/dictionary';
import { displayNumber, orderErrorWord, orderTranslator, type OrderWord } from '../dictionary';
import type { Selection } from '../core/types';

export const ordersStyles = StyleSheet.create({
  fill: { flex: 1, minHeight: 0, backgroundColor: colors.background },
  content: { padding: 14, gap: 12, width: '100%', maxWidth: 940, alignSelf: 'center' },
  stack: { gap: 12 },
  row: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  spread: { justifyContent: 'space-between' },
  card: { backgroundColor: colors.white, borderWidth: 1, borderColor: colors.border, borderRadius: 13, padding: 14, gap: 10 },
  title: { color: colors.ink, fontSize: 22, lineHeight: 32, fontWeight: '700' },
  strong: { color: colors.ink, fontSize: 16, lineHeight: 24, fontWeight: '600' },
  note: { backgroundColor: colors.pale, borderRadius: 11, padding: 12, gap: 8 },
  warning: { backgroundColor: colors.warning },
  number: { writingDirection: 'ltr', color: colors.ink, fontSize: 15, lineHeight: 23, fontVariant: ['tabular-nums'] },
  tabs: { flexDirection: 'row', gap: 4, backgroundColor: colors.white, borderBottomWidth: 1, borderBottomColor: colors.border, paddingHorizontal: 12 },
  tab: { flex: 1, minWidth: 44, minHeight: 48, alignItems: 'center', justifyContent: 'center', paddingVertical: 10, paddingHorizontal: 2, borderBottomWidth: 3, borderBottomColor: 'transparent' },
  selectedTab: { borderBottomColor: colors.blue },
  footer: { padding: 14, gap: 10, backgroundColor: colors.white, borderTopWidth: 1, borderTopColor: colors.border },
  flexible: { flex: 1, minWidth: 0 },
});

export const rowDirection = (language: Language) => ({ flexDirection: language === 'ar' ? 'row-reverse' : 'row' }) as const;

export function NumberText({ value, suffix = '' }: { value: string | number | null | undefined; suffix?: string }) {
  return <Text style={ordersStyles.number}>{displayNumber(value)}{suffix ? ` ${suffix}` : ''}</Text>;
}

export function Note({ text, language, warning = false }: { text: string; language: Language; warning?: boolean }) {
  return <View style={[ordersStyles.note, warning && ordersStyles.warning, ordersStyles.row, rowDirection(language)]}>
    <Icon icon={warning ? 'alert' : 'info'} color={colors.muted} size={18} />
    <View style={ordersStyles.flexible}><Label language={language} muted>{text}</Label></View>
  </View>;
}

export function Empty({ title, help, language }: { title: string; help?: string; language: Language }) {
  return <View style={{ minHeight: 220, padding: 20, gap: 12, justifyContent: 'center' }}>
    <Label language={language}>{title}</Label>
    {!!help && <Label language={language} muted>{help}</Label>}
  </View>;
}

export function Busy({ language }: { language: Language }) {
  return <View accessibilityRole="progressbar" accessibilityLabel={orderTranslator(language)('loading')} style={{ padding: 18 }}><ActivityIndicator color={colors.blue} /></View>;
}

export function Failure({ error, language, retry }: { error: unknown; language: Language; retry?: () => void }) {
  const t = orderTranslator(language);
  return <View style={ordersStyles.stack} accessibilityLiveRegion="polite"><Note language={language} warning text={t(orderErrorWord(error))} />
    {retry && <Button title={t('retry')} onPress={retry} quiet />}
  </View>;
}

/** Orders-specific choice composition. The chat company selector requires chat_view. */
export function Choice({ label, options, value, onSelect, language, disabled = false, testID }: {
  label: string; options: Selection[]; value: number; onSelect: (id: number) => void; language: Language; disabled?: boolean; testID?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const current = useRef({ options, onSelect, disabled });
  current.current = { options, onSelect, disabled };
  const alive = useAlive();
  const t = orderTranslator(language);
  return <View style={{ gap: 5 }}>
    <Label language={language} muted>{label}</Label>
    <Pressable testID={testID} accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ expanded: open, disabled: disabled || !options.length }}
      disabled={disabled || !options.length} onPress={() => { if (alive() && !current.current.disabled) { setQuery(''); setOpen(true); } }}
      style={({ pressed }) => [ordersStyles.card, ordersStyles.row, rowDirection(language), { minHeight: 48, paddingVertical: 10 }, pressed && { opacity: .75 }]}>
      <Text numberOfLines={2} style={[ordersStyles.strong, direction(language), ordersStyles.flexible]}>{options.find(option => option.id === value)?.name ?? t(options.length ? 'choose' : 'noOptions')}</Text>
      <Icon icon="chevronDown" size={20} color={colors.muted} />
    </Pressable>
    {open && <Sheet title={label} close={() => setOpen(false)} t={translator(language)} compact language={language}>
      <Field language={language} accessibilityLabel={label} value={query} onChangeText={setQuery} maxLength={80} />
      {options.filter(option => option.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).map(option => <Pressable key={option.id}
        testID={`${testID}-option-${option.id}`} accessibilityRole="button" accessibilityLabel={option.name} accessibilityState={{ selected: value === option.id }}
        style={[ordersStyles.row, rowDirection(language), { minHeight: 48, padding: 10, borderRadius: 10, backgroundColor: value === option.id ? colors.pale : colors.white }]}
        onPress={() => { if (!alive() || current.current.disabled || !current.current.options.some(item => item.id === option.id)) return; setOpen(false); current.current.onSelect(option.id); }}>
        <View style={ordersStyles.flexible}><Label language={language}>{option.name}</Label></View>{value === option.id && <Icon icon="check" size={18} color={colors.blue} />}
      </Pressable>)}
    </Sheet>}
  </View>;
}

export function useAlive() {
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  return () => alive.current;
}

export function Heading({ word, language }: { word: OrderWord; language: Language }) {
  return <Text style={[ordersStyles.title, direction(language)]}>{orderTranslator(language)(word)}</Text>;
}

export function KeyValue({ label, children, language }: { label: string; children: React.ReactNode; language: Language }) {
  return <View style={[ordersStyles.row, ordersStyles.spread, rowDirection(language)]}><Label muted language={language}>{label}</Label><View style={{ flexShrink: 1 }}>{children}</View></View>;
}
