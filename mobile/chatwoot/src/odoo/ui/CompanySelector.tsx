import React, { useEffect, useRef, useState } from 'react';
import { AppState, Pressable, Text, View } from 'react-native';
import type { Bootstrap } from '../core/ChatEngine';
import { colors, direction, Field, Icon, Label, Sheet, styles } from './components';
import { authorizedCompanies } from './companyNames';
import type { Language, Translate } from './dictionary';

export function CompanySelector({
  identity,
  companyId,
  onSelect,
  language,
  t,
}: {
  identity: Bootstrap;
  companyId: number;
  onSelect: (id: number) => void;
  language: Language;
  t: Translate;
}) {
  const options = authorizedCompanies(identity, language);
  const context = JSON.stringify([
    identity.database,
    identity.user_id,
    companyId,
    language,
    identity.permissions.revision,
    identity.permissions.chat_view,
    options,
  ]);
  const [opened, setOpened] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const openedRef = useRef<string | null>(null);
  const active = useRef(AppState.currentState === 'active');
  const latest = useRef({
    context,
    options,
    allowed: identity.permissions.chat_view === true,
    onSelect,
  });
  latest.current = { context, options, allowed: identity.permissions.chat_view === true, onSelect };
  const visible = opened === context && active.current && latest.current.allowed;
  const close = () => {
    openedRef.current = null;
    setOpened(null);
    setQuery('');
  };
  useEffect(() => {
    close();
  }, [context]);
  useEffect(() => {
    const subscription = AppState.addEventListener('change', state => {
      active.current = state === 'active';
      if (!active.current) close();
    });
    return () => {
      active.current = false;
      openedRef.current = null;
      subscription.remove();
    };
  }, []);
  const choose = (id: number) => {
    const current = latest.current;
    if (
      opened !== current.context ||
      openedRef.current !== opened ||
      !active.current ||
      !current.allowed ||
      !current.options.some(option => option.id === id)
    )
      return;
    close();
    current.onSelect(id);
  };
  const selected = options.find(option => option.id === companyId);
  const filtered = options.filter(option =>
    option.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
  const title = selected?.name || t(options.length ? 'selectCompany' : 'noCompanies');
  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${t('selectCompany')}: ${title}`}
        accessibilityState={{
          expanded: visible,
          disabled: !options.length || !latest.current.allowed,
        }}
        testID="company-selector"
        disabled={!options.length || !latest.current.allowed}
        onPress={() => {
          if (active.current && latest.current.allowed) {
            setQuery('');
            openedRef.current = latest.current.context;
            setOpened(latest.current.context);
          }
        }}
        style={({ pressed }) => [
          styles.row,
          {
            minHeight: 48,
            flexWrap: 'nowrap',
            borderWidth: 1,
            borderColor: colors.border,
            borderRadius: 12,
            paddingHorizontal: 14,
            backgroundColor: colors.white,
            flexDirection: language === 'ar' ? 'row-reverse' : 'row',
          },
          pressed && { opacity: 0.75 },
        ]}>
        <Text numberOfLines={1} style={[styles.text, direction(language), { flex: 1 }]}>
          {title}
        </Text>
        <Icon icon="chevronDown" size={20} color={colors.muted} />
      </Pressable>
      {visible && (
        <Sheet title={t('selectCompany')} close={close} t={t}>
          <Field
            language={language}
            accessibilityLabel={t('searchCompanies')}
            placeholder={t('searchCompanies')}
            value={query}
            onChangeText={setQuery}
            maxLength={80}
          />
          {filtered.map(option => (
            <Pressable
              key={option.id}
              testID={`company-option-${option.id}`}
              accessibilityRole="button"
              accessibilityState={{ selected: option.id === companyId }}
              accessibilityLabel={option.name}
              onPress={() => choose(option.id)}
              style={({ pressed }) => [
                styles.row,
                {
                  minHeight: 48,
                  padding: 12,
                  flexWrap: 'nowrap',
                  borderRadius: 10,
                  backgroundColor: option.id === companyId ? colors.pale : colors.white,
                  flexDirection: language === 'ar' ? 'row-reverse' : 'row',
                },
                pressed && { opacity: 0.75 },
              ]}>
              <Text numberOfLines={2} style={[styles.text, direction(language), { flex: 1 }]}>
                {option.name}
              </Text>
              {option.id === companyId && <Icon icon="check" size={20} color={colors.blue} />}
            </Pressable>
          ))}
          {!filtered.length && (
            <View style={{ padding: 12 }}>
              <Label language={language} muted>
                {t('noCompanies')}
              </Label>
            </View>
          )}
        </Sheet>
      )}
    </>
  );
}
