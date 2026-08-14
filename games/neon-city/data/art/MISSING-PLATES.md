# Missing plates — NEON CITY: THE CROSSING

75 subject(s) are authored in `subjects.yaml` and have no image in
`plates/`, so each falls through the resolution chain to the procedural
silhouette.
One of them is `the_grid`, the entry location, which is why a new run
opens on a placeholder.

**Generated, not written.** Every prompt below is the output of
`engine.media.art.render_prose` / `render_tags` against the shipped
`subjects.yaml`, so it is exactly what the live pipeline would send — not a
fourth copy of the art voice free to drift from the three that ship. After
editing a subject, re-run the generator rather than editing the prompts here:

```powershell
.\.venv\Scripts\python.exe scripts\art_missing.py --game neon-city
```

## Order to work in

1. **`the_grid`** — the entry location, so this is the first screen of
   every new run.
2. The rest, in any order. Each one only shows up if the player goes there.

## Sizes

| Kind | Size | Directory |
| --- | --- | --- |
| location | 1280x720 | `plates/scenes/` |
| portrait | 768x1024 | `plates/portraits/` |
| item | 768x1024 | `plates/items/` |

Read from `subjects.yaml`'s `formats:` block, which is also what the live Grok
and ComfyUI providers size their requests from — so generating by hand and
generating through the pipeline land the same shape. `tests/test_story_art.py`
holds that block to the plates actually on disk. JPEG, same as the rest.

## After the files land

Add each to `manifest.yaml` under its kind. Locations take
`{base: ..., alts: [...]}`; portraits and items take a bare path. Paths are
relative to `paths.art_root`. The ready-to-paste block is at the bottom.

---

## Locations (14)

### `the_grid`

- **File:** `scenes/the-grid.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
An underground night market in a converted service vault. Visible detail: counter rows under strung cabling, green neon accents, ticker screens scrolling prices, crowd of traders, condensation on concrete. Half the counters shuttered, one figure restocking from unmarked crates, green neon and one work lamp, everything else in vault-dark. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An underground night market in a converted service vault, counter rows under strung cabling, green neon accents, ticker screens scrolling prices, crowd of traders, condensation on concrete, half the counters shuttered, one figure restocking from unmarked crates, green neon and one work lamp, everything else in vault-dark, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/the-grid-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
An underground night market in a converted service vault. Visible detail: counter rows under strung cabling, green neon accents, ticker screens scrolling prices, crowd of traders, condensation on concrete. Full trade, three conversations deep at every counter, dense green-white neon, no daylight ever reaches here. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An underground night market in a converted service vault, counter rows under strung cabling, green neon accents, ticker screens scrolling prices, crowd of traders, condensation on concrete, full trade, three conversations deep at every counter, dense green-white neon, no daylight ever reaches here, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/the-grid-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
An underground night market in a converted service vault. Visible detail: counter rows under strung cabling, green neon accents, ticker screens scrolling prices, crowd of traders, condensation on concrete. The evening surge, couriers threading the crowd, tickers casting scrolling light across faces. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An underground night market in a converted service vault, counter rows under strung cabling, green neon accents, ticker screens scrolling prices, crowd of traders, condensation on concrete, the evening surge, couriers threading the crowd, tickers casting scrolling light across faces, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/the-grid-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
An underground night market in a converted service vault. Visible detail: counter rows under strung cabling, green neon accents, ticker screens scrolling prices, crowd of traders, condensation on concrete. Thinner crowd, serious buyers, shutters half down, pools of green neon with long dark gaps between them. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An underground night market in a converted service vault, counter rows under strung cabling, green neon accents, ticker screens scrolling prices, crowd of traders, condensation on concrete, thinner crowd, serious buyers, shutters half down, pools of green neon with long dark gaps between them, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

### `neon_strip`

- **File:** `scenes/neon-strip.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
A canyon of light and appetite through Midtown at street level. Visible detail: stacked signage, magenta neon, crowds under umbrellas, camera masts at intervals, steam from food stalls. The morning after: cleaners, litter, signage still burning, grey wet first light losing to magenta neon. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A canyon of light and appetite through Midtown at street level, stacked signage, magenta neon, crowds under umbrellas, camera masts at intervals, steam from food stalls, the morning after: cleaners, litter, signage still burning, grey wet first light losing to magenta neon, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/neon-strip-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
A canyon of light and appetite through Midtown at street level. Visible detail: stacked signage, magenta neon, crowds under umbrellas, camera masts at intervals, steam from food stalls. Thin daytime crowd under dead signage, flat overcast day, the neon waiting. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A canyon of light and appetite through Midtown at street level, stacked signage, magenta neon, crowds under umbrellas, camera masts at intervals, steam from food stalls, thin daytime crowd under dead signage, flat overcast day, the neon waiting, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/neon-strip-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
A canyon of light and appetite through Midtown at street level. Visible detail: stacked signage, magenta neon, crowds under umbrellas, camera masts at intervals, steam from food stalls. The evening flood beginning, every sign waking, magenta and cyan neon doubling in the wet street. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A canyon of light and appetite through Midtown at street level, stacked signage, magenta neon, crowds under umbrellas, camera masts at intervals, steam from food stalls, the evening flood beginning, every sign waking, magenta and cyan neon doubling in the wet street, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/neon-strip-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
A canyon of light and appetite through Midtown at street level. Visible detail: stacked signage, magenta neon, crowds under umbrellas, camera masts at intervals, steam from food stalls. Full flood, a river crossing made of people, total neon saturation, rain as falling light. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A canyon of light and appetite through Midtown at street level, stacked signage, magenta neon, crowds under umbrellas, camera masts at intervals, steam from food stalls, full flood, a river crossing made of people, total neon saturation, rain as falling light, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

### `club_noir`

- **File:** `scenes/club-noir.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
A casino interior dressed as a cathedral nave. Visible detail: black marble, gold table lamps, card tables in pools of light, a vaulted dark ceiling, dealers in black. The last table still playing, chips being counted, one table lamp, the nave in darkness. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A casino interior dressed as a cathedral nave, black marble, gold table lamps, card tables in pools of light, a vaulted dark ceiling, dealers in black, the last table still playing, chips being counted, one table lamp, the nave in darkness, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/club-noir-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
A casino interior dressed as a cathedral nave. Visible detail: black marble, gold table lamps, card tables in pools of light, a vaulted dark ceiling, dealers in black. Empty tables under cloths, a cleaner moving slowly, work lights, the gold dimmed. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A casino interior dressed as a cathedral nave, black marble, gold table lamps, card tables in pools of light, a vaulted dark ceiling, dealers in black, empty tables under cloths, a cleaner moving slowly, work lights, the gold dimmed, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/club-noir-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
A casino interior dressed as a cathedral nave. Visible detail: black marble, gold table lamps, card tables in pools of light, a vaulted dark ceiling, dealers in black. Tables uncovering, the first serious money arriving, table lamps lighting one by one down the nave. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A casino interior dressed as a cathedral nave, black marble, gold table lamps, card tables in pools of light, a vaulted dark ceiling, dealers in black, tables uncovering, the first serious money arriving, table lamps lighting one by one down the nave, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/club-noir-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
A casino interior dressed as a cathedral nave. Visible detail: black marble, gold table lamps, card tables in pools of light, a vaulted dark ceiling, dealers in black. Full play, secrets moving with the cards, gold pools on green baize, black between the tables. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A casino interior dressed as a cathedral nave, black marble, gold table lamps, card tables in pools of light, a vaulted dark ceiling, dealers in black, full play, secrets moving with the cards, gold pools on green baize, black between the tables, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

### `velvet_pit`

- **File:** `scenes/velvet-pit.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
A low-ceilinged speakeasy below street level. Visible detail: a long zinc bar, booth shadows, a fence's cloth spread on a back table, bottles lit from behind. Chairs on tables, one booth still occupied, back-bar glow only. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A low-ceilinged speakeasy below street level, a long zinc bar, booth shadows, a fence's cloth spread on a back table, bottles lit from behind, chairs on tables, one booth still occupied, back-bar glow only, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/velvet-pit-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
A low-ceilinged speakeasy below street level. Visible detail: a long zinc bar, booth shadows, a fence's cloth spread on a back table, bottles lit from behind. Quiet trade, deals in the booths, dim amber, no windows. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A low-ceilinged speakeasy below street level, a long zinc bar, booth shadows, a fence's cloth spread on a back table, bottles lit from behind, quiet trade, deals in the booths, dim amber, no windows, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/velvet-pit-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
A low-ceilinged speakeasy below street level. Visible detail: a long zinc bar, booth shadows, a fence's cloth spread on a back table, bottles lit from behind. Filling up, the hiring hall coming to order, amber bar light, faces in half shadow. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A low-ceilinged speakeasy below street level, a long zinc bar, booth shadows, a fence's cloth spread on a back table, bottles lit from behind, filling up, the hiring hall coming to order, amber bar light, faces in half shadow, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/velvet-pit-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
A low-ceilinged speakeasy below street level. Visible detail: a long zinc bar, booth shadows, a fence's cloth spread on a back table, bottles lit from behind. Full, loud, every table a negotiation, warm dark, the cloth's corner lit by one lamp. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A low-ceilinged speakeasy below street level, a long zinc bar, booth shadows, a fence's cloth spread on a back table, bottles lit from behind, full, loud, every table a negotiation, warm dark, the cloth's corner lit by one lamp, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

### `junkyard_sprawl`

- **File:** `scenes/junkyard-sprawl.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
Mountains of dead technology under a crane line. Visible detail: stacked drone hulls and server racks, amber work lights, a crane cab lit high up, oily puddles. Mist between the stacks, the crane starting up, amber floods and grey first light. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
Mountains of dead technology under a crane line, stacked drone hulls and server racks, amber work lights, a crane cab lit high up, oily puddles, mist between the stacks, the crane starting up, amber floods and grey first light, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/junkyard-sprawl-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
Mountains of dead technology under a crane line. Visible detail: stacked drone hulls and server racks, amber work lights, a crane cab lit high up, oily puddles. Crews working the faces, sparks off a cutting torch, flat industrial daylight, amber accents. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
Mountains of dead technology under a crane line, stacked drone hulls and server racks, amber work lights, a crane cab lit high up, oily puddles, crews working the faces, sparks off a cutting torch, flat industrial daylight, amber accents, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/junkyard-sprawl-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
Mountains of dead technology under a crane line. Visible detail: stacked drone hulls and server racks, amber work lights, a crane cab lit high up, oily puddles. Shift change, tallies being argued, the yard lights waking, stack shadows going long. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
Mountains of dead technology under a crane line, stacked drone hulls and server racks, amber work lights, a crane cab lit high up, oily puddles, shift change, tallies being argued, the yard lights waking, stack shadows going long, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/junkyard-sprawl-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
Mountains of dead technology under a crane line. Visible detail: stacked drone hulls and server racks, amber work lights, a crane cab lit high up, oily puddles. Empty faces, the north face very dark, isolated amber pools, the crane cab lit alone. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
Mountains of dead technology under a crane line, stacked drone hulls and server racks, amber work lights, a crane cab lit high up, oily puddles, empty faces, the north face very dark, isolated amber pools, the crane cab lit alone, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

### `ripper_street`

- **File:** `scenes/ripper-street.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
A street of chop shops and back-room clinics. Visible detail: shopfronts of chrome limbs and parts bins, a red cross in dead neon, awnings dripping, a recovery chair visible through glass. The night's work sleeping it off, shutters half up, pale wet light, one clinic sign burning. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A street of chop shops and back-room clinics, shopfronts of chrome limbs and parts bins, a red cross in dead neon, awnings dripping, a recovery chair visible through glass, the night's work sleeping it off, shutters half up, pale wet light, one clinic sign burning, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/ripper-street-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
A street of chop shops and back-room clinics. Visible detail: shopfronts of chrome limbs and parts bins, a red cross in dead neon, awnings dripping, a recovery chair visible through glass. Open trade, parts changing hands off folding tables, overcast day, neon crosses buzzing. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A street of chop shops and back-room clinics, shopfronts of chrome limbs and parts bins, a red cross in dead neon, awnings dripping, a recovery chair visible through glass, open trade, parts changing hands off folding tables, overcast day, neon crosses buzzing, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/ripper-street-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
A street of chop shops and back-room clinics. Visible detail: shopfronts of chrome limbs and parts bins, a red cross in dead neon, awnings dripping, a recovery chair visible through glass. The queue forming at sable's door, red and white clinic neon in the wet. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A street of chop shops and back-room clinics, shopfronts of chrome limbs and parts bins, a red cross in dead neon, awnings dripping, a recovery chair visible through glass, the queue forming at Sable's door, red and white clinic neon in the wet, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/ripper-street-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
A street of chop shops and back-room clinics. Visible detail: shopfronts of chrome limbs and parts bins, a red cross in dead neon, awnings dripping, a recovery chair visible through glass. The late shift: stretchers, cash, no questions, clinic light spilling across dark pavement. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A street of chop shops and back-room clinics, shopfronts of chrome limbs and parts bins, a red cross in dead neon, awnings dripping, a recovery chair visible through glass, the late shift: stretchers, cash, no questions, clinic light spilling across dark pavement, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

### `ghost_alley`

- **File:** `scenes/ghost-alley.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
A dead-end lane where netrunners meet in the flesh. Visible detail: taped junction boxes, a noodle stall's steam, dead screens that sometimes wake, cable bundles overhead. Empty, the noodle stall lighting its burner, blue-grey dark, one steam-lit lamp. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A dead-end lane where netrunners meet in the flesh, taped junction boxes, a noodle stall's steam, dead screens that sometimes wake, cable bundles overhead, empty, the noodle stall lighting its burner, blue-grey dark, one steam-lit lamp, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/ghost-alley-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
A dead-end lane where netrunners meet in the flesh. Visible detail: taped junction boxes, a noodle stall's steam, dead screens that sometimes wake, cable bundles overhead. Quiet, one figure at a junction box, thin daylight that never reaches the alley floor. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A dead-end lane where netrunners meet in the flesh, taped junction boxes, a noodle stall's steam, dead screens that sometimes wake, cable bundles overhead, quiet, one figure at a junction box, thin daylight that never reaches the alley floor, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/ghost-alley-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
A dead-end lane where netrunners meet in the flesh. Visible detail: taped junction boxes, a noodle stall's steam, dead screens that sometimes wake, cable bundles overhead. The broker line's hours beginning, screen-light waking in upper windows. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A dead-end lane where netrunners meet in the flesh, taped junction boxes, a noodle stall's steam, dead screens that sometimes wake, cable bundles overhead, the broker line's hours beginning, screen-light waking in upper windows, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/ghost-alley-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
A dead-end lane where netrunners meet in the flesh. Visible detail: taped junction boxes, a noodle stall's steam, dead screens that sometimes wake, cable bundles overhead. Figures at intervals, all pretending not to wait, cyan screen-glow, the rest in true dark. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A dead-end lane where netrunners meet in the flesh, taped junction boxes, a noodle stall's steam, dead screens that sometimes wake, cable bundles overhead, figures at intervals, all pretending not to wait, cyan screen-glow, the rest in true dark, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

### `rusty_anchor`

- **File:** `scenes/rusty-anchor.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
A dockside-style tavern interior that remembers everyone. Visible detail: a long scarred bar, keg stack, a ledger under the taps, crews at plank tables, steamed windows. Chairs down, ines counting kegs, grey window light, the bar lamps off. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A dockside-style tavern interior that remembers everyone, a long scarred bar, keg stack, a ledger under the taps, crews at plank tables, steamed windows, chairs down, Ines counting kegs, grey window light, the bar lamps off, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/rusty-anchor-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
A dockside-style tavern interior that remembers everyone. Visible detail: a long scarred bar, keg stack, a ledger under the taps, crews at plank tables, steamed windows. Eaters and one quiet negotiation, warm lamps against a wet grey window. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A dockside-style tavern interior that remembers everyone, a long scarred bar, keg stack, a ledger under the taps, crews at plank tables, steamed windows, eaters and one quiet negotiation, warm lamps against a wet grey window, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/rusty-anchor-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
A dockside-style tavern interior that remembers everyone. Visible detail: a long scarred bar, keg stack, a ledger under the taps, crews at plank tables, steamed windows. Shift crowd arriving, the room getting loud, amber bar light, faces warm. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A dockside-style tavern interior that remembers everyone, a long scarred bar, keg stack, a ledger under the taps, crews at plank tables, steamed windows, shift crowd arriving, the room getting loud, amber bar light, faces warm, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/rusty-anchor-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
A dockside-style tavern interior that remembers everyone. Visible detail: a long scarred bar, keg stack, a ledger under the taps, crews at plank tables, steamed windows. Crews forged over synth-beer, one man alone at the short end, low warm light, the ledger in shadow. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A dockside-style tavern interior that remembers everyone, a long scarred bar, keg stack, a ledger under the taps, crews at plank tables, steamed windows, crews forged over synth-beer, one man alone at the short end, low warm light, the ledger in shadow, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

### `omnicorp_plaza`

- **File:** `scenes/omnicorp-plaza.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
A vast corporate plaza between glass towers at street level. Visible detail: polished stone, sparse figures, silent security drones, camera masts, tower glass rising out of frame. Empty acres of stone, sprinklers washing it, cold blue pre-dawn, tower lights above. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A vast corporate plaza between glass towers at street level, polished stone, sparse figures, silent security drones, camera masts, tower glass rising out of frame, empty acres of stone, sprinklers washing it, cold blue pre-dawn, tower lights above, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/omnicorp-plaza-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
A vast corporate plaza between glass towers at street level. Visible detail: polished stone, sparse figures, silent security drones, camera masts, tower glass rising out of frame. Lanyards crossing at intervals, security watching, white corporate daylight, no warmth in it. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A vast corporate plaza between glass towers at street level, polished stone, sparse figures, silent security drones, camera masts, tower glass rising out of frame, lanyards crossing at intervals, security watching, white corporate daylight, no warmth in it, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/omnicorp-plaza-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
A vast corporate plaza between glass towers at street level. Visible detail: polished stone, sparse figures, silent security drones, camera masts, tower glass rising out of frame. The exodus, a thousand identical coats, tower glass burning with sunset it does not share. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A vast corporate plaza between glass towers at street level, polished stone, sparse figures, silent security drones, camera masts, tower glass rising out of frame, the exodus, a thousand identical coats, tower glass burning with sunset it does not share, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/omnicorp-plaza-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
A vast corporate plaza between glass towers at street level. Visible detail: polished stone, sparse figures, silent security drones, camera masts, tower glass rising out of frame. Empty, lit like a stage nobody performs on, white security floods, drone running-lights. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A vast corporate plaza between glass towers at street level, polished stone, sparse figures, silent security drones, camera masts, tower glass rising out of frame, empty, lit like a stage nobody performs on, white security floods, drone running-lights, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

### `synthsec_gridpoint`

- **File:** `scenes/synthsec-gridpoint.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
A militarized checkpoint between the city and the dark. Visible detail: wire fencing, a sensor mast, a gatehouse, red floodlights, a truck lane with a barrier arm, one corporal at the gate. Shift change, trucks queued at the wire, red floods against grey first light. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A militarized checkpoint between the city and the dark, wire fencing, a sensor mast, a gatehouse, red floodlights, a truck lane with a barrier arm, one corporal at the gate, shift change, trucks queued at the wire, red floods against grey first light, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/synthsec-gridpoint-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
A militarized checkpoint between the city and the dark. Visible detail: wire fencing, a sensor mast, a gatehouse, red floodlights, a truck lane with a barrier arm, one corporal at the gate. Papers being checked, the mast turning slowly, hard flat light, red accents. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A militarized checkpoint between the city and the dark, wire fencing, a sensor mast, a gatehouse, red floodlights, a truck lane with a barrier arm, one corporal at the gate, papers being checked, the mast turning slowly, hard flat light, red accents, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/synthsec-gridpoint-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
A militarized checkpoint between the city and the dark. Visible detail: wire fencing, a sensor mast, a gatehouse, red floodlights, a truck lane with a barrier arm, one corporal at the gate. The day's last crossings, the dark side going black, red floodlight and long shadows through wire. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A militarized checkpoint between the city and the dark, wire fencing, a sensor mast, a gatehouse, red floodlights, a truck lane with a barrier arm, one corporal at the gate, the day's last crossings, the dark side going black, red floodlight and long shadows through wire, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/synthsec-gridpoint-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
A militarized checkpoint between the city and the dark. Visible detail: wire fencing, a sensor mast, a gatehouse, red floodlights, a truck lane with a barrier arm, one corporal at the gate. The gate an island of light with nothing beyond it, red floods, the mast's status lights, absolute dark past the wire. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A militarized checkpoint between the city and the dark, wire fencing, a sensor mast, a gatehouse, red floodlights, a truck lane with a barrier arm, one corporal at the gate, the gate an island of light with nothing beyond it, red floods, the mast's status lights, absolute dark past the wire, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

### `deepstate_bunker`

- **File:** `scenes/deepstate-bunker.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
An archive hall below ground, shelving receding past the light. Visible detail: numbered drive racks going back into dark, a single desk with a blotter, a counter with tags face down, violet accent light. Unchanged; the hall does not have mornings, violet accents over dark shelving, one desk lamp. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An archive hall below ground, shelving receding past the light, numbered drive racks going back into dark, a single desk with a blotter, a counter with tags face down, violet accent light, unchanged; the hall does not have mornings, violet accents over dark shelving, one desk lamp, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/deepstate-bunker-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
An archive hall below ground, shelving receding past the light. Visible detail: numbered drive racks going back into dark, a single desk with a blotter, a counter with tags face down, violet accent light. Unchanged, one figure at the counter, the same violet dark, the same lamp. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An archive hall below ground, shelving receding past the light, numbered drive racks going back into dark, a single desk with a blotter, a counter with tags face down, violet accent light, unchanged, one figure at the counter, the same violet dark, the same lamp, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/deepstate-bunker-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
An archive hall below ground, shelving receding past the light. Visible detail: numbered drive racks going back into dark, a single desk with a blotter, a counter with tags face down, violet accent light. Unchanged, the blotter mid-page, lamp and violet dark, always. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An archive hall below ground, shelving receding past the light, numbered drive racks going back into dark, a single desk with a blotter, a counter with tags face down, violet accent light, unchanged, the blotter mid-page, lamp and violet dark, always, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/deepstate-bunker-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
An archive hall below ground, shelving receding past the light. Visible detail: numbered drive racks going back into dark, a single desk with a blotter, a counter with tags face down, violet accent light. Unchanged; time is a thing that happens upstairs, the desk lamp, and the dark taking the rest. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An archive hall below ground, shelving receding past the light, numbered drive racks going back into dark, a single desk with a blotter, a counter with tags face down, violet accent light, unchanged; time is a thing that happens upstairs, the desk lamp, and the dark taking the rest, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

### `shadow_crossing`

- **File:** `scenes/shadow-crossing.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
Open dead ground between a distant wire and a far structure, no lights anywhere. Visible detail: wrecks half-sunk in mud, rain moving in sheets, pre-corporate concrete stubs, a tiny torch-beam scale figure. Grey light finding the wrecks one at a time, weak colourless dawn under full cloud. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
Open dead ground between a distant wire and a far structure, no lights anywhere, wrecks half-sunk in mud, rain moving in sheets, pre-corporate concrete stubs, a tiny torch-beam scale figure, grey light finding the wrecks one at a time, weak colourless dawn under full cloud, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/shadow-crossing-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
Open dead ground between a distant wire and a far structure, no lights anywhere. Visible detail: wrecks half-sunk in mud, rain moving in sheets, pre-corporate concrete stubs, a tiny torch-beam scale figure. Flat waste under a low sky, the city a glow behind, dim storm-light, no shadows. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
Open dead ground between a distant wire and a far structure, no lights anywhere, wrecks half-sunk in mud, rain moving in sheets, pre-corporate concrete stubs, a tiny torch-beam scale figure, flat waste under a low sky, the city a glow behind, dim storm-light, no shadows, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/shadow-crossing-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
Open dead ground between a distant wire and a far structure, no lights anywhere. Visible detail: wrecks half-sunk in mud, rain moving in sheets, pre-corporate concrete stubs, a tiny torch-beam scale figure. The dark arriving early and completely, the last light on wet mud, the city's neon a far smear. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
Open dead ground between a distant wire and a far structure, no lights anywhere, wrecks half-sunk in mud, rain moving in sheets, pre-corporate concrete stubs, a tiny torch-beam scale figure, the dark arriving early and completely, the last light on wet mud, the city's neon a far smear, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/shadow-crossing-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
Open dead ground between a distant wire and a far structure, no lights anywhere. Visible detail: wrecks half-sunk in mud, rain moving in sheets, pre-corporate concrete stubs, a tiny torch-beam scale figure. True dark, rain, something's suggestion of movement, one hand torch against everything. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
Open dead ground between a distant wire and a far structure, no lights anywhere, wrecks half-sunk in mud, rain moving in sheets, pre-corporate concrete stubs, a tiny torch-beam scale figure, true dark, rain, something's suggestion of movement, one hand torch against everything, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

### `the_lift`

- **File:** `scenes/the-lift.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
A freight lift head inside a poured-slab shed older than the city. Visible detail: massive slab walls, a winch mechanism with three stations, lift doors of pitted metal, cable spools, one cage lamp. The shed interior, doors shut, dust unmoved, one cage lamp, slab-dark corners. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A freight lift head inside a poured-slab shed older than the city, massive slab walls, a winch mechanism with three stations, lift doors of pitted metal, cable spools, one cage lamp, the shed interior, doors shut, dust unmoved, one cage lamp, slab-dark corners, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/the-lift-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
A freight lift head inside a poured-slab shed older than the city. Visible detail: massive slab walls, a winch mechanism with three stations, lift doors of pitted metal, cable spools, one cage lamp. The winch stations, the panel's single waking light, torchlight and the panel's cyan point. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A freight lift head inside a poured-slab shed older than the city, massive slab walls, a winch mechanism with three stations, lift doors of pitted metal, cable spools, one cage lamp, the winch stations, the panel's single waking light, torchlight and the panel's cyan point, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/the-lift-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
A freight lift head inside a poured-slab shed older than the city. Visible detail: massive slab walls, a winch mechanism with three stations, lift doors of pitted metal, cable spools, one cage lamp. Figures at the winch, the doors considering, cage lamp and torches, cyan on the panel. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A freight lift head inside a poured-slab shed older than the city, massive slab walls, a winch mechanism with three stations, lift doors of pitted metal, cable spools, one cage lamp, figures at the winch, the doors considering, cage lamp and torches, cyan on the panel, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/the-lift-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
A freight lift head inside a poured-slab shed older than the city. Visible detail: massive slab walls, a winch mechanism with three stations, lift doors of pitted metal, cable spools, one cage lamp. The doors open on a descending dark, the shaft swallowing every lumen offered. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A freight lift head inside a poured-slab shed older than the city, massive slab walls, a winch mechanism with three stations, lift doors of pitted metal, cable spools, one cage lamp, the doors open on a descending dark, the shaft swallowing every lumen offered, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

### `core_hall`

- **File:** `scenes/core-hall.jpg`
- **Size:** 1344x768

#### Base — dawn

**Grok Imagine** (prose)

```text
An immense server hall of pre-corporate scale, cold and humming. Visible detail: rack rows receding beyond sight, cyan status lights by the million, poured stone older than any logo, a single human figure for scale. The hall; it has no dawn, a million cyan points in absolute black. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An immense server hall of pre-corporate scale, cold and humming, rack rows receding beyond sight, cyan status lights by the million, poured stone older than any logo, a single human figure for scale, the hall; it has no dawn, a million cyan points in absolute black, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

<details><summary>Alt — day (`scenes/core-hall-day.jpg`)</summary>

**Grok Imagine** (prose)

```text
An immense server hall of pre-corporate scale, cold and humming. Visible detail: rack rows receding beyond sight, cyan status lights by the million, poured stone older than any logo, a single human figure for scale. The hall, unchanged, patient, cyan constellation light, cold. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An immense server hall of pre-corporate scale, cold and humming, rack rows receding beyond sight, cyan status lights by the million, poured stone older than any logo, a single human figure for scale, the hall, unchanged, patient, cyan constellation light, cold, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — dusk (`scenes/core-hall-dusk.jpg`)</summary>

**Grok Imagine** (prose)

```text
An immense server hall of pre-corporate scale, cold and humming. Visible detail: rack rows receding beyond sight, cyan status lights by the million, poured stone older than any logo, a single human figure for scale. The hall, indifferent, cyan on black, a cursor's worth of movement somewhere. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An immense server hall of pre-corporate scale, cold and humming, rack rows receding beyond sight, cyan status lights by the million, poured stone older than any logo, a single human figure for scale, the hall, indifferent, cyan on black, a cursor's worth of movement somewhere, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

<details><summary>Alt — night (`scenes/core-hall-night.jpg`)</summary>

**Grok Imagine** (prose)

```text
An immense server hall of pre-corporate scale, cold and humming. Visible detail: rack rows receding beyond sight, cyan status lights by the million, poured stone older than any logo, a single human figure for scale. The hall, describing, cyan points to the horizon of the room. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An immense server hall of pre-corporate scale, cold and humming, rack rows receding beyond sight, cyan status lights by the million, poured stone older than any logo, a single human figure for scale, the hall, describing, cyan points to the horizon of the room, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

</details>

---

## Portraits (11)

### `mira_vex`

- **File:** `portraits/mira-vex.jpg`
- **Size:** 768x1024

**Grok Imagine** (prose)

```text
A fixer at her market counter, red hair, green eyes, faster than her smile. Visible detail: fingerless gloves, a counter of street-tech between her and the viewer, one eyebrow pricing something. The grid's green neon behind her, ticker light on the glass, fast, flat, amused at a rate she controls. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A fixer at her market counter, red hair, green eyes, faster than her smile, fingerless gloves, a counter of street-tech between her and the viewer, one eyebrow pricing something, the Grid's green neon behind her, ticker light on the glass, fast, flat, amused at a rate she controls, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `lyra_vance`

- **File:** `portraits/lyra-vance.jpg`
- **Size:** 768x1024

**Grok Imagine** (prose)

```text
A broker lit by three screens in a dark room. Visible detail: close-cut hair, unblinking eyes with screen reflections, a headset around the neck, cable everywhere. Ghost alley's broker room, cyan screen-glow the only light, precise, remote, listening to something else as well. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A broker lit by three screens in a dark room, close-cut hair, unblinking eyes with screen reflections, a headset around the neck, cable everywhere, Ghost Alley's broker room, cyan screen-glow the only light, precise, remote, listening to something else as well, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `ivo_dane`

- **File:** `portraits/ivo-dane.jpg`
- **Size:** 768x1024

**Grok Imagine** (prose)

```text
A gate corporal in SynthSec grey, tired and exact. Visible detail: middle years, weather-worn face, immaculate uniform worn like a debt, eyes that count. The grid point gatehouse, red floodlight from one side, tired, exact, six years deep. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A gate corporal in SynthSec grey, tired and exact, middle years, weather-worn face, immaculate uniform worn like a debt, eyes that count, the Grid Point gatehouse, red floodlight from one side, tired, exact, six years deep, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `grease`

- **File:** `portraits/grease.jpg`
- **Size:** 768x1024

**Grok Imagine** (prose)

```text
A scrap queen in a crane harness, third generation and it shows. Visible detail: broad shoulders, oil-marked overalls, a priced glance, hair tied back with cable. The junkyard's amber floods and stacked hulls behind her, honest by the kilo, nobody's fool. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A scrap queen in a crane harness, third generation and it shows, broad shoulders, oil-marked overalls, a priced glance, hair tied back with cable, the Junkyard's amber floods and stacked hulls behind her, honest by the kilo, nobody's fool, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `dr_sable`

- **File:** `portraits/dr-sable.jpg`
- **Size:** 768x1024

**Grok Imagine** (prose)

```text
A struck-off surgeon in a spotless apron over street clothes. Visible detail: steady hands, magnifier pushed up on her forehead, eyes that have seen the whole menu. The clinic's white-and-red light, a recovery chair behind, brisk, unshockable, cash up front. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A struck-off surgeon in a spotless apron over street clothes, steady hands, magnifier pushed up on her forehead, eyes that have seen the whole menu, the clinic's white-and-red light, a recovery chair behind, brisk, unshockable, cash up front, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `rho`

- **File:** `portraits/rho.jpg`
- **Size:** 768x1024

**Grok Imagine** (prose)

```text
A fence of indeterminate everything at a table with a spread cloth. Visible detail: plain dark clothes with no labels and no history, gloved hands, face half out of the lamp light on purpose. The velvet pit's back table, one lamp on the cloth, epigrammatic, amused by provenance. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A fence of indeterminate everything at a table with a spread cloth, plain dark clothes with no labels and no history, gloved hands, face half out of the lamp light on purpose, the Velvet Pit's back table, one lamp on the cloth, epigrammatic, amused by provenance, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `dita_halvorsen`

- **File:** `portraits/dita-halvorsen.jpg`
- **Size:** 768x1024

**Grok Imagine** (prose)

```text
A wheelwoman drawing tunnel junctions on a napkin from memory. Visible detail: wiry, driving gloves tucked in an epaulette, eyes that have already left by every exit. The end of the pit's bar, amber light, professional, precise about numbers, unhurried. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A wheelwoman drawing tunnel junctions on a napkin from memory, wiry, driving gloves tucked in an epaulette, eyes that have already left by every exit, the end of the Pit's bar, amber light, professional, precise about numbers, unhurried, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `frankie`

- **File:** `portraits/frankie.jpg`
- **Size:** 768x1024

**Grok Imagine** (prose)

```text
An info broker dealing cards at a private table. Visible detail: slicked black hair, immaculate cuffs, a card face-down under one finger, a smile with a ledger behind it. Club noir's gold table light, black marble dark behind, charming, transactional, first to know. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An info broker dealing cards at a private table, slicked black hair, immaculate cuffs, a card face-down under one finger, a smile with a ledger behind it, Club Noir's gold table light, black marble dark behind, charming, transactional, first to know, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `ines_barbosa`

- **File:** `portraits/ines-barbosa.jpg`
- **Size:** 768x1024

**Grok Imagine** (prose)

```text
A tavern keeper at her taps with a ledger below the bar. Visible detail: strong forearms, an apron older than the clientele, eyes that record. The rusty anchor's warm lamps and steamed window, warm at a fixed rate, remembers everything. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A tavern keeper at her taps with a ledger below the bar, strong forearms, an apron older than the clientele, eyes that record, the Rusty Anchor's warm lamps and steamed window, warm at a fixed rate, remembers everything, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `wren_solis`

- **File:** `portraits/wren-solis.jpg`
- **Size:** 768x1024

**Grok Imagine** (prose)

```text
A courier-faced person of no fixed name at an archive counter. Visible detail: unremarkable on purpose, neat dark clothes, price tags face down on the counter, a gaze with a shutter in it. The bunker's violet-lit shelving receding behind, flat, contained, four names this year. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A courier-faced person of no fixed name at an archive counter, unremarkable on purpose, neat dark clothes, price tags face down on the counter, a gaze with a shutter in it, the Bunker's violet-lit shelving receding behind, flat, contained, four names this year, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `the_archivist`

- **File:** `portraits/the-archivist.jpg`
- **Size:** 768x1024

**Grok Imagine** (prose)

```text
An old archivist writing in a ledger, face never quite resolving. Visible detail: a blotter, an antique pen, hands older than the shelving, features that slide off memory. A desk lamp's pool in an archive dark, shelving beyond, patient, past-tense, without cruelty. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An old archivist writing in a ledger, face never quite resolving, a blotter, an antique pen, hands older than the shelving, features that slide off memory, a desk lamp's pool in an archive dark, shelving beyond, patient, past-tense, without cruelty, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

## Items (50)

### `synth_food`

- **File:** `items/synth-food.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A vacuum-pressed synthetic food brick in drab shrink-wrap. Visible detail: ration-grade, corner torn, dense extruded texture visible. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A vacuum-pressed synthetic food brick in drab shrink-wrap, ration-grade, corner torn, dense extruded texture visible, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `sprawl_ramen`

- **File:** `items/sprawl-ramen.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A steaming bag of street ramen with a tape handle. Visible detail: noodles and broth in translucent plastic, chopsticks through the tape. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A steaming bag of street ramen with a tape handle, noodles and broth in translucent plastic, chopsticks through the tape, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `sump_coffee`

- **File:** `items/sump-coffee.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A dented metal flask of black street coffee. Visible detail: steam off the mouth, oily sheen on the coffee, thumb-worn flask. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A dented metal flask of black street coffee, steam off the mouth, oily sheen on the coffee, thumb-worn flask, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `sealed_ration`

- **File:** `items/sealed-ration.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A corp-issue field ration in a foil brick, seal intact. Visible detail: serial burned off one corner, decade-old packaging design. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A corp-issue field ration in a foil brick, seal intact, serial burned off one corner, decade-old packaging design, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `protein_paste`

- **File:** `items/protein-paste.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A half-rolled tube of grey protein paste. Visible detail: nutrition grid printed small, a bead of grey at the nozzle. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A half-rolled tube of grey protein paste, nutrition grid printed small, a bead of grey at the nozzle, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `synth_beer`

- **File:** `items/synth-beer.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A condensation-beaded bottle of unlabelled synth-beer. Visible detail: amber glass, no label, a tavern's own crown cap. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A condensation-beaded bottle of unlabelled synth-beer, amber glass, no label, a tavern's own crown cap, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `stim_patch`

- **File:** `items/stim-patch.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A translucent adhesive stimulant patch on its backing. Visible detail: micro-needle grid catching the light, one lifted corner. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A translucent adhesive stimulant patch on its backing, micro-needle grid catching the light, one lifted corner, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `overdrive_amp`

- **File:** `items/overdrive-amp.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A matte-black injector ampoule with a red band. Visible detail: military lines, a dose window showing amber fluid. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A matte-black injector ampoule with a red band, military lines, a dose window showing amber fluid, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `medkit`

- **File:** `items/medkit.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A soft-shell street medkit, unzipped a finger's width. Visible detail: worn red shell, sutures and sealant visible at the zip. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A soft-shell street medkit, unzipped a finger's width, worn red shell, sutures and sealant visible at the zip, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `trauma_patch`

- **File:** `items/trauma-patch.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A heavy trauma patch in sterile foil, palm sized. Visible detail: clinical print, one corner dog-eared from a pocket. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A heavy trauma patch in sterile foil, palm sized, clinical print, one corner dog-eared from a pocket, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `salvage_tech`

- **File:** `items/salvage-tech.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A bundle of salvaged circuit boards and relays tied with wire. Visible detail: gold contacts bright against corrosion, yard mud in the sockets. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A bundle of salvaged circuit boards and relays tied with wire, gold contacts bright against corrosion, yard mud in the sockets, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `copper_spool`

- **File:** `items/copper-spool.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A tight hand-wound spool of stripped copper wire. Visible detail: bright metal where the sheath came off, heavy and honest. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A tight hand-wound spool of stripped copper wire, bright metal where the sheath came off, heavy and honest, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `deck_parts`

- **File:** `items/deck-parts.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A cyberdeck's pulled internals laid in a neat row. Visible detail: co-processor, cooling sleeve, an input array with thumb-wear. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A cyberdeck's pulled internals laid in a neat row, co-processor, cooling sleeve, an input array with thumb-wear, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `courier_wrap`

- **File:** `items/courier-wrap.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A weatherproof courier carry-harness, coiled. Visible detail: matte straps, sealed seams, one buckle scorched. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A weatherproof courier carry-harness, coiled, matte straps, sealed seams, one buckle scorched, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `drone_chassis`

- **File:** `items/drone-chassis.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A grounded surveillance drone chassis, rotors snapped. Visible detail: corp serial ground off, lens cluster cracked, yard grit. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A grounded surveillance drone chassis, rotors snapped, corp serial ground off, lens cluster cracked, yard grit, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `dropped_credstick`

- **File:** `items/dropped-credstick.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
An anonymous credstick trodden flat into wet asphalt. Visible detail: scuffed casing, contact strip still bright. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An anonymous credstick trodden flat into wet asphalt, scuffed casing, contact strip still bright, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `tourist_visor`

- **File:** `items/tourist-visor.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A rental AR visor with a snapped strap. Visible detail: candy-coloured shell, geofence sticker peeling. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A rental AR visor with a snapped strap, candy-coloured shell, geofence sticker peeling, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `dead_drop_shard`

- **File:** `items/dead-drop-shard.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A data shard wrapped in weatherproof tape. Visible detail: tape half peeled, cyan contact edge showing. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A data shard wrapped in weatherproof tape, tape half peeled, cyan contact edge showing, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `ice_fragment`

- **File:** `items/ice-fragment.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A fractured black data crystal with sharp edges. Visible detail: internal fault-lines catching cyan light, faintly wrong to look at. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A fractured black data crystal with sharp edges, internal fault-lines catching cyan light, faintly wrong to look at, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `cache_key`

- **File:** `items/cache-key.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A single-use credential key, industrial and anonymous. Visible detail: rolling code window dark, tamper seal intact. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A single-use credential key, industrial and anonymous, rolling code window dark, tamper seal intact, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `camera_capture`

- **File:** `items/camera-capture.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A thin frame-set cartridge from a street camera. Visible detail: evidence-grade housing, timestamp window blank. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A thin frame-set cartridge from a street camera, evidence-grade housing, timestamp window blank, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `patrol_log`

- **File:** `items/patrol-log.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A dot-matrix patrol route sheet, folded twice. Visible detail: grey print on cheap paper, rain-spotted, one route circled. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A dot-matrix patrol route sheet, folded twice, grey print on cheap paper, rain-spotted, one route circled, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `precorp_cable`

- **File:** `items/precorp-cable.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A length of pre-corporate sheathed cable, coiled. Visible detail: insulation stamped with an unregistered maker's mark, unaged. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A length of pre-corporate sheathed cable, coiled, insulation stamped with an unregistered maker's mark, unaged, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `precorp_tooling`

- **File:** `items/precorp-tooling.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A machined hand tool for an unnameable job. Visible detail: tolerances too fine to measure, no wear anywhere, older than every logo. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A machined hand tool for an unnameable job, tolerances too fine to measure, no wear anywhere, older than every logo, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `one_of_one`

- **File:** `items/one-of-one.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A small machined object with no production siblings. Visible detail: geometry that resolves differently at second glance, matte finish, no marks. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A small machined object with no production siblings, geometry that resolves differently at second glance, matte finish, no marks, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `rain_shell`

- **File:** `items/rain-shell.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A folded laminate rain poncho, taped seams. Visible detail: packs to a fist, drab, acid-spotted at the hem. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A folded laminate rain poncho, taped seams, packs to a fist, drab, acid-spotted at the hem, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `filter_mask`

- **File:** `items/filter-mask.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A twin-cartridge civilian filter mask. Visible detail: rubber seals cracked at the edges, cartridge windows half spent. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A twin-cartridge civilian filter mask, rubber seals cracked at the edges, cartridge windows half spent, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `climbing_rig`

- **File:** `items/climbing-rig.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A compact climbing harness with line and two cams. Visible detail: yard-worn webbing, chalk and oil, the line coiled tight. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A compact climbing harness with line and two cams, yard-worn webbing, chalk and oil, the line coiled tight, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `flash_torch`

- **File:** `items/flash-torch.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A heavy hand lamp with a scarred lens. Visible detail: aluminium body dented, tape grip, honest white beam off. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A heavy hand lamp with a scarred lens, aluminium body dented, tape grip, honest white beam off, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `street_pistol`

- **File:** `items/street-pistol.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A stamped-frame pistol with a filed serial. Visible detail: two magazines beside it, matte and history-free. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A stamped-frame pistol with a filed serial, two magazines beside it, matte and history-free, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `shock_baton`

- **File:** `items/shock-baton.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A collapsed shock baton with a capacitor window. Visible detail: livestock-tool markings, charge light dark. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A collapsed shock baton with a capacitor window, livestock-tool markings, charge light dark, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `burner_deck`

- **File:** `items/burner-deck.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A cheap cyberdeck with the casing screws mismatched. Visible detail: boots, works, disposable; a storm-drain-ready deck. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A cheap cyberdeck with the casing screws mismatched, boots, works, disposable; a storm-drain-ready deck, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `emp_grenade`

- **File:** `items/emp-grenade.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A drab pulse charge the size of a fist. Visible detail: arming collar taped, stencil markings sanded off. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A drab pulse charge the size of a fist, arming collar taped, stencil markings sanded off, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `id_scrub`

- **File:** `items/id-scrub.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A single-use identity solvent stick in plain packaging. Visible detail: one-time chip visible through the shell, no branding. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A single-use identity solvent stick in plain packaging, one-time chip visible through the shell, no branding, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `cooldown_spoof`

- **File:** `items/cooldown-spoof.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A forged closure-paperwork injector chip on a lanyard. Visible detail: official-looking seal that does not survive attention. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A forged closure-paperwork injector chip on a lanyard, official-looking seal that does not survive attention, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `burner_face`

- **File:** `items/burner-face.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A subdermal restructuring kit in a clinical case. Visible detail: applicator and ampoules in cut foam, deeply unpleasant implications. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A subdermal restructuring kit in a clinical case, applicator and ampoules in cut foam, deeply unpleasant implications, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `ghost_protocol`

- **File:** `items/ghost-protocol.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A matte black card with no markings at all. Visible detail: absorbs the light that hits it, one contact edge. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A matte black card with no markings at all, absorbs the light that hits it, one contact edge, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `black_ice`

- **File:** `items/black-ice.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A jet-black data spike that seems to bite the light. Visible detail: faint red tracery under the surface, edges you do not test with a thumb. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A jet-black data spike that seems to bite the light, faint red tracery under the surface, edges you do not test with a thumb, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `red_lace`

- **File:** `items/red-lace.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A folded paper wrap leaking a red crystalline dust. Visible detail: wax-paper folds, a residue that catches neon. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A folded paper wrap leaking a red crystalline dust, wax-paper folds, a residue that catches neon, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `forged_id`

- **File:** `items/forged-id.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A clean identity laminate with a stranger's name. Visible detail: hologram slightly too perfect, two good spends in it. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A clean identity laminate with a stranger's name, hologram slightly too perfect, two good spends in it, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `the_shard`

- **File:** `items/the-shard.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A single black data shard on wet asphalt. Visible detail: unlabelled, corporate header notch, forty seconds inside it. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A single black data shard on wet asphalt, unlabelled, corporate header notch, forty seconds inside it, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `halloran_drop`

- **File:** `items/halloran-drop.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A taped weatherproof package from inside a junction box. Visible detail: tape printed with rain, a careful man's knots. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A taped weatherproof package from inside a junction box, tape printed with rain, a careful man's knots, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `routing_stamp`

- **File:** `items/routing-stamp.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A corporate routing stamp chip in an evidence sleeve. Visible detail: authority glyph etched small, older styling than the corp that uses it. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A corporate routing stamp chip in an evidence sleeve, authority glyph etched small, older styling than the corp that uses it, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `stamp_registry`

- **File:** `items/stamp-registry.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A sheaf of registry printout, still printer-warm. Visible detail: columns of authorities, one row's worth of dread. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A sheaf of registry printout, still printer-warm, columns of authorities, one row's worth of dread, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `confidence_paper`

- **File:** `items/confidence-paper.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A single sheet of paper with a decimal figure on it. Visible detail: typed, unsigned, too many decimal places to argue with. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A single sheet of paper with a decimal figure on it, typed, unsigned, too many decimal places to argue with, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `truck_manifest`

- **File:** `items/truck-manifest.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A cargo manifest flimsy with one resolved column. Visible detail: carbon-copy grey, the cargo line legible and wrong. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A cargo manifest flimsy with one resolved column, carbon-copy grey, the cargo line legible and wrong, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `floor87_pass`

- **File:** `items/floor87-pass.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A laminated visitor pass for an unlisted floor. Visible detail: corporate blank with an 87 punched where a floor code goes. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A laminated visitor pass for an unlisted floor, corporate blank with an 87 punched where a floor code goes, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `access_codes`

- **File:** `items/access-codes.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A cold-boot credential slate of pre-corporate make. Visible detail: numbering that does not start at one, contacts of unworn gold. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A cold-boot credential slate of pre-corporate make, numbering that does not start at one, contacts of unworn gold, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `shadow_map`

- **File:** `items/shadow-map.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A hand-drawn map of ground no satellite will admit to. Visible detail: draughtsman-precise linework, annotations in a careful hand. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A hand-drawn map of ground no satellite will admit to, draughtsman-precise linework, annotations in a careful hand, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

### `proxy_effigy`

- **File:** `items/proxy-effigy.jpg`
- **Size:** 256x256

**Grok Imagine** (prose)

```text
A telemetry doppel folded into a coat, boxed. Visible detail: gait servos at the joints, a pulse unit where a heart would sit. The single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround. Cinematic cyberpunk illustration on a near-black canvas, rain-slick surfaces, neon as the only light source, cyan accent light threading the dark, heavy atmosphere, painterly grain, faces and objects lit by screens and signage, no text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A telemetry doppel folded into a coat, boxed, gait servos at the joints, a pulse unit where a heart would sit, the single object alone in the centre of a square frame, laid on wet black asphalt or dark brushed metal, a faint cyan rim light, nothing else in the frame, one cold cyan accent light from the upper left, soft neon reflections in the wet ground, deep black surround, cyberpunk illustration, black canvas, neon noir, rain-slick streets, cyan accent lighting, screen-lit faces, painterly, heavy atmosphere, volumetric haze, no text, no watermark
```

```text
NEGATIVE: daylight, sunshine, medieval, fantasy, cartoon, anime, bright cheerful colors, text, lettering, watermark, logo, blurry, low quality, clean streets, emoji, user interface elements
```

---

## LoRA hints

From `subjects.yaml` `style.loras`. ComfyUI only; Grok ignores them.

```yaml
- name: Neon_Noir
  weight: 0.6
- name: Rain_City
  weight: 0.4
```

## Manifest block to paste

```yaml
locations:
  the_grid:
    base: scenes/the-grid.jpg
    alts: []   # optional: scenes/the-grid-day.jpg, scenes/the-grid-dusk.jpg, scenes/the-grid-night.jpg
  neon_strip:
    base: scenes/neon-strip.jpg
    alts: []   # optional: scenes/neon-strip-day.jpg, scenes/neon-strip-dusk.jpg, scenes/neon-strip-night.jpg
  club_noir:
    base: scenes/club-noir.jpg
    alts: []   # optional: scenes/club-noir-day.jpg, scenes/club-noir-dusk.jpg, scenes/club-noir-night.jpg
  velvet_pit:
    base: scenes/velvet-pit.jpg
    alts: []   # optional: scenes/velvet-pit-day.jpg, scenes/velvet-pit-dusk.jpg, scenes/velvet-pit-night.jpg
  junkyard_sprawl:
    base: scenes/junkyard-sprawl.jpg
    alts: []   # optional: scenes/junkyard-sprawl-day.jpg, scenes/junkyard-sprawl-dusk.jpg, scenes/junkyard-sprawl-night.jpg
  ripper_street:
    base: scenes/ripper-street.jpg
    alts: []   # optional: scenes/ripper-street-day.jpg, scenes/ripper-street-dusk.jpg, scenes/ripper-street-night.jpg
  ghost_alley:
    base: scenes/ghost-alley.jpg
    alts: []   # optional: scenes/ghost-alley-day.jpg, scenes/ghost-alley-dusk.jpg, scenes/ghost-alley-night.jpg
  rusty_anchor:
    base: scenes/rusty-anchor.jpg
    alts: []   # optional: scenes/rusty-anchor-day.jpg, scenes/rusty-anchor-dusk.jpg, scenes/rusty-anchor-night.jpg
  omnicorp_plaza:
    base: scenes/omnicorp-plaza.jpg
    alts: []   # optional: scenes/omnicorp-plaza-day.jpg, scenes/omnicorp-plaza-dusk.jpg, scenes/omnicorp-plaza-night.jpg
  synthsec_gridpoint:
    base: scenes/synthsec-gridpoint.jpg
    alts: []   # optional: scenes/synthsec-gridpoint-day.jpg, scenes/synthsec-gridpoint-dusk.jpg, scenes/synthsec-gridpoint-night.jpg
  deepstate_bunker:
    base: scenes/deepstate-bunker.jpg
    alts: []   # optional: scenes/deepstate-bunker-day.jpg, scenes/deepstate-bunker-dusk.jpg, scenes/deepstate-bunker-night.jpg
  shadow_crossing:
    base: scenes/shadow-crossing.jpg
    alts: []   # optional: scenes/shadow-crossing-day.jpg, scenes/shadow-crossing-dusk.jpg, scenes/shadow-crossing-night.jpg
  the_lift:
    base: scenes/the-lift.jpg
    alts: []   # optional: scenes/the-lift-day.jpg, scenes/the-lift-dusk.jpg, scenes/the-lift-night.jpg
  core_hall:
    base: scenes/core-hall.jpg
    alts: []   # optional: scenes/core-hall-day.jpg, scenes/core-hall-dusk.jpg, scenes/core-hall-night.jpg
portraits:
  mira_vex: portraits/mira-vex.jpg
  lyra_vance: portraits/lyra-vance.jpg
  ivo_dane: portraits/ivo-dane.jpg
  grease: portraits/grease.jpg
  dr_sable: portraits/dr-sable.jpg
  rho: portraits/rho.jpg
  dita_halvorsen: portraits/dita-halvorsen.jpg
  frankie: portraits/frankie.jpg
  ines_barbosa: portraits/ines-barbosa.jpg
  wren_solis: portraits/wren-solis.jpg
  the_archivist: portraits/the-archivist.jpg
items:
  synth_food: items/synth-food.jpg
  sprawl_ramen: items/sprawl-ramen.jpg
  sump_coffee: items/sump-coffee.jpg
  sealed_ration: items/sealed-ration.jpg
  protein_paste: items/protein-paste.jpg
  synth_beer: items/synth-beer.jpg
  stim_patch: items/stim-patch.jpg
  overdrive_amp: items/overdrive-amp.jpg
  medkit: items/medkit.jpg
  trauma_patch: items/trauma-patch.jpg
  salvage_tech: items/salvage-tech.jpg
  copper_spool: items/copper-spool.jpg
  deck_parts: items/deck-parts.jpg
  courier_wrap: items/courier-wrap.jpg
  drone_chassis: items/drone-chassis.jpg
  dropped_credstick: items/dropped-credstick.jpg
  tourist_visor: items/tourist-visor.jpg
  dead_drop_shard: items/dead-drop-shard.jpg
  ice_fragment: items/ice-fragment.jpg
  cache_key: items/cache-key.jpg
  camera_capture: items/camera-capture.jpg
  patrol_log: items/patrol-log.jpg
  precorp_cable: items/precorp-cable.jpg
  precorp_tooling: items/precorp-tooling.jpg
  one_of_one: items/one-of-one.jpg
  rain_shell: items/rain-shell.jpg
  filter_mask: items/filter-mask.jpg
  climbing_rig: items/climbing-rig.jpg
  flash_torch: items/flash-torch.jpg
  street_pistol: items/street-pistol.jpg
  shock_baton: items/shock-baton.jpg
  burner_deck: items/burner-deck.jpg
  emp_grenade: items/emp-grenade.jpg
  id_scrub: items/id-scrub.jpg
  cooldown_spoof: items/cooldown-spoof.jpg
  burner_face: items/burner-face.jpg
  ghost_protocol: items/ghost-protocol.jpg
  black_ice: items/black-ice.jpg
  red_lace: items/red-lace.jpg
  forged_id: items/forged-id.jpg
  the_shard: items/the-shard.jpg
  halloran_drop: items/halloran-drop.jpg
  routing_stamp: items/routing-stamp.jpg
  stamp_registry: items/stamp-registry.jpg
  confidence_paper: items/confidence-paper.jpg
  truck_manifest: items/truck-manifest.jpg
  floor87_pass: items/floor87-pass.jpg
  access_codes: items/access-codes.jpg
  shadow_map: items/shadow-map.jpg
  proxy_effigy: items/proxy-effigy.jpg
```
