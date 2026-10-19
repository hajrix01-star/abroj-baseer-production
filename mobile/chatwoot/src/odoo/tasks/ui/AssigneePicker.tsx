import React, { useEffect, useRef, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { Button, colors, direction, Field, Icon, Label, Sheet, styles } from '../../ui/components';
import { translator, type Language } from '../../ui/dictionary';
import type { TasksEngine } from '../core/TasksEngine';
import type { TaskSelection } from '../core/types';
import { taskErrorWord, taskTranslator } from '../dictionary';
import { taskRow, taskStyles as s } from './taskStyles';

/** Company-scoped, server-paged assignee search; never a generic user-directory dump. */
export function AssigneePicker({ engine, companyId, language, presented, value, onSelect, excludeId, disabled = false }: {
  engine: TasksEngine; companyId: number; language: Language; presented: boolean; value: TaskSelection | null; onSelect: (person: TaskSelection) => void; excludeId?: number; disabled?: boolean;
}) {
  const t = taskTranslator(language), [open, setOpen] = useState(false), [query, setQuery] = useState('');
  const [people, setPeople] = useState<TaskSelection[]>([]), [cursor, setCursor] = useState<number | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(null);
  const alive = useRef(true), generation = useRef(0), gate = useRef(false), current = useRef({ presented, companyId, disabled, onSelect, excludeId });
  current.current = { presented, companyId, disabled, onSelect, excludeId };
  const selection = useRef({ open, people }); selection.current = { open, people };
  const selectionGeneration = generation.current;
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++; }; }, []);
  useEffect(() => { if (!presented || disabled) { setOpen(false); generation.current++; gate.current = false; setBusy(false); } }, [presented, disabled]);
  const allowed = () => alive.current && current.current.presented && current.current.companyId === companyId && !current.current.disabled && companyId > 0;
  const load = async (more = false) => {
    if (!allowed() || gate.current || (more && (!cursor || people.length >= 200))) return;
    gate.current = true; const ticket = ++generation.current; setBusy(true); setError(null);
    try { const page = await engine.assignees(companyId, { q: query.trim(), ...(more && cursor ? { afterId: cursor } : {}) });
      if (!allowed() || ticket !== generation.current) return;
      setPeople(previous => { const next = more ? [...previous, ...page.assignees] : page.assignees; return next.filter((person, index) => person.id !== excludeId && next.findIndex(other => other.id === person.id) === index).slice(0, 200); });
      setCursor(page.next_after_id);
    } catch (failure) { if (allowed() && ticket === generation.current) setError(failure); }
    finally { if (ticket === generation.current) { gate.current = false; if (alive.current) setBusy(false); } }
  };
  useEffect(() => { generation.current++; gate.current = false; setPeople([]); setCursor(null);
    if (!open || !presented || disabled || !companyId) return;
    const timer = setTimeout(() => void load(), 250); return () => { clearTimeout(timer); generation.current++; gate.current = false; };
  }, [open, query, companyId, presented, disabled]);
  return <View style={{ gap: 5 }}><Label language={language} muted>{t('assignee')}</Label>
    <Pressable testID="task-assignee-picker" accessibilityRole="button" accessibilityLabel={t('chooseAssignee')} accessibilityState={{ disabled: disabled || !companyId, expanded: open }}
      disabled={disabled || !companyId} onPress={() => { if (allowed()) { setQuery(''); setOpen(true); } }}
      style={({ pressed }) => [styles.input, s.row, taskRow(language), pressed && { opacity: .75 }]}>
      <Text style={[styles.text, direction(language), s.flexible]}>{value?.name ?? t('nothingSelected')}</Text><Icon icon="chevronDown" color={colors.muted} size={20} />
    </Pressable>
    {open && presented && !disabled && <Sheet title={t('chooseAssignee')} close={() => setOpen(false)} compact language={language} t={translator(language)}>
      <Field testID="task-assignee-search" language={language} accessibilityLabel={t('searchAssignees')} placeholder={t('searchAssignees')} value={query} onChangeText={setQuery} maxLength={80} />
      {people.map(person => <Pressable key={person.id} testID={`task-assignee-${person.id}`} accessibilityRole="button" accessibilityLabel={person.name} accessibilityState={{ selected: person.id === value?.id }}
        onPress={() => { if (allowed() && selection.current.open && selectionGeneration === generation.current && selection.current.people.some(item => item.id === person.id)) { setOpen(false); current.current.onSelect(person); } }}
        style={({ pressed }) => [s.row, taskRow(language), { minHeight: 48, padding: 10, borderRadius: 9, backgroundColor: person.id === value?.id ? colors.pale : colors.white }, pressed && { opacity: .75 }]}>
        <View style={s.flexible}><Label language={language}>{person.name}</Label></View>{person.id === value?.id && <Icon icon="check" size={18} color={colors.blue} />}
      </Pressable>)}
      {!busy && !error && !people.length && <Label language={language} muted>{t('noAssignees')}</Label>}
      {!!error && <><Label language={language}>{t(taskErrorWord(error))}</Label><Button title={t('retry')} quiet onPress={() => void load()} /></>}
      {(cursor || busy) && people.length < 200 && <Button title={t('loadMore')} quiet busy={busy} onPress={() => void load(true)} />}
      {people.length >= 200 && cursor !== null && <Label language={language} muted>{t('assigneeLimit')}</Label>}
    </Sheet>}
  </View>;
}
