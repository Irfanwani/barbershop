module.exports = function (api) {
  api.cache(true);
  return {
    presets: [
      ['babel-preset-expo', { jsxImportSource: 'nativewind' }],
      'nativewind/babel',
    ],
    // Reanimated 4 delegates its worklets runtime to react-native-worklets, and
    // that plugin has to be last in the list or the app fails to build.
    plugins: ['react-native-worklets/plugin'],
  };
};