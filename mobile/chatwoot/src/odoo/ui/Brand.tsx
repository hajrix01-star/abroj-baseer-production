import React from 'react';
import { Image, View } from 'react-native';

/** Owner-approved raster artwork, never mirrored or recolored in RTL. */
const artwork = {
  horizontal: require('../../../assets/bwork/bwork-wordmark-approved-20261019.png'),
  mark: require('../../../assets/bwork/bwork-icon-1024.png'),
};
const sizes = {
  // Keep established header/menu slots; one approved blue b now starts "work".
  header: { width: 128, height: 38.4 },
  login: { width: 224, height: 56 },
  drawer: { width: 140, height: 42 },
  mark: { width: 36, height: 36 },
} as const;

// Frame the approved raster's artwork, not its generous preview-canvas margins.
// This viewport leaves clear space around all glyphs and preserves source bytes.
const wordmark = {
  width: 2169, height: 725,
  viewport: { x: 440, y: 174, width: 1344, height: 372 },
} as const;

export function Brand({ variant = 'header' }: { variant?: keyof typeof sizes }) {
  const size = sizes[variant];
  const scale = Math.min(size.width / wordmark.viewport.width, size.height / wordmark.viewport.height);
  const imageStyle = variant === 'mark' ? { width: '100%' as const, height: '100%' as const } : {
    position: 'absolute' as const,
    width: wordmark.width * scale,
    height: wordmark.height * scale,
    left: (size.width - wordmark.viewport.width * scale) / 2 - wordmark.viewport.x * scale,
    top: (size.height - wordmark.viewport.height * scale) / 2 - wordmark.viewport.y * scale,
  };
  return (
    <View
      testID={`bwork-brand-${variant}`}
      style={{ ...size, maxWidth: '100%', overflow: 'hidden', backgroundColor: '#ffffff', direction: 'ltr' }}>
      <Image
        accessible
        accessibilityLabel="BWork"
        source={variant === 'mark' ? artwork.mark : artwork.horizontal}
        resizeMode="contain"
        style={imageStyle}
      />
    </View>
  );
}
