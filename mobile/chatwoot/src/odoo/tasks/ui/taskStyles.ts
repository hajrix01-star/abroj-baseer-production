import { StyleSheet } from 'react-native';
import { colors } from '../../ui/components';
import type { Language } from '../../ui/dictionary';
export const taskStyles = StyleSheet.create({
  fill: { flex: 1, minHeight: 0, backgroundColor: colors.background },
  content: { padding: 14, gap: 12, width: '100%', maxWidth: 900, alignSelf: 'center' },
  card: { padding: 14, gap: 8, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.white },
  stack: { gap: 12 }, row: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  flexible: { flex: 1, minWidth: 0 }, title: { color: colors.ink, fontSize: 22, lineHeight: 32, fontWeight: '700' },
  strong: { color: colors.ink, fontSize: 16, lineHeight: 24, fontWeight: '600' },
  tabs: { flexDirection: 'row', gap: 4, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.white },
  tab: { flex: 1, minWidth: 44, minHeight: 48, padding: 8, alignItems: 'center', justifyContent: 'center', borderBottomWidth: 3, borderBottomColor: 'transparent' },
  selected: { borderBottomColor: colors.blue }, muted: { color: colors.muted, fontSize: 13, lineHeight: 20 },
  footer: { padding: 14, gap: 8, backgroundColor: colors.white, borderTopWidth: 1, borderTopColor: colors.border },
});
export const taskRow = (language: Language) => ({ flexDirection: language === 'ar' ? 'row-reverse' : 'row' }) as const;
