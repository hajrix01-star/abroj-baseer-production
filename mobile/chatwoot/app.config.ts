import { ConfigContext, ExpoConfig } from 'expo/config';

export default ({ config }: ConfigContext): ExpoConfig => {
  const trial = process.env.EXPO_PUBLIC_BACKEND !== 'chatwoot';
  return {
    name: trial ? 'BChat Trial' : 'Chatwoot',
    slug: process.env.EXPO_PUBLIC_APP_SLUG || (trial ? 'bchat-odoo-trial' : 'chatwoot-mobile'),
    version: trial ? '0.1.4' : '4.9.11',
    orientation: 'portrait',
    icon: './assets/icon.png',
    userInterfaceStyle: 'light',
    scheme: trial ? 'bchat-trial' : 'chatwootapp',
    ios: {
      supportsTablet: true,
      bundleIdentifier: trial ? 'com.baseer.bchat.trial' : 'com.chatwoot.app',
      infoPlist: {
        NSCameraUsageDescription:
          'This app requires access to the camera to upload images and videos.',
        NSPhotoLibraryUsageDescription:
          'This app requires access to the photo library to upload images.',
        NSMicrophoneUsageDescription: 'This app requires access to the microphone to record audio.',
        NSAppleMusicUsageDescription:
          'This app does not use Apple Music, but a system API may require this permission.',
        UIBackgroundModes: trial ? [] : ['fetch', 'remote-notification'],
        ITSAppUsesNonExemptEncryption: false,
      },
      // Please use the relative path to the google-services.json file
      googleServicesFile: process.env.EXPO_PUBLIC_IOS_GOOGLE_SERVICES_FILE,
      entitlements: trial ? {} : { 'aps-environment': 'production' },
      associatedDomains: trial ? [] : ['applinks:app.chatwoot.com'],
    },
    android: {
      ...(trial ? { versionCode: 5 } : {}),
      ...(trial ? { allowBackup: false } : {}),
      adaptiveIcon: { foregroundImage: './assets/adaptive-icon.png', backgroundColor: '#ffffff' },
      package: trial ? 'com.baseer.bchat.trial' : 'com.chatwoot.app',
      permissions: [
        'android.permission.CAMERA',
        'android.permission.RECORD_AUDIO',
        'android.permission.POST_NOTIFICATIONS',
      ],
      // Please use the relative path to the google-services.json file
      googleServicesFile: process.env.EXPO_PUBLIC_ANDROID_GOOGLE_SERVICES_FILE,
      intentFilters: trial ? [] : [
        {
          action: 'VIEW',
          autoVerify: true,
          data: [
            {
              scheme: 'https',
              host: 'app.chatwoot.com',
              pathPrefix: '/app/accounts/',
              pathPattern: '/*/conversations/*',
            },
          ],
          category: ['BROWSABLE', 'DEFAULT'],
        },
        {
          action: 'VIEW',
          data: [
            {
              scheme: 'chatwootapp',
            },
          ],
          category: ['BROWSABLE', 'DEFAULT'],
        },
      ],
    },
    extra: {
      eas: {
        projectId: process.env.EXPO_PUBLIC_PROJECT_ID,
        storybookEnabled: process.env.EXPO_STORYBOOK_ENABLED,
      },
    },
    ...(trial ? {} : { owner: 'chatwoot' }),
    plugins: [
      ...(trial ? ['./with-odoo-trial-native.js'] : []),
      'expo-font',
      'expo-image',
      'expo-status-bar',
      [
        'expo-splash-screen',
        {
          image: './assets/splash.png',
          resizeMode: 'contain',
          backgroundColor: '#ffffff',
          enableFullScreenImage_legacy: true,
        },
      ],
      [
        'react-native-permissions',
        { iosPermissions: trial ? ['Camera', 'PhotoLibrary', 'Microphone'] : ['Camera', 'PhotoLibrary', 'MediaLibrary', 'Notifications'] },
      ],
      ...(!trial ? [[
        '@sentry/react-native',
        {
          url: 'https://sentry.io/',
          project: process.env.EXPO_PUBLIC_SENTRY_PROJECT_NAME,
          organization: process.env.EXPO_PUBLIC_SENTRY_ORG_NAME,
        },
      ] as [string, Record<string, unknown>]] : []),
      'expo-web-browser',
      '@react-native-community/datetimepicker',
      ...(!trial ? ['@react-native-firebase/app', '@react-native-firebase/messaging'] : []),
      [
        'expo-build-properties',
        {
          // compileSdk/targetSdk 36 = Expo SDK 54 / RN 0.81 default (Android 16).
          // notifee (issue #808) needs compileSdk >= 35, satisfied by 36.
          android: {
            ...(trial ? { buildToolsVersion: '36.1.0', usesCleartextTraffic: false } : {}),
            minSdkVersion: 24,
            compileSdkVersion: 36,
            targetSdkVersion: 36,
            enableProguardInReleaseBuilds: true,
          },
        },
      ],
      ...(!trial ? ['./with-ffmpeg-pod.js', './with-android-notification-channel.js', './with-notifee-maven-repo.js', './with-ios-modular-headers.js'] : []),
    ],
  };
};
