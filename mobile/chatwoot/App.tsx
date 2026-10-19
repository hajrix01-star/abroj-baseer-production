// Do not import the upstream root: it initializes telemetry and persisted Redux.
const Entry = process.env.EXPO_PUBLIC_BACKEND === 'chatwoot'
  ? require('./ChatwootApp').default
  : require('./src/odoo/OdooTrialApp').default;
export default Entry;
