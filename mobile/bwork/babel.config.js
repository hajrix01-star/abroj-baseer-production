module.exports = function (api) {
  api.cache(true);
  return {
    presets: [
      [
        'babel-preset-expo',
        {
          ...(process.env.EXPO_PUBLIC_BACKEND === 'chatwoot'
            ? { jsxImportSource: '@welldone-software/why-did-you-render' }
            : {}),
        },
      ],
    ],
  };
};
