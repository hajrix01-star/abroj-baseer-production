import React, { useEffect, useRef, useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button, colors, direction, IconButton } from '../../ui/components';
import { translator, type Language } from '../../ui/dictionary';
import { monthLabel } from './presentation';

const MIN_YEAR = 1900, MAX_YEAR = 9998;
const row = (language: Language) => ({ flexDirection: language === 'ar' ? 'row-reverse' : 'row' } as const);
const valueFor = (year: number, month: number) => `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}`;

/** A month is a civil YYYY-MM string, never a local/UTC Date conversion. */
export function MonthField({ value, onChange, label, language, disabled, testID = 'leadership-month' }: {
  value: string; onChange: (month: string) => void; label: string; language: Language; disabled?: boolean; testID?: string;
}) {
  const t = translator(language), [open, setOpen] = useState<number | null>(null), [year, setYear] = useState(Number(value.slice(0, 4))), [years, setYears] = useState(false);
  const alive = useRef(true), serial = useRef(0), latest = useRef({ value, disabled, onChange });
  // Invalidate synchronously: queued native presses must not use an old modal
  // after cancel, authority/value/callback change, a new open, or unmount.
  if (latest.current.value !== value || latest.current.disabled !== disabled || latest.current.onChange !== onChange) {
    serial.current++; latest.current = { value, disabled, onChange };
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; serial.current++; }; }, []);
  const current = () => alive.current && !latest.current.disabled && open !== null && open === serial.current;
  const close = () => { if (current()) { serial.current++; setOpen(null); } };
  const visible = current();
  const start = Math.max(MIN_YEAR, Math.min(MAX_YEAR - 11, Math.floor((year - MIN_YEAR) / 12) * 12 + MIN_YEAR));
  const previousDisabled = years ? start === MIN_YEAR : year === MIN_YEAR;
  const nextDisabled = years ? start + 11 === MAX_YEAR : year === MAX_YEAR;
  const move = (delta: number) => { if (current()) setYear(currentYear => Math.max(MIN_YEAR, Math.min(MAX_YEAR, currentYear + delta * (years ? 12 : 1)))); };
  return <>
    <Pressable testID={testID} disabled={disabled} accessibilityRole="button" accessibilityLabel={`${label}: ${monthLabel(value, language)}`}
      accessibilityState={{ disabled, expanded: visible }} onPress={() => { if (alive.current && !latest.current.disabled) { setYear(Number(latest.current.value.slice(0, 4))); setYears(false); setOpen(++serial.current); } }}
      style={[s.field, row(language)]}>
      <View style={{ flex: 1, gap: 3 }}><Text style={[s.caption, direction(language)]}>{label}</Text><Text style={[s.value, direction(language)]}>{monthLabel(value, language)}</Text></View>
      <Text style={{ color: colors.blue, fontSize: 18 }} accessibilityElementsHidden>▾</Text>
    </Pressable>
    {visible && <Modal visible transparent animationType="fade" onRequestClose={close}>
      <View style={s.overlay}>
        <Pressable testID={`${testID}-backdrop`} accessible={false} style={{ position: 'absolute', top: 0, bottom: 0, left: 0, right: 0 }} onPress={close} />
        <SafeAreaView style={s.safe} pointerEvents="box-none">
          <View style={s.panel} accessibilityViewIsModal>
            <View style={[s.header, row(language)]}><Text style={[s.value, direction(language), { flex: 1 }]}>{label}</Text><IconButton icon="close" label={t('close')} onPress={close} /></View>
            <ScrollView contentContainerStyle={{ gap: 12 }}>
              <View style={[s.header, row(language)]}>
                <Pressable testID={`${testID}-year-previous`} accessibilityRole="button" accessibilityLabel={language === 'ar' ? 'السنوات السابقة' : 'Previous years'} disabled={previousDisabled} accessibilityState={{ disabled: previousDisabled }} onPress={() => move(-1)} style={s.arrow}><Text style={[s.value, { opacity: previousDisabled ? .35 : 1 }]}>{language === 'ar' ? '›' : '‹'}</Text></Pressable>
                <Pressable testID={`${testID}-year`} accessibilityRole="button" accessibilityLabel={language === 'ar' ? 'اختيار السنة' : 'Choose year'} onPress={() => { if (current()) setYears(v => !v); }} style={[s.arrow, { flex: 1 }]}><Text style={s.value}>{years ? `${start} — ${start + 11}` : String(year)} ▾</Text></Pressable>
                <Pressable testID={`${testID}-year-next`} accessibilityRole="button" accessibilityLabel={language === 'ar' ? 'السنوات التالية' : 'Next years'} disabled={nextDisabled} accessibilityState={{ disabled: nextDisabled }} onPress={() => move(1)} style={s.arrow}><Text style={[s.value, { opacity: nextDisabled ? .35 : 1 }]}>{language === 'ar' ? '‹' : '›'}</Text></Pressable>
              </View>
              {Array.from({ length: 4 }, (_, index) => <View key={index} style={[row(language), { gap: 6 }]}>
                {Array.from({ length: 3 }, (_, column) => {
                  const item = index * 3 + column, targetYear = start + item, month = item + 1;
                  const selected = years ? targetYear === Number(value.slice(0, 4)) : value === valueFor(year, month);
                  return <Pressable key={item} testID={years ? `${testID}-year-option-${targetYear}` : `${testID}-option-${String(month).padStart(2, '0')}`}
                    accessibilityRole="button" accessibilityState={{ selected }} onPress={() => {
                      if (!current()) return;
                      if (years) { setYear(targetYear); setYears(false); } else { close(); latest.current.onChange(valueFor(year, month)); }
                    }} style={[s.option, selected && s.selected]}>
                    <Text style={[s.month, direction(language), selected && { color: colors.blue }]}>{years ? String(targetYear) : monthLabel(valueFor(year, month), language).replace(/\s*\d{4}/, '').trim()}</Text>
                  </Pressable>;
                })}
              </View>)}
              <View testID={`${testID}-cancel`}><Button quiet title={t('cancel')} onPress={close} /></View>
            </ScrollView>
          </View>
        </SafeAreaView>
      </View>
    </Modal>}
  </>;
}

const s = StyleSheet.create({
  field: { minHeight: 54, alignItems: 'center', gap: 8, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 6 },
  caption: { fontSize: 11, color: colors.muted }, value: { fontSize: 16, color: colors.ink, fontWeight: '600', fontVariant: ['tabular-nums'] },
  overlay: { flex: 1, backgroundColor: 'rgba(16,27,54,.45)', justifyContent: 'center', padding: 12 }, safe: { width: '100%', maxWidth: 480, maxHeight: '100%', alignSelf: 'center', flexShrink: 1 },
  panel: { backgroundColor: colors.white, borderRadius: 16, padding: 12, gap: 8, maxHeight: '100%', flexShrink: 1 },
  header: { alignItems: 'center', gap: 6 }, arrow: { minWidth: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  option: { flex: 1, minWidth: 0, minHeight: 44, borderRadius: 8, padding: 6, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.border },
  selected: { backgroundColor: colors.pale, borderColor: colors.blue }, month: { fontSize: 13, color: colors.ink, textAlign: 'center', flexShrink: 1 },
});
