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

## What it deliberately does not ship yet

No honest shops, forage, labour, boon or complication tables, no encounters,
decks, clocks, threads or factions. Each is a later release's job, and
`game.yaml` lists them. The only trade is the two fences.
The graph template's stubs for these were removed rather than left in place --
they described a mill and a hedge-berry wood.

The ids above are pinned: later features read the districts, the fence ids
(`npc_pell_hollis`, `npc_marrow`) and the watch roles by name.

## Balance

Unmeasured. `scripts/simulate.py`'s policies are flagship-owned and there is no
headless harness for this story yet; the design adds a thief policy in v0.9.
