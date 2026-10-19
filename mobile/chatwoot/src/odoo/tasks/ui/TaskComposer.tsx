import React, { useRef, useState } from 'react';
import { ScrollView, View } from 'react-native';
import type { Bootstrap } from '../../core/ChatEngine';
import { Button, Field, Label } from '../../ui/components';
import { CompanySelector } from '../../ui/CompanySelector';
import { DateTimeField } from '../../ui/DateTimeField';
import { translator, type Language } from '../../ui/dictionary';
import type { TasksEngine } from '../core/TasksEngine';
import type { TaskSelection, WorkTaskCreateInput, WorkTaskWriteResult } from '../core/types';
import { taskErrorWord, taskTranslator } from '../dictionary';
import { AssigneePicker } from './AssigneePicker';
import { taskStyles as s } from './taskStyles';

export function TaskComposer({ engine, identity, language, presented, companyId, companies, onCompany, onSaved, onPending, onBack }: {
  engine: TasksEngine; identity: Bootstrap; language: Language; presented: boolean; companyId: number; companies: TaskSelection[];
  onCompany: (id: number) => void; onSaved: (result: WorkTaskWriteResult) => void; onPending: () => void; onBack: () => void;
}) {
  const t = taskTranslator(language), [title, setTitle] = useState(''), [description, setDescription] = useState(''), [assignee, setAssignee] = useState<TaskSelection | null>(null);
  const [due, setDue] = useState<string | null>(null), [reminder, setReminder] = useState<string | null>(null), [extra, setExtra] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(null), gate = useRef(false), alive = useRef(true);
  const current = useRef({ presented, companyId }); current.current = { presented, companyId };
  React.useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const allowed = () => alive.current && current.current.presented && current.current.companyId === companyId;
  const submit = async () => {
    if (!allowed() || gate.current || !title.trim() || !assignee || !companies.some(company => company.id === companyId)) return;
    if ((reminder && !due) || (reminder && due && reminder > due)) { setError({ code: 'invalid_payload' }); return; }
    gate.current = true; setBusy(true); setError(null);
    const input: WorkTaskCreateInput = { company_id: companyId, room_id: null, title: title.trim(), description: description.trim(), assignee_id: assignee.id, due_at: due, reminder_at: reminder };
    try { const result = await engine.create(input); if (alive.current && current.current.companyId === companyId) onSaved(result); }
    catch (failure) { if (alive.current) { setError(failure); onPending(); } }
    finally { gate.current = false; if (alive.current) setBusy(false); }
  };
  return <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={[s.content, { paddingBottom: 32 }]} testID="task-composer">
    <Button title={t('back')} quiet onPress={() => { if (allowed() && !busy) onBack(); }} disabled={!presented || busy} />
    {companies.length > 1 && (presented ? <CompanySelector identity={identity} permission="task_view" companyIds={companies.map(company => company.id)} companyId={companyId} language={language} t={translator(language)}
      onSelect={id => { if (allowed() && !busy) onCompany(id); }} /> : <View style={{ minHeight: 48 }} />)}
    <Label language={language}>{t('title')}</Label><Field testID="task-title" accessibilityLabel={t('title')} placeholder={t('titleExample')} language={language} value={title}
      editable={presented && !busy} maxLength={160} onChangeText={text => { if (allowed()) setTitle(text); }} />
    {!companyId && <Label language={language} muted>{t('chooseCompany')}</Label>}
    <AssigneePicker engine={engine} companyId={companyId} language={language} presented={presented} value={assignee} onSelect={person => { if (allowed()) setAssignee(person); }} disabled={busy} />
    <DateTimeField label={t('due')} testID="task-due" language={language} value={due} disabled={!presented || busy} onChange={value => { if (allowed()) { setDue(value); if (!value) setReminder(null); } }} />
    <Button title={t('moreDetails')} quiet onPress={() => { if (allowed()) setExtra(value => !value); }} disabled={!presented || busy} />
    {extra && <View style={s.stack}>
      <Label language={language}>{t('description')}</Label><Field testID="task-description" language={language} accessibilityLabel={t('description')} value={description} multiline maxLength={4096}
        editable={presented && !busy} onChangeText={text => { if (allowed()) setDescription(text); }} style={{ minHeight: 88, textAlignVertical: 'top' }} />
      <DateTimeField label={t('reminder')} testID="task-reminder" help={t('reminderHelp')} language={language} value={reminder} disabled={!presented || busy || !due}
        onChange={value => { if (allowed()) setReminder(value); }} />
    </View>}
    {!!error && <View accessibilityLiveRegion="polite"><Label language={language}>{t(taskErrorWord(error))}</Label></View>}
    <Button title={t('assign')} busy={busy} disabled={!presented || !companyId || !assignee || !title.trim()} onPress={() => void submit()} />
  </ScrollView>;
}
