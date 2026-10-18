import React, { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, Switch, Text, View } from 'react-native';
import type { ChatEngine } from '../core/ChatEngine';
import { loginDiagnostic } from '../core/loginDiagnostics';
import { config } from '../runtime';
import { Button, Field, Label, styles } from './components';
import type { Language, Translate } from './dictionary';
import type { ChatView } from './useChat';

export function LoginScreen({
  engine,
  chat,
  language,
  t,
}: {
  engine: ChatEngine;
  chat: ChatView;
  language: Language;
  t: Translate;
}) {
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(true);
  const [diagnostic, setDiagnostic] = useState<string | null>(null);
  const submit = () => {
    const secret = password;
    setPassword('');
    setDiagnostic(null);
    void chat
      .run(() => engine.login(login.trim(), secret, remember))
      .catch(error => {
        setDiagnostic(loginDiagnostic(error));
      });
  };
  return (
    <KeyboardAvoidingView
      style={styles.fill}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ flexGrow: 1, justifyContent: 'center', padding: 24 }}>
        <View style={[styles.card, { width: '100%', maxWidth: 480, alignSelf: 'center', gap: 18 }]}>
          <Text style={styles.title}>{t('login')}</Text>
          <Label language={language} muted>
            {t('secure')}
          </Label>
          <Text style={[styles.muted, { writingDirection: 'ltr', textAlign: 'left' }]}>
            {config.origin}
            {'\n'}
            {config.database}
          </Text>
          <Label language={language}>{t('user')}</Label>
          <Field
            language={language}
            accessibilityLabel={t('user')}
            value={login}
            onChangeText={setLogin}
            autoCapitalize="none"
            autoCorrect={false}
            textContentType="username"
            autoComplete="username"
          />
          <Label language={language}>{t('password')}</Label>
          <Field
            language={language}
            accessibilityLabel={t('password')}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            autoCapitalize="none"
            autoCorrect={false}
            textContentType="password"
            autoComplete="password"
            onSubmitEditing={submit}
          />
          <View style={styles.row}>
            <Switch
              accessibilityLabel={t('remember')}
              value={remember}
              onValueChange={setRemember}
            />
            <View style={styles.fill}>
              <Label language={language}>{t('remember')}</Label>
            </View>
          </View>
          {chat.error && <Label language={language}>{t(chat.error)}</Label>}
          {chat.error && diagnostic && (
            <View style={{ gap: 4 }}>
              <Label language={language} muted>
                {t('diagnostic')}
              </Label>
              <Text
                selectable
                style={[styles.muted, { writingDirection: 'ltr', textAlign: 'left' }]}>
                {diagnostic}
              </Text>
            </View>
          )}
          <Button
            title={t('login')}
            disabled={!login.trim() || !password}
            busy={chat.busy}
            onPress={submit}
          />
          <Button
            quiet
            title={t('restore')}
            disabled={chat.busy}
            onPress={() => {
              setDiagnostic(null);
              void chat
                .run(async () => {
                  await engine.restoreOffline();
                })
                .catch(() => undefined);
            }}
          />
          <Label language={language} muted>
            {t('offlineNote')}
          </Label>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
