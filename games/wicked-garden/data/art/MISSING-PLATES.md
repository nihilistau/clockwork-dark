# Missing plates — The Wicked Garden

8 subject(s) are authored in `subjects.yaml` and have no image in
`plates/`, so each falls through the resolution chain to the procedural
silhouette.
One of them is `mortal_threshold`, the entry location, which is why a new run
opens on a placeholder.

**Generated, not written.** Every prompt below is the output of
`engine.media.art.render_prose` / `render_tags` against the shipped
`subjects.yaml`, so it is exactly what the live pipeline would send — not a
fourth copy of the art voice free to drift from the three that ship. After
editing a subject, re-run the generator rather than editing the prompts here:

```powershell
.\.venv\Scripts\python.exe scripts\art_missing.py --game wicked-garden
```

## Order to work in

1. **`unknown`** — the fallback plate. One image and the procedural
   silhouette stops appearing for every location that has none of its own.
2. **`mortal_threshold`** — the entry location, so this is the first screen of
   every new run.
3. The rest, in any order. Each one only shows up if the player goes there.

## Sizes

| Kind | Size | Directory |
| --- | --- | --- |
| location | 1280x720 | `scenes/` under `paths.art_root` |
| portrait | 768x1024 | `portraits/` under `paths.art_root` |
| item | 768x1024 | `items/` under `paths.art_root` |

Read from `subjects.yaml`'s `formats:` block, which is also what the live Grok
and ComfyUI providers size their requests from — so generating by hand and
generating through the pipeline land the same shape. `tests/test_story_art.py`
holds that block to the plates actually on disk. JPEG, same as the rest.

## After the files land

`scripts/generate_art.py --game wicked-garden --promote` writes each plate the
generator made into `manifest.yaml` itself. For a plate made by hand, add it
under its kind: a location's plates go under `times: {<daypart>: ...}` (or
`base:` for a location whose subject declares no `times:` -- note that a
`base:` then answers every daypart); portraits and items take a bare path.
Paths are relative to `paths.art_root`. The ready-to-paste block is at the
bottom.

---

## Locations (6)

### `mortal_threshold`

- **Size:** 1280x720

Renders under the **`mortal`** style variant, not the house style — a drab modern flat has to read as the opposite of the Garden, and that contrast is the opening screen's job. So the prompt below carries no vines, petals or botanical art nouveau, even though the LoRA stack it still loads is called `Botanical_Fantasy`. The one flower that belongs here is in the **night** alt, through the floorboards, and nowhere else.

#### dawn

- **File:** `scenes/mortal-threshold-dawn.jpg`

**Grok Imagine** (prose)

```text
An ordinary empty room in the waking world, seen from the doorway. Visible detail: a coat still on its hook, unopened post stacked by the door, a dead houseplant, dust on every horizontal surface. Nobody has been in for days and the room has settled into it, flat grey window light, all colour a shade too low. Painterly digital illustration in a muted contemporary-realist register, lit like photography rather than like an illustration. A palette of greyed beige, cold window-white, dull wood-brown and washed-out domestic colour, with no gold and no bioluminescence anywhere. Ordinary modern surfaces, worn and specific -- painted skirting, laminate, a radiator, post on a mat. Nothing is growing. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An ordinary empty room in the waking world, seen from the doorway, a coat still on its hook, unopened post stacked by the door, a dead houseplant, dust on every horizontal surface, nobody has been in for days and the room has settled into it, flat grey window light, all colour a shade too low, painterly digital illustration, muted contemporary realism, photographic lighting, greyed beige and cold window-white palette, dull wood tones, desaturated, ordinary modern interior, worn domestic surfaces, nothing growing, shallow depth of field, cinematic composition, no text, no watermark
```

<details><summary>day (`scenes/mortal-threshold-day.jpg`)</summary>

- **File:** `scenes/mortal-threshold-day.jpg`

**Grok Imagine** (prose)

```text
An ordinary empty room in the waking world, seen from the doorway. Visible detail: a coat still on its hook, unopened post stacked by the door, a dead houseplant, dust on every horizontal surface. The post gone from a stack to a drift, desaturated daylight, warm tones drained out of the wood. Painterly digital illustration in a muted contemporary-realist register, lit like photography rather than like an illustration. A palette of greyed beige, cold window-white, dull wood-brown and washed-out domestic colour, with no gold and no bioluminescence anywhere. Ordinary modern surfaces, worn and specific -- painted skirting, laminate, a radiator, post on a mat. Nothing is growing. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An ordinary empty room in the waking world, seen from the doorway, a coat still on its hook, unopened post stacked by the door, a dead houseplant, dust on every horizontal surface, the post gone from a stack to a drift, desaturated daylight, warm tones drained out of the wood, painterly digital illustration, muted contemporary realism, photographic lighting, greyed beige and cold window-white palette, dull wood tones, desaturated, ordinary modern interior, worn domestic surfaces, nothing growing, shallow depth of field, cinematic composition, no text, no watermark
```

</details>

<details><summary>dusk (`scenes/mortal-threshold-dusk.jpg`)</summary>

- **File:** `scenes/mortal-threshold-dusk.jpg`

**Grok Imagine** (prose)

```text
An ordinary empty room in the waking world, seen from the doorway. Visible detail: a coat still on its hook, unopened post stacked by the door, a dead houseplant, dust on every horizontal surface. The room going dark without anyone turning anything on, streetlight through net curtains, orange and unhelpful. Painterly digital illustration in a muted contemporary-realist register, lit like photography rather than like an illustration. A palette of greyed beige, cold window-white, dull wood-brown and washed-out domestic colour, with no gold and no bioluminescence anywhere. Ordinary modern surfaces, worn and specific -- painted skirting, laminate, a radiator, post on a mat. Nothing is growing. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An ordinary empty room in the waking world, seen from the doorway, a coat still on its hook, unopened post stacked by the door, a dead houseplant, dust on every horizontal surface, the room going dark without anyone turning anything on, streetlight through net curtains, orange and unhelpful, painterly digital illustration, muted contemporary realism, photographic lighting, greyed beige and cold window-white palette, dull wood tones, desaturated, ordinary modern interior, worn domestic surfaces, nothing growing, shallow depth of field, cinematic composition, no text, no watermark
```

</details>

<details><summary>night (`scenes/mortal-threshold-night.jpg`)</summary>

- **File:** `scenes/mortal-threshold-night.jpg`

**Grok Imagine** (prose)

```text
An ordinary empty room in the waking world, seen from the doorway. Visible detail: a coat still on its hook, unopened post stacked by the door, a dead houseplant, dust on every horizontal surface. Black, except that one flower has come up through the floorboards, no light source, a faint rose bioluminescence at floor level. Painterly digital illustration in a muted contemporary-realist register, lit like photography rather than like an illustration. A palette of greyed beige, cold window-white, dull wood-brown and washed-out domestic colour, with no gold and no bioluminescence anywhere. Ordinary modern surfaces, worn and specific -- painted skirting, laminate, a radiator, post on a mat. Nothing is growing. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An ordinary empty room in the waking world, seen from the doorway, a coat still on its hook, unopened post stacked by the door, a dead houseplant, dust on every horizontal surface, black, except that one flower has come up through the floorboards, no light source, a faint rose bioluminescence at floor level, painterly digital illustration, muted contemporary realism, photographic lighting, greyed beige and cold window-white palette, dull wood tones, desaturated, ordinary modern interior, worn domestic surfaces, nothing growing, shallow depth of field, cinematic composition, no text, no watermark
```

</details>

---

### `path_first_petals`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/path-first-petals-dawn.jpg`

**Grok Imagine** (prose)

```text
A narrow path of white petals through leaning trees. Visible detail: petals laid ahead and absent behind, trees inclined inward as if listening, a single pale glass moth in the air. The petals wet, the path uncertain more than ten paces ahead, silver pre-dawn under canopy, everything low-contrast. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A narrow path of white petals through leaning trees, petals laid ahead and absent behind, trees inclined inward as if listening, a single pale glass moth in the air, the petals wet, the path uncertain more than ten paces ahead, silver pre-dawn under canopy, everything low-contrast, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

<details><summary>day (`scenes/path-first-petals-day.jpg`)</summary>

- **File:** `scenes/path-first-petals-day.jpg`

**Grok Imagine** (prose)

```text
A narrow path of white petals through leaning trees. Visible detail: petals laid ahead and absent behind, trees inclined inward as if listening, a single pale glass moth in the air. God rays through the leaves with pollen turning in them, magic hour under canopy, dust and pollen as glitter. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A narrow path of white petals through leaning trees, petals laid ahead and absent behind, trees inclined inward as if listening, a single pale glass moth in the air, god rays through the leaves with pollen turning in them, magic hour under canopy, dust and pollen as glitter, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

</details>

<details><summary>dusk (`scenes/path-first-petals-dusk.jpg`)</summary>

- **File:** `scenes/path-first-petals-dusk.jpg`

**Grok Imagine** (prose)

```text
A narrow path of white petals through leaning trees. Visible detail: petals laid ahead and absent behind, trees inclined inward as if listening, a single pale glass moth in the air. The moth landing, its wings showing a calendar coming apart, gold going to rose, long shadows off the leaning trunks. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A narrow path of white petals through leaning trees, petals laid ahead and absent behind, trees inclined inward as if listening, a single pale glass moth in the air, the moth landing, its wings showing a calendar coming apart, gold going to rose, long shadows off the leaning trunks, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

</details>

<details><summary>night (`scenes/path-first-petals-night.jpg`)</summary>

- **File:** `scenes/path-first-petals-night.jpg`

**Grok Imagine** (prose)

```text
A narrow path of white petals through leaning trees. Visible detail: petals laid ahead and absent behind, trees inclined inward as if listening, a single pale glass moth in the air. The petals faintly luminous and the trees closer together than they were, moonlight silver, ghost-teal at the path edges. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A narrow path of white petals through leaning trees, petals laid ahead and absent behind, trees inclined inward as if listening, a single pale glass moth in the air, the petals faintly luminous and the trees closer together than they were, moonlight silver, ghost-teal at the path edges, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

</details>

---

### `aviary_unsent`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/aviary-unsent-dawn.jpg`

**Grok Imagine** (prose)

```text
The interior of a great domed aviary of wire and briar, full of paper birds. Visible detail: folded paper birds in the hundreds, none of them settling, ink showing through the folds, a wire floor thick with the ones that fell. The birds quiet and low, drifting rather than flying, cold light down through the dome, dust in the beams. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
The interior of a great domed aviary of wire and briar, full of paper birds, folded paper birds in the hundreds, none of them settling, ink showing through the folds, a wire floor thick with the ones that fell, the birds quiet and low, drifting rather than flying, cold light down through the dome, dust in the beams, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

<details><summary>day (`scenes/aviary-unsent-day.jpg`)</summary>

- **File:** `scenes/aviary-unsent-day.jpg`

**Grok Imagine** (prose)

```text
The interior of a great domed aviary of wire and briar, full of paper birds. Visible detail: folded paper birds in the hundreds, none of them settling, ink showing through the folds, a wire floor thick with the ones that fell. The whole flock in the air at once and none of it landing, flat white daylight through wire, hard shadows on the floor. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
The interior of a great domed aviary of wire and briar, full of paper birds, folded paper birds in the hundreds, none of them settling, ink showing through the folds, a wire floor thick with the ones that fell, the whole flock in the air at once and none of it landing, flat white daylight through wire, hard shadows on the floor, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

</details>

<details><summary>dusk (`scenes/aviary-unsent-dusk.jpg`)</summary>

- **File:** `scenes/aviary-unsent-dusk.jpg`

**Grok Imagine** (prose)

```text
The interior of a great domed aviary of wire and briar, full of paper birds. Visible detail: folded paper birds in the hundreds, none of them settling, ink showing through the folds, a wire floor thick with the ones that fell. One bird at the dome's apex trying the same gap repeatedly, gold through the briar lattice, the floor already dark. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
The interior of a great domed aviary of wire and briar, full of paper birds, folded paper birds in the hundreds, none of them settling, ink showing through the folds, a wire floor thick with the ones that fell, one bird at the dome's apex trying the same gap repeatedly, gold through the briar lattice, the floor already dark, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

</details>

<details><summary>night (`scenes/aviary-unsent-night.jpg`)</summary>

- **File:** `scenes/aviary-unsent-night.jpg`

**Grok Imagine** (prose)

```text
The interior of a great domed aviary of wire and briar, full of paper birds. Visible detail: folded paper birds in the hundreds, none of them settling, ink showing through the folds, a wire floor thick with the ones that fell. Still, and the ink faintly luminous through the paper, no source, a pale glow off the folded pages. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
The interior of a great domed aviary of wire and briar, full of paper birds, folded paper birds in the hundreds, none of them settling, ink showing through the folds, a wire floor thick with the ones that fell, still, and the ink faintly luminous through the paper, no source, a pale glow off the folded pages, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

</details>

---

### `night_market`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/night-market-dawn.jpg`

**Grok Imagine** (prose)

```text
A market of small strange stalls between two hedges at night. Visible detail: vendors the size of children's toys and the size of doors, wares that are appetites rather than objects, lit by things that are not lamps. The hedges gone back to being two hedges, nothing left but flattened grass, grey, ordinary, and disappointing. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A market of small strange stalls between two hedges at night, vendors the size of children's toys and the size of doors, wares that are appetites rather than objects, lit by things that are not lamps, the hedges gone back to being two hedges, nothing left but flattened grass, grey, ordinary, and disappointing, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

<details><summary>day (`scenes/night-market-day.jpg`)</summary>

- **File:** `scenes/night-market-day.jpg`

**Grok Imagine** (prose)

```text
A market of small strange stalls between two hedges at night. Visible detail: vendors the size of children's toys and the size of doors, wares that are appetites rather than objects, lit by things that are not lamps. Shut, and the gap between the hedges narrower than a body, green daylight, nothing worth looking at. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A market of small strange stalls between two hedges at night, vendors the size of children's toys and the size of doors, wares that are appetites rather than objects, lit by things that are not lamps, shut, and the gap between the hedges narrower than a body, green daylight, nothing worth looking at, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

</details>

<details><summary>dusk (`scenes/night-market-dusk.jpg`)</summary>

- **File:** `scenes/night-market-dusk.jpg`

**Grok Imagine** (prose)

```text
A market of small strange stalls between two hedges at night. Visible detail: vendors the size of children's toys and the size of doors, wares that are appetites rather than objects, lit by things that are not lamps. The stalls coming up in an order, the lights lit one by one, biolume teal and rose, the sky still blue behind. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A market of small strange stalls between two hedges at night, vendors the size of children's toys and the size of doors, wares that are appetites rather than objects, lit by things that are not lamps, the stalls coming up in an order, the lights lit one by one, biolume teal and rose, the sky still blue behind, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

</details>

<details><summary>night (`scenes/night-market-night.jpg`)</summary>

- **File:** `scenes/night-market-night.jpg`

**Grok Imagine** (prose)

```text
A market of small strange stalls between two hedges at night. Visible detail: vendors the size of children's toys and the size of doors, wares that are appetites rather than objects, lit by things that are not lamps. The market at full trade, prices being quoted in years, ghost teal and thorn-gold, no two stalls lit the same colour. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A market of small strange stalls between two hedges at night, vendors the size of children's toys and the size of doors, wares that are appetites rather than objects, lit by things that are not lamps, the market at full trade, prices being quoted in years, ghost teal and thorn-gold, no two stalls lit the same colour, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

</details>

---

### `briar_deep`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/briar-deep-dawn.jpg`

**Grok Imagine** (prose)

```text
An under-root cathedral with no far wall, roots the size of towers. Visible detail: root columns going up out of frame, roses growing on them at every height, a vast face half-arranged out of the mass, more hands than there were. The face not assembled, the roots merely roots, amber sap light from below, everything backlit and enormous. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An under-root cathedral with no far wall, roots the size of towers, root columns going up out of frame, roses growing on them at every height, a vast face half-arranged out of the mass, more hands than there were, the face not assembled, the roots merely roots, amber sap light from below, everything backlit and enormous, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

<details><summary>day (`scenes/briar-deep-day.jpg`)</summary>

- **File:** `scenes/briar-deep-day.jpg`

**Grok Imagine** (prose)

```text
An under-root cathedral with no far wall, roots the size of towers. Visible detail: root columns going up out of frame, roses growing on them at every height, a vast face half-arranged out of the mass, more hands than there were. The scale visible, the far wall genuinely absent, no daylight, warm root-light coming up through the floor. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An under-root cathedral with no far wall, roots the size of towers, root columns going up out of frame, roses growing on them at every height, a vast face half-arranged out of the mass, more hands than there were, the scale visible, the far wall genuinely absent, no daylight, warm root-light coming up through the floor, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

</details>

<details><summary>dusk (`scenes/briar-deep-dusk.jpg`)</summary>

- **File:** `scenes/briar-deep-dusk.jpg`

**Grok Imagine** (prose)

```text
An under-root cathedral with no far wall, roots the size of towers. Visible detail: root columns going up out of frame, roses growing on them at every height, a vast face half-arranged out of the mass, more hands than there were. The face coming together and taking an interest, underlighting from the roots, eyes catching the light last. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An under-root cathedral with no far wall, roots the size of towers, root columns going up out of frame, roses growing on them at every height, a vast face half-arranged out of the mass, more hands than there were, the face coming together and taking an interest, underlighting from the roots, eyes catching the light last, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

</details>

<details><summary>night (`scenes/briar-deep-night.jpg`)</summary>

- **File:** `scenes/briar-deep-night.jpg`

**Grok Imagine** (prose)

```text
An under-root cathedral with no far wall, roots the size of towers. Visible detail: root columns going up out of frame, roses growing on them at every height, a vast face half-arranged out of the mass, more hands than there were. The floor moving very slightly, in time, deep amber and rot-purple, one bloom lit like an eye. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An under-root cathedral with no far wall, roots the size of towers, root columns going up out of frame, roses growing on them at every height, a vast face half-arranged out of the mass, more hands than there were, the floor moving very slightly, in time, deep amber and rot-purple, one bloom lit like an eye, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

</details>

---

### `unknown`

- **Size:** 1280x720

The fallback plate for any location with no art of its own, which is why it reads as a void. Generating this one first is the cheapest way to stop the procedural silhouette appearing anywhere — it covers the other five until they exist. Also on the **`mortal`** variant: this place is defined by having no botany in it yet.

#### dawn

- **File:** `scenes/unknown-dawn.jpg`

**Grok Imagine** (prose)

```text
A figure standing in a place with no architecture and no horizon. Visible detail: light with no source, ground with no texture, a suggestion of petals at the very edge of the frame that resolves into nothing. No scale, no distance, no way to tell which way is out, even ambient light from nowhere, no shadows at all. Painterly digital illustration in a muted contemporary-realist register, lit like photography rather than like an illustration. A palette of greyed beige, cold window-white, dull wood-brown and washed-out domestic colour, with no gold and no bioluminescence anywhere. Ordinary modern surfaces, worn and specific -- painted skirting, laminate, a radiator, post on a mat. Nothing is growing. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A figure standing in a place with no architecture and no horizon, light with no source, ground with no texture, a suggestion of petals at the very edge of the frame that resolves into nothing, no scale, no distance, no way to tell which way is out, even ambient light from nowhere, no shadows at all, painterly digital illustration, muted contemporary realism, photographic lighting, greyed beige and cold window-white palette, dull wood tones, desaturated, ordinary modern interior, worn domestic surfaces, nothing growing, shallow depth of field, cinematic composition, no text, no watermark
```

<details><summary>day (`scenes/unknown-day.jpg`)</summary>

- **File:** `scenes/unknown-day.jpg`

**Grok Imagine** (prose)

```text
A figure standing in a place with no architecture and no horizon. Visible detail: light with no source, ground with no texture, a suggestion of petals at the very edge of the frame that resolves into nothing. The same, and the sameness has begun to be the point, flat white void, faint rose at the extreme edges. Painterly digital illustration in a muted contemporary-realist register, lit like photography rather than like an illustration. A palette of greyed beige, cold window-white, dull wood-brown and washed-out domestic colour, with no gold and no bioluminescence anywhere. Ordinary modern surfaces, worn and specific -- painted skirting, laminate, a radiator, post on a mat. Nothing is growing. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A figure standing in a place with no architecture and no horizon, light with no source, ground with no texture, a suggestion of petals at the very edge of the frame that resolves into nothing, the same, and the sameness has begun to be the point, flat white void, faint rose at the extreme edges, painterly digital illustration, muted contemporary realism, photographic lighting, greyed beige and cold window-white palette, dull wood tones, desaturated, ordinary modern interior, worn domestic surfaces, nothing growing, shallow depth of field, cinematic composition, no text, no watermark
```

</details>

<details><summary>dusk (`scenes/unknown-dusk.jpg`)</summary>

- **File:** `scenes/unknown-dusk.jpg`

**Grok Imagine** (prose)

```text
A figure standing in a place with no architecture and no horizon. Visible detail: light with no source, ground with no texture, a suggestion of petals at the very edge of the frame that resolves into nothing. Something at the periphery deciding what this place will be, colour bleeding in from the edges of the frame inward. Painterly digital illustration in a muted contemporary-realist register, lit like photography rather than like an illustration. A palette of greyed beige, cold window-white, dull wood-brown and washed-out domestic colour, with no gold and no bioluminescence anywhere. Ordinary modern surfaces, worn and specific -- painted skirting, laminate, a radiator, post on a mat. Nothing is growing. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A figure standing in a place with no architecture and no horizon, light with no source, ground with no texture, a suggestion of petals at the very edge of the frame that resolves into nothing, something at the periphery deciding what this place will be, colour bleeding in from the edges of the frame inward, painterly digital illustration, muted contemporary realism, photographic lighting, greyed beige and cold window-white palette, dull wood tones, desaturated, ordinary modern interior, worn domestic surfaces, nothing growing, shallow depth of field, cinematic composition, no text, no watermark
```

</details>

<details><summary>night (`scenes/unknown-night.jpg`)</summary>

- **File:** `scenes/unknown-night.jpg`

**Grok Imagine** (prose)

```text
A figure standing in a place with no architecture and no horizon. Visible detail: light with no source, ground with no texture, a suggestion of petals at the very edge of the frame that resolves into nothing. The ground beginning to have a smell of soil, near black with a warm suggestion underneath it. Painterly digital illustration in a muted contemporary-realist register, lit like photography rather than like an illustration. A palette of greyed beige, cold window-white, dull wood-brown and washed-out domestic colour, with no gold and no bioluminescence anywhere. Ordinary modern surfaces, worn and specific -- painted skirting, laminate, a radiator, post on a mat. Nothing is growing. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A figure standing in a place with no architecture and no horizon, light with no source, ground with no texture, a suggestion of petals at the very edge of the frame that resolves into nothing, the ground beginning to have a smell of soil, near black with a warm suggestion underneath it, painterly digital illustration, muted contemporary realism, photographic lighting, greyed beige and cold window-white palette, dull wood tones, desaturated, ordinary modern interior, worn domestic surfaces, nothing growing, shallow depth of field, cinematic composition, no text, no watermark
```

</details>

---

## Portraits (1)

### `court_generic`

- **File:** `portraits/court-generic.jpg`
- **Size:** 768x1024

A crowd plate, used wherever a named courtier is not on screen. Faces at mid-distance rather than a hero portrait, so it can sit behind dialogue without any one figure claiming to be somebody.

**Grok Imagine** (prose)

```text
A group of adult fae courtiers in botanical couture, arranged to be looked at. Visible detail: living fabric that grows and jewellery that has rooted, too-sharp smiles, shadows that lag very slightly behind their owners. The heart grove at dusk, hanging silk and lantern-moths, mid-figure of a dance, beautiful, bored, and taking notes. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A group of adult fae courtiers in botanical couture, arranged to be looked at, living fabric that grows and jewellery that has rooted, too-sharp smiles, shadows that lag very slightly behind their owners, the heart grove at dusk, hanging silk and lantern-moths, mid-figure of a dance, beautiful, bored, and taking notes, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

---

## Items (1)

### `sap_sketch`

- **File:** `items/sap-sketch.jpg`
- **Size:** 768x1024

**Grok Imagine** (prose)

```text
A fast charcoal sketch of a face, on a rough torn sheet. Visible detail: the mouth clearly wrong and the eyes exactly right, charcoal smudged by a thumb, one drop of amber sap dried on the corner of the paper. The single object alone at the centre of the frame, laid on deep plum-black velvet, reliquary still-life, nothing else in the frame, no hands and no figure, hero-lit from the upper left with a warm rose key and a ghost-teal rim, soft vignette falling to plum-black at the edges, a faint dust of pollen in the air, painterly reliquary photography. Painterly digital illustration in a Pre-Raphaelite dark-romantic register, semi-realistic figures with tactile skin and heavy fabric, lit like photography rather than like an illustration. A palette of plum-black shadow, deep poison green, crimson rose, antique thorn-gold and pale lilac-silver, with ghost-teal bioluminescence in the night flora. Lush organic forms everywhere -- vines, petals, pollen, dew, silk, moth wings -- and one detail in every frame that is beautiful and slightly wrong. Cinematic framing with shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A fast charcoal sketch of a face, on a rough torn sheet, the mouth clearly wrong and the eyes exactly right, charcoal smudged by a thumb, one drop of amber sap dried on the corner of the paper, the single object alone at the centre of the frame, laid on deep plum-black velvet, reliquary still-life, nothing else in the frame, no hands and no figure, hero-lit from the upper left with a warm rose key and a ghost-teal rim, soft vignette falling to plum-black at the edges, a faint dust of pollen in the air, painterly reliquary photography, painterly digital illustration, pre-raphaelite dark romantic fantasy, semi-realistic adult figures, tactile skin and heavy fabric, photographic lighting, plum-black and poison-emerald palette, crimson rose accents, antique thorn-gold, pale lilac-silver, ghost-teal bioluminescence, living vines and petals, pollen and dew in the air, botanical art nouveau, shallow depth of field, cinematic composition, one beautiful wrong detail, no text, no watermark
```

---

## LoRA hints

From `subjects.yaml` `style.loras`. ComfyUI only; Grok ignores them.

```yaml
- name: Oil_Painting_Style
  weight: 0.55
- name: Botanical_Fantasy
  weight: 0.5
- name: Cinematic_Portrait
  weight: 0.35
```

## Manifest block to paste

```yaml
locations:
  mortal_threshold:
    times:
      dawn: scenes/mortal-threshold-dawn.jpg
      day: scenes/mortal-threshold-day.jpg
      dusk: scenes/mortal-threshold-dusk.jpg
      night: scenes/mortal-threshold-night.jpg
  path_first_petals:
    times:
      dawn: scenes/path-first-petals-dawn.jpg
      day: scenes/path-first-petals-day.jpg
      dusk: scenes/path-first-petals-dusk.jpg
      night: scenes/path-first-petals-night.jpg
  aviary_unsent:
    times:
      dawn: scenes/aviary-unsent-dawn.jpg
      day: scenes/aviary-unsent-day.jpg
      dusk: scenes/aviary-unsent-dusk.jpg
      night: scenes/aviary-unsent-night.jpg
  night_market:
    times:
      dawn: scenes/night-market-dawn.jpg
      day: scenes/night-market-day.jpg
      dusk: scenes/night-market-dusk.jpg
      night: scenes/night-market-night.jpg
  briar_deep:
    times:
      dawn: scenes/briar-deep-dawn.jpg
      day: scenes/briar-deep-day.jpg
      dusk: scenes/briar-deep-dusk.jpg
      night: scenes/briar-deep-night.jpg
  unknown:
    times:
      dawn: scenes/unknown-dawn.jpg
      day: scenes/unknown-day.jpg
      dusk: scenes/unknown-dusk.jpg
      night: scenes/unknown-night.jpg
portraits:
  court_generic: portraits/court-generic.jpg
items:
  sap_sketch: items/sap-sketch.jpg
```
