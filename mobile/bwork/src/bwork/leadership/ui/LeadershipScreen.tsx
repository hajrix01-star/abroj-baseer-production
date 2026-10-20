import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import Svg, { Line, Path } from 'react-native-svg';
import type { Bootstrap } from '../../core/ChatEngine';
import { Button, colors, direction, IconButton, Label, Sheet } from '../../ui/components';
import { companyDisplayName } from '../../ui/companyNames';
import { DateTimeField } from '../../ui/DateTimeField';
import { translator, type Language } from '../../ui/dictionary';
import type { LeadershipEngine } from '../core/LeadershipEngine';
import { accessDenied } from '../types';
import type { Amount, LeadershipDay, LeadershipOptions, LeadershipQuery, LeadershipReport, Period } from '../types';
import { errorWord, leadershipTranslator, weekdayName, type LeadershipWord } from '../dictionary';
import { calendarIntegerDisplay, coverageLabel, dayLabel, dayWord, monthLabel, percentagePresentation, snapshotDate } from './presentation';
import { MonthField } from './MonthField';

export interface LeadershipScreenProps { engine: LeadershipEngine; identity: Bootstrap; language: Language; presented: boolean; online?: boolean; scopeKey: string; onBack?: () => void }
const row = (language: Language) => ({ flexDirection: language === 'ar' ? 'row-reverse' : 'row' } as const);
const riyadhDate = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Riyadh', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
const pickerValue = (value: string) => new Date(`${value}T12:00:00`).toISOString();
const chosenDate = (value: string) => { const d = new Date(value); return `${String(d.getFullYear())}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

/** Scope changes unmount private UI; a hidden dashboard exposes no financial elements. */
export function LeadershipScreen(props: LeadershipScreenProps) {
  const key = JSON.stringify([props.scopeKey, props.identity.database, props.identity.user_id, props.identity.company_ids, props.identity.permissions.revision, props.identity.permissions.dashboard_view]);
  return <Workspace key={key} {...props} />;
}

function Workspace({ engine, identity, language, presented, online = true, onBack }: LeadershipScreenProps) {
  const t = leadershipTranslator(language), today = riyadhDate();
  const [month, setMonth] = useState(today.slice(0, 7)), [period, setPeriod] = useState<Period>('month'), [customDate, setCustomDate] = useState(today);
  const [companyId, setCompany] = useState(0), [tab, setTab] = useState<'overview' | 'heatmap'>('overview');
  const [options, setOptions] = useState<LeadershipOptions | null>(null), [ready, setReady] = useState(false), [report, setReport] = useState<{ key: string; value: LeadershipReport; cached: boolean } | null>(null);
  const [error, setError] = useState<unknown>(null), [busy, setBusy] = useState(false), [reading, setReading] = useState(false), [refresh, setRefresh] = useState(0), [comparison, setComparison] = useState(false), [scopeDetails, setScopeDetails] = useState(false), [selectedDay, setSelectedDay] = useState<string | null>(null);
  const alive = useRef(true), active = useRef(false), generation = useRef(0), readGeneration = useRef(0), readyRef = useRef(false);
  active.current = presented && identity.permissions.dashboard_view === true;
  const query: LeadershipQuery = { month, period, ...(period === 'date' ? { date: customDate } : {}), ...(companyId ? { companyId } : {}) }, key = JSON.stringify(query);
  const data = report?.key === key ? report.value : null;
  const live = online && !report?.cached;
  const latestKey = useRef(key); latestKey.current = key;
  const deny = (failure: unknown) => { engine.clear(); readyRef.current = false; setReady(false); setOptions(null); setReport(null); setComparison(false); setScopeDetails(false); setSelectedDay(null); setError(failure); };
  useEffect(() => { alive.current = true; return () => { alive.current = false; engine.cancelReads(); }; }, [engine]);
  useEffect(() => {
    const ticket = ++generation.current; engine.cancelReads(); readyRef.current = false; setReady(false); setReading(false);
    if (!online) { setReport(null); setComparison(false); setScopeDetails(false); setSelectedDay(null); }
    if (!active.current) { setComparison(false); setScopeDetails(false); setSelectedDay(null); if (!identity.permissions.dashboard_view) { engine.clear(); setReport(null); setOptions(null); } return; }
    setBusy(true); setError(null);
    void engine.options().then(next => { if (!alive.current || !active.current || ticket !== generation.current) return;
      if (!next.can_view) { deny({ code: 'forbidden' }); return; }
      const companies = next.companies.filter(c => identity.company_ids.includes(c.id));
      if (companies.length !== next.companies.length) { deny({ code: 'forbidden' }); return; }
      setCompany(current => companies.length === 1 ? companies[0].id : companies.some(c => c.id === current) ? current : 0);
      setOptions(next); readyRef.current = true; setReady(true);
    }).catch(failure => { if (alive.current && active.current && ticket === generation.current) { if (accessDenied(failure)) deny(failure); else if (failure?.code !== 'stale') setError(failure); } })
      .finally(() => { if (alive.current && ticket === generation.current) setBusy(false); });
    return () => { generation.current++; engine.cancelReads(); };
  }, [presented, online, identity.permissions.dashboard_view, engine]);
  useEffect(() => {
    if (!active.current || !ready || !readyRef.current) return;
    const ticket = ++readGeneration.current; setReading(true); setError(null); setSelectedDay(null);
    void engine.read(query).then(value => { if (alive.current && active.current && ticket === readGeneration.current && latestKey.current === key) setReport({ key, value, cached: engine.displayIsCached ?? !online }); })
      .catch(failure => { if (alive.current && active.current && ticket === readGeneration.current) { if (accessDenied(failure)) deny(failure); else if (failure?.code !== 'stale') { if (!online) setReport(null); setError(failure); } } })
      .finally(() => { if (alive.current && ticket === readGeneration.current) setReading(false); });
    // A report cleanup must not cancel a newer options verification on reconnect.
    return () => { readGeneration.current++; };
  }, [key, ready, refresh, online, engine]);
  useEffect(() => {
    if (!report?.cached) return;
    const remaining = engine.displayLeaseRemainingMs;
    if (!Number.isFinite(remaining)) return;
    const expire = () => { engine.cancelReads(); setReading(false); setReport(null); setComparison(false); setScopeDetails(false); setSelectedDay(null); readyRef.current = false; setReady(false); setError({ code: 'snapshot_unavailable' }); };
    if (!(remaining > 0)) { expire(); return; }
    const timer = setTimeout(expire, remaining); return () => clearTimeout(timer);
  }, [engine, online, report]);
  const choose = useCallback((action: () => void) => { if (!active.current || !readyRef.current) return; engine.cancelReads(); setComparison(false); setScopeDetails(false); setSelectedDay(null); setError(null); action(); }, [engine]);
  const selectMonth = useCallback((selected: string) => choose(() => { setMonth(selected); if (period === 'date') setCustomDate(`${selected}-01`); }), [choose, period]);
  const refreshReport = () => { if (active.current) { if (readyRef.current) setRefresh(v => v + 1); else { setReady(false); setRefresh(v => v + 1); /* Retry options below through remount-free callback. */ void retryOptions(); } } };
  const retryOptions = async () => { if (!active.current) return; const ticket = ++generation.current; setBusy(true); setError(null);
    try { const next = await engine.options(); if (alive.current && active.current && ticket === generation.current) { setOptions(next); setCompany(next.companies.length === 1 ? next.companies[0].id : 0); readyRef.current = true; setReady(true); } }
    catch (failure) { if (alive.current && active.current && ticket === generation.current) { if (accessDenied(failure)) deny(failure); else setError(failure); } }
    finally { if (alive.current && ticket === generation.current) setBusy(false); } };
  if (!presented) return <View testID="leadership-privacy-cover" style={s.fill} />;
  const day = data?.calendar.days.find(d => d.date === selectedDay) ?? data?.previous_calendar.days.find(d => d.date === selectedDay);
  return <View style={s.fill} testID="leadership-screen">
    <View style={[s.header, row(language)]}>
      {onBack && <IconButton icon="back" label={t('back')} onPress={onBack} />}
      <Text style={[s.title, direction(language), { flex: 1 }]}>{t('title')}</Text>
      <IconButton icon="refresh" label={t('refresh')} busy={busy || reading} onPress={refreshReport} disabled={!identity.permissions.dashboard_view} />
    </View>
    {!identity.permissions.dashboard_view ? <View style={s.content}><Label language={language}>{t('noAccess')}</Label></View> : <>
      <View style={[s.tabs, row(language)]}>{(['overview', 'heatmap'] as const).map(value => <Pressable key={value} testID={`leadership-tab-${value}`} accessibilityRole="tab" accessibilityState={{ selected: tab === value }} onPress={() => setTab(value)} style={[s.tab, tab === value && s.selected]}><Text style={[direction(language), { color: tab === value ? colors.blue : colors.muted, fontWeight: '600' }]}>{t(value)}</Text></Pressable>)}</View>
      <ScrollView contentContainerStyle={[s.content, tab === 'heatmap' && s.calendarContent]} testID="leadership-scroll">
        {options && options.companies.length > 1 && <View style={[s.row, row(language), { flexWrap: 'wrap' }]} testID="leadership-companies">{[{ id: 0, name: t('all') }, ...options.companies].map(company => { const profile = identity.profile?.companies.find(c => c.id === company.id), name = profile ? companyDisplayName(profile, language, company.id) : company.name; return <Pressable key={company.id} testID={`leadership-company-${company.id}`} accessibilityRole="button" accessibilityLabel={name} accessibilityState={{ selected: companyId === company.id, disabled: !ready }} disabled={!ready} onPress={() => choose(() => setCompany(company.id))} style={[s.companyChip, companyId === company.id && { backgroundColor: colors.blue, borderColor: colors.blue }]}><Text style={[direction(language), { fontSize: 11, color: companyId === company.id ? colors.white : colors.muted }]}>{name}</Text></Pressable>; })}</View>}
        {!!error && <View accessibilityLiveRegion="polite" testID="leadership-error"><Label language={language}>{t(errorWord(error))}</Label><Button quiet title={t('retry')} onPress={refreshReport} /></View>}
        {(busy || reading) && !data && <ActivityIndicator color={colors.blue} accessibilityLabel={t('loading')} />}
        {(ready || data) && <>
          {tab === 'overview' && <View style={s.panel}>
            <View style={[s.periods, row(language)]}>{(['yesterday', 'today', 'month', 'date'] as const).map(value => <Pressable key={value} testID={`leadership-period-${value}`} accessibilityRole="button" accessibilityState={{ selected: period === value, disabled: !ready }} disabled={!ready} onPress={() => choose(() => { setPeriod(value); if (value === 'date' && customDate.slice(0, 7) !== month) setCustomDate(`${month}-01`); })} style={[s.period, period === value && { backgroundColor: colors.blue }]}><Text style={[direction(language), { fontSize: 12, color: period === value ? colors.white : colors.muted }]}>{t(value)}</Text></Pressable>)}</View>
            {period === 'date' && <DateTimeField disabled={!ready} label={t('chooseDate')} testID="leadership-date" language={language} value={pickerValue(customDate)} onChange={value => { if (value) choose(() => { const selected = chosenDate(value); setCustomDate(selected); setMonth(selected.slice(0, 7)); }); }} />}
            {data && <>
              <View style={[s.cards, row(language)]} testID="leadership-three-cards">
                <SummaryCard disabled={!ready} word="sales" amount={data.overview.sales} change={data.overview.current_month.sales_change} average={data.overview.current_month.daily_average} forecast={data.overview.current_month.forecast} language={language} primary onPress={() => { if (active.current && readyRef.current) setComparison(true); }} />
                <SummaryCard disabled={!ready} word="spending" amount={data.overview.spending} ratio={data.overview.spending_ratio} change={data.overview.current_month.spending_change} language={language} onPress={() => { if (active.current && readyRef.current) setScopeDetails(true); }} />
                <SummaryCard disabled={!ready} word="difference" amount={data.overview.difference} ratio={data.overview.difference_ratio} change={data.overview.current_month.difference_change} language={language} onPress={() => { if (active.current && readyRef.current) setScopeDetails(true); }} />
              </View>
              <Text style={[s.caption, direction(language)]}>{data.filters.from} — {data.filters.to}</Text>
            </>}
          </View>}
          <View style={[s.panel, tab === 'heatmap' && s.calendarPanel]} testID="leadership-calendar-panel">
            <MonthField key={String(online)} disabled={!ready} label={t('chooseMonth')} testID="leadership-month" language={language} value={month} onChange={selectMonth} />
            {data && (tab === 'heatmap' ? <>
              <Text style={[s.heading, direction(language)]}>{monthLabel(data.calendar.month, language)}</Text>
              <Text style={[s.caption, direction(language)]}>{t('weekdayAverage')}</Text>
              <View style={s.weekdays} testID="leadership-weekday-averages" accessibilityLabel={t('positiveDays')}>{[5, 6, 0, 1, 2, 3, 4].map(index => { const item = data.calendar.weekdays.find(w => w.weekday === index)!, name = weekdayName(language, index); return <View key={index} style={s.weekday} accessibilityLabel={`${name}: ${calendarIntegerDisplay(item.average)}; ${t('sample')}: ${String(item.sample_count)}`}><Text style={[s.caption, direction(language)]} numberOfLines={1}>{name}</Text><Money amount={item.average} size={11} center calendarInteger /></View>; })}</View>
              <Heatmap live={live} disabled={!ready} days={data.calendar.days} asOf={data.as_of} companyCount={data.companies.length} language={language} selected={selectedDay} onSelect={date => { if (active.current && readyRef.current) setSelectedDay(date); }} />
              <View style={[s.row, row(language), { flexWrap: 'wrap' }]}>{(['recordedZero', 'noRecords', 'partial', 'future'] as const).map(word => <Text key={word} style={[s.legend, direction(language)]}>{t(word)}</Text>)}</View>
            </> : <>
              <Text style={[s.heading, direction(language)]}>{monthLabel(data.calendar.month, language)}</Text>
              <Trend disabled={!ready} report={data} language={language} onSelect={date => { if (active.current && readyRef.current) setSelectedDay(date); }} selected={selectedDay} />
            </>)}
          </View>
        </>}
      </ScrollView>
      {day && ready && data && <Sheet title={`${t('selectedDay')} · ${day.date}`} close={() => setSelectedDay(null)} t={translator(language)} language={language} compact>
        <View testID="leadership-day-detail" style={{ gap: 8 }}>
          <Detail label={t('sales')} amount={day.sales} language={language} /><Label language={language}>{dayLabel(day, data.as_of, language, live)}</Label><Label language={language} muted>{coverageLabel(day, data.companies.length, language)}</Label>
          <Detail label={t('target')} amount={day.target} language={language} /><Detail label={t(day.basis_kind === 'target' ? 'target' : day.basis_kind === 'baseline' ? 'baseline' : 'noBasis')} amount={day.basis} language={language} /><Detail label={t('ratio')} amount={day.ratio} percent language={language} />
          {tab === 'overview' && <Detail label={`${t('previous')} · ${data.previous_calendar.days.find(d => d.day === day.day)?.date ?? '—'}`} amount={data.previous_calendar.days.find(d => d.day === day.day)?.sales} language={language} />}
        </View>
      </Sheet>}
      {comparison && ready && data && <Sheet title={t('comparison')} close={() => setComparison(false)} t={translator(language)} language={language} compact>
        <Label language={language}>{t('current')} · {data.overview.current_month.month}</Label><Label language={language}>{t('fixedComparison')}</Label><Label language={language} muted>{data.overview.current_month.from} — {data.overview.current_month.to}</Label>
        <Detail label={t('sales')} amount={data.overview.current_month.sales} language={language} /><Detail label={t('previousSales')} amount={data.overview.current_month.previous_sales} language={language} /><Detail label={t('dailyAverage')} amount={data.overview.current_month.daily_average} language={language} /><Detail label={t('previousAverage')} amount={data.overview.current_month.previous_daily_average} language={language} /><Detail label={t('salesChange')} amount={data.overview.current_month.sales_change} percent trend="higher" language={language} /><Detail label={t('spendingChange')} amount={data.overview.current_month.spending_change} percent trend="lower" language={language} /><Detail label={t('differenceChange')} amount={data.overview.current_month.difference_change} percent trend="higher" language={language} />
      </Sheet>}
      {scopeDetails && ready && data && <Sheet title={t('details')} close={() => setScopeDetails(false)} t={translator(language)} language={language} compact><View testID="leadership-spending-detail"><Label language={language} muted>{data.filters.from} — {data.filters.to}</Label><Detail label={t('purchases')} amount={data.overview.spending_breakdown.purchases} language={language} /><Detail label={t('operating')} amount={data.overview.spending_breakdown.operating} language={language} /><Detail label={t('spending')} amount={data.overview.spending} language={language} /><Detail label={t('difference')} amount={data.overview.difference} language={language} /><Label language={language} muted>{t('supplierScope')}</Label><Label language={language} muted>{t('differenceHelp')}</Label></View></Sheet>}
    </>}
  </View>;
}

type TrendDirection = 'higher' | 'lower';
function Money({ amount, size = 22, percent = false, trend, center = false, calendarInteger = false }: { amount?: Amount; size?: number; percent?: boolean; trend?: TrendDirection; center?: boolean; calendarInteger?: boolean }) {
  const value = percent ? percentagePresentation(amount, trend) : { display: calendarInteger ? calendarIntegerDisplay(amount) : amount?.display ?? '—', tone: 'neutral' };
  const color = value.tone === 'favorable' ? colors.success : value.tone === 'unfavorable' ? colors.danger : colors.ink;
  return <Text numberOfLines={calendarInteger ? undefined : 1} adjustsFontSizeToFit={calendarInteger ? undefined : true} minimumFontScale={calendarInteger ? undefined : .45} style={{ color, fontSize: size, fontWeight: '700', writingDirection: 'ltr', textAlign: center ? 'center' : 'left', alignSelf: center ? 'stretch' : undefined, fontVariant: ['tabular-nums'], flexShrink: 1 }}>{calendarInteger ? value.display.replace(/,/g, ',\u200b') : value.display}</Text>;
}
function SummaryCard({ word, amount, ratio, change, average, forecast, language, primary, onPress, disabled }: { word: LeadershipWord; amount: Amount; ratio?: Amount; change: Amount; average?: Amount; forecast?: Amount; language: Language; primary?: boolean; onPress?: () => void; disabled?: boolean }) {
  const t = leadershipTranslator(language), trend = word === 'spending' ? 'lower' : 'higher';
  return <Pressable testID={`leadership-card-${word}`} accessibilityRole="button" accessibilityLabel={`${t(primary ? 'openDetails' : word)}: ${amount.display}`} accessibilityState={{ disabled }} disabled={disabled} onPress={onPress} style={[s.card, primary && { backgroundColor: colors.pale, borderColor: colors.blue }]}>
    <View style={{ gap: 4, minHeight: 37 }}><Text style={[s.cardTitle, direction(language)]}>{t(word)}</Text>{primary && <CompactMetric label={t('monthChange')} amount={change} percent trend={trend} language={language} />}</View>
    <Money amount={amount} size={23} /><View style={{ gap: 5 }}>
      {average && <CompactMetric label={t('daily')} amount={average} language={language} />}{forecast && <CompactMetric label={t('estimated')} amount={forecast} language={language} />}
      {ratio && <CompactMetric label={t('ratio')} amount={ratio} percent language={language} />}{!primary && <CompactMetric label={t('monthChange')} amount={change} percent trend={trend} language={language} />}
    </View>
  </Pressable>;
}
function CompactMetric({ label, amount, language, percent, trend }: { label: string; amount: Amount; language: Language; percent?: boolean; trend?: TrendDirection }) { return <View style={[row(language), { alignItems: 'center', gap: 3, justifyContent: 'space-between' }]}><Text style={[direction(language), { fontSize: 9, color: colors.muted, flexShrink: 1 }]}>{label}</Text><Money amount={amount} size={11} percent={percent} trend={trend} /></View>; }
function Detail({ label, amount, language, percent, trend }: { label: string; amount?: Amount; language: Language; percent?: boolean; trend?: TrendDirection }) { return <View style={[s.row, row(language), { justifyContent: 'space-between', paddingVertical: 5 }]}><Text style={[s.caption, direction(language), { flex: 1 }]}>{label}</Text><Money amount={amount} size={16} percent={percent} trend={trend} /></View>; }

const heatColor = (day: LeadershipDay, asOf: string, live: boolean): string => {
  if (dayWord(day, asOf, live) === 'future') return '#f3f5f8';
  if (dayWord(day, asOf, live) === 'inProgress') return colors.pale;
  if (!day.sales.available || !day.has_sales) return colors.white;
  if (day.status === 'partial' || day.status === 'incomplete') return colors.warning;
  if (day.sales.value && /^-?0(?:\.0+)?$/.test(day.sales.value)) return '#e9eef4';
  return ({ neutral: colors.pale, watch: '#edf0c8', high: '#b9e6d3', good: '#d7eadc', low: '#fae2c3' } as Record<string, string>)[day.heat_level] ?? colors.pale;
};
function Heatmap({ days, asOf, companyCount, language, selected, onSelect, disabled, live }: { days: LeadershipDay[]; asOf: string; companyCount: number; language: Language; selected: string | null; onSelect: (date: string) => void; disabled?: boolean; live: boolean }) {
  const t = leadershipTranslator(language), today = snapshotDate(asOf), [width, setWidth] = useState(0);
  const first = days[0], blank = first ? (first.weekday - 5 + 7) % 7 : 0;
  // Explicit weeks avoid percentage/flexWrap rounding creating six columns.
  const cells: Array<LeadershipDay | null> = [...Array(blank).fill(null), ...days];
  const weeks = Array.from({ length: Math.ceil(cells.length / 7) }, (_, week) =>
    Array.from({ length: 7 }, (_, column) => cells[week * 7 + column] ?? null));
  return <View testID="leadership-heatmap" onLayout={event => setWidth(event.nativeEvent.layout.width)}>
    {weeks.map((week, index) => <View key={index} testID={`leadership-week-${index}`} style={s.weekdays}>
      {week.map((day, column) => {
        const current = live && day?.date === today, chosen = day?.date === selected;
        const display = day?.has_sales && day.sales.available ? calendarIntegerDisplay(day.sales) : '—';
        return <View key={day?.date ?? `blank-${column}`} style={s.heatSlot}>
          {day && <Pressable disabled={disabled} testID={`leadership-day-${day.date}`} accessibilityRole="button"
            accessibilityLabel={`${day.date}, ${display}, ${dayLabel(day, asOf, language, live)}, ${coverageLabel(day, companyCount, language)}`}
            accessibilityState={{ selected: chosen, disabled }} onPress={() => onSelect(day.date)}
            style={[s.heatDay, { backgroundColor: heatColor(day, asOf, live), borderColor: current || chosen ? colors.blue : colors.border,
              borderStyle: !current && (!day.has_sales || !day.sales.available) ? 'dashed' : 'solid' }]}>
            <Text style={[s.heatDate, { color: current ? colors.blue : dayWord(day, asOf, live) === 'future' ? colors.muted : colors.ink }]}>{String(day.day)}</Text>
            <View style={s.heatValue}>
              {/* Display-only ceil; full exact decimals remain in the selected-day detail.
                  Keep all integer digits and sign, wrapping only at thousands. */}
              <Text testID={`leadership-day-sales-${day.date}`} textBreakStrategy="simple" android_hyphenationFrequency="none"
                style={[s.heatAmount, { fontSize: width >= 420 ? 12 : 10 }]}>{display.replace(/,/g, ',\u200b')}</Text>
            </View>
            {current && <Text testID={`leadership-day-live-${day.date}`} style={[s.heatLive, direction(language)]}>{t('live')}</Text>}
          </Pressable>}
        </View>;
      })}
    </View>)}
  </View>;
}

/** Conversion and arithmetic below place points only; all reported business values are server displays. */
function Trend({ report, language, onSelect, selected, disabled }: { report: LeadershipReport; language: Language; onSelect: (date: string) => void; selected: string | null; disabled?: boolean }) {
  const t = leadershipTranslator(language), [showPrevious, setPrevious] = useState(true), [showActual, setActual] = useState(true), [width, setWidth] = useState(320);
  const current = report.calendar.days, prior = report.previous_calendar.days, inspection = Array.from({ length: Math.max(current.length, prior.length) }, (_, index) => current[index] ?? prior[index]), visible = (d: LeadershipDay) => d.has_sales && d.sales.available && d.sales.value !== null;
  const snapshotDay = snapshotDate(report.as_of);
  const actual = current.filter(d => d.date < snapshotDay && ['complete', 'closed'].includes(d.status));
  const values = [...(showActual ? actual : []), ...(showPrevious ? prior : [])].filter(visible).map(d => Number(d.sales.value));
  const low = Math.min(0, ...values), high = Math.max(0, ...values), span = high - low || 1;
  const x = (day: number) => 14 + (day - 1) * 292 / 30, y = (value: number) => 150 - (value - low) / span * 130;
  const path = (days: LeadershipDay[]) => { let connected = false; return days.map(d => { if (!visible(d)) { connected = false; return ''; } const p = `${connected ? 'L' : 'M'}${x(d.day).toFixed(2)},${y(Number(d.sales.value)).toFixed(2)}`; connected = true; return p; }).join(' '); };
  return <View style={{ gap: 6 }} testID="leadership-trend">
    <View style={[s.row, row(language), { flexWrap: 'wrap' }]}><Pressable disabled={disabled} accessibilityRole="button" accessibilityState={{ selected: showActual, disabled }} onPress={() => setActual(v => !v)} style={s.series}><Text style={{ color: showActual ? colors.blue : colors.muted }}>━ {t('actual')}</Text></Pressable><Pressable disabled={disabled} accessibilityRole="button" accessibilityState={{ selected: showPrevious, disabled }} onPress={() => setPrevious(v => !v)} style={s.series}><Text style={{ color: colors.muted }}>┄ {t('previous')}{!showPrevious && ' · —'}</Text></Pressable></View>
    <Pressable disabled={disabled} accessibilityRole="imagebutton" accessibilityLabel={t('inspect')} testID="leadership-chart" onLayout={event => setWidth(event.nativeEvent.layout.width)} onPress={event => { const day = Math.max(1, Math.min(inspection.length, Math.round((event.nativeEvent.locationX / Math.max(width, 1) * 320 - 14) / 292 * 30) + 1)); onSelect(inspection[day - 1].date); }} style={{ height: 174 }}>
      <Svg width="100%" height="174" viewBox="0 0 320 174" preserveAspectRatio="none"><Line x1={14} x2={306} y1={y(0)} y2={y(0)} stroke={colors.border} />{showPrevious && <Path d={path(prior)} fill="none" stroke={colors.muted} strokeWidth={1.5} strokeDasharray="5 4" />}{showActual && <Path d={path(current.map(d => actual.includes(d) ? d : { ...d, has_sales: false }))} fill="none" stroke={colors.blue} strokeWidth={2.5} />}{selected && <Line x1={x(Number(selected.slice(8)))} x2={x(Number(selected.slice(8)))} y1={10} y2={155} stroke={colors.blue} strokeDasharray="3 3" />}</Svg>
    </Pressable>
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ direction: 'ltr' }}><View style={{ flexDirection: 'row' }}>{inspection.map(d => <Pressable disabled={disabled} key={d.date} accessibilityRole="button" accessibilityLabel={`${d.date}, ${d.sales.display}`} accessibilityState={{ selected: d.date === selected, disabled }} testID={`leadership-inspect-${d.day}`} onPress={() => onSelect(d.date)} style={[s.dayChip, selected === d.date && s.selected]}><Text style={{ color: colors.muted }}>{String(d.day)}</Text></Pressable>)}</View></ScrollView>
  </View>;
}

const s = StyleSheet.create({
  fill: { flex: 1, minHeight: 0, backgroundColor: colors.background }, header: { backgroundColor: colors.white, paddingHorizontal: 12, minHeight: 58, gap: 8, alignItems: 'center' }, title: { fontSize: 19, fontWeight: '700', color: colors.ink },
  content: { padding: 12, gap: 12, paddingBottom: 26, width: '100%', maxWidth: 760, alignSelf: 'center' }, tabs: { paddingHorizontal: 12, paddingVertical: 6, backgroundColor: colors.white, gap: 6 }, tab: { flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 10 }, selected: { backgroundColor: colors.pale },
  calendarContent: { paddingHorizontal: 6 }, calendarPanel: { paddingHorizontal: 6 },
  panel: { backgroundColor: colors.white, borderRadius: 16, borderWidth: 1, borderColor: colors.border, padding: 12, gap: 10 }, row: { gap: 8, alignItems: 'center' }, heading: { fontSize: 15, color: colors.ink, fontWeight: '700' }, caption: { fontSize: 11, color: colors.muted },
  cards: { gap: 6, alignItems: 'stretch' }, card: { flex: 1, minWidth: 0, minHeight: 152, borderRadius: 12, padding: 8, gap: 9, borderWidth: 1, borderColor: colors.border, justifyContent: 'space-between' }, cardTitle: { fontSize: 12, color: colors.muted }, companyChip: { minHeight: 44, paddingHorizontal: 9, justifyContent: 'center', borderRadius: 9, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.white },
  periods: { padding: 3, gap: 3, backgroundColor: colors.background, borderRadius: 10 }, period: { flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 8 }, stats: { gap: 12, flexWrap: 'wrap' }, stat: { width: '47%', minWidth: 0, gap: 8, paddingVertical: 8 },
  weekdays: { flexDirection: 'row', direction: 'ltr' }, weekday: { flex: 1, minWidth: 0, alignItems: 'center', gap: 5, paddingVertical: 3 },
  heatSlot: { flex: 1, minWidth: 0, padding: 2, minHeight: 88 }, heatDay: { flex: 1, minHeight: 84, paddingHorizontal: 0, paddingVertical: 5, alignItems: 'center', borderWidth: 1, borderRadius: 8, gap: 3 },
  heatDate: { fontSize: 12, lineHeight: 16, fontWeight: '600', writingDirection: 'ltr', fontVariant: ['tabular-nums'] },
  heatValue: { flex: 1, alignSelf: 'stretch', justifyContent: 'center', minWidth: 0 },
  heatAmount: { lineHeight: 15, letterSpacing: -.15, color: colors.ink, textAlign: 'center', writingDirection: 'ltr', fontWeight: '600', fontVariant: ['tabular-nums'] },
  heatLive: { color: colors.blue, fontSize: 10, lineHeight: 14, fontWeight: '600', textAlign: 'center' },
  legend: { fontSize: 10, color: colors.muted, paddingVertical: 4 }, series: { minHeight: 44, justifyContent: 'center' }, dayChip: { minWidth: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 8 },
});
