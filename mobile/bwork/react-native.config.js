const trial = process.env.EXPO_PUBLIC_BACKEND !== 'chatwoot';
module.exports = {
  dependencies: {
    ...(trial ? Object.fromEntries([
      '@react-native-firebase/app', '@react-native-firebase/messaging', '@sentry/react-native',
    ].map(name => [name, { platforms: { android: null, ios: null } }])) : {}),
    'ffmpeg-kit-react-native': {
      platforms: {
        android: null, // 👈 prevents Android autolinking
      },
    },
    '@notifee/react-native': {
      platforms: {
        android: null, // 👈 prevents Android autolinking
      },
    },
  },
};
