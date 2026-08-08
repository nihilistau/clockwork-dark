# ComfyUI Prompt Templates — The Clockwork Dark

Lifted from `clockwork-dark/data/procgen_templates/comfyui.yaml` and the design brief (§5–§6). Append the **style suffix** to every prompt; pair with the **standard negative**. Add the **corruption suffix** only from the SPREADING phase onward.

## Style suffix (append to all)
```
oil-painted fantasy illustration, grounded realism, muted earth palette,
soft atmospheric lighting, detailed textures, frontier village aesthetic,
no modern elements, no text, no watermark
```

## Negative prompt (standard)
```
cartoon, anime, neon, sci-fi, cyberpunk, modern clothing, cars, guns,
text, watermark, logo, blurry, low quality, oversaturated, heroic pose,
glowing magic effects, floating UI
```

## Corruption overlay (SPREADING+ only)
```
, subtle brass clockwork motifs in organic matter, sick green undertone,
uncanny wrongness, melancholy dread
```

## Workflow specs
| Type | Aspect | Resolution | Notes |
|------|--------|-----------|-------|
| portrait | 3:4 | 768×1024 | SDXL + IPAdapter for consistency |
| location_still | 16:9 | 1344×768 | SDXL; no characters center-frame |
| cutscene_video | 16:9 | 512×288 × 24fps | AnimateDiff; ≤4s v0.1 |
| item_icon | 1:1 | 256×256 | SD 1.5 fast; flat illustrative |

## Locations (subject prompt, by time variant)
- **forest_clearing** — dawn: *misty birch forest clearing, distant village smoke, mushrooms, ferns* · noon: *sun-dappled birch clearing, worn path toward village smoke* · dusk: *blue hour forest edge, long shadows, distant hearth glow*
- **edgewood_square** — dawn: *quiet frontier village square, timber houses, communal stone oven, mist* · noon: *busy village square, chickens, timber frames, market stalls* · dusk: *village square at evening, lantern light, communal oven smoke*
- **edgewood_bakery** — dawn: *small bakery interior, brick oven warming, flour sacks, warm light* · night: *empty bakery at night, embers in oven, flour dust in moonlight*
- **tinker_caravan** — dusk: *colorful tinker tent, brass charms, maps, wagon wheels at sunset*
- **millhaven_gate** — dawn: *wooden palisade gate, militia banners, mud road, cold morning*
- **corruption_border** (SPREADING only) — *wheat field with brass gear growths, sick sky, wrong perspective*

## NPC portrait briefs (subject; append style suffix + negative)
- **npc_maris** (Baker) — *woman, 40s, flour on forearms, kind tired eyes, bakery interior, oven glow; warmth with worry underneath*
- **npc_odran** (Caravan Master) — *man, 50s, weathered, ledger in hand, coiled horse whip, wagon trail at dusk; merchant cheer masking gossip hunger*
- **npc_ilya** (Tinker) — *androgynous, sharp eyes, nine brass pins in scarf, tent interior with hanging charms; curious, slightly unsettling smile*
- **npc_sera** (Militia Sergeant) — *woman, 30s, scar on cheek, practical armor, Millhaven gate in rain; duty-heavy, not a villain*
- **npc_brindle** (Cat / Assistant form) — *grey barn cat, too-knowing eyes, tail curled, village square edge; cute but uncanny*

## The Assistant — five canonical forms
`cat` (early/low trust) · `wanderer` (grey cloak, face in shadow) · `child` (draws gears in dirt, STIRRING anomalies) · `tinker` (overlaps Ilya — ambiguous) · `reflection` (player silhouette in water/mirror, high Awareness).

## Cutscene captions (from canon)
- **cutscene_stirring_phase** — "The village clock stopped at a hour that never was." / "Crows gather on the mill roof, perfectly still."
- **cutscene_assistant_reveal** — "Cat eyes reflect a map of the Heartlands."
- **cutscene_consuming_horizon** — "Wheat rows tick like a metronome toward the horizon."

LoRA hints: `Oil_Painting_Style` ~0.6, `Medieval_Environment` ~0.4. Avoid anime/cyberpunk LoRAs.

## d20 faces (interface furniture, 1:1 1024×1024)

Twenty plates, one per possible roll — the toast shows the face the engine
actually rolled. Authoritative spec: `data/art/subjects.yaml` → `dice_faces`,
rendered into both dialects by `engine/media/art.py`. Mirror for the ComfyUI
client: `data/procgen_templates/comfyui.yaml` → `dice`. Generate with
`python scripts/generate_dice_art.py`.

**Subject (per face `n`)**
```
A single aged bone twenty-sided die, the numeral n uppermost and square to the viewer
```

**Shared detail (append to every face, before the style suffix)**
```
a heavy ivory-white icosahedron of old bone with chipped rounded edges and hairline
cracks running through it, the uppermost triangular facet cut deep with its numeral and
darkened with old ink, the surrounding facets carrying their own smaller drilled marks;
the engraved numeral is part of the die itself, not lettering laid over the picture,
the die alone and centred, filling most of a square frame, standing on dark scarred slate
with nothing else in shot, one low warm lamp from the upper left, thick oil impasto on the
lit facets, the ground falling away to near-black in the corners
```

Then the standard **style suffix** and **negative prompt**. Do *not* add the
corruption suffix — the dice are chrome, not world, and do not rot with it.

The `no text` clause in the style suffix fights a numbered die by definition.
The "part of the die itself, not lettering laid over the picture" wording in the
shared detail is what settles it; without it Imagine returns unmarked pip dice.
