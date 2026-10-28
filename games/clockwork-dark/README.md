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
(`ui/src/stories/clockwork-dark/`), including the notice-board overlay (`n`).

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
| The Counted March | the march arc open, the militia at 20, a levy seen through (a march quest, or a night on the wall) | the gate or the square while Sera is there: `the_muster_roll` / `M1` / `strike_it` |
| The Named Wound | named, decided, and the last quiet morning at its third stage | the bakery 04-09, Maris there: `the_morning_firing` / `Q1` / `tell_her` or `say_nothing` |
| The Price Asked | named, chose (a thing offered at `S1`), paid | wherever Ilya is while the sacrifice is open: `the_price` / `S2` / the beat for the thing offered, which takes exactly that thing |
| The Pin and the Join | the ninth pin taken and held, the join walked | at the Join: `the_join` / `J1` / `set_it` |
| The Stopped Wheel | the doom reading at 1.0 | forced, not walked to: the declared event `the_last_hour` deals `the_stopped_wheel` / `Z1` once an open encounter or hand is done |

## Art

The largest shipped pack, in `content/scenes/clockwork/static/art/` (the
flagship's art root predates per-story art directories):
`data/art/manifest.yaml` maps 20 locations, five Assistant forms, four
portraits, 81 items, five enemies, UI plates and the dice. The two secret
places, the four new people and the new bands' six enemies have prompts but
no plate yet, so they draw the procedural tile.
`scripts/art_missing.py --game clockwork-dark` lists what is still missing,
and `scripts/generate_art.py` (the default plan is this story's) fills it.

## Balance

`scripts/simulate.py` is this story's harness: five policies (`baker`,
`cautious`, `hero`, `pauper`, `reckless`), headless, no model.

```powershell
.\.venv\Scripts\python.exe scripts\simulate.py --policy all --turns 200 --seed 42
```

```sh
.venv/bin/python scripts/simulate.py --policy all --turns 200 --seed 42   # Linux
```

Run it before changing a balance constant (AGENTS.md rule 10).

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

The flagship has a row in every per-story test (`tests/test_finales.py`
plays it to an ending), and `scripts/simulate.py`'s policies drive it
headless. `tests/test_no_flagship_nouns_in_engine.py`
and `tests/test_no_flagship_content_literals.py` keep its nouns out of the
engine.

## Known gaps

From CLAUDE.md's "Deliberately deferred" list, the rows that touch this story:

- Set pieces (`paths.challenges`, which only this story declares) are not
  checked by `scripts/doctor.py` or `scripts/validate_content.py`.
- Survival's hunger and death are not cut-invariant: how in-game time is cut
  into turns can change the outcome.
