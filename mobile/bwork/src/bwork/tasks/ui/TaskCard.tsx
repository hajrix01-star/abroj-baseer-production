import React from 'react';
import { Pressable, Text, View } from 'react-native';
import { colors, direction, Icon, Label } from '../../ui/components';
import type { Language } from '../../ui/dictionary';
import { dateTimeLabel } from '../../ui/dateTime';
import type { WorkTask, TasksView } from '../core/types';
import { taskTranslator } from '../dictionary';
import { taskRow, taskStyles as s } from './taskStyles';
export function TaskBadge({ task, language }: { task: WorkTask; language: Language }) {
  const t = taskTranslator(language);
  return <View style={{ alignSelf: language === 'ar' ? 'flex-end' : 'flex-start', backgroundColor: colors.pale, borderRadius: 7, paddingVertical: 2, paddingHorizontal: 8 }}>
    <Text style={[s.muted, direction(language), { color: task.state === 'cancelled' ? colors.danger : colors.blue }]}>{t(task.state)}</Text>
  </View>;
}
export function TaskCard({ task, companyName, language, view, onOpen, disabled }: {
  task: WorkTask; companyName: string; language: Language; view: TasksView; onOpen: () => void; disabled: boolean;
}) {
  const t = taskTranslator(language);
  return <Pressable testID={`task-row-${task.company_id}-${task.id}`} accessibilityRole="button" accessibilityLabel={task.title} disabled={disabled}
    onPress={onOpen} style={({ pressed }) => [s.card, pressed && { opacity: .75 }]}>
    <Text style={[s.strong, direction(language)]}>{task.title}</Text>
    <Label language={language} muted>{companyName}</Label>
    <Label language={language} muted>{view === 'mine' ? t('creator') : t('assignee')}: {view === 'mine' ? task.creator_name : task.assignee_name}</Label>
    <View style={[s.row, taskRow(language), { justifyContent: 'space-between' }]}>
      <TaskBadge task={task} language={language} /><View style={[s.row, taskRow(language), { flexShrink: 1 }]}><Icon icon="clock" size={15} color={colors.muted} />
        <Text style={[s.muted, direction(language)]}>{task.due_at ? dateTimeLabel(task.due_at, language) : t('noDate')}</Text>
      </View>
    </View>
    {task.reminder_due && <Label language={language} muted>{t('reminderDue')}</Label>}
  </Pressable>;
}
