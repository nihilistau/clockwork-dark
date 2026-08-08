# The Drowned Carillon

A second, complete game on the same engine. Nothing in `engine/` was edited to
make it playable.

    python launcher.py --game drowned-carillon
    CLOCKWORK_GAME=drowned-carillon python launcher.py

## The premise

A cathedral organ lies intact under the Brass Coast, and the tide plays it. It
does not drown people; it *tunes* them, and leaves salt, verdigris and a chime
where a heartbeat used to be. It answers bells — the shore-bell on
Bellfounders' Quay was rung once, in the year of the three tides, and the
Carillon has been holding the second half of that phrase ever since.

It feeds on song and grief. The more cleanly a thing has been sung over, the
more cleanly it can be sounded out.

## What you can actually do

The map is six places in four rings, all of them going down:

    tide_flats -> bellfounders_quay -> wet_steps -> sunken_nave -> choir_loft
                        |
                  net_lofts, lamp_house

- **Mend nets and carry oil.** The `tide_work` arc is two full quests and a
  vendor economy across three merchants. A player who never learns the word
  *Carillon* has finished the game — the same thesis as the flagship, and it
  is stated in `data/quests/arcs.yaml` in the same words.
- **Trade.** Cael sells light and wax, Vesh sells twine and fish, Halloran
  buys green brass by weight and writes nothing down.
- **Craft.** Three recipes, including `damp_a_casting` — this game's `sympathy`
  recipe, hardest band in the directory, and the only thing you can make whose
  purpose is to stop something being heard.
- **Go down.** Four dangerous travel legs, each with encounter content in both
  directions: a gull that rings, a set-net sorted by pitch, Vesh on the ninth
  step, chime-husks on the stair, the choir in the nave, and the Tide-Cantor
  on the loft stair.
- **Still the Carillon.** The `the_stilling` arc unlocks on awareness and a
  witnessed bell-watch. Four stages, all engine-evaluable: get the wax, reach
  the nave, reach the choir loft in the low-water hour, still the pipes.

## What was ported, and where it went

The source project shipped `games/drowned-carillon/` as 11 KB of content with
no manifest, no loader and no Python. The writing was good. It was ported into
this engine's schemas rather than left as files nothing reads:

| Source file | Where it is now |
| --- | --- |
| `data/bestiary.yaml` — `ringing_gull` | `data/encounters/coast.yaml` → `ringing_gull_on_the_bar` |
| `data/bestiary.yaml` — `chime_husk` | `data/encounters/coast.yaml` → `chime_husk_on_the_steps`, and `data/encounters/nave.yaml` → `chime_husk_choir` |
| `data/bestiary.yaml` — `tide_cantor` | `data/encounters/nave.yaml` → `the_tide_cantor` |
| `data/bestiary.yaml` — loot ids | `data/items/coast.yaml` (`brass_quill`, `salvaged_brass`, `tuning_fork`) |
| `data/contracts.yaml` — `still_the_carillon` | `data/quests/the_stilling/still_the_carillon.yaml` |
| `data/contracts.yaml` — `carry_the_lamp_oil` | `data/quests/tide_work/carry_the_lamp_oil.yaml` |
| `data/contracts.yaml` — `bounty_tide_cantor` | `data/quests/the_stilling/bounty_tide_cantor.yaml` |
| `knowledge/*.md` | kept verbatim in `knowledge/`; rewritten into the engine's lore format in `data/lore/*.md` |

`data/bestiary.yaml` and `data/contracts.yaml` are kept beside the ported
content as provenance. **This engine does not read them.** It has no
`engine/game/combat.py` and no `ContractBoard`; conflict here is a *scene* of
one to three contested checks (`engine/game/encounter.py`) and commitment is a
quest with engine-evaluable stages (`engine/game/quests.py`). The two files
are the source of the port, not a live content path, and no manifest key
points at them.

## The retarget proof

The source's sharpest idea was that the sympathy "unmaking" mechanic keys off
content rather than code, so a brass sea-chime is unmade by engine that was
written for a brass thing in a birch stand four hundred miles inland. That
survives the port intact, and `tests/test_games.py` asserts it as *outcomes*
rather than as "a loader ran":

- The Tide-Cantor is only reachable on the `sunken_nave <-> choir_loft` legs,
  and only that encounter offers `unmake_it` at the `legendary` band.
- Resolving `unmake_it` well runs through `engine/game/checks.py` against
  **this** game's `data/rules/skills.yaml`, sets `nf_cantor_unmade`, and puts
  a `tuning_fork` in the inventory — an item id that exists in no other game.
- Holding that fork satisfies the final stage of `still_the_carillon`, which
  is a quest predicate evaluated by untouched engine code.
- `stop_your_ears` is offered on **every** encounter in this game and on none
  in the flagship, because `default_approaches` is table content and its gate
  is an item id (`wax_earplugs`) the engine has never heard of.

## Phase names

The engine's evil phases are `dormant`, `stirring`, `spreading`, `consuming`,
and this game's content triggers on those ids. The four marks cut into the
notice-board post — *low water*, *spring tide*, *flood mark*, *full chime* —
are the diegetic names for the same four states. They live in prose
(`data/lore/the_receding_tide.md`) and in `game.yaml`'s `phase_names` block,
which the engine ignores and `GET /api/games` passes through.

## Known gap

`engine/game/procgen.py::_build_forest` hardcodes `forest_clearing` and the
Edgewood ids `deeper_forest` / `old_barrows` / `herb_glen`. Generated forage
nodes and hidden paths therefore hang off places that do not exist on this
coast. Nothing crashes — the ids are simply never matched — but the feature is
inert here until those two lists become content. `forage_resources` and
`barrow_names` are authored in `data/procgen_templates/brass_coast.yaml`
ready for that.
