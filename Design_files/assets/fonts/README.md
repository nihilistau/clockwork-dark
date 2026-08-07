# Self-hosting the webfonts

The system's four type voices are **confirmed**:

| Role | Family | Weights used |
|------|--------|--------------|
| Narration | **EB Garamond** | 400, 500, 600 + italics |
| UI / chrome | **Source Sans 3** | 400, 500, 600, 700 |
| Stats / dice / clock | **IBM Plex Mono** | 400, 500, 600 |
| Assistant | **Nunito** | 400, 600 + italic |

Right now `tokens/fonts.css` loads these from **Google Fonts** (works online, zero setup). To self-host for production/offline:

1. Download the families (e.g. via [google-webfonts-helper](https://gwfh.mranftl.com/fonts)) as `.woff2` and drop them in this folder, e.g. `EBGaramond-Regular.woff2`, `SourceSans3-SemiBold.woff2`, …
2. In `tokens/fonts.css`, comment out the Google `@import` line and uncomment the `@font-face` block (the family names and `var(--font-*)` stacks already match — nothing else changes).

> Licensing note: all four are open-licensed (OFL / Apache), so you may self-host freely — but Claude can't fetch the binaries for you, so the actual `.woff2` files must be added here by you.
