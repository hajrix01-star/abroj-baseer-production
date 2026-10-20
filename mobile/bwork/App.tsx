// Do not import the upstream root: it initializes telemetry and persisted Redux.
const Entry = process.env.EXPO_PUBLIC_BACKEND === 'chatwoot'
  ? require('./ChatwootApp').default
  : require('./src/bwork/BWorkApp').default;
export default Entry;
