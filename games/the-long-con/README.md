# THE LONG CON

Two rooms over a laundry, a name on the glass with one too many Vances in it,
and a client who has not taken off her gloves. The papers buried the man in her
photograph nine days before it was taken.

```powershell
.\.venv\Scripts\python.exe launcher.py --game the-long-con
```

What changed, release by release: [CHANGELOG.md](CHANGELOG.md).

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

Two meters, both `veiled` (`state.yaml`): **standing** and **heat**. The
client and the narrator get a band word, never the number. Every stage of the
case adds heat and spends standing; the goods Georgie Pell sells (cigarettes,
bonded rye, somebody else's press pass) and the city's work (the
weighbridge, the Cadenza's door) push back. Money reads in dollars. There is
no hunger and no rest verb: this story declares no `survival.yaml`, and no
ground to forage on.

It ends in one of three classes (`data/rules/endings.yaml`, epilogues in
`data/epilogues/`): `clean_hands`, `the_frame_holds` and `carrying_it`.

**Its own UI plugin** — `ui.plugin: the-long-con`
(`ui/src/stories/the-long-con/`): its own ledger and theme.

## What it exercises

Built to use the engine's newer work rather than to describe it:

| Feature | Where you meet it |
|---|---|
| Subject memory | Sonia, Ruse, Farrow and Sarn remember what you said and what you owe |
| `secret:` places | **The Drying Room** is not on the map, in the travel options or on the road to it until the case reaches its stage (`known_when:` in `data/world/locations.yaml`) |
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
wrong painting would be. It declares no art paths at all (`art_subjects`,
`art_manifest`, `art_root`) and has no `data/art/`, so an art brief is the
first thing to write before `generate_art.py --game the-long-con` has
anything to plan.

## What is not measured

`scripts/simulate.py`'s policies are flagship-owned — they walk Edgewood's ids
and buy from Edgewood's vendors — so **no balance claim here has been
simulated**. The numbers on the edges and the clock thresholds are authored
judgement, not measurement. Say so before trusting them.

## Tests

The story has no test file of its own; it has a row in the per-story tests,
among them `tests/test_finales.py` (the case played to an ending),
`tests/test_secret_locations.py` (the drying room's reveal),
`tests/test_livelihood_per_game.py` (its vendor and work),
`tests/test_forced_and_repeatable_decks.py` (the interview deals as before)
and `tests/test_presence_every_story.py`.
