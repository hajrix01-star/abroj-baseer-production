import React, { useEffect, useState } from 'react';
import { Alert, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import type { ChatEngine } from './core/ChatEngine';
import { getEngine } from './runtime';
import { Button, colors, direction, Label, styles } from './ui/components';
import { translator, type Language } from './ui/dictionary';
import { LoginScreen } from './ui/LoginScreen';
import { ManagementSheet } from './ui/ManagementSheet';
import { RoomsScreen, type ManagementMode } from './ui/RoomsScreen';
import { TimelineScreen } from './ui/TimelineScreen';
import { useChat } from './ui/useChat';
import { presentationKey } from './ui/viewModel';
import { VersionLabel } from './ui/VersionLabel';

function SessionApp({ engine }: { engine: ChatEngine }) {
  const chat = useChat(engine);
  const [language, setLanguage] = useState<Language>('ar');
  const [companyId, setCompanyId] = useState(0);
  const [management, setManagement] = useState<ManagementMode | null>(null);
  const t = translator(language);
  const { width } = useWindowDimensions();
  const wide = width >= 850;
  useEffect(() => {
    if (!chat.identity) {
      setCompanyId(0);
      setManagement(null);
      return;
    }
    if (!chat.identity.company_ids.includes(companyId))
      setCompanyId(chat.identity.current_company_id || chat.identity.company_ids[0]!);
  }, [chat.identity?.user_id, chat.identity?.company_ids.join(','), companyId]);
  const logout = () => {
    const perform = () => {
      setManagement(null);
      void chat.logout().catch(() => undefined);
    };
    if (chat.pending.length)
      Alert.alert(t('logout'), t('pendingWarning'), [
        { text: t('cancel'), style: 'cancel' },
        { text: t('logout'), style: 'destructive', onPress: perform },
      ]);
    else perform();
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
      <View
        style={[
          styles.header,
          styles.row,
          {
            justifyContent: 'space-between',
            flexDirection: language === 'ar' ? 'row-reverse' : 'row',
          },
        ]}>
        <View style={{ flexShrink: 1 }}>
          <Text style={[styles.title, direction(language)]}>{t('app')}</Text>
          <Label language={language} muted>
            {(chat.presentationReady && chat.identity?.profile?.name) || t('trial')}
          </Label>
          <VersionLabel language={language} />
        </View>
        <View style={styles.row}>
          <Button
            quiet
            title={language === 'ar' ? 'English' : 'العربية'}
            onPress={() => setLanguage(language === 'ar' ? 'en' : 'ar')}
          />
          {chat.identity && (
            <>
              <Button
                quiet
                title={t('refresh')}
                disabled={chat.busy}
                onPress={() => {
                  void chat.sync();
                }}
              />
              <Button quiet title={t('logout')} disabled={chat.busy} onPress={logout} />
            </>
          )}
        </View>
      </View>
      {!chat.identity ? (
        <LoginScreen engine={engine} chat={chat} language={language} t={t} />
      ) : !chat.presentationReady ? (
        <View style={[styles.fill, { justifyContent: 'center', padding: 24 }]}>
          <Label language={language}>{t('loading')}</Label>
        </View>
      ) : (
        <>
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
                    setCompanyId(id);
                    setManagement(null);
                    void chat.select(null);
                  }}
                  select={room => {
                    void chat.select(room);
                  }}
                  manage={setManagement}
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
                manage={() => setManagement('members')}
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
          {management && (
            <ManagementSheet
              key={`${chat.identity.user_id}/${companyId}/${management}`}
              mode={management}
              companyId={companyId}
              room={chat.selected}
              engine={engine}
              close={() => setManagement(null)}
              changed={changed}
              language={language}
              t={t}
            />
          )}
        </>
      )}
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
