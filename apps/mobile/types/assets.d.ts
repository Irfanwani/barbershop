/**
 * Static asset imports.
 *
 * Metro turns `require('./icon.png')` into a number that `Image` understands.
 * TypeScript has no idea, so every branded image in the app would otherwise be
 * an error.
 */

declare module '*.png' {
  const asset: number;
  export default asset;
}

declare module '*.jpg' {
  const asset: number;
  export default asset;
}

declare module '*.jpeg' {
  const asset: number;
  export default asset;
}
