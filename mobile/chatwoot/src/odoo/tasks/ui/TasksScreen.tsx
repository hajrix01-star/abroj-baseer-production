import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, KeyboardAvoidingView, Platform, Pressable, Text, View } from 'react-native';
import type { Bootstrap } from '../../core/ChatEngine';
import { Button, colors, direction, IconButton, Label } from '../../ui/components';
import { CompanySelector } from '../../ui/CompanySelector';
import { companyDisplayName } from '../../ui/companyNames';
import { translator, type Language } from '../../ui/dictionary';
import type { TasksEngine } from '../core/TasksEngine';
import type { PendingTaskAttempt, TaskSelection, TasksStateFilter, TasksView, WorkTask, WorkTasksOptions, WorkTaskWriteResult } from '../core/types';
import { taskAccessDenied, taskErrorWord, taskTranslator } from '../dictionary';
import { TaskCard } from './TaskCard';
import { TaskComposer } from './TaskComposer';
import { TaskDetail } from './TaskDetail';
import { taskRow, taskStyles as s } from './taskStyles';

export interface TasksScreenProps { engine: TasksEngine; identity: Bootstrap; language: Language; presented: boolean; scopeKey: string; onBack?: () => void }

/** The scope key clears private state on identity/permission change, not on verification. */
export function TasksScreen(props: TasksScreenProps) {
  const t = taskTranslator(props.language), scope = JSON.stringify([props.scopeKey, props.identity.database, props.identity.user_id, props.identity.company_ids, props.identity.permissions]);
  return <View style={s.fill} testID="tasks-screen">
    <View pointerEvents={props.presented ? 'auto' : 'none'} accessibilityElementsHidden={!props.presented} importantForAccessibility={props.presented ? 'auto' : 'no-hide-descendants'}
      style={[s.fill, !props.presented && { opacity: 0 }]} testID="tasks-retained-workspace">
      <Workspace key={scope} {...props} />
    </View>
    {!props.presented && <View testID="tasks-privacy-cover" style={{ position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, backgroundColor: colors.white }} />}
    {!props.identity.permissions.task_view && props.presented && <View style={s.content}><Label language={props.language}>{t('noAccess')}</Label><Label language={props.language} muted>{t('permissionHelp')}</Label></View>}
  </View>;
}

function Workspace({ engine, identity, language, presented, onBack }: TasksScreenProps) {
  const t = taskTranslator(language), [options, setOptions] = useState<WorkTasksOptions | null>(null), [error, setError] = useState<unknown>(null), [busy, setBusy] = useState(false), [optionsReady, setOptionsReady] = useState(false);
  const [view, setView] = useState<TasksView>('mine'), [state, setState] = useState<TasksStateFilter>('open'), [filter, setFilter] = useState(0);
  const [mode, setMode] = useState<'list' | 'create' | 'detail'>('list'), [detail, setDetail] = useState<WorkTask | null>(null), [detailBusy, setDetailBusy] = useState(false);
  const [lastCompany, setLastCompany] = useState(0), [createCompany, setCreateCompany] = useState(0), [refresh, setRefresh] = useState(0), [pending, setPending] = useState<PendingTaskAttempt[]>([]);
  const alive = useRef(true), active = useRef(presented), optionsGate = useRef(false), detailGeneration = useRef(0), optionsGeneration = useRef(0);
  const knownDenied = useRef(false);
  active.current = presented && identity.permissions.task_view === true;
  const retryRead = useRef<{ run: () => void; needsOptions: boolean } | null>(null), [resumeTick, setResumeTick] = useState(0), recovered = useRef(false), pendingDirty = useRef(false);
  const keyboardFrame = useRef<View>(null), measureGeneration = useRef(0), [keyboardOffset, setKeyboardOffset] = useState(0);
  if (!presented) recovered.current = false;
  const networkLive = () => alive.current && active.current;
  const ready = presented && optionsReady && !knownDenied.current;
  const live = () => networkLive() && optionsReady && !knownDenied.current;
  const denySection = (failure: unknown) => {
    if (!alive.current) return;
    knownDenied.current = true; retryRead.current = null; optionsGeneration.current++; detailGeneration.current++; engine.cancelReads();
    optionsGate.current = false; pendingDirty.current = true; setOptionsReady(false); setOptions(null); setDetail(null); setPending([]); setMode('list');
    setCreateCompany(0); setLastCompany(0); setFilter(0); setBusy(false); setDetailBusy(false); setError(failure);
  };
  const companies: TaskSelection[] = (options?.companies ?? []).filter(company => identity.company_ids.includes(company.id)).map(company => {
    const profile = identity.profile?.companies.find(item => item.id === company.id);
    return { id: company.id, name: profile ? companyDisplayName(profile, language, company.id) : company.name };
  });
  const name = (task: WorkTask) => companies.find(company => company.id === task.company_id)?.name ?? task.company_name;
  const readCompany = companies.length === 1 ? companies[0].id : companies.some(company => company.id === filter) ? filter : 0;
  const canManage = options?.can_manage === true && identity.permissions.task_manage === true;
  const interrupted = (failure: unknown, retry: () => void, needsOptions = true) => {
    if (failure && typeof failure === 'object' && 'code' in failure && failure.code === 'stale' && (!active.current || !recovered.current)) {
      retryRead.current = { run: retry, needsOptions }; setResumeTick(value => value + 1); return true;
    }
    return false;
  };
  const loadPending = async () => { if (!networkLive() || knownDenied.current) { pendingDirty.current = true; return; } try { const next = await engine.pending(); if (networkLive() && !knownDenied.current) { setPending(next); pendingDirty.current = false; } }
    catch (failure) { if (alive.current && taskAccessDenied(failure)) denySection(failure); else if (networkLive()) setError(failure); } };
  const loadOptions = async () => {
    if (!networkLive() || optionsGate.current) return; optionsGate.current = true; const generation = ++optionsGeneration.current; setBusy(true); setError(null); setOptionsReady(false);
    try { const next = await engine.options(); if (!networkLive() || generation !== optionsGeneration.current) return;
      if (!next.can_view) { denySection({ code: 'forbidden', status: 403 }); return; }
      knownDenied.current = false; setOptions(next); setOptionsReady(true);
      if (!next.can_manage) setMode(current => current === 'create' ? 'list' : current); await loadPending(); }
    catch (failure) { if (alive.current && generation === optionsGeneration.current) { if (taskAccessDenied(failure)) denySection(failure); else if (!interrupted(failure, () => void loadOptions(), false)) setError(failure); } }
    finally { optionsGate.current = false; if (alive.current && generation === optionsGeneration.current) setBusy(false); }
  };
  const openDetail = async (task: WorkTask) => {
    if (!live() || !companies.some(company => company.id === task.company_id)) return;
    const generation = ++detailGeneration.current; setDetailBusy(true); setError(null);
    try { const next = await engine.detail(task.id, task.company_id); if (live() && generation === detailGeneration.current) { setDetail(next.task); setMode('detail'); }
      else if (alive.current && generation === detailGeneration.current) interrupted({ code: 'stale' }, () => void openDetail(task)); }
    catch (failure) { if (alive.current && generation === detailGeneration.current) { if (taskAccessDenied(failure)) denySection(failure); else if (!interrupted(failure, () => void openDetail(task))) setError(failure); } }
    finally { if (alive.current && generation === detailGeneration.current) setDetailBusy(false); }
  };
  useEffect(() => { alive.current = true; return () => { alive.current = false; optionsGeneration.current++; detailGeneration.current++; engine.cancelReads(); }; }, [engine]);
  useEffect(() => { if (!presented) { setOptionsReady(false); engine.cancelReads(); } else void loadOptions(); }, [presented]);
  useEffect(() => { if (!presented || !retryRead.current || (retryRead.current.needsOptions && !ready) || recovered.current) return;
    recovered.current = true; const retry = retryRead.current; retryRead.current = null; retry.run(); }, [presented, ready, resumeTick]);
  const outcome = (result: WorkTaskWriteResult) => {
    if (!alive.current || knownDenied.current || !identity.company_ids.includes(result.task.company_id)) return;
    setDetail(result.task); setMode('detail'); setRefresh(value => value + 1); pendingDirty.current = true; if (active.current) void loadPending();
  };
  const enterCreate = () => {
    if (!live() || !canManage) return;
    const company = companies.length === 1 ? companies[0].id : companies.some(item => item.id === lastCompany) ? lastCompany : readCompany;
    setCreateCompany(company); setMode('create'); setError(null);
  };
  const changedCompany = (id: number) => { if (!live() || !companies.some(company => company.id === id)) return; setCreateCompany(id); setLastCompany(id); };
  const measure = () => { const generation = ++measureGeneration.current; keyboardFrame.current?.measureInWindow((_x, top) => { if (alive.current && generation === measureGeneration.current && Number.isFinite(top)) setKeyboardOffset(Math.max(0, top)); }); };
  return <View style={s.fill} ref={keyboardFrame} collapsable={false} onLayout={measure} testID="tasks-workspace-frame">
    {identity.permissions.task_view && <>
      <View testID="tasks-section-header" style={[s.content, { backgroundColor: colors.white, paddingVertical: 4, gap: 6 }]}>
        <View style={[s.row, taskRow(language), { flexWrap: 'nowrap' }]}>
          {onBack && <IconButton icon="back" label={t('back')} disabled={!presented} onPress={() => { if (live()) onBack(); }} />}
          <Text style={[s.title, direction(language), s.flexible]}>{t(mode === 'create' ? 'newTask' : 'tasks')}</Text>
          {mode === 'list' && canManage && <Button title={t('newTask')} disabled={!presented} onPress={enterCreate} />}
          {mode === 'list' && <IconButton icon="refresh" label={t('refresh')} busy={busy || detailBusy} disabled={!presented} onPress={() => { if (live()) { setRefresh(value => value + 1); void loadOptions(); } }} />}
        </View>
        {!!error && <View accessibilityLiveRegion="polite"><Label language={language}>{t(taskErrorWord(error))}</Label><Button title={t('retry')} quiet disabled={!presented} onPress={() => void loadOptions()} /></View>}
        {!options && busy && <ActivityIndicator color={colors.blue} accessibilityLabel={t('loading')} />}
      </View>
      {options?.can_view && <KeyboardAvoidingView style={s.fill} behavior={Platform.OS === 'ios' ? 'padding' : 'height'} keyboardVerticalOffset={keyboardOffset}>
        {mode === 'create' ? <TaskComposer key={`compose-${createCompany}`} engine={engine} identity={identity} language={language} presented={ready && canManage} companyId={createCompany} companies={companies}
          onCompany={changedCompany} onSaved={outcome} onPending={() => void loadPending()} onBack={() => { if (live()) setMode('list'); }} onDenied={denySection} />
          : mode === 'detail' && detail && companies.some(company => company.id === detail.company_id) ? <TaskDetail key={`detail-${detail.company_id}-${detail.id}`} engine={engine} task={canManage ? detail : { ...detail, allowed_actions: [] }} companyName={name(detail)} language={language} presented={ready}
            onUpdated={outcome} onPending={() => void loadPending()} onBack={() => { if (live()) { detailGeneration.current++; setMode('list'); } }} onRefresh={() => void openDetail(detail)} onDenied={denySection}
            blocked={pending.some(attempt => attempt.kind === 'transition' && attempt.companyId === detail.company_id && attempt.taskId === detail.id)} />
            : <>
              <View style={[s.tabs, taskRow(language)]}>{(['mine', 'created'] as const).map(item => <Pressable key={item} testID={`tasks-view-${item}`} accessibilityRole="tab" accessibilityLabel={t(item)}
                accessibilityState={{ selected: view === item }} disabled={!presented} onPress={() => { if (live()) { setView(item); setError(null); } }} style={[s.tab, view === item && s.selected]}>
                <Text style={[s.strong, direction(language), { color: view === item ? colors.blue : colors.muted }]}>{t(item)}</Text>
              </Pressable>)}</View>
              <View testID="tasks-list-filters" style={[s.content, { paddingVertical: 6, gap: 6 }]}>
                <View style={[s.row, taskRow(language)]}>{(['open', 'done', 'cancelled'] as const).map(item => <Pressable key={item} testID={`tasks-state-${item}`} accessibilityRole="tab" accessibilityLabel={t(item)}
                  accessibilityState={{ selected: state === item }} disabled={!presented} onPress={() => { if (live()) setState(item); }} style={{ minHeight: 44, minWidth: 44, paddingHorizontal: 12, justifyContent: 'center', backgroundColor: state === item ? colors.pale : 'transparent', borderRadius: 10 }}>
                  <Text style={[s.muted, direction(language), { color: state === item ? colors.blue : colors.muted }]}>{t(item)}</Text>
                </Pressable>)}</View>
                {companies.length > 1 && (ready ? <CompanySelector identity={identity} permission="task_view" companyId={readCompany} onSelect={id => { if (live() && (id === 0 || companies.some(company => company.id === id))) { engine.cancelReads(); setFilter(id); } }}
                  language={language} t={translator(language)} companyIds={companies.map(company => company.id)} allowAll /> : <View style={{ minHeight: 48 }} />)}
                {detailBusy && <ActivityIndicator color={colors.blue} accessibilityLabel={t('loading')} />}
              </View>
              <TaskList key={`${view}-${state}-${readCompany}`} engine={engine} language={language} presented={ready} view={view} state={state} companyId={readCompany} companies={companies} refresh={refresh} onOpen={task => void openDetail(task)} onDenied={denySection} />
            </>}
        <PendingPanel engine={engine} pending={pending.filter(attempt => companies.some(company => company.id === attempt.companyId))} language={language} presented={ready} onResult={outcome} onChanged={() => void loadPending()} onDenied={denySection} />
      </KeyboardAvoidingView>}
    </>}
  </View>;
}

function TaskList({ engine, language, presented, view, state, companyId, companies, refresh, onOpen, onDenied }: {
  engine: TasksEngine; language: Language; presented: boolean; view: TasksView; state: TasksStateFilter; companyId: number; companies: TaskSelection[]; refresh: number; onOpen: (task: WorkTask) => void; onDenied: (error: unknown) => void;
}) {
  const t = taskTranslator(language), [tasks, setTasks] = useState<WorkTask[]>([]), [cursor, setCursor] = useState<number | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(null);
  const active = useRef(presented), alive = useRef(true), gate = useRef(false), generation = useRef(0), pendingRead = useRef(false), moreInterrupted = useRef(false), recovered = useRef(false);
  active.current = presented; if (!presented) recovered.current = false;
  const [resume, setResume] = useState(0);
  const load = async (more = false) => {
    if (!alive.current || !active.current || gate.current || (more && (!cursor || tasks.length >= 200))) return;
    gate.current = true; const ticket = ++generation.current; setBusy(true); setError(null);
    try { const page = await engine.list({ view, state, ...(companyId ? { companyId } : {}), ...(more && cursor ? { beforeId: cursor } : {}) });
      if (!alive.current || ticket !== generation.current) return;
      if (!active.current) { pendingRead.current = true; moreInterrupted.current = more; return; }
      setTasks(previous => { const next = more ? [...previous, ...page.tasks] : page.tasks; return next.filter((task, index) => companies.some(company => company.id === task.company_id) && next.findIndex(other => other.id === task.id && other.company_id === task.company_id) === index).slice(0, 200); }); setCursor(page.next_before_id); pendingRead.current = false;
    } catch (failure) { if (alive.current && ticket === generation.current) {
      if (taskAccessDenied(failure)) onDenied(failure);
      else if (failure && typeof failure === 'object' && 'code' in failure && failure.code === 'stale' && (!active.current || !recovered.current)) { pendingRead.current = true; moreInterrupted.current = more; setResume(value => value + 1); }
      else setError(failure);
    } } finally { gate.current = false; if (alive.current && ticket === generation.current) setBusy(false); }
  };
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; generation.current++; }; }, []);
  const previousRefresh = useRef(refresh);
  useEffect(() => { if (refresh !== previousRefresh.current) { previousRefresh.current = refresh; if (presented) void load(); else pendingRead.current = true; } }, [refresh]);
  useEffect(() => { if (!presented || !pendingRead.current || recovered.current) return; recovered.current = true; pendingRead.current = false; void load(moreInterrupted.current); }, [presented, resume]);
  return <FlatList testID="tasks-list" style={s.fill} contentContainerStyle={[s.content, { paddingTop: 2, paddingBottom: 24 }]} keyboardShouldPersistTaps="handled"
    data={tasks.filter(task => companies.some(company => company.id === task.company_id))} keyExtractor={task => `${task.company_id}-${task.id}`} initialNumToRender={12} windowSize={7} maxToRenderPerBatch={12}
    renderItem={({ item }) => <View style={{ marginBottom: 10 }}><TaskCard task={item} language={language} companyName={companies.find(company => company.id === item.company_id)?.name ?? item.company_name} view={view} disabled={!presented}
      onOpen={() => { if (alive.current && active.current) onOpen(item); }} /></View>}
    ListEmptyComponent={!busy && !error ? <View style={{ paddingVertical: 32, gap: 8 }}><Label language={language}>{t('noTasks')}</Label><Label language={language} muted>{t('emptyHelp')}</Label></View> : null}
    ListFooterComponent={<View style={s.stack}>
      {!!error && <><Label language={language}>{t(taskErrorWord(error))}</Label><Button title={t('retry')} quiet disabled={!presented} onPress={() => void load()} /></>}
      {(busy || cursor !== null) && tasks.length < 200 && <Button title={t('loadMore')} quiet busy={busy} disabled={!presented} onPress={() => void load(true)} />}
      {cursor !== null && tasks.length >= 200 && <Label language={language} muted>{t('listLimit')}</Label>}
    </View>} />;
}

function PendingPanel({ engine, pending, language, presented, onResult, onChanged, onDenied }: {
  engine: TasksEngine; pending: PendingTaskAttempt[]; language: Language; presented: boolean; onResult: (result: WorkTaskWriteResult) => void; onChanged: () => void; onDenied: (error: unknown) => void;
}) {
  const t = taskTranslator(language), [busy, setBusy] = useState<string | null>(null), [error, setError] = useState<unknown>(null), gate = useRef(false), active = useRef(presented), alive = useRef(true);
  active.current = presented;
  const latestPending = useRef(pending); latestPending.current = pending;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const retry = async (uuid: string) => {
    if (!alive.current || !active.current || gate.current || !latestPending.current.some(attempt => attempt.uuid === uuid)) return;
    gate.current = true; setBusy(uuid); setError(null);
    try { const result = await engine.retry(uuid); if (alive.current) onResult(result); }
    catch (failure) { if (alive.current) { if (taskAccessDenied(failure)) onDenied(failure); else setError(failure); } }
    finally { gate.current = false; if (alive.current) { setBusy(null); onChanged(); } }
  };
  if (!pending.length) return null;
  return <View style={s.footer} testID="tasks-pending"><Label language={language}>{t('pending')}</Label><Label language={language} muted>{t('unknown')}</Label>
    {pending.map(attempt => <Button key={attempt.uuid} title={`${t('retryAttempt')} · ${String(attempt.taskId ?? attempt.companyId)}`} busy={busy === attempt.uuid} disabled={!presented || busy !== null} onPress={() => void retry(attempt.uuid)} />)}
    {!!error && <Label language={language}>{t(taskErrorWord(error))}</Label>}
  </View>;
}
