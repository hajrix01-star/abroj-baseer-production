import React from 'react';
import { ScrollView, Text, Pressable, View } from 'react-native';
import { FlashList } from '@shopify/flash-list';
import type { Bootstrap, Room } from '../core/ChatEngine';
import { Button, colors, direction, Label, styles } from './components';
import type { Language, Translate } from './dictionary';
import { companyActions } from './viewModel';

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
  const actions = companyActions(identity, companyId, offline);
  const rows = rooms.filter(room => room.company_id === companyId);
  return (
    <View style={styles.fill}>
      <View style={styles.header}>
        <Label language={language} muted>
          {t('companies')}
        </Label>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{
            gap: 8,
            flexDirection: language === 'ar' ? 'row-reverse' : 'row',
          }}>
          {identity.company_ids.map(id => {
            const company = identity.profile?.companies.find(item => item.id === id);
            const name =
              (language === 'ar' ? company?.name_ar : company?.name_en) ||
              company?.name ||
              String(id);
            return (
              <Button
                key={id}
                quiet={id !== companyId}
                title={name}
                onPress={() => selectCompany(id)}
              />
            );
          })}
        </ScrollView>
        <View style={[styles.row, { flexDirection: language === 'ar' ? 'row-reverse' : 'row' }]}>
          {actions.createGroup && (
            <Button
              title={t('group')}
              disabled={actions.disabled}
              onPress={() => manage('create')}
            />
          )}
          {actions.direct && (
            <Button
              quiet
              title={t('direct')}
              disabled={actions.disabled}
              onPress={() => manage('direct')}
            />
          )}
          {actions.policy && (
            <Button
              quiet
              title={t('policy')}
              disabled={actions.disabled}
              onPress={() => manage('policy')}
            />
          )}
        </View>
      </View>
      <FlashList
        data={rows}
        keyExtractor={room => String(room.id)}
        ListEmptyComponent={
          <View style={{ padding: 24 }}>
            <Label language={language}>{t('noRooms')}</Label>
          </View>
        }
        renderItem={({ item }) => (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={item.name}
            onPress={() => select(item)}
            style={({ pressed }) => [
              styles.listRow,
              { backgroundColor: selected?.id === item.id ? colors.pale : colors.white },
              pressed && { opacity: 0.7 },
            ]}>
            <View
              style={[styles.row, { flexDirection: language === 'ar' ? 'row-reverse' : 'row' }]}>
              <View
                style={{
                  width: 42,
                  height: 42,
                  borderRadius: 14,
                  backgroundColor: colors.pale,
                  justifyContent: 'center',
                  alignItems: 'center',
                }}>
                <Text style={{ color: colors.blue, fontSize: 20, fontWeight: '700' }}>
                  {item.name.slice(0, 1)}
                </Text>
              </View>
              <View style={styles.fill}>
                <Text
                  numberOfLines={1}
                  style={[styles.text, { fontWeight: '600' }, direction(language)]}>
                  {item.name}
                </Text>
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
