# App assets

The app icon, Android adaptive layers, splash screen and notification icon
follow the same brand as the marketing site in `apps/web`: a cream Fraunces
`B` crossed by tomato barber-pole stripes on an espresso field, with a lime
spark and a gold full stop.

| File                           | Used by                                        |
| ------------------------------ | ---------------------------------------------- |
| `icon.png`                     | The default Expo icon reference.               |
| `adaptive-icon.png`            | Android launcher, legacy.                      |
| `adaptive-icon-foreground.png` | Android launcher, foreground layer.            |
| `adaptive-icon-monochrome.png` | Android themed icons.                          |
| `splash.png`                   | The legacy splash image.                       |
| `splash-icon.png`              | The splash logo, without the background.       |
| `notification-icon.png`        | Android notification icon, white on transparent. |

The matching website assets live in `apps/web/public/assets` (`favicon.png`,
`logo.png`, `logo-512.png` and `og.png`). The shared palette is:

- Espresso `#1B1511`
- Cream `#FFF9EF`
- Tomato `#E34E26`
- Lime `#D8F26B`
- Gold `#F3C75D`

If the branding changes, update these files and the matching colours or image
references in `app.json`. Do not edit native folders — there are none, and
`expo prebuild` regenerates them.

The icon artwork uses Fraunces 800. Keep the `B` clear of the adaptive-icon
safe zone (the foreground is inset to roughly 72% of the canvas).
