import React, { useEffect, useState } from 'react';
import {
  AppState,
  Modal,
  Pressable,
  ScrollView,
  Switch,
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
import { Brand } from './Brand';

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
          minHeight: 48,
          paddingHorizontal: 12,
          paddingVertical: 10,
          flexDirection: language === 'ar' ? 'row-reverse' : 'row',
          alignItems: 'center',
          gap: 12,
          borderRadius: 10,
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
  soundsEnabled = false,
  soundsReady = false,
  onSoundsChange,
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
  soundsEnabled?: boolean;
  soundsReady?: boolean;
  onSoundsChange?: (enabled: boolean) => void;
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
        <View
          style={{
            flex: 1,
            direction: 'ltr',
            flexDirection: language === 'ar' ? 'row-reverse' : 'row',
          }}>
          <View
            accessibilityViewIsModal
            style={{
              width: Math.min(width * 0.65, 304),
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
                minHeight: 44,
                gap: 8,
              }}>
              <IconButton icon="menu" label={t('close')} onPress={close} />
              {page === 'home' ? (
                <View
                  style={{ flex: 1, alignItems: language === 'ar' ? 'flex-end' : 'flex-start' }}>
                  <Brand variant="drawer" />
                </View>
              ) : (
                <Text
                  numberOfLines={1}
                  style={[styles.title, direction(language), { flex: 1, fontSize: 18 }]}>
                  {title}
                </Text>
              )}
              {page !== 'home' && (
                <IconButton
                  icon="back"
                  label={t('back')}
                  onPress={() => setPage('home')}
                  style={language === 'ar' ? { transform: [{ rotate: '180deg' }] } : undefined}
                />
              )}
            </View>
            <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 12, gap: 4 }}>
              <View
                testID="drawer-account"
                style={{
                  paddingHorizontal: 12,
                  paddingVertical: 16,
                  gap: 12,
                  direction: 'ltr',
                  flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                  alignItems: 'center',
                  borderBottomWidth: 1,
                  borderColor: colors.border,
                  marginBottom: 4,
                }}>
                <View
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: 20,
                    backgroundColor: colors.pale,
                    flexShrink: 0,
                    justifyContent: 'center',
                    alignItems: 'center',
                  }}>
                  <Text style={{ color: colors.blue, fontSize: 19, fontWeight: '700' }}>
                    {name.slice(0, 1)}
                  </Text>
                </View>
                <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
                  <Text
                    numberOfLines={2}
                    accessibilityLabel={name}
                    style={[styles.title, direction(language), { fontSize: 16, lineHeight: 22 }]}>
                    {name}
                  </Text>
                  <Text
                    style={[styles.muted, direction(language), { fontSize: 12, lineHeight: 18 }]}>
                    {t(offline ? 'offline' : 'connected')}
                  </Text>
                  {!!pendingCount && (
                    <Text
                      style={[styles.muted, direction(language), { fontSize: 12, lineHeight: 18 }]}>
                      {t('queue')}: {String(pendingCount)}
                    </Text>
                  )}
                </View>
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
                  <View
                    style={{
                      paddingHorizontal: 16,
                      paddingVertical: 8,
                      flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                      alignItems: 'center',
                      gap: 8,
                    }}>
                    <View style={{ flex: 1 }}>
                      <Label language={language}>{t('chatSounds')}</Label>
                      <Label language={language} muted>
                        {t('chatSoundsHint')}
                      </Label>
                    </View>
                    <Switch
                      accessibilityLabel={t('chatSounds')}
                      value={soundsEnabled}
                      disabled={!soundsReady || !onSoundsChange}
                      onValueChange={onSoundsChange}
                      trackColor={{ true: colors.blue }}
                    />
                  </View>
                  <View style={{ padding: 16 }}>
                    <Label language={language} muted>
                      {t('offlineNote')}
                    </Label>
                  </View>
                </>
              )}
              <View
                style={{
                  borderTopWidth: 1,
                  borderColor: colors.border,
                  paddingTop: 6,
                  marginTop: 8,
                }}>
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
            </ScrollView>
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
