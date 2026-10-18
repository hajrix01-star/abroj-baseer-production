import React, { useRef } from 'react';
import { Text, Pressable, View } from 'react-native';
import { FlashList } from '@shopify/flash-list';
import type { Bootstrap, Room } from '../core/ChatEngine';
import { Icon, IconButton, colors, direction, Label, styles } from './components';
import type { Language, Translate } from './dictionary';
import { companyActions } from './viewModel';
import { CompanySelector } from './CompanySelector';
import { authorizedCompanies } from './companyNames';

export type ManagementMode = 'create' | 'direct' | 'policy' | 'members';
export function RoomsScreen({
  identity,
  rooms,
  companyId,
  selectCompany,
  selected,
  select,
  manage,
  language,
  t,
  offline,
}: {
  identity: Bootstrap;
  rooms: Room[];
  companyId: number;
  selectCompany: (id: number) => void;
  selected: Room | null;
  select: (room: Room) => void;
  manage: (mode: ManagementMode) => void;
  language: Language;
  t: Translate;
  offline: boolean;
}) {
  const companies = authorizedCompanies(identity, language);
  const allowedIds = companies.map(company => company.id);
  const allowed = identity.permissions.chat_view === true;
  const rows = allowed
    ? rooms.filter(
        room =>
          allowedIds.includes(room.company_id) &&
          (companyId === 0 || room.company_id === companyId),
      )
    : [];
  const scope = JSON.stringify([
    identity.database,
    identity.user_id,
    identity.permissions,
    identity.company_ids,
    identity.mobile_policy,
    companyId,
    language,
    offline,
  ]);
  const actionScopes = companies
    .filter(company => companyId === 0 || company.id === companyId)
    .map(company => companyActions(identity, company.id, offline));
  const actions = {
    createGroup: allowed && actionScopes.some(action => action.createGroup),
    direct: allowed && actionScopes.some(action => action.direct),
    policy: allowed && actionScopes.some(action => action.policy),
    disabled: offline,
  };
  const latest = useRef({ scope, rows, select, manage, actions });
  latest.current = { scope, rows, select, manage, actions };
  const openRoom = (room: Room) => {
    const current = latest.current;
    const fresh = current.rows.find(
      item =>
        item.id === room.id &&
        item.company_id === room.company_id &&
        item.membership_id === room.membership_id,
    );
    if (current.scope === scope && fresh) current.select(fresh);
  };
  const openManagement = (mode: ManagementMode) => {
    const current = latest.current;
    const permitted =
      mode === 'create'
        ? current.actions.createGroup
        : mode === 'direct'
          ? current.actions.direct
          : mode === 'policy' && current.actions.policy;
    if (current.scope === scope && permitted && !current.actions.disabled) current.manage(mode);
  };
  return (
    <View style={styles.fill}>
      <View style={styles.header}>
        <CompanySelector
          identity={identity}
          companyId={companyId}
          onSelect={selectCompany}
          language={language}
          t={t}
          allowAll
        />
        <View style={[styles.row, { flexDirection: language === 'ar' ? 'row-reverse' : 'row' }]}>
          {actions.createGroup && (
            <IconButton
              icon="members"
              label={t('group')}
              tone="primary"
              disabled={actions.disabled}
              onPress={() => openManagement('create')}
            />
          )}
          {actions.direct && (
            <IconButton
              icon="user"
              label={t('direct')}
              disabled={actions.disabled}
              onPress={() => openManagement('direct')}
            />
          )}
          {actions.policy && (
            <IconButton
              icon="settings"
              label={t('policy')}
              disabled={actions.disabled}
              onPress={() => openManagement('policy')}
            />
          )}
        </View>
      </View>
      <FlashList
        data={rows}
        keyExtractor={room => String(room.id)}
        ListEmptyComponent={
          <View style={{ padding: 24 }}>
            <Label language={language}>{t(companyId === 0 ? 'noRoomsAll' : 'noRooms')}</Label>
          </View>
        }
        renderItem={({ item }) => (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`${item.name} · ${companies.find(company => company.id === item.company_id)?.name ?? String(item.company_id)}`}
            onPress={() => openRoom(item)}
            style={({ pressed }) => [
              styles.listRow,
              { backgroundColor: selected?.id === item.id ? colors.pale : colors.white },
              pressed && { opacity: 0.7 },
            ]}>
            <View
              style={[
                styles.row,
                {
                  flexWrap: 'nowrap',
                  gap: 12,
                  flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                },
              ]}>
              <View
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: 24,
                  backgroundColor: colors.pale,
                  justifyContent: 'center',
                  alignItems: 'center',
                }}>
                <Text style={{ color: colors.blue, fontSize: 20, fontWeight: '700' }}>
                  {item.name.slice(0, 1)}
                </Text>
              </View>
              <View style={[styles.fill, { minWidth: 0, gap: 2 }]}>
                <Text
                  numberOfLines={1}
                  style={[styles.text, { fontWeight: '600' }, direction(language)]}>
                  {item.name}
                </Text>
                <View
                  style={[
                    styles.row,
                    {
                      gap: 4,
                      flexWrap: 'nowrap',
                      alignSelf: language === 'ar' ? 'flex-end' : 'flex-start',
                      flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                      maxWidth: '100%',
                      paddingHorizontal: 7,
                      borderRadius: 6,
                      backgroundColor: colors.pale,
                    },
                  ]}>
                  <Icon icon="building" size={12} color={colors.muted} />
                  <Text
                    numberOfLines={1}
                    style={[
                      styles.muted,
                      direction(language),
                      { fontSize: 11, lineHeight: 19, flexShrink: 1 },
                    ]}>
                    {companies.find(company => company.id === item.company_id)?.name ??
                      String(item.company_id)}
                  </Text>
                </View>
                <Text numberOfLines={1} style={[styles.muted, direction(language)]}>
                  {item.last_message_preview || (item.is_group ? t('members') : t('direct'))}
                </Text>
              </View>
              {!!item.unread_count && (
                <Text
                  style={{
                    backgroundColor: colors.blue,
                    color: colors.white,
                    borderRadius: 12,
                    paddingHorizontal: 8,
                    paddingVertical: 2,
                  }}>
                  {String(item.unread_count)}
                </Text>
              )}
            </View>
          </Pressable>
        )}
      />
    </View>
  );
}
