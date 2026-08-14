# NEON CITY: THE CROSSING

The fourth shipped story, first in the NeonCity canon: a survival/expedition
on the engine's graph shape. Somebody sold you forty seconds of your own
death with a corporate header and a timestamp twenty-one days out; the walk
from Mira's counter to the thing that filed it crosses every district of the
Sprawl, and every district is a debt you pay to pass.

The design doc is [BIBLE.md](BIBLE.md) — canon-checked against the NeonCity
project files; every name, price and gate number in this tree is checked
against it.

```powershell
.\.venv\Scripts\python.exe launcher.py --game neon-city
```

## The shape

Graph story, flagship-shaped, with the deck half's structural systems wired
in: fourteen locations across four altitudes, 22 quests in four arcs, a
scavenge economy (forage tables per district, seven vendors, five jobs), and
three declared systems the flagship does not use —

| System | Where | What it does |
|---|---|---|
| The timestamp | `state.yaml` + `data/rules/clocks.yaml` | 0–21, wound one segment per world day past a slack ladder to day 28. Quests make it SLIP (negative value effects) — the doom_resistance-shaped reprieve, wired to a real clock. |
| Collections | same pair | debt escalation: reminder → visit → consequence, fed by an empty purse and the `debt_marker` flag. |
| Threads | `data/rules/threads.yaml` | the Sprawl's contracts: Collections' marker, Dita's fifteen percent, Dane's arrangement, Wren's invoice. |
| Endings | `data/rules/endings.yaml` + `data/epilogues/` | six classes from the bible; the finale lock rides `who_holds_the_pen`'s `on_complete` (`ending_lock` + `ending_module`). |

**No doom clock** — `world.evil_base_rate_per_day: 0.0`; the pressure is
heat, debt, the weather and the file.

## What is deliberately not here yet

- **Art pack**: `data/art/manifest.yaml` maps nothing; the procedural
  silhouette carries the story. `data/art/subjects.yaml` is the complete
  brief (both prompt dialects) for the batch render, and
  `scripts/art_missing.py --game neon-city` writes the gap list.
- **Bespoke UI plugin**: the manifest borrows the Garden's skin
  (`ui.plugin: wicked-garden`); the NeonCity look (black canvas, #06b6d4,
  gold mono prices) is a later phase.
- **Balance measurements**: `scripts/simulate.py` refuses non-flagship graph
  stories (its five policies walk Edgewood by design), so this story's
  economy and clock numbers are UNMEASURED — they are the bible's canon
  numbers, hand-checked, not simulated. Treat balance claims accordingly.

## The gates, honestly

The engine's travel graph carries no predicates, so the canon gates are
enforced where this engine can enforce them: the Bunker's heat ≤ 40 is a
real stage predicate (`heat_forty`); the Grid Point's heat-70 refusal and
the lift's keys-and-crew interlock are quest preconditions, encounter
pressure, ending gates and the narrator's standing law
(`prompts/storyteller.md`) — not a wall the travel system itself raises.
