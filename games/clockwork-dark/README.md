# The Clockwork Dark

The flagship. You wake at the forest's edge beside Edgewood, the last
comfortable village before the Marches, and something patient and brass is
working its way outward from the Wound. Become a hero or become a baker: the
evil ticks either way, and the quiet life counts as a complete game.

```powershell
.\.venv\Scripts\python.exe launcher.py --game clockwork-dark
```

```sh
.venv/bin/python launcher.py --game clockwork-dark   # Linux
```

It is the engine's default story (`game.default` in `config/default.yaml`), so
a bare `launcher.py` plays it too. What changed, release by release:
[CHANGELOG.md](CHANGELOG.md). The design and the story bible are in
[docs/DESIGN.md](../../docs/DESIGN.md).

## The shape

A graph story, and the one every other graph story was measured against:

| What | Where |
|---|---|
| Twenty-two locations in rings out from the Wound, two of them secret since v0.25.0 (the works below the stump, known once the sealed seam's riddle is solved; the Join on the inward road, known once the road is measured); the five canon ids (`forest_clearing`, `edgewood_square`, `edgewood_bakery`, `tinker_caravan`, `millhaven_gate`) must not be renamed | `data/world/locations.yaml` |
| A village generated per seed: villagers, venues, the festival | `data/procgen_templates/edgewood.yaml` |
| The **evil clock**: `dormant`, `stirring`, `spreading`, `consuming`, advancing whatever you do; pushing back buys reprieve (`doom_resistance`) | `data/rules/doom_effects.yaml`, `state.yaml` |
| 26 quests in four arcs (`quiet_life`, `whisper`, `march`, `convergence`) that open on **awareness**, a hidden stat, so a baker who never listens stays a baker | `data/quests/` |
| Eight ending classes and their epilogue cards, each locked BY NAME at its own door since v0.25.0 (a deck card where its person is, or the terminal death); each has a one-line `tease` | `data/rules/endings.yaml`, `data/epilogues/`, `data/scenes/` |
| The critical path on cards since v0.25.0: every quest stage on an ending's path that waited on the narrator has a card that settles it, dealt where and when the stage can complete (seven repeatable decks: the bakehouse, Nessa's drawings, the naming, the village meeting, the levy table, the ninth pin, the inward road) | `data/scenes/` |
| **Sera's levy** (v0.25.0): a hidden clock that fills from the first militia press seen over fifteen days and then deals the press in the square (a boy's name on the list: speak for him, hide him, or let it be); and **Sergeant Venn's bargain**, a night on the wall at the gate for one Edgewood name off her list, struck in the morning while the conscription list is open | `data/rules/clocks.yaml`, `data/rules/threads.yaml`, `data/scenes/the_press.yaml` |
| Three archetypes: Wayfarer, Hearthkeeper, Tinker-apprentice | `data/rules/archetypes.yaml` |
| Survival (stamina, hunger, hp; rest is never gated) and death rules: you are carried back to the square, and only a second death while the world is `consuming` ends the run | `data/rules/survival.yaml`, `data/rules/death.yaml` |
| Trade with three vendors, paid work, foraging, boons and complications, collectable sets | `data/economy.yaml`, `data/tables/` |
| Crafting: 22 recipes (baking, herbalism, mending), offered by the `craft` verb only where one can be made | `data/recipes/` |
| Encounters played as scenes on every road since v0.25.0: the forest walk, the Millhaven road, arrivals in the square and at the gate, and five bands for the rest (the wood, the barrows, the toll road, the heartland road, the works); only doors carry no danger | `data/encounters/` |
| Set pieces in Edgewood | `data/challenges/edgewood.yaml` |
| World events and schedules, NPC schedules, factions, rumours | `data/world/` |
| The cast: five canon people (Maris, Odran, Ilya, Sera, Brindle) and three villagers a seed, plus four the lore named, declared with hourly routines since v0.25.0: Hallam the smith (the forge by day), Nessa Fallow (the square 09-16, the Fallow holding otherwise), old Wenna (the shrine at dawn and dusk, Well Row by day) and Edrin Fallow (his holding). The doom clock moves Ilya and Sera to the square, and Edrin and Nessa to the ditch camp at 0.88 | `data/world/npc_schedules.yaml`, `data/rules/doom_effects.yaml` |
| A lore corpus for RAG | `data/lore/` |

**Two agents** (`agents.yaml`, canon ids): `clockwork_storyteller` narrates,
and `clockwork_assistant` is the in-world companion whose trust you earn. It
takes one of five forms, never sees the raw evil clock, and is not a pipeline
participant (`pipeline: false`), so turns do not negotiate. Its hints are in
`data/assistant/hints.yaml`.

**Its own UI plugin** — `ui.plugin: clockwork-dark`
(`ui/src/stories/clockwork-dark/`), with six overlays: the pack (`i`), the
journal (`j`), the codex (`c`), the notice board (`n`), barter (`b`) and, since
v0.25.0, **The ways it ends** (`e`).
Since v0.25.0 the overlays that act (barter, the pack and its recipes, the
notice board) press engine intents, not typed words: each button is a pair
the server lists (`GET /api/intents/overlay`) and the engine runs before the
narrator speaks, one thing a press; a pair not on offer is drawn and not
pressable, and nothing is while a card or an encounter owns the turn.
Examine stays typed text (it moves nothing).
Since v0.25.0 the encounter draws an approach not offered this turn unlit and
binds keys 1-9 to the offered ones while the choice row is empty; the sheet
names each faction and its standing's word; **The ways it ends** (`e`) lists
the doors open now (title, tease, how close), never a locked one; who is here
is listed under the sheet; and the ending screen shows the ending's gallery
plate.

## The endings and their doors

Each ending is locked by name at one door (a choice the player reads), and
its Speak · Act · Seal and epilogue card follow on the same beat. A door deck
is dealt one card a visit, only where and when its person is there, and comes
round again on the next visit, so "not yet" is never the last chance.

| Ending | Its gate, in short | Where its door stands |
|---|---|---|
| The Hearth Holds | a place in Edgewood (one of six quiet-life quests done), the larder walked (`H0`), awareness 40 or less | the bakery 04-09, Maris there: `the_morning_firing` / `H1` / `stay` |
| The Dark Keeps Its Hours (the fail-forward) | none | the same card's `stay_anyway`, offered when the Hearth's gate is shut; and the terminal death (a second death while the world is `consuming`; `data/rules/death.yaml`'s `terminal.ending`), which shows its card |
| The Long Witness | awareness 30, listened (a whisper quest, or awareness 50), the Unnamed Saints at 30, day 27 | the shrine while old Wenna is there (06-07, 18-21): `the_count_kept` / `W1` / `give_it` |
| The Counted March | the march arc open, the militia at 20, a levy seen through (a march quest, or a night on the wall: Sergeant Venn's bargain kept) | the gate or the square while Sera is there: `the_muster_roll` / `M1` / `strike_it` |
| The Named Wound | named, decided, and the last quiet morning at its third stage | the bakery 04-09, Maris there: `the_morning_firing` / `Q1` / `tell_her` or `say_nothing` |
| The Price Asked | named, chose (a thing offered at `S1`), paid | wherever Ilya is while the sacrifice is open: `the_price` / `S2` / the beat for the thing offered, which takes exactly that thing |
| The Pin and the Join | the ninth pin taken and held, the join walked | at the Join: `the_join` / `J1` / `set_it`. The pin is taken on Ilya's felt (`the_ninth_pin` / `T3` / `take_it`, once the tinkers' standing is 10) |
| The Stopped Wheel | the doom reading at 1.0 | forced, not walked to: the declared event `the_last_hour` deals `the_stopped_wheel` / `Z1` once an open encounter or hand is done |

## Art

The largest shipped pack, in `content/scenes/clockwork/static/art/` (the
flagship's art root predates per-story art directories):
`data/art/manifest.yaml` maps all 22 locations, each with its own base
(eight with a night plate, twelve with a `corrupted` pool), five Assistant
forms, nine portraits (everyone scheduled but the cat), 81 items, eleven
enemies, an ending plate for each of the eight endings (`gallery:`), UI
plates and the dice. v0.25.0's 47 plates were generated on a local Forge Neo
with Qwen Image 2.1: `scripts/generate_art.py --game clockwork-dark
--story-plan --provider forge` plans them from `data/art/subjects.yaml`
(a location's `base: true`, `times:` and `phases: [consuming]`; `enemies:`;
`gallery:`), and `--promote` writes them in. Without `--story-plan` the
flagship keeps its legacy plan. `scripts/art_missing.py --game
clockwork-dark` lists what is still missing.

## Balance

`scripts/simulate.py` is this story's harness: five policies (`baker`,
`cautious`, `hero`, `pauper`, `reckless`), headless, no model.

```powershell
.\.venv\Scripts\python.exe scripts\simulate.py --policy all --turns 200 --seed 42
```

```sh
.venv/bin/python scripts/simulate.py --policy all --turns 200 --seed 42   # Linux
```

Since v0.25.0 `scripts/simulate_doors.py` (or `simulate.py --policy doors`)
measures the doors: one scripted policy per ending (`baker`, `settler`,
`witness`, `marcher`, `namer`, `payer`, `pinner`, `drifter`, `reckless`),
every dealt card answered through the director, no model. v0.25.0's table
(seeds 0-39) is in the root CHANGELOG.

```powershell
.\.venv\Scripts\python.exe scripts\simulate_doors.py --seeds 40
```

Run them before changing a balance constant (AGENTS.md rule 10).

## Sounds

Heard in the browser (v0.24.0, `data/sounds/sounds.yaml`; brass and gears). The files are the engine's; each sound has a synthesised fallback. One action makes one sound.

| When | Sound | What |
|---|---|---|
| Press | Gear tick | a short bandpassed click |
| Choice | Ratchet | three falling clicks |
| Turn arrives | Clock chime | two sine partials, a long tail |
| Ending | A bell tolls | engine bell file at 0.8 rate |
| Evil phase advances (`clockwork.phase`) | A low bell | the same file at 0.6 rate; tolls on an advance only, never a retreat or a load |
| Roll cast / degree | engine's | the DiceToast (which owns the `rolls` panel) calls the roll cue |
| Encounter starts | engine's | heard from the Stage, which is always mounted |

The phase badge, the Stage and the DiceToast fire the cues in `ui/src/stories/clockwork-dark/`. Every sound is on the audition page (`/?sounds=1`).

## Tests

The flagship has a row in every per-story test, and `scripts/simulate.py`'s
policies drive it headless. Since v0.25.0 `tests/test_finales.py` reaches every
ending through its door and walks every gate clause unmet
(`tests/clockwork_doors.py`), `tests/test_clockwork_dark.py` holds the story
(its decks, cards, cast and doors, and every ending reached by cards alone
through `tests/clockwork_walks.py`), and `tests/test_clockwork_dark_saves.py`
loads and plays nine v0.24.0 saves. `tests/test_no_flagship_nouns_in_engine.py`
and `tests/test_no_flagship_content_literals.py` keep its nouns out of the
engine.

## Known gaps

From CLAUDE.md's "Deliberately deferred" list and docs/GOVERNANCE.md's NOT
WIRED table, the rows that touch this story:

- Survival's hunger and death are not cut-invariant: how in-game time is cut
  into turns can change the outcome (`engine/game/survival.py`; ruled out of
  v0.25.0: engine-wide).
- The balance pass left five rows missed and recorded (CLAUDE.md): the
  `pinner` reaches The Pin and the Join in 57.5% of runs (band 80%), the
  `marcher`'s and the `drifter`'s median turns sit just under their bands,
  `scripts/simulate.py`'s `cautious` misses at seed 42, and no policy walks
  the barrows (`scripts/simulate_doors.py`).
- A card whose stage waits is dealt again on each visit (the bakery's
  `H1_the_question` up to 24 times in one run of the doors harness) and costs
  that turn (`data/scenes/`).
- On turn one, **The ways it ends** says "Nothing here is decided yet.": the
  only open door is the fail-forward, which the overlay hides until it is the
  locked ending, by design (`ui/src/stories/clockwork-dark/screens/Ends.jsx`).
  The overlay's hiding is the client's: the payload's endings block ships
  every tier (`engine/game/endings.py::to_client`).
- At a trader the player has not met, barter's rows cannot be pressed until
  the first turn played at that counter, and the overlay's list already
  carries that trader's real id and name (`engine/scenes/default_api.py`,
  `trade_offer` and `overlay_offer`; v0.26.0).
- With no session, the atlas route lists the works and the Join
  (`engine/scenes/default_api.py::codex_places`; v0.26.0).
- The narrator can raise `nf_naming_laid_it_out` before `spreading`, laying
  the naming out before its card would (`data/quests/convergence/naming_the_wound.yaml`;
  the card, `G1`, waits for `spreading`; v0.26.0).
- A v0.24.0 save already past 0.50 or 0.88 keeps Ilya and Sera on their
  routines: those doom beats fired before a move placed anyone
  (`engine/game/clocks.py::_apply_npc_moves`).
- `the_last_hour`, a fire-once `when:` event, is journalled once per day
  crossed inside one multi-day step
  (`engine/world/schedules.py::declared_events_due`).
- No verb gives or drops a thing, and barter buys one row a press
  (`ui/src/stories/clockwork-dark/parts/Inventory.jsx`,
  `ui/src/stories/clockwork-dark/screens/Trade.jsx`); the caravan brings no
  goods of its own (`engine/world/schedules.py`).
