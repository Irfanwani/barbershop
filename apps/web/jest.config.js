/**
 * The site has no build step, and the tests keep that promise.
 *
 * The browser loads these files as native ES modules, so the tests do too:
 * `transform: {}` means Jest hands the source to Node untouched, and
 * `--experimental-vm-modules` lets Jest instantiate ES modules in its sandbox.
 * Nothing here is transpiled, so a file that works in a test works in a browser.
 *
 * @type {import('jest').Config}
 */
export default {
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/tests/setup.js'],
  transform: {},
  collectCoverageFrom: ['lib.js', 'app.js'],
  coverageThreshold: {
    global: { branches: 75, functions: 80, lines: 85, statements: 85 },
  },
};
