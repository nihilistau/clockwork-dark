# Hue & Cry

Tallowmere, a candle-making port lit by the Everflame. You step off the
morning barge, a Lantern of the Watch shouts "the Magpie!", and the whole city
decides you are its most famous thief. Register: Quest for Glory warmth, real
stakes -- wry and affectionate, and the gallows are real.

```powershell
.\.venv\Scripts\python.exe launcher.py --game hue-and-cry
```

Design: `docs/superpowers/specs/2026-09-23-hue-and-cry-design.md` §6.
What changed, release by release: [CHANGELOG.md](CHANGELOG.md).

It draws with the engine's default skin (`ui.plugin: _engine`) until v0.21.0's
UI overhaul builds the wanted poster, job panel and casing board as engine
panels. No art plates ship yet: `data/art/subjects.yaml` briefs 19 locations
and 15 portraits, and `generate_art.py --game hue-and-cry` plans them.

## What ships now

The story was built alongside four engine features -- premises (v0.9), the
Law (v0.10), jobs and flashbacks (v0.11), agendas (v0.12) -- and is being
finished as a run of point releases up to v1.0.0 (living city v0.14, guild
economy v0.15; Acts I--III and the eight endings are v0.16--v0.17). Here is
what is in it today:

| What | Where |
|---|---|
| Eleven districts, three of them `secret: true` | `data/world/locations.yaml` |
| Fourteen scheduled people, all 24 hours; watch roles `captain` / `sergeant` / `watch` | `data/world/npc_schedules.yaml` |
| Two pipeline agents -- the city and Pip -- so every turn negotiates | `agents.yaml`, `prompts/` |
| Three archetypes: Cutpurse, Silver-tongue, Bruiser | `data/rules/archetypes.yaml` |
| The opening on Tallow Docks: run, talk, or go quietly, each with an intent | `game.yaml` → `entry.opening` |
| One reachable ending, `honest_after_all`, with its epilogue | `data/quests/the_way_out/`, `data/rules/endings.yaml`, `data/epilogues/` |
| Art prompts for every district, person and premise type; no plates yet | `data/art/` |
| Thirty-one premises a run -- eight generated types and four anchors (Vessaline House, the Margrave's Treasury, Mother Gannet's House, the Captain's Office) -- each with a household that keeps real hours, security by tier, loot and one secret | `data/premises/` |
| Pockets: alertness and purse by role, six days of heat | `data/rules/thievery.yaml` |
| Loot and purse goods, valued in crowns; crests and seals are `named` and stay hot | `data/items/goods.yaml` |
| The two fences, Pell Hollis (Wickmarket) and Marrow (the Snuffs); money reads "12 cr" | `data/tables/trade.yaml`, `data/economy.yaml` |
| The Lantern Watch (v0.10): three watch-houses, wanted bands, guises (your face, the Magpie's mask, a porter's smock), arrest to the Lantern House | `data/rules/law.yaml` |
| The Lantern's stop -- run, talk, bribe, surrender or fight -- opened only by a patrol that knows your face | `data/encounters/watch_stop.yaml` |
| Dock Mag, the first honest vendor, selling porters' smocks; Marrow's Magpie mask | `data/economy.yaml`, `data/items/guises.yaml` |
| Sergeant Brask's price: a bribe that loses your file -- offered only while the Wick's drawer holds something against you (v0.15) | `data/rules/threads.yaml` |
| Jobs (v0.11): `burgle` a house and walk it stage by stage -- get there unseen, get in (door, window, roof or cellar), get past whoever is inside, open the strongroom, get clear -- with every house's security moving the odds, casing earning prep, three flashbacks to spend it on, and an alarm that brings the Watch; the Treasury has its own vault floor | `data/rules/jobs.yaml` |
| The burglar's kit, sold by Marrow: lockpicks and smoke pellets | `data/items/tools.yaml`, `data/economy.yaml` |
| The Porters' Hall bench (v0.15): `craft` lockpicks, smoke pellets, a lamplighter's coat (a new guise) and a forged Margrave's Hill gate pass (a jobs tool on the Hill only) from makings sold by the two fences or found in the Snuffs' middens -- a set of picks for under half Marrow's price, and nothing that sells for more than its makings | `data/recipes/workshop.yaml`, `data/rules/jobs.yaml` |
| The Magpie's Hoard (v0.15): six famous shines the ballad says the Magpie took and never fenced -- four in the anchors' strongrooms, two found by standing in secret places. Named, so hot for good: kept, not fenced, and an arrest takes them all back. Carry all six at once and the Honest Company thinks the better of you | `data/tables/collections.yaml`, `data/quests/the_magpies_hoard/` |
| Blackmail (v0.15): a house's secret, cased and carried out of its job, is held -- and each anchor's is a squeeze on its owner (Lady Imelda, Mother Gannet, Captain Ardane, Steward Quill), struck at their door in their hours and collected there inside two days. Left uncollected, the squeezed party swears a `blackmail` report to the Watch (all but Mother Gannet) and their people turn on you | `data/rules/threads.yaml`, `data/premises/anchors/`, `data/rules/law.yaml` |
| The fences' credit (v0.15): Pell Hollis's advance (ten crowns, thirteen back in three days) and Marrow's slate (five, eight back in two), paid in coin at her counter. Welsh on one and neither fence buys from you or lends to you again, and her collectors walk the streets for you -- after dark, and by day in the fences' own districts -- until you pay | `data/rules/threads.yaml`, `data/tables/trade.yaml`, `data/encounters/streets.yaml` |
| Somewhere to sleep (v0.14): a pallet at Old Nance's flophouse in the Snuffs (1 cr), a free bunk over the Porters' Hall for anyone the Honest Company has no quarrel with, a room at the Snuffed Wick or over the Tallow Barge (3 cr), the plank bench in the cells while you are held, and a rough night anywhere, always -- plus bread and eel pie from Dock Mag's basket and ship's biscuit at Hollis's. Hunger runs at 2 an hour, and every street now costs stamina | `data/rules/survival.yaml`, `data/items/food.yaml`, `data/economy.yaml` |
| Scrounging and the secret ways (v0.14): two hours in the gutters of the docks, Wickmarket, the Snuffs, Gallows Green or Chandlers' Rise for bread, candle ends and the odd lost button -- and the hidden ways in: a drainpipe and a loading crane to the Rooftop Road, a yard grating to the Undercroft, the churchyard wall to the Old Bell Tower. The cells' drain reveals the Undercroft to anyone arrested; the Rooftop Road reveals the tower | `data/tables/forage.yaml`, `data/items/scrounge.yaml`, `data/procgen_templates/tallowmere.yaml`, `data/world/locations.yaml` |
| Honest work and luck (v0.14): carry for Dock Mag's gang on the quay (mornings, a crown or two and the end of the loaf), dip candles at Marsh & Daughters on the Rise (mornings), run errands for the Wickmarket stalls (market hours), or go round the lamps with Wren at dusk -- each open only in the hours its employer keeps, posted on the notice board, two shifts a day. An honest day covers bread and a flophouse bed with a little over; thieving pays more. Natural 20s and 1s draw Tallowmere's luck: a dropped crown, a Lantern's blind eye, a pie across the counter, tallow on the step, a crown lighter, and a jackdaw with opinions | `data/tables/labour.yaml`, `data/tables/boons.yaml`, `data/tables/complications.yaml` |
| Factions and the city's memory (v0.14): seven groups keep an opinion of you -- the Honest Company, the Lantern Watch, the Worshipful Company of Chandlers, the Wickmarket stallholders (each moved by honest work or a fight with a Lantern), the Margrave's household and the Silk Row houses (moved since v0.15 by a squeeze left uncollected), and the Temple of the Everflame (declared for the acts to come, moved by nothing yet) -- and a lore corpus the narrator can draw on: the city, the Everflame, the Magpie's legend, the Watch, the Company, the Hanging Fair, the guilds, and the hidden city (the narrator's alone) | `data/world/factions.yaml`, `data/lore/*.md` |
| Mother Gannet's job: any house on Silk Row for the Honest Company, fifteen crowns net of its cut, three days to do it; left undone it costs the Company's good opinion | `data/rules/threads.yaml`, `data/world/factions.yaml` |

## What it deliberately does not ship yet

Each of these is a later release's job, and CLAUDE.md's "Deliberately
deferred" list carries the engine-side rows:

- **No decks.** The initiation, interrogation and fair-day decks are
  v0.16--v0.17, with Acts I--II in v0.16; Act III and the eight endings
  are v0.17. Until then the one ending is
  `honest_after_all`.
- **No `death.yaml`.** It waits for v0.17 and The Rope ending, so until then a
  lost fight or hunger can leave hp at zero with no respawn.
- **Flags nothing reads yet.** Completing the Magpie's Hoard sets
  `magpies_hoard_complete`, read by nothing until v0.17's The Legend; the
  agenda clocks' beats set flags only later scenes will read; and nothing
  sets `magpie_unmasked`, so nothing ever says who the Magpie is.
- **A generated house's secret opens no thread.** It is held when carried out
  of a job; only the four anchors' secrets name a blackmail.
- **Hired hands** (spec §4) are not built: a job is walked solo.
- **No bespoke screens.** The Law and the job reach the client payload and the
  prose; no panel draws them until v0.21.0.

The threads that do ship are Brask's bribe, Mother Gannet's job, the four
squeezes and the two lines of credit. The graph template's stubs were removed
rather than left in place -- they described a mill and a hedge-berry wood.

The ids above are pinned: later features read the districts, the fence ids
(`npc_pell_hollis`, `npc_marrow`) and the watch roles by name.

## Balance

Every HUE & CRY system is measured by its own headless harness, with no model,
over 40 seeds of in-game days (AGENTS.md rule 10). None of them writes a
save.

| Harness | Policies | Numbers set against it |
|---|---|---|
| `scripts/simulate_law.py` | `careful`, `reckless`, `briber` | `data/rules/law.yaml` |
| `scripts/simulate_jobs.py` | `blind`, `careful`, `greedy`, `greedy_bare` | `data/rules/jobs.yaml` (table in its header) |
| `scripts/simulate_agendas.py` | `idle`, `careful`, `reckless` | `data/rules/agendas.yaml`, `data/rules/clocks.yaml` |
| `scripts/simulate_scrounge.py` | `scrounger`, `mornings` | `data/tables/forage.yaml` (table in its header) |
| `scripts/simulate_labour.py` | `porter`, `dipper`, `careful`, `scrounger`, `careful_pell`, `careful_marrow` | `data/tables/labour.yaml` (table in its header) |
| `scripts/simulate_streets.py` | `wanderer` | `data/encounters/rules.yaml`, `data/encounters/streets.yaml` |
| `scripts/simulate_hoard.py` | `hoarder` | `data/tables/collections.yaml`, the squeezes in `data/rules/threads.yaml` |

The law, jobs and agendas harnesses take `--set KEY=VALUE` to try a number
without editing the file; every one takes `--json` for the raw table. The measured tables are in [the root
CHANGELOG](../../CHANGELOG.md) under the release that set them (summarised in
this story's [CHANGELOG.md](CHANGELOG.md)), and `tests/test_hue_and_cry.py`
asserts the Law's floors and the jobs, scrounging and cost-of-living bounds.
`scripts/simulate.py`'s policies are flagship-owned; a thief policy for it is
v0.18.0.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_hue_and_cry.py -q
```

`tests/test_hue_and_cry.py` holds the story's shape and its measured bounds;
the story also has a row in every per-story test (`tests/test_finales.py`
plays it to `honest_after_all`).
