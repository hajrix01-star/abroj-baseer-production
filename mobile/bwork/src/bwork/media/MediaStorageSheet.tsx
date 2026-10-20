import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, AppState, Switch, View } from 'react-native';
import { Button, colors, Label, Sheet, styles } from '../ui/components';
import type { Language, Translate } from '../ui/dictionary';
import { mediaTranslator } from './dictionary';
import { mediaCacheOverview, planMediaCacheCleanup, confirmMediaCacheCleanup, setMediaCachePolicy } from '../runtime';
import type { MediaCacheOverview, MediaCacheCleanPlan, MediaCacheCleanResult, MediaCacheTotals } from '../storage/MediaCacheContracts';

function Totals({ title, value, language }: { title: string; value: MediaCacheTotals; language: Language }) {
  return <View style={{ padding: 12, gap: 4, borderRadius: 12, backgroundColor: colors.pale }}>
    <Label language={language}>{title}</Label>
    <Label language={language}>{value.bytesDisplay} · {value.filesDisplay}</Label>
  </View>;
}
export function MediaStorageSheet({ scopeKey, language, t, close }: {
  scopeKey: string; language: Language; t: Translate; close(): void;
}) {
  const mt = mediaTranslator(language);
  const [overview, setOverview] = useState<MediaCacheOverview | null>(null);
  const [plan, setPlan] = useState<MediaCacheCleanPlan | null>(null);
  const [result, setResult] = useState<MediaCacheCleanResult | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(false);
  const owner = useRef({ key: scopeKey, serial: 0, working: false, active: AppState.currentState === 'active' });
  if (owner.current.key !== scopeKey) owner.current = { key: scopeKey, serial: owner.current.serial + 1, working: false, active: AppState.currentState === 'active' };
  const run = async (task: (live: () => boolean) => Promise<void>) => {
    const current = owner.current;
    if (current.key !== scopeKey || current.working || !current.active || AppState.currentState !== 'active') return;
    current.working = true;
    const serial = ++current.serial;
    setBusy(true); setError(false);
    const live = () => owner.current === current && current.serial === serial && current.active && AppState.currentState === 'active';
    try { await task(live); } catch { if (live()) setError(true); }
    finally { if (live()) { current.working = false; setBusy(false); } }
  };
  const load = async () => {
    const current = owner.current, serial = current.serial;
    if (current.key !== scopeKey || !current.active || AppState.currentState !== 'active') return;
    const value = await mediaCacheOverview();
    if (owner.current === current && current.serial === serial && current.active && AppState.currentState === 'active') setOverview(value);
  };
  useEffect(() => {
    const current = owner.current;
    void run(load);
    const listener = AppState.addEventListener('change', state => {
      if (state !== 'active') { current.active = false; current.serial++; close(); }
    });
    return () => { current.active = false; current.serial++; listener.remove(); };
    // A keyed account scope owns every plan and result; language does not renew it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeKey]);
  const allowed = () => owner.current.key === scopeKey && owner.current.active && AppState.currentState === 'active';
  return <Sheet title={mt('storage')} close={close} language={language} t={t} compact>
    {busy && <ActivityIndicator color={colors.blue} accessibilityLabel={t('loading')} />}
    {error && <Label language={language}>{mt('cleanupFailed')}</Label>}
    <Label language={language} muted>{mt('deviceOnly')}</Label>
    {plan ? <>
      <Totals title={mt('preview')} value={plan.estimated} language={language} />
      <Label language={language}>{mt('warning')}</Label>
      <Label language={language} muted>{mt('previewHint')}</Label>
      <Button title={mt('confirm')} busy={busy} disabled={busy || plan.estimated.files === 0} onPress={() => {
        if (!allowed() || busy) return;
        const token = plan.id;
        void run(async live => {
          const value = await confirmMediaCacheCleanup(token);
          if (!live()) return;
          setPlan(null); setResult(value); await load();
        });
      }} />
      <Button quiet title={mt('cancel')} disabled={busy} onPress={() => { if (allowed()) setPlan(null); }} />
    </> : <>
      {overview && <>
        <Totals title={mt('total')} value={overview.total} language={language} />
        <Totals title={mt('protected')} value={overview.protected} language={language} />
        <View style={[styles.row, { alignItems: 'center', gap: 12 }]}>
          <View style={{ flex: 1 }}><Label language={language}>{mt('auto')}</Label><Label language={language} muted>{mt('autoHint')}</Label></View>
          <Switch accessibilityLabel={mt('auto')} disabled={busy} value={overview.policy.autoClean30Days} onValueChange={value => {
            if (allowed() && !busy) void run(async live => { await setMediaCachePolicy(value); if (live()) await load(); });
          }} />
        </View>
        <Button title={mt('clean')} busy={busy} disabled={busy || overview.total.files === 0} onPress={() => {
          if (!allowed() || busy) return;
          void run(async live => { const value = await planMediaCacheCleanup('all'); if (live()) { setPlan(value); setResult(null); } });
        }} />
      </>}
      <Button quiet title={mt('refresh')} disabled={busy} onPress={() => { if (allowed()) void run(load); }} />
      {result && <View style={{ gap: 8 }}>
        <Label language={language}>{mt(result.partial ? 'partial' : result.deleted.files ? 'complete' : 'nothing')}</Label>
        <Totals title={mt('deleted')} value={result.deleted} language={language} />
        {result.skipped.files > 0 && <Totals title={mt('skipped')} value={result.skipped} language={language} />}
        {result.failed.files > 0 && <Totals title={mt('errors')} value={result.failed} language={language} />}
      </View>}
    </>}
  </Sheet>;
}
