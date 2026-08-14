# THE LONG CON

Two rooms over a laundry, a name on the glass with one too many Vances in it,
and a client who has not taken off her gloves. The papers buried the man in her
photograph nine days before it was taken.

```powershell
.\.venv\Scripts\python.exe launcher.py --game the-long-con
```

## The shape: a graph city with a deck in the middle of it

**The first shipped story to declare both halves.** `locations`, `quests`,
`encounters`, `economy` and `tables` make it a graph you walk — eight places,
hours on every edge, `danger_dc` that is the bulls rather than muggers. And
`decks` plus `clocks` give it an authored set-piece: when `the_frame` fills,
`forces_scene` deals `the_interview`, and Ruse stops being your old partner.

That coupling is the whole trick, and it is two files that must agree:
`data/rules/clocks.yaml` names the deck by its **id**, and
`data/scenes/the_interview.yaml` carries it. A clock whose forced scene does
not exist is a promise with nothing behind it.

`dev-story` already proved decks and quests coexist. What is new here is decks
alongside a *full* graph — roads, road encounters, a shop.

## What it exercises

Built to use the engine's newer work rather than to describe it:

| Feature | Where you meet it |
|---|---|
| Subject memory | Sonia, Ruse, Farrow and Sarn remember what you said and what you owe |
| `secret:` places | **The Drying Room** is not on the map and neither is the road to it, until you stand in it |
| Derived map points | Active case stages and Georgie Pell's stock appear as pins; no map data is authored |
| Clue board | What you work out is yours — press `K` — and is not what is true |
| Gossip | Say something at the Cadenza and meet it again at the Mirado |
| Continuity guard | A scene that greets somebody you know as a stranger is rejected and rewritten |
| The engine's map | Press `M`. This story authors nothing for it |

## The cast

**Delphine Ruse-Bellamy**, the client, whose surname has a hyphen in it she has
not mentioned. **Sonia Kell** behind the Cadenza's bar, who treats remembering
what everybody drinks as a filing system. **Lt. Aurelio Ruse**, your partner
once, with your brother's file in his third drawer. **Bette Farrow** at The
Ledger, who trades a look at a folder for something she can print. **Vittorio
Sarn**, who owns Club Mirado the way weather owns a season. **Georgie Pell**
under the third lamp, selling what came off a boat.

No `agents.yaml`: every one of them is narrated. Giving one an agent would make
her a model call and a persona file, and this story's people work better as
things the narrator is *told about* than as voices arguing in the pipeline.

## What to edit for what

| You want to change | Edit |
|---|---|
| The first frame and its choices | `game.yaml` → `entry.opening` |
| The narrator's voice, the cast | `prompts/storyteller.md` |
| The city and what crossing it costs | `data/world/locations.yaml` |
| Who is where, hour by hour | `data/world/npc_schedules.yaml` |
| The case | `data/quests/the_case/` |
| What fills the frame, and what it deals | `data/rules/clocks.yaml` |
| The interrogation | `data/scenes/the_interview.yaml` |
| Meters and the clock (what they ARE) | `state.yaml` |

## Art

Ships with **no plates**, and plays without them: the procedural silhouette
carries every location, which for a story this dark is closer to right than a
wrong painting would be. `data/art/subjects.yaml` and a `generate_art.py` run
are the next thing it wants, not a blocker.

## What is not measured

`scripts/simulate.py`'s policies are flagship-owned — they walk Edgewood's ids
and buy from Edgewood's vendors — so **no balance claim here has been
simulated**. The numbers on the edges and the clock thresholds are authored
judgement, not measurement. Say so before trusting them.
