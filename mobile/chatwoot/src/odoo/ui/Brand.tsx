import React from 'react';
import { Image, View } from 'react-native';

/** Owner-approved raster artwork, never mirrored or recolored in RTL. */
const artwork = {
  horizontal: require('../../../assets/bwork/bwork-horizontal-white.png'),
  mark: require('../../../assets/bwork/bwork-icon-1024.png'),
};
const sizes = {
  header: { width: 112, height: 28 },
  login: { width: 224, height: 56 },
  drawer: { width: 136, height: 34 },
  mark: { width: 36, height: 36 },
} as const;

export function Brand({ variant = 'header' }: { variant?: keyof typeof sizes }) {
  return (
    <View
      testID={`bwork-brand-${variant}`}
      style={{ ...sizes[variant], maxWidth: '100%', backgroundColor: '#ffffff', direction: 'ltr' }}>
      <Image
        accessible
        accessibilityLabel="BWork"
        source={variant === 'mark' ? artwork.mark : artwork.horizontal}
        resizeMode="contain"
        style={{ width: '100%', height: '100%' }}
      />
    </View>
  );
}
