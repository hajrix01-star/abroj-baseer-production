import React, { useEffect, useRef, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { Button, direction, Field, Label, Sheet } from '../../ui/components';
import { dateTimeLabel } from '../../ui/dateTime';
import { translator, type Language } from '../../ui/dictionary';
import type { TasksEngine } from '../core/TasksEngine';
import type { TaskAction, TaskSelection, WorkTask, WorkTaskWriteResult } from '../core/types';
import { taskAccessDenied, taskErrorWord, taskTranslator } from '../dictionary';
import { AssigneePicker } from './AssigneePicker';
import { TaskBadge } from './TaskCard';
import { taskStyles as s } from './taskStyles';

export function TaskDetail({ engine, task, companyName, language, presented, blocked, onBack, onUpdated, onPending, onRefresh, onDenied }: {
  engine: TasksEngine; task: WorkTask; companyName: string; language: Language; presented: boolean; blocked: boolean; onBack: () => void;
  onUpdated: (result: WorkTaskWriteResult) => void; onPending: () => void; onRefresh: () => void; onDenied: (error: unknown) => void;
}) {
  const t = taskTranslator(language), [note, setNote] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(null);
  const [cancelOpen, setCancelOpen] = useState(false), [reassignOpen, setReassignOpen] = useState(false), [assignee, setAssignee] = useState<TaskSelection | null>(null);
  const alive = useRef(true), gate = useRef(false), latest = useRef({ presented, task, blocked }); latest.current = { presented, task, blocked };
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { if (!presented) { setCancelOpen(false); setReassignOpen(false); } }, [presented]);
  const allowed = (action: TaskAction) => alive.current && latest.current.presented && !latest.current.blocked && latest.current.task.id === task.id
    && latest.current.task.company_id === task.company_id && latest.current.task.revision === task.revision && latest.current.task.allowed_actions.includes(action);
  const transition = async (action: TaskAction) => {
    if (!allowed(action) || gate.current || (action === 'reassign' && (!assignee || assignee.id === task.assignee_id))) return;
    gate.current = true; setBusy(true); setError(null); setCancelOpen(false);
    try { const result = await engine.transition(task, { action, ...(action === 'reassign' ? { assigneeId: assignee!.id } : {}), ...(note.trim() ? { note: note.trim() } : {}) });
      if (alive.current) { setNote(''); setReassignOpen(false); onUpdated(result); }
    } catch (failure) { if (alive.current) { if (taskAccessDenied(failure)) onDenied(failure); else { setError(failure); onPending(); } } }
    finally { gate.current = false; if (alive.current) setBusy(false); }
  };
  const fact = (label: string, value: string) => <View style={{ gap: 3 }}><Label language={language} muted>{label}</Label><Label language={language}>{value}</Label></View>;
  return <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={[s.content, { paddingBottom: 32 }]} testID="task-detail">
    <Button title={t('back')} quiet onPress={() => { if (alive.current && latest.current.presented && !busy) onBack(); }} disabled={!presented || busy} />
    <TaskBadge task={task} language={language} /><Text style={[s.title, direction(language)]}>{task.title}</Text><Label language={language} muted>{companyName}</Label>
    <Label language={language}>{task.description || t('noDescription')}</Label>
    <View style={s.card}>{fact(t('assignee'), task.assignee_name)}{fact(t('creator'), task.creator_name)}{fact(t('due'), task.due_at ? dateTimeLabel(task.due_at, language) : t('noDate'))}
      {task.reminder_at && fact(t('reminderDate'), dateTimeLabel(task.reminder_at, language))}
      {task.reminder_due && <Label language={language}>{t('reminderDue')}</Label>}
    </View>
    {task.state === 'done' ? <View style={s.card} testID="task-completion-details">
      {!!task.done_at && fact(t('completedAt'), dateTimeLabel(task.done_at, language))}{!!task.done_by_name && fact(t('completedBy'), task.done_by_name)}
      {!!task.completion_note && fact(t('completionNote'), task.completion_note)}{!task.done_at && !task.done_by_name && !task.completion_note && <Label language={language} muted>{t('noCompletionDetails')}</Label>}
    </View> : !!task.last_note && fact(t('lastNote'), task.last_note)}
    {!!task.allowed_actions.length && <><Label language={language}>{t('note')}</Label><Field testID="task-note" language={language} accessibilityLabel={t('note')} value={note} multiline maxLength={512}
      editable={presented && !busy && !blocked} onChangeText={text => { if (alive.current && latest.current.presented && !latest.current.blocked && !gate.current) setNote(text); }} style={{ minHeight: 80, textAlignVertical: 'top' }} /></>}
    {task.allowed_actions.includes('done') && <Button title={t('complete')} busy={busy} disabled={!presented || blocked} onPress={() => void transition('done')} />}
    {task.allowed_actions.includes('start') && <Button title={t('start')} quiet disabled={!presented || busy || blocked} onPress={() => void transition('start')} />}
    {task.allowed_actions.includes('reassign') && <Button title={t('reassign')} quiet disabled={!presented || busy || blocked} onPress={() => { if (allowed('reassign')) { setAssignee(null); setReassignOpen(true); } }} />}
    {task.allowed_actions.includes('cancel') && <Button title={t('cancel')} quiet disabled={!presented || busy || blocked} onPress={() => { if (allowed('cancel')) setCancelOpen(true); }} />}
    {blocked && <Label language={language}>{t('pendingBlock')}</Label>}
    {!!error && <View style={s.stack} accessibilityLiveRegion="polite"><Label language={language}>{t(taskErrorWord(error))}</Label><Button title={t('refresh')} quiet disabled={!presented || busy} onPress={() => { if (latest.current.presented) onRefresh(); }} /></View>}
    {cancelOpen && presented && allowed('cancel') && <Sheet title={t('cancelQuestion')} close={() => setCancelOpen(false)} t={translator(language)} compact language={language}>
      <Label language={language}>{t('cancelHelp')}</Label><Button title={t('confirmCancel')} onPress={() => void transition('cancel')} /><Button title={t('keepTask')} quiet onPress={() => setCancelOpen(false)} />
    </Sheet>}
    {reassignOpen && presented && allowed('reassign') && <Sheet title={t('reassign')} close={() => setReassignOpen(false)} t={translator(language)} compact language={language}>
      <AssigneePicker engine={engine} companyId={task.company_id} language={language} presented={presented} value={assignee} onSelect={setAssignee} excludeId={task.assignee_id} disabled={busy || blocked} onDenied={onDenied} />
      <Button title={t('changeAssignee')} busy={busy} disabled={!assignee || blocked} onPress={() => void transition('reassign')} />
    </Sheet>}
  </ScrollView>;
}
