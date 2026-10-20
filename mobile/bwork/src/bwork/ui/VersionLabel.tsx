import React from 'react';
import { Text } from 'react-native';
import * as Application from 'expo-application';
import { direction, styles } from './components';
import { translator, type Language } from './dictionary';

/** The installed binary is the source of truth, including after a future upgrade. */
export function VersionLabel({ language }: { language: Language }) {
  const version = Application.nativeApplicationVersion || '—';
  const build = Application.nativeBuildVersion || '—';
  const t = translator(language);
  const number = (value: string) => (language === 'ar' ? `\u2066${value}\u2069` : value);
  const text = `${t('version')} ${number(version)} · ${t('build')} ${number(build)}`;
  const accessibleText = `${t('version')} ${version} · ${t('build')} ${build}`;
  return (
    <Text
      testID="odoo-app-version"
      accessibilityLabel={accessibleText}
      style={[styles.muted, direction(language)]}>
      {text}
    </Text>
  );
}
