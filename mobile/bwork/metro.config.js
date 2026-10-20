const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');
const { getSentryExpoConfig } = require('@sentry/react-native/metro');
const withStorybook = require('@storybook/react-native/metro/withStorybook');

/** @type {import('expo/metro-config').MetroConfig} */
const defaultConfig = getDefaultConfig(__dirname);
if (process.env.EXPO_PUBLIC_BACKEND !== 'chatwoot') {
  module.exports = defaultConfig;
} else {
const sentryConfig = getSentryExpoConfig(__dirname);

// Merge Sentry config with default config
const config = {
  ...defaultConfig,
  ...sentryConfig,
};

module.exports = withStorybook(config, {
  enabled: true,
  configPath: path.resolve(__dirname, './.storybook'),
});
}
