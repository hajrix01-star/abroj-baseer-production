import React, { useEffect, useState } from 'react';
import {
  AppState,
  Modal,
  Pressable,
  ScrollView,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import type { Bootstrap } from '../core/ChatEngine';
import { authorizedCompanies } from './companyNames';
import { colors, direction, Icon, IconButton, Label, styles, type IconName } from './components';
import type { Language, Translate } from './dictionary';
import { VersionLabel } from './VersionLabel';

export type DrawerAction = 'ar' | 'en' | 'refresh' | 'logout' | 'policy';
function MenuRow({
  label,
  icon,
  language,
  onPress,
  disabled,
  selected,
  danger,
}: {
  label: string;
  icon: IconName;
  language: Language;
  onPress: () => void;
  disabled?: boolean;
  selected?: boolean;
  danger?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !!disabled, selected: !!selected }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        {
          minHeight: 52,
          paddingHorizontal: 16,
          paddingVertical: 12,
          flexDirection: language === 'ar' ? 'row-reverse' : 'row',
          alignItems: 'center',
          gap: 14,
          borderRadius: 12,
          backgroundColor: selected ? colors.pale : 'transparent',
        },
        disabled && styles.disabled,
        pressed && { backgroundColor: colors.pale },
      ]}>
      <Icon icon={icon} color={danger ? colors.danger : colors.blue} />
      <Text
        style={[
          styles.text,
          direction(language),
          { flex: 1, color: danger ? colors.danger : colors.ink },
        ]}>
        {label}
      </Text>
      {selected && <Icon icon="check" size={18} color={colors.blue} />}
    </Pressable>
  );
}

export function NavigationDrawer({
  visible,
  identity,
  language,
  t,
  offline,
  pendingCount,
  busy,
  canManage,
  close,
  onAction,
}: {
  visible: boolean;
  identity: Bootstrap | null;
  language: Language;
  t: Translate;
  offline: boolean;
  pendingCount: number;
  busy: boolean;
  canManage: boolean;
  close: () => void;
  onAction: (action: DrawerAction) => void;
}) {
  const [page, setPage] = useState<'home' | 'profile' | 'settings'>('home');
  const { width } = useWindowDimensions();
  useEffect(() => {
    if (!visible) setPage('home');
  }, [visible]);
  useEffect(() => {
    if (!visible) return;
    const listener = AppState.addEventListener('change', state => {
      if (state !== 'active') close();
    });
    return () => listener.remove();
  }, [visible, close]);
  if (!visible || !identity) return null;
  const name = identity.profile?.name || t('user');
  const title = page === 'home' ? t('menu') : t(page);
  const exit = () => {
    if (page === 'home') close();
    else setPage('home');
  };
  return (
    <Modal visible transparent animationType="none" onRequestClose={exit}>
      <SafeAreaView style={{ flex: 1, backgroundColor: '#15233366' }}>
        <View style={{ flex: 1, direction: 'ltr', flexDirection: language === 'ar' ? 'row-reverse' : 'row' }}>
          <View
            accessibilityViewIsModal
            style={{
              width: Math.min(width - 24, 350),
              backgroundColor: colors.white,
              paddingHorizontal: 8,
              paddingTop: 6,
              paddingBottom: 12,
            }}>
            <View
              style={{
                flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                direction: 'ltr',
                alignItems: 'center',
                gap: 8,
              }}>
              <IconButton icon="menu" label={t('close')} onPress={close} />
              <Text style={[styles.title, direction(language), { flex: 1, fontSize: 20 }]}>
                {title}
              </Text>
              {page !== 'home' && (
                <IconButton
                  icon="back"
                  label={t('back')}
                  onPress={() => setPage('home')}
                  style={language === 'ar' ? { transform: [{ rotate: '180deg' }] } : undefined}
                />
              )}
            </View>
            <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 16, gap: 12 }}>
              <View
                style={{ padding: 16, gap: 8, borderBottomWidth: 1, borderColor: colors.border }}>
                <View
                  style={{
                    width: 56,
                    height: 56,
                    borderRadius: 28,
                    backgroundColor: colors.pale,
                    alignSelf: language === 'ar' ? 'flex-end' : 'flex-start',
                    justifyContent: 'center',
                    alignItems: 'center',
                  }}>
                  <Text style={{ color: colors.blue, fontSize: 26, fontWeight: '700' }}>
                    {name.slice(0, 1)}
                  </Text>
                </View>
                <Text style={[styles.title, direction(language), { fontSize: 19 }]}>{name}</Text>
                <Label language={language} muted>
                  {t(offline ? 'offline' : 'connected')}
                </Label>
                {!!pendingCount && (
                  <Label language={language} muted>
                    {t('queue')}: {String(pendingCount)}
                  </Label>
                )}
              </View>
              {page === 'home' && (
                <>
                  <MenuRow
                    icon="user"
                    label={t('profile')}
                    language={language}
                    onPress={() => setPage('profile')}
                  />
                  <MenuRow
                    icon="settings"
                    label={t('settings')}
                    language={language}
                    onPress={() => setPage('settings')}
                  />
                </>
              )}
              {page === 'profile' && (
                <View style={{ padding: 16, gap: 14 }}>
                  <Label language={language} muted>
                    {t('accountDetails')}
                  </Label>
                  <Label language={language}>
                    {t('userId')}: {String(identity.user_id)}
                  </Label>
                  <Label language={language} muted>
                    {t('companies')}
                  </Label>
                  {authorizedCompanies(identity, language).map(company => (
                    <Text key={company.id} style={[styles.text, direction(language)]}>
                      {company.name}
                    </Text>
                  ))}
                </View>
              )}
              {page === 'settings' && (
                <>
                  <View style={{ paddingHorizontal: 16 }}>
                    <Label language={language} muted>
                      {t('language')}
                    </Label>
                  </View>
                  <MenuRow
                    icon="globe"
                    label="العربية"
                    language={language}
                    selected={language === 'ar'}
                    onPress={() => onAction('ar')}
                  />
                  <MenuRow
                    icon="globe"
                    label="English"
                    language={language}
                    selected={language === 'en'}
                    onPress={() => onAction('en')}
                  />
                  {canManage && (
                    <MenuRow
                      icon="settings"
                      label={t('policy')}
                      language={language}
                      disabled={offline || busy}
                      onPress={() => onAction('policy')}
                    />
                  )}
                  <View style={{ padding: 16 }}>
                    <Label language={language} muted>
                      {t('offlineNote')}
                    </Label>
                  </View>
                </>
              )}
            </ScrollView>
            <View style={{ borderTopWidth: 1, borderColor: colors.border, paddingTop: 8 }}>
              <MenuRow
                icon="refresh"
                label={t('refresh')}
                language={language}
                disabled={busy}
                onPress={() => onAction('refresh')}
              />
              <MenuRow
                icon="logout"
                label={t('logout')}
                language={language}
                disabled={busy}
                danger
                onPress={() => onAction('logout')}
              />
              <View style={{ paddingHorizontal: 16, paddingTop: 8 }}>
                <VersionLabel language={language} />
              </View>
            </View>
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t('close')}
            onPress={close}
            style={{ flex: 1 }}
          />
        </View>
      </SafeAreaView>
    </Modal>
  );
}
