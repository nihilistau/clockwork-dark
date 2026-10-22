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

On Linux (every command in this guide has the same shape: `.venv/bin/python`
for `.\.venv\Scripts\python.exe`, and `/` for `\`):

```sh
.venv/bin/python scripts/new_story.py my-story --template minimal --title "My Story"
.venv/bin/python scripts/validate_content.py --game my-story --strict
.venv/bin/python -m pytest tests/test_story_content_integrity.py -q
.venv/bin/python launcher.py --game my-story
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
slugs (`is_valid_slug`: lowercase letters, digits, hyphens, and no Windows
device name such as `con` or `nul` — the slug becomes a directory name, a save
namespace and a URL segment, on every platform), and copies files rather
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
| `state:` / `state.yaml` | The story's own meters, clocks and tracks (§3.1). |
| `save_summary:` | Which declared values the load menu shows. Absent means the engine's own row — what both big stories use. |
| `endless:` | `true` for a story with no ending, by design (§2.6). Absent means finishable. |

Unknown top-level keys are kept verbatim in `extras` (that is how `ui:` and
unknown keys travel), so a manifest can carry data the dataclass has not learned
about.

### 2.1 The `paths.*` vocabulary

`config/default.yaml`'s `paths:` block is the engine's complete inventory of
content systems — 35 keys, every one declared and empty. A key listed there is
a thing a story MAY ship; a key a story declares that is not listed is a line
nothing validates. Validation requires every declared path to **exist** —
except `lore_db` (`OUTPUT_PATH_KEYS`), which the engine writes rather than
reads and which is checked on its parent.

**`paths.saves` is not a story key** (since v0.20.0). Saves are the engine's:
they live under `storage.root` (`config/default.yaml`, `data` by default, or
`CLOCKWORK_DATA_DIR`), at `<root>/saves/<slug>/`, and the store appends the
slug for you. A manifest that still declares `saves:` plays, but the key is
ignored (`config_overlay` drops it) and `scripts/validate_content.py` and the
doctor give it an advisory — which also says the VALUE is ignored when it is
not `data/saves`. Delete the line. The owner moves saves with `storage.root`
in `config/local.yaml`, never a story.

| Group | Keys | Read by |
|---|---|---|
| The world | `locations`, `factions`, `world_schedules`, `npc_schedules`, `world_rumors`, `procgen_templates` | `engine/game/locations.py`, `engine/world/**` |
| Things, work, trade | `items`, `recipes`, `economy`, `tables` | inventory, crafting, vendors, forage/labour/boon draws |
| What happens to the player | `quests`, `encounters`, `rules`, `challenges`, `doom_effects` | quests, road danger, the rules dir (§2.2), set-pieces, doom beats |
| What the player is told | `lore`, `lore_db`, `assistant_hints`, `prompts` | RAG lore, the companion, the narrator persona |
| Pictures | `art_subjects`, `art_manifest`, `art_root`, `comfyui_templates` | `engine/media/**`; `art_root` is served at `/story-art/` by `engine/api/art.py`, never via `/static` |
| Structural systems | `clocks`, `threads`, `endings`, `decks`, `challenge_bounds`, `epilogues` | §3.3–3.6 |
| The phone | `social` — a DIRECTORY, not a file (v0.22.0): `creation`, `population`, `behaviours`, `apps`, `relationships`, `media`, `venues` and `games` `.yaml`, found by fixed name, plus `words.txt` | `engine/social/` (§3.15). A story that does not declare it pays nothing: no `engine.social` submodule is imported and its payload carries no `phone` key |

**A location edge's `minutes` (v0.23.0).** An edge in `paths.locations` may carry
`minutes`, a whole number 0-59, for a leg shorter than an hour (READ RECEIPTS'
one-minute doors between rooms). An edge with `minutes` defaults `hours` to 0,
not 1, and `GameEngine.move_to` charges `hours + minutes/60` through the clock;
the travel label reads "Kitchen, 1 min", and the move receipt carries a
`minutes` key only when it is non-zero. The loader refuses (logs an error and
drops the edge) a `minutes` outside 0-59, one that is not a whole number, and an
edge whose `hours` and `minutes` are both 0. An edge with no `minutes` is read
exactly as before. `validate_content.py` reports a malformed `minutes` edge as an ERROR, and a one-way-less
minutes edge's mirrored return keeps its `minutes`. The graph's own flagship-style `hours: 0` edges are untouched.

A path habit worth adopting from the shipped manifests: write a comment block
naming what you deliberately do NOT declare — `games/dev-story/game.yaml` is
the model.

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
(`paths`, `llm` and its pre-v0.19 name `lmstudio`, `stack`, `scene`, `game`,
`comfyui`, `tts`, `stt`) are refused with a specific reason naming the danger.

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
  `governance.commit`, `governance.post` — by class name, choosing among
  shipped behaviours; an unknown name is skipped with a warning, so a story
  cannot introduce code. Every template shortens `governance.directives` to
  `[StorytellerMind]`, the genuinely story-neutral shaper — the engine's fuller
  default chain narrates a doom ledger your story probably does not keep.
- **The narrator's disposition**: `storyteller.cruelty_bias`,
  `storyteller.reward_generosity` — optional; a story that sets neither gets
  no disposition line at all.
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

**An opening choice that MOVES, SPENDS or RISKS anything must declare an
`intent`**, exactly as a narrated choice does (`engine/game/intents.py`):

```yaml
      - id: a
        text: "Step through"
        intent: { action: travel, target: gate_of_briars }
```

Judge it per option. A choice that walks somewhere carries `travel`; one that
buys carries `buy`; one the fiction puts a real risk on carries `check`. A
choice that talks, looks or listens carries **nothing**, and that is the
ordinary case — an intent that resolves nothing is noise.

This is the one place the rule is easy to forget, because the opening is
written by an author rather than sampled from a grammar: nothing constrains it
at authoring time, and `execute_intent` re-checks it against the live world, so
a mistyped destination is a silent refusal in a log during a playtest while the
narrator walks the player somewhere the save disagrees about. It was forgotten
for three of the four shipped stories — The Wicked Garden's "Step through" *is*
the crossing the whole first act hangs on and declared nothing, so the model
narrated the crossing and the save still read `mortal_threshold`. The mechanism
had only ever been authored into the flagship's opening.

Two traps worth knowing before you write one. A `flag` intent is scoped to the
**current quest stage**, and at turn 0 no quest has ticked, so
`allowed_narrative_flags` is empty and an opening `flag` intent always refuses —
let the quest raise its own flag. And a verb only exists where the engine can
honour it, so check what your story actually affords before declaring it:

```powershell
.\.venv\Scripts\python.exe -c "from engine.games import registry; registry.activate('my-story'); from engine.game.procgen import new_game_state; from engine.game.intents import legal_intents; s=new_game_state(seed=1); print([(v.action, list(v.targets)) for v in legal_intents(s)])"
```

```sh
.venv/bin/python -c "from engine.games import registry; registry.activate('my-story'); from engine.game.procgen import new_game_state; from engine.game.intents import legal_intents; s=new_game_state(seed=1); print([(v.action, list(v.targets)) for v in legal_intents(s)])"
```

`tests/test_turn_intent_per_game.py` holds all of this against **every**
discovered story: each authored opening intent is driven through a real
`run_turn` and the outcome read back off `GameState`, and any story with a
travel graph must be able to move. Your story is swept the moment its directory
exists.

**When one verb is not the whole moment: `deed`, `on_pass`, `on_fail`
(v0.16).** An opening choice may carry three more keys beside its `intent`
(`engine/game/authored_choice.py`). HUE & CRY's is the worked example: a
stranger who bolts from a Lantern has rolled stealth *and* done something the
Watch can file, and one who holds out their wrists is arrested on the quay,
not walked to the gaol.

```yaml
      - id: a
        text: "Duck the lamp and lose yourself in the crowd"
        intent: { action: check, target: stealth, difficulty: standard }
        deed: resisting_watch          # a deed kind your law file lists
        on_pass:
          text: "You are behind a cart of tallow, then simply somewhere else."
        on_fail:
          text: "You make it four steps."
          encounter: watch_stop        # begins this scene, on the spot
      - id: c
        text: "Hold out your wrists and go quietly"
        on_pass:                       # no intent: the choice always passes
          text: "You hold out your wrists."
          effects:
            - { type: report, deed: pickpocket, guise: magpie, jurisdiction: quay, precision: 0.3 }
            - { type: arrest }
```

- `deed:` is committed after the intent, pass or fail, through
  `law.commit_deed` -- witnesses rolled on the LAW stream exactly as for a
  lift, with the check's margin when the intent was a check. Needs a Law
  (§3.11); a kind the law file does not list commits nothing.
- `on_pass` applies when the choice passed -- its `check` came up `success`
  or better (a `partial` is a fail here), or, for any other intent or none,
  the intent went through -- and `on_fail` otherwise. Each is `{text,
  effects, encounter}`, all optional. `text` is handed to the narrator as the
  outcome's line, followed by what any Law effect said in its own words (the
  gaol's name, a guise's label, a clarity word) and whether the deed was
  seen. `effects` are bounded like a card beat's -- the ordinary types, the
  structural ones (`report`, `quash_reports`, `law_discharge`, ...) -- plus
  `arrest`, which ONLY an authored choice may carry
  (`spec.AUTHORED_CHOICE_EFFECT_TYPES`): a card, a thread, a set-piece and a
  model-composed challenge all drop it. `encounter` begins that scene through
  the same door the patrol uses, unless one is already open.
- A **refused** intent applies nothing: the player did not do it.
- The button says it first. A choice with an intent gets its intent's chip
  as any choice does; one with NO intent whose `on_pass` carries `arrest` is
  chipped `arrest · <the gaol's name>` (`default_state._label_authored`) --
  HUE & CRY's (c) reads `arrest · The Lantern House`. Nothing else in the
  authored keys is chipped; display only, it runs nothing.
- The model can never carry any of this. The keys are read from your manifest,
  by choice id, and only while the player is choosing from the opening frame
  (`default_state.resolve_authored_choice`); a narrated choice that writes
  `deed:` gets nothing, and the keys never reach the client.
- An opening with none of the keys is exactly what it was.
  `scripts/validate_content.py` (`check_opening`) names a deed the law does
  not list, an encounter nobody declared, and an effect an authored choice
  may not use.

### 2.5 `ui:` — the plugin, declared not inferred

```yaml
ui:
  plugin: wicked-garden
```

Empty/omitted falls back to the story's own slug — the old directory-name
match. The client contract (slug, `theme()`, `initialState`/`reduce`/
`bodyData`, the naming slots `title`/`documentTitle`/`beginLabel`/
`asideLabel`/`onboardingTitle`/`onboardingFinishLabel`/`saveMeta` (one line
of the story's own words on a save row; since v0.21.0 core prints none of
its own), and the component
slots: `Mark`, `HeaderBadge`, `Aside`, `Ledger`, `Stage`, `Toast`,
`MenuBanner`, `Wrap`, `StartIntro`, `Wordmark`, `Ending`, `onboarding`,
`overlays`, `hideChoices`, and since v0.22.0 the two whole-screen slots
`PlayScreen` and `NewRun`, below) is documented at the top of `ui/src/core/story.js`;
every field is optional and core has a working default for all of them, so a
story that ships no plugin still runs.

`ui/tests/plugin-contract.test.js` (`npm test --prefix ui`) holds that contract
against **every** shipped plugin: it harvests the legal slot names from core's
own source, so a plugin exporting a key core never reads fails, and so does a
plugin whose `theme()` import path has moved, whose two overlays claim the same
keyboard letter, or whose `reduce` rebuilds its slice for an action it should
have ignored. Add a plugin and it is covered by writing nothing.

**Declare nothing and you get the engine's own skin.** `ui/src/stories/_engine/`
is a real plugin that deliberately has no world: a quiet warm-neutral palette,
a wordmark that renders your story's name, onboarding that explains what a turn
is rather than what your fiction is, and core's map. It is the honest starting
point for a new story and a perfectly good permanent home for one that never
wants its own look. `dev-story` wears it.

This replaced a bad choice. A story with no plugin used to run on bare core —
no theme, no wordmark — so it looked broken rather than plain, and the only
cure was to borrow another STORY's plugin and inherit its voice along with its
spacing.

**Borrowing another story's plugin is still supported and now rarely right.** A
`ui/src/stories/<slug>/` directory becomes its own chunk in the COMMITTED
`dist/` tree, so do not ship one for a skin that already exists — but borrow
`wicked-garden` only if your story genuinely wants to look like the Garden, not
merely to look like *something*. For that, `_engine` is the answer. A borrowed
plugin lends its **look, not its voice**:
when `plugin != slug` the loader strips the naming slots (`title`,
`documentTitle`, `Wordmark`, `StartIntro`, `beginLabel`, `asideLabel`,
`saveMeta`, `onboarding`, **`overlays`**, **`PlayScreen`** and **`NewRun`**) and substitutes your story's own name from the
catalogue, so a scratch story borrowing the Garden's skin does not announce
itself as The Wicked Garden or invite the player through a hedge it does not
have. Nothing shipped borrows another story's plugin today — `dev-story` moved
to `_engine` when the engine got its own — so this path is held by
`ui/tests/plugin-contract.test.js` rather than by a running game. If you borrow,
you are the one exercising it.

**Borrowing does not lend overlays, and that is deliberate.** An overlay looks
like a visual slot and is not — it is a whole screen written against one
story's concepts. A funeral-barge test story borrowing the Garden was
offering "The court" and "The mirror pool", and the court drew Sophia and
Mother Briar, who are not aboard and do not exist in it. A screen rendering
another story's cast is worse than no screen, so a borrower gets none. If your
story wants overlays, that is the signal to ship your own plugin.

**`PlayScreen` and `NewRun` — a story's own screens (v0.22.0, READ RECEIPTS).**
A plugin may replace the play screen wholesale. `PlayScreen` takes
`{state, sessionId, busy, onAct, onOpenMenu, onOpenSaves, blocked}` and is
drawn in place of core's `Play` (`blocked` is true while core's menu,
settings, an overlay or a cutscene is up: a screen's own window-level keys,
such as a deck's arrows, stand down under it); core keeps the connection banner, the pause menu
(Escape -- but Escape in one of the screen's text fields only leaves the
field, so the menu never opens over half a message), saves and settings
around it, and offers it no overlays (no map, no clue board, no shortcut). `onAct({action, target, args, text})` sends one
phone action as `phone_action` with the session's id -- there is no
`onChoose` and no `onCustom` -- and never sets `busy`. Core sends one action
at a time; one answered `turn_error {busy}` (a voicing pass committing
holds the turn lock for milliseconds) is re-sent once after 150 ms without
reaching the store, and a second busy answer reaches it, so the plugin can
keep what the player composed (`ui/src/core/socket.js::createPhoneSender`).
`onAct` returns whether the action was taken, and an action that never
reached the server (queued at a disconnect, or cut off waiting for its
re-send) comes back to `reduce` as `{type: "PHONE_DROPPED", intents}`:
nothing the player composed is dropped in silence. The plugin does not
re-send a busy answer itself (core already has): READ RECEIPTS' `usePhoneAct`
turns the second busy, a `PHONE_DROPPED` and a refused `onAct` into "Not
sent — tap to retry" with the words kept. An answer core credits to no
action (a timed-out action's late one) reaches `reduce` marked `stale: true`,
so a plugin never counts it as its own action's answer.
The background pushes `phone_message` and `media_ready` are the plugin's to
reduce: core's reducer keeps nothing of them. `NewRun` takes
`{onBegin(creation), onCancel, busy, error}` and is opened by the start
screen's Begin in place of starting at once (the start screen then shows no
name, class or seed of its own); it reads its form with
`fetchCreation()` (`GET /api/social/creation`), and `onBegin(creation)`
starts the run with `{player_name: creation.name, creation}` -- a refusal
names its field in `error`. Both are **stripped when borrowed**, like
`overlays`: each is a whole screen written against the payload's `phone`
block, which a borrowing story's payload lacks.

**When to stop borrowing.** Borrow while the difference between your story and
the lender's is subject matter. Build when it is *register*. NEON CITY borrowed
the Garden's skin at v0.1.0 and outgrew it: a fae court's gold contracts,
growing vines and ash hourglass are the wrong instrument for a story whose whole
surface is telemetry — black canvas, one cyan accent swapped per district, gold
mono `₵` on every price, and a five-rung heat ladder that is the game's central
pressure. That plugin is `ui/src/stories/neon-city/`, and the migration was
exactly one line of `game.yaml`. If you cannot name a rule of your story's
visual identity that the borrowed skin actively contradicts, keep borrowing.

#### `ui.panels` — the engine panels

```yaml
ui:
  plugin: _engine          # unchanged meaning
  panels:                  # optional. Omitted: the data-gated defaults.
    - wanted               # a bare id: its default region
    - casing
    - job
    - id: people
      region: stage        # a mapping: the id and, optionally, a region
    - encounter
```

The client reads it through the catalogue (`ui/src/core/story.js` sets
`story.panelDeclaration`; `ui/src/core/panels/resolve.js` places the panels).
Every panel in the table below is built and drawn (v0.21.0); a panel whose
component the client has not got is resolved and simply not drawn.

- **Omitted:** every data-gated panel (`wanted`, `job`, `casing`,
  `negotiation`, `rolls`) in its default region, in registry order, and no
  opt-in panel. A data-gated panel renders only when its payload key is
  present, which only a story declaring the system sends.
- **Present:** exactly the listed panels, in the listed order within each
  region, and nothing else. `panels: []` turns every core panel off.
- **`region:`** names where a panel is drawn, from the regions it allows:

| Panel | Default region | May be drawn in | Gate | Fed by |
|---|---|---|---|---|
| `wanted` | `ledger` | `ledger`, `shelf` | data | `paths.law` |
| `job` | `shelf` | `shelf`, `ledger` | data | `paths.jobs` |
| `casing` | `ledger` | `ledger`, `shelf` | data | `paths.premises` |
| `negotiation` | `shelf` | `shelf` | data | the negotiate agent |
| `rolls` | `toast` | `toast` | data | skill checks |
| `people` | `stage` | `stage`, `ledger` | declared | the people route |
| `encounter` | `shelf` | `shelf` | declared | `paths.encounters` |

**Validation.** ERROR (activation refuses the story; `validate_content.py`
reports it too): a non-list `panels`; an entry that is neither a string nor a
mapping; a mapping with a key other than `id`/`region`; an unknown id; a
duplicate id; a region the panel is not drawn in. ADVISORY (a WARN in
`validate_content.py --warnings` and `doctor.py`): `wanted`, `job`, `casing`
or `encounter` listed by a story that declares no `paths.law`, `paths.jobs`,
`paths.premises` or `paths.encounters`: it will never render.

**`ownsPanels`, the plugin's half.** A plugin that draws a system itself
says so, by registry id, and core does not draw it twice:

```js
export default { /* ... */ ownsPanels: ["rolls", "encounter"] };
```

What is drawn is the declaration (or the defaults) minus `ownsPanels`. The
flagship owns `["rolls", "encounter"]` (its dice toast and encounter panel),
NEON CITY `["encounter"]` (its stage draws the approaches). It is a visual
slot, so it is KEPT when another story borrows the plugin: the borrower
inherits the drawing, so it inherits the claim. `ui.panels` is the story's,
never the plugin's: `loadStory` writes `panelDeclaration` last, and
`ui/tests/plugin-contract.test.js` fails a plugin that exports one. The
contract is at the top of `ui/src/core/story.js`; the registry is
`ui/src/core/panels/registry.js`, kept equal to `UI_PANELS` by
`tests/test_ui_panels_manifest.py`.

### 2.6 `endless:` — a story with no ending

`endless: true` (v0.22.0) says the story has no ending on purpose: it is
played, not finished. It is a top-level manifest key, kept in `extras` and
read by `GameManifest.endless`; absent (or `false`) means the story is
finishable.

What it refuses (`StoryValidator.check_endless`, errors): a value that is not
`true` or `false`, and, with `true`, a declared `paths.endings` or
`paths.epilogues` — an endless story with an ending is a contradiction.

What it answers to: `tests/test_finales.py` holds every shipped story to one
of two lists. A slug in `FINALE_SLUGS` must be playable to an epilogue and
must not say `endless`; any other shipped story must say `endless: true` and
declare no endings or epilogues
(`test_an_endless_story_declares_no_ending_and_says_so`). A new story is
therefore either added to `FINALE_SLUGS`, with an ending it can reach, or
declared endless.

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

**`memory:` — subjects the narrator must not lose track of.** Optional, and
separate from the value table because a topic is a memory KEY rather than a
declared value:

```yaml
memory:
  topics: [the_ledger_case, the_thing_in_the_cellar]
```

Every turn, the engine recalls what it knows about each person in the room,
about the room itself, and about each declared topic, and hands all three to
the narrator (`engine/agents/prompts.py::memory_blocks`). People and places
need no declaration — they are recalled by their own ids automatically. A
topic is for the rest: an open case, a rumour, a thing with no location and no
face. A story that declares none pays nothing.

Memory is written the way it always was — engine events write directly, the
model proposes deltas that are validated — and read two ways: unprompted in
the blocks above, and on demand through the `recall_subject` skill. A durable
detail that must not fade ("the shutter is still off its hinge") is a **note**
(`ledger.note`), not a fact: facts decay and archive by design, notes do not.

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
- **A menu beat's `text` is the narrator's; its `label` is the player's**
  (v0.21.0). The narrator is handed the full `text` ("render it, do not
  replace it"), and the intent enum names the beat by it. The player's chip,
  and the hint under a card chip, read the beat's `label:` (at most 120
  characters) when it has one, otherwise the first sentence of `text` with
  every backticked span removed (`engine/content/director.py::player_label`).
  So a beat whose text carries an author's note -- a `` `flag` `` name, "Sets
  ...", "Resolve with ...", "Always.", "RARE" -- needs a `label:`, or the
  note is what the player reads; `validate_content.py` and `doctor.py` print
  an advisory for such a beat (`StoryValidator._check_beat_label`).
- **THE DEAL-TIME RULE.** A pool card's `when:` is evaluated **when the hand
  is dealt**, not when the card comes up. Gate a card on a flag that another
  card in the same deck sets, and it can never be dealt on the day that flag
  is earned — the deal already happened. Same-day consequences belong in a
  later beat of the same card, or on a *gate* inside a beat (gates evaluate at
  resolution time); next-day consequences belong on a pool card's `when:`.
  The deck walker's `rejected` table (§5.2) is where this bug becomes visible.
- Effects are clamped to per-scene ceilings derived from each value's own
  scale (`engine/challenges/spec.py`), at most four effects per outcome
  branch, and text is capped. AUTHORED text -- a story's own file: card and
  beat text, an outcome's text, a set-piece's steps and prompt -- is capped
  at `spec.MAX_AUTHORED_TEXT` (1500 characters; a card title at 120); the
  smaller `spec.MAX_TEXT` (400) bounds only what a model composes mid-turn.
  Past a cap the loader cuts; since v0.17 the validator names every cut in a
  story's own files as an error (`check_truncated_content`), so shorten or
  split the line -- no shipped line comes near it (the longest, 899). The
  narrator reads every character of it, so a note to yourself or to the
  engine (`RUNTIME:`, "NOTE: the design...", "open the thread through the
  thread tool") goes in a YAML comment beside the card or beat, never in
  its `text`: the narrator never acts (AGENTS.md rule 1), and
  `tests/test_no_author_meta_in_narration.py` fails a story that forgets.
  The `track` effect kind is deliberately unreachable from deck
  beats — an ending intent set by a dice table is not a scene, it is a hijack.
  Enums are spelled as one flag per value (`entry_mode_guest`), the convention
  the Garden's scenes README documents. A beat may write a **`ledger_fact`**
  (since v0.16: it is in `STRUCTURAL_EFFECT_TYPES`, so authored content
  may and a model-composed challenge may not): the `card` verb hands the
  beat the session's ledger, so the fact lands, and a gate on `disposition`
  can hold. HUE & CRY's accusation remembers who the Magpie is this way.
- A clock's `forces_scene` names a deck by its filename id (or a single card
  by its card id, which is placed first in the hand). A forced scene naming
  nothing is a promise with no scene behind it, and the validator says so. A
  declared world event may force one too — `forces_scene:` on an entry of the
  `world_schedules` `events:` block (§3.7) — and it is kept by the same
  director through the same query (`clocks.forced_scenes`). The difference is
  lifetime: a clock beat's promise stands for the rest of the run, an event's
  only while the event is active, so a player who takes no turn during its
  window never sees it.
- **A forced deck waits for its own `when:`** (v0.17). A deck that is
  forced (by a clock beat or an event) and also declares a top-level `when:`
  is dealt only while that `when:` holds. Until then it WAITS: it is neither
  dealt nor retired, and any other deck that is due (a scheduled one, or a
  repeatable one such as an interrogation dealt on arrest) may deal
  meanwhile. Once the `when:` holds while the promise still stands, it
  deals. If the forcing ends first (the event expires) before the `when:`
  ever held, it is simply not dealt. So a fair forced by its event and gated
  `at_location: gallows_green` meets the player on the green, not wherever
  they happen to stand. Because a `when:` also SCHEDULES a deck on its own,
  put the event in it too (`event_active: <event id>`), or the deck deals
  whenever the rest of its `when:` holds, fair or no fair. A forced single
  CARD ignores its deck's `when:` and is placed in the hand as before. A
  `repeatable` deck forced AS A DECK by a declared world event and gated on
  its own `when:` re-arms on that `when:` alone, not on the event (still
  active when the player walks off the green): so HUE & CRY's fair is dealt
  again on each return to the Green, with `once` on every card that must not
  repeat (`data/scenes/fair_day.yaml`). The event stays the trigger for a
  row that forces a single card (which deals whatever the `when:` says, so
  it must hold the deck spent while its event stands), and a clock beat's
  row, which is permanent, never lets its deck re-arm at all.
- **A card that takes hp can kill, on that card** (v0.17). When a card's
  beats lower hp to the death threshold, `encounter.check_death` runs on that
  card: `death.yaml`'s terminal block (locking its ending) or its respawn.
  Either way the rest of the hand is dropped, the same as an open encounter,
  and the narrator is told on that turn.
- **A deal waits for whatever owns the turn.** The director deals nothing
  while a hand is open, a job is under way, an encounter is open, or (a story
  declaring `paths.social`) an in-person social scene is open. The
  encounter covers a Lantern's stop, which the Law's patrol can open in the same
  turn an arrival makes a deck due. A card can open an encounter, never the
  reverse. The deal is not spent by waiting: it lands on the first turn
  after, if its `when:` still holds. So a deck scheduled on arrival
  (HUE & CRY's initiation) is met after the stop, not over it.
- **A deck is dealt once, unless it says `repeatable: true`.** Every deck is
  spent by its deal (`deck_played_<id>`, and for a forced deal
  `scene_played_<id>`), so a scheduled deck does not re-deal on every turn its
  `when:` stays true. A top-level `repeatable: true` re-arms it — but only
  once its trigger has been seen FALSE since the deal: its `when:` fell, or no
  active world event forces it any more. One deal per rising edge. A deck
  gated `when: {in_custody: true}` deals on the first arrest, not again while
  the player is still held, and again on the second arrest. A deck forced by
  a recurring event (a market day) re-deals on the next occurrence only if the
  event LAPSES in between and the player takes a turn during the lapse: an
  event that runs back to back, or a lapse slept straight through, leaves no
  false edge to see, and the deck stays spent. Edges are read at the turn
  (`director.rearm`, the start of `ensure_scene`) — the only moment a deal can
  happen — so a fall and a rise inside one turn deal nothing new. A deck
  forced by a CLOCK never re-arms: a clock beat's promise is permanent.
  `once` cards stay spent across re-deals; give a repeatable deck cards that
  can be dealt again. `repeatable` must be a bool — the validator reports
  `repeatable: "yes"`, which would otherwise load as one-shot.

  ```yaml
  # data/scenes/the_cells.yaml
  id: the_cells
  draw: 1
  when: { in_custody: true }
  repeatable: true
  cards: [...]
  ```

  HUE & CRY's interrogation (`data/scenes/interrogation.yaml`) is the shipped
  example, and it shows two rules any deck in the cells lives by. A card
  cannot write custody (`arrest` and `release` are not card effects), so the
  fine and the days fixed at the door stand: such a deck moves the FILE
  (`quash_reports`, `report`), never the sentence. And while a card is open
  `pay_fine` and `serve` are hidden (the card is the turn), so every card
  there needs an answer that asks no roll, or a held player is stuck behind
  a hand. A deck scheduled on custody deals on the same turn an arrest closes
  the arrest encounter, and the re-arm is read before any guard, so a release
  seen only under a later encounter still counts.

### 3.4 Clocks and threads

`paths.clocks` → `engine/game/clocks.py`: progress clocks with `advance_when`
predicates, threshold beats, and `forces_scene`. Wound from
`clock.advance_time`, so they move even for a player who sleeps through the
week. `paths.threads` → `engine/game/threads.py`: contracts with a lifecycle —
offer → terms → renegotiate → seal → discharge/break/expire. No card effect
seals a thread, and nothing in `engine/agents` does either: the **player**
does, with the `bargain` verb (`strike_bargain`,
`engine/skills/builtin/scenes.py`), on a turn no card holds. It seals the
template **as written** — the renegotiate step is **NOT WIRED**
(`threads.renegotiate`/`transform` have no production caller; see
docs/GOVERNANCE.md), so a template's `renegotiations:` block is never reached
in play. Because the walker plays cards rather than verbs, it seals threads
itself (§5.2). A template may declare
`discharge_requires:` — a condition from the shared grammar, e.g.
`{min_gold: 12}` — and until it holds the `discharge` verb does not offer the
thread and settling it is refused: a bribe whose `on_discharge` pays the
sergeant must not be settled from an empty purse, because the `gold` effect
clamps at zero. A template's own `requires:` (same grammar) gates STRIKING
it: until it holds the `bargain` verb does not offer it and `strike_bargain`
refuses. HUE & CRY's `brask_bribe` is the worked example of both, and its
`quash_reports` shows that thread hooks are bounded as authored content.

A template is struck **once a run** by default: whatever became of it, a
struck template is never offered again, and `strike_bargain` refuses it too
(before v0.15 only the verb stopped offering it). `repeatable: true` (a bool
— the validator refuses `"yes"`, which would load as once-a-run) makes it a
line of credit instead: offered again as soon as no copy of it is open, and
never while one is — two open copies would be one debt counted twice.
Whether it is offered again after a *break* is its own `requires:`' business.
`on_seal:` effects apply the moment it is struck (a loan pays out there).
`broken_text:` is the narrator's line when it breaks — journalled once,
through `engine/game/moved.py` (kind `promise`), the turn it came due or was
cut; without it a thread that lapses on the day tick breaks in silence, its
`on_break` applied and nothing in the prose saying why. It is told on ANY
break -- one that came due, one broken early, one cut -- so word it true for
all of them ("you welshed on...", not "it came due"). HUE & CRY's
`pell_advance` and `marrow_slate` are the worked example of all three, and
every HUE & CRY thread with an `on_break` carries one (asserted).
`strike_bargain` refuses in words that say which gate is shut: already open,
already struck once, or not here and now (`threads.strike_refusal`). A
template may add `refusals: [{when, text}]`: when its `requires:` fails and
a row's `when` holds, the first such row's `text` is the refusal instead of
"not here and now" -- the story's own words for the real reason (validated
like any condition, no ledger predicates).

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

**A door per ending, gated on the ending** (HUE & CRY, v0.17). A story whose
endings each have their own door locks each BY NAME (`{type: ending_lock,
ending: <id>}`; an id-less lock can resolve to the fail-forward) and opens the
door only while that ending is earned, by asking the ending itself: a card's
`when: {ending: {eligible: <id>}}`, a stage's `complete_when` clause of the
same. The gate is then written once, in endings.yaml, and a door cannot open
on a state the gate refuses -- a lock the engine would refuse anyway, but
after the card had already told the player it happened. Such a card need
not be `once` in a repeatable deck: declining it must not close the ending,
and it cannot be walked through twice (a locked run never locks again).
**A locked run is dealt no door** (`deck.eligible_cards`, v0.17): a POOL card
whose beats carry an `ending_lock` anywhere is not dealt once the run's
ending is locked -- `{ending: {eligible: <id>}}` reads the gate, not the
lock, so without this a re-offered door came back after the story had
ended. A required card is the spine and is dealt regardless (the Garden's
finale spine is re-dealt after its lock, by design). A deck whose own `when:`
reads an ending's eligibility may therefore come due and deal nothing after
the lock (spent, as any deck with no eligible card).
**A card that locks the ending AND plays its module ends its hand**
(`director.resolve`, v0.17): nothing after it in that hand is presented. A
finale that locks on one card and plays the module on a later one (the
Garden's F3/F4, epilogue cards after) runs on as before. Cards come one at a
time, so two doors in one hand is a choice the player cannot see: when two
endings can be open at once, offer both as beats of ONE card (HUE & CRY's
badge card: take the badge, or `clear_my_name`, the second gated on its own
ending) and keep the other door's card for the case where only it is open.
HUE & CRY's `data/rules/endings.yaml` header lists each door; `tests/test_finales.py`
drives each ending through its door (`ENDING_DOORS`) and walks each earned
one's door with its gate unmet (`UNEARNED_DOORS`).

**A death that ends the story in an ending.** `death.yaml` (inside
`paths.rules`, §2.2) may declare

```yaml
terminal:
  when: { in_custody: true }   # a condition in the shared grammar
  ending: the_rope             # a declared ending id
  text: "They do not let you wake."
```

`when` is read at the moment of death, BEFORE any respawn hours. When it
holds, the run ends (`state.ended`), `ending` is locked and its Speak · Act ·
Seal module plays, so `epilogue.for_state` shows its card on that turn.
Otherwise the ordinary `respawn:` runs. The lock **skips the ending's own
`requires:`/`completable:`** — the death is its eligibility, so "this death
ends in The Rope" always works; give such an ending a `requires:` only if you
also want the finale's ordinary lock to reach it. A run already locked to
another ending keeps that one (a lock is never walked back) and its module
plays instead. Nobody wakes from a terminal death: no hours, no respawn, no
move. Custody stays (a prisoner who dies is not released); the dying
encounter is closed; a fall that killed mid-job closes the job `hurt`. A
finished run stops dying: once `state.ended` is set, later hours at hp 0 run
no death rules at all. The skip is the `ending_lock` effect's `terminal:
true`, honoured ONLY while a terminal death applies its own lock — written in
a quest or card, or by anything a respawn's hours run, it is refused, so it
is not a way round a gate.

**A terminal death inside time passing gets no death receipt in that turn's
prose.** Starvation takes hp an hour at a time inside `advance_time`, which
checks death itself; a death found there locks the ending and ends the run,
but the turn's receipt comes from whatever spent the hours (a rest, a served
sentence), not from a death. So `when: {in_custody: true}` also fires on a
prisoner starving through a sentence in the cell, and that turn's narration
does not hear why. HUE & CRY's The Rope (v0.17.0) gates on more than
custody for that reason: `{all: [{in_custody: true}, {event_active:
hanging_fair}]}` — held while the fair is on. A `when` may name an event id
the story has not declared yet (neither the loader nor the validator checks
event ids); it is simply false until the event fires.

**A death in the cells: `respawn.in_custody`** (v0.17, opt-in). By default a
respawn RELEASES a held player and carries them to `respawn.location_id` — a
prisoner carried out of the cells is not still in them. A story that means
otherwise declares

```yaml
respawn:
  location_id: the_snuffs
  # ... hours, hp_fraction, wound, effects, text ...
  in_custody:            # `true`, or a mapping of respawn keys laid over the above
    text: "You come to on the plank bench, still held."
    effects: [...]
```

and a player the watch holds AT THE MOMENT OF DEATH respawns HELD: at the
Law's `arrest.gaol`, the custody record (fine, days, charge, `since_hour`)
untouched, so the stay goes on and ends the usual way — paid, served or
broken out. The block's keys replace the respawn's for that death only (a
`text` and `effects` that do not say "the step of the flophouse"); hours,
hp, stamina, the purse and the wound are shared unless it names them. It may
not carry a `location_id` (the gaol is where a held player wakes). A free
player's respawn is unchanged, and a story that does not declare it is
byte-identical (asserted). The death record gains `kept_in_custody: true`.
A repeatable deck keyed on `in_custody` (HUE & CRY's interrogation) is not
dealt again: the stay never ended, so it never re-armed.

**Validated at activation, by the validator and at load**, naming
`death.yaml`: `when` and `ending` come together, `ending` must be declared,
`when` must use known predicates (and no combinator beside a sibling
predicate), the block may not also carry the flagship's older
`phases:`/`flag:` shape — that one (a second death while the world is
`consuming`) still sets `state.ended` with no ending, unchanged — and
`respawn.in_custody` is `true` or a mapping without `location_id`. Since
v0.17 `registry.validate` runs the loader's checks (`encounter.
death_file_problem`), so `activate` refuses a story whose death rules would
raise, instead of the player's first death raising it; an unreadable
death.yaml is refused there too (the loader alone would read it as empty).

### 3.6 The canon dictionary and the two-direction flag rule

A story may ship `data/canon/state-dictionary.json` (or
`canon/state-dictionary.json`) — the Garden's shape, `flags.booleans` grouped
however you like. The validator runs the strongest check in the repo against
it, in both directions across decks, clocks, threads and endings:

- a flag that is **read but never written** and not canon → **error**: "this
  gate can never open". Besides the four structural files, a labour
  posting's `effects` (§3.7) and a collection's completion `effects`
  (`tables/collections.yaml`, v0.17 -- HUE & CRY's `magpies_hoard_complete`,
  read by an ending) count as WRITERS;
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

**Arcs and acts.** `arcs.yaml` maps an arc id to `name`, `blurb`, `order`,
`involvement`, `default`, `requires_all`/`requires_any` (the shared condition
grammar) and `unlock_text`. A new run opens on the story's own `default: true`
arcs (`quests.seed_default_arcs`, called by `procgen.new_game_state`), with
`active_arc` the highest `order` among them; `active_arc` then only climbs, to
the highest-order arc unlocked. A story that declares no default keeps the
engine's `quiet_life` placeholder, since a quest with no `arc:` key belongs to
it. An arc that is an ACT of the story declares **`narrate: true`**: while it
is the active arc the narrator is given one line, `ACT: <name>. <blurb>`
(`prompts.act_block`), the same two strings the journal shows the player, so
keep the blurb to one sentence and free of anything the player has not
earned. An arc without the key puts nothing in the prompt, and that holds
byte-for-byte for every story that does not use it. A side door such as a way
out or a collection belongs at a lower `order` than the acts, so it never
takes `active_arc` from one. HUE & CRY's `data/quests/arcs.yaml` is the
worked example: Act I is the default, Act II opens on a flag, and the way out
and the Hoard sit at order 0 beneath them. `involvement` is the pacing weight
(`plot.PlotFormula.arc_weight`), and it is read from arcs the player holds
QUEST RECORDS in, not from unlocked arcs or `active_arc`: an act's
involvement counts only once a quest filed under that act has started.

**Eight things a place.** The `buy` verb offers at most eight choices where
the player stands (`engine/game/intents.py` `_MAX_OPTIONS`, every vendor there
together) and drops the rest in id order, so a ninth stock row is stock no
choice can reach. HUE & CRY's two fences sit at eight since v0.15 and its test
fails if a row is cut (`test_every_counter_offers_all_of_its_stock`).

**Recipes** (`paths.recipes`, a directory; the flagship's
`data/recipes/mending.yaml` is the annotated schema) become the `craft` verb,
offered only while a recipe's `station` is here and its tools and inputs are
carried (`mechanics.craftable_here`). The verb re-reads the directory each
turn it is built, so keep a story to one or two files. Source every input
somewhere the player can reach — a stock row or a forage table — and price
bought inputs so that what they make sells for less than they cost, or the
bench is a mint. HUE & CRY's Porters' Hall bench
(`games/hue-and-cry/data/recipes/workshop.yaml`) is the worked example, with
its measurement in the header.

**Collections** (`<paths.tables>/collections.yaml`; the flagship's is the
annotated schema) are sets of items that pay once, when every member is
CARRIED. A member's item row must say `collection: <set id>` -- the set
settles when such an item lands, by any door (the `item` effect: a purchase,
a job's getaway, a quest reward) -- and the validator refuses a member that
does not, a member that is not an item, a `counts` key that is not a member,
and an item naming a set nobody declared. The set's `reward_text` reaches the
narrator on the receipt that carried the last piece. HUE & CRY's Magpie's
Hoard is the second worked example: its pieces are placed in anchors and in
two secret places, as finds (quests that start and finish on arrival).

**Work has hours.** A `labour.yaml` job may declare `when:`, a condition in
the shared grammar (`quests.evaluate_condition`; most often
`hour_between: [start, end]`, start inclusive, end exclusive, wrapping
midnight), and `closed_text:`.
Unmet, the job is shut like any other gate — off the notice board
(`/api/notices`) and out of the `work` enum — and `work` refuses it in the
`closed_text` words at no cost (`engine/game/economy.py::_requirements_met`).
Without it a posting is open around the clock, which is right for a village
chore and wrong for a porter boss asleep in her shed at 3 a.m. HUE & CRY
gates each posting on the hours its employer is scheduled at the counter, and
its test asserts the two agree (`tests/test_hue_and_cry.py`). Wages are whole
units floored, and a `faction:` prices the wage at a neutral face's 0.85 — on
a 2-crown shift that is 1 crown, so a story counting small coin may keep the
faction on `reputation:` rows and off the wage (HUE & CRY's labour.yaml
header). `scripts/simulate_labour.py` measures what a working day keeps
against the cost of living.

**A shift can leave a record: `effects:`** (v0.17). A job may list authored
effects, each row optionally degree-gated with `degrees:` exactly as `in_kind`
and `reputation` rows are (no `degrees` fires on every shift worked); the
engine applies them through `effects.apply_effect` after the wage
(`economy.work`). It exists because the shift cap's own markers expire with
the day, so without it nothing remembers that the player ever worked. HUE &
CRY's four postings each write `{type: flag, flag: honest_wage_earned,
degrees: [crit_success, success, partial]}` -- the degrees their pay tables
pay -- and its Honest After All ending gates on that flag. The validator's
two-direction flag sweep (§3.6) counts these rows as writers, so an ending
may read a flag only a shift writes; and it checks each row: a known effect
type, fields that agree with it, and `degrees` naming only degrees the job's
`pay` table has (a misspelt degree is a row that never fires). A job that declares none writes exactly
what it always did.

**A stage can say why it will not close: `refusals:`** (v0.17). A quest
stage may carry `refusals: [{when, text}]` -- the shape a thread's and a
bed's refusals use -- read in order, the first whose `when` holds
(`QuestEngine.stage_refusal`). While one holds, the stage's objective line in
the narrator's prompt reads `<quest> - <objective> (Not yet: <text>)`, and the
stage's own `narrative_flags` are withheld from the narrator's vocabulary
(`allowed_narrative_flags`, and so from the `flag` intent's enum): a player
who tries is answered with the reason, and the prose cannot report as done a
step the engine will not close. It gates nothing by itself -- put the real
gate in `complete_when` and let the refusals restate it in the story's words.
The `when` is evaluated with no ledger, so `disposition` is refused there by
the validator, which also wants a `when` and a `text` on every row. HUE &
CRY's evening barge is the worked example: `complete_when` asks `{ending:
{eligible: honest_after_all}}` itself, so door and gate cannot drift, and
six refusals give the bargemaster's terms in the gate's order, each restating
one of its clauses (`never_stole` takes two: a theft, and a squeeze), and a
test holds them equal, case by case. A stage with no refusals is unchanged, line
for line.

**World events on the calendar.** The `events:` block of `paths.world_schedules`
declares things that HAPPEN — a market day, a raid, a curfew. Each entry fires
on a fixed day (`on_day`), on a cadence (`every_days`, from `first_day`), or on
the first rolled day a `when:` predicate holds; it lasts `duration_days`
(default 1), may name a `location_id` and `npc_ids`, and its `text` reaches the
narrator on the turn it starts (`engine/world/schedules.py::declared_events_due`,
fired from `advance_time`'s day roll, no randomness). An event may also carry
`forces_scene: <deck or card id>`: while it is active, the scene director deals
that deck (§3.3) exactly as it deals a clock's forced scene. The id must name a
deck or card the story ships — and a story with no decks declaring one is an
error naming the schedules file.

```yaml
events:
  the_raid:
    on_day: 3
    text: "The watch kicks in doors along the quay."
    forces_scene: raid          # data/scenes/raid.yaml
```

The shipped example is HUE & CRY's `hanging_fair` (`data/world/schedules.yaml`,
v0.17): `on_day: 10`, `duration_days: 3`, on Gallows Green, forcing
`fair_day` — a deck whose own `when:` names the event AND the Green, so the
forced deal waits for the player to walk there (§3.3). A schedules file that
declares only `events:` stages none of the flagship's caravan, tinker or
militia: those fire only for a story that declares their blocks. **An event
a condition names must be one the story raises** (v0.17): an `event_active`,
`event_seen`, `held_before_event` or `days_since_event: {event}` whose id is
no `events:` entry, engine slot block, procgen `festival` or `event_id` the
story's own content emits is a validator error, because the predicate is
false forever (`validation.check_event_references`).

**Road danger, by the hour.** A walk rolls for an encounter on ARRIVAL
(`engine/game/engine.py::_roll_travel_encounter`, the ENCOUNTER stream). The
chance is the edge's `danger_dc` times `trigger.per_danger_dc` (plus
`trigger.base`), times `trigger.time_of_day[<daypart>]` for the arrival hour
(`dawn` 5–8, `day` 8–17, `dusk` 17–20, `night` 20–5), less
`trigger.stealth_reduction_per_point` × the walker's stealth modifier, clamped
to `[min_chance, max_chance]` (`encounter.trigger_chance`; the `trigger:`
block lives in any file of `paths.encounters`). An edge at `danger_dc: 0` never
rolls. So night-only danger needs no special key: give the streets a
`danger_dc`, put `day` near zero in `time_of_day`, and gate the scenes
themselves with `triggers.hours` (and `to`/`from`/`edges`). A row with no
`triggers` matches every leg. Keep the two in agreement: an hour where the
chance is above zero and no row is eligible is a roll that cannot pay off
(it logs and draws nothing). HUE & CRY's night streets are the worked example
(`games/hue-and-cry/data/encounters/streets.yaml`, measured by
`scripts/simulate_streets.py`).

**`min_chance`** on an encounter row (v0.15, a number in (0, 1]) raises the
leg's chance to at least that WHILE the row is eligible for the leg
(`encounter.row_floor`, `leg_chance`), capped at `trigger.max_chance`, and
only on an edge with a `danger_dc`. It is for a scene gated on something
the player did -- HUE & CRY's fences' collectors by day, `requires_flag:
welshed_on_pell` -- that should find them on streets whose own daytime
danger is near zero. For anyone the row does not match, the leg's chance
and every ENCOUNTER draw are exactly what they were (asserted). The row
still competes by `weight` once the leg triggers.

**`on_roads: false`** on an encounter row keeps it off every road whatever its
`triggers` say, while `encounter.begin` still opens it on demand. It is for a
scene some other system opens — HUE & CRY's `watch_stop`, begun by the Law's
patrol, has no `triggers` and would otherwise be drawn as a free stop on any
street with danger. A row that does not write the key matches exactly as it
always did.

**The map draws itself.** Any story with a travel graph gets core's map screen
(`ui/src/core/screens/Map.jsx`, keyboard `m`) — nodes laid out by `ring`, roads
from `connections` (plus any hidden path the player has found), and the place
you are standing in. You author nothing for it. A plugin that declares its own overlay with `id: "map"` replaces it.

Two things you *can* author:

- **`secret: true` on a location.** Two kinds of hidden exist and they are not
  the same problem. A place you have not walked to is drawn and greyed — the
  shape of the map is not a secret, only what is behind the next tree. A place
  marked `secret: true` is one the player must not know EXISTS: it is withheld
  from the payload entirely, along with any road pointing at it, because
  drawing the edge and hiding the destination advertises the secret in the act
  of keeping it. It is withheld from the travel options too: a road to a
  secret place is never offered, by name or otherwise, until the player knows
  the place (`engine/game/locations.py::is_known`, the one rule the map, the
  travel enum and the resume screen all ask). The player knows it once any of
  these holds: they are standing in it; they have been there (the visited
  ledger — walking there reveals it permanently); a discovered hidden path
  ends there; its own `known_when:` condition holds; or content has
  **revealed** it with a flag.

  **Prefer `known_when:` when the reveal follows from state.** It is a
  condition in the shared grammar on the secret place itself, asked afresh
  every time and never stored — so a save made before the reveal existed
  knows the place the moment the condition holds. THE LONG CON's drying room
  is revealed this way, by its case standing at (or past) the stage that
  sends you there:

  ```yaml
  the_drying_room:
    secret: true
    known_when: { quest_state: { quest: the_dead_man_photographed, stage_at_least: 3 } }
  ```

  It shipped first as a flag set by that stage's `on_enter` — and a v0.12
  save already on the stage never ran it, so the stage's door stayed a secret
  road nothing would offer and the case could never finish. `known_when` is
  checked at load (the loader logs and ignores a bad one; the validator
  reports it as an error naming the graph file): known predicates, no
  combinator beside a sibling predicate, not empty, only on a `secret: true`
  place, and none of `disposition`, `days_in_stage`, `days_since_started` —
  `is_known` has no ledger and no quest record, so those would never hold.

  **A flag reveal** is for a moment rather than a state: set
  `location_known:<location id>` with the ordinary flag effect from anything
  that runs effects — a card, a set piece, a stage's `on_complete` — or list
  it in a stage's `narrative_flags` so the narrator may raise it:

  ```yaml
  on_complete:
    effects:
      - { type: flag, flag: "location_known:the_old_well" }
  ```

  A flag is stored, so it reaches only saves that run the effect after it
  ships. A revealed place the player has not walked to is drawn greyed, like
  any unvisited place. The validator reads the id after `location_known:` as
  a location reference — in a flag effect and in `narrative_flags` alike — so
  a typo is an error at load; a reveal nothing gates on is not reported as
  write-only. A secret place nothing reveals can only be reached by content
  that puts the player there — if it has no such door, it is unreachable.

  **A hidden path is the third reveal**: found by foraging, it makes both of
  its ends known. The pool comes from the story's `paths.procgen_templates`
  (`counts.hidden_paths`, drawn from `hidden_path_labels` and
  `hidden_path_targets`) and is dealt round-robin across the forageable
  places — wherever the alphabet falls. To start a path in a particular place,
  pin it: row N of `hidden_path_placements` pins path N, each key optional
  (`from` must be a forageable place, or the pin is ignored and the path is
  dealt as usual — a path is only ever found by foraging at its home):

  ```yaml
  counts: { hidden_paths: 1 }
  hidden_path_placements:
    - from: wickmarket
      leads_to: rooftop_road
      labels: [drainpipe with good brackets up the back of the pie shop]
  ```

  HUE & CRY reveals all three of its secrets through these three mechanisms —
  pinned hidden paths from the streets it scrounges, a `location_known` flag
  on every arrest (the drain in the cell floor), and the Old Bell Tower's
  `known_when` (seen from the Rooftop Road). A story that declares no
  placements generates exactly the paths it always did.
- **Nothing else.** Points of interest are DERIVED — an active quest stage that
  names a location becomes an objective pin, a vendor who trades there becomes
  a vendor pin. There is deliberately no map-pins file: a second place to
  declare the same thing is a second place to forget, and the first symptom
  would be a map pointing confidently at a quest that ended two days ago.

### 3.8 `spoilers.yaml`

**Spoilers.** Fixed filename inside `paths.rules`. Rows are
`{term, instead}`: surface forms the awareness gate masks in narration until
`awareness.spoiler_gate_threshold` is crossed. Two tables layer
(`engine/lore/interceptors.py`): the story's rows first, then the engine's own
story-neutral rows for identifiers the machinery leaks out of any story
(`evil_progress` and kin) — so a story with no table still leaks no mechanics,
and a story that wants its own phrasing for a mechanical id simply declares
it and wins by ordering.

**A secret place keeps its name once found.** A row may add
`location: <id>` for the place its term names. The gate drops that row as
soon as `locations.is_known` says the player knows the place (revealed,
visited, stood in, or at the end of a found path), so the prose names it the
way the travel choices and the map already do, below the threshold or not.
The validator refuses an id that is not in the graph: `is_known` counts a
place the graph does not hold as nobody's secret, so such a row would lift on
the first turn and leak the very name it hides. A row with no `location:` is unaffected. Keep the cover phrase
and the real name out of the same lore chunk, or the narrator learns they are
one place and keeps using the cover after the reveal.

**A role chosen by the seed is not a table row.** A `paths.agendas` role can
carry a `mask`:

```yaml
mask:
  instead: "the Magpie"
  unmask_when: {flag: magpie_unmasked}
  aliases: {npc_wren: ["the lamplighter"]}
```

- `unmask_when` is required.
- `aliases` is optional and keyed by candidate.
- **The mask matches only what you declare.**
  - The display name is matched in full and case-sensitively, so a trace that
    says "Silas" when the display name is "Silas Crook" is NOT masked unless
    `aliases` lists `"Silas"`.
  - List every short form, nickname and epithet your trace texts can produce.
  - An alias written with its article (`"the lamplighter"`) matches "the" or
    "The" and needs it, so "a lamplighter" is left alone.
  - At the start of a sentence the replacement is capitalised ("The Magpie
    was seen").

Until `unmask_when` holds, text the agendas themselves write (signs, and
public traces in the moved journal) calls the chosen NPC `instead`. Once it
holds, the GM line says who the role is. That is the only place the engine
could link the role to its NPC, so the only place it masks. The cast, your
storyteller prompt and the narration keep every name. The same rule applies
to what you author: **treat every candidate the same everywhere else**. Do
not name the role's secret in `storyteller.md`, `spoilers.yaml` or any
dialogue, and give each candidate the same weight of description, because a
narrator that was never told the link cannot give it away.


### 3.9 Art

`art_manifest` maps ids to files, `art_root` is the directory those paths
resolve against (served at `/story-art/`), `art_subjects` carries generation
prompts. A story with none of the three runs on the procedural silhouette,
which carries a new story fine. When the prompts are written,
`scripts/art_missing.py --game <slug>` writes `data/art/MISSING-PLATES.md` —
every gap, with a ready-to-paste prompt in both dialects at the right pixel
size. `games/dev-story/README.md` § Art shows the intended workflow.
A declared `art_root` must exist as a directory or the story will not activate: a story whose plates are
not rendered yet keeps an empty one (a `.gitkeep`), as READ RECEIPTS does (`data/art/plates/`). A location row
with `base:` and `times:` (no `alts:`) shows its `base` plate for any daypart it has none for.

A `portraits:` row keyed by an NPC id (`npc_ardane: …`) is shown in the people
strip (`ui.panels: [people]`), to a player who has met that person; a stranger
is a silhouette and a role. The strip (`ui/src/core/panels/PeopleStrip.jsx`)
reads `GET /api/people` (`engine/scenes/default_api.py::people_here`); a met
person with no portrait in the pack gets their initial in a medallion.

**Generating the pack.** `scripts/generate_art.py --game <slug>` plans from
the same subjects and the same idea of "missing" as the brief (both call
`generate_art.plan_plates`):

- **The plan** is every location at each daypart its `times:` block declares
  (one plate if it declares none), every portrait and every item — nothing
  the story does not declare, and no evil-phase variants (a `corrupted:` pool
  stays hand-filled).
- **`--dry-run`** lists kind, subject, daypart and target path and writes
  nothing. **`--only locations:<id>`**, **`--only portraits`** (repeatable,
  comma-separated) and **`--dayparts day,night`** narrow it — the entry
  location first is `--only locations:<entry id>`. A subject the story does
  not declare is an error.
- **`--missing`** (default on; `--no-missing` to redo) skips a plate the
  manifest already resolves, by the serving chain's own test
  (`shipped.lookup`). So a location entry with a `base:` resolves every
  daypart; one with only `times:` resolves only the dayparts it names.
- **A run without `--promote`** generates into the disposable cache
  (`data/media/images`) with `media.image_provider` (or `--provider`). It is
  slow by design — minutes per image on Grok.
- **`--promote`** then copies each cached plate under `paths.art_root`
  (`scenes/<id>-<daypart>.jpg`, `portraits/<id>.jpg`, `items/<id>.jpg`; JPEG
  fitted to the `formats:` size) and writes it into `paths.art_manifest` as
  `locations.<id>.times.<daypart>`, `portraits.<id>` or `items.<id>`. Only
  the lines of the entries it changes are rewritten, so comments outside
  those entries survive (a comment inside an entry it rewrites goes with it).
  A manifest it cannot read, an entry it cannot edit safely (a quoted key it
  would otherwise duplicate), or a plate whose path would land outside
  `paths.art_root` stops the promote with an error before any file is
  written. `--promote --dry-run` lists what would move and writes nothing.

The generation cache is per story: a request's key includes the slug of the
story it was made under (`ImageRequest.story`), so two stories that share a
subject id (The Wicked Garden and Dev Story both have a `sophia` portrait)
never share a cached image, at runtime or through `--promote`. The flagship's
keys are the original story-blind ones, so nothing already cached for it is
orphaned.

The flagship (the default with no `--game`) keeps its original plan and flags
(`--locations`, `--portraits`, `--items`, `--all`, `--list`, `--prompts`).

### 3.10 Premises, thievery and fences

`paths.premises` → a directory (`districts.yaml`, `names.yaml`, `types/`,
`anchors/`); `paths.thievery` → one YAML file. Both are optional and both pay
nothing when undeclared — the worked example for the whole shape is
`games/hue-and-cry/data/premises/` and `games/hue-and-cry/data/rules/thievery.yaml`.

`paths.premises` is drawn by core's casing board (`ui/src/core/panels/CasingBoard.jsx`,
the `casing` entry of `ui.panels`, in the ledger by default): one row per
house cased in the player's district, headed by each type's `label`.

**`paths.premises` layout:**

- `districts.yaml` — one entry per district location: `count` premises to
  generate plus `types: {<type>: <weight>, ...}`, and an optional `anchors:
  [<anchor id>, ...]` list (anchors are hand-written premises **in addition
  to** `count`, not counted against it). A district that should hold nothing
  (a `secret: true` location, say) is simply left out.
- `names.yaml` — the pattern fields (`{surname}`, `{street}`, `{craft}`, …)
  `name_patterns` draw from.
- `types/*.yaml` — one file per premise type: `id`, **`label`** (required —
  what the casing board and the narrator call it; falling back to the raw id
  was a review-round-1 bug, so it is now a hard load error, same as a missing
  `district`/`name`/`tier` on an anchor), `name_patterns`, `tiers: {N:
  weight}` (a tier-N premise draws N `security` features **sampled without
  replacement** — so every tier needs at least N eligible `security` rows —
  and `tier` `loot` rows **drawn with replacement** by weight, so one eligible
  `loot` row per tier is enough; only `security` scales its requirement with
  the tier), `household` (roles with routines — see below), `security`
  (`{id, text, tier_min}`; `text` is what a watch learns word for word),
  `loot` (`tier -> [{item_id, weight}]`, ids from `data/items/`), and
  `secrets` (`[{id, text, thread?}]`, one drawn per premise — casing only
  reveals that a secret *exists*; the `text` is what going inside finds).
  `thread` (v0.15, optional) names the `paths.threads` template that holding
  the secret opens — a blackmail. It is checked at load: the template must
  exist, and its `requires` must read `secret_held` for this secret (an
  anchor's clause may also name its own premise, `prem_<anchor id>`; a
  generated type's may name only the secret, since its premise ids are drawn
  per seed). A lever offered before the thief holds it, or never, is refused
  naming the file. A secret with no `thread` is still held when carried out (§3.12)
  and read by nothing else yet.
- `anchors/*.yaml` — the same schema, hand-written: a fixed `district`,
  `name`, `tier` and contents rather than generated ones. An anchor may also
  declare `owner: <scheduled npc id>`, validated at load; `premises.owner(state,
  premise_id)` answers it, or a generated premise's first household member
  when the premise names none. This is how an agenda's `premise` selector
  filters on `owner`, and how `premise_robbed`'s own `owner` filter (§3.13)
  reads "the player robbed a house so-and-so keeps" without a hand-rolled flag
  per house.

**`clues.yaml` — a masked role's trail (v0.16, optional).** Found by fixed
filename inside `paths.premises` (`engine/world/clues.py`); a story without
one pays nothing, and its premises never gain a `clue` key. HUE & CRY's is
the worked example (`games/hue-and-cry/data/premises/clues.yaml`):

```yaml
role: magpie          # a role in paths.agendas (§3.13), two candidates or more
evidence: evidence    # a meter the story's state.yaml declares: veiled, min and max
trail: 4              # clues pointing at the seed's chosen candidate
herrings: 2           # clues pointing at EACH other candidate
fresh_flag: clue_fresh  # optional (v0.16): set true by every clue carried out
clues:
  - {id: wick_ends, points_to: npc_wren, text: "a twist of cheap lamp-wick ends ..."}
```

- **Laid at world generation**, after every PREMISES draw, on its own
  `CLUES` stream (`engine/game/rng.py`), so a trail arriving moves no house.
  The role's candidate is READ (`agendas.role_for_seed`, the derivation
  `agendas.role` makes), never drawn. The seed samples `trail` of that
  candidate's rows and `herrings` of each other candidate's, and as many
  **generated** premises — never an anchor, which may be a candidate's own
  home. Every premise of the story then carries `clue`: a row id, or `""`.
- **Rows:** `id` (unique), `points_to` (one of the role's `from`
  candidates — never rendered anywhere) and `text` (what the thief finds, word
  for word). A candidate's rows are the same sentences whether the seed makes
  them the culprit or a red herring, so one clue suggests and never proves.
  Every candidate needs at least `max(trail, herrings)` rows, and the trail
  may not lay more clues than the city generates houses.
- **Refused at load, naming the file:** an undeclared role, a role with one
  candidate, an `evidence` value that is not a veiled, bounded meter, a
  `points_to` outside the role, an id written twice, and a `text` naming any
  candidate by display name or alias (the mask's own matching: a clue
  describes, it never accuses).
- **Found by a job** (§3.12): casing gives a clue house up LAST, as
  "something here doesn't belong" (intel id `clue`, appended after the
  shuffled rows so no other intel moves), until the clue is carried out; the
  score sees the clue cased or not; a job carried out keeps it. The ledger
  fact leads with the clue's text, and a `text` longer than the ledger's
  fact length (`MAX_FACT_CHARS`, 140) is refused at load.
- **The meter rises for red herrings too.** A gate on `evidence` alone can
  open on herrings; pair it with `clues_favour` before a card treats the
  evidence as pointing at anyone. A clue's `text` must not sex its owner
  either (no dress, grooming or jewellery): in a story where the player is
  taken for the role, that sexes the player.
- **`clues_favour: {npc, min?: 1, excluding?: [npc, ...]}`** is registered
  in the shared grammar: at least `min` found clues point at `npc` AND
  strictly more than at any other candidate (a tie favours nobody).
  `excluding` (v0.16) sets candidates aside -- the lead is counted among the
  rest, and an excluded `npc` never leads -- so a suspect already named
  wrongly stops standing in front of the others. Like `agenda_role`, **a
  condition only** — no prompt block renders it or any `points_to`
  (`tests/test_premises_clues.py`), so a card may ask whom the evidence
  favours while the narrator still does not know. False with no trail, an
  `npc` who is not a candidate, a `min` below 1, or an `excluding` that is
  not a list of names.
- **`fresh_flag`** (optional, v0.16) names a flag `clues.take` sets true on
  every clue carried out (through `apply_effect`). Content clears it (`{type:
  flag, flag: clue_fresh, value: false}`) and later asks `{flag: clue_fresh}`:
  "has a clue been found since?". HUE & CRY's accusation clears it on a
  wrong naming, so a second accusation waits for something new
  (`data/scenes/lantern_house_desk.yaml`). Refused at load if it is not a
  name, or is a `clue_found:` one. Without it, `take` writes nothing new.

**Household routines.** A `household` role's `routine` is an ordinary
schedule-row list (`{hours, location, activity, available}`), with two
special location tokens: `@home` (this premise) and `@work` (one of the
type's `work_at` districts, drawn once per person at generation). Every
household member becomes a real procgen NPC merged through the same path
flagship villagers already use — present, gossip-able and liftable, and,
in a story that declares `paths.law`, a witness: `law.commit_deed` rolls
every awake person present, household members included — with no new code.
**Anchors are additive to the district's
`count`**, never counted against it, so a district's premise total is
`count + len(anchors)`.

**`paths.thievery` (one file):**

- `alertness` — role → difficulty band (from `skills.yaml`) a `lift` rolls
  against. `default` is optional here (unlike `purses`' below); an unnamed
  role simply falls back to `"standard"` rather than failing to load, so a
  new household role a later premise type adds needs no entry.
- `purses` — role → weighted rows, either `{gold: [lo, hi], weight}` or
  `{item_id, weight}`; a partial lift draws gold rows only, halved (min 1).
  `default` **is** required — this is the one row `load_spec` enforces.
- `hot_days` — how long a lifted or looted item stays `hot` before it cools;
  an item tagged `named` in `data/items/` stays hot regardless. There is no
  laundering mechanism: any fence sale — hot or cool — consumes the
  provenance record it sells, same as an honest one selling a cool unit;
  nothing about *which* vendor buys it changes that.

**Security is text a watch learns, and — with `paths.jobs` — a job's odds.**
A `security` row's `text` is what a watch learns through `case`, word for
word. In a story that also declares `paths.jobs` (§3.12), the jobs file's
`features` block says what each row does to which stage of a burglary, cased
and uncased; HUE & CRY gives every one of its rows a line there, and its test
suite fails when a new row has none. Without `paths.jobs`, security stays
text.

**Fences.** A trade profile with `fence: true` (optional `fence_cut: {hot,
cool}`, default `0.5`/`0.8`) buys stolen units too: it prices one at value
× its `spread.sell` × `fence_cut.hot` for a fresh or `named` piece, `.cool`
for one aged past `hot_days` (`engine/game/trade.py`). Both numbers are the
price -- the cut alone is not. It buys clean goods at the ordinary price
(value × `spread.sell`), never discounting a clean unit even at a fence.
An honest vendor (no `fence: true`) sells a mixed stack's clean and cool
units normally and refuses only the hot ones, in its own voice. Both read
`thievery.heat_split` per unit, never per item, so a mixed stack of clean and
stolen goods is never priced or refused as a whole.

**A vendor who will not buy from you.** Any trade profile (a fence or not)
may declare `refuses_to_buy: {when: <condition>, text: <her words>}`. While
`when` holds (the shared grammar, evaluated with no ledger — the validator
refuses a disposition predicate here, and a `when` or `text` left out) she
buys nothing from the player: the `sell` verb leaves her out, `sell` refuses
in `text` (never a `fencing` deed — a grudge is not a crime), and the
narrator's PEOPLE HERE line for her carries `[buys nothing from you: <text>]`
while she is present. She still sells. HUE & CRY's two fences each read BOTH
credit threads' break flags: welsh on one and neither buys (`data/tables/trade.yaml`, §3.4).

### 3.11 `paths.law` — the watch

`paths.law` names ONE YAML file: a story's whole contract for who the watch
is, what it counts as a crime and how badly it wants you. Optional, and pays
nothing when undeclared — no deed is ever committed, the recognition check
never rolls, and a story's payload carries no `law` key. The worked example
is `games/hue-and-cry/data/rules/law.yaml`, with the tuning story behind every
number in its header comment and in CHANGELOG.md's `[0.10.0]` entry.

Core's wanted poster (`ui/src/core/panels/WantedPoster.jsx`, the `wanted`
entry of `ui.panels`, in the ledger by default, with a header chip) draws the
`law` block: the wanted band per jurisdiction, a sketch drawn from the `clarity`
word, and, for a thief held, the fine and the days. It needs no authoring beyond this file; the words
on it are the file's own plus the panel's few ("Wanted", "Held").

**Required** (the loader refuses the file without them):

- `guises` — `{<id>: {label: <text>, item: <optional item id>}}`. Must
  declare `self`, the player's own face, and every guise needs a `label`. A
  guise is offered through the `guise` verb only while its `item` is carried
  (never the one already worn), so a guise with no `item` can be put on only
  by an authored `law_guise` effect. A guise's `label` is the only thing the
  narrator or the payload ever say about it — no id reaches either.
- `wanted.bands` / `wanted.thresholds` — parallel lists, thresholds strictly
  ascending and starting at 0 (the floor of the score is the floor of the
  first band). `wanted.cool_per_day` (default 0) wears the score down, hour by
  hour, through `clock.advance_time`.

**Optional, but the Law does nothing useful without them** (each loads as
empty, and an empty one switches its part off):

- `deeds` — `{<kind>: {severity: <int >= 0}}`. A deed not listed here cannot
  be committed (`{type: deed}` refuses it; a scene author only ever names a
  kind this file declares). No `deeds`, no crime.
- `jurisdictions` — `{<name>: [<location id>, ...]}`. Each location falls in
  at most one; a location in none is watched by nobody — a deed there is
  witnessed and never filed. A house (an interior id) answers to its street's
  jurisdiction. Give jurisdictions a `labels: {<name>: <text>}` map or the id
  itself, humanised, reaches the narrator.
- `recognise` — `{<band>: <chance>}`. Only bands named here ever roll; a story
  can leave `unknown`/`noticed` unrollable and gate recognition on `sought`
  and up, as HUE & CRY does. Rolled once a turn per law-role person present
  and awake, before narration and never during a scene. No `recognise`, no
  stop.
- `arrest` — `{encounter, gaol, fine_per_severity, days_per_severity}`. When
  the block is present, `gaol` must be a real location, and `encounter` must
  name a real scene once `paths.encounters` is declared (a typo is a
  load-time fault naming the file, not a silent no-op). Optional `max_days` /
  `max_fine` cap the sentence a charge sheet would otherwise sum without
  bound — HUE & CRY sets 3 days and 30 crowns after measuring sentences up to
  27 days uncapped (CHANGELOG.md).

**Optional, with defaults:**

- `notice: {base, night, per_margin}` — the chance an onlooker sees a deed at
  all: `base` (default 0.6), `night` added after dusk (may be negative),
  `per_margin` added per point of the roll's own stealth margin.
- `precision: {<hop>: <chance>}` — how clearly a report at each remove reads,
  hop 1 (the witness) at 1.0 by convention. Spoken to the narrator as
  "clearly" at precision 1.0 and "only a glimpse" otherwise, never as a
  number.
- `clarity_words: [<word>, ...]` — how well the watch knows the face the
  player wears, ascending (at least two non-empty strings; a number is a
  load-time fault). Default `[nothing, a rumour, a description, a likeness]`.
  The first means no live report here on that face or any face linked to
  it; the rest split the best live precision (0, 1] evenly, so with four
  words below 1/3 is the second, below 2/3 the third, from 2/3 the fourth
  (the default hops 0.3 / 0.6 / 1.0 land one on each). A paid-off or
  bribed-away deed draws nothing. The word ships as the payload's
  `law.clarity` (the wanted poster's sketch: core's `wanted` panel, `ui/src/core/panels/WantedPoster.jsx`, and the header chip) and ends the narrator's
  wanted line ("it has a description of you"), so write words that read
  after "it has".
- `spread_per_hour` (default 0.3) — the chance one held deed passes to
  another person awake in the same room, per in-game hour, capped at hop 3.
- `reporters: {<role>: <chance>}` — a non-watch witness (a vendor, a servant)
  who may report straight to the watch without the deed passing through
  anyone else first.
- `labels: {<jurisdiction>: <text>}` — else a humanised id.
- `links: [[<guise>, <guise>], ...]` — what the watch believes on the first
  morning, before the player changes anything (HUE & CRY starts with
  `self`/`magpie` linked: the Watch was told at the docks). Linked guises
  share one wanted score and are read together by `same_person`.
- `arrest.approaches` — **NOT WIRED** (`engine/world/law.py`, `load_spec`):
  the block is loaded and kept, and nothing reads it. Give the arrest scene
  its exits in the encounter file itself (§3.7). Recorded in
  `docs/GOVERNANCE.md`.

**The arrest encounter.** `arrest.encounter` opens when `law.patrol` gets a
recognition hit; it is an ordinary encounter (§3.7) whose approaches end in
either outcome:

- `{type: arrest}` — moves the player to `arrest.gaol`, seizes every HOT unit
  carried (a mixed stack keeps its cool ones), and sets custody: fine and
  days from `sentence_for`, capped by `max_fine`/`max_days`, charging exactly
  the deeds on file for the face worn (and any linked face) in this
  jurisdiction. `pay_fine` (offered only with the coin) and `serve_sentence`
  (days × 24 hours, fed before each meal) discharge exactly those deeds —
  their reports and witness rows are dropped for good — and a bare `release`
  (a story's own break-out) discharges nothing. **A scene that falls due
  stops a sentence** (v0.17): serving is one action over days, and decks deal
  only at a turn, so `serve_sentence` cuts each meal's hours at every hour a
  deck's `when:` can change its answer on the clock alone
  (`director.due_boundary_hours`: midnight, every `hour_between` bound, and —
  when any deck that can be due while held reads `time_of_day` — the four
  band edges 5, 8, 17 and 20) and asks the director (`director.due`) at each
  cut; a deck due now that was not due when the sentence began stops it, the
  prisoner still held — the receipt says `served_out: false,
  interrupted_by: <deck>`, and `run_turn` deals the deck that same turn. A
  deck already owed at the start (the stay's own interrogation) does not
  interrupt. A clock-read gate stops the sentence on its very hour, whatever
  hour the serve began (the prisoner is still fed once a meal); a gate on a
  flag, a value or a clock that the hours move in passing is caught at the
  next cut, not on its hour — at worst the next midnight or band edge. **A
  stopped sentence is resumed, not begun again** (v0.17): every step served is
  counted on the custody record (`served_hours`, written by the engine's
  `custody_served` effect, engine-only: the validator reports a story file naming it), so a second `serve`
  waits out only what was left. The charge was discharged at the start.
- `{type: deed, deed: <kind>, seen_by_watch: true}` — commits a deed from
  inside authored content (a scene's own outcome can be a crime); the story's
  `deeds` must list `<kind>`. `seen_by_watch: true` makes every law-role
  person present a certain witness, whatever the notice roll would have said
  — the watch_stop's `fight` approach uses this for `assault_watch`.
  `report_precision: <0..1>` is the victim telling the watch-house himself,
  for a scene's own watchman who is no scheduled person (so `seen_by_watch`
  cannot find him): when nobody present filed the deed, one report of it is
  filed for the guise worn, where it happened, at that clarity; when someone
  did, it adds nothing. HUE & CRY's drunk Lantern uses `0.6`.

An approach may also declare `cost_per_severity` (`encounter.approach_cost`):
added, per point, to the charge an arrest would lay against the face worn
here right now, on top of any flat `cost_gold` — a bribe that gets more
expensive the more the watch already has on you. HUE & CRY's `bribe`
approach is 3 crowns a severity, uncapped by the arrest's own caps (a bribe
is a choice, not the sentence).

**Thread conditions.** A `threads.yaml` template may gate on the Law through
the shared condition grammar (§3.7): `requires` gates the `bargain` verb (the
template is not even offered while it fails) and `discharge_requires` gates
`discharge` (refused, writing nothing, while it fails). Both take any
predicate the grammar knows, including `at_location` and `min_gold` — HUE &
CRY's `brask_bribe` requires `at_location: lantern_house` (Brask names his
price at his desk, nowhere else) and its `discharge_requires` asks
`{min_gold: 12}` and the same `filed` clause as its `requires` (below),
paying it and quashing the Wick's files together in `on_discharge` -- so a
file gone before payday cannot be paid for. That is safe only because the
bribe has no `on_break`: a refused discharge lets the thread come due, and a
template whose break has teeth (`ardane_magpie_file` files a report and
costs -10) must not gate its discharge on something the player can lose. There is
no predicate for who else is standing there — see the NOT WIRED row in
`docs/GOVERNANCE.md`.

**Something to lose: `filed`.** `{filed: {jurisdiction, guise?, linked?}}`
is true while any LIVE report row matches — read through the same matcher
`quash_reports` uses (`law.report_matcher`), so the gate and the bribe it
guards always agree on which rows are meant. The guise is exact unless
`linked: true` widens it to every face the watch takes for the same person.
A discharged or quashed deed's rows are gone, so they do not count. False —
never open — in a story with no Law, with no (or a blank) `jurisdiction`, or naming a
jurisdiction or guise the Law does not know; an agenda naming one is refused
at load. `brask_bribe` requires it alongside the desk, so a sergeant names no
price to a clean record:

```yaml
requires:
  all:
    - { at_location: lantern_house }
    - { filed: { jurisdiction: wick, guise: self, linked: true } }
```

`linked: true` matters there: the Magpie agenda files half-seen burglaries
against `magpie`, which the watch links to `self`. Without it, a thief wanted
in the Wick only under the Magpie's name would be refused the very bribe whose
`linked` quash loses her file.

**Law effects, and who may use them.** An encounter outcome may use any of
`report`, `quash_reports`, `law_guise`, `law_link`, `law_unlink`, `law_cool`,
`arrest`, `release`, `law_discharge` and `deed`. A thread's authored
`on_seal`/`on_discharge`/`on_break` effects and a deck card's gate outcomes
may use **`quash_reports`, `report`, `law_discharge` and `law_unlink` only**
(`report` since v0.15: a squeezed victim going to the watch; the other two
since v0.16: the alibi and the reveal): the bounder (`engine/game/threads.py`,
`_bound_effects`; `engine/content/deck.py`, `_bound_gate`) drops every other
Law kind with a logged adjustment, so a thread that tries to `arrest` does
nothing. A set-piece's challenge (`paths.challenges`) may use those four
plus **`release`** and no other Law kind, and only because it is read from
the story's own file (the four through
`engine/challenges/spec.py::STRUCTURAL_EFFECT_TYPES`, `release` through
`AUTHORED_CHALLENGE_EFFECT_TYPES`); a model-composed challenge has no Law
kinds on its allowlist at all, and a thread or deck gate never gets
`release`. An authored opening choice's `on_pass`/`on_fail` (§2.4, v0.16)
may use the four plus **`arrest`** (`AUTHORED_CHOICE_EFFECT_TYPES`), and
commits a deed through its own `deed:` key rather than the `deed` effect;
nothing else outside an encounter may arrest.

**Breaking a link: `law_unlink` and `linked`.** `{type: law_unlink, a: self,
b: magpie}` removes that DIRECT pair from what the watch believes (the file's
starting `links` read through, as `law_link` does) and records it in
`state.law["broken_links"]`. A broken link stays broken until a witness sees
the guise change again: an authored `law_link` of the pair, either way round,
is refused (no key re-forms it), but when the player changes face with
someone present who notices (`law.change_guise`, the same roll that makes
any link), that is new evidence -- the pair leaves `broken_links` and is
linked again, and the Magpie's file counts against you once more. So a
player who has broken the link and then puts the Magpie's mask on in front
of a witness has undone their own alibi. `law_unlink` is refused, writing
nothing, for an unknown guise, a guise paired with itself, or a pair not
directly linked (a belief running through a third face is broken by
unlinking one of its pairs). Nothing is recomputed: wanted,
the charge sheet, the wanted poster's likeness, `filed {linked: true}` and
`quash_reports {linked: true}` all read `law.links` each time, so once
`self`/`magpie` is broken the Magpie's reports stay on the Magpie's file and
stop counting against you at once. `{linked: {a, b}}` is the grammar's face
of that belief -- true while the watch takes `a` and `b` for one person,
transitively, as the wanted score does; false with no Law or an unknown
guise (refused at load in an agenda gate).

**Custody history, and the alibi.** `arrest` stamps `since_hour` (the first
whole absolute hour the clock has not yet crossed, `law.next_hour` -- the
same boundary an agenda move fires at) beside `since_day`, and `release` --
however it comes: paid, served, broken out or a death in the cells (unless
`death.yaml` declares `respawn.in_custody`, §3.5) --
appends `{since_hour, until_hour, jurisdiction}` to
`state.law["custody_log"]` before clearing custody. An agenda's robbery
(`robs: true`) whose move filed a `report` carries that report's `deed_id`
(§3.13). Together: `{alibi: {agenda?, min?: 1, open?: false}}` is true
when at least `min` of that agenda's joined robberies (any agenda's,
without `agenda`) fell at an hour inside a logged stay (`since_hour <= hour
< until_hour`) or at or after the live stay's `since_hour`. `{type: law_discharge, alibi: true,
agenda?: the_magpie}` closes exactly those deeds, resolved when the effect is
applied (`agendas.alibi_deeds`), merged with any `deed_ids` it also names;
with nothing to close it is refused. Only ROBBERIES are joined: a report an
agenda files with no robbery behind it -- HUE & CRY's Ardane
`takes_a_statement`, a Magpie `pickpocket` on the witness's word -- has no
hit, so no alibi can discharge it, and its charge stays on `self` for as
long as the watch links you to the Magpie; a card that only discharges by
alibi leaves such rows filed, and `law_unlink` is what takes their weight
off you. An alibi, once earned, stays earned -- discharging the robbery
does not undo the night in the cells -- so a card that should be offered
once per alibi gates on **`open: true`** (v0.16): only the joined robberies
whose deed is not yet discharged (`law.discharged`) count. Presented, the
card is not offered again; a robbery in a LATER stay opens a new one. A
card presenting a night in the cells as proof is the intended caller.
HUE & CRY's is the Lantern House front desk
(`games/hue-and-cry/data/scenes/lantern_house_desk.yaml` `D1_the_alibi`,
and its twin in the cells, `interrogation.yaml` `Q4_the_alibi`), cut down:

```yaml
# data/scenes/lantern_house_desk.yaml
repeatable: true
when:
  all:
    - { at_location: lantern_house }
    - { in_custody: false }
    - { alibi: { agenda: the_magpie, open: true } }
cards:
  - id: D1_the_alibi
    tags: [menu]
    when: { alibi: { agenda: the_magpie, open: true } }
    beats:
      - id: present_it
        text: "Put your finger on the dates, and let the book say it."
        gate:
          on_pass:
            effects:
              - { type: law_discharge, alibi: true, agenda: the_magpie }
              - { type: flag, flag: alibi_proven }
      - id: let_it_lie        # a roll-free way to say nothing: offered again next visit
        text: "Say nothing about it."
        gate: { on_pass: { text: "The book will keep." } }
```

Whether the alibi also breaks the link is the story's call. HUE & CRY's
does not (it proves you were not the Magpie on those nights, no more); its
`law_unlink self/magpie` is on the accusation that names the real Magpie,
`D2_name_*` in the same deck. Because an alibi can still be open AFTER that
naming, HUE & CRY ships the book twice at each door, one card per belief:
`D1_the_alibi` (and `Q4_the_alibi`) gated `not_flag: magpie_unmasked`, whose
text says the file still says Magpie, and `D1_the_alibi_struck` (and
`Q4_the_alibi_struck`) gated `flag: magpie_unmasked`, whose text says it no
longer does. A card's words are handed to the narrator as fact: when a
flag can change what the card should say, gate a second card on it rather
than write one sentence that is true only half the time.

A save from before v0.16 has no log and no hit `deed_id`s: a custody record
with no `since_hour` releases without a log row (its start cannot be placed,
and a guessed one would invent an alibi), and an unjoined hit is never an
alibi. A quash lasts: the lost deeds are remembered per
jurisdiction (`law.quashed`), and that watch-house refuses to re-file them
when a witness's gossip reaches one of its watchmen. All are
`engine/game/effects.py` kinds; none is written anywhere else (AGENTS.md
rule 3).

**Custody in the grammar, and a break-out.** `{in_custody: true}` is a
predicate in the shared condition grammar (§3.7), true exactly while the
watch holds the player — from `arrest` until `pay_fine`, `serve_sentence`, a
`release` or a death in the cells (a respawn releases, unless `death.yaml`
declares `respawn.in_custody`, §3.5) — and always false in a story with no Law
(so `{in_custody: false}` is always true there; an agenda may not use it
without a Law). `arrest` sets no flag, so this is the only way content can ask
"is the player in the cells?". **`{held_before_event: <event id>}`** (v0.17)
asks the sharper question "was the watch already holding the player when this
event began?": true while held, in a stay whose `since_hour` is at or before
the midnight the live event started on (a declared event starts on
`advance_time`'s day roll) — so an arrest at 23:30 the night before counts,
one at 00:30 does not. False when free, with no Law, when no event of that
id is active, and for a pre-v0.16 custody record with no `since_hour`. HUE &
CRY's gallows (`data/scenes/the_gallows.yaml`) hangs exactly the thieves the
Watch saved up for the Hanging Fair with it; one taken at the fair is
questioned and may pay or serve.

**What the player did, seen or not.** **`{committed_deed: <deed>}`** or
**`{committed_deed: [<deed>, ...]}`** (v0.17) is true once the player has
committed at least one deed of a kind named, WHETHER OR NOT ANYBODY SAW IT:
`law.commit_deed` counts every deed it commits (the engine-only
`law_deed_committed` effect, into `state.law["committed"]`) before it looks
for a witness. `wanted` and `filed` read what the Watch KNOWS; this reads what
the player DID. A deed only filed by a `report` effect (a card's, an agenda's)
was never committed and is not counted; false with no Law. The validator
names a deed the law file does not declare. HUE & CRY's Honest After All
reads it: no lift, burglary or fencing, ever. A set-piece may carry an optional `requires:`
— any condition from the same grammar, checked alongside its
`location_id`/`requires_flags`/`forbids_flags` gates (an unknown predicate, a
sibling beside `all`/`any`/`none`, or a predicate the gate cannot answer --
`disposition` needs a ledger, `days_in_stage`/`days_since_started` a quest,
and `is_available` has neither -- is logged and the piece skipped at load).
Together they make a third way out of a cell:

```yaml
# data/challenges/cells.yaml
set_pieces:
  - id: lantern_house_break
    location_id: lantern_house
    requires: { in_custody: true }     # offered in the cell, never outside it
    grants_flag: broke_out_of_the_lantern_house
    challenge:
      id: lantern_house_break
      kind: puzzle
      title: The Loose Bar
      prompt: One bar in the window turns in its socket. What opens it?
      answer: patience
      attempts: 2
      reward: { text: "The bar comes free.", effects: [{ type: release }] }
      fail:   { text: "The bar holds.", effects: [] }
```

Held, the travel verb is withheld but set-pieces are not, so the break-out is
offered; once started it owns the turn like any set-piece. (A dealt card owns
the turn first: HUE & CRY's interrogation is answered before the break-out is
offered.) Success runs `release` and nothing else: custody clears, the player
stays where they are (the gaol) and walks out still wanted — unlike paying or
serving, a break-out discharges no deed. Failure leaves the player held. A
challenge takes no in-game time.

What a break-out may cost, and what it may not. Its outcomes may carry any
set-piece effect: HUE & CRY's (`data/challenges/lantern_house.yaml`, two
skill gauntlets) files a fresh `report` of an `escape` deed on success and
takes `hp` on failure. **A challenge step that lowers hp checks death on
that step** (v0.17, `runner.resolve`, as a card's beat does): the receipt
carries `death`, and the narrator hears it as the step's last sentence. There
is **no authored way to lengthen a stay**: the custody record's `days` is
written by `arrest` alone and counted down by `serve`, and no card, thread
or set-piece effect reaches it — so "failure adds days" cannot be written;
price a failed attempt in hp, stamina or a report instead. **A challenge
takes no in-game time**, so a failed piece is offered again on the very next
turn and a cheap failure is a free reroll: declare `retry: next_day` on the
piece (v0.17, opt-in, the only value) and a FAILED attempt closes it for the
rest of the world day it was made on (midnight reopens it; a win is left to
the piece's own gates). HUE & CRY's break-out is one try a day this way. A
`report` in any outcome must name a deed, guise and jurisdiction the law file
declares — the validator checks it (`check_law_effects`); a typo is refused
at runtime and files nothing. And mind the
`grants_flag`: it retires the piece for the rest of the run (the engine's
one-shot). HUE & CRY keeps a way out on every stay by pairing its first
break-out with a second that `requires_flags` the first's flag and grants
none.

**Set-pieces are validated** (v0.17) with the rest of the story, by
`validate_content` and doctor (`validation.check_set_pieces`, rules in
`set_pieces.set_piece_problems`). Each of these is an error naming the
challenge file and the piece: a missing or duplicate `id`; a `location_id`
not in the graph; a `requires:` the grammar cannot read; `requires_flags` or
`forbids_flags` that are not a LIST of flag names (a bare string would gate
on its letters); a `grants_flag` that is not one flag name (no spaces); a
`challenge` the spec validator rejects (unknown `kind`, a puzzle with no
`answer`, an empty gauntlet); an outcome effect no set-piece may apply (the
model-composed set, the structural kinds, `release` and the story's own
values are allowed); a `retry` other than `next_day` (the only value); and
`release` anywhere but a challenge's SUCCESS outcome. That means a `reward` (on a decision tree, only a success node's)
or a dice-table row (a roll always succeeds), never a `fail` block and never
outside the `challenge`. Mind the dice table: the runner treats EVERY row as
a success, so `release` is allowed in every row, including one you wrote as
a flavour failure ("the guard wakes"). A row that should keep the prisoner
held must simply not carry `release`, and for a break-out that can truly
fail, use a puzzle, gauntlet or decision tree, which have a `fail` outcome.

### 3.12 `paths.jobs` — authored jobs and guild contracts

`paths.jobs` names ONE YAML file: a burglary held in state from `burgle` to a
close, walked stage by stage, plus the anchored premises whose strongroom is
more than a `score` roll. Optional, and pays nothing when undeclared — no
`job`/`abort`/`flashback` verb is ever offered, the payload carries no `job`
key, and `advance_time` never calls `jobs.tick`. It opens on a premise
(`paths.premises`, §3.10) — a story with jobs and no premises is a load fault
naming the file, because a job with nothing to rob is a whole system that can
never be entered. The shipped worked example is HUE & CRY's
`games/hue-and-cry/data/rules/jobs.yaml` — every security row of its eight
house types and four anchors given a line, the Treasury's `vault_floor`, and
the measured numbers with the story behind them in its header
(`scripts/simulate_jobs.py`, CHANGELOG.md); its contract recipe is
`gannet_silk_row` in `data/rules/threads.yaml`. The examples below are
illustrative unless they name that file, and the synthetic
`tests/test_jobs.py`'s `JOBS_SPEC` exercises every key.

**The five stages, always in this order:** `approach` (get to the house
unseen), `entry` (get in), `inside` (past whoever and whatever is in the
way), `score` (the strongroom or its equivalent) and `getaway` (get clear
with the take). `stages: {<name>: {hours}}` must give all five and no others
— an anchor's own extra stages live under `anchors`, not here.

- `tier_band: {<tier>: <band>}` — the band a job on a premise of that tier
  starts from, before any stage shift. Must cover every tier a premise type
  or anchor can actually have (from `paths.premises`), or the loader refuses
  naming the file: a tier nothing bands is a job that cannot be planned.
- `entries: {<id>: {skill, shift, label, hurts}}` — the entry stage's ways
  in, each its own skill and shift off the base band, and a `label` (never
  the id) for the `job` verb's options. `hurts` (optional, default false) is
  the one thing that turns an entry failure into a physical fall (one hp,
  then the story's ordinary death rules) instead of only noise — a `roof`
  or a cellar drop would carry it; a `door` or `window` would not. A
  respawn's hours count as the watch's hours: with the alarm raised, the
  watch can arrive while the thief is down, and its arrest scene is open
  when they wake.
- `approach: {skill, shift}` — one roll, the same for every premise.
- `inside: {awake: {skill, shift}, asleep: {skill, shift}}` — which row
  answers for a given obstacle depends on whether whoever (or whatever) is in
  the way is awake right now; a security **feature** obstacle (a dog) always
  rolls as `awake`, since a feature has no schedule to be asleep on.
- `score: {skill, shift, draws: {<tier>: <n>}}` — `draws[tier]` loot rows are
  sampled from the premise's own `loot` (§3.10) without replacement; an
  anchor's score takes **all** of its loot, ignoring `draws`. A cased secret
  (§3.10's `secrets`) is named in the receipt the moment the score succeeds,
  never before; the narrator is told it was FOUND, and that it is the
  thief's only if they get clear. From v0.15 it is **held** once the job is
  carried out — the getaway that closes it `clean` or `noisy` writes,
  through `apply_effect`, the flag `secret_held:<premise id>:<secret id>`
  (what the `secret_held` predicate reads) and an engine-sourced ledger fact
  of `kind: secret` about the premise's owner. Caught, aborted or hurt, the
  thief holds nothing: the Watch or the house has what was found. The
  getaway's receipt line says the thief came away holding it and, when the
  secret names a `thread`, who it is a lever over (the thread's `source`, by
  name) — never a price, since whether the squeeze can be struck is the
  thread's own gate. An uncased secret is not taken: the thief does not know
  what it would be holding. The lever is what was READ — nothing reaches the
  pack — so a blackmail's terms should never promise to hand an object back.
  A **clue** (§3.10's `clues.yaml`, v0.16) is kept on the same terms but
  needs no casing: the score's receipt carries its words (`clue`) whether or
  not the house was watched, and the getaway that carries the job out writes,
  through `apply_effect`, the flag `clue_found:<clue id>`, an engine-sourced
  ledger fact of `kind: clue` (no subject) and the story's `evidence` meter
  +1, and its receipt carries `clue_taken` and `evidence` (the meter's band
  word). The narrator hears the clue's words at the score and again when it
  is kept — never whom it points to. A house an agenda emptied first still
  holds its clue.
- `getaway: {skill, shift}` — the last roll; success or a costly `partial`
  carries the loot out HOT (`stolen_from`) and marks the premise robbed
  (`jobs.robbed`, read by `burgle` so a robbed house is never offered again,
  and by the `premise_robbed` predicate below).

**`features` and `tools`** — what a premise's own security, or what the
thief carries, does to a roll:

- `features: {<security id>: {stage, entries, shift, known_shift, obstacle}}`.
  The key must be a security id **some premise type or anchor actually
  declares** (§3.10) — a feature nothing can carry would load, validate and
  change nothing, the drafting failure this repo has shipped before, so it is
  a load-time fault naming the file instead. `stage` is a single stage id:
  one of the five, **or an anchor's own stage id** (`anchors.<id>.stages[].id`,
  below) — a security row on the vault floor is as real a feature as one on
  the front door. `shift` applies while the feature is not yet cased,
  `known_shift` once it is (`security:<id>` in `premises.known`). Both
  default to **0**, and `known_shift` defaults to 0, **not** to `shift`: a
  feature authored with only `shift` stops mattering the moment it is cased.
  Give both the same number for a feature that reads the same whether or not
  it was cased (say, a forge's glow that is there either way). A feature is
  named among the reasons at its stage only when it moves the odds: an
  uncased one when its `shift` is not 0 ("…, not yet cased"), a cased one
  when its `known_shift` is not 0 or differs from its `shift` ("…, cased
  already" -- so casing that took a lock's shift to 0 still says so). A
  feature authored with both at 0 is never named.
  When `stage` is an anchor's own stage id, that anchor's own `security`
  (§3.10) must declare the feature — only that anchor's premise ever reaches
  its stage, and a roll there reads only the robbed premise's own security,
  so a townhouse's lock named against the vault floor is a load fault naming
  the file.
  `entries` (optional) restricts a feature to named entries; it binds only at
  the `entry` stage, so `entries` on a feature whose `stage` is anything but
  `entry` is a load fault naming the file. `obstacle: true` (default false)
  makes the feature a real obstacle in the `inside` list (a dog, not a lock)
  and its shift then applies **only to its own roll**, never to the roll
  against whoever else is in the house. It is allowed **only with `stage:
  inside`** — obstacles exist only there, so the loader refuses it on any
  other stage, naming the file.
- `tools: {<item id>: {stage, entries, districts, shift, consumed}}`. The key must be a
  real item (`data/items/`). `stage` is a name or a list of stage ids, same
  widened set as `features` (the five, or any anchor's own). `entries` binds
  only at `entry`, same as a feature's, so `entries` on a tool whose `stage`
  list does not include `entry` is a load fault naming the file. `shift`
  defaults to 0. `consumed: true` (default false)
  removes the item the moment it helps a roll that used it — a smoke pellet
  spent at the getaway, lockpicks that are not.
  `districts` (optional, a name or a list) limits the tool to jobs on
  premises standing in those districts, at every stage it names — HUE &
  CRY's forged Hill pass (`districts: [margraves_hill]`) is shown at a Hill
  gate and door and is a scrap of vellum anywhere else. Each name must be a
  location **that `districts.yaml` puts at least one house in**; an unknown
  location, or one with no premise (a row that could never apply), is a load
  fault naming the file. A row without the key applies in every district,
  exactly as before.

Every step above (base band, then features, then tools, then a banked
flashback shift — see below) is summed and clamped **once**, so a tool that
eases a legendary climb is never swallowed by a clamp applied partway. The
narrator is handed the human reasons ("a good lock on the street door, not
yet cased", a tool's own name, "what you set up beforehand") and never a
number, an id or a band name.

**Degrees, Blades-style.** A roll's degree decides the stage, not a
pass/fail line:

- `success` / `crit_success` — advance the stage cleanly. `outcome: clean`,
  except at the `getaway`, where the job closes `clean` only if the alarm is
  still at 0 and `noisy` otherwise, however well the last roll went.
- `partial` — advance anyway, at a cost: the alarm rises by `alarm.on_fail`
  and the outcome is `noisy`. The thief gets through, but not quietly.
- anything else (`failure`) — the stage does **not** advance: the alarm
  rises by `alarm.on_crit_fail`, and depending on where it happened, one of —
  `inside`, against a household member in the way: they SEE the thief, a
  real Law witness, `outcome: seen`; at an entry marked `hurts`: a fall, one
  hp and the death rules, `outcome: hurt`; anywhere else: `outcome: noisy`
  with nothing gained.

**`alarm: {max, bands, on_fail, on_crit_fail, watch_delay_hours, deed}`** —
`on_fail` defaults to 1, `on_crit_fail` to 2 and `watch_delay_hours` to 0 (the
watch arrives the moment the alarm is raised). A bounded meter, `bands` naming every level *below* `max` (`max` words, reaching
it is always said as "raised" — never authored). `deed` is the Law deed kind
a raised alarm (or a seen household member) files; it must be a real deed
when `paths.law` is declared, and is never read otherwise (a job commits no
deeds without a Law). `watch_delay_hours` is how long after the alarm is
raised the watch actually arrives — `jobs.tick`, called from
`advance_time` (rule 2: jobs advance on in-game hours, never the wall-clock
tick -- `run_turn`'s background tick does not run at all while a job is open,
and is re-stamped so the paused real time never arrives as a burst of hours
once it closes), closes the job `caught` and opens `arrest.encounter` once that many
hours have passed with the alarm still raised, or `aborted` with no Law (or
no loaded arrest scene) to catch anyone.

**`prep: {max, per_case, bands}`** — `per_case` defaults to 0 (casing then
earns no prep at all). A second bounded meter, `bands` naming
every level from 0 to `max` inclusive (`max + 1` words). Prep is earned
**only** by casing (`premises.case`, §3.10): a successful case pays
`per_case`, capped at `max`; a refused case (nothing left to learn) pays
nothing. It never moves any other way, and it is spent by flashbacks below.
Always a band word to the narrator, never a number.

**`flashbacks: {<kind>: {label, stage, requires, cost, effect, exposure}}`**
— what the `flashback` verb offers mid-job: the thief arranged something
beforehand, and it pays off now without moving the clock (rule: a flashback
never calls `advance_time`, never rewrites a stage already resolved). A kind
is offered when its `stage` (a name or list — the five or an anchor's own,
same widened set as `features`) includes the job's current stage, it has not
been used already this job, and both hold:

- `cost: {prep, gold}` — read plainly and never spent to find out whether the
  kind is affordable; only an offered, affordable kind may be called.
- `requires` — a condition through the shared grammar (`quests.evaluate_
  condition`, §3.7), with `{district}` and `{premise}` filled in from the
  open job before it is evaluated — so one authored `requires: {visited:
  "{district}"}` reads correctly against whichever house the player is
  actually robbing. Every predicate name in it must be one the grammar
  actually has (including the three this module registers, below) or the
  file fails to load naming itself — an unknown predicate is unmet forever,
  silently, otherwise.

`effect` is exactly one of:

- `{shift: <int>}` — banked into the current stage's odds
  (`active.shifts[stage]`) as "what you set up beforehand"; it counts in the
  one clamp above like any other step.
- `{remove_obstacle: <n ≥ 1>}` — removes the first `n` obstacles from the
  `inside` list, initialising it first (the same deterministic household
  read a roll there would do, on no stream) if nothing has touched `inside`
  yet. **`remove_obstacle` may only be authored on a flashback whose `stage`
  is `inside` and nothing else** — the loader refuses any other `stage` list
  naming the file, because a flashback offered off `inside` would otherwise
  write an obstacle list at the wrong stage and leave `inside` silently
  skipped by the time the job reached it.
  "First" means the order the premise file lists its `household` (then its
  obstacle features), among whoever is home when `inside` is first read — so
  an author decides whom a bribe buys by that order. HUE & CRY's Treasury
  lists its night guard first for exactly this. The list is read ONCE, then
  at every roll inside anyone no longer at home is dropped from it first
  (never rolled against, never a witness) and whether each one left is awake
  is re-read; someone who comes home after it was read is not added.

`exposure: household` (optional, the only value) draws one member of the
premise's **whole household** (not only whoever happens to be home tonight —
the servant you bribed need not have been on shift) on the `JOB` stream and,
only with a Law declared, makes them a real, named witness under the alarm's
own deed; with no Law, nothing is drawn and nothing is filed.

**`anchors: {<anchored premise id>: {after, stages: [{id, label, skill, band,
hours}]}}`** — an authored job's own extra stages, spliced into the five
right after `after` (one of the five). Each stage needs a unique `id` (in
the same namespace as the five — a `features`/`tools`/`flashbacks` `stage`
list may name it once declared), a `label` (the only thing the narrator or a
`job` option ever says — never the id), a real `skill` and `band`
(`DIFFICULTY_BANDS`), and its own `hours`. It resolves exactly like any of
the five — one roll, the same degree table, the same alarm consequences —
except its band and skill are authored outright rather than derived from
`tier_band`. A `features` or `tools` row may target an anchor's stage id the
same as any of the five (for instance, an anchor whose own `security`
declares an `iron_bar` could name it, and a lockpicks tool row, against its
`vault_floor` stage), and both are read there exactly the same way: the security feature's
`known_shift` once cased, a carried tool's shift, banked flashback shifts —
summed and clamped once, same as anywhere else.

**The four predicates this module registers**, for `flashbacks.*.requires`,
guild contracts (below) and anything else in the shared grammar:

- `premise_cased: {min, premise?}` — at least `min` intel rows are known
  about `premise` (default: the open job's own).
- `premise_robbed: {premise?, type?, district?, owner?}` — a **finished**
  job (one that reached `clean` or `noisy`) carried the score from a premise
  matching every filter given; with none given, any robbed premise does.
  `owner` is `premises.owner` (an anchor's declared owner, else the first
  household member; §3.13). This is the hook a guild contract's
  `discharge_requires` reads. A house an agenda robbed first (§3.13) still
  counts once the player's job carries its (empty) score out.
- `job: {open}` — whether a job is under way right now (default `true`).
- `secret_held: {premise?, secret?}` — the thief holds a secret carried out
  of a job matching every filter given; with none given (or `true`), any held
  secret does. A bare string is a secret id. This is what a blackmail
  thread's `requires` reads (below).

**Blackmail is a thread too** (v0.15). A secret's `thread:` names an ordinary
template tagged as the story likes (HUE & CRY: `Blackmail`), whose
`requires` gates on `secret_held` and on where — and when — the person it
squeezes can be found; `on_seal` may cost something the moment it is struck,
`discharge_requires` is going back to collect, `on_discharge` pays (coin, or
a `quash_reports` for a captain looking away), and `on_break` is the victim
acting on the two days you gave them: a `report` of a deed your `law.yaml`
names, filed in their jurisdiction, and/or a `reputation` loss. HUE & CRY's
four are in its `data/rules/threads.yaml`; its `blackmail` deed and why it
is filed only on break are in its `law.yaml`.

**Guild contracts are threads, not a new mechanism.** A contract is an
ordinary `paths.threads` template (§3.4); nothing in `engine/game/threads.py`
changed for jobs, because `offer` / `seal` / `discharge` / `break_thread` /
`expire_due` already do everything a contract needs once `discharge_requires`
can read `premise_robbed`:

- `requires` gates **where it can be struck** — the same `threads.offerable`/
  `can_strike` gate any other bargain uses, so the `bargain` verb only ever
  offers the contract at the Guild's own desk. `premise_robbed` reads "ever
  robbed", not "robbed since the contract", so a contract whose discharge
  reads it should also only be struck while no matching premise is robbed
  yet — `requires: {all: [{at_location: …}], none: [{premise_robbed: …}]}`,
  as HUE & CRY's `gannet_silk_row` does — or a robbery done before the
  contract pays it on the spot. (Since v0.16 that `all:` also holds
  `{flag: guild_initiated}`, and a `refusals:` row says why before the
  initiation deck's oath: a Guild's work is for its own members.)
- `discharge_requires: {premise_robbed: {type: <premise type>, district:
  <location>}}` (and/or `has_item`, for "bring back the ledger itself" rather
  than merely robbing the place) gates `discharge`: refused, paying nothing,
  until a job has actually robbed a matching premise. Filters combine — a
  contract for a townhouse in one district is not discharged by robbing the
  right *type* in the wrong *district*, or vice versa.
- `on_discharge` pays the fee **net of the Guild's cut** as one plain `gold`
  effect — the arithmetic is the author's, at YAML-authoring time; the
  engine does not compute a cut, it applies the number it is given.
- `on_break` (via `expire_due`, once `due_in_days` passes unpaid) sours the
  Guild: a plain `reputation` effect against the Guild's own faction id.
  Both `gold` and `reputation` are on every thread's ordinary allowlist
  already (`engine/challenges/spec.py`'s `ALLOWED_EFFECT_TYPES`) — nothing
  Law-shaped is needed here, unlike the Law's own `quash_reports` (§3.11),
  so no new engine surface was added for this recipe.

Worked example (a synthetic one, the fixture `tests/test_jobs_authored.py`
runs; not any shipped story's contract):

```yaml
# threads.yaml
templates:
  guild_job_treasury:
    source: guild
    terms: "Empty a townhouse strongroom in the Square. Robbery only — no bloodshed."
    requires: { at_location: edgewood_square }   # struck only at the Guild's desk there
    due_in_days: 5
    discharge_requires:
      premise_robbed: { type: townhouse, district: edgewood_square }
    on_discharge:
      - { type: gold, delta: 18 }                # the fee, already net of the Guild's cut
    on_break:
      - { type: reputation, faction: guild, delta: -8 }
```

Struck (`threads.offer` → `threads.seal`), it sits active and undischargeable
until a `burgle` on a matching townhouse closes `clean` or `noisy`; then
`discharge` pays the 18 gold and closes it `discharged`. Left unpaid past its
fifth day, the next `expire_due` sweep (every day tick, same as any other
thread) closes it `broken` and costs the Guild's good opinion instead.

**The client and the narrator.** Once `paths.jobs` is declared, the payload
carries a stable `job: {active: null | {premise_name, stage_label, stages,
at, alarm}, prep: <band>}` (`prep` lives only at this top level — casing
raises it whether or not a job happens to be open). `active` is `null`
between jobs; every stage name in it is a word, never an id or a band. The
narrator's own block (`prompts.job_block`) says the house, the current
stage, the obstacle in the way, the reasons moving the odds, which flashback
paid off this turn, the alarm's band, and — the turn a job closes — how it
ended; all in the same words, nothing the client payload doesn't also say.

The payload also carries `scales` (the `prep` and `alarm` words, low to
high), and core's job panel (`ui/src/core/panels/JobPanel.jsx`, the `job`
entry of `ui.panels`, in the shelf by default) draws it while a job is open:
the house, the stages as a stepper, the alarm and prep as words with marks.

**NOT WIRED** (`docs/GOVERNANCE.md`): **hired hands** (spec §4, an optional
extra the design allows for and this release does not build).

### 3.13 `paths.agendas` — what the world does while you are not looking

`paths.agendas` → one YAML file, loaded and validated by
`engine/world/agendas.py`. It is what lets a story's NPCs run their own
authored plans on the clock — no model call anywhere, every move and
reaction is data the engine evaluates, on in-game hours, inside
`clock.advance_time`. The shipped example is
`games/hue-and-cry/data/rules/agendas.yaml` (three agendas: a thief chosen by
the seed, the watch captain hunting them, a rival working the guild) — read
it alongside this section; its header comments carry the gotchas below in
the story's own words.

**Shape:**

```yaml
roles:                          # optional: hidden identities the SEED chooses
  magpie:
    from: [npc_wren, npc_silas, npc_imelda]   # scheduled NPC ids
    mask:                       # optional; see §3.8 for the masking rules
      instead: "the Magpie"
      unmask_when: {flag: magpie_unmasked}
      aliases: {npc_wren: ["the lamplighter"]}

agendas:
  the_magpie:
    owner: {role: magpie}       # or a scheduled npc id directly
    goal: "steal every shining thing"          # GM-facing only; never narrated
    clock: magpie_spree         # a story clock, declared `visibility: hidden`
    moves:
      - id: lift_a_shiny
        every_hours: 24         # cadence, at least 1 hour
        start_hour: 0           # optional: first eligible absolute hour
        at_hours: [1, 2, 3]     # optional: fires only on these hours of day
        when: {none: [{flag: magpie_caught}]}    # the shared condition grammar
        select: {premise: {tier_min: 2, not_robbed: true, loot_tag: shiny}}
        effects: [{type: report, deed: burglary, guise: magpie, ...}]
        advance: 1              # clock delta, applied through the `value` effect
        robs: true              # optional: the selected premise counts as robbed
        trace: {text: "...", where: target, public: false}
    reactions:
      - id: the_captain_hears
        "on": {reported_to: {npc: npc_ardane, guise: magpie}}   # edge-triggered
        once: true
        effects: []
        advance: 1
```

**`"on":` must be quoted.** YAML 1.1 (what PyYAML's `safe_load` implements)
reads a bare `on:` key as the boolean `true`, not the string `"on"` — so an
unquoted reaction trigger loads as `{True: {...}}`, the loader's
`body.get("on")` finds nothing, and you get "a reaction needs an `on`
trigger" pointing at a file that looks like it has one. Always write
`"on": {...}`. The loader catches the slip: a reaction keyed `true` with no
`on` is a load error naming the file and telling you to quote it.

**Moves** fire on a cadence (`every_hours`, first eligible at `start_hour`),
optionally restricted to hours of day (`at_hours`), gated by `when`, and only
when their `select` finds a target (a move with no candidate does not fire
and does not stamp its cadence — it tries again next time it is due).
Selectors: `premise {district?, type?, tier_min?, tier_max?, not_robbed?,
loot_tag?, owner?}` (a district's declared premises, generated and anchored
alike — `not_robbed` excludes both the player's own scores and every other
agenda's `hits`); `fence {district?}` (a vendor with `fence: true`);
`witness {knows: <guise>, jurisdiction?}` (an NPC holding a live sighting of
that guise). A firing move substitutes `{target}`, `{target_name}`,
`{target_district}`, `{target_jurisdiction}`, `{owner}` into its effects,
advances its clock by `advance`, and — with `robs: true` — records the
premise as taken through the agenda's own `hits` (never the player's
`jobs.robbed`). Since v0.16 the pass stamps every `report` a move (or a
reaction) files with `agenda` (its id) and `hour` (the absolute hour it
fired at, overwriting anything authored -- the stamp is the pass's to say),
and a robbery's hit carries the `deed_id` of the first report that firing
filed; a move that filed nothing (or whose report was refused) leaves a hit
with no `deed_id`. That join is what `alibi` reads (§3.11). **Trace text
may use only `{target_name}`**: the others are ids (or a masked role's npc id) that would print into the narrator's
material, and any of them in a trace is a load error. A `premise` selector
never picks the house of the player's OPEN job. A house an agenda robbed can
still be burgled — the thief need not know — but its score finds the
strongroom stripped: the receipt says `emptied` and nothing is drawn, EXCEPT
that an agenda never takes a collectable set's piece — the score takes every
loot row whose item names a `collection:` (`jobs._left_by_agendas`), the
close records them in `jobs.last`'s `left`, and the narration says the house
was robbed of everything but them. The close still records the house
robbed, so a contract on it can be paid.

**No trace may name a role candidate.** Every candidate's display name and
every declared alias, of every role, is refused in trace text (private or
public), naming the file — matched as the mask matches (word-bounded, the
proper noun case-sensitive). The mask covers only the seed's chosen NPC, so
a trace naming another candidate would reach the narrator unmasked; one
naming the chosen one is the link itself. This holds for a trace in an
agenda the candidate owns outright, too (a Silas-owned move's sign may not
say "Silas").

**Reactions are edge-triggered**, not level-triggered. `truth` is the value
of `on` as evaluated the LAST time this reaction was checked — evaluated
before the reaction's own effects apply, and written after them (so an
effect a reaction fires cannot change the edge it fired on). A reaction fires when `on` is
true now and `truth` says it was false (or unrecorded) last time; `once:
true` then fires at most once ever, otherwise it fires again after `on`
falls and rises. **On an old save, or on a state's very first agendas walk,
a condition that already holds counts as an edge** — there is no "before" to
compare against, so the first evaluation IS the rising edge, and the
reaction fires at the first hour boundary the pass walks. Author reactions
knowing a save loaded mid-story can trip them immediately if their condition
already holds.

**Predicates** the shared condition grammar gains, for `when`/`on`/
`unmask_when` alike (all refused at load, naming the file, if the story
declares no Law where a Law is needed): `wanted {guise?: self, jurisdiction?:
<here>, min: <band>}` — that face's wanted band in that jurisdiction is
`min` or above, in the Law's own band order. **`own: true`** (v0.17,
opt-in) counts only the player's OWN deeds: report rows the agendas pass
stamped (`agenda`/`hour`, filed by a move -- the Magpie's robberies landing
on a mask the watch links to your face, or Ardane's own statement) are left
out, and everything the player did still counts, under any linked guise
(`law.wanted_band(..., own=True)`); each file's cooling stands as it is.
Absent, every row counts, exactly as before. HUE & CRY's Honest After All
gates on it, so the Magpie robbing on your name does not keep an honest
thief off the barge. The validator checks a `wanted` condition in ANY story
file -- a known band, guise and jurisdiction, and `own` a boolean -- not
only an agenda's; `reported_to {npc, guise?:
self}` — that person holds a LIVE (not discharged, not lost to a bribe)
witness row for a face the watch links to `guise`; `agenda_hit {agenda?,
premise?, district?}` — some agenda's `hits` record a match. `premise_robbed`
(declared with `paths.jobs`, engine/world/jobs.py) gains an `owner` filter
here too: `{premise_robbed: {owner: npc_gannet}}` is true once a FINISHED job
(the player's own) has robbed a premise that npc owns — this is how an
agenda reacts to the player robbing a house that matters to someone, without
a bespoke flag per house.

Two more Law predicates are open to an agenda and need a Law just the same
(`engine/world/agendas.py::LAW_PREDICATES`): `in_custody` (§3.11) and, since
v0.15, `filed {jurisdiction, guise?, linked?}` — something live on file
there (§3.11's "Something to lose"); an agenda naming an unknown
jurisdiction or guise in `filed` is refused at load. Since v0.16, two more:
`linked {a, b}` and `alibi {agenda?, min?, open?}` (both §3.11; an unknown
guise, an undeclared agenda, a `min` below 1 or a non-bool `open` is
refused at load).

`agenda_role {role, npc}` (v0.16) is true iff the seed chose `npc` for
`role` -- `{agenda_role: {role: magpie, npc: npc_wren}}` in the seeds where
Wren is the Magpie. It reads `agendas.role` (derived from the seed, never
stored) and advances no stream, so asking it changes nothing. **It is a
condition only**: no prompt block renders it or its answer, so a card or a
clue may branch on who the Magpie is while the narrator still does not know
(`tests/test_law_memory.py` holds this). An undeclared role, or an `npc`
that is not one of the role's `from` candidates, is refused at load in an
agenda gate; elsewhere either is simply false. Its companion for the trail
the seed lays through the houses is `clues_favour {npc, min?, excluding?}`
(§3.10's `clues.yaml`), a condition only on the same terms. HUE & CRY's
accusation (`data/scenes/lantern_house_desk.yaml`) uses both: the card for
a suspect is dealt only while the clues favour them, and whether naming
them is right is its beat's `agenda_role` gate, resolved when the player
names them.

A gate cannot read a StoryLedger or a quest's progress (the pass runs inside
`advance_time`, which holds neither): `disposition`, `days_in_stage` and
`days_since_started` are load errors naming the file, not silently-false
gates.

**Masking (see §3.8 for the full rule).** A role's `mask` protects the
role↔NPC link only in text the agendas themselves author — a trace's text,
and a public trace once it reaches the moved journal. It does **not** touch
the cast block, the storyteller prompt, or the narrator's own prose: masking
one candidate's name everywhere would itself point at them by making that
one person's name behave differently from the other two. **List every short
form your traces can produce** in `aliases`, keyed by candidate — a nickname,
a title, an epithet, every case form the prose actually uses (the display
name itself is matched case-sensitively and in full; "Silas" is not masked
unless `aliases` lists it, even though the display name is "Silas Crook").
Once `unmask_when` holds, the GM-only line in the clocks block gains a
reveal — "WHO THE MAGPIE IS (the player has earned this; name them freely):
Wren, the lamplighter." — and agenda text starts naming the chosen NPC
normally.

**What the narrator sees, and no more.** Progress reaches the prose only as
the agenda's clock label and band in the GM-only `_clocks_block` — never the
goal, an id, or a number. A private trace surfaces only at its own location,
as "SIGNS HERE" in the prompt, until narrated; a public trace goes straight
to the moved journal, unlocated, as common talk. A story that declares no
`paths.agendas` pays nothing: prompt, legal intents and payload are
byte-identical to one that never heard of this system.

**NOT WIRED** (`docs/GOVERNANCE.md`): agenda moves posted to the notice
board; a `fence {most: hot_goods}` selector (fences hold no stock to count);
`disposition`/quest-progress predicates in agenda conditions (no ledger, no
quest, in scope).

### 3.14 `survival.yaml` — hunger, rest and a meal

Found by fixed name inside `paths.rules` (§2.2) and read by
`engine/game/survival.py`. Shipping it is a decision with two halves: it gives
the story a `rest` verb (one enum target per `rest:` entry, offered in every
place and in custody), and it makes walking cost stamina — 5 per hour of road
— because the engine only charges stamina a story can give back (AGENTS.md
rule 6). Leave it out and the story has neither. Models:
`games/clockwork-dark/data/rules/survival.yaml` (the flagship),
`games/neon-city/data/rules/survival.yaml`,
`games/hue-and-cry/data/rules/survival.yaml` (priced and gated beds).

- `hunger` — `per_hour`, `max`, `thresholds` (`peckish`/`hungry`/`starving`),
  `hungry_stamina_cap_penalty`, `starving_hp_per_hour`. The Law's gaol rations
  are timed against `per_hour` and `starving`.
- `rest.<kind>` — `hours`, `stamina` (a number or `full`), `hp`, `text`, an
  optional `check: {skill, difficulty}` with `on_failure: {stamina, hp, text}`.
  Three optional gates, each downgrading to the entry's `fallback` when unmet
  — **never a refusal**, and followed as a chain, so a gated fallback is asked
  too:
  - `locations: [...]` — where somebody keeps such a bed.
  - `requires:` — a condition in the shared grammar (§3.7): a guild's bunk
    `{reputation: {faction: x, min: 0}}`, the cells `{in_custody: true}`.
  - `cost: N` — the price in the story's coin, paid at the door through the
    `gold` effect; the receipt carries `paid` and the narrator's receipt line
    says "paid 3 cr for the bed". A purse short of it downgrades.

  An unmet `requires:` may say why, in the story's voice:
  `refusals: [{when, text}]`, the same shape a thread uses. The first row
  whose `when` holds is the downgrade's note, in place of the generic "that
  bed is not yours tonight". HUE & CRY's guild bunk tells an unsworn thief
  that the Company receives newcomers after dark. It is still a downgrade,
  never a refusal.

  **Give every gated entry a `fallback` that is not gated** — the story's
  rough night. An entry whose gate fails with no fallback is slept in anyway
  (unpaid), because refusing rest is the soft-lock rule 6 forbids. A story
  whose entries declare none of the three keys gets exactly the receipt it
  always had: no `paid` key, no gold moved.
- `eat` — `hours`, `items.<id>: {hunger, stamina, text}`, a `default` row, and
  `edible_tags` (anything carrying one is edible through `default`). A meal
  needs an item in `paths.items` and, to be bought, a vendor row in
  `paths.economy`.

### 3.15 `paths.social` — a phone the engine runs

`paths.social` (v0.22.0) names a DIRECTORY. Its files are found by fixed name
(`engine/social/__init__.py::FILES`): `creation`, `population`,
`behaviours`, `apps`, `relationships`, `media`, `venues` and `games`
`.yaml`, plus `words.txt` beside `games.yaml`; since v0.23.0 also
`conversation`, `promises`, `growth`, `topics`, `layers`, `plans`,
`scenes`, `life_events` and `homes` `.yaml` (`growth`, `topics` and
`layers` are read by `engine/social/growth.py`, `conversation` by
`engine/social/convo.py`, `life_events` by `engine/social/life.py`
and `homes` by `engine/social/places.py`, below), and `activities.yaml` found beside `paths.locations` rather than in
the directory (`social.world_dir()`, read into `load_all()["activities"]`,
`{}` when absent); and the story's
`prompts/texter.md` (for what
a person remembers, `prompts/episode_recap.md`, below). READ RECEIPTS
(`games/read-receipts/`) is the one shipped story that declares it, and
each of its files opens with a header that documents every key: read those
headers beside this section, which is the map. A story that declares the
key is played on two layers: the phone, through phone actions
(`phone_action`, no model), and since v0.23.0 the world, through the
ordinary narrated turn (`player_choice`), refused only while the phone is up
(below, "The world"); its client is a plugin with its own `PlayScreen` and
`NewRun` (§2.5).

**Background people, and `npc_schedules` in a phone story (v0.23.0).** A
phone story MAY also declare `paths.npc_schedules` for the people who belong
to a place and are not on the phone (READ RECEIPTS: two baristas, two bars'
staff, a concierge, two neighbours). The rows are the ordinary `npc_sim`
shape (`name`, `role`, `routine` slots of `hours`, `location`, `activity`,
`available`) with NO `home`: off shift a person resolves to no location, so
`npcs_at` never lists them. The cast is never a row there (engine/social runs
it), so the cast gate's roster is these people only, and a contact's name is
checked by the agreement check as before. Keep their first names out of
`population.yaml`'s lists (`tests/test_rr_people_around.py`). They show in
PEOPLE HERE and the dossiers only while on shift; no people strip is declared.

What is fixed and what is yours: the people are a pure function of the seed
and an index (`population.py`), every decision about them is the engine's
(rule 1), and the model only writes what they say (`texter.md`). Every
number in these files is a balance constant: run
`scripts/simulate_social.py` before changing one (rule 10; §5.2).

**Checked twice.** Each file is parsed and checked when the story's data
loads (`social._check_loaded`: `behaviours`' arcs and canon,
`relationships`, `media`, `venues` with `relationships.meets`, `games`,
`conversation`, `growth` with `topics` and `layers`, `plans`, `scenes`, `life_events`, and `activities` refuse to load with a `ValueError` naming file and key), and every file is
checked whole by `scripts/validate_content.py` and the doctor
(`engine/games/validation.py::check_social`, one finding per fault). A file
that is absent reads as empty, and most blocks are then required: ship all
eight of v0.22.0's, and `conversation`, `growth`, `topics` and `layers`;
`promises`, `plans`, `scenes` and `life_events` are checked once they have any
rows (`homes` is checked by nothing yet).

#### `population.yaml` — who is in the apps

Read by `engine/social/population.py`. Nobody is stored: a person is drawn
from these tables on the stream `stable_rng(seed, "social.population:<index>")`
whenever they are needed, so a seed always holds the same people. Only what
happens between them and the player is kept (`state.social["people"]`).

| Key | Shape | Checked |
|---|---|---|
| `filter` | `{sex: opposite \| same \| any, age_from_discovery: bool}` | `sex` one of `population.FILTER_MODES` |
| `age_spill` | the player's discovery range widened by this share either side | |
| `age_bounds` | `{min, max}`, whole numbers; `min` is the apps' age floor (data, never an engine gate) | required |
| `names` | `{female: [...], male: [...]}`, drawn after the filter on its own key | both non-empty |
| `ages` | per dating app `{mean, sd}`, clamped to the discovery range and `age_bounds` | |
| `neighbourhoods` | exactly eleven `{id, label}` rows | eleven distinct ids |
| `distance` | an 11x11 table of whole numbers 0-4, symmetric, 0 on the diagonal (matching's distance term) | every cell |
| `jobs` | `{id, label, shape, education: [...], weight?, article?}`; `shape` names a `schedules` week, `article` (a \| an) where the first letter misleads | each `shape` has a week |
| `schedules` | per job shape, per weekday (`mon`-`sun`), `[start_hour, end_hour, status]` bands; status `asleep \| work \| free \| out`; an hour no band covers is asleep | each band |
| `hobbies` | `{id, label, tags: [...], weight?}`: the tags feed matching's hobby term | |
| `traits` | `{id, label, weight?}`, three drawn per person: character notes for the voice | |
| `personality` | the five slider names, each 1-5 per person | |
| `attribute_tables` | the attribute tables drawn in this order; each a list of `{id, label, weight?}` rows of the same name (`height`, `build`, ...), every id one of `creation.yaml`'s for that attribute | each names a table |
| `appearance` | `{eyes, skin, features}` rows: joined after the attribute labels into the image prompt's description | weights |
| `flags` | `name: probability`, each drawn once per person: the fixed facts a mechanic may gate on (`media.yaml` `requires_flag`) | |
| `texting_styles` | `{id, length, caps, punctuation, emoji, questions, humour, weight}`: character notes for the voice, never rules | |
| `bios`, `like_comments` | per texting style, templates; a template may name only `{hobby_a} {hobby_b} {job} {a_job} {A_job} {neighbourhood}` (`population.BIO_FIELDS`) | each style declared, each name known |
| `prompts` | per app, `[{q, a_by_hobby: {hobby: [...]}, a_any: [...]}]`: Front Porch's three, an answer by a hobby they hold, else `a_any` | `a_any` required |
| `photo_set` | `{id, label, scene}` rows: every person's 2-5 photos (so at least five) and the player's own; READ RECEIPTS ships 33 | |
| `preferences` | `selectivity {mean, sd}` (0-1), `age_below`/`age_above` `[low, high]`, `dealbreaker_count [low, high]`, `dealbreakers: [...]` | |

A table row's `weight` defaults to 1 and must be a positive number where
given. A `dealbreakers` id is `<attribute>_<value>` (`smokes_yes`,
`kids_dont_want`): matching splits it at the FIRST underscore, so an
attribute's own name must not contain one. A person's archetype and what
they are looking for are drawn by their app's `culture` (`apps.yaml`), not
here.

**The filter.** `filter.sex` decides who the apps show: `opposite` (READ
RECEIPTS ships this, the owner's brief), `same`, or `any`. Changing it
changes each person's sex and name and nothing else about them: sex is drawn
on `...:<index>:sex` (only under `any`) and the name on `...:<index>:name`,
keyed by that sex, so every other field keeps its draw. `same` and `any` are
built and tested but no shipped story uses them (a docs/GOVERNANCE.md row).

```yaml
filter: {sex: opposite, age_from_discovery: true}
age_bounds: {min: 18, max: 75}
jobs:
  - {id: nurse, label: Nurse, shape: shifts, education: [degree]}
  - {id: hr_manager, label: HR manager, shape: office, education: [degree], article: an}
schedules:
  office:
    mon: [[7, 9, free], [9, 17, work], [17, 23, free]]
bios:
  dry_one_liners:
    - "{job}. It's fine."
flags: {has_pet: 0.3}
```

#### `creation.yaml` — the player

Read by `engine/social/creation.py`. `GET /api/social/creation` serves the
form resolved (each `of_table` expanded to `{id, label}` rows), and
`POST /api/game/new`'s `creation` object is checked against it: an unknown
key, a value outside its list or range, or a list of the wrong length is
refused naming its dotted field; an omitted field takes its default. A
choice with no `default`, and a `multi`, default to a pick seeded per
dotted field, so adding a field moves no other field's default.

| Field kind | Keys |
|---|---|
| `text` | `max` (required), `default` (required); blank takes the default |
| `choice` | `of: [...]` or `of_table: <population.yaml table>`; `default?` |
| `int` | `min?`, `max?`, `default` (required) |
| `multi` | `of_table` (or `of`), `min`, `max`; distinct ids |
| `sliders` | `of: [names]`, `min`, `max`; each slider defaults to 3 |

A mapping with no `kind` is a group of fields (`attributes:`,
`discovery:`). `start_hour` (0-23) is the hour a new run starts on day 1.
Quote `"no"` and `"yes"` so YAML reads them as words.

```yaml
start_hour: 19
fields:
  name:  {kind: text, max: 24, default: "Sam"}
  age:   {kind: int, min: 18, max: 75, default: 29}
  hobbies: {kind: multi, of_table: hobbies, min: 2, max: 6}
  attributes:
    smokes: {kind: choice, of: ["no", sometimes, "yes"]}
  discovery:
    distance: {kind: choice, of: [near, city, anywhere], default: city}
```

**What the engine reads of the profile**, and so what a field MEANS:
`name` (the run's `player_name`), `sex` (the filter), `age`,
`neighbourhood` (distance), `looking_for` (an intent id, matching),
`hobbies`, `personality`, `attributes` (a person's dealbreakers, and the
profile's completeness), `photos`, `discovery` (`age_min`, `age_max`,
`distance`: a `matching.discovery_distance` key), and `attributes.job`,
`age` and `name` for the agreement checks' "what the player told them".

**Adding a field.** Declare it under `fields:` with a kind; the wizard
(`ui/src/stories/read-receipts/NewRun.jsx`) draws every kind generically,
the engine validates it and keeps it in `state.social["player"]`, and the
validator checks its shape. A field nothing above names is kept and read by
nothing until code reads it: no matching term, no voice block. A new
attribute that people should have too needs a `population.yaml` table of
the same name listed in `attribute_tables` (the validator checks its ids
against the field's), and is then also a possible `dealbreakers` id.

#### `behaviours.yaml` — how people behave

Read by `engine/social/behaviour.py` (rows), `convo.py` (each
conversation's start draws and the initiations by window, v0.23.0),
`messaging.py` (openers, double texts) and `relationships.py` (arcs).
Three blocks: `archetypes`, `arcs` and `canon`. (v0.22.0's `pacing:` block
went in v0.23.0: its reply and ghost terms are `conversation.yaml`'s
`reply:` block, below; a `pacing:` block is now a validation error.)

**The event queue.** Nothing a person does runs on the wall clock. Every
read, reply, opener, double text, initiation, like seen, likes-you arrival,
match expiry, game move, meet-up start and arc beat is an event at an exact
in-game hour in `state.social["queue"]` (`engine/social/events.py`), kept in
`(at, seq)` order and walked inside `clock.advance_time` (rule 2), at most
`social.max_events_per_advance` per advance. The kinds are fixed
(`events.KINDS`); a story chooses only the numbers that time them. At 04:00
each day the `daily` event runs every module's morning step: likes reset,
the day's likes-you, the day's initiations, mood back to neutral, interest
decay, drift, the cold wind-down and the fade, a "later" media request
kept or broken, the games' invites and clean-up (since v0.23.0 media budgets
refill, and unasked media are drawn, as each conversation closes instead). So a time in this file is a time IN THE
GAME, never a wall-clock one. Since v0.23.0 a reply inside a conversation
is never delayed at all (`conversation.yaml`, below): `reply_minutes` times
only an opener after a match and a game's answer.

**An archetype** carries every key of `behaviour.ARCHETYPE_KEYS`, and no
other:

```yaml
archetypes:
  steady:
    reply_minutes: {median: 25, spread: 0.6}   # lognormal, in-game minutes: an opener's delay
    reply_prob: 0.96                # the reply draw when a conversation starts (v0.23.0)
    opener_prob: 0.6                # writes first after a match (an `either` app)
    ghost_per_episode: 0.008        # the ghost draw when a conversation starts (v0.23.0)
    left_on_read_sensitivity: 0.4   # interest lost per hour left on read
    warmth_mult: 1.0                # times the model's proposed warmth
    warmth_cap_band: null           # or a relationships.yaml band warmth never passes
    cool_off_step: 1                # 0-5: interest a `cool_off` proposal costs
    flake_prob: 0.02                # a meet-up flaked on the day
    double_text: {after_hours: 18, prob: 0.15, max_in_row: 1}
    initiations:
      - id: how_was_your_day
        window: after_work          # waking | commute | lunch | after_work | evening | late
        when: {stage_min: numbers, hours_since_player: 18}
        prob: [0.1, 0.4, 0.6, 0.7, 0.75]   # the chance each morning, by disclosure depth 0-4
        kind: text
        instruction: window_message # a row of texter.md's ## Instructions (default: window_message)
    media: {offer_mult: 0.9, accept_mult: 1.0}
    games: {skill: 0.55, invite_prob_per_day: 0.04}
    arc: null                       # or an `arcs:` id
    growth: {pace: 1.0, cap: 4, cap_in_person: 4, decay_mult: 1}   # v0.23.0, below
    promise_prob: 0.85              # v0.23.0: a sign-off carries a promise (drawn from T4)
    offer_number_prob: 0.8          # v0.23.0: they offer their number at depth 1 (drawn from T5)
```

`growth` (v0.23.0, every key required, `behaviour.GROWTH_KEYS`): `pace`
(above 0) multiplies every paced openness gain; `cap` is the deepest
disclosure rung (0-4) they reach on the phone and `cap_in_person` in a
scene; `decay_mult` scales every openness loss (a ghoster's 2: their
openness "decays twice as fast"). See `growth.yaml` below.

`promise_prob` and `offer_number_prob` (v0.23.0, 0-1, required) are read
by nothing yet: the person's sign-off promise is drawn from T4 and the
number offer from T5 (docs/GOVERNANCE.md NOT WIRED).

An initiation (v0.23.0) names a `window` -- resolved against the person's
own schedule (`engine/social/windows.py`: `waking` their first waking
hour, `commute` the hour before work, `lunch` 12-14 if awake, `after_work`
two hours from their shift's end, `evening` 18-22 off work, `late` 22-01
if up) -- and `prob`, five chances, one per disclosure depth. Each morning
every live person's rows are tried in order: the window is resolved for
the day, `when` checked, `prob[depth]` drawn and the minute drawn inside
the window (SOCIAL_CONVO); at most one is queued a day, and none while a
conversation with them is going. When due it is skipped if a conversation
is going, if the player wrote to them within
`initiation.skip_if_talked_minutes`, or if its `instruction` is one of the
situations retired as bare (`good_morning`, `check_in`, `late_night`);
otherwise it lands and starts a conversation. `at_hours`, `prob_per_day`
and a single `prob` are load errors. `when` may name `stage_min` (a live
stage), `hours_since_player`, `days_since_last`, `ghosted` (true: only after
they went quiet, and it brings them back) and `weekend`; nothing else
loads. `kind` is the decision's message kind: every shipped one is `text`,
and a person's photos, voice notes and videos come from `media.yaml`, not
from an initiation.

**Arcs** change a relationship over time. Exactly one of `at` (a point,
counted in `exchanges`) or `from` (a start, counted in
`days_since_matched`), each `{measure: [low, high]}` with a point drawn once
per person; then a `beat` (at the point: `reveal` a `canon:` row,
`history` a line on their card, `instruction` the situation the reveal's
message is written in, `then` a `stage` and `warmth`/`trust`/`interest`/`mood`
moved exactly) and/or `each_day` (from the start, each morning). **Canon**
rows are one fact each, at most 140 characters, added to a person's canon
when a beat reveals them; the voice reads canon and no mechanic does.

```yaml
arcs:
  turner_wants_different:
    at: {exchanges: [8, 30]}
    beat:
      reveal: wants_something_else
      history: Wanted something different
      instruction: reveal_turn
      then: {stage: winding_down, warmth: -10}
canon:
  wants_something_else: has realised that what they want is not what this is turning into
```

**Adding an archetype.** (1) A row under `archetypes:` with every key.
(2) A weight in at least one dating app's `culture.archetype_weights`
(`apps.yaml`), or nobody is drawn with it; an app naming an undeclared
archetype is an error. (3) Every initiation's `instruction` (or id) a row
of `texter.md`'s `## Instructions`. (4) Optionally a `## Fallbacks` block
for it: an archetype with none falls back to the engine's one line, "hey".
(5) A `warmth_cap_band` names a `relationships.yaml` band. Then run
`scripts/simulate_social.py`: its `also.days_to_*` and `also.real_hours_to_*`
rows report the in-game days and real hours from a match to each closeness
band per archetype.

#### `conversation.yaml` — conversations that flow

Read by `engine/social/convo.py` (v0.23.0), and by `turn.py` for `costs`
and `clock`; `convo.check_data` checks it whole at load. A conversation is
an **episode** (`people[pid]["episode"]`, written only by the
`social_episode` effect): it opens when the person answers a cold message
(the draws below), when an opener or an initiation of theirs lands, or (T13)
when a scene starts; it closes when no message passes either way for
`episode_gap_minutes` (a chat only), or when a new one begins after a
sign-off, and the closed row joins `people[pid]["recap_due"]` (at most
`social.recap_due_max`) until its recap is written into the person's
memory (below).

**Instant replies.** While an episode is going, the player's message is read
at its own minute and the reply is due at that same minute: the send's
`advance_time` walks it, so chatting needs no `wait`. A person who is not
available reads it at `convo.next_available`, the first whole hour their
schedule and habits allow -- a boundary, never a random delay. Ghosting,
left on read and the reply itself are drawn once per episode START
(`reply:`), never mid-conversation. A burst (more messages before their
reply is voiced) is answered by one reply, re-decided in place; a message
sent while a voicing pass is already writing the reply is answered by the
NEXT decision, queued when that reply commits (`convo.after_commit`).

| Key | What it holds |
|---|---|
| `costs` | in-game minutes a message costs the player: `text`, `voice`, `photo`, `video` (required), `reply` (0: a reply costs nothing) |
| `clock` | `wait`'s targets, whole hours: `evening`, `morning`; `min_sleep_hours` (sleep's floor, read from T11); `work_lead_hours` (optional, default 2: how long before the player's work band "Go to work" is offered) |
| `episode_gap_minutes` | above 0: no message either way for this long and a chat episode lapses |
| `together` (optional) | `{hold_retry_minutes}`, 1 or more (v0.23.0 W5): while a person is with the player their due texts are held and tried again this many minutes on; they land once the two are apart |
| `habits` | `weights` per archetype (`default` required) of each phone habit's options -- `at_work` `never`/`glances`/`chatty`, `late_night` `no`/`sometimes`/`night_owl` (quote `"no"`: YAML reads a bare `no` as false), `in_company` `rude_not_to`/`glances` -- drawn once per person (a counterless key); `night_owl_shift_hours` |
| `talk` | the nudge: `exchanges` `[low, high]` per archetype (`default` required), the target drawn when it opens; `per_depth` (five), `late_mult` (`default`, `night_owl`; 21:00-04:00) and `work_mult` scale it; `energy_per_exchange`, `short_player_chars`, `short_extra_energy`, `topic_energy_back`; `boundary_minutes` (to their next schedule change: the pressure climbs steeply under it); `winding_at` <= `sign_off_at`; `after_sign_off` `[low, high]` replies still answered; `away_after_sign_off`: minutes they are gone after a sign-off, by what ended it -- exactly `boundary` (at least until the boundary itself), `glance`, `energy`, `length`, `player` -- then their next available moment; `player_chars_kept` |
| `modes` | `chatting_after`, `deep_energy`, `deep_player_chars`; `caps` per mode (`quick`, `chatting`, `deep`): `bubbles` `[min, max]`, `bubble_chars`, `max_tokens`; optional `deep_as_chatting` (true: `deep` is voiced with `chatting`'s caps on any binding, spec §20.2's latency lever, `voicing.mode_caps`) |
| `reply` | the episode-start draws: `depth_factor` (five) and `interest_factor` `[at 0, at 100]` multiply `reply_prob`; `stage_factor` (`default` required) multiplies `ghost_per_episode` x (1 - interest/100) |
| `left_on_read_quiet_minutes` | after they leave the player on read, their next read waits this long or until their next schedule boundary, whichever is first: another message does not re-roll the draw |
| `initiation` | `skip_if_talked_minutes`: a window's nudge is skipped this soon after the player wrote |
| `reasons` | the engine's words for why they wind down, voiced in their own words: `work` (with `{hour}`), `lunch_over`, `asleep`, `out`, `early`, `energy`, `length`, `glance` (a glance at work), `player` (the player said "talk later") |
| `reasons_recap` | exactly the `reasons` keys, each the line a recap uses about them when no model writes it ("they had to go to sleep"; `memory.recap_fallback`) |

**Availability** combines their schedule status with their habits: free
and out answer (out caps the mode at `quick`); at work a `chatty` worker
answers, a `glances` one answers once and signs off, a `never` one does
not; asleep, a `night_owl` is up `night_owl_shift_hours` into their sleep
band and a `sometimes` answers in their first sleep hour (`quick`).

**The nudge.** Each decision weighs three terms -- exchanges against the
drawn target, energy spent, and the minutes to their next schedule boundary
-- a change to LESS available only: work starting for a `never` or
`glances` worker, going out, bed; coming off work, coming home, a chatty
worker's shift start and a night owl's late band are none --
and past `winding_at` they start to wind down, past `sign_off_at` they sign
off with the term's `reasons:` line. The decision's **mode** (`quick`
until `chatting_after` exchanges, and whenever capped; `deep` with energy,
depth 2+, long player messages and one of their rung's topics named) sets
its bubbles; a burst of three raises the minimum to two. The voice reads
the mode, the end and the reason from T7.

**What a person remembers** (v0.23.0, `engine/social/memory.py`, spec §7):
one memory per PERSON, `people[pid]["memory"]`, whatever app the two of you
talk on -- so moving from a dating app to Texts or Natter keeps the
conversation. It holds `current` (the open conversation, both sides, word
for word, `social.memory.verbatim` bubbles), `bridge` (the last
`bridge_bubbles` of the one before: how you left it), `episodes` (each
closed conversation's recap, `{id, kind, where, from_at, to_at, recap,
topics, end_reason}`, at most `episodes_kept`), `story` (the oldest recaps
folded into the story so far, at most `story_words`), `open` (follow-ups
due, at most `open_max`), and `canon`, `knows`, `told` and `history`. A
conversation that ends is recapped by one utility call over
`prompts/episode_recap.md`: the text above its `## The story so far`
heading is the recap's system prompt (one to three sentences, at most
`social.memory.recap_words`), the text below it the story fold's (at most
`story_words`); "you" in both is the phone's owner and the person is
"they". With no model the engine writes the recap from what it knows: the
topics named, why it ended (`reasons_recap:`) and a promise made, and the
story keeps its newest sentences. A **follow-up** (`{about, due_at}`, from
a reply's `followups`, T7, or from a promise the player broke) rides on
the person's next reply once it is due ("ask how it went") and is closed
when that reply is written. Someone you have not talked to for
`dormant_days` keeps their story and three recaps in the save, and the
rest goes to the archive whole (a `recap` row of `phone_archive.jsonl`):
nothing is lost, and when they talk again it is folded back into their
story. Every fold leaves its record there too.

#### `promises.yaml` — promises and sign-offs

Read by `engine/social/promises.py` (v0.23.0); `promises.check_data` checks
it whole at load and in `validate_content.py`. A promise is engine state,
`state.social["promises"]["pr<n>"]` (`{id, pid, by: person|player, window,
opens_at, closes_at, about, made_at, status: open|kept|broken|void,
fallback, message_id?}`), written only by the `social_promise` effect. An
open promise of the same side and window whose span overlaps is the same
promise: it is never made twice. It is made four ways, none of them a
model's free text:

- **the chip**, the phone verb `sign_off {who: me|you, window}` ("Talk
  later"): the player's line (or "Talk later — I'll message you {window}" /
  "Message me {window}?") is sent, the promise recorded, and the person's
  reply signs the conversation off (`reasons.player`);
- **their own sign-off**: their archetype's `promise_prob` (`behaviours.yaml`)
  is drawn when they sign off; a glance at work promises `lunch`, any other
  sign-off the first of `after_work`, `tonight`, `morning` their day has in
  reach, else `later`. Recorded before the reply is voiced;
- **a model's proposal**, `relationships.yaml` `proposals: promise` (its
  `window:` lists the windows it may name), legal only while the
  conversation is winding down or signed off;
- **with no model**, a `phrases:` row stated (not asked, not negated) in
  the player's own message: a pending request the person's next reply
  accepts.

**Whose day the window is.** The sender's -- whoever will write in it --
except `at_work`, which is the receiver's: "message me at work" lands in the
PLAYER's work band, whatever the person's habits. `morning` is their waking
band (never before `conversation.yaml` `clock.morning`; a night shift's
small hours are not a morning), `lunch` 12:00-14:00, `after_work` the two
hours after their last work band, `tonight` 18:00-24:00 while they are up,
`weekend` Saturday or Sunday 09:00-22:00, `at_work` their work band,
`later` their first free band at least `later_min_hours` ahead. A window
their day does not have is their next free band, and its words say so
(`words.fallback`: "after work, so tomorrow morning").

**Keeping them.** The person's promise is always kept: their
`promised_message` falls due inside the window and the promise is kept when
that message is written (void only if they leave or the relationship ends
first), and nobody ghosts while they hold one. The
player's is kept by any message to that person inside the window (trust
`kept_trust`, openness `growth.yaml` `gain.promise_kept`) and broken by
silence until `grace_minutes` past it (`broken`'s trust and warmth,
openness `loss.broken_promise`; the person's next reply carries
`broken_reason` once). `wait {until: promise:<id>}` jumps to one.

**A promise made inside its own window** means that window's NEXT
occurrence: "message you at lunch" said at lunch is tomorrow's lunch, never
the lunch already under way.

| Key | What it holds |
|---|---|
| `later_min_hours` | `later`'s lead, hours (0 or more) |
| `max_ahead_hours` | a promise whose window opens further ahead is refused ("That's too far off to promise") |
| `grace_minutes` | how long past its window a player's promise is broken |
| `closed_kept` | whole number 0 or more, REQUIRED (no default; a file without it fails to load): closed promises (kept, broken, void) kept per person at save compaction; older ones are forgotten and tallied on the person as `promises_closed`, except any a reader still needs |
| `kept_trust` | whole number 0 or more: trust a kept player promise gives |
| `broken` | exactly `{trust, warmth}`, whole numbers 0 or less |
| `broken_reason` | the engine's words the next reply carries, naming `{window}` |
| `phrases` | exactly `you` ("message me ...": the person promises) and `me` ("I'll message you ...": the player does), each a mapping of chip window (`lunch`, `after_work`, `tonight`, `morning`, `at_work`) to a list of phrases |
| `words` | every promise window's words (`lunch`, `after_work`, `tonight`, `morning`, `weekend`, `at_work`, `later`) and `fallback`, naming `{window}` and `{when}` |


#### The phone's own switches and the world layer

The phone verb `set_wake {to: on|off}` (skill `social_set_wake`; Settings' "Wake me for messages") sets
`settings.wake_for_messages`, which the payload's `settings` reports; it needs no data file. In the world
layer (the phone down) the client draws the **companion card** from the payload's `scene` section (name, stage
words and closeness words, portrait: words only, never a number) while a scene is open, and the **household
card** from `world.household` (who lives with the player and where they are, in words) otherwise. Every phone
action's answer carries the world's legal choices (`away.world_choices`), so the world is never dead after the
phone is used. Both are the engine's; a story authors none of it.

#### `plans.yaml` — plans with no set time

Read by `engine/social/plans.py` (v0.23.0 T12); `plans.check_data` checks it
whole at load and in `validate_content.py`. A plan is engine state,
`state.social["plans"]["pl<n>"]` (`{id, pid, kind, venue, when, made_at,
patience_hours, by: player|person, status: open|met|lapsed|cancelled|
stood_up, episodes_at}`, and on a `now` / `tonight` plan `due_at`,
`arrives_at` and `arrived`, v0.23.0 T23C), written only by the `social_plan`
effect. It has a
time of day in WORDS (`when`: `now`, `tonight` or `soon`), a place and a
person, and no slot or date; the payload (`plans`) carries words, never when
it was made. It is made by the player's `ask {what: meet, kind?, venue?,
when}` (a request their read answers: the `meet` commitment in growth.yaml
`willing:` and their time -- `now` needs them available with
`now_min_hours` free, `tonight` their evening, `soon` willingness alone --
and the engine picks the venue by kind and shared hobbies when none is
named), by their own ask (the `ask_meet` proposal, or `invite`, a morning
chance by disclosure depth for the evening) which the player answers, and
by a scene's closer (`scenes.yaml`, below: `call_it_a_night:plan:soon`, and
the `now` plan of `back_to_yours`, `back_to_theirs` and `go_somewhere_else`,
made in person with no time to find and no flake). Arriving on a kept plan
opens its scene.

**The person really travels** (v0.23.0 addendum 4, T23C). A `now` plan is
due when made, a `tonight` one at the start of their evening; the person
gets there at `arrives_at`: the venue's `travel_minutes` (their home's, in
`homes.yaml`, for `your_place`; none for `their_place`, where they are
home) plus a lateness from `arrival.late_minutes`, one counterless draw keyed
on the plan id. The `plan_arrive` event at that minute only records it
(`arrived`) and, when the player is somewhere else, queues their message
(`texter.md`'s `arrived`). The scene opens where the clock has stopped: on
`go`, on putting the phone down, at the end of an activity (an
interruptible one stops at their arrival: "Kai arrives."), after "Wait for
{name}" (the world verb `scene`'s `plan:<id>` target, offered while their
plan's place is where the player is and they are not there yet; it waits
up to `arrival.wait_cap_hours`), when another scene ends with the player
staying, and after a world turn. A `your_place` plan counts any of the
flat's places and meets in the lounge. A plan made in person (a closer)
arrives with the player: no lateness, no event, no text. Patience runs from
`arrives_at`. Keys:

- `kinds` -- exactly `coffee, drinks, dinner, walk, visit, film, climbing,
  games, gig, their_place, your_place` (a venue's `kind` in `venues.yaml` is
  one of the first nine; the last two meet at a home and name no venue).
- `patience_hours` -- `{now, tonight}`: how long a plan waits once made.
  Arrive (`go`) inside it and it is kept; after it, the plan is `stood_up` at
  `stood_up` (exact regard moves) and they say so (`texter.md`'s `stood_up`).
  A "running late" message within patience (`running_late`: phrases, not negated: "not running late" does not count) extends it
  once by `late_grace_hours`.
- `now_min_hours`, `late_grace_hours`, `lapse_after_hours` (a plan nobody went
  to closes quietly that long after its patience), `soon_patience_episodes`
  (a `soon` plan lapses after that many of the person's closed conversations,
  never days) and `closed_kept` (closed plans kept a person).
- `flake.stage_prob` -- `{<stage>: chance, default: chance}`, joined with the
  archetype's `flake_prob`; one draw when a `now` or `tonight` plan is made
  (SOCIAL_SCENE), shown a minute later as their message (`texter.md`'s
  `flake`) with the plan cancelled.
- `invite` -- `{prob: [by depth 0..], window}`: their own evening invitation
  (`texter.md`'s `invite`), at most one a morning, never mid-conversation, with
  a plan open or an ask waiting, or before the `meet` commitment holds.
- `arrival` (optional, v0.23.0 T23C) -- `{late_minutes: [low, high],
  wait_cap_hours}`: the lateness drawn once per plan on top of the travel
  (default `[0, 20]`), and the longest "Wait for {name}" waits at once
  (default 2).

Every number is a first value (rule 10). Every key is required once the file has
any, and `kinds` must be the engine's list.

#### `scenes.yaml` — meet-ups played in person

Read by `engine/social/scene.py` (v0.23.0 T13); `scene.check_data` checks it
whole at load (passed the `population.yaml` trait ids) and in
`validate_content.py`. A scene opens when the player arrives on a kept plan
(`plans.arrive`), and owns the narrated turn: the verbs are `scene {move,
topic?}`, `close {closer[:arg]}` and, at the flat, `do` for a shared
activity; `go` only through a closer. It is engine state,
`state.social["scene"]` (one at a time), written only by the `social_scene`
effect, and a conversation episode of kind `scene` runs beside it (it never
lapses; it closes at the scene's end and is recapped like any other). Each
scene turn's narration is written to the run's archive as a `scene` row,
never to state or memory. Keys:

- `prior` -- `{base, terms: {chemistry, warmth, mood: {<mood>: term}},
  spread}`: v0.22's meet quality, moved. Drawn once when the scene opens:
  base, plus chemistry x their chemistry (0-1), warmth x their warmth / 100,
  their mood's term, and a centred SOCIAL_SCENE draw of `spread`. It biases
  every moment, and x100 is their starting energy.
- `moment` -- `{spread, bands: {lands, fine, flat}, topic_fit: {theirs,
  shared}, energy_cost: {lands, fine, flat, misstep}}`: a move's score is the
  prior, the move's fit, the topic's fit (`theirs`: asking about a topic of
  theirs at their own rung; `shared`: telling them about a hobby you share),
  their mood's term and a centred draw of `spread`, banded by the least scores
  (below `flat`, a misstep). Each band spends their energy.
- `moves` -- exactly `ask_about, tell_about, playful, quiet, phone, talk`, in
  that order. Offered are three of their topics, two of yours, then `playful`,
  `quiet` and `talk` (v0.23.0 addendum 4 W7): `phone` is never offered, its
  row scoring the phone picked up in company; `talk` is what a line the
  player TYPES in a scene becomes when it names no topic (a typed line that
  names one of their topics, or a hobby, a running event or "my job" of
  yours, becomes that `ask_about`/`tell_about` move; see `typed:` below). **A move row is exactly `label`, `minutes`, `fit` and `bands`**: no
  floor, no stage, no refusal (`check_data` refuses any other key). `label`
  may name `{topic}`; `fit` is `{traits: {<population.yaml trait id>: term},
  archetypes: {<archetype>: term}}` (a `fit.traits` key that is not a
  `population.yaml` trait fails to load); `bands` gives each of `lands, fine,
  flat, misstep` the exact `warmth`/`trust` it moves (whole numbers). Asking
  about a topic above their rung is answered by them steering elsewhere: the
  band is `too_deep_band` and growth.yaml's `loss.too_deep` is paid -- a
  scored outcome, never a refusal. Checking the phone with someone who finds
  it rude (their `in_company` habit) is a misstep.
- `closers` -- the closers offered, from `another_round, go_somewhere_else,
  walk_them_home, back_to_yours, back_to_theirs, stay_the_night,
  call_it_a_night, propose` (`call_it_a_night` is required: the way home has no gate;
  `propose` is v0.23.0 T18's, below with `wedding`).
  `call_it_a_night` may add `:promise:morning` (a promise of the player's),
  `:plan:soon` (a plan) or `:stay` (stay where you are; otherwise home, the
  travel charged). `back_to_yours` and `back_to_theirs` are offered only when
  growth.yaml's `come_over` / `go_to_theirs` holds; `stay_the_night` is
  offered at a home (theirs, or the flat) when `stay` allows it (below). A closer's promise or plan is the only commitment a scene
  makes, and is recorded for the fact checks.
- `close` -- `energy_out` and `misstep_run` (they close when their energy is
  spent or after that many missteps in a row; their schedule's next boundary,
  under conversation.yaml `talk.boundary_minutes`, closes it too),
  `another_round_minutes`, `another_round_energy` (a share of 100 given back),
  `walk_extra_minutes`.
- `end_bands` -- `{great, good, fine, awkward}`: the moments' average score
  bands the evening (below `awkward`, bad). A `great` or `good` one counts
  toward the branch from `meeting` (`meets_good`); `fine` or better swaps
  numbers if none were; a first scene moves `numbers` to `meeting`; their
  `post_meet` text follows (relationships.yaml `meets.post_meet`).
- `too_deep_band` -- a moment band.
- `shared_activities` -- `{<location id>: [activities.yaml ids]}`: what the
  two of you can do together at the flat.
- `stay` -- staying over (§10.5), logistics only. `stay_the_night` is offered
  when growth.yaml's `stay_over` holds, the evening so far bands `fine` or
  better, their energy is above `energy_min` and no work start is within
  `early_start_hours`. `accept` is the chance they say yes, keyed by
  archetype alone (`default` otherwise): there is no intent term. A yes ends
  the scene, takes the clock to the player's morning and writes a "Stayed
  over" history row; a no is a plain answer whose reason is only their
  energy or the home's `homes.yaml` `stay_reasons`. The morning scene is
  v0.24.0's.
- `wedding` -- `{moments, moves}` (§12.2, T18): the wedding is a scene at
  the registry office, opened by arriving on its plan (a `wedding` plan, the
  engine's own: it stands in no other plan's way and never lapses) while
  the two are engaged. Only `moves` are offered, no closer, every moment's
  band is floored at `fine` (it cannot go badly), and it ends after
  `moments` moments: the couple is `married`. The closer `propose` (in the
  `closers` list) is offered while growth.yaml's `willing.propose` holds;
  they say yes, the stage is `engaged`, and the evening goes on. At home,
  with a household partner whose schedule says `free` while the player is
  in the flat, the `scene` world verb offers "Spend time with ..." with no
  plan and no travel (`kind: at_home`: `call_it_a_night` staying in,
  `another_round` and `propose` only), and the narrator is handed the
  partner's companion block whenever they are home and free. With no scene
  open, that prose is held only to the profile, other people and the stage
  (`agreement.HOME_PROSE_CHECKS`): "see you tonight" at home names no plan.
  The partner who lives with the player gets no `their_place` plan, and an
  unmatch, a block, an end, a fade or an expiry moves them out (a `wedding`
  plan not yet kept is called off with it).
- `chance` (optional; v0.23.0 addendum 4 W9) -- `{prob: {<status>: share},
  block_hours, max_here, max_candidates, prior_bias}`: chance meetings with
  people the player already knows. Only while the player is at a VENUE (never
  the flat, the building, the street, a home or the registry office, and not
  at work), a live contact may be there by their schedule
  (`engine/social/presence.py::chance_here`). Per person and block of
  `block_hours`, ONE counterless draw (`stable_rng`, keyed on the person, the
  day and the block: it moves no counter, so no other system's draws shift)
  says whether they are out -- under `prob` of their schedule's status now
  (`out`, `free`; `work` and `asleep` never count) -- and which ONE venue that
  fits their hobbies (`places.fitting_venues`, `pick_venue`'s overlap) they
  are at. The candidates are the player's live contacts, never the
  population: at most `max_candidates`, the most recently in contact first,
  less the blocked or unmatched, the ghosting, anyone away on a life event,
  the household partner, anyone with an open `now`/`tonight` plan (they are
  on their way, W4) and the scene's person; at most `max_here` at one venue
  (by pid). They are named to the narrator as "Also here: Sam (just
  matched)." (seen, not voiced, until approached), listed on the world's
  plate by name (`world.here`, with the background people on shift), and
  their texts are held while they are there, approached or not (W5). The
  `scene` world verb offers "Go over to {name}" (`approach:<pid>`), which
  opens a scene of kind `chance` with no plan (an open `soon` plan with them
  is recorded `met`); its prior takes `prior_bias`. **Its end is gated** (C3):
  `fine` or better swaps numbers only while growth.yaml's `willing.number`
  holds then, and `numbers` moves to `meeting` only while `willing.meet`
  holds; `meets_good` counts only from `meeting`; the run-in goes on their
  card ("Ran into each other at The Anchor: ..."); no `post_meet` text
  follows (`texter.md` has no chance row); and they stay "Also here" but
  are not offered "Go over to" again for the rest of that block. When their block moves them on, their held
  texts land at the next phone action or world turn. The closers that make a
  plan (`back_to_yours`, `back_to_theirs`, `go_somewhere_else` and
  `call_it_a_night:plan:soon`) are offered only while `willing.meet` holds.
  Absent, nobody is anywhere by chance. Every value is a first value,
  unmeasured until T29.

Everything here is conversation, an activity, a mood or something shared
about yourself. What two adults do on an evening is the narration's, in the
storyteller prompt's register: no move, band or closer describes it, and
`back_to_yours` or staying over is where the evening goes, nothing more
(rule 12).

**The narration of a scene (v0.23.0 T15, spec §10.6).** While a scene is
open the narrator is handed the companion block: who they are now
(`growth.who_now`), where you are, their story with you, the last three
recaps, what is open and how you left it, and this moment in the engine's
words, trimmed to `social.world.companion_tokens` (1200, config). Its prose is
then held to the same fact checks as their texts (`agreement.check_scene_prose`,
relationships.yaml's phrase lists): their age, job and neighbourhood, a name
they cannot know, a stage not reached, and a promise, plan or step no closer
made. The checks read narration as narration: the companion's own words (a
quote attributed to them, or a statement that starts with their name or
pronoun) and the player's ("you") count; someone else's ("her brother says
...", another contact's name) does not. A promise the narration states is
only checked, never adopted: the storyteller is not their voice on the phone.
A first miss is rewritten once; a second, or no model at all, shows the
moment's engine words instead (`scene.receipt_lines`). The phrases an author
adds to relationships.yaml's `claims`, `meet_claims` and `negations` are
read by these checks too.

```yaml
moves:
  quiet: {label: "Let a silence sit", minutes: 15, fit: {traits: {laid_back: 0.06}},
          bands: {lands: {trust: 3}, fine: {trust: 1}, flat: {}, misstep: {warmth: -1}}}
end_bands: {great: 0.72, good: 0.56, fine: 0.42, awkward: 0.3}
```

#### `growth.yaml`, `topics.yaml`, `layers.yaml` — who people become with you

Read by `engine/social/growth.py` (v0.23.0). Each person keeps a growth
record (`people[pid]["growth"]`): a disclosure **depth** 0-4, an
**openness** meter 0-100, their fixed **pace**, a `guarded` count, and the
layers revealed. Depth is self-disclosure and topics only: what a person
will talk about and share. Nothing else is on a rung.

**The closed vocabulary is the engine's, not yours.** The five rungs and
the disclosure kinds each may hold are fixed in code (`growth.RUNGS`;
`growth.KINDS` is their union):

| Depth | Rung | Kinds |
|---|---|---|
| 0 | `small_talk` | `places`, `hobbies`, `work_outline`, `the_apps` |
| 1 | `everyday` | `daily_life`, `work`, `friends`, `plans`, `opinions` |
| 2 | `personal_stories` | `upbringing`, `family_outline`, `past`, `travel`, `proud_of` |
| 3 | `hopes_and_fears` | `hopes`, `worries`, `regrets`, `values` |
| 4 | `family_and_future` | `family`, `future_plans`, `home_life`, `money` |

`growth.check_data` (run when the data loads, and by `validate_content.py`)
refuses: a `kinds:` list that is not exactly `growth.KINDS`; `depths:` that
do not list the five rungs in order; a rung listing a kind outside its own
set; a `topics:` or `layers:` row whose `kind` is not in the vocabulary;
a repeated topic or layer id; **any key outside each row's schema** (a
rung's `id, kinds, floors, counts`; `floors`' `warmth, trust`; `counts`'
`episodes, scenes`, whole numbers -- no floor or count reads in-game days;
a topic's `id, kind, label, when, follows_up`; a layer's `id, kind, text,
when`; a `when`'s `job, job_shape, flag, hobby, life`, each an id or a
list of ids); a top-level key outside `growth.TOP_KEYS`; a `trait_mult`
key that is not a `population.yaml` trait id; a `willing:` id outside
`growth.COMMITMENTS`, or a key outside its closed set; `depth` on any
`willing:` row but `number` and `meet`; `days_since_exclusive` on any row
but `move_in`; a `willing:` stage that is not one; and a value of the wrong type or range: every floor, gain, loss,
`mode_mult` and `jitter` a number 0 or more, every `trait_mult` above 0,
`guarded_episodes`, `topics_per_kind` and `life_lines` whole numbers 0 or
more, `gain:` keys only `growth.GAIN_EVENTS` and `mode_mult`, `loss:` keys
only `growth.LOSS_EVENTS`, `mode_mult` keys only the episode modes.

| `growth.yaml` key | Shape |
|---|---|
| `kinds` | the vocabulary, mirrored |
| `depths` | five `{id, kinds, floors: {warmth, trust}, counts: {episodes, scenes}}` rows: with openness at 100, the NEXT rung's floors and counts must hold to step up into it |
| `pace` | `{jitter}`: a person's pace is the archetype's `growth.pace` x each of their traits' `trait_mult` x `exp(jitter x N(0,1))`, drawn once |
| `trait_mult` | population trait id -> pace multiplier (READ RECEIPTS: `private`, `shy` 0.7; `warm`, `confident` 1.3) |
| `gain` | openness per engine-measured event: `exchange` (x pace x `mode_mult[mode]`), `good_end` (x pace), `moment[band]` (x pace), `promise_kept`, `support` (flat) |
| `loss` | openness lost: `broken_promise`, `left_on_read`, `fight`, `too_deep` (x the archetype's `decay_mult`) |
| `guarded_episodes` | how many episodes a betrayal's `guarded` +1 halves every gain for |
| `topics_per_kind` | topics drawn per kind per person |
| `life_lines` | "Since you met" lines the voice is given at most |
| `closer_soon_at` | openness at which the client hints "Getting closer" (the payload's `hints`, a boolean, never the number); 70 shipped |
| `willing` | commitment -> gate: what each person is willing to do NOW (below) |

**Willingness** (`growth.willing(state, pid, commitment) -> (ok, why)`,
v0.23.0 T5, spec §6.5). The commitments are a closed engine enum,
`growth.COMMITMENTS`: `number`, `meet`, `come_over`, `go_to_theirs`,
`stay_over`, `exclusive`, `meet_family`, `move_in`, `propose`,
`stay_or_go`. A row's gate may read only: `stage_min` (a stage rank at
least) or `stages` (one of), `warmth`/`trust` floors, `episodes`/`scenes`
play counts, `needs` (`{both: <intent>}`), `depth` (`number` and `meet`
only: swapping numbers or meeting follows from talking about one's day),
`days_since_exclusive` (`move_in` only, R15: since the stage
`exclusive` began, `people[pid]["exclusive_since"]`) and `no_household`.
Why not: `not_yet` (a floor, count, depth or the days), `stage`, `needs`,
`household`. No life-logistics commitment may read depth (rule 12). A
commitment the story leaves out is a `ValueError` when the engine asks.
Read since T5: `number` (the `numbers` stage gate, `{willing: number}`, and
the payload's `hints`) and `exclusive` (`{willing: exclusive}`); the rest
are read by the task that brings their mechanic (docs/GOVERNANCE.md NOT
WIRED). Reaching `everyday` queues the person's **number offer**: an
`offer_number` event at once in an open conversation, else at their next
available minute; it draws the archetype's `offer_number_prob` and, on
yes, makes a request of theirs (answered through `answer`, as their
`offer_number` proposal's is) and an `offer_number` message.

```yaml
willing:
  number:   {depth: 1, warmth: 25}
  exclusive: {stages: [dating], warmth: 70, trust: 65, scenes: 4, needs: {both: long_term}}
  move_in:  {stage_min: exclusive, days_since_exclusive: 14, scenes: 12, warmth: 78, trust: 72, no_household: true}
```

Openness is never written by the model: the engine's mechanics call
`growth.gain` and `growth.loss` with the event they measured (an event
outside `GAIN_EVENTS` or `LOSS_EVENTS` is a `ValueError`). A full meter
steps one rung when the next rung's floors, its counts and the
archetype's cap all hold; openness returns to 0, a history row is written
and the rung's next **layer** is queued as a reveal. Depth never goes
down. The conversation calls them (`engine/social/convo.py`, v0.23.0 T3):
every reply decided is an `exchange` (by its mode; a burst answered once is
one), an episode that closes after a sign-off with warmth risen across it is
a `good_end`, every closed episode ticks `guarded` down, and the first
charge of a spell left on read (`relationships.settle_left_on_read`) is a
`left_on_read` loss. Promises (T4), scenes (T13) and life events (T17) call
the rest: `moment`, `promise_kept` and `support` (a reply of yours or a scene with them while a hard event of
theirs runs, once per event, `life.support`) all gain now, and `growth._STUBBED` is empty. A queued reveal is voiced from T7 (situation
`opens_up`): until then `reveal_due` waits.

`topics.yaml`: `{id, kind, label, when?, follows_up?}` rows. Each person
draws `topics_per_kind` per kind, once (a counterless key), among the rows
whose `when` holds for them: keep at least one row with no `when` in every
kind. `follows_up` is accepted and read by nothing yet. `layers.yaml`:
`{id, kind, text, when?}` rows, each one plain fact in the third person;
on a step up, a layer is drawn (a counterless key per rung) among the
rows of that rung's kinds whose `when` holds and which they have not
revealed. A `when`'s `life` names their life events (v0.23.0 T17,
`life_events.yaml` ids, running or past).

```yaml
# topics.yaml
topics:
  - {id: t_shifts, kind: work, label: their shifts, when: {job_shape: [shifts]}}
  - {id: t_sister, kind: family_outline, label: their sister}
# layers.yaml
layers:
  - {id: l_dad_fisherman, kind: family_outline, text: Their dad was a fisherman out of the Quays}
```

`growth.who_now(state, pid)` is the who-they-are-now block: name, age,
job and neighbourhood, hobbies, traits, the texting style (at depth 2 or
more a `short` style reads `medium` in a chatting or deep episode), the
dating bio and prompt answers at depth 0 only, "Since you met", "What you
talk about with them now" (their topics up to their depth) and "What you
still keep to yourself" (the next rung's). The voice does not read it yet
(v0.23.0 T7); its home line (T10) and "Since you met" (T17, `life.since_lines`) are filled.

#### `life_events.yaml` — what happens to people, and to the player

Read by `engine/social/life.py` (v0.23.0 T17, spec §11); checked at load and by
`validate_content` (`life.check_data`: an unknown key, a bad id, number, mood, stage or
`when` is a load error naming the key). Life events are the world's calendar, so odds and
cooldowns are in DAYS (R15). They are ordinary life -- a boiler, a parcel, a holiday, a job
offer, illness, family news (rule 12) -- and each row's `text` (or a public row's `canon`) is a plain fact. Keys:
`kept: {past: n}` (the past events a person and the player keep in a save beside the running
ones and those on cooldown), `player` (12 rows, drawn once a day from `world_rng(SOCIAL_LIFE)`),
`person` (15 rows, one daily draw per eligible row per live person, each on their own SOCIAL_LIFE
counter) and `seen` (§12.4, T18: `prob`, one `world_rng(SOCIAL_LIFE)` draw at the end of every scene
with someone ELSE while the player has a partner at `exclusive` or later; on a discovery each such
partner's trust moves by `trust` (0 or less), their `guarded` count rises by one, their mood is `hurt`
for `mood_days`, and their history says "They found out" -- a fact, someone saw; the `cold:` rule is
the repair). A row: `id`, `when` (`stage_min` or `stages`; a person's
only), `prob_per_week`, `cooldown_days`, `text`, `lasts_days`, `news`, `mood: {value, days}`,
`followup: {about, when}`, `unavailable` (a holiday: they do not answer; needs `lasts_days`),
`support` (a reply of yours or a scene with them while it runs gains `support` once; needs
`lasts_days`), `blocked_by_open_promise`, `proposal: stay_or_go` (a job offer: they ask, you answer
"ask them to stay" or "tell them to go", and `growth.yaml` `willing.stay_or_go` decides),
`job: draw` (a new job, a counterless draw; `who_now` reads it), `home: redraw` (a new home; never drawn for
the partner who lives in the player's flat, T18) and `plan: wedding`
(T18: the wedding's row, `when: {stages: [engaged]}`, eligible only once relationships.yaml
`wedding_after_days` have passed since `engaged_since` and no wedding plan is open; it queues the
registry office plan, `plans.make_wedding`; READ RECEIPTS draws it at odds 1 a day, `prob_per_week: 7`). A player
row also has `label` (its `tell_about` topic: "your boiler"), `sign_off` (the reason the engine
gives when YOU end a chat while it runs), `flag` (`life_<id>` held while it runs), `scene` (the deck
dealt for it), `schedule` (`work_extra_hours` or `lift_extra_minutes`) and `effects`.

**The player's decks.** A world moment is an ordinary deck (§3.3) whose `when:` reads the event's
flag and the room: `data/scenes/boiler.yaml` (`life_boiler`, `apt_kitchen`) and `parcel.yaml`
(`life_parcel`, `bldg_reception`). Make it `repeatable: true` (the event comes round again) and let each
beat's `gate.on_pass.effects` clear the flag (`{type: flag, flag: life_boiler, value: false}`); the
event clears it itself when its days are out. A deck waits while a scene is open (the director deals
nothing over one). A deck schedules on its own `when:`, not a card's. Telling people: the player's
news is offered as a `tell_about` topic and a sign-off reason, and a person hears it only if the player
says it (`memory.add_knows` after the move). No row means anything beyond the fact it states.

#### `apps.yaml` — the phone

Read by `population.py` (pools, cultures), `apps.py` (the apps, decks and
limits), `matching.py` and `messaging.py`. An app is an engine surface: the
phone's catalogue offers its verbs from this table and the state, and
refuses anything it does not allow.

Keys marked **required** are refused when missing (`validation._check_apps`);
`capabilities` and `cost_minutes` are not, but an app that carries messages
or spends time needs them, and every value given is checked.

| Key | For | Meaning |
|---|---|---|
| `kind` | every app, **required** | `dating \| messenger \| games \| gallery \| calendar \| contacts \| settings` |
| `label` | every app | what the phone calls it |
| `capabilities` | threads; unset is none, so a thread on the app carries nothing | what a thread may carry: `text`, `photo`, `voice`, `video` (each checked) |
| `cost_minutes` | every app; unset is none, so its verbs cost no time | in-game minutes per verb: `swipe`, `like`, `edit`, `move` (each checked, 0 or more). A message's cost is `conversation.yaml`'s `costs:`, the same on every app (v0.23.0); a `text`, `photo`, `voice` or `video` row here is an error |
| `unlock` | messenger, games | the live stage that opens the app with a person |
| `receipts`, `typing` | threads | whether read receipts show, and typing dots (`typing`, true when unset: Texts says `false`, as SMS shows none) |
| `pool` | dating | `{from, size}`: a range of person indices, disjoint across apps; `overlap_with` + `overlap` add a band after every pool whose people are on both |
| `deck` | dating, **required** | `swipe` (one card: like, pass, super) or `browse` (a full profile: like a photo or a prompt) |
| `likes_per_day` | dating, **required** | a whole number above 0, reset each morning |
| `super_likes_per_day` | dating | reset each morning; 0 when unset |
| `likes_you_per_day`, `likes_you_visible`, `comment_on_like` | dating | people who like the player first, and whether "Likes you" shows them |
| `first_message` | dating, **required** | `either` (they may write first, `opener_prob`) or `player` |
| `match_expiry_days` | dating, **required** | a match nobody writes in expires (whole days above 0) |
| `culture` | dating, **required** | `archetype_weights`, `intent_weights` (`long_term`, `short_term`, `friendship`, `unsure`), `selectivity_mult` |
| `offers` | games | the games it holds (`wordgame`, `this_or_that`) |

The `matching:` block is compatibility and like-back: `weights` over
`looking_for`, `hobbies`, `personality`, `preferences` and `distance`
(summing to 1.0), `looking_for_table` (intent pairs, 0-1), `dealbreaker_mult`,
`chemistry [low, high]`, `like_back_base` per dating app, `compat_offset`,
`completeness [low, high]`, `super_like_mult`, `see_like_hours {median,
spread, max?}`, `likes_you_hours [start, end]` within the day from 04:00,
and `discovery_distance` (each `creation.yaml` discovery distance to 0-4).
The like-back is drawn once per pair, so un-liking cannot re-roll it.

```yaml
apps:
  natter:
    kind: messenger
    label: Natter
    unlock: numbers
    capabilities: [text, photo, voice, video]
    receipts: true
    typing: true
```

**Adding an app.** A `messenger`, `gallery`, `calendar`, `contacts`,
`settings` or `games` app is data: give it an id, a `kind` and its keys,
and the client draws it by kind (`ui/src/stories/read-receipts/PlayScreen.jsx`);
a messenger with `unlock: numbers` opens with each person once they have
swapped numbers. A new DATING app needs a `pool` (disjoint from the
others), a `deck`, its limits and a `culture`, an `ages` row in
`population.yaml`, and a `like_back_base` entry (texter.md needs nothing:
the voice does not know which app it writes in). The engine runs it in
full -- deck, likes, matches, expiry, threads -- but the READ RECEIPTS
client draws its two dating apps by id (`matchstick`, `front_porch`), so a
third shows the "not yet" screen until the plugin draws it (a
docs/GOVERNANCE.md row).

#### `relationships.yaml` — where they stand with the player

Read by `engine/social/relationships.py`, `agreement.py`, `media.py` and
`scene.py`; required blocks: `stages`, `branch`, `claims`, `bands`,
`regard`, `interest`, `mood`, `asks`, `cold`, `fade_days`, `proposals`.

- `stages` lists exactly the engine's stages, in its order
  (`engine/social/kinds.py::STAGES`), each with `words` (all the player
  sees, never a number) and, if reached by a gate, `from`, `trigger`
  (`automatic`, `ask`, `meet`, `branch` or `event`), `gate` (`willing:
  <commitment>`, a `growth.yaml` `willing:` row that must hold, and
  minimums of `warmth`, `trust`, `exchanges`, `meets_good`) and `needs:
  {both: long_term}`. No gate reads days: `days` and `stage_days` refuse to
  load (v0.23.0 spec §1.4). READ RECEIPTS' `numbers` gate is `{willing:
  number}` and its `exclusive` gate `{willing: exclusive}`; an ask below
  its gate is answered no with `why` `not_yet` (or `stage`, `needs`,
  `household`), which the voice and the phone both say. A story re-tunes
  the gates and words; it cannot add a stage. A gate is read only for a
  stage reached `automatic`, by `ask` or by `branch`: a `meet` stage
  (`meeting`, moved by a scene's end) or an `event` one (`married`, moved by
  the wedding's end) carrying a gate refuses to load, since nothing would
  read it (v0.23.0 T18 removed v0.22's `meeting` gate, warmth 70 and trust
  70, for that reason). Since v0.23.0 the list holds the long term after
  `exclusive` (ranked 6-8, `kinds.STAGE_RANKS`; spec §12): `living_together`
  (from `exclusive`, `{willing: move_in}`), `engaged` (from `exclusive` or
  `living_together`, `{willing: propose}`; `engaged_since` is written) and
  `married` (from `engaged`, `trigger: event`). Moving in at `engaged` or
  `married` records the household (`state.social["household"]`, the
  partner's pid, written only by the `social_household` effect) and moves
  no stage; ending, fading or expiring moves the partner out. None of them
  is an ending: cooling off, ending, fading and the cold recovery apply to
  every one. Moving into THEIR home is not built (docs/GOVERNANCE.md).
- `branch` picks dating, friends or fling out of `meeting`: the first row
  whose `either` one side wants.
- `bands` are the closeness bands the player sees, each `{name, warmth,
  contact_days}`, lowest first.
- `regard` bounds the model: `start`, `per_reply` (a reply's warmth and
  trust move, clamped), `per_episode_gain` (gains only, per conversation
  episode -- a scene counts as one -- and again between episodes, reset as
  each closes: `convo.cap_key`, v0.23.0), `fight_warmth`,
  `reconcile_warmth` (a fight and a making-up are still a day's), and
  `fallback` -- what an engine-written fallback reply moves (+1/+1 shipped)
  and its own `per_episode` cap, so a run with no model server still
  progresses, more slowly than a working one.
- `interest`, `mood` (`values`, the enum a reply may set; `decay_hours`;
  `media_mult`), `asks` (`per_episode`: asks of one kind an episode, the
  next refused "Give it a while"; `repeat_mult`, `repeat_warmth`,
  `turned_down`), `cold` (`warmth_below` for `days` winds a live stage down;
  warming to `recover_above` for `recover_days` mornings goes back to the
  stage it left), `fade_days` (no contact for that long: faded; 21
  shipped) and `wedding_after_days` (R15: the wedding follows the
  engagement by days; 14 shipped, read from T18).
- **No gate or cap reads days** (`tests/test_social_no_days.py` walks
  `growth`, `relationships` and `media.yaml`): a key naming days, hours or
  a per-day cap fails unless it is one of the test's named exemptions,
  each with its reason (an absence measure such as `fade_days`, a decay or
  grace window such as `mood.decay_hours`, R15's two).
- **Proposals** are the only things a voiced reply may ask the engine for
  (spec §10.5): `offer_number`, `ask_exclusive`, `cool_off`, `offer_photo`,
  `offer_voice`, `offer_video`, `invite_game`, `ask_meet`, `promise`,
  `followups`, and (v0.23.0 T18) `move_in` and `propose`, each a request to
  the player (`{stage: live, gate: living_together}` and `{stage: live,
  gate: engaged}`: the `move_in` and `propose` willingness), answered yes
  through the household and the stage (`relationships.PROPOSALS`; `followups` is never offered in
  the list: it holds a reply's own follow-ups, `max` 1-2 of them, to its
  stage and gate, `relationships.apply_followups`). Each row is `{stage, gate}`: the stage it may
  be made at (`live`: any live stage) and the stage whose gate must hold.
  List a subset to offer fewer; an id the engine does not apply refuses to
  load. The engine re-checks every one at commit (the media offers also
  hold `media.yaml`'s budget and unlock; `invite_game` the games app's
  unlock and no game running; `ask_meet` numbers or past it, willing to meet
  (growth.yaml `willing.meet`) and no plan but a `soon` one; it has no `gate:`).
- The phrase lists the agreement checks MATCH (`engine/social/agreement.py`):
  `claims` (per stage), `media_claims`, `media_denials`, `agree_phrases`,
  `negations`, `ordinary_names`, `meet_claims` (just `any`: a plan has no day,
  v0.23.0 T12), `meet_denials` and `arrival_claims` (just `any`, v0.23.0
  T23C: "i'm here", "just got here"; a statement passes only while a `now` /
  `tonight` plan of theirs is open and they have got there, so nobody texts
  "I'm here" from the road; it is judged only while a plan with the player is
  open, and "I'm here for you", "my mum just got here" and a contact's
  name before the phrase are no claim). A whole phrase, case-folded, in a clause that
  is not a question. They test facts, never tone (rule 12): precision first.
  `claims` also holds two tables (v0.23.0): `claims.promise` (a promise
  window -- `lunch`, `after_work`, `tonight`, `morning`, `at_work` -- ->
  phrases promising to message in it; "promise claimed" fails a reply that
  names a window other than the promise the engine holds, one that does
  not resolve for them now, or any from someone whose archetype makes
  none; a window that resolves is kept as their promise) and
  `claims.commitment` (`number`, `meet`, `come_over`, `exclusive`,
  `move_in` or `propose` -> phrases stating or asking that step, in the
  second person; "commitment claimed" fails one whose growth.yaml
  `willing:` row does not hold and whose stage is not yet reached -- a
  question counts here, since asking is the step, but a phrase with a
  third-person subject in the three words before it does not).
- `meets:` is what is left of v0.22.0's meet-ups beside scenes
  (`engine/social/scene.py`, v0.23.0 T13; plans replaced the appointments in
  T12, and `scenes.yaml` holds the prior and the bands): `post_meet`
  (`pace_mult`, `none_after` scene bands, `none_from` archetypes),
  and `recap_lines` (the engine's words for each scene band). Any other key
  fails to load. It
  is **required** once the story ships a `venues.yaml`
  (`scene.meets_faults`).

```yaml
stages:
  numbers:
    words: Swapped numbers
    from: [talking]
    trigger: ask
    gate: {willing: number}
regard:
  start: {warmth: 20, trust: 15}
  per_reply: {warmth: [-4, 4], trust: [-2, 2]}
  per_episode_gain: {warmth: 6, trust: 4}
  fallback: {warmth: 1, trust: 1, per_episode: {warmth: 3, trust: 2}}
proposals:
  offer_number: {stage: talking, gate: numbers}
  cool_off: {stage: live, gate: null}
```

#### `media.yaml` — photos, voice notes, videos

Read by `engine/social/media.py`; every block of `media.BLOCKS` is required.
The engine decides every medium (rule 1) and the model only words the
message that carries it.

- `budget`: per kind (`photo`, `voice`, `video`) `{start, per_episode,
  cap, unlock_stage}`: `per_episode` is added as each conversation with
  them closes (v0.23.0), to at most `cap`; one send spends 1.
- `request`: the player's `ask {what: photo|voice|video}`, decided at their
  next read: `accept {base, trust_per_10, warmth_per_10}`, `later_share`,
  `mood_mult` (every mood a `relationships.yaml` mood value).
- `unsolicited`: `per_episode_at_stage` (a draw per kind as each
  conversation closes, at that stage or past it, one sent at most, due at
  their next available minute) and `offered_mult` (a model's `offer_*`
  proposal).
- `subjects`: what a photo or video of theirs shows: `{id, when, label,
  scene, requires_flag?}`; `when` a schedule status or statuses,
  `requires_flag` a `population.yaml` flag (never canon text).
- `player_subjects` (`{id, kinds, label, scene}`), `portrait {scene}`,
  `style` (appended to every image prompt), `voice {max_seconds}`.

Nothing here filters, rates or rewrites an image (rule 12). Whether a
medium is generated at all is the owner's machine setting
(`phone_media.provider`, `tts.enabled`; docs/MEDIA_SERVERS.md); off, each
is a procedural tile with its caption or transcript.

```yaml
budget:
  photo: {start: 0, per_episode: 0.15, cap: 2, unlock_stage: talking}
subjects:
  - {id: pet, when: free, requires_flag: has_pet, label: their pet, scene: "their pet curled up nearby"}
```

#### `venues.yaml` — where meet-ups happen

Read by `engine/social/places.py` (since v0.23.0 T13; `places.venue_faults`).
`kinds` maps a kind to `{label, at}` (the engine's own line: "Coffee" "at"
"The Copper Kettle"); `venues` holds twelve or more `{id, label,
neighbourhood, kind, hobbies, duration_hours}` rows (plus `travel_minutes`),
each neighbourhood and hobby a `population.yaml` id. A plan with no venue
named is given one by the hobbies the two share.

```yaml
kinds:
  coffee: {label: Coffee, at: at}
venues:
  - {id: copper_kettle, label: The Copper Kettle, neighbourhood: old_town, kind: coffee,
     hobbies: [coffee, reading, baking], duration_hours: 1.5}
```

#### `activities.yaml` and the world — a phone story's narrated turn

v0.23.0 (spec §8.2-§8.5). A phone story is played on two layers. The PHONE
is phone actions (no model, `engine/social/turn.py`); the WORLD is the
engine's ordinary narrated turn (`default_state.run_turn`: the storyteller,
`legal_intents`, the decks, the evaluator), with two world verbs of its own
(`engine/social/world.py`, offered only where `paths.social` is declared):

- **Phone up, phone down.** One saved flag, `phone_up`. Any phone action picks
  the phone up; the phone verb `put_down` ("Put the phone down") puts it
  down. While it is up a world choice is refused with "Put the phone down
  first." (HTTP 409 with `phone_up: true`; the socket's `turn_error` carries
  `phone_up` too). Notifications that land while it is down are the BUZZ: the
  narrator is told how many and whose names, never a word of them.
- **`do {activity}`**, from `activities.yaml`, found beside `paths.locations`
  (`data/world/activities.yaml`, not in the social directory). A row is
  `{id, label, at: [location ids], minutes | until, when?, interruptible,
  narrate, say?}`: exactly one of `minutes` and `until` (`morning`, `evening`,
  `work_end`); `when` holds only `flag` or `not_flag` (a story flag set or
  unset); `say` lists base-form verb-object phrases of two words or more
  that a typed line may name it by ("make breakfast", "do the dishes"; the
  `label` counts too); no other key. Checked at load (`world.check_activities`: a
  `ValueError` naming `activities.yaml`). An activity is offered where its
  `at` holds the player's location. An `interruptible` one stops at the
  first notification that may wake the player and offers "Carry on"; asleep,
  only a person's promise or a late-night person's message wakes them, and
  only with "wake me for messages" on. `until: morning` is the player's
  waking band at least `conversation.yaml` `clock.min_sleep_hours` ahead.
  "Carry on" resumes a cut-short activity to its original end; the next `do` or any `go` forgets it.
  Rule 6: list sleep in the bedroom with no `when`.
- **Work.** `go_to_work` (offered from `conversation.yaml` `clock.work_lead_hours`,
  2 hours, before the player's work band) sets `at_work` until the band ends; while at work the only world
  verbs are the two rows with `at: []`, `carry_on_working` and
  `leave_early` (which returns the player to `apt_hall`). The phone stays
  usable.
- **`go {to}`** reaches the places with no edges (the venues, the cast's
  homes and `registry_office`, tagged `sentinel` in `locations.yaml`): the
  open plans' destinations, then the venues ranked by the hobbies the
  player shares with each, at most eight. From anywhere outside the flat
  and building "Head home" (`apt_lounge`) comes first and always, with no
  gate. The travel is the row's `travel_minutes` (`venues.yaml`,
  `homes.yaml`); the `social_go` effect writes the place. The phone's Places
  app (the phone verb `go`, the payload's `places` section) lists every
  venue, with no cap; choosing one puts the phone down and goes.
- **The narrator** is the story's `prompts/storyteller.md`, with the
  `SocialWorld` directive (name it in `settings.governance.directives`,
  READ RECEIPTS: `[StorytellerMind, SocialWorld]`): where the player is and
  the buzz. Like THE LONG CON, there is no `agents.yaml`. The opening
  (`entry.opening.choices`) offers world choices; give one an intent the
  entry can honour (READ RECEIPTS: "Tidy up a bit", `do tidy_up`).

- **Typed lines** (v0.23.0 addendum 4 §3). The player may type into the
  world instead of picking. The route gives typed text no intent (rule 1);
  the engine reads it on the server, under the turn lock, against what it
  offers at that moment (`engine/social/typed.py`), first match wins: ONE
  offered `do` or room `travel` by the matcher below; in a scene, a topic
  move the line names, else `talk`; otherwise nothing (the line is narrated
  only, and no time passes). A typed line never runs a `go` (a venue, a
  home), a closer, a plan, a promise, an approach, a phone action or the
  work rows. The receipt carries `typed: true`, and the narrator is told
  "The player said this; the engine read it as: <label> (<band>)."
- **`typed:`**, a block beside `activities`, is the matcher's data, every
  list checked at load (an unknown key, a non-list or a `rooms` key that is
  no location is a load fault naming `activities.yaml`):
  - `modals`, `negations`, `shifts` -- a line holding any of these as whole
    words is never matched (a wish, a "maybe", a "don't", a "later");
  - `leads` -- one may start a clause before the phrase ("I", "I'll", "ok");
    `progressive_leads` ("I'm") also allow the `-ing` form;
  - `movement` -- the verbs a room move starts with (`go`, `head`, ...);
  - `rooms` -- `{<location id>: [nouns]}` for the flat and building places
    (beside each one's `locations.yaml` `name`).

  The matcher: a line ending in `?`, or holding a cue, is rejected; it
  splits into clauses on `, ; . !`, "and" and "then"; strips one lead; and
  a clause matches only if it STARTS with a phrase (an activity's `label` or
  `say`), its verb in the base form, `+s` only in an acted line
  (`*makes breakfast*`), `-ing` only acted or after a progressive lead -- or
  with a `movement` verb and a room's noun within three words. Exactly one
  target across the line, offered or not, or nothing.

```yaml
activities:
  - {id: tidy_up, label: "Tidy up", at: [apt_lounge, apt_kitchen], minutes: 30, interruptible: false, narrate: "You tidy.", say: ["tidy up", "do the dishes"]}
  - {id: sleep, label: "Sleep", at: [apt_bedroom], until: morning, interruptible: true, narrate: "You sleep.", say: ["go to sleep", "go to bed"]}
typed:
  modals: [would, could, should, maybe, "let's", "want to", if]
  negations: ["don't", not, never]
  shifts: [later, tomorrow, earlier]
  leads: [i, "i'll", ok]
  progressive_leads: ["i'm"]
  movement: [go, head, walk]
  rooms: {apt_kitchen: [kitchen], apt_hall: [hall, front door]}
```

#### `games.yaml` and `words.txt` — the two games

Read by `engine/social/games/`. `wordgame:` is Tile Talk: `label`, `size`
(11), `rack` (7), `premiums` (11 strings of 11 squares: `.` `l` `L` `w`
`W` and `*` at the centre), `letters` (`{count, value}` per letter) with
`blanks` (2) making a 72-tile bag, `bingo_bonus`, `node_budget` (the
person's search, a count of prefixes tried, never a time),
`top_k_by_skill`, `scoreless_turns`, `swap_bag_min`, `pace_mult`,
`banter_prob` and `effects` (`finished`, `crushing_margin`,
`<archetype>_crushing_warmth`). `words.txt` is the word list, one lower-case
word a line. `this_or_that:` is This or That: `label`, `pace_mult`, `lean`
(`hobby`, `trait`, `slider`, `sharpness`, `noise`), `effects`, `tags`
(`{hobbies, traits, sliders}`, every id a `population.yaml` one) and
`pairs` (60 or more `{a: {label, tags}, b: {label, tags}}`). A game is
started by the player's `game_invite` or a person's (their
`games.invite_prob_per_day`, or a reply's `invite_game` proposal); the
games themselves are engine code, so a story tunes these two and cannot add
a third.

#### `prompts/texter.md` — the voice

Read by `engine/social/voicing.py::parse_texter`, in three parts:

1. **The persona**, everything above `## Instructions`: the system message
   of every voicing call, sent as written. Say how this person texts and
   that a conversation that is going is a real conversation; the engine
   tells the model the mode (quick, chatting, deep) and the bubble count.
2. **The instruction table**: under `## Instructions`, one row per
   situation, exactly `` - `<id>`: <line> ``. The engine sends the row of the
   situation it decided (a reply, an opener, a decline, a photo sent ...)
   in the prompt's RIGHT NOW block, and beside it the rows for how the
   conversation ends (`winding`, `sign_off`), a follow-up to raise
   (`followup`) and a layer to open up about (`opens_up`). A row may name
   engine facts as `{field}`: `{reason}` (why the conversation ends),
   `{promise_when}` (a promise's window in words), `{promise_words}`,
   `{followup}`, `{topic}` and `{them}`; any other field refuses to load.
   Every situation the engine emits (`voicing.SITUATIONS` and
   `voicing.ENGINE_ROWS`: `opener`, `reply`, `double_text`,
   `answer_request`, `send_selfie`, `send_photo`, `send_voice`,
   `send_video`, `decline_photo`, `decline_voice`, `decline_video`,
   `game_banter`, `post_meet`, `offer_number`, `promised_message`,
   `window_message`, `opens_up`, `winding`, `sign_off`, `followup`) and
   every one `behaviours.yaml` names (an initiation's `instruction` or id,
   an arc beat's `instruction`) must have a row; the validator names a
   missing one (and should one slip past it, that message's voicing falls
   back to the story's line, logged at ERROR). Rows the engine does not
   emit yet are allowed: READ RECEIPTS keeps `news`, `stood_up` and `flake`
   for the tasks that emit them, and `ask_meet`, which a reply carries as a
   proposal. `good_morning`, `check_in`, `late_night` and `reveal_turn` are
   retired as rows; a message still due under one of them is voiced by
   `window_message` (or `opens_up`).
3. **The Fallbacks fence**: under `## Fallbacks`, one fenced `yaml` block.
   `reasons:` gives each `conversation.yaml` `reasons:` key in the
   person's own words ("I've got an early start"). `any:` holds every
   archetype's lines keyed `<situation>.<mode>` (`reply.quick`,
   `sign_off.chatting`); an archetype's own block takes `<situation>`,
   `<situation>.<mode>` or `decline`. When no model answers (or both
   attempts fail the agreement checks), the engine picks one line, seeded
   by the message: `decline` first for any answer that is no; for a reply,
   how the conversation ends (`sign_off.<mode>`, `winding.<mode>`) or the
   follow-up it raises; then the situation -- the archetype's
   `<situation>.<mode>`, its plain `<situation>` (read as quick lines),
   `any`'s `<situation>.<mode>` -- then `reply` the same way, then the
   engine's "hey". A line may name the same `{fields}`; a line whose fact
   is missing is skipped (`{promise_words}` may be empty). Every archetype
   in it must be a `behaviours.yaml` one, every key a table row (with a
   mode) or `decline`. A fallback reply moves `regard.fallback`, never
   more, and reveals nothing.

````markdown
## Instructions

- `reply`: Carry the conversation on. Answer what they said, all of it and not only the last line.
- `sign_off`: You need to go now: {reason}. Say goodbye your way, and say why.

## Fallbacks

```yaml
reasons:
  early: "I've got an early start"
any:
  reply.quick: ["ha, fair", "tell me more"]
  sign_off.chatting: ["Got to go — {reason}. {promise_words} This was nice."]
steady:
  reply: ["That sounds good.", "How did it go?"]
  decline: ["Not yet, but I'm glad you asked."]
```
````

**The prompt** (`voicing.messages`) is the persona, then eight blocks from
the most stable to the most volatile: WHO YOU ARE NOW (`growth.who_now`),
YOUR STORY TOGETHER (the story and recaps), WHAT YOU KNOW ABOUT THEM, STILL
OPEN (promises and follow-ups), YOU AND THEM (stage, closeness, what you
share, mood, the commitments that hold, what you have told them, history),
THIS CONVERSATION (how the last one ended, then this one), RIGHT NOW and
FORMAT. It is trimmed to the call's window (`social.voice.window_tokens`,
the binding's context, less the mode's reply cap; docs/MODEL_SERVERS.md §
The texter profile).

The model's answer is a JSON reply (`voicing.reply_schema`: the mode's
bubbles, facts learned and shared, a mood, warmth and trust within
`regard.per_reply`, at most two proposals from the list above, up to two
`followups` `{about, when}`, and -- only while the conversation is winding
or signing off with no promise made -- a `promise` whose window is one that
resolves for them), checked against what the engine holds before it lands
and again at commit. No line in any of these files may rate content (rule
12).

---

## 3.9 The studio — the same job, in a browser

```powershell
.\.venv\Scripts\python.exe launcher.py --game dev-story --studio --port 5610
# then open  http://localhost:5610/?studio=1
```

```sh
.venv/bin/python launcher.py --game dev-story --studio --port 5610
```

`dev-story` is the bench — rewrite it while the server is running. Any other
slug works; the studio lists every story under `games/`.
Everything below can be done from a terminal, and the studio is the same work
with the files in front of you: every story listed with its live validation
health, every editable file readable and writable, validate on demand, and
`New story` running the same scaffolder as `new_story.py`.

**The review queue is the part that has no terminal equivalent.** `author.py
--promote` is all-or-nothing and blind: it validates, then moves every draft
into the live tree at once. Validation catches what is *wrong* — see §4.1 —
but what survives it is a question of taste, and no validator will ever have
any. The queue shows each drafted entry with its full text. **Keep** promotes
that one file into the live tree (`POST /api/studio/draft/accept`, same
placement as `author.py --promote` for the kind). Edit in place writes the
draft where it sits. Throw away deletes it.

Two things it will not do, both deliberate:

- **It is opt-in.** `--studio` mounts the routes; without the flag they do not
  exist. The studio writes to `games/` on request, which is right for an
  authoring tool and wrong for a machine somebody is only playing on.
- **It cannot save what the engine cannot read.** YAML and JSON are parsed
  before anything touches disk, so a syntax error is a refusal rather than a
  broken story. Validation runs after and is *reported*, not enforced — a
  story mid-edit is allowed to be briefly wrong, but not silently.

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
discouraged. Inference rides the engine's own model backend -- whichever
server `llm.provider` names ([MODEL_SERVERS.md](MODEL_SERVERS.md)), which
always receives the draft's schema (as `format` on Ollama); `--repair` and
`--promote` never open a connection, so the review half of the loop works
offline. A story sets nothing provider-specific: which model server narrates
it is the owner's config, never the story's.

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

```sh
.venv/bin/python scripts/author.py --game my-story --draft item --brief brief.txt --count 3
.venv/bin/python scripts/author.py --game my-story --from-bible BIBLE.md
.venv/bin/python scripts/author.py --game my-story --repair
.venv/bin/python scripts/author.py --game my-story --promote
.venv/bin/python scripts/author.py --game my-story --promote item
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
Bureaucratic dread, played warm.
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

### 4.1 The four mistakes the model made, and where they are caught now

All four were found by drafting a test story from a bible and reading
the result. All four produced content that **loaded, validated and played** —
the reason to write them down is that none announced itself, and three of
them had been possible in the schema since the tool was written.

**A gate that cannot fail.** The model likes beats named `stealth_check`,
`nerve_check`, `perfect_grief` — and wrote them with an `on_fail` branch and
no `when` or `check`. `_resolve_gate` opens at `passed = True`
(`engine/content/deck.py`), so those beats always take `on_pass` and the
failure text is unreachable at every seed. A whole nine-day draft came back
that way and read like working content.

*Now:* the gate schema is three `anyOf` branches, and `on_fail` exists only
on the two that carry something able to fail, so the pairing is
ungrammatical rather than merely invalid. The validator reports it too, for
hand-written content — but **only** when an `on_fail` is present. A gate
with `on_pass` alone and no condition is a shipped idiom meaning "this beat
always happens, and here is what it costs" (205 beats in the Garden), and
flagging those would fail `--strict` on a convention the engine supports.

**An effect that is silently discarded.** After a repair pass the drafts came
back with `{type: value, item_id: favor, qty: 1}` — a value row wearing an
item row's fields. `_e_value` resolves its target from `name`/`value`/`id`,
finds none, and returns `_unknown`: the row is dropped without a word, by
design, so that foreign or old content cannot abort a turn. The result was
nine decks in which every beat had effects and no meter could move.

*Now:* `_effect_schema` is one branch per kind discriminated by a `const`
type, each requiring the fields its kind actually reads, with the `item`
branch offered only to stories that ship items. The validator reports the
mismatch as an error wherever it appears.

**A beat that gates and bands.** `_bind_beat` keeps the gate, discards the
band and logs it — at deck-load time, into a stream nobody reads while
authoring. Twelve beats across four decks carried both, so twelve authored
band texts and awards could not run at any seed.

*Now:* the beat schema is two branches, gate-beat or band-beat (a beat with
neither is still legal — plain narration is a real thing to write), and the
validator reports the pairing.

**A receipt where the prose goes.** Asked for a beat whose effect moves
`composure`, the model sometimes writes `text: composure +1` — putting the
delta in the slot the *player* reads. The effect beside it is correct, so
nothing breaks and nothing warns; the story simply says "composure +1" out
loud. In a story whose meters are declared `veiled`, that is the one thing
the visibility setting exists to prevent, and the narrator persona forbids it
in the same words. Four of eight beats in a drafted finale read this way.

*Now:* the validator reports a beat text that is **only** a declared value
and a signed number. The pattern is anchored and whole-string on purpose —
prose that happens to mention a meter is fine and common, and only a text
consisting of nothing else is unambiguously a receipt in the wrong slot.

The shared lesson is the one the turn grammar already encodes
(`engine/llm/schemas.py`): **constrain the sampler, do not correct it
afterwards.** A flat object with a `type` enum and every other key optional
will eventually be filled in with another kind's fields, and the engine's
tolerance for unknown rows is exactly what makes that invisible.

### 4.2 What no validator will catch: the model writes sequences, not choices

Across the nine day-decks drafted for that story, **none** of the 23 cards
came back tagged `menu` — the tag that makes the player pick which beat
resolves. All 23 are `sequence` cards, which play automatically. The only
menu card in that story is hand-authored.

This is not a defect any check can flag, because a deck of sequences is
legal, loads fine and reads well. It is a shape: the model writes consecutive
moments fluently and mutually-exclusive alternatives badly, and its sequence
beats are composed to *follow* one another. That means they cannot be
rescued by retagging — a sequence retagged `menu` offers the player several
halves of one paragraph.

If you want choices inside your days, **ask for them in the bible in those
words** ("each day should offer two or three mutually exclusive things the
player can do, not a run of moments"), check the tag census after drafting,
and expect to write the pivotal ones yourself. Card-level agency is the part
of a deck story the tool is currently worst at.

---

## 5. Verification

Four tools, in the order that finds problems cheapest.

### 5.1 The validator

```powershell
.\.venv\Scripts\python.exe scripts\validate_content.py --game my-story --strict
.\.venv\Scripts\python.exe scripts\validate_content.py --game all --strict
```

```sh
.venv/bin/python scripts/validate_content.py --game my-story --strict
.venv/bin/python scripts/validate_content.py --game all --strict
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

```sh
.venv/bin/python scripts/simulate.py --game my-deck-story --runs 200
.venv/bin/python scripts/simulate.py --policy all --turns 200
```

**Graph stories:** the five policies (`baker`, `cautious`, `hero`, `pauper`,
`reckless`) are **flagship-owned by design** — they walk Edgewood's location
ids and buy from Edgewood's vendors. A non-flagship graph story is refused
with its reason; there is no headless harness for your graph story yet, which
means your balance claims are unmeasured — say so in your README rather than
asserting them. What the harness is *for* — observing every number downstream
of a clock that actually ticks — is its module docstring, and AGENTS.md rule
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
**threads are sealed at `--thread-rate`** because in real play the player
seals them with the `bargain` verb, which the walker never chooses, so **a
clock that waits on a live thread reads low by construction** —
the Garden's `ashen_pressure` reporting 0.0 is the walker's blind spot, not
the story's bug; and **`--max-days`** lets a small deck (a fresh scaffold's
one file) loop until its meters travel far enough to open gated endings —
the template's two endings are both reachable at the default 30. Low run
counts under-report reachability; use `--runs 200` before believing a
"never" list.

**Phone stories** (`paths.social`, §3.15): `scripts/simulate_social.py
--game read-receipts` plays the phone headless through the same mechanics action
and voicing pass play uses, with a stub voice (never a model) and a seeded
player policy (`--policy attentive|swiper|picky|slow|neglectful|pushy|devoted|bachelor|flaky|chatty|all`,
`--voice neutral_model|romantic_model|cold_model|zero|no_model|all`), in
SESSIONS of 40 real minutes (`--sessions`): every action is priced in real
seconds (`REAL_SECONDS`: a send 30, a swipe 4, a bubble read 3, and the
model's `--model-seconds` -- 6, 15 or 30 -- a reply; a wait is free), and the
report is the v0.23.0 spec's §17.2 rows (`REPORT_ROWS`): conversations'
length and ends, cold messages unanswered, ghosting, the real minutes from a
match to a number, promises kept, fuller replies, the in-game minutes a real
minute buys (`DERIVED_ROWS`, never banded), and the days and real hours to
each closeness band per archetype. A row its sessions cannot reach (a scene,
a life event, the long-term stages; T9's sessions are phone only) is `None`.
Seed ranges run side by side (`--first-seed N --seeds 2 --raw OUT`) and
fold (`--fold OUT...`). READ RECEIPTS' README has the commands and where
its measured tables live. The harness is READ RECEIPTS' only (`--game`
accepts that slug alone: its policies use that story's app ids), so a new
phone story's numbers are unmeasured until it learns the story -- say so in
the story's README, as for a graph story above.

### 5.3 Doctor

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py
```

```sh
.venv/bin/python scripts/doctor.py
```

Environment, services, and a Games section that reports every discovered
story against the path vocabulary — "declares every content path it reads" is
the line yours should get.

### 5.4 The per-game tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_story_content_integrity.py -q   # every discovered story
.\.venv\Scripts\python.exe -m pytest tests\ -q                                  # everything
```

```sh
.venv/bin/python -m pytest tests/test_story_content_integrity.py -q
.venv/bin/python -m pytest tests/ -q
```

The per-story tests parametrise over discovery, so your story is swept the
moment it exists: content integrity, prompt identity
(`tests/test_prompts_story_neutral.py` — every discovered story must ship its
own `prompts/storyteller.md`, and the persona the model receives must be that
file; the engine's neutral fallback exists for runtime, not as a way to pass
this test),
the story surface. Run the full suite
before calling the story done; it is the same bar the shipped stories clear.

**Every ending, through its own door.** `tests/endings_driver.py` drives one
ending through the door a player uses: a quest's completion
(`Door.quest(quest_id)`), a card beat played in its dealt hand
(`Door.card(deck_id, card_id, beat_id)`, dealt as the director would and
never placed past the card's own `when:`), a set-piece won
(`Door.set_piece(piece_id, {"answer": ...})`) or a terminal death
(`Door.death()`). It then asserts the ending is locked and its epilogue card
shows. Register a row per ending in `tests/test_finales.py`'s
`ENDING_DOORS`, with a `setup(state)` that puts the run at the door through
`apply_effect`. List your story in `COMPLETE_DOORS` and the suite fails on
any declared ending with no door. The driver's docstring has the row shape.
Name the ending on every authored `ending_lock`. An id-less lock asks
`endings.resolve()`, and a door that can land on the fail-forward is a door
to the wrong ending.

---

## 6. The worked examples index

| Where | What it teaches |
|---|---|
| `games/dev-story/` | **The full worked example.** One small working instance of every subsystem — thirteen locations, eight scheduled NPCs, a two-agent pipeline, a clock that forces a scene, a thread with renegotiations (declared only: renegotiation is NOT WIRED, §3.4), three gated endings and their epilogues — each file annotated at a depth a template cannot afford. When a mechanism is unclear, it is running here with the lights on. |
| `games/wicked-garden/` | **The deck exemplar**, full scale. Its `data/scenes/README.md` is the deck grammar's reference treatment; its `data/canon/` established the dictionary shape; its manifest shows the "what this story deliberately does not ship" comment style. |
| `games/clockwork-dark/` | **The graph exemplar**, full scale. The travel graph, arcs, encounters, the livelihood economy, doom — 5,300 lines of the shape the engine's clock was tuned for. |
| `games/read-receipts/` | **The phone exemplar** (`paths.social`, §3.15): the flat, the building, the street and the city (28 locations: `travel`, and `do` and `go` in its narrated world turn), no plot, no ending (`endless: true`); a seeded population the engine runs, two dating apps, messaging on the engine's clock, relationships, media, meet-ups and two games, voiced by `prompts/texter.md`. Every data file's header documents its keys and the measured rows its numbers move. |
| `scripts/story_template/minimal/` | The smallest thing that validates and plays a turn. Start here unless you already know your shape. |
| `scripts/story_template/graph/` | The flagship's skeleton with Edgewood removed. |
| `scripts/story_template/deck/` | The Garden's skeleton, one working instance of each coupling. |

The relationship, and the maintenance rule that keeps it true: **the templates
are distilled from dev-story** — when a subsystem changes shape, fix dev-story
first (the suite runs its rows, so it cannot silently rot), then re-distil the
templates. A template that drifts from the bench teaches the old engine.

Version: v0.1.5 [2026-10-13]
