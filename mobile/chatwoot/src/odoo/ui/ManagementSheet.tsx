import React, { useEffect, useRef, useState } from 'react';
import { Alert, AppState, Pressable, Switch, Text, View } from 'react-native';
import { ChatError, groupDescription, type ChatEngine, type GroupInfo, type Room } from '../core/ChatEngine';
import { launchImageLibrary } from 'react-native-image-picker';
import { GroupAvatar } from './GroupAvatar';
import { chooseGroupPhoto } from './groupPhotoOperation';
import {
  Button,
  colors,
  direction,
  Field,
  Icon,
  IconButton,
  Label,
  Sheet,
  styles,
} from './components';
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
  onPhotoOutcome,
  language,
  t,
}: {
  mode: ManagementMode;
  companyId: number;
  room: Room | null;
  engine: ChatEngine;
  close: () => void;
  changed: (roomId?: number) => Promise<void>;
  onPhotoOutcome?: (outcome: { scope: string; room: Room; status: 'saved' | 'failed'; error?: unknown }) => void;
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
  const [expandedMember, setExpandedMember] = useState<number | null>(null);
  const [description, setDescription] = useState('');
  const [savedDescription, setSavedDescription] = useState('');
  const [avatarVersion, setAvatarVersion] = useState(room?.avatar_version ?? 0);
  const descriptionDirty = useRef(false);
  const descriptionRevision = useRef(0);
  const mutation = useRef(false);
  const alive = useRef(true);
  const readScope = () => `${engine.accountScope}/${engine.identity?.database}/${engine.identity?.user_id}/${room?.company_id}/${room?.id}/${room?.membership_id}`;
  const identityScope = readScope();
  const liveScope = useRef(identityScope); liveScope.current = identityScope;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, [identityScope]);
  const current = (requested: string) => alive.current && liveScope.current === requested && readScope() === requested;
  const applyDetail = (detail: GroupInfo, saved?: { value: string; revision: number }) => {
    setMembers(detail.members); setCanManage(detail.can_manage);
    setAvatarVersion(detail.room.avatar_version); setSavedDescription(detail.room.description);
    if (saved && detail.room.description !== saved.value) throw new ChatError('group_readback_mismatch');
    if (!descriptionDirty.current || !detail.can_manage || saved?.revision === descriptionRevision.current) {
      setDescription(detail.room.description); descriptionDirty.current = false;
    }
  };
  useEffect(() => {
    setExpandedMember(null);
  }, [companyId, room?.id, room?.membership_id, mode, canManage]);
  useEffect(() => {
    let live = true;
    const requested = identityScope;
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
            if (live && current(requested)) applyDetail(detail);
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
  const act = async (operation: () => Promise<unknown>, dismiss = false, saved?: { value: string; revision: number }) => {
    if (mutation.current) return;
    mutation.current = true;
    const requested = identityScope;
    setBusy(true);
    setError(null);
    try {
      const result = (await operation()) as { room_id?: number } | undefined;
      if (!current(requested)) return;
      await changed(result?.room_id);
      if (dismiss) close();
      else if (room) {
        const detail = await engine.groupInfo(room);
        if (current(requested)) applyDetail(detail, saved);
      }
    } catch (e) {
      if (current(requested)) setError(errorWord(e));
    } finally {
      mutation.current = false;
      if (current(requested)) setBusy(false);
    }
  };
  const changePhoto = async () => {
    if (!room || !canManage || busy || mutation.current || engine.offline) return;
    const requested = identityScope;
    const photoScope = engine.accountScope, photoRoom = { ...room };
    const report = (status: 'saved' | 'failed', error?: unknown) => {
      if (photoScope && engine.accountScope === photoScope) {
        try { onPhotoOutcome?.({ scope: photoScope, room: photoRoom, status, ...(status === 'failed' ? { error } : {}) }); } catch { /* Presentation cannot change an upload outcome. */ }
      }
    };
    let saved = false;
    mutation.current = true; setBusy(true); setError(null);
    try {
      const result = await chooseGroupPhoto(engine, photoRoom, () => launchImageLibrary({ mediaType: 'photo', selectionLimit: 1, maxWidth: 1600, maxHeight: 1600, quality: 0.9 }));
      if (result.status === 'cancelled') return;
      saved = true; report('saved');
      if (!current(requested)) return;
      applyDetail(result.detail); await changed();
    } catch (e) {
      if (!saved) report('failed', e);
      if (!current(requested)) return;
      // Refresh display after an uncertain upload, but never convert that outcome into success.
      try { if (AppState.currentState === 'active') { const detail = await engine.groupInfo(room); if (current(requested)) applyDetail(detail); } } catch { /* Keep the last permitted presentation. */ }
      if (current(requested)) setError(errorWord(e));
    } finally { mutation.current = false; if (current(requested)) setBusy(false); }
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
    <Sheet title={title} close={close} t={t} compact={mode === 'members'} language={language}>
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
              {room && <View style={{ alignItems: 'center', gap: 6, paddingVertical: 4 }}>
                <GroupAvatar engine={engine} room={{ ...room, avatar_version: avatarVersion }} enabled={!engine.offline} size={64} label={t('groupPhoto')} />
                {canManage && <Button quiet title={t('changeGroupPhoto')} disabled={busy || engine.offline} onPress={() => { void changePhoto(); }} />}
              </View>}
              {canManage && (
                <View
                  style={{
                    flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                    direction: 'ltr',
                    alignItems: 'center',
                    gap: 8,
                  }}>
                  <Field
                    language={language}
                    accessibilityLabel={t('name')}
                    value={name}
                    onChangeText={setName}
                    maxLength={100}
                    style={{ flex: 1, minWidth: 0, minHeight: 44 }}
                  />
                  <IconButton
                    icon="check"
                    label={t('rename')}
                    tone="primary"
                    disabled={!name.trim() || busy}
                    onPress={() => {
                      if (room)
                        void act(() => engine.groupChange(room, { action: 'rename', name }));
                    }}
                  />
                </View>
              )}
              {!canManage && room && <Label language={language}>{room.name}</Label>}
              <View style={{ gap: 6 }}>
                <Label language={language} muted>{t('groupDescription')}</Label>
                {canManage ? <>
                  <Field language={language} multiline value={description} maxLength={1024} editable={!busy}
                    placeholder={t('descriptionPlaceholder')} accessibilityLabel={t('groupDescription')}
                    onChangeText={value => { descriptionRevision.current++; descriptionDirty.current = true; setDescription(value); }}
                    style={{ minHeight: 68, maxHeight: 120, textAlignVertical: 'top' }} />
                  <View style={[styles.row, { justifyContent: 'space-between', flexDirection: language === 'ar' ? 'row-reverse' : 'row', direction: 'ltr' }]}>
                    <Text style={styles.muted}>{String(new TextEncoder().encode(description).length)}/1024</Text>
                    <Button quiet title={t('saveDescription')} disabled={busy || engine.offline || !descriptionDirty.current}
                      onPress={() => {
                        try {
                          const value = groupDescription(description); const revision = descriptionRevision.current;
                          if (room) void act(() => engine.groupChange(room, { action: 'set_description', description: value }), false, { value, revision });
                        } catch (e) { setError(errorWord(e)); }
                      }} />
                  </View>
                </> : <Label language={language}>{savedDescription || t('noDescription')}</Label>}
              </View>
              {members.map(member => (
                <View
                  key={member.user_id}
                  testID={`group-member-${member.user_id}`}
                  style={{
                    borderBottomWidth: 1,
                    borderBottomColor: colors.border,
                    paddingVertical: 4,
                  }}>
                  <View
                    style={{
                      minHeight: 48,
                      flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                      direction: 'ltr',
                      alignItems: 'center',
                      gap: 10,
                    }}>
                    <View
                      style={{
                        width: 36,
                        height: 36,
                        borderRadius: 18,
                        flexShrink: 0,
                        backgroundColor: colors.pale,
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}>
                      <Text
                        accessible={false}
                        style={{ color: colors.blue, fontSize: 16, fontWeight: '600' }}>
                        {Array.from(member.name.trim())[0] ?? ''}
                      </Text>
                    </View>
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <Text
                        numberOfLines={2}
                        accessibilityLabel={member.name}
                        style={[
                          styles.text,
                          direction(language),
                          { fontSize: 15, lineHeight: 21 },
                        ]}>
                        {member.name}
                      </Text>
                      {member.is_admin && (
                        <Text
                          style={[
                            styles.muted,
                            direction(language),
                            { fontSize: 12, lineHeight: 16 },
                          ]}>
                          {t('admin')}
                        </Text>
                      )}
                    </View>
                    {canManage && member.user_id !== engine.identity?.user_id && (
                      <IconButton
                        icon="more"
                        label={`${t(expandedMember === member.user_id ? 'close' : 'settings')}: ${member.name}`}
                        disabled={busy}
                        onPress={() =>
                          setExpandedMember(
                            expandedMember === member.user_id ? null : member.user_id,
                          )
                        }
                      />
                    )}
                  </View>
                  {canManage &&
                    member.user_id !== engine.identity?.user_id &&
                    expandedMember === member.user_id && (
                      <View
                        style={[
                          styles.row,
                          {
                            flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                            direction: 'ltr',
                            paddingStart: 46,
                            paddingBottom: 4,
                          },
                        ]}>
                        <Button
                          quiet
                          title={t('remove')}
                          accessibilityLabel={`${t('remove')}: ${member.name}`}
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
                          accessibilityLabel={`${member.is_admin ? t('demote') : t('makeAdmin')}: ${member.name}`}
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
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={t('leave')}
                accessibilityState={{ disabled: busy }}
                disabled={busy}
                style={{
                  minHeight: 48,
                  paddingHorizontal: 2,
                  flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                  direction: 'ltr',
                  alignItems: 'center',
                  gap: 8,
                }}
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
                }>
                <Icon icon="logout" color={colors.danger} size={18} />
                <Text
                  style={[
                    styles.text,
                    direction(language),
                    { color: colors.danger, fontSize: 14 },
                  ]}>
                  {t('leave')}
                </Text>
              </Pressable>
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
                    accessibilityLabel={
                      mode === 'members' ? `${t('add')}: ${user.name}` : undefined
                    }
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
                      mode === 'members'
                        ? {
                            minHeight: 48,
                            paddingVertical: 6,
                            paddingHorizontal: 2,
                            flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                            direction: 'ltr',
                            alignItems: 'center',
                            gap: 10,
                            borderBottomWidth: 1,
                            borderBottomColor: colors.border,
                          }
                        : styles.listRow,
                      selected.includes(user.user_id) && { backgroundColor: colors.pale },
                    ]}>
                    {mode === 'members' ? (
                      <>
                        <Text
                          numberOfLines={2}
                          accessibilityLabel={user.name}
                          style={[
                            styles.text,
                            direction(language),
                            { flex: 1, minWidth: 0, fontSize: 15, lineHeight: 21 },
                          ]}>
                          {user.name}
                        </Text>
                        <View
                          style={{
                            flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                            direction: 'ltr',
                            alignItems: 'center',
                            gap: 4,
                          }}>
                          <Icon icon="plus" size={18} color={colors.blue} />
                          <Text style={[styles.muted, direction(language), { color: colors.blue }]}>
                            {t('add')}
                          </Text>
                        </View>
                      </>
                    ) : (
                      <Label language={language}>
                        {selected.includes(user.user_id) ? '✓ ' : ''}
                        {user.name}
                      </Label>
                    )}
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
