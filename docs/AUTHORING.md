# Authoring a Story

From an empty directory to a validated, simulated, playable story, without
reading engine source.

Authority reminder: the code wins. If this file disagrees with
`engine/games/**`, `engine/content/**` or the scripts it names, they are right
and this is stale. Every command below was run against the tree this file
shipped with.

The one idea everything else hangs off: **a story is a directory under
`games/<slug>/` with a `game.yaml` in it, and an undeclared `paths.*` key
resolves to NOTHING.** The engine's defaults name no story's content. Declare
what you ship; omit what you do not; the omission is an authoring decision.
(It was not always so — every story that omitted a key used to silently read
The Clockwork Dark's files, and the only symptom was a fae court quoting
Edgewood's bread prices. The repair is why this rule gets stated first.)

---

## 1. The five-minute path

```powershell
# 1. Scaffold. Three templates: minimal | graph | deck (see §6).
.\.venv\Scripts\python.exe scripts\new_story.py my-story --template minimal --title "My Story"

# 2. Prove it is sound before touching anything.
.\.venv\Scripts\python.exe scripts\validate_content.py --game my-story --strict
.\.venv\Scripts\python.exe -m pytest tests\test_story_content_integrity.py -q

# 3. Play it.
.\.venv\Scripts\python.exe launcher.py --game my-story
```

A fresh scaffold validates with zero errors and zero advisories, is discovered
by the picker, and is swept by every per-story test — the suite parametrises
over `registry.discover()`, not over a hardcoded list, so your story gets the
same rows the shipped ones do the moment the directory exists. The full suite
stays green with a fresh scaffold present; that claim is itself tested
(`tests/test_new_story.py`, including a test that activates the minimal
scaffold and completes a turn).

Then change one thing. The scaffold's own `README.md` carries a
"You want to change → Edit" table; the shortest useful loop is:

1. Edit `game.yaml` → `entry.opening` — the first frame of a new run, shown
   before the model says anything.
2. Edit `prompts/storyteller.md` — the narrator's voice. This file *is* the
   persona the model receives.
3. Re-run `validate_content.py --game my-story --strict` and reload.

The scaffolder refuses to overwrite an existing `games/<slug>/`, refuses bad
slugs (`SLUG_RE`: lowercase letters, digits, hyphens — the slug becomes a
directory name, a save namespace and a URL segment), and copies files rather
than generating YAML, so every teaching comment in the template survives into
your tree. **Do not duplicate those comments here or anywhere: the template
files are the reference for their own keys.**

---

## 2. The story contract — `game.yaml`

The manifest is the whole of what makes a game a game. The spec, with the
worked "tide-and-bell" example, is the module docstring of
`engine/games/manifest.py`; this section is the map, not the territory.

A manifest is a small, bounded set of things:

| Block | What it is |
|---|---|
| `id`, `title`, `version`, `blurb` | Identity — what the picker shows. `id` must equal the directory name; the directory wins on mismatch, loudly. |
| `engine_requires` | A gate checked at activation. `">=0.2.0"`; a bare version means `>=`. Refusing to load beats mis-running. |
| `paths:` | The repoint. Deep-merged over the config's `paths:` block at activation. This is most of the trick. |
| `settings:` | A SHORT allowlist of engine settings a story may declare. Anything else is a hard validation error, never a silent drop. |
| `entry:` | Where a new run starts and what it may start as. |
| `scene:` | Which server scene serves this story. Every shipped story declares the engine default by saying so — see any template's comment. |
| `ui:` | Which client plugin draws it. |
| `safety:` | The story's content rating (top-level, not under `settings:` — see §3.8). |
| `state:` / `state.yaml` | The story's own meters, clocks and tracks (§3.1). |
| `save_summary:` | Which declared values the load menu shows. Absent means the engine's own row — what both big stories use. |

Unknown top-level keys are kept verbatim in `extras` (that is how `ui:` and
`safety:` travel), so a manifest can carry data the dataclass has not learned
about.

### 2.1 The `paths.*` vocabulary

`config/default.yaml`'s `paths:` block is the engine's complete inventory of
content systems — 30 keys, every one declared and empty except `saves`. A key
listed there is a thing a story MAY ship; a key a story declares that is not
listed is a line nothing validates. Validation requires every declared path to
**exist** — except `saves` and `lore_db` (`OUTPUT_PATH_KEYS`), which the
engine writes rather than reads and which are checked on their parent.

| Group | Keys | Read by |
|---|---|---|
| The world | `locations`, `factions`, `world_schedules`, `npc_schedules`, `world_rumors`, `procgen_templates` | `engine/game/locations.py`, `engine/world/**` |
| Things, work, trade | `items`, `recipes`, `economy`, `tables` | inventory, crafting, vendors, forage/labour/boon draws |
| What happens to the player | `quests`, `encounters`, `rules`, `challenges`, `doom_effects` | quests, road danger, the rules dir (§2.2), set-pieces, doom beats |
| What the player is told | `lore`, `lore_db`, `assistant_hints`, `prompts` | RAG lore, the companion, the narrator persona |
| Pictures | `art_subjects`, `art_manifest`, `art_root`, `comfyui_templates` | `engine/media/**`; `art_root` is served at `/story-art/` by `engine/api/art.py`, never via `/static` |
| Structural systems | `clocks`, `threads`, `endings`, `decks`, `challenge_bounds`, `epilogues` | §3.3–3.6 |
| Output | `saves` | the save store appends the slug: runs land in `data/saves/<slug>/` |

Two path habits worth adopting from the shipped manifests: restate `saves:
"data/saves"` so the save root is visible in the file, and write a comment
block naming what you deliberately do NOT declare — `games/dev-story/game.yaml`
is the model.

### 2.2 Fixed filenames inside `paths.rules`

`archetypes.yaml`, `skills.yaml`, `spoilers.yaml`, `survival.yaml` and
`death.yaml` are found by fixed name **inside** the rules directory — they do
not get their own path keys, and adding one would be a second way to say the
same thing. Note the asymmetry: `clocks`, `threads` and `endings` typically
*sit* in the same directory but are addressed by their own keys, and an
undeclared key resolves to nothing regardless of what sits in the directory.

### 2.3 The settings allowlist

`settings:` merges only the keys on `SETTING_ALLOWLIST` in
`engine/games/manifest.py`, each listed there with the reason it is safe AND
the reason a story needs it. The membership test: does this number describe
the STORY's shape, and would a wrong value cost the player nothing but a
different game? Anything describing the MACHINE — endpoints, credentials,
ports, service commands — is the player's, and the dangerous sections
(`paths`, `lmstudio`, `stack`, `scene`, `game`, `comfyui`, `tts`, `stt`) are
refused with a specific reason naming the danger.

What is on the list, by family:

- **The clock**: `world.tick_hours`, `world.tick_max_hours`,
  `world.tick_interval_seconds`. Every fresh template zeroes the first two —
  nothing should tick until time is one of your mechanics.
- **Doom**: `world.evil_base_rate_per_day` (0.0 = no doom clock, phase pinned
  at `dormant`), `world.evil_engagement_slowdown_max`,
  `world.doom_resistance_decay_per_day`.
- **Reveal pacing**: `awareness.reveal_threshold`,
  `awareness.reflection_form_min`, `awareness.spoiler_gate_threshold`,
  `assistant.reflection_awareness_min`.
- **The governance chains**: `comms.interceptors`, `governance.directives`,
  `governance.commit`, `governance.post`, `governance.media` — by class name,
  choosing among shipped behaviours; an unknown name is skipped with a
  warning, so a story cannot introduce code. Every template shortens
  `governance.directives` to `[SafetyDirective, StorytellerMind]`, the two
  genuinely story-neutral shapers — the engine's fuller default chain narrates
  a doom ledger your story probably does not keep.
- **Set-piece pacing**: `media.cutscene_budget`,
  `media.cutscene_skip_after_seconds` — these only ever REDUCE what fires.

### 2.4 `entry:`

`location_id` must exist in your locations file. `archetypes:` must be
**present** even if empty: `archetypes: []` means "no classes, creation offers
a name", while omitting the key is a validation error
(`engine/games/registry.py` — declared-empty versus absent is a real
distinction). `fallback_narration` is the one canned sentence a turn shows
when the model is unreachable; omit it and the engine speaks its own
story-neutral line (it used to breathe the flagship's forest at every story's
player). `opening:` is the deterministic first frame — narration plus choices
with ids `a`/`b`/`c`, which is what the UI posts back.

### 2.5 `ui:` — the plugin, declared not inferred

```yaml
ui:
  plugin: wicked-garden
```

Empty/omitted falls back to the story's own slug — the old directory-name
match. The client contract (slug, `theme()`, `initialState`/`reduce`/
`bodyData`, the naming slots `title`/`documentTitle`/`beginLabel`/
`asideLabel`/`onboardingTitle`/`onboardingFinishLabel`, and the component
slots: `Mark`, `HeaderBadge`, `Aside`, `Ledger`, `Stage`, `Toast`,
`MenuBanner`, `Wrap`, `StartIntro`, `Wordmark`, `Ending`, `onboarding`,
`overlays`, `hideChoices`) is documented at the top of `ui/src/core/story.js`;
every field is optional and core has a working default for all of them, so a
story that ships no plugin still runs.

`ui/tests/plugin-contract.test.js` (`npm test --prefix ui`) holds that contract
against **every** shipped plugin: it harvests the legal slot names from core's
own source, so a plugin exporting a key core never reads fails, and so does a
plugin whose `theme()` import path has moved, whose two overlays claim the same
keyboard letter, or whose `reduce` rebuilds its slice for an action it should
have ignored. Add a plugin and it is covered by writing nothing.

**Borrowing is the supported path** — a `ui/src/stories/<slug>/` directory
becomes its own chunk in the COMMITTED `dist/` tree, so do not ship one for a
skin that already exists. A borrowed plugin lends its **look, not its voice**:
when `plugin != slug` the loader strips the naming slots (`title`,
`documentTitle`, `Wordmark`, `StartIntro`, `beginLabel`, `onboarding`) and
substitutes your story's own name from the catalogue, so a scratch story
borrowing the Garden's skin does not announce itself as The Wicked Garden or
invite the player through a hedge it does not have. `dev-story` borrows it
today, which is what keeps that path exercised by something shipped.

**When to stop borrowing.** Borrow while the difference between your story and
the lender's is subject matter. Build when it is *register*. NEON CITY borrowed
the Garden's skin at v0.1.0 and outgrew it: a fae court's gold contracts,
growing vines and ash hourglass are the wrong instrument for a story whose whole
surface is telemetry — black canvas, one cyan accent swapped per district, gold
mono `₵` on every price, and a five-rung heat ladder that is the game's central
pressure. That plugin is `ui/src/stories/neon-city/`, and the migration was
exactly one line of `game.yaml`. If you cannot name a rule of your story's
visual identity that the borrowed skin actively contradicts, keep borrowing.

---

## 3. The content types

One subsection per file kind: what it is, who reads it, and the sharp edges.
The teaching comments in the templates and in `games/dev-story/` go deeper on
each key — this section is what cuts across files.

### 3.1 `state.yaml` — what a value IS

`games/<slug>/state.yaml`, optional (a story that ships none runs on the
engine spine). Declares `meters`, `clocks` and `tracks`, each with bounds,
default, `visibility` and `backing`. Full treatment: [docs/STATE.md](STATE.md).
The authoring essentials:

- `backing: bag` for state the engine has never heard of; `backing: field`
  only when describing an existing engine attribute.
- `visibility`: `public` sends the number, `veiled` sends a band word and
  never the integer (numbers read as scores, scores get optimised), `hidden`
  never leaves the server. Build with `public`, ship with `veiled` where the
  fiction wants it.
- **Do not write `owners:` by hand when you have a roster** — `agents.yaml`
  grants writes and `engine/state/active.py` folds them into the schema at
  load. Permissions declared in two files disagree eventually; they did.

**The half-and-half rule** (the deck shape lives or dies by it): `state.yaml`
says what a clock IS; `data/rules/clocks.yaml` says what it DOES. Delete the
state half and the clock fails *silently* — `value_of` reads 0.0 and
`at: max` never resolves.

### 3.2 `agents.yaml` and `prompts/` — the cast

Full treatment: [docs/AGENTS.md](AGENTS.md). The authoring essentials:

- **Two agents is the switch.** `MIN_AGENTS = 2` in
  `engine/agents/pipeline.py`; the count of pipeline participants IS the flag
  that turns on plan → negotiate → commit, at the cost of one extra model call
  per turn. `pipeline: false` keeps an agent in the cast (voices owned, scopes
  filtered, writes granted) without it counting toward that threshold — the
  flagship's companion is exactly this.
- **An agent is not an NPC.** An NPC is a row in `npc_schedules.yaml` — a
  location per hour and an activity string, costing nothing. An agent has a
  persona file and a model call. Never both for the same character, or you
  get two of her.
- **The missing-prompt-file trap is now a hard validator error.** An agent
  whose persona file does not exist does not fail — it silently never plans,
  and the other agent leads every turn. That trap shipped once;
  `engine/games/validation.py::check_agents` errors on it. An agent with no
  `prompt:` at all is a warning for the same reason.
- A voice claimed by two agents, or a `negotiation:` rule naming an agent
  that does not exist, is a hard `RosterError` at load. Deleting an agent
  means deleting the rules that name it.
- `prompt:` paths are relative to the story root; the planner resolves the
  leaf under `paths.prompts`, so `prompts/storyteller.md` works from both
  directions.

The worked example with every one of these edges annotated is
`games/dev-story/agents.yaml`.

### 3.3 Decks — the day/chapter grammar

Read by `engine/content/deck.py` through `paths.decks`. **The filename is the
deck id.** The grammar — `draw`, `required` spine cards, pool `when`,
`once`, `weight`, per-beat `gate`/`band`, text beats, the per-value effect
ceilings, and the `menu`/`sequence` tags contract — is documented twice at the
right depths: `scripts/story_template/deck/data/scenes/day_one.yaml` teaches
every key inline, and `games/wicked-garden/data/scenes/README.md` is the full
exemplar treatment (including the per-value ceiling table and the
enum-as-flags convention). Do not learn it from here; learn it from those.
What cuts across:

- **Every card carries exactly one of `menu` or `sequence`.** `menu` beats
  are alternatives — exactly the chosen one resolves, and a menu card resolved
  without a choice takes the first beat and logs a WARNING. `sequence` beats
  are steps, all resolved in order. Get this wrong and a decision card applies
  every branch of the decision at once.
- **THE DEAL-TIME RULE.** A pool card's `when:` is evaluated **when the hand
  is dealt**, not when the card comes up. Gate a card on a flag that another
  card in the same deck sets, and it can never be dealt on the day that flag
  is earned — the deal already happened. Same-day consequences belong in a
  later beat of the same card, or on a *gate* inside a beat (gates evaluate at
  resolution time); next-day consequences belong on a pool card's `when:`.
  The deck walker's `rejected` table (§5.2) is where this bug becomes visible.
- Effects are clamped to per-scene ceilings derived from each value's own
  scale (`engine/challenges/spec.py`), at most four effects per outcome
  branch, and the `track` effect kind is deliberately unreachable from deck
  beats — an ending intent set by a dice table is not a scene, it is a hijack.
  Enums are spelled as one flag per value (`entry_mode_guest`), the convention
  the Garden's scenes README documents.
- A clock's `forces_scene` names a deck by its filename id. A forced scene
  naming nothing is a promise with no scene behind it, and the validator says
  so.

### 3.4 Clocks and threads

`paths.clocks` → `engine/game/clocks.py`: progress clocks with `advance_when`
predicates, threshold beats, and `forces_scene`. Wound from
`clock.advance_time`, so they move even for a player who sleeps through the
week. `paths.threads` → `engine/game/threads.py`: contracts with a lifecycle —
offer → terms → renegotiate → seal → discharge/break/expire. No card effect
seals a thread; an **agent** does, mid-scene (which has consequences for how
the walker measures them — §5.2).

The couplings that make a deck story a machine rather than a pile of files —
deck sets flag, clock watches flag, clock forces deck, thread obstructs
ending — are wired into the deck template on purpose and listed in its
README ("The couplings that make this shape work"). Trace them before
rewriting.

### 3.5 Endings and epilogues

`paths.endings` → `engine/game/endings.py`. The two gates are separate on
purpose: `requires:` (you have EARNED it) versus `completable:` (nothing still
live makes it IMPOSSIBLE), because the lock text a UI renders should tell the
player which one is in their way. `fail_forward:` names the one ending that is
always eligible — the finale must never softlock, and it must be a real
ending, not an apology. `score:` is a continuous 0–1 closeness for
foreshadowing. `beats:` is the three-beat ending module — Speak · Act · Seal —
ordinary bounded beats in the deck grammar, played once by
`endings.run_module` after `lock()`, before `epilogue.for_state` hands over
the card. The order of operations, from a REPL:

```
endings.eligible(state) -> set_intent -> lock -> run_module -> epilogue.for_state(state)
```

**Two shapes.** Variant-less: each class id under `classes:` IS an ending id
(the deck template's two-ending file is this shape). With `variants:`: a class
fans out into variant ids (E1a, E1b, …) and a variant inherits `beats:` from
its class when it declares none (the Garden's 23-variant table is this shape).
Either way, **`data/epilogues/epilogue_index.yaml` must agree with the final
ending ids exactly** — a locked ending with no epilogue row is an error and a
blank last screen. The lock itself is authored content: a finale card declares
`{type: ending_lock}` (with no id, meaning "whatever the player earned"), and
the three ending-flow effect kinds are authored-content-only — a model
composing a challenge mid-turn cannot reach them.

### 3.6 The canon dictionary and the two-direction flag rule

A story may ship `data/canon/state-dictionary.json` (or
`canon/state-dictionary.json`) — the Garden's shape, `flags.booleans` grouped
however you like. The validator runs the strongest check in the repo against
it, in both directions across decks, clocks, threads and endings:

- a flag that is **read but never written** and not canon → **error**: "this
  gate can never open";
- a flag that is **written but never read** and not canon → **error** when
  the story ships a dictionary, advisory when it does not (without a declared
  vocabulary a write-only flag is dead weight, not a provable typo).

The dictionary is how a story says "this write has a reader you cannot see
from the YAML". The teaching case, carried by both the deck template and
dev-story: `ending_gallery_unlocked` is written by every Seal beat and read
only by the **client**, so no YAML ever tests it — declaring it canon is what
keeps it from being flagged. Add every flag your decks and endings write.

### 3.7 The graph half — quests, encounters, economy, tables

The flagship's shape: a travel graph with hours on the edges, quests in arcs
(`arcs.yaml` plus one directory per arc), encounters triggered on edges,
vendor stock in `economy.yaml`, and the livelihood tables (forage, labour,
trade, boons, complications). Learn it from `scripts/story_template/graph/` —
every stub is annotated — and its README's three rules, which are the shape's
real hazards: every id must resolve (the dominant failure of this shape is
`wild_mushroom` versus `wild_mushrooms` — a reference that raises nothing and
produces a shop entry that cannot be bought); keep a free food loop (price
everything and you have authored a countdown, not an economy — the flagship
shipped that bug and `scripts/simulate.py` is how it was found); danger and
encounters must agree. Every vendor id in `economy.yaml` must be an NPC
scheduled in `npc_schedules.yaml`, or the shop has no keeper — the validator
says so.

### 3.8 `spoilers.yaml` and the `safety:` block

**Spoilers.** Fixed filename inside `paths.rules`. Rows are
`{term, instead}`: surface forms the awareness gate masks in narration until
`awareness.spoiler_gate_threshold` is crossed. Two tables layer
(`engine/lore/interceptors.py`): the story's rows first, then the engine's own
story-neutral rows for identifiers the machinery leaks out of any story
(`evil_progress` and kin) — so a story with no table still leaks no mechanics,
and a story that wants its own phrasing for a mechanical id simply declares
it and wins by ordering.

**Safety.** A **top-level** `safety:` block in `game.yaml` — not under
`settings:` — declaring `intensity: {ceiling, default}`, optionally
`fade.available` and `aftercare.default`. Full treatment:
[docs/SAFETY.md](SAFETY.md). The authoring essentials: nothing is on by
default — a story that declares nothing is inert and pays zero tokens;
declaring a rating is asking for the layer to run; raise the ceiling in your
story, never in `config/default.yaml`, which is the engine's answer for every
story that declares nothing (and moving it there fails
`tests/test_safety_shipped_games.py`). **Leave `hard_nos` out**: limits belong
to the player, set in the boundary sheet at the start of a run — a story
pre-filling them is a story deciding what its player finds unbearable.

### 3.9 Art

`art_manifest` maps ids to files, `art_root` is the directory those paths
resolve against (served at `/story-art/`), `art_subjects` carries generation
prompts. A story with none of the three runs on the procedural silhouette,
which carries a new story fine. When the prompts are written,
`scripts/art_missing.py --game <slug>` writes `data/art/MISSING-PLATES.md` —
every gap, with a ready-to-paste prompt in both dialects at the right pixel
size. `games/dev-story/README.md` § Art shows the intended workflow.

---

## 4. The AI-assisted loop — `scripts/author.py`

Drafts story content as valid YAML with the model on a leash. The contract
(the module docstring has the full statement): everything the model produces
is (1) sampled under a JSON schema derived from what the **loaders** accept —
not the docs, because the loaders are forgiving and a dropped entry loads into
silence; (2) converted to the loader's YAML shape by the tool, never by the
model; (3) validated by the shared backbone against drafts and live content
together; (4) written only under `games/<slug>/data/drafts/<kind>/`.

**The drafts convention.** `drafts/` is invisible to the validator and to
every loader (`DRAFTS_DIRNAME` in `engine/games/validation.py`) until
`--promote` moves it into the live tree — so a half-finished draft cannot fail
your build or leak into a running game, and `validate_content.py --strict`
stays green while drafts accumulate. Verified: a draft sitting in
`data/drafts/item/` does not appear in validation; after `--promote` the file
is in the live `paths.items` directory and validation is still clean.

Eleven kinds: `location`, `npc`, `item`, `quest`, `deck`, `card` (cards
appended into an existing deck), `encounter`, `rumor`, `lore`, `prompt`,
`spoilers`. Each schema enum-constrains references to the story's **own**
vocabulary — its locations, items, declared state values, skills, bands, arcs
— so an id that resolves to nothing is unsampleable rather than merely
discouraged. Inference rides the engine's own LM Studio backend; `--repair`
and `--promote` never open a connection, so the review half of the loop works
offline.

```powershell
# One kind, one brief (a file, or '-' for stdin):
.\.venv\Scripts\python.exe scripts\author.py --game my-story --draft item --brief brief.txt --count 3

# Whole content set from a story bible:
.\.venv\Scripts\python.exe scripts\author.py --game my-story --from-bible BIBLE.md

# Feed validator errors back to the model (at most 3 attempts per file):
.\.venv\Scripts\python.exe scripts\author.py --game my-story --repair

# Move validated drafts into the live tree:
.\.venv\Scripts\python.exe scripts\author.py --game my-story --promote        # all kinds
.\.venv\Scripts\python.exe scripts\author.py --game my-story --promote item   # one kind
```

`--from-bible` first asks the model for a plan — and the plan schema is shaped
by what your manifest **declares**: a story with no `paths.decks` is never
offered decks, so the model cannot plan content the engine would never load.
Then it drafts each planned entry with the bible and the already-drafted
siblings as context, in dependency order (locations before the NPCs that live
at them). A bible is freeform prose; what makes one work is concrete nouns and
counts the planner can turn into ids:

```markdown
# The Salt Archive — story bible

A lighthouse converted to a records office, kept by an archivist who indexes
things that have not happened yet. The player arrives to file a claim.

## Places (3)
The lantern room (entry), the stacks, the tide cellar. The cellar floods on a
schedule nobody will write down.

## People
The archivist (an AGENT, her own voice). Two clerks (NPCs, scheduled).

## Things
A claim form that changes while folded. A lamp that burns only borrowed oil.

## Tone
Bureaucratic dread, played warm. Nothing explicit; the ceiling is suggestive.
```

**Promote's two warnings, worth respecting:**

1. `--promote` **refuses outright while any error stands** — attributed to a
   draft, unattributed in the live tree, or a merge collision (a draft
   redefining a live id, a card aimed at a deck that does not exist).
   Promoting around a broken combined tree just moves the breakage somewhere
   the validator finds it tomorrow. It also refuses when the manifest declares
   no `paths.<kind>` for a draft — declare the path (the file or directory
   must exist) and re-run.
2. **Promote rewrites live single-file targets.** Directory kinds move the
   draft file in whole, header comment included. But single-file kinds
   (locations, NPCs, rumors, spoilers, cards-into-decks) merge into the live
   document through a YAML round-trip: the file's **leading comment banner
   survives; interior comments do not.** The CLI says so after every promote.
   If your locations file carries per-entry commentary you care about, review
   the diff before committing — or draft into a fresh file and merge by hand.

---

## 5. Verification

Four tools, in the order that finds problems cheapest.

### 5.1 The validator

```powershell
.\.venv\Scripts\python.exe scripts\validate_content.py --game my-story --strict
.\.venv\Scripts\python.exe scripts\validate_content.py --game all --strict
```

Cross-checks every id reference in the story's tree against the thing it
names, through the manifest, without activating anything. Every finding names
the file and the offending id. `--strict` promotes advisories to failures;
ship at `--strict` zero. Each check runs only when the story declares the
path — undeclared means "this story ships none of this" and the section is
skipped silently. The same logic has three faces: this CLI, doctor's Games
section, and `tests/test_story_content_integrity.py` — one home,
`engine/games/validation.py`.

### 5.2 The simulators

`--game` dispatches by shape:

```powershell
.\.venv\Scripts\python.exe scripts\simulate.py --game my-deck-story --runs 200          # deck shape -> the walker
.\.venv\Scripts\python.exe scripts\simulate.py --policy all --turns 200                 # the flagship's policy harness
```

**Graph stories:** the five policies (`baker`, `cautious`, `hero`, `pauper`,
`reckless`) are **flagship-owned by design** — they walk Edgewood's location
ids and buy from Edgewood's vendors. A non-flagship graph story is refused
with its reason; there is no headless harness for your graph story yet, which
means your balance claims are unmeasured — say so in your README rather than
asserting them. What the harness is *for* — observing every number downstream
of a clock that actually ticks — is its module docstring, and CLAUDE.md rule
10 (simulate before changing a balance constant) applies to your story's
numbers the moment such a harness exists.

**Deck stories:** `scripts/simulate_decks.py` (or `simulate.py --game`, same
thing) walks the real loaders through the same entry points the scene uses —
deal, resolve, clocks, threads, the finale chain, the epilogue — with a
seeded policy over every choice point and no model anywhere. Read the
**acceptance block** at the bottom first:

```
acceptance:
  endings reachable  2/2
  orphan cards       0
  clock fire rates   suspicion=0.35
  epilogue gaps      none
```

- **endings reachable** — an ending no run ever locked is either gated too
  tight or gated on something the walker cannot do (see the caveats below).
- **orphan cards** — a card never dealt in any run. Cross-read with the
  per-deck `rejected` reasons; a deal-time-rule bug (§3.3) shows up here.
- **clock fire rates** — how often each clock's threshold beats fired.
- **epilogue gaps** — endings locked with no card behind them. Anything but
  `none` is a blank last screen a player will meet.

And read it knowing what the walker honestly approximates: **bands are
swept** with seeded qualities so the whole range is exercised; **menu choices
are uniform**, not in-character — it measures reachability, not taste;
**threads are sealed at `--thread-rate`** because in real play an agent seals
them mid-scene, so **a clock only agents wind reads low by construction** —
the Garden's `ashen_pressure` reporting 0.0 is the walker's blind spot, not
the story's bug; and **`--max-days`** lets a small deck (a fresh scaffold's
one file) loop until its meters travel far enough to open gated endings —
the template's two endings are both reachable at the default 30. Low run
counts under-report reachability; use `--runs 200` before believing a
"never" list.

### 5.3 Doctor

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py
```

Environment, services, and a Games section that reports every discovered
story against the path vocabulary — "declares every content path it reads" is
the line yours should get.

### 5.4 The per-game tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_story_content_integrity.py -q   # every discovered story
.\.venv\Scripts\python.exe -m pytest tests\ -q                                  # everything
```

The per-story tests parametrise over discovery, so your story is swept the
moment it exists: content integrity, prompt identity
(`tests/test_prompts_story_neutral.py` — every discovered story must ship its
own `prompts/storyteller.md`, and the persona the model receives must be that
file; the engine's neutral fallback exists for runtime, not as a way to pass
this test), the safety declaration (`tests/test_safety_shipped_games.py`),
the story surface. Run the full suite
before calling the story done; it is the same bar the shipped stories clear.

---

## 6. The worked examples index

| Where | What it teaches |
|---|---|
| `games/dev-story/` | **The full worked example.** One small working instance of every subsystem — thirteen locations, eight scheduled NPCs, a two-agent pipeline, a clock that forces a scene, a thread with renegotiations, three gated endings and their epilogues — each file annotated at a depth a template cannot afford. When a mechanism is unclear, it is running here with the lights on. |
| `games/wicked-garden/` | **The deck exemplar**, full scale. Its `data/scenes/README.md` is the deck grammar's reference treatment; its `data/canon/` established the dictionary shape; its manifest shows the `safety:` block and the "what this story deliberately does not ship" comment style. |
| `games/clockwork-dark/` | **The graph exemplar**, full scale. The travel graph, arcs, encounters, the livelihood economy, doom — 5,300 lines of the shape the engine's clock was tuned for. |
| `scripts/story_template/minimal/` | The smallest thing that validates and plays a turn. Start here unless you already know your shape. |
| `scripts/story_template/graph/` | The flagship's skeleton with Edgewood removed. |
| `scripts/story_template/deck/` | The Garden's skeleton, one working instance of each coupling. |

The relationship, and the maintenance rule that keeps it true: **the templates
are distilled from dev-story** — when a subsystem changes shape, fix dev-story
first (the suite runs its rows, so it cannot silently rot), then re-distil the
templates. A template that drifts from the bench teaches the old engine.

Version: v0.1.1 [2026-08-14]
