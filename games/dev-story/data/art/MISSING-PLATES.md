# Missing plates — Dev Story

12 subject(s) are authored in `subjects.yaml` and have no image in
`plates/`, so each falls through the resolution chain to the procedural
silhouette.

**Generated, not written.** Every prompt below is the output of
`engine.media.art.render_prose` / `render_tags` against the shipped
`subjects.yaml`, so it is exactly what the live pipeline would send — not a
fourth copy of the art voice free to drift from the three that ship. After
editing a subject, re-run the generator rather than editing the prompts here:

```powershell
.\.venv\Scripts\python.exe scripts\art_missing.py --game dev-story
```

## Order to work in

Any order. None of these is a fallback plate or the entry location, so
each one only shows up if the player goes there.

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

`scripts/generate_art.py --game dev-story --promote` writes each plate the
generator made into `manifest.yaml` itself. For a plate made by hand, add it
under its kind: a location's plates go under `times: {<daypart>: ...}` (or
`base:` for a location whose subject declares no `times:` -- note that a
`base:` then answers every daypart); portraits and items take a bare path.
Paths are relative to `paths.art_root`. The ready-to-paste block is at the
bottom.

---

## Locations (12)

### `hallway`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/hallway-dawn.jpg`

**Grok Imagine** (prose)

```text
The hallway of an ordinary house. Visible detail: coats on hooks, shoes not quite paired, a radiator, doors standing open onto other rooms, a light switch worn pale. Nobody through it yet, grey from the frosted panel in the front door. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
The hallway of an ordinary house, coats on hooks, shoes not quite paired, a radiator, doors standing open onto other rooms, a light switch worn pale, nobody through it yet, grey from the frosted panel in the front door, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

<details><summary>day (`scenes/hallway-day.jpg`)</summary>

- **File:** `scenes/hallway-day.jpg`

**Grok Imagine** (prose)

```text
The hallway of an ordinary house. Visible detail: coats on hooks, shoes not quite paired, a radiator, doors standing open onto other rooms, a light switch worn pale. A bag dropped where somebody stopped to answer their phone, flat daylight from both ends. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
The hallway of an ordinary house, coats on hooks, shoes not quite paired, a radiator, doors standing open onto other rooms, a light switch worn pale, a bag dropped where somebody stopped to answer their phone, flat daylight from both ends, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>dusk (`scenes/hallway-dusk.jpg`)</summary>

- **File:** `scenes/hallway-dusk.jpg`

**Grok Imagine** (prose)

```text
The hallway of an ordinary house. Visible detail: coats on hooks, shoes not quite paired, a radiator, doors standing open onto other rooms, a light switch worn pale. The overhead on because the hall has no window worth the name, warm overhead, the doorways darker. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
The hallway of an ordinary house, coats on hooks, shoes not quite paired, a radiator, doors standing open onto other rooms, a light switch worn pale, the overhead on because the hall has no window worth the name, warm overhead, the doorways darker, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>night (`scenes/hallway-night.jpg`)</summary>

- **File:** `scenes/hallway-night.jpg`

**Grok Imagine** (prose)

```text
The hallway of an ordinary house. Visible detail: coats on hooks, shoes not quite paired, a radiator, doors standing open onto other rooms, a light switch worn pale. One lamp left on for whoever is still out, low, yellow, the far end unlit. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
The hallway of an ordinary house, coats on hooks, shoes not quite paired, a radiator, doors standing open onto other rooms, a light switch worn pale, one lamp left on for whoever is still out, low, yellow, the far end unlit, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

---

### `bathroom`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/bathroom-dawn.jpg`

**Grok Imagine** (prose)

```text
A small domestic bathroom. Visible detail: a mirror with a damp patch cleared in it, tiles, a towel over the radiator, too many bottles on the ledge. Still humid from someone earlier, the extractor fan light, cold and mean. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A small domestic bathroom, a mirror with a damp patch cleared in it, tiles, a towel over the radiator, too many bottles on the ledge, still humid from someone earlier, the extractor fan light, cold and mean, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

<details><summary>day (`scenes/bathroom-day.jpg`)</summary>

- **File:** `scenes/bathroom-day.jpg`

**Grok Imagine** (prose)

```text
A small domestic bathroom. Visible detail: a mirror with a damp patch cleared in it, tiles, a towel over the radiator, too many bottles on the ledge. Dry and blank, daylight through frosted glass. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A small domestic bathroom, a mirror with a damp patch cleared in it, tiles, a towel over the radiator, too many bottles on the ledge, dry and blank, daylight through frosted glass, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>dusk (`scenes/bathroom-dusk.jpg`)</summary>

- **File:** `scenes/bathroom-dusk.jpg`

**Grok Imagine** (prose)

```text
A small domestic bathroom. Visible detail: a mirror with a damp patch cleared in it, tiles, a towel over the radiator, too many bottles on the ledge. The mirror fogged at the edges, overhead, unflattering. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A small domestic bathroom, a mirror with a damp patch cleared in it, tiles, a towel over the radiator, too many bottles on the ledge, the mirror fogged at the edges, overhead, unflattering, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>night (`scenes/bathroom-night.jpg`)</summary>

- **File:** `scenes/bathroom-night.jpg`

**Grok Imagine** (prose)

```text
A small domestic bathroom. Visible detail: a mirror with a damp patch cleared in it, tiles, a towel over the radiator, too many bottles on the ledge. The light left on by accident, a single hard overhead. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A small domestic bathroom, a mirror with a damp patch cleared in it, tiles, a towel over the radiator, too many bottles on the ledge, the light left on by accident, a single hard overhead, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

---

### `kitchen`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/kitchen-dawn.jpg`

**Grok Imagine** (prose)

```text
A domestic kitchen with the everyday mess left in it. Visible detail: mugs by the sink, a kettle, a noticeboard, a chair pulled out at an angle, a window over the worktop. The kettle just boiled and nobody in the room, early grey, the overhead not on yet. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A domestic kitchen with the everyday mess left in it, mugs by the sink, a kettle, a noticeboard, a chair pulled out at an angle, a window over the worktop, the kettle just boiled and nobody in the room, early grey, the overhead not on yet, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

<details><summary>day (`scenes/kitchen-day.jpg`)</summary>

- **File:** `scenes/kitchen-day.jpg`

**Grok Imagine** (prose)

```text
A domestic kitchen with the everyday mess left in it. Visible detail: mugs by the sink, a kettle, a noticeboard, a chair pulled out at an angle, a window over the worktop. Somebody eating standing up, daylight from the window over the sink. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A domestic kitchen with the everyday mess left in it, mugs by the sink, a kettle, a noticeboard, a chair pulled out at an angle, a window over the worktop, somebody eating standing up, daylight from the window over the sink, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>dusk (`scenes/kitchen-dusk.jpg`)</summary>

- **File:** `scenes/kitchen-dusk.jpg`

**Grok Imagine** (prose)

```text
A domestic kitchen with the everyday mess left in it. Visible detail: mugs by the sink, a kettle, a noticeboard, a chair pulled out at an angle, a window over the worktop. The overhead on and the window gone black, warm overhead against a dark window. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A domestic kitchen with the everyday mess left in it, mugs by the sink, a kettle, a noticeboard, a chair pulled out at an angle, a window over the worktop, the overhead on and the window gone black, warm overhead against a dark window, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>night (`scenes/kitchen-night.jpg`)</summary>

- **File:** `scenes/kitchen-night.jpg`

**Grok Imagine** (prose)

```text
A domestic kitchen with the everyday mess left in it. Visible detail: mugs by the sink, a kettle, a noticeboard, a chair pulled out at an angle, a window over the worktop. One light over the hob, the rest dark, a single low source. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A domestic kitchen with the everyday mess left in it, mugs by the sink, a kettle, a noticeboard, a chair pulled out at an angle, a window over the worktop, one light over the hob, the rest dark, a single low source, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

---

### `living_room`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/living-room-dawn.jpg`

**Grok Imagine** (prose)

```text
An ordinary living room. Visible detail: a sofa with a throw pulled crooked, a low table with rings on it, a television nobody is watching, a lamp in the corner. Curtains still shut, the little that gets past the curtains. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An ordinary living room, a sofa with a throw pulled crooked, a low table with rings on it, a television nobody is watching, a lamp in the corner, curtains still shut, the little that gets past the curtains, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

<details><summary>day (`scenes/living-room-day.jpg`)</summary>

- **File:** `scenes/living-room-day.jpg`

**Grok Imagine** (prose)

```text
An ordinary living room. Visible detail: a sofa with a throw pulled crooked, a low table with rings on it, a television nobody is watching, a lamp in the corner. Curtains open, the room honest about its wear, flat daylight. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An ordinary living room, a sofa with a throw pulled crooked, a low table with rings on it, a television nobody is watching, a lamp in the corner, curtains open, the room honest about its wear, flat daylight, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>dusk (`scenes/living-room-dusk.jpg`)</summary>

- **File:** `scenes/living-room-dusk.jpg`

**Grok Imagine** (prose)

```text
An ordinary living room. Visible detail: a sofa with a throw pulled crooked, a low table with rings on it, a television nobody is watching, a lamp in the corner. Lamps on, the room suddenly warmer than it is, two lamps, no overhead. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An ordinary living room, a sofa with a throw pulled crooked, a low table with rings on it, a television nobody is watching, a lamp in the corner, lamps on, the room suddenly warmer than it is, two lamps, no overhead, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>night (`scenes/living-room-night.jpg`)</summary>

- **File:** `scenes/living-room-night.jpg`

**Grok Imagine** (prose)

```text
An ordinary living room. Visible detail: a sofa with a throw pulled crooked, a low table with rings on it, a television nobody is watching, a lamp in the corner. The television the only thing lit, screen light, blue and moving. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
An ordinary living room, a sofa with a throw pulled crooked, a low table with rings on it, a television nobody is watching, a lamp in the corner, the television the only thing lit, screen light, blue and moving, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

---

### `front_porch`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/front-porch-dawn.jpg`

**Grok Imagine** (prose)

```text
The front step of an ordinary house, looking out. Visible detail: a door that sticks, a mat, a bin at the corner of the path, the street beyond and the campus buildings past it. Nobody on the street yet, cold early light, long shadows. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
The front step of an ordinary house, looking out, a door that sticks, a mat, a bin at the corner of the path, the street beyond and the campus buildings past it, nobody on the street yet, cold early light, long shadows, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

<details><summary>day (`scenes/front-porch-day.jpg`)</summary>

- **File:** `scenes/front-porch-day.jpg`

**Grok Imagine** (prose)

```text
The front step of an ordinary house, looking out. Visible detail: a door that sticks, a mat, a bin at the corner of the path, the street beyond and the campus buildings past it. The walk to campus visible past the gate, plain daylight. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
The front step of an ordinary house, looking out, a door that sticks, a mat, a bin at the corner of the path, the street beyond and the campus buildings past it, the walk to campus visible past the gate, plain daylight, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>dusk (`scenes/front-porch-dusk.jpg`)</summary>

- **File:** `scenes/front-porch-dusk.jpg`

**Grok Imagine** (prose)

```text
The front step of an ordinary house, looking out. Visible detail: a door that sticks, a mat, a bin at the corner of the path, the street beyond and the campus buildings past it. The street lights coming on before they are needed, orange sodium against the last of the blue. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
The front step of an ordinary house, looking out, a door that sticks, a mat, a bin at the corner of the path, the street beyond and the campus buildings past it, the street lights coming on before they are needed, orange sodium against the last of the blue, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>night (`scenes/front-porch-night.jpg`)</summary>

- **File:** `scenes/front-porch-night.jpg`

**Grok Imagine** (prose)

```text
The front step of an ordinary house, looking out. Visible detail: a door that sticks, a mat, a bin at the corner of the path, the street beyond and the campus buildings past it. The porch light on, the street empty, one bulb over the door, everything past it dark. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
The front step of an ordinary house, looking out, a door that sticks, a mat, a bin at the corner of the path, the street beyond and the campus buildings past it, the porch light on, the street empty, one bulb over the door, everything past it dark, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

---

### `quad`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/quad-dawn.jpg`

**Grok Imagine** (prose)

```text
A university quad between buildings. Visible detail: wet paving, a strip of grass nobody walks on, bike racks, a noticeboard with too many pins, students crossing at angles. Empty, still wet from overnight, flat early grey. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university quad between buildings, wet paving, a strip of grass nobody walks on, bike racks, a noticeboard with too many pins, students crossing at angles, empty, still wet from overnight, flat early grey, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

<details><summary>day (`scenes/quad-day.jpg`)</summary>

- **File:** `scenes/quad-day.jpg`

**Grok Imagine** (prose)

```text
A university quad between buildings. Visible detail: wet paving, a strip of grass nobody walks on, bike racks, a noticeboard with too many pins, students crossing at angles. Full, everyone crossing to somewhere else, open daylight, no shelter. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university quad between buildings, wet paving, a strip of grass nobody walks on, bike racks, a noticeboard with too many pins, students crossing at angles, full, everyone crossing to somewhere else, open daylight, no shelter, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>dusk (`scenes/quad-dusk.jpg`)</summary>

- **File:** `scenes/quad-dusk.jpg`

**Grok Imagine** (prose)

```text
A university quad between buildings. Visible detail: wet paving, a strip of grass nobody walks on, bike racks, a noticeboard with too many pins, students crossing at angles. Thinning out, the windows brighter than the sky, lit windows against a darkening quad. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university quad between buildings, wet paving, a strip of grass nobody walks on, bike racks, a noticeboard with too many pins, students crossing at angles, thinning out, the windows brighter than the sky, lit windows against a darkening quad, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>night (`scenes/quad-night.jpg`)</summary>

- **File:** `scenes/quad-night.jpg`

**Grok Imagine** (prose)

```text
A university quad between buildings. Visible detail: wet paving, a strip of grass nobody walks on, bike racks, a noticeboard with too many pins, students crossing at angles. Empty except the lights on the paths, pooled lamplight, the middle dark. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university quad between buildings, wet paving, a strip of grass nobody walks on, bike racks, a noticeboard with too many pins, students crossing at angles, empty except the lights on the paths, pooled lamplight, the middle dark, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

---

### `admin_block`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/admin-block-dawn.jpg`

**Grok Imagine** (prose)

```text
A university administration corridor and counter. Visible detail: a counter with a bell nobody rings twice, laminated notices, a queue rail, closed office doors with names on them. Shutters still down on the counter, corridor strips only. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university administration corridor and counter, a counter with a bell nobody rings twice, laminated notices, a queue rail, closed office doors with names on them, shutters still down on the counter, corridor strips only, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

<details><summary>day (`scenes/admin-block-day.jpg`)</summary>

- **File:** `scenes/admin-block-day.jpg`

**Grok Imagine** (prose)

```text
A university administration corridor and counter. Visible detail: a counter with a bell nobody rings twice, laminated notices, a queue rail, closed office doors with names on them. Somebody ahead of you in the queue, hard fluorescent, no windows worth the name. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university administration corridor and counter, a counter with a bell nobody rings twice, laminated notices, a queue rail, closed office doors with names on them, somebody ahead of you in the queue, hard fluorescent, no windows worth the name, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>dusk (`scenes/admin-block-dusk.jpg`)</summary>

- **File:** `scenes/admin-block-dusk.jpg`

**Grok Imagine** (prose)

```text
A university administration corridor and counter. Visible detail: a counter with a bell nobody rings twice, laminated notices, a queue rail, closed office doors with names on them. The counter closing, one light left over it, one strip on, the rest off. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university administration corridor and counter, a counter with a bell nobody rings twice, laminated notices, a queue rail, closed office doors with names on them, the counter closing, one light left over it, one strip on, the rest off, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>night (`scenes/admin-block-night.jpg`)</summary>

- **File:** `scenes/admin-block-night.jpg`

**Grok Imagine** (prose)

```text
A university administration corridor and counter. Visible detail: a counter with a bell nobody rings twice, laminated notices, a queue rail, closed office doors with names on them. Locked, dark, a green exit sign, exit-sign green and nothing else. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university administration corridor and counter, a counter with a bell nobody rings twice, laminated notices, a queue rail, closed office doors with names on them, locked, dark, a green exit sign, exit-sign green and nothing else, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

---

### `cafeteria`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/cafeteria-dawn.jpg`

**Grok Imagine** (prose)

```text
A university cafeteria at the serving line. Visible detail: steel counters, trays stacked, a hot cabinet, tables in rows, chairs pushed in wrong. Chairs still up on the tables, half the strips on. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university cafeteria at the serving line, steel counters, trays stacked, a hot cabinet, tables in rows, chairs pushed in wrong, chairs still up on the tables, half the strips on, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

<details><summary>day (`scenes/cafeteria-day.jpg`)</summary>

- **File:** `scenes/cafeteria-day.jpg`

**Grok Imagine** (prose)

```text
A university cafeteria at the serving line. Visible detail: steel counters, trays stacked, a hot cabinet, tables in rows, chairs pushed in wrong. The line moving, every table taken, full fluorescent, steam over the counter. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university cafeteria at the serving line, steel counters, trays stacked, a hot cabinet, tables in rows, chairs pushed in wrong, the line moving, every table taken, full fluorescent, steam over the counter, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>dusk (`scenes/cafeteria-dusk.jpg`)</summary>

- **File:** `scenes/cafeteria-dusk.jpg`

**Grok Imagine** (prose)

```text
A university cafeteria at the serving line. Visible detail: steel counters, trays stacked, a hot cabinet, tables in rows, chairs pushed in wrong. The last of the food and most of the tables empty, strips over the counter, the room dimmer. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university cafeteria at the serving line, steel counters, trays stacked, a hot cabinet, tables in rows, chairs pushed in wrong, the last of the food and most of the tables empty, strips over the counter, the room dimmer, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>night (`scenes/cafeteria-night.jpg`)</summary>

- **File:** `scenes/cafeteria-night.jpg`

**Grok Imagine** (prose)

```text
A university cafeteria at the serving line. Visible detail: steel counters, trays stacked, a hot cabinet, tables in rows, chairs pushed in wrong. Wiped down and shut, one row of lights left on. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university cafeteria at the serving line, steel counters, trays stacked, a hot cabinet, tables in rows, chairs pushed in wrong, wiped down and shut, one row of lights left on, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

---

### `dorm_room`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/dorm-room-dawn.jpg`

**Grok Imagine** (prose)

```text
A student dorm room. Visible detail: a narrow bed, a desk with a laptop and a mug on it, things stuck to the wall, a wardrobe that does not shut flush. The laptop still open from last night, grey through a thin curtain. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A student dorm room, a narrow bed, a desk with a laptop and a mug on it, things stuck to the wall, a wardrobe that does not shut flush, the laptop still open from last night, grey through a thin curtain, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

<details><summary>day (`scenes/dorm-room-day.jpg`)</summary>

- **File:** `scenes/dorm-room-day.jpg`

**Grok Imagine** (prose)

```text
A student dorm room. Visible detail: a narrow bed, a desk with a laptop and a mug on it, things stuck to the wall, a wardrobe that does not shut flush. The door propped open onto the corridor, daylight and corridor light both. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A student dorm room, a narrow bed, a desk with a laptop and a mug on it, things stuck to the wall, a wardrobe that does not shut flush, the door propped open onto the corridor, daylight and corridor light both, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>dusk (`scenes/dorm-room-dusk.jpg`)</summary>

- **File:** `scenes/dorm-room-dusk.jpg`

**Grok Imagine** (prose)

```text
A student dorm room. Visible detail: a narrow bed, a desk with a laptop and a mug on it, things stuck to the wall, a wardrobe that does not shut flush. Desk lamp on, the overhead off, one warm lamp, screen glow. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A student dorm room, a narrow bed, a desk with a laptop and a mug on it, things stuck to the wall, a wardrobe that does not shut flush, desk lamp on, the overhead off, one warm lamp, screen glow, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>night (`scenes/dorm-room-night.jpg`)</summary>

- **File:** `scenes/dorm-room-night.jpg`

**Grok Imagine** (prose)

```text
A student dorm room. Visible detail: a narrow bed, a desk with a laptop and a mug on it, things stuck to the wall, a wardrobe that does not shut flush. Only the screen, laptop light on a face's worth of room. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A student dorm room, a narrow bed, a desk with a laptop and a mug on it, things stuck to the wall, a wardrobe that does not shut flush, only the screen, laptop light on a face's worth of room, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

---

### `classroom`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/classroom-dawn.jpg`

**Grok Imagine** (prose)

```text
A university classroom between sessions. Visible detail: rows of tables, a whiteboard half wiped, a projector on standby, chairs at angles where people got up. Empty and straightened, daylight, blinds half down. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university classroom between sessions, rows of tables, a whiteboard half wiped, a projector on standby, chairs at angles where people got up, empty and straightened, daylight, blinds half down, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

<details><summary>day (`scenes/classroom-day.jpg`)</summary>

- **File:** `scenes/classroom-day.jpg`

**Grok Imagine** (prose)

```text
A university classroom between sessions. Visible detail: rows of tables, a whiteboard half wiped, a projector on standby, chairs at angles where people got up. Mid-session, bags on the floor, daylight plus overheads. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university classroom between sessions, rows of tables, a whiteboard half wiped, a projector on standby, chairs at angles where people got up, mid-session, bags on the floor, daylight plus overheads, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>dusk (`scenes/classroom-dusk.jpg`)</summary>

- **File:** `scenes/classroom-dusk.jpg`

**Grok Imagine** (prose)

```text
A university classroom between sessions. Visible detail: rows of tables, a whiteboard half wiped, a projector on standby, chairs at angles where people got up. Emptying out, someone still packing up, overheads on, the windows dark. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university classroom between sessions, rows of tables, a whiteboard half wiped, a projector on standby, chairs at angles where people got up, emptying out, someone still packing up, overheads on, the windows dark, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>night (`scenes/classroom-night.jpg`)</summary>

- **File:** `scenes/classroom-night.jpg`

**Grok Imagine** (prose)

```text
A university classroom between sessions. Visible detail: rows of tables, a whiteboard half wiped, a projector on standby, chairs at angles where people got up. Chairs up, board wiped, one bank of lights. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university classroom between sessions, rows of tables, a whiteboard half wiped, a projector on standby, chairs at angles where people got up, chairs up, board wiped, one bank of lights, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

---

### `gym`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/gym-dawn.jpg`

**Grok Imagine** (prose)

```text
A university gym. Visible detail: rubber matting, a rack of weights, mirrors along one wall, a water fountain, a hand-written sign taped to a machine. Two people in and neither talking, strips over the mats. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university gym, rubber matting, a rack of weights, mirrors along one wall, a water fountain, a hand-written sign taped to a machine, two people in and neither talking, strips over the mats, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

<details><summary>day (`scenes/gym-day.jpg`)</summary>

- **File:** `scenes/gym-day.jpg`

**Grok Imagine** (prose)

```text
A university gym. Visible detail: rubber matting, a rack of weights, mirrors along one wall, a water fountain, a hand-written sign taped to a machine. Busy, everything in use, bright, even, unkind. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university gym, rubber matting, a rack of weights, mirrors along one wall, a water fountain, a hand-written sign taped to a machine, busy, everything in use, bright, even, unkind, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>dusk (`scenes/gym-dusk.jpg`)</summary>

- **File:** `scenes/gym-dusk.jpg`

**Grok Imagine** (prose)

```text
A university gym. Visible detail: rubber matting, a rack of weights, mirrors along one wall, a water fountain, a hand-written sign taped to a machine. The after-class rush, full lights, dark windows. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university gym, rubber matting, a rack of weights, mirrors along one wall, a water fountain, a hand-written sign taped to a machine, the after-class rush, full lights, dark windows, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>night (`scenes/gym-night.jpg`)</summary>

- **File:** `scenes/gym-night.jpg`

**Grok Imagine** (prose)

```text
A university gym. Visible detail: rubber matting, a rack of weights, mirrors along one wall, a water fountain, a hand-written sign taped to a machine. Nearly empty, one machine running, half the lights off. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university gym, rubber matting, a rack of weights, mirrors along one wall, a water fountain, a hand-written sign taped to a machine, nearly empty, one machine running, half the lights off, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

---

### `library`

- **Size:** 1280x720

#### dawn

- **File:** `scenes/library-dawn.jpg`

**Grok Imagine** (prose)

```text
A university library reading room. Visible detail: long tables with individual lamps, stacks receding, a trolley of returns, a laptop left open at an empty chair. Unlocked and nobody in yet, daylight from high windows. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university library reading room, long tables with individual lamps, stacks receding, a trolley of returns, a laptop left open at an empty chair, unlocked and nobody in yet, daylight from high windows, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

<details><summary>day (`scenes/library-day.jpg`)</summary>

- **File:** `scenes/library-day.jpg`

**Grok Imagine** (prose)

```text
A university library reading room. Visible detail: long tables with individual lamps, stacks receding, a trolley of returns, a laptop left open at an empty chair. Every other seat taken and completely silent, daylight and table lamps together. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university library reading room, long tables with individual lamps, stacks receding, a trolley of returns, a laptop left open at an empty chair, every other seat taken and completely silent, daylight and table lamps together, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>dusk (`scenes/library-dusk.jpg`)</summary>

- **File:** `scenes/library-dusk.jpg`

**Grok Imagine** (prose)

```text
A university library reading room. Visible detail: long tables with individual lamps, stacks receding, a trolley of returns, a laptop left open at an empty chair. The lamps doing the work now, pools of lamplight, the stacks dark. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university library reading room, long tables with individual lamps, stacks receding, a trolley of returns, a laptop left open at an empty chair, the lamps doing the work now, pools of lamplight, the stacks dark, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

<details><summary>night (`scenes/library-night.jpg`)</summary>

- **File:** `scenes/library-night.jpg`

**Grok Imagine** (prose)

```text
A university library reading room. Visible detail: long tables with individual lamps, stacks receding, a trolley of returns, a laptop left open at an empty chair. Close to closing, one or two left, table lamps only. Photographic, contemporary, unremarkable. Available light -- overhead strips, a window, a desk lamp -- with the colour it actually casts rather than a corrected version of it. Muted greens, greys, warm beige, the institutional palette of a building nobody chose. Ordinary modern surfaces, worn and specific: scuffed vinyl, a radiator, a whiteboard half wiped, a noticeboard with too many pins. Shallow depth of field. Every figure is an adult. No text or lettering anywhere in the frame.
```

**ComfyUI** (tags)

```text
A university library reading room, long tables with individual lamps, stacks receding, a trolley of returns, a laptop left open at an empty chair, close to closing, one or two left, table lamps only, photographic, contemporary interior, available light, muted institutional palette, greys and warm beige, worn everyday surfaces, scuffed vinyl, fluorescent strip lighting, shallow depth of field, natural composition, unremarkable, no text, no watermark
```

```text
NEGATIVE: child, teenager, youthful minor, childlike proportions, chibi, anime, manga, cartoon, cel shading, fantasy, magic, medieval, ornate, gilded, vines, petals, foliage, art nouveau, bioluminescence, glowing, neon, cyberpunk, sci-fi, text, lettering, watermark, logo, signature, blurry, low quality, oversaturated, HDR, heroic pose
```

</details>

---

## LoRA hints

From `subjects.yaml` `style.loras`. ComfyUI only; Grok ignores them.

```yaml
- name: Photoreal_Interior
  weight: 0.5
```

## Manifest block to paste

```yaml
locations:
  hallway:
    times:
      dawn: scenes/hallway-dawn.jpg
      day: scenes/hallway-day.jpg
      dusk: scenes/hallway-dusk.jpg
      night: scenes/hallway-night.jpg
  bathroom:
    times:
      dawn: scenes/bathroom-dawn.jpg
      day: scenes/bathroom-day.jpg
      dusk: scenes/bathroom-dusk.jpg
      night: scenes/bathroom-night.jpg
  kitchen:
    times:
      dawn: scenes/kitchen-dawn.jpg
      day: scenes/kitchen-day.jpg
      dusk: scenes/kitchen-dusk.jpg
      night: scenes/kitchen-night.jpg
  living_room:
    times:
      dawn: scenes/living-room-dawn.jpg
      day: scenes/living-room-day.jpg
      dusk: scenes/living-room-dusk.jpg
      night: scenes/living-room-night.jpg
  front_porch:
    times:
      dawn: scenes/front-porch-dawn.jpg
      day: scenes/front-porch-day.jpg
      dusk: scenes/front-porch-dusk.jpg
      night: scenes/front-porch-night.jpg
  quad:
    times:
      dawn: scenes/quad-dawn.jpg
      day: scenes/quad-day.jpg
      dusk: scenes/quad-dusk.jpg
      night: scenes/quad-night.jpg
  admin_block:
    times:
      dawn: scenes/admin-block-dawn.jpg
      day: scenes/admin-block-day.jpg
      dusk: scenes/admin-block-dusk.jpg
      night: scenes/admin-block-night.jpg
  cafeteria:
    times:
      dawn: scenes/cafeteria-dawn.jpg
      day: scenes/cafeteria-day.jpg
      dusk: scenes/cafeteria-dusk.jpg
      night: scenes/cafeteria-night.jpg
  dorm_room:
    times:
      dawn: scenes/dorm-room-dawn.jpg
      day: scenes/dorm-room-day.jpg
      dusk: scenes/dorm-room-dusk.jpg
      night: scenes/dorm-room-night.jpg
  classroom:
    times:
      dawn: scenes/classroom-dawn.jpg
      day: scenes/classroom-day.jpg
      dusk: scenes/classroom-dusk.jpg
      night: scenes/classroom-night.jpg
  gym:
    times:
      dawn: scenes/gym-dawn.jpg
      day: scenes/gym-day.jpg
      dusk: scenes/gym-dusk.jpg
      night: scenes/gym-night.jpg
  library:
    times:
      dawn: scenes/library-dawn.jpg
      day: scenes/library-day.jpg
      dusk: scenes/library-dusk.jpg
      night: scenes/library-night.jpg
```
