/**
 * NativeWind's Metro transformer.
 *
 * Must be `last` — it has to see the JavaScript every other plugin has already
 * rewritten.
 */
const { getDefaultConfig } = require('expo/metro-config');
const { withNativeWind } = require('nativewind/metro');

const config = getDefaultConfig(__dirname);

module.exports = withNativeWind(config, { input: './global.css' });