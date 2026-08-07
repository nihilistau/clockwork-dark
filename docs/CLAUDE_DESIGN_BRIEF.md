# The Clockwork Dark — Claude Design Brief

**Document type:** Creative direction handoff  
**Audience:** Claude Design (or any design-focused AI)  
**Do not:** Write implementation code, backend logic, or agent prompts unless explicitly asked for prompt *templates*  
**Canon reference:** [DESIGN.md](DESIGN.md)

---

## §0 — Your Role

You are the **Art Director and UX Designer** for *The Clockwork Dark*, a local-first AI roleplaying game.

**Your outputs should be:**
- Design decisions with rationale (palettes, typography, layout)
- UI wireframe descriptions or HTML/CSS prototypes (static mockups only)
- ComfyUI prompt templates and negative prompts
- NPC visual briefs and environment art direction
- Cutscene storyboards (shot lists + caption text)
- Audio direction notes (TTS character, ambient beds)
- Icon and item art specifications

**You must respect canon constraints in §9.** When unsure, choose the option that feels *worn, quiet, and slowly wrong* — not epic high fantasy.

---

## §1 — Creative North Star

### Elevator pitch (visual)

*A frontier village at the edge of an old forest, lit by tallow and mistrust. Beauty in bread steam and moss. Dread in a child's drawing of gears. The UI should feel like a traveler's journal crossed with a clockmaker's ledger.*

### Touchstones

| Reference | Take |
|-----------|------|
| *The Name of the Wind* | Tinker wagons, road dust, sympathy as craft not spectacle |
| *Dragonlance* | Weight of rising evil; no neon prophecy UI |
| *Princess Mononoke* | Forest edge village; nature as character |
| *Darkest Dungeon* | Dread accents, stress — but less grotesque, more melancholy |
| *Firewatch* | Environmental storytelling; strong color moments at dusk |
| Archives of Anubis | Phase-based atmosphere shift (subtle corruption creep) |

### Anti-references (avoid)

- MMO HUD clutter, loot beam colors, cartoon proportions
- Purple "magic UI" glow everywhere
- Cyberpunk neon (this is not CosySim's NEON CITY)
- Over-ornate throne-room high fantasy
- Generic "AI chat" bubble aesthetics (Slack/Discord clone)

### Emotional targets by evil phase

| Phase | Visual mood | UI behavior |
|-------|-------------|-------------|
| **DORMANT** | Warm linen, moss green, honey light | Clean journal; no corruption motifs |
| **STIRRING** | Brass accents appear; shadows slightly too long | Subtle tick motif in dividers |
| **SPREADING** | Desaturated greens; sickly chartreuse corruption | Weather widget shows "wrong" readings |
| **CONSUMING** | High contrast; clockwork filigree in borders | Letterbox cutscenes; UI "stutters" one frame per minute |

---

## §2 — Visual Identity System

### Primary palette (Direction A — *Hearth Ledger*)

| Token | Hex | Usage |
|-------|-----|-------|
| `--forest-deep` | `#2C3E2C` | Forest scenes, headers |
| `--moss-light` | `#6B7F5E` | Secondary panels |
| `--linen` | `#F2E8D5` | Narrative log background |
| `--tallow` | `#E8C47A` | Highlights, candlelight |
| `--iron` | `#3D3D3D` | Stats, borders |
| `--rust-clock` | `#8B4513` | Clock motifs, tinker brass |
| `--corruption` | `#7A9E4F` | Sickly; use sparingly until SPREADING |
| `--blood-quiet` | `#6B2D2D` | Combat, injury (muted) |

### Typography

| Role | Font direction | Notes |
|------|----------------|-------|
| Narration | Old-style serif (e.g. EB Garamond, Lora) | 18–20px, generous line-height |
| UI chrome | Humanist sans (e.g. Source Sans 3) | 14px labels |
| Stats / dice | Monospace (e.g. IBM Plex Mono) | Tabular numbers |
| Assistant speech | Slightly rounded sans (e.g. Nunito) | Distinct from narration |

### Texture language

- Paper grain on narrative panel (subtle CSS noise or background image)
- Woodcut-style section dividers (SVG)
- Worn leather texture on inventory strip
- **No** glossy glassmorphism

### Request: produce 3 palette directions

When invoked, deliver **three** complete palette proposals:

1. **Hearth Ledger** (default above) — cozy → wrong
2. **Tinker Brass** — more copper, caravan lanterns, road dust
3. **Ash & Thorn** — colder, bleaker, earlier dread

For each: 8 tokens, mood paragraph, sample screen description.

---

## §3 — UI/UX Wireframe Briefs

### Global layout (desktop 1280×800 minimum)

```
┌─────────────────────────────────────────────────────────────┐
│  SCENE VISUAL (60% height) — ComfyUI still or cutscene      │
│  [optional: letterbox bars during CUTSCENE]                   │
├──────────────┬──────────────────────────────┬─────────────────┤
│ ASSISTANT    │ NARRATIVE LOG              │ CHARACTER SHEET │
│ 180px col    │ flex grow                  │ 220px col       │
│ Portrait +   │ Scrollable SSE text        │ HP, Stamina,    │
│ speech bubble│ Choice chips (2–4)         │ Focus, Craft    │
│              │ Free text + mic            │ Inventory list  │
├──────────────┴──────────────────────────────┴─────────────────┤
│ FOOTER: Day 12 · Evening · Overcast · [🔊] [⚙]              │
└─────────────────────────────────────────────────────────────┘
```

### Screens to draft

#### 3.1 Forest Opening (`forest_clearing`)

- First frame: mist, birch trunks, distant smoke (Edgewood)
- Narration begins before image finishes loading (skeleton → fade-in)
- Choices: "Walk toward smoke", "Forage the clearing", "Listen"
- **No** minimap yet

#### 3.2 Village Square (`edgewood_square`)

- Central oven, timber houses, chickens, notice board
- NPC markers subtle (name on hover, not gamey icons)
- Market day variant: extra stalls, brighter tallow accents

#### 3.3 Tinker Caravan (`tinker_caravan`)

- Nine-pin tent motif, hanging charms, chalk symbols
- Ilya's wagon: tools, maps, suspicious sympathy lamps
- Trade UI overlay: barter list, not gold coins floating

#### 3.4 Assistant Appearance Overlay

- Assistant bubble slides from left; does not block choices
- Form variants: cat (small portrait), wanderer (hooded), child, tinker, reflection (mirrored player silhouette — unsettling)
- `[VOICE:whisper]` = smaller text, italic, lighter color

#### 3.5 Combat Sheet (rare)

- Minimal: player HP, enemy name, 3–5 action buttons
- Dice result toast: center-screen 1.5s fade (`d20: 14 + 2 = 16 vs DC 13 — Success`)
- No battle animations in v0.1 — still image with red vignette pulse

#### 3.6 Cutscene Frame

- 2.39:1 letterbox inside scene visual
- Captions bottom-third (serif, semi-transparent bar)
- Skip button after 5s (small, respectful)

### Component inventory

| Component | Behavior |
|-----------|----------|
| `NarrativeLog` | SSE append; user can scroll up; auto-scroll if at bottom |
| `ChoiceChip` | 2–4 pills; keyboard 1–4 |
| `DiceToast` | Non-blocking; shows engine result verbatim |
| `AwarenessShimmer` | **Hidden until Awareness≥20** — faint edge vignette pulse once per session |
| `WorldClockIndicator` | **Hidden until discovered** — then small gear icon in footer |
| `AssistantBubble` | Max 3 lines; typewriter optional |
| `ImageLoader` | Blur-up placeholder; cache badge if reused |

### Interaction patterns

| Input | UX |
|-------|-----|
| Click choice | Immediate disable + spinner on log |
| Free text | Enter to send; Shift+Enter newline |
| Push-to-talk | Hold mic button; waveform while recording |
| Image ready | Crossfade 400ms; no layout jump |

---

## §4 — Character & NPC Design Sheets

### Player archetypes (visual silhouette, not classes)

| Archetype | Silhouette | Starting gear look |
|-----------|------------|-------------------|
| **Wayfarer** | Cloak, staff, road boots | Travel-worn, practical |
| **Hearthkeeper** | Apron or rolled sleeves, sturdy | Flour dust, warm colors |
| **Tinker-apprentice** | Tool belt, goggles optional | Brass pins, chalk stains |

### NPC portrait briefs (ComfyUI)

Produce **full prompt + negative** for each when invoked.

#### `npc_maris` — Baker

- Woman, 40s, flour on forearms, kind eyes, tired
- Setting: bakery interior, oven glow
- Mood: warmth with worry underneath

#### `npc_odran` — Caravan Master

- Man, 50s, weathered, ledger in hand, horse whip coiled
- Setting: wagon trail at dusk
- Mood: merchant cheer masking gossip hunger

#### `npc_ilya` — Tinker

- Androgynous, sharp eyes, nine brass pins in scarf
- Setting: tent interior, hanging charms
- Mood: curious, slightly unsettling smile

#### `npc_sera` — Militia Sergeant

- Woman, 30s, scar on cheek, practical armor
- Setting: Millhaven gate, rain
- Mood: duty-heavy, not villain

#### `npc_brindle` — Cat (Assistant form)

- Grey barn cat, too-knowing eyes, tail curled
- Setting: village square edge
- Mood: cute but uncanny

#### Player character template

- Neutral fantasy traveler, face partially obscured (player projection)
- Three archetype outfit variants

### The Assistant — five canonical forms

| Form | When to use (design) | Visual note |
|------|----------------------|-------------|
| `cat` | Early game, low trust | Brindle or strange stray |
| `wanderer` | Whisper arc | Grey cloak, face in shadow |
| `child` | STIRRING phase anomalies | Draws gears in dirt |
| `tinker` | Trade/knowledge moments | Overlaps Ilya's aesthetic — ambiguous |
| `reflection` | High Awareness | Player silhouette in water/mirror |

---

## §5 — Environment Art Direction

### Location ComfyUI seeds

When producing prompts, append **style suffix** (§6) to each seed.

| Location ID | Seed prompt (subject) | Time variants |
|-------------|----------------------|---------------|
| `forest_clearing` | misty birch forest clearing, distant village smoke, mushrooms, ferns | dawn mist / noon / blue hour |
| `edgewood_square` | frontier village square, timber houses, communal stone oven, chickens | market day / quiet evening |
| `edgewood_bakery` | small bakery interior, brick oven, flour sacks, warm light | morning prep / night empty |
| `tinker_caravan` | colorful tinker tent, brass charms, maps, wagon wheels | arrival sunset / rainy pack-up |
| `millhaven_gate` | wooden palisade gate, militia banners, mud road, refugees | rain / clear cold morning |
| `corruption_border` | wheat field with brass gear growths, sick sky, wrong perspective | SPREADING phase only |

### Weather states (footer + image modifier)

- `clear`, `overcast`, `mist`, `rain`, `wrong_rain` (rain falls up briefly — STIRRING+ only)

---

## §6 — ComfyUI Asset Spec

### Workflow types

| Type | Aspect | Resolution | Model notes |
|------|--------|------------|-------------|
| `portrait` | 3:4 | 768×1024 | SDXL + IPAdapter for consistency |
| `location_still` | 16:9 | 1344×768 | SDXL; no characters center-frame |
| `cutscene_video` | 16:9 | 512×288 × 24fps | AnimateDiff; ≤4s v0.1 |
| `item_icon` | 1:1 | 256×256 | SD 1.5 fast; flat illustrative |

### Style suffix (append to all prompts)

```
oil-painted fantasy illustration, grounded realism, muted earth palette,
soft atmospheric lighting, detailed textures, frontier village aesthetic,
no modern elements, no text, no watermark
```

### Negative prompt (standard)

```
cartoon, anime, neon, sci-fi, cyberpunk, modern clothing, cars, guns,
text, watermark, logo, blurry, low quality, oversaturated, heroic pose,
glowing magic effects, floating UI
```

### Corruption overlay suffix (SPREADING+ only)

```
, subtle brass clockwork motifs in organic matter, sick green undertone,
uncanny wrongness, melancholy dread
```

### LoRA recommendations (optional)

- `Oil_Painting_Style` — light weight 0.6
- `Medieval_Environment` — 0.4 for locations
- Avoid: anime, cyberpunk LoRAs

### Milestone cutscene storyboards (draft when invoked)

1. **`cutscene_stirring_phase`** — Broken village clock; crows; child's gear drawing
2. **`cutscene_assistant_reveal`** — Cat eyes reflect map of Heartlands
3. **`cutscene_consuming_horizon`** — Wheat field ticks like metronome

Each storyboard: 4–6 shots, caption text per shot, duration, music mood.

---

## §7 — Audio Direction

### TTS voice profiles

| Role | Character | Pitch | Pace | Notes |
|------|-----------|-------|------|-------|
| Storyteller | Warm narrator | Low-mid | Measured | Never campy; reads choices clearly |
| Assistant `cat` | — | — | — | Optional: subtle chime instead of voice |
| Assistant `wanderer` | Dry, tired | Low | Slow | Pauses mid-sentence |
| Assistant `child` | Bright | High | Quick | Innocent until line lands wrong |
| `npc_maris` | Soft maternal | Mid | Normal | Flour in the voice metaphorically |
| `npc_odran` | Merchant boom | Mid-low | Brisk | |
| `npc_ilya` | Precise | Mid | Careful | |

Store mappings in `config/voices.yaml` (design spec only here).

### Ambient beds (loopable, low)

| Scene | Bed |
|-------|-----|
| Forest | wind, leaves, distant bird |
| Village day | chickens, cart wheels, murmur |
| Bakery | oven crackle, kneading rhythm |
| Caravan | bells, canvas flap, fire crackle |
| Corruption | low clock tick, detuned drone |

### Cutscene scoring

- Acoustic guitar + cello for Stirring
- No triumphant brass until Convergence (and even then, bitter)
- Stinger on phase shift: single reversed bell

---

## §8 — Deliverables Checklist

When you are invoked for a design pass, produce as many of these as the user requests:

- [ ] **Palette decision doc** — 3 directions → pick 1 with rationale
- [ ] **UI mockup descriptions** — all 6 screens in §3 (or HTML/CSS static prototype)
- [ ] **10 ComfyUI prompt templates** — location + portrait + item + corruption variant
- [ ] **6 NPC portrait briefs** — full prompts (§4)
- [ ] **3 cutscene storyboards** — §6 milestone list
- [ ] **24-item icon list** — name, description, prompt seed for each
- [ ] **Typography & spacing spec** — CSS custom properties ready for dev handoff
- [ ] **Assistant form style guide** — portrait framing per form
- [ ] **Phase transition visual spec** — what changes in UI per evil phase
- [ ] **Accessibility notes** — contrast ratios, font min sizes, colorblind-safe corruption indicator

### Suggested first prompt to give Claude Design

> Read `docs/CLAUDE_DESIGN_BRIEF.md` and `docs/DESIGN.md`. Produce: (1) Palette Direction A finalized with CSS variables, (2) wireframe descriptions for Forest Opening and Village Square, (3) ComfyUI prompts for `forest_clearing` and `npc_maris`, (4) cutscene storyboard for `cutscene_stirring_phase`.

---

## §9 — Canon Constraints (do not violate)

1. **Magic is grounded** — sympathy, naming, craft; no fireball VFX in UI
2. **No chosen-one imagery** until Convergence arc (no glowing chosen silhouettes early)
3. **Edgewood is poor but proud** — not a fairy-tale perfect village
4. **The Assistant is ambiguous** — never design them as a clear "tutorial fairy"
5. **Clockwork corruption is organic-mechanical** — gears in wheat, brass in bone; not steampunk city
6. **Player can be a baker** — domestic UI (recipes, oven timer) must look as polished as adventure UI
7. **Diversity without caricature** — frontier means mixed travelers; respect in NPC design
8. **No fourth-wall UI** — no "AI narrator" labels visible to player
9. **Awareness is hidden** — do not put "Awareness: 12%" on HUD in v0.1
10. **Location IDs are fixed** — use canonical IDs from DESIGN.md glossary

---

## §10 — Handoff to Implementation

When design is approved, deliver:

1. `docs/design/PALETTE.md` — chosen palette + CSS variables
2. `docs/design/UI_SPEC.md` — component measurements
3. `docs/design/COMFYUI_PROMPTS.md` — all prompt templates
4. `content/scenes/clockwork/static/css/design_tokens.css` — dev-ready tokens

Coding agents read [CLAUDE_CODE_BRIEF.md](CLAUDE_CODE_BRIEF.md) for implementation.

---

*End of design brief.*