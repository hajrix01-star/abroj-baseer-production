import React, { useEffect, useState } from 'react';
import { Alert, Pressable, Switch, Text, View } from 'react-native';
import type { ChatEngine, Room } from '../core/ChatEngine';
import { Button, colors, Field, Label, Sheet, styles } from './components';
import { errorWord, type Language, type Translate, type Word } from './dictionary';
import type { ManagementMode } from './RoomsScreen';

type Member = { user_id: number; name: string; is_admin: boolean };
export function ManagementSheet({
  mode,
  companyId,
  room,
  engine,
  close,
  changed,
  language,
  t,
}: {
  mode: ManagementMode;
  companyId: number;
  room: Room | null;
  engine: ChatEngine;
  close: () => void;
  changed: (roomId?: number) => Promise<void>;
  language: Language;
  t: Translate;
}) {
  const [name, setName] = useState(room?.name ?? '');
  const [query, setQuery] = useState('');
  const [users, setUsers] = useState<{ user_id: number; name: string }[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [canManage, setCanManage] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Word | null>(null);
  useEffect(() => {
    let live = true;
    const timer = setTimeout(async () => {
      setBusy(true);
      try {
        if (mode === 'policy') {
          const policy = await engine.policy(companyId);
          if (live) {
            setEnabled(policy.direct_enabled);
            setCanManage(policy.can_manage);
          }
        } else {
          if (mode === 'members' && room) {
            const detail = await engine.groupInfo(room);
            if (live) {
              setMembers(detail.members);
              setCanManage(detail.can_manage);
            }
            if (!detail.can_manage) return;
          }
          const candidates = await engine.candidates(companyId, query);
          if (live) setUsers(candidates.users);
        }
      } catch (e) {
        if (live) setError(errorWord(e));
      } finally {
        if (live) setBusy(false);
      }
    }, 200);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [companyId, engine, mode, query, room]);
  const act = async (operation: () => Promise<unknown>, dismiss = false) => {
    setBusy(true);
    setError(null);
    try {
      const result = (await operation()) as { room_id?: number } | undefined;
      await changed(result?.room_id);
      if (dismiss) close();
      else if (room) {
        const detail = await engine.groupInfo(room);
        setMembers(detail.members);
      }
    } catch (e) {
      setError(errorWord(e));
    } finally {
      setBusy(false);
    }
  };
  const title =
    mode === 'create'
      ? t('group')
      : mode === 'direct'
        ? t('direct')
        : mode === 'policy'
          ? t('policy')
          : t('members');
  return (
    <Sheet title={title} close={close} t={t}>
      {mode === 'policy' ? (
        <>
          <View style={styles.row}>
            <Switch
              value={enabled}
              disabled={!canManage || busy}
              onValueChange={setEnabled}
              accessibilityLabel={t('directEnabled')}
            />
            <View style={styles.fill}>
              <Label language={language}>{t('directEnabled')}</Label>
            </View>
          </View>
          <Label language={language} muted>
            {t('historyKept')}
          </Label>
          <Button
            title={t('save')}
            disabled={!canManage}
            busy={busy}
            onPress={() => {
              void act(() => engine.setPolicy(companyId, enabled), true);
            }}
          />
        </>
      ) : (
        <>
          {mode === 'create' && (
            <Field
              language={language}
              placeholder={t('name')}
              accessibilityLabel={t('name')}
              value={name}
              onChangeText={setName}
              maxLength={100}
            />
          )}
          {mode === 'members' && (
            <>
              {canManage && (
                <View style={{ gap: 8 }}>
                  <Field
                    language={language}
                    accessibilityLabel={t('name')}
                    value={name}
                    onChangeText={setName}
                    maxLength={100}
                  />
                  <Button
                    quiet
                    title={t('rename')}
                    disabled={!name.trim() || busy}
                    onPress={() => {
                      if (room)
                        void act(() => engine.groupChange(room, { action: 'rename', name }));
                    }}
                  />
                </View>
              )}
              {members.map(member => (
                <View
                  key={member.user_id}
                  style={[styles.card, { borderWidth: 1, borderColor: colors.border }]}>
                  <Label language={language}>
                    {member.name}
                    {member.is_admin ? ` · ${t('admin')}` : ''}
                  </Label>
                  {canManage && member.user_id !== engine.identity?.user_id && (
                    <View style={styles.row}>
                      <Button
                        quiet
                        title={t('remove')}
                        disabled={busy}
                        onPress={() => {
                          if (room)
                            void act(() =>
                              engine.groupChange(room, {
                                action: 'remove_member',
                                user_id: member.user_id,
                              }),
                            );
                        }}
                      />
                      <Button
                        quiet
                        title={member.is_admin ? t('demote') : t('makeAdmin')}
                        disabled={busy}
                        onPress={() => {
                          if (room)
                            void act(() =>
                              engine.groupChange(room, {
                                action: member.is_admin ? 'demote_admin' : 'promote_admin',
                                user_id: member.user_id,
                              }),
                            );
                        }}
                      />
                    </View>
                  )}
                </View>
              ))}
              <Button
                quiet
                title={t('leave')}
                disabled={busy}
                onPress={() =>
                  Alert.alert(t('leave'), t('confirmLeave'), [
                    { text: t('cancel'), style: 'cancel' },
                    {
                      text: t('leave'),
                      style: 'destructive',
                      onPress: () => {
                        if (room)
                          void act(() => engine.groupChange(room, { action: 'leave' }), true);
                      },
                    },
                  ])
                }
              />
            </>
          )}
          {(mode !== 'members' || canManage) && (
            <>
              <Field
                language={language}
                value={query}
                onChangeText={setQuery}
                placeholder={t('search')}
                accessibilityLabel={t('search')}
                maxLength={80}
              />
              {mode === 'create' && (
                <Label language={language} muted>
                  {t('selectMembers')} · {String(selected.length)}/49
                </Label>
              )}
              {users
                .filter(user => !members.some(member => member.user_id === user.user_id))
                .map(user => (
                  <Pressable
                    key={user.user_id}
                    accessibilityRole="button"
                    disabled={busy}
                    onPress={() => {
                      if (mode === 'direct') {
                        void act(() => engine.directOpen(companyId, user.user_id), true);
                        return;
                      }
                      if (mode === 'members' && room) {
                        void act(() =>
                          engine.groupChange(room, { action: 'add_member', user_id: user.user_id }),
                        );
                        return;
                      }
                      setSelected(previous =>
                        previous.includes(user.user_id)
                          ? previous.filter(id => id !== user.user_id)
                          : previous.length < 49
                            ? [...previous, user.user_id]
                            : previous,
                      );
                    }}
                    style={[
                      styles.listRow,
                      selected.includes(user.user_id) && { backgroundColor: colors.pale },
                    ]}>
                    <Label language={language}>
                      {selected.includes(user.user_id) ? '✓ ' : ''}
                      {user.name}
                      {mode === 'members' ? ` · ${t('add')}` : ''}
                    </Label>
                  </Pressable>
                ))}
              {!users.length && !busy && (
                <Label language={language} muted>
                  {t('noMembers')}
                </Label>
              )}
            </>
          )}
          {mode === 'create' && (
            <Button
              title={t('create')}
              disabled={!name.trim() || !selected.length}
              busy={busy}
              onPress={() => {
                void act(() => engine.createGroup(companyId, name, selected), true);
              }}
            />
          )}
        </>
      )}
      {error && <Text style={{ color: colors.danger }}>{t(error)}</Text>}
    </Sheet>
  );
}
