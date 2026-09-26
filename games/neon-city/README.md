# NEON CITY: THE CROSSING

The first story in the NeonCity canon: a survival/expedition on the engine's
graph shape. Somebody sold you forty seconds of your own death with a
corporate header and a timestamp twenty-one days out; the walk from Mira's
counter to the thing that filed it crosses every district of the Sprawl, and
every district is a debt you pay to pass.

The design doc is [BIBLE.md](BIBLE.md) — canon-checked against the NeonCity
project files; every name, price and gate number in this tree is checked
against it. What changed, release by release: [CHANGELOG.md](CHANGELOG.md).

```powershell
.\.venv\Scripts\python.exe launcher.py --game neon-city
```

## The shape

Graph story, flagship-shaped, with the deck half's structural systems wired
in: fourteen locations across four altitudes, 22 quests in four arcs
(`the_toll`, `the_count`, `the_file`, `the_gate`), a scavenge economy (forage
tables per district, seven vendors, five jobs), survival and death rules
(`data/rules/survival.yaml`, and a `death.yaml` that respawns rather than
ending the run), a lore corpus (`data/lore/`), and the systems below, which
the flagship does not use:

| System | Where | What it does |
|---|---|---|
| The timestamp | `state.yaml` + `data/rules/clocks.yaml` (`timestamp`) | 0–21, wound one segment per world day past a slack ladder to day 28. Quests make it SLIP (negative value effects) — the doom_resistance-shaped reprieve, wired to a real clock. |
| Collections | same pair (`debt`) | debt escalation: reminder → visit → consequence, fed by an empty purse and the `debt_marker` flag. |
| Threads | `data/rules/threads.yaml` | the Sprawl's contracts: Collections' marker, Dita's fifteen percent, Dane's arrangement, Wren's invoice. |
| Heat | `state.yaml` | a `veiled` meter: the client gets the rung of the heat ladder, never the number. |

**Six ending classes** from the bible (`data/rules/endings.yaml`, epilogues
in `data/epilogues/`); the finale lock rides `who_holds_the_pen`'s
`on_complete` (`ending_lock` + `ending_module`).

**No doom clock** — `world.evil_base_rate_per_day: 0.0`; the pressure is
heat, debt, the weather and the file.

**Three agents, two in the pipeline** (`agents.yaml`): `gm` (the world) and
`ghost` (the signal) plan and negotiate every turn, which costs one extra
model call; `the_line`, the Grid's earpiece channel, is the companion and
leads no turns. Mira Vex is deliberately a scheduled vendor, not an agent.

**Its own UI plugin** — `ui.plugin: neon-city` (`ui/src/stories/neon-city/`):
black canvas, a #06b6d4 scene accent, gold mono prices (`₵`) and the heat
ladder as chrome (BIBLE.md §7.4), and `NO FEED` where a plate is missing.

## What is deliberately not here yet

- **Art pack**: `data/art/manifest.yaml` maps nothing; the procedural
  silhouette carries the story. `data/art/subjects.yaml` is the complete
  brief for 75 plates, the entry location `the_grid` included, and
  `data/art/MISSING-PLATES.md` (regenerate it with
  `scripts/art_missing.py --game neon-city`) lists them with ready prompts;
  `scripts/generate_art.py --game neon-city` renders them.
- **Balance measurements**: `scripts/simulate.py`'s five policies walk
  Edgewood by design, so this story's economy and clock numbers are
  UNMEASURED — they are the bible's canon numbers, hand-checked, not
  simulated. Treat balance claims accordingly.

## The gates, honestly

The engine's travel graph carries no predicates on its roads, so the canon
gates are enforced where this engine can enforce them: the Bunker's heat ≤ 40
is a real stage predicate (`heat_forty`); the Grid Point's heat-70 refusal
and the lift's keys-and-crew interlock are quest preconditions, encounter
pressure, ending gates and the narrator's standing law
(`prompts/storyteller.md`) — not a wall the travel system itself raises.

## Tests

The story has no test file of its own; it has a row in the per-story tests,
among them `tests/test_finales.py` (played to an ending),
`tests/test_presence_every_story.py`, `tests/test_quests.py` and
`tests/test_terminal_death_ending.py` (its respawn is unchanged by terminal
deaths).
