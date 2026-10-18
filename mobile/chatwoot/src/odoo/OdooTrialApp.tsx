import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, AppState, BackHandler, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import type { ChatEngine, Room } from './core/ChatEngine';
import { getEngine } from './runtime';
import { Button, colors, direction, IconButton, Label, styles } from './ui/components';
import { translator, type Language } from './ui/dictionary';
import { LoginScreen } from './ui/LoginScreen';
import { ManagementSheet } from './ui/ManagementSheet';
import { RoomsScreen, type ManagementMode } from './ui/RoomsScreen';
import { TimelineScreen } from './ui/TimelineScreen';
import { useChat } from './ui/useChat';
import { companyActions, presentationKey } from './ui/viewModel';
import { VersionLabel } from './ui/VersionLabel';
import { NavigationDrawer, type DrawerAction } from './ui/NavigationDrawer';
import { CompanySelector } from './ui/CompanySelector';
import { Brand } from './ui/Brand';

type CompanyMode = Exclude<ManagementMode, 'members'>;
type ManagementTarget = {
  mode: ManagementMode;
  companyId: number;
  room: Room | null;
  scope: string;
};

export function SessionApp({ engine }: { engine: ChatEngine }) {
  const chat = useChat(engine);
  const [language, setLanguage] = useState<Language>('ar');
  const [companyId, setCompanyId] = useState(0);
  const [management, setManagement] = useState<ManagementTarget | null>(null);
  const [companyChoice, setCompanyChoice] = useState<{ mode: CompanyMode; scope: string } | null>(
    null,
  );
  const [menu, setMenu] = useState(false);
  const t = translator(language);
  const { width } = useWindowDimensions();
  const wide = width >= 850;
  const identity = chat.presentationReady ? chat.identity : null;
  const active = useRef(AppState.currentState === 'active');
  const interactionEpoch = useRef(0);
  const eligibleCompanies = (mode: CompanyMode) =>
    !identity || identity.permissions.chat_view !== true
      ? []
      : identity.company_ids.filter(id => {
          if (!Number.isSafeInteger(id) || id <= 0) return false;
          const actions = companyActions(identity, id, chat.offline);
          return mode === 'create'
            ? actions.createGroup
            : mode === 'direct'
              ? actions.direct
              : actions.policy;
        });
  const canManage = eligibleCompanies('policy').length > 0;
  const scopeKey = JSON.stringify([
    identity?.database,
    identity?.user_id,
    identity?.company_ids,
    identity?.permissions,
    identity?.mobile_policy,
    companyId,
    language,
    chat.offline,
    chat.busy,
    chat.selected?.id,
    chat.selected?.company_id,
    chat.selected?.membership_id,
    interactionEpoch.current,
  ]);
  const liveScope = useRef(scopeKey);
  liveScope.current = scopeKey;
  const closeMenu = useCallback(() => setMenu(false), []);
  const openMenu = () => {
    if (identity && active.current && liveScope.current === scopeKey) setMenu(true);
  };
  useEffect(() => {
    setMenu(false);
    setManagement(null);
    setCompanyChoice(null);
  }, [scopeKey]);
  useEffect(() => {
    const listener = AppState.addEventListener('change', state => {
      active.current = state === 'active';
      if (state !== 'active') {
        interactionEpoch.current++;
        liveScope.current = '';
        setMenu(false);
        setManagement(null);
        setCompanyChoice(null);
      }
    });
    return () => listener.remove();
  }, []);
  useEffect(() => {
    if (wide || !chat.selected) return;
    const listener = BackHandler.addEventListener('hardwareBackPress', () => {
      if (menu) setMenu(false);
      else if (companyChoice) setCompanyChoice(null);
      else if (management) setManagement(null);
      else void chat.select(null);
      return true;
    });
    return () => listener.remove();
  }, [wide, chat.selected, chat.select, menu, management, companyChoice]);
  useEffect(() => {
    if (!chat.identity) {
      setCompanyId(0);
      setManagement(null);
      setCompanyChoice(null);
      return;
    }
    if (companyId !== 0 && !chat.identity.company_ids.includes(companyId)) setCompanyId(0);
  }, [
    chat.identity?.database,
    chat.identity?.user_id,
    chat.identity?.company_ids.join(','),
    companyId,
  ]);
  const requestManagement = (mode: ManagementMode) => {
    if (
      !identity ||
      !active.current ||
      liveScope.current !== scopeKey ||
      chat.offline ||
      chat.busy ||
      identity.permissions.chat_view !== true
    )
      return;
    if (mode === 'members') {
      const room = chat.selected;
      if (!room?.is_group || !identity.company_ids.includes(room.company_id)) return;
      setManagement({ mode, companyId: room.company_id, room, scope: scopeKey });
      return;
    }
    const eligible = eligibleCompanies(mode);
    if (!eligible.length) return;
    if (companyId > 0) {
      if (eligible.includes(companyId))
        setManagement({ mode, companyId, room: null, scope: scopeKey });
    } else setCompanyChoice({ mode, scope: scopeKey });
  };
  const logout = () => {
    const perform = () => {
      if (!identity || !active.current || liveScope.current !== scopeKey) return;
      setMenu(false);
      setManagement(null);
      setCompanyChoice(null);
      void chat.logout().catch(() => undefined);
    };
    if (chat.pending.length)
      Alert.alert(t('logout'), t('pendingWarning'), [
        { text: t('cancel'), style: 'cancel' },
        { text: t('logout'), style: 'destructive', onPress: perform },
      ]);
    else perform();
  };
  const menuAction = (action: DrawerAction) => {
    if (!identity || !active.current || liveScope.current !== scopeKey) return;
    if (action === 'ar' || action === 'en') {
      setLanguage(action);
      return;
    }
    setMenu(false);
    if (!identity) return;
    if (action === 'refresh') {
      void chat.sync();
      return;
    }
    if (action === 'logout') {
      logout();
      return;
    }
    if (action === 'policy' && canManage && !chat.offline && !chat.busy) {
      const requested = liveScope.current;
      requestAnimationFrame(() => {
        if (liveScope.current === requested) requestManagement('policy');
      });
    }
  };
  const changed = async (roomId?: number) => {
    await engine.refresh();
    chat.capture();
    if (roomId) {
      const room = engine.rooms().find(item => item.id === roomId);
      if (room) await chat.select(room);
    }
  };
  return (
    <SafeAreaView style={styles.page}>
      {(!identity || wide || !chat.selected) && (
        <View
          style={[
            styles.header,
            styles.row,
            {
              justifyContent: 'space-between',
              paddingHorizontal: 8,
              paddingVertical: 6,
              direction: 'ltr',
              flexWrap: 'nowrap',
              flexDirection: language === 'ar' ? 'row-reverse' : 'row',
            },
          ]}>
          {identity && <IconButton icon="menu" label={t('menu')} onPress={openMenu} />}
          <View style={{ flex: 1, minWidth: 0 }}>
            <View style={{ alignItems: language === 'ar' ? 'flex-end' : 'flex-start' }}>
              <Brand />
            </View>
            {identity ? (
              <Text numberOfLines={1} style={[styles.muted, direction(language), { fontSize: 12, lineHeight: 18 }]}>
                {t(chat.offline ? 'offline' : 'connected')}
              </Text>
            ) : (
              <>
                <Label language={language} muted>
                  {t('trial')}
                </Label>
                <VersionLabel language={language} />
              </>
            )}
          </View>
          <View style={styles.row}>
            {!identity && (
              <Button
                quiet
                title={language === 'ar' ? 'English' : 'العربية'}
                onPress={() => setLanguage(language === 'ar' ? 'en' : 'ar')}
              />
            )}
          </View>
        </View>
      )}
      {!chat.identity ? (
        <LoginScreen engine={engine} chat={chat} language={language} t={t} />
      ) : !chat.presentationReady ? (
        <View style={[styles.fill, { justifyContent: 'center', padding: 24 }]}>
          <Label language={language}>{t('loading')}</Label>
        </View>
      ) : (
        <>
          {(chat.offline || (!chat.selected && chat.pending.length > 0)) && (
            <View
              style={[
                styles.banner,
                { backgroundColor: chat.offline ? colors.warning : colors.pale },
              ]}>
              <Label language={language} muted>
                {t(chat.offline ? 'offline' : 'connected')}
                {chat.pending.length ? ` · ${t('queue')}: ${String(chat.pending.length)}` : ''}
              </Label>
              {chat.offline && (
                <Label language={language} muted>
                  {t('offlineNote')}
                </Label>
              )}
            </View>
          )}
          {chat.error && !chat.selected && (
            <View style={styles.banner}>
              <Label language={language}>{t(chat.error)}</Label>
            </View>
          )}
          <View
            style={[
              styles.fill,
              { flexDirection: wide ? (language === 'ar' ? 'row-reverse' : 'row') : 'column' },
            ]}>
            {(wide || !chat.selected) && (
              <View
                style={[
                  wide
                    ? {
                        width: Math.min(380, width * 0.38),
                        borderEndWidth: 1,
                        borderEndColor: colors.border,
                      }
                    : styles.fill,
                ]}>
                <RoomsScreen
                  identity={chat.identity}
                  rooms={chat.rooms}
                  companyId={companyId}
                  selected={chat.selected}
                  language={language}
                  t={t}
                  offline={chat.offline}
                  selectCompany={id => {
                    if (
                      !identity ||
                      !active.current ||
                      liveScope.current !== scopeKey ||
                      identity.permissions.chat_view !== true ||
                      (id !== 0 && !identity.company_ids.includes(id))
                    )
                      return;
                    setCompanyId(id);
                    setManagement(null);
                    setCompanyChoice(null);
                    void chat.select(null);
                  }}
                  select={room => {
                    if (
                      !identity ||
                      !active.current ||
                      liveScope.current !== scopeKey ||
                      identity.permissions.chat_view !== true ||
                      !identity.company_ids.includes(room.company_id)
                    )
                      return;
                    void chat.select(room);
                  }}
                  manage={requestManagement}
                />
              </View>
            )}
            {chat.selected ? (
              <TimelineScreen
                key={presentationKey(chat.identity, chat.selected)}
                engine={engine}
                chat={chat}
                language={language}
                t={t}
                back={
                  wide
                    ? undefined
                    : () => {
                        void chat.select(null);
                      }
                }
                manage={() => requestManagement('members')}
                onMenu={wide ? undefined : openMenu}
              />
            ) : (
              wide && (
                <View style={[styles.fill, { justifyContent: 'center', padding: 32 }]}>
                  <Label language={language} muted>
                    {t('choose')}
                  </Label>
                </View>
              )
            )}
          </View>
          {companyChoice?.scope === scopeKey && identity?.permissions.chat_view === true && (
            <CompanySelector
              key={`${scopeKey}/${companyChoice.mode}`}
              identity={identity}
              companyId={0}
              companyIds={eligibleCompanies(companyChoice.mode)}
              pickerOnly
              onDismiss={() => setCompanyChoice(null)}
              onSelect={id => {
                if (
                  !active.current ||
                  liveScope.current !== scopeKey ||
                  id <= 0 ||
                  !eligibleCompanies(companyChoice.mode).includes(id) ||
                  chat.offline ||
                  chat.busy
                )
                  return;
                setCompanyChoice(null);
                setManagement({
                  mode: companyChoice.mode,
                  companyId: id,
                  room: null,
                  scope: scopeKey,
                });
              }}
              language={language}
              t={t}
            />
          )}
          {management?.scope === scopeKey && (
            <ManagementSheet
              key={`${chat.identity.user_id}/${management.companyId}/${management.mode}`}
              mode={management.mode}
              companyId={management.companyId}
              room={management.room}
              engine={engine}
              close={() => setManagement(null)}
              changed={changed}
              language={language}
              t={t}
            />
          )}
        </>
      )}
      <NavigationDrawer
        key={scopeKey}
        visible={menu && !!identity}
        identity={identity}
        language={language}
        t={t}
        offline={chat.offline}
        pendingCount={chat.pending.length}
        busy={chat.busy}
        canManage={canManage}
        close={closeMenu}
        onAction={menuAction}
      />
    </SafeAreaView>
  );
}

export default function OdooTrialApp() {
  const [engine] = useState(() => {
    try {
      return getEngine();
    } catch {
      return null;
    }
  });
  return (
    <SafeAreaProvider>
      {engine ? (
        <SessionApp engine={engine} />
      ) : (
        <SafeAreaView style={[styles.page, { justifyContent: 'center', padding: 24 }]}>
          <Text style={styles.title}>{translator('ar')('app')}</Text>
          <VersionLabel language="ar" />
          <Text style={styles.text}>{translator('ar')('config')}</Text>
        </SafeAreaView>
      )}
    </SafeAreaProvider>
  );
}
