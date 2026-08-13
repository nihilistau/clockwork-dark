# {{title}}

Scaffolded from the **graph** template: flagship-shaped. A travel graph with
hours on the edges, quests in arcs, encounters where the map says danger
lives, and a livelihood economy — vendors, paid work, forage tables, boons
and complications on the natural 20 and 1.

```powershell
.\.venv\Scripts\python.exe launcher.py --game {{slug}}
```

## What to edit for what

| You want to change | Edit |
|---|---|
| The opening scene and the buttons | `game.yaml` → `entry.opening` |
| The narrator's voice and the world | `prompts/storyteller.md` |
| The map and travel costs | `data/world/locations.yaml` |
| The objects everything else names | `data/items/goods.yaml` |
| Skills, difficulty bands, modifiers | `data/rules/skills.yaml` |
| Character classes | `data/rules/archetypes.yaml` + `entry.archetypes` |
| Quests | `data/quests/arcs.yaml` + `data/quests/<arc>/` |
| Road danger | `data/encounters/` + `danger_dc` on edges |
| Who sells what, at what price | `data/economy.yaml` + `data/tables/trade.yaml` |
| Paid work | `data/tables/labour.yaml` |
| Free food | `data/tables/forage.yaml` |
| Crit and fumble outcomes | `data/tables/boons.yaml`, `complications.yaml` |
| What the narration may not say yet | `data/rules/spoilers.yaml` |

## The three rules this shape lives or dies by

1. **Every id must resolve.** A forage row, a wage in-kind or a stock line
   naming an item that `data/items/` does not declare fails silently — the
   pick just never arrives. Check references when you rename anything.
2. **Keep a free food loop.** Foraging is the floor under a broke player.
   Price everything and you have authored a countdown, not an economy — the
   flagship shipped that bug and `scripts/simulate.py` is how it was found.
   Run it before trusting any balance number you change here.
3. **Danger and encounters agree.** `danger_dc` on an edge with no matching
   encounter rows is a roll that cannot pay off; encounters for an edge with
   `danger_dc: 0` never fire.

## Growing it

Each subsystem is one `paths.*` line in `game.yaml`. Missing halves of the
flagship's shape — `recipes` (crafting), `npc_schedules` and `factions`
(people with routines and opinions; add `faction:` keys back to jobs and
vendors once declared), `doom_effects` and a nonzero `evil_base_rate_per_day`
(background dread) — are all additive. The full worked example of every
subsystem is `games/dev-story/`; the full-scale version of this shape is
`games/clockwork-dark/`.
