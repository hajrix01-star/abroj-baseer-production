const { withSettingsGradle } = require('@expo/config-plugins');

// Expo 57's dependency merge retains an existing object for a null platform
// override. Exclude unused SDKs in the native linker command itself so the
// trial cannot silently link upstream telemetry/push or the retired FFmpeg SDK.
const excluded = [
  '@notifee/react-native', 'ffmpeg-kit-react-native',
  '@react-native-firebase/app', '@react-native-firebase/messaging', '@sentry/react-native',
];
module.exports = config => withSettingsGradle(config, current => {
  const original = 'ex.autolinkLibrariesFromCommand(expoAutolinking.rnConfigCommand)';
  const replacement = `ex.autolinkLibrariesFromCommand(expoAutolinking.rnConfigCommand + ${JSON.stringify(['--exclude', ...excluded])}) // bchat-odoo-native-boundary`;
  if (!current.modResults.contents.includes('bchat-odoo-native-boundary')) {
    if (!current.modResults.contents.includes(original)) throw new Error('Odoo trial native linker template changed');
    current.modResults.contents = current.modResults.contents.replace(original, replacement);
  }
  return current;
});
