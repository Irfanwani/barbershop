/**
 * Jest config.
 *
 * NativeWind is deliberately left out of the test transform. Its Babel plugin
 * injects an interop helper into every module, which collides with Jest's mock
 * hoisting, and in tests the `className` strings are inert anyway — no styles
 * are asserted on.
 *
 * @type {import('jest').Config}
 */
module.exports = {
  preset: 'jest-expo',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  transform: {
    '^.+\\.[jt]sx?$': [
      'babel-jest',
      { presets: [['babel-preset-expo', { jsxImportSource: 'react' }]], babelrc: false, configFile: false },
    ],
  },
  transformIgnorePatterns: [
    'node_modules/(?!((jest-)?react-native|@react-native(-community)?|expo(nent)?|@expo(nent)?/.*|@expo-google-fonts/.*|react-navigation|@react-navigation/.*|@unimodules/.*|unimodules|sentry-expo|react-native-svg|react-native-css-interop))',
  ],
  moduleNameMapper: {
    // Order matters: the assets rule has to win for image paths, which would
    // otherwise be swallowed by the general `@/` rule.
    '^@/assets/(.*)$': '<rootDir>/assets/$1',
    '^@/(.*)$': '<rootDir>/src/$1',
  },
  // Screens are excluded on purpose. They are thin wiring over the logic layer,
  // and asserting on them means asserting on NativeWind class strings and a
  // mocked router. What is worth a coverage number is the layer a bug in
  // cannot be seen on screen: request building, session handling, preferences.
  collectCoverageFrom: [
    'src/api/client.ts',
    'src/api/endpoints.ts',
    'src/lib/cn.ts',
    'src/lib/secure-store.ts',
    'src/store/**/*.ts',
  ],
  coverageThreshold: {
    global: { branches: 70, functions: 70, lines: 80, statements: 80 },
  },
};