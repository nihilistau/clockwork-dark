# The Wicked Garden

A garden between worlds, and a High Fae who has decided she wants you. One day
here is ten days at home, and the toll is charged whether you spend it well or
not. Please her, match her, escape her, or be consumed.

```powershell
.\.venv\Scripts\python.exe launcher.py --game wicked-garden
```

The deck exemplar: no hp, no hunger, no dice rolls against a skill, no
vendors and no travel costs worth planning around. It exists to show the
engine is not one game with the nouns swapped. What changed, release by
release: [CHANGELOG.md](CHANGELOG.md).

Two longer notes live beside the content they describe:
[data/README.md](data/README.md) (the world: places, items, cast, lore
scopes, the art pack's sources) and
[data/scenes/README.md](data/scenes/README.md) (the day chapters: the deck
grammar, bounds, and what was wired when).

## The shape

| What | Where |
|---|---|
| Ten authored days, `day_00_prologue` to `day_09_finale`, plus the thorn labyrinth's chamber deck: eleven decks, 136 cards | `data/scenes/` |
| **Time debt**: `time_debt_mortal_days`, ten mortal days charged for each one spent inside | `state.yaml` |
| **Veiled meters**: `favor`, `autonomy`, `corruption`, `knowledge`, `desire`, `equality_seed`. The client gets a band word, never the number, and the suite enforces it | `state.yaml` |
| Four clocks: `briar_hunger`, `ashen_pressure`, `sophia_break`, `mortal_collapse` | `data/rules/clocks.yaml` |
| Threads: the bargains, which are this story's currency | `data/rules/threads.yaml` |
| 23 endings in six classes (E1–E6), each with its epilogue; the finale locks what the player earned and plays its Speak · Act · Seal beats | `data/rules/endings.yaml`, `data/epilogues/` |
| Fourteen places (13 real, plus the `unknown` sentinel) in a demiplane whose door in is one-way; going home is an ending, not a road | `data/world/locations.yaml` |
| Eight scheduled people (Sophia is not one of them), seven factions, rumours in three awareness tiers | `data/world/` |
| 23 items in five reliquary sets | `data/items/garden.yaml`, `data/tables/collections.yaml` |
| A lore corpus with knowledge scopes: GM secrets and Sophia's private chunks | `data/lore/` |

It declares no quests, economy, encounters, recipes, challenges, procgen or
doom clock; `game.yaml` says why for each.

**Two agents in the pipeline** (`agents.yaml`): `gm` (the world) and `sophia`
(the High Fae, a character agent, not a scheduled NPC). Both plan before
either speaks, so every turn negotiates and costs one extra model call; each
is kept from the other's secrets by the lore scopes.

**Its own UI plugin** — `ui.plugin: wicked-garden`
(`ui/src/stories/wicked-garden/`): Sophia's portrait, the veiled meters and
the epilogue card.

## Art

`data/art/plates/`, mapped by `data/art/manifest.yaml`: eight location plates,
Sophia's portrait with her wardrobe states and expressions, the other
courtiers, 22 item plates and a still. `data/art/MISSING-PLATES.md` lists
what is missing, with prompts (`scripts/art_missing.py --game wicked-garden`
regenerates it).

## Balance and tests

`scripts/simulate_decks.py` walks the deck shape headless, with no model:
every ending, card and clock, over seeded runs.

```powershell
.\.venv\Scripts\python.exe scripts\simulate_decks.py --game wicked-garden --runs 200
```

`tests/test_wicked_garden_scenes.py` and `tests/test_simulate_decks.py` hold
the decks; the story has a row in every per-story test
(`tests/test_finales.py` plays it to an ending).

## Known gaps

From CLAUDE.md's "Deliberately deferred" list:

- **Endings the walker never reaches.** Measured 2026-09-26 with
  `simulate_decks.py`: 7 of the 23 endings are never reached in 1000 runs
  (E2b, E2c, E3a, E3b, E3c, E4d, E5a) and 9 in 200. No card goes undealt.
- **`mortal_threshold`, the entry location, has no plate on purpose.** It
  hosts the ten-card prologue, so a new player sees no scene art until the
  prologue ends. Six of the fourteen places have no plate.
- **`day_09_finale` is dealt twice** (pre-existing).
