# App assets

Launcher icon, adaptive icon and splash screen. All generated from the branding
in the original `servicebarbershop` repository — specifically the Android
launcher and splash drawables under
`android/app/src/main/res/` in that repo's `main` branch.

They were re-rendered rather than copied so the set covers what Expo SDK 54
asks for (`icon.png`, `adaptive-icon-*.png`, `splash.png`, `splash-icon.png`)
and at the densities a modern Android launcher wants, which the originals did
not.

| File                        | Used by                                  |
| --------------------------- | ---------------------------------------- |
| `icon.png`                  | The default Expo icon reference.         |
| `adaptive-icon.png`         | Android launcher, legacy.                |
| `adaptive-icon-foreground.png` | Android launcher, foreground layer.    |
| `adaptive-icon-monochrome.png` | Android themed icons.                 |
| `splash.png`                | The splash screen image.                 |
| `splash-icon.png`           | The splash logo, without the background. |

If the branding changes, change it here and in `app.json`, not in the native
folders — there are none, and `expo prebuild` regenerates them.

The original assets are preserved in the archived `servicebarbershop` repository
if they are ever needed.
