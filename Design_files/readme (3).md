# The Clockwork Dark — Design System

> *A frontier village at the edge of an old forest, lit by tallow and mistrust. Beauty in bread steam and moss. Dread in a child's drawing of gears. The UI feels like a traveler's journal crossed with a clockmaker's ledger.*

This is the brand & UI design system for **The Clockwork Dark**, a **local-first AI roleplaying game**. The player wakes in a forest clearing at the margin of Edgewood, a poor-but-proud frontier village, while an ambiguous "Assistant" (a cat, a wanderer, a child…) watches. A slow corruption — gears in wheat, brass in bone — creeps inward from the Heartlands across four hidden **evil phases**. The interface must feel *worn, quiet, and slowly wrong* — never epic high fantasy.

The game presents as a single browser scene: a **scene visual** (ComfyUI still or cutscene) over a three-column journal — Assistant · Narrative Log · Character Sheet — bracketed by a chrome header (world clock) and footer (day · time · weather · audio · settings).

---

## Sources

This system was built by reading the game's codebase and creative-direction docs (read-only, mounted locally as `clockwork-dark/`):

| Source | What it gave us |
|--------|-----------------|
| `docs/CLAUDE_DESIGN_BRIEF.md` | The canonical creative direction — palettes, type, screen briefs, phase moods, canon constraints (§9). Primary reference. |
| `docs/DESIGN.md` (referenced) | World/mechanics canon, location IDs, glossary. |
| `content/scenes/clockwork/static/css/design_tokens.css` | The shipped "Hearth Ledger" palette + font stacks — our starting tokens. |
| `content/scenes/clockwork/static/css/clockwork.css` | The live scene layout (three-column grid, panels, chips). |
| `content/scenes/clockwork/templates/clockwork.html` | The real DOM structure of the game scene. |
| `content/scenes/clockwork/static/js/clockwork.js` | Socket.IO turn loop — narration append, choices, stats, assistant bubble, image-ready crossfade. |
| `data/lore/*.md`, `data/economy.yaml`, `data/tables/*.yaml` | Voice, copy samples, item & NPC names. |
| `data/procgen_templates/comfyui.yaml` | ComfyUI prompt templates, style suffix, negative prompt, cutscene captions. |

No font binaries shipped in the repo. The brief names web families (EB Garamond, Source Sans 3, IBM Plex Mono, Nunito) over system fallbacks (Georgia, Segoe UI, Consolas, Trebuchet). **We load the web families from Google Fonts** — see Caveats.

---

## Index

**Foundations**
- `styles.css` — global entry point (link this one file). `@import`s everything below.
- `tokens/colors.css` — Hearth Ledger primitives, derived ramps, semantic aliases.
- `tokens/typography.css` — four font voices, type scale, weights, tracking.
- `tokens/spacing.css` — spacing scale, frame columns, radii, border weights.
- `tokens/effects.css` — shadows, motion, paper grain, the tick divider.
- `tokens/phases.css` — the four evil-phase theme overrides (`[data-phase]`).
- `tokens/fonts.css` — webfont `@import`.

**Components** (`components/`) — `core/` (Button, ChoiceChip, Badge, StatLine), `feedback/` (DiceToast, AssistantBubble), `scene/` (ScenePanel, WorldClock).

**UI kits** (`ui_kits/`):
- `ui_kits/clockwork-scene/` — interactive recreation of the full game scene (grim-dark), with a phase switcher.
- `ui_kits/clockwork-world/` — the interactive **World & Interface bible**: Atlas (places & buildings), Souls (NPCs, the cat, the robed Assistant-wizard study in white/grey/red/black, the five forms, player archetypes), Things (items & relics), Interface (HUD anatomy, panel designs, cutscene letterbox, combat sheet, phase transitions), **Screens** (Trade/barter overlay, Bakery domestic UI with live oven timer, Millhaven militia gate), and Play (the live scene embedded).

**Templates** (`templates/`):
- `templates/clockwork-scene/` — **Clockwork Scene** starter (`ClockworkScene.dc.html` + `ds-base.js`). A grim-dark journal scene shell a consuming project copies and edits inline; mounts the DS components via `<x-import>` and has a live evil-phase switch.

**Specimen cards** (`guidelines/`) — the swatch/type/spacing cards rendered in the Design System tab.

**Other**
- `assets/` — wordmark, gear motif, woodcut divider, icon notes.
- `SKILL.md` — Agent-Skills wrapper for downloading this system into Claude Code.

See **Content Fundamentals**, **Visual Foundations**, and **Iconography** below.

---

## Content Fundamentals

How copy is written in The Clockwork Dark. The world *narrates*; it never *instructs*.

**Voice & person.** Narration is **second person, present-ish**, addressed to the player as "you" — but quietly, like a journal someone else is keeping about you. <em>"The forest clearing where travelers wake is generous but not tame."</em> NPCs and lore speak in plain, grounded sentences. The Assistant is a separate voice — shorter, stranger, never a tutorial fairy (canon §4).

**Tone.** Worn, melancholy, understated. Dread arrives in small concrete images, not adjectives: <em>"stillborn lambs with brass teeth, bread that rings when it cracks, clocks that tick hours that never were."</em> Beauty arrives the same way: flour on sleeves, honey light, a hum to keep the gears quiet. **Show the wrongness in objects; never announce it.**

**Casing.** Sentence case everywhere in prose. **Tracked UPPERCASE smallcaps** for UI chrome labels only (`HP`, `STAMINA`, `INVENTORY`, the assistant-form tag `CAT`). Scene titles are Title Case. The world clock is monospace (`Day 12 · Evening`).

**Concrete > abstract.** Prices are in copper, not "gold floating in the air." Items have honest names: *Loaf of bread, Whetstone, Sympathy charm, Tinker knowledge map.* Choices are short imperatives: *"Walk toward smoke", "Forage the clearing", "Listen."*

**What the player must never see (canon §8–9).** No "AI narrator" labels. No `Awareness: 12%` on the HUD. No chosen-one language. No fourth-wall meta. Awareness, the World Clock, and corruption motifs stay **hidden until discovered** in-world.

**Emoji.** Effectively none. The shipped UI uses a single 🎤 on the mic stub; treat that as legacy and prefer an SVG/icon-font glyph. No emoji in narration, choices, or labels — they break the woodcut/ledger register.

**Micro-copy examples (from canon):**
- Dice toast: `d20: 14 + 2 = 16 vs DC 13 — Success` (engine result, verbatim, monospace).
- Complication: *"You slip — lose next action stamina."*
- Boon: *"Notice something others missed — free clue."*
- Cutscene caption: <em>"The village clock stopped at a hour that never was."</em>
- Footer: `Day 12 · Evening · Overcast`.

---

## Visual Foundations

> **Theme direction — Ash & Thorn (grim-dark).** This system now ships **grim-dark by default**: cold slate surfaces, bleak air, almost no light fills, and a single warm note of **tinker-brass candlelight**. The journal that was once warm linen is now **dark aged vellum** — a lit page in surrounding shadow ("lit by tallow and mistrust"). The semantic tokens carry these dark values; the raw *Hearth Ledger* primitives remain documented for reference, and **Ash & Thorn** / **Tinker Brass** are the guiding moods. Texture is restrained (the heavy woodcut grain is dialed back in favor of smooth dark gradients + brass hairlines).


**Overall register.** A traveler's journal over a clockmaker's ledger. Rectangular, calm, ruled. Warm linen pages framed by iron chrome and forest dark. Nothing glossy, nothing neon, nothing rounded-and-cute.

**Color.** Three anchored families: **forest dark** (`--forest-deep`) for scene backdrop and chrome shadow, **warm linen** (`--linen`, `--linen-300`) for the readable pages, and **tallow candlelight** (`--tallow`) as the single bright accent. **Iron** rules and borders everything. **Rust/brass** (`--rust-clock`) carries the clock/tinker motif. **Corruption** (`--corruption`, sickly green) and **blood-quiet** (muted maroon) are held back — corruption is *gated* until the SPREADING phase; blood only appears in combat. Imagery is warm, oil-painted, muted-earth, soft atmospheric light (see Iconography → imagery). Color is applied through **semantic aliases** (`--surface-narrative`, `--text-narration`, `--accent-candle`) so the four **phase themes** can re-tint the whole product from one `[data-phase]` attribute: cozy → brass-creep → sickly chartreuse → high-contrast clockwork.

**Type.** Four deliberately distinct voices: **EB Garamond** old-style serif for narration (19px, line-height 1.65, generous); **Source Sans 3** humanist sans for chrome/labels (13–14px, uppercase tracked for labels); **IBM Plex Mono** for stats, dice and the clock (tabular); **Nunito** rounded sans for the Assistant, so its voice reads as *other*. Display/scene titles use the serif or tracked sans caps.

**Spacing & layout.** A fixed three-column frame: assistant `200px` · narrative `flex` · sheet `220px`, header and footer bars fixed top/bottom, scene visual claiming ~38vh of the narrative column. Panel padding is `1rem–1.25rem`. Layout is intentionally **fixed and gridded**, not fluid-marketing; below 900px the side columns collapse. Spacing scale is a 0.25rem base.

**Backgrounds.** Solid earthen fills, not gradients. The narrative panel carries a **subtle paper-grain texture** (CSS SVG noise, ~4% opacity) — never a photographic background behind text. The scene visual is **full-bleed imagery** (ComfyUI stills) with a blur-up placeholder. Cutscenes letterbox to 2.39:1 with a semi-transparent caption bar. **No gradient meshes, no glassmorphism, no purple magic glow** (anti-references).

**Borders & dividers.** The ledger rule: hard **iron borders**, `2px` between panels, `1px` hairlines (`--line-soft`) within. The signature decorative element is the **tick divider** — a woodcut dashed/repeating rule (`--rule-tick`) that appears in section breaks once the world begins to stir. The assistant bubble carries a `4px` **brass accent edge** on its left.

**Corner radii.** Restrained. Choice chips and inputs `4px`; the assistant bubble uses an asymmetric `0 8px 8px 0` (open corner toward its accent edge). Most panels are **square (0 radius)**. Nothing is pill-rounded except a true pill control.

**Cards.** A "card" here is a linen surface with a soft warm shadow (`--shadow-card`), square or barely-rounded corners, and — when it's the Assistant — a brass left edge. Low elevation. No colored-left-border-accent cliché except the intentional brass bubble edge.

**Shadows.** Warm and low, tinted with forest-green-black rather than neutral grey (`rgba(29,41,29,…)`). `--shadow-card` for raised surfaces, `--shadow-raise` for overlays/toasts, `--shadow-inset` for pressed inputs. A **candle glow** (`--glow-candle`, tallow ring) marks focus and active states instead of a blue focus ring.

**Motion.** Quiet. Crossfades (image-ready `400ms`), gentle fades, the dice toast dwelling `1.5s` then fading. **No bounce, no spring, no parallax.** Easing is `cubic-bezier(0.4,0,0.2,1)`. At CONSUMING phase the UI may "stutter" one frame per minute — a deliberate wrongness, not a loading state. Respects `prefers-reduced-motion`.

**Hover / press states.** Hover **deepens** warmth (tallow → `--tallow-700`, or a subtle darken), never lightens to white and never adds a colored glow halo. Press **darkens and insets** (`--shadow-inset`) — a physical ledger-button feel — with no scale-shrink trick. Disabled drops to `opacity: 0.5` with a `wait` cursor (choices disable the instant they're clicked, per the turn loop).

**Transparency & blur.** Used sparingly and purposefully: the cutscene caption bar (semi-transparent dark), the modal/overlay scrim (`--surface-overlay`, forest-dark at ~72%), the blur-up image placeholder. No frosted-glass panels.

**Fixed elements.** Header (world clock) and footer (day/weather/controls) are persistent chrome. The Assistant bubble slides in from the left and **must not block the choices**. Toasts are center-screen, non-blocking, auto-dismissing.

---

## Iconography

**Approach: woodcut, not icon-font-clutter.** The Clockwork Dark has no shipped icon system — the live UI uses a single emoji (🎤) on a stub button and otherwise relies on text labels. The brand's iconographic register is **woodcut / engraving**: the gear/clock motif, a tick divider, a nine-pin tinker mark. Iconography is **sparse and meaningful** — every glyph earns its place; there is no toolbar of decorative icons.

- **No built-in icon font or SVG sprite** exists in the codebase. We do **not** invent ornate hand-drawn SVGs.
- **Recommended substitution (flag):** for functional UI glyphs (mic, settings gear, audio, send, close) use **[Lucide](https://lucide.dev)** via CDN — its thin, even, slightly hand-cut stroke suits the woodcut register better than filled/rounded sets. Tint glyphs with `--text-on-dark` / `--accent-candle` on chrome. This is a **substitution**, not a brand asset — see Caveats.
- **The gear motif** (`assets/gear-motif.svg`) is the one true brand glyph — the World Clock indicator, the settings affordance, and the corruption signature all derive from it. Keep it line-art, brass-tinted, never animated except the deliberate phase stutter.
- **The tick / woodcut divider** (`assets/woodcut-divider.svg`) marks section breaks; it intensifies (dash → dot) as phases advance.
- **Emoji:** avoid. The legacy 🎤 should be replaced by a Lucide `mic` glyph.
- **Unicode:** the middle dot `·` is used as the canonical separator in chrome (`Day 12 · Evening · Overcast`). Keep it.

**Imagery.** All scene art is **oil-painted fantasy illustration, grounded realism, muted earth palette, soft atmospheric lighting** (the ComfyUI style suffix). Warm, never oversaturated; no neon, no glowing magic, no floating UI. Portraits 3:4, locations 16:9, item icons 1:1 flat illustrative. Corruption imagery adds *subtle brass clockwork motifs in organic matter, sick green undertone* — and only from SPREADING on. Full prompt templates live in `assets/comfyui-prompts.md`.

---

## Caveats

- **Fonts are confirmed** — EB Garamond (narration), Source Sans 3 (UI), IBM Plex Mono (stats/dice), Nunito (Assistant), all open-licensed. They load from Google Fonts today; a drop-in **self-host scaffold** is ready in `tokens/fonts.css` + `assets/fonts/README.md` (add the `.woff2` files and flip one comment). Claude can't fetch the binaries for you.
- **Icons are a substitution.** No brand icon set exists; we recommend Lucide via CDN for functional glyphs and supply only the gear + woodcut-divider brand marks. **Confirm or provide a real icon set.**
- **Scene/portrait art is generated at runtime by ComfyUI** — this system ships *prompt templates and placeholders*, not final art. UI kit previews use painterly placeholders.
- The two alternate palette directions from the brief (**Tinker Brass**, **Ash & Thorn**) are documented as specimen cards but the canonical product palette is **Hearth Ledger** (Direction A), as shipped.
