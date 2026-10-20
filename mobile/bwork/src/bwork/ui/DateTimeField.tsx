import React, { useEffect, useRef, useState } from 'react';
import { AppState, Pressable, Text, View } from 'react-native';
import { Button, colors, direction, Field, Icon, IconButton, Label, Sheet, styles } from './components';
import { translator, type Language } from './dictionary';
import { calendarDays, dateTimeLabel, localParts, partsToUTC, westernDigits, type DateTimeParts } from './dateTime';

const words = {
  en: { choose: 'Choose date and time', clear: 'Clear date', save: 'Use date', invalid: 'Enter a valid date and time.', year: 'Year', month: 'Month', day: 'Day', hour: 'Hour (0–23)', minute: 'Minute', previous: 'Previous month', next: 'Next month', timezone: 'Times use your device’s time zone.' },
  ar: { choose: 'اختيار التاريخ والوقت', clear: 'مسح الموعد', save: 'اعتماد الموعد', invalid: 'أدخل تاريخًا ووقتًا صحيحين.', year: 'السنة', month: 'الشهر', day: 'اليوم', hour: 'الساعة (0–23)', minute: 'الدقيقة', previous: 'الشهر السابق', next: 'الشهر التالي', timezone: 'الأوقات حسب المنطقة الزمنية لجهازك.' },
} as const;

/** Shared app-owned control: no OS locale or native dialog can change its digits. */
export function DateTimeField({ label, language, value, onChange, disabled = false, testID = 'date-time', help }: {
  label: string; language: Language; value: string | null; onChange: (value: string | null) => void; disabled?: boolean; testID?: string; help?: string;
}) {
  const t = words[language], [open, setOpen] = useState(false), [parts, setParts] = useState<DateTimeParts>(() => localParts(value));
  const [width, setWidth] = useState(0), [invalid, setInvalid] = useState(false);
  const active = useRef(AppState.currentState === 'active'), alive = useRef(true), current = useRef({ disabled, onChange });
  current.current = { disabled, onChange };
  useEffect(() => { alive.current = true; const listener = AppState.addEventListener('change', state => { active.current = state === 'active'; if (!active.current) setOpen(false); });
    return () => { alive.current = false; listener.remove(); }; }, []);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  const allowed = () => alive.current && active.current && !current.current.disabled;
  const change = (key: keyof DateTimeParts, text: string) => { if (allowed()) { setInvalid(false); setParts(previous => ({ ...previous, [key]: westernDigits(text) })); } };
  const save = () => { if (!allowed()) return; const iso = partsToUTC(parts); if (!iso) { setInvalid(true); return; } setOpen(false); current.current.onChange(iso); };
  const year = Number(parts.year), month = Number(parts.month);
  const calendar = width >= 308 && year >= 1900 && year <= 9999 && month >= 1 && month <= 12;
  const move = (delta: number) => { if (!allowed()) return; const next = new Date(year, month - 1 + delta, 1); if (next.getFullYear() < 1900 || next.getFullYear() > 9999) return;
    setParts(previous => ({ ...previous, year: String(next.getFullYear()), month: String(next.getMonth() + 1).padStart(2, '0'), day: String(Math.min(Number(previous.day) || 1, new Date(next.getFullYear(), next.getMonth() + 1, 0).getDate())).padStart(2, '0') })); };
  const input = (key: keyof DateTimeParts, limit: number) => <View key={key} style={{ flex: 1, minWidth: 0, gap: 4 }}>
    <Label language={language} muted>{t[key]}</Label><Field testID={`${testID}-${key}`} accessibilityLabel={t[key]} language={language} value={parts[key]}
      editable={!disabled} keyboardType="number-pad" maxLength={limit} onChangeText={text => change(key, text)} style={{ textAlign: 'center', writingDirection: 'ltr', minHeight: 44, paddingHorizontal: 4 }} />
  </View>;
  return <View style={{ gap: 5 }}>
    <Label language={language} muted>{label}</Label>
    <Pressable testID={testID} accessibilityRole="button" accessibilityLabel={`${label}: ${value ? dateTimeLabel(value, language) : t.choose}`}
      accessibilityState={{ expanded: open && !disabled, disabled }} disabled={disabled}
      onPress={() => { if (allowed()) { setParts(localParts(value)); setInvalid(false); setOpen(true); } }}
      style={({ pressed }) => [styles.input, { flexDirection: language === 'ar' ? 'row-reverse' : 'row', alignItems: 'center', gap: 8 }, pressed && { opacity: .75 }]}>
      <Icon icon="clock" color={colors.blue} size={20} /><Text style={[styles.text, direction(language), { flex: 1 }]}>{value ? dateTimeLabel(value, language) : t.choose}</Text>
    </Pressable>
    {!!help && <Label language={language} muted>{help}</Label>}
    {open && !disabled && <Sheet title={label} close={() => setOpen(false)} t={translator(language)} language={language} compact>
      <View testID={`${testID}-picker`} onLayout={event => setWidth(event.nativeEvent.layout.width)} style={{ gap: 10 }}>
        <Label language={language} muted>{t.timezone}</Label>
        {calendar && <>
          <View style={{ flexDirection: language === 'ar' ? 'row-reverse' : 'row', alignItems: 'center', justifyContent: 'space-between' }}>
            <IconButton icon="back" label={t.previous} onPress={() => move(-1)} />
            <Text style={[styles.text, direction(language)]}>{new Intl.DateTimeFormat(language === 'ar' ? 'ar-SA' : 'en-GB', { calendar: 'gregory', numberingSystem: 'latn', month: 'long', year: 'numeric' }).format(new Date(year, month - 1, 1))}</Text>
            <IconButton icon="back" label={t.next} onPress={() => move(1)} style={{ transform: [{ rotate: '180deg' }] }} />
          </View>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', direction: 'ltr' }}>
            {Array.from({ length: 7 }, (_, index) => <View key={`weekday-${index}`} style={{ width: '14.285714%', minHeight: 32, alignItems: 'center', justifyContent: 'center' }}>
              <Text style={styles.muted}>{new Intl.DateTimeFormat(language === 'ar' ? 'ar-SA' : 'en-GB', { calendar: 'gregory', numberingSystem: 'latn', weekday: 'narrow' }).format(new Date(2026, 0, 4 + index))}</Text>
            </View>)}
            {calendarDays(year, month).map((day, index) => <View key={index} style={{ width: '14.285714%', minHeight: 44 }}>
              {day !== null && <Pressable testID={`${testID}-day-${day}`} accessibilityRole="button" accessibilityLabel={`${String(day)} ${String(month)} ${String(year)}`}
                accessibilityState={{ selected: Number(parts.day) === day }} onPress={() => change('day', String(day).padStart(2, '0'))}
                style={({ pressed }) => ({ minHeight: 44, minWidth: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 8, backgroundColor: Number(parts.day) === day ? colors.pale : 'transparent', opacity: pressed ? .7 : 1 })}>
                <Text style={[styles.text, { color: Number(parts.day) === day ? colors.blue : colors.ink, writingDirection: 'ltr' }]}>{String(day)}</Text>
              </Pressable>}
            </View>)}
          </View>
        </>}
        <View style={{ flexDirection: language === 'ar' ? 'row-reverse' : 'row', gap: 8 }}>{input('day', 2)}{input('month', 2)}{input('year', 4)}</View>
        <View style={{ flexDirection: language === 'ar' ? 'row-reverse' : 'row', gap: 8 }}>{input('hour', 2)}{input('minute', 2)}</View>
        {invalid && <View accessibilityLiveRegion="polite"><Label language={language}>{t.invalid}</Label></View>}
        <Button title={t.save} onPress={save} /><Button title={t.clear} quiet onPress={() => { if (allowed()) { setOpen(false); current.current.onChange(null); } }} />
      </View>
    </Sheet>}
  </View>;
}
