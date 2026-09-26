# The Clockwork Dark

The flagship. You wake at the forest's edge beside Edgewood, the last
comfortable village before the Marches, and something patient and brass is
working its way outward from the Wound. Become a hero or become a baker: the
evil ticks either way, and the quiet life counts as a complete game.

```powershell
.\.venv\Scripts\python.exe launcher.py --game clockwork-dark
```

It is the engine's default story (`game.default` in `config/default.yaml`), so
a bare `launcher.py` plays it too. What changed, release by release:
[CHANGELOG.md](CHANGELOG.md). The design and the story bible are in
[docs/DESIGN.md](../../docs/DESIGN.md).

## The shape

A graph story, and the one every other graph story was measured against:

| What | Where |
|---|---|
| Twenty locations in rings out from the Wound; the five canon ids (`forest_clearing`, `edgewood_square`, `edgewood_bakery`, `tinker_caravan`, `millhaven_gate`) must not be renamed | `data/world/locations.yaml` |
| A village generated per seed: villagers, venues, the festival | `data/procgen_templates/edgewood.yaml` |
| The **evil clock**: `dormant`, `stirring`, `spreading`, `consuming`, advancing whatever you do; pushing back buys reprieve (`doom_resistance`) | `data/rules/doom_effects.yaml`, `state.yaml` |
| 25 quests in four arcs (`quiet_life`, `whisper`, `march`, `convergence`) that open on **awareness**, a hidden stat, so a baker who never listens stays a baker | `data/quests/` |
| Eight ending classes and their epilogue cards | `data/rules/endings.yaml`, `data/epilogues/` |
| Three archetypes: Wayfarer, Hearthkeeper, Tinker-apprentice | `data/rules/archetypes.yaml` |
| Survival (stamina, hunger, hp; rest is never gated) and death rules: you are carried back to the square, and only a second death while the world is `consuming` ends the run | `data/rules/survival.yaml`, `data/rules/death.yaml` |
| Trade with three vendors, paid work, foraging, boons and complications, collectable sets | `data/economy.yaml`, `data/tables/` |
| Crafting: 22 recipes (baking, herbalism, mending), offered by the `craft` verb only where one can be made | `data/recipes/` |
| Encounters played as scenes on the roads, in the forest, the village and the Marches | `data/encounters/` |
| Set pieces in Edgewood | `data/challenges/edgewood.yaml` |
| World events and schedules, NPC schedules, factions, rumours | `data/world/` |
| A lore corpus for RAG | `data/lore/` |

**Two agents** (`agents.yaml`, canon ids): `clockwork_storyteller` narrates,
and `clockwork_assistant` is the in-world companion whose trust you earn. It
takes one of five forms, never sees the raw evil clock, and is not a pipeline
participant (`pipeline: false`), so turns do not negotiate. Its hints are in
`data/assistant/hints.yaml`.

**Its own UI plugin** — `ui.plugin: clockwork-dark`
(`ui/src/stories/clockwork-dark/`), including the notice-board overlay (`n`).

## Art

The largest shipped pack, in `content/scenes/clockwork/static/art/` (the
flagship's art root predates per-story art directories):
`data/art/manifest.yaml` maps 20 locations, five Assistant forms, four
portraits, 81 items, five enemies, UI plates and the dice.
`scripts/art_missing.py --game clockwork-dark` lists what is still missing,
and `scripts/generate_art.py` (the default plan is this story's) fills it.

## Balance

`scripts/simulate.py` is this story's harness: five policies (`baker`,
`cautious`, `hero`, `pauper`, `reckless`), headless, no model.

```powershell
.\.venv\Scripts\python.exe scripts\simulate.py --policy all --turns 200 --seed 42
```

Run it before changing a balance constant (AGENTS.md rule 10).

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
