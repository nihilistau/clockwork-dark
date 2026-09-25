# Hue & Cry

Tallowmere, a candle-making port lit by the Everflame. You step off the
morning barge, a Lantern of the Watch shouts "the Magpie!", and the whole city
decides you are its most famous thief. Register: Quest for Glory warmth, real
stakes -- wry and affectionate, and the gallows are real.

```powershell
.\.venv\Scripts\python.exe launcher.py --game hue-and-cry
```

Design: `docs/superpowers/specs/2026-09-23-hue-and-cry-design.md` §6.

## What ships now: the skeleton

v0.9 builds four engine features on this story -- the Law, premises, heists,
NPC agendas -- and v1.0 finishes it. What is here is the ground they stand on:

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
| Sergeant Brask's price: a bribe that loses your file | `data/rules/threads.yaml` |
| Jobs (v0.11): `burgle` a house and walk it stage by stage -- get there unseen, get in (door, window, roof or cellar), get past whoever is inside, open the strongroom, get clear -- with every house's security moving the odds, casing earning prep, three flashbacks to spend it on, and an alarm that brings the Watch; the Treasury has its own vault floor | `data/rules/jobs.yaml` |
| The burglar's kit, sold by Marrow: lockpicks and smoke pellets | `data/items/tools.yaml`, `data/economy.yaml` |
| Somewhere to sleep (v0.14): a pallet at Old Nance's flophouse in the Snuffs (1 cr), a free bunk over the Porters' Hall for anyone the Honest Company has no quarrel with, a room at the Snuffed Wick or over the Tallow Barge (3 cr), the plank bench in the cells while you are held, and a rough night anywhere, always -- plus bread and eel pie from Dock Mag's basket and ship's biscuit at Hollis's. Hunger runs at 2 an hour, and every street now costs stamina | `data/rules/survival.yaml`, `data/items/food.yaml`, `data/economy.yaml` |
| Scrounging and the secret ways (v0.14): two hours in the gutters of the docks, Wickmarket, the Snuffs, Gallows Green or Chandlers' Rise for bread, candle ends and the odd lost button -- and the hidden ways in: a drainpipe and a loading crane to the Rooftop Road, a yard grating to the Undercroft, the churchyard wall to the Old Bell Tower. The cells' drain reveals the Undercroft to anyone arrested; the Rooftop Road reveals the tower | `data/tables/forage.yaml`, `data/items/scrounge.yaml`, `data/procgen_templates/tallowmere.yaml`, `data/world/locations.yaml` |
| Honest work and luck (v0.14): carry for Dock Mag's gang on the quay (mornings, a crown or two and the end of the loaf), dip candles at Marsh & Daughters on the Rise (mornings), run errands for the Wickmarket stalls (market hours), or go round the lamps with Wren at dusk -- each open only in the hours its employer keeps, posted on the notice board, two shifts a day. An honest day covers bread and a flophouse bed with a little over; thieving pays more. Natural 20s and 1s draw Tallowmere's luck: a dropped crown, a Lantern's blind eye, a pie across the counter, tallow on the step, a crown lighter, and a jackdaw with opinions | `data/tables/labour.yaml`, `data/tables/boons.yaml`, `data/tables/complications.yaml` |
| Factions and the city's memory (v0.14): seven groups keep an opinion of you -- the Honest Company, the Lantern Watch, the Worshipful Company of Chandlers, the Wickmarket stallholders (each moved by honest work or a fight with a Lantern), and the Temple, the Margrave's household and the Silk Row houses (declared for the acts to come) -- and a lore corpus the narrator can draw on: the city, the Everflame, the Magpie's legend, the Watch, the Company, the Hanging Fair, the guilds, and the hidden city (the narrator's alone) | `data/world/factions.yaml`, `data/lore/*.md` |
| Mother Gannet's job: any house on Silk Row for the Honest Company, fifteen crowns net of its cut, three days to do it; left undone it costs the Company's good opinion | `data/rules/threads.yaml`, `data/world/factions.yaml` |

## What it deliberately does not ship yet

No decks (the initiation, the interrogation and the fair-day decks are
v0.16-v0.17), only two threads, and none of the acts' story yet. No
`death.yaml` either: it waits for v0.17 and The Rope ending, so until then a
lost fight can leave hp at zero with no respawn. Each is a later release's
job, and `game.yaml` lists them.
The graph template's stubs for these were removed rather than left in place --
they described a mill and a hedge-berry wood.

The ids above are pinned: later features read the districts, the fence ids
(`npc_pell_hollis`, `npc_marrow`) and the watch roles by name.

## Balance

The Law is measured: `scripts/simulate_law.py` plays a careful thief, a
reckless one, and a briber -- the reckless thief answering every Lantern's
stop with the bribe whenever its purse covers the price -- over 40 seeds x 10
in-game days, and every number in `data/rules/law.yaml` was set against it (the table is in CHANGELOG.md;
`tests/test_hue_and_cry.py` asserts the floors).

Jobs are measured too: `scripts/simulate_jobs.py` plays four burglars over 40
seeds -- `blind` (tier-1/2 houses, uncased, empty-handed, whenever, never
walking away), `careful` (lockpicks, cases a house to two lines, goes in the
hour nobody is home, spends its flashbacks, walks away from a roused house),
`greedy` (the careful method with a smoke pellet, on a tier-3+ house and then
the Treasury) and `greedy_bare` (the Treasury the blind way). Every number in
`data/rules/jobs.yaml` was set against it; the table is in its header and in
CHANGELOG.md, and `tests/test_hue_and_cry.py` asserts the bounds.
Scrounging is measured: `scripts/simulate_scrounge.py` plays a thief who
lives on it and one who does it mornings only, over 40 seeds x 10 days; the
table is in `data/tables/forage.yaml`'s header and CHANGELOG.md, and
`tests/test_hue_and_cry.py` bounds it (under a careful pickpocket's income,
under a full day's food).
The cost of living is measured: `scripts/simulate_labour.py` has an honest
porter, a candle-dipper, the careful pickpocket and the scrounger each buy
their own bread and bed over 40 seeds x 10 days; the table is in
`data/tables/labour.yaml`'s header and CHANGELOG.md, and
`tests/test_hue_and_cry.py` bounds it (an honest day keeps you most days with
little over, and pays less than thieving).
Everything else is unmeasured: `scripts/simulate.py`'s policies are
flagship-owned.
