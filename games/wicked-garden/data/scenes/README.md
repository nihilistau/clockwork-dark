# The Wicked Garden — day chapters

Ten files, `day_00_prologue.yaml` … `day_09_finale.yaml`, one per Garden day.
They are the **ribcage** `Design_files/Wicked-Garden/docs/design/scenes/README.md:3`
asks for: authored bone, improvised flesh. Nothing here is dialogue. Sophia is
an agent with her own voice file and the day scripts tell her what the scene
*asks* of her, never what she says.

Source of truth, in order: `Design_files/Wicked-Garden/docs/design/scenes/DAY-*.md`
for the beats, `Design_files/Wicked-Garden/docs/design/agents/state-dictionary.json`
for every id, `games/wicked-garden/state.yaml` for every value and clock.

---

## The shape is a deck

Every file is a **deck** in the exact grammar `engine/content/deck.py` already
parses, the same one `data/rules/decks/thorn_labyrinth.yaml` is written in.
There is no second format and no new loader:

| Key | Meaning |
|-----|---------|
| `id` | Must equal the filename stem. `load_deck` resolves by stem. |
| `draw` | How many **pool** cards the day deals on top of its spine. |
| `cards[].required` | The spine. Dealt in authored order, always, and does not consume a draw slot. |
| `cards[].when` | Pool-card eligibility, in the shared predicate grammar. |
| `cards[].beats[].gate` | A hard threshold (`when:`) and/or a seeded check (`check:`). |
| `cards[].beats[].band` | `favor: +5..12` — engine owns the range, the agent picks inside it. |

A beat that declares neither is a **text beat**: narration, which
`resolve_beat` treats as a pass with no effects. That is a legal and common
thing for a beat to be here, because a lot of a day is atmosphere with a
declared intent and no arithmetic.

### `tags:` carries the resolution contract

`Card.to_dict()` publishes `tags`, so this is the one piece of authored
structure beyond gate/band that actually reaches the narrator. Every card
carries exactly one of:

- **`menu`** — the beats are *alternatives*. The runtime resolves **exactly
  one**, the one the player chose. Calling `resolve_card` on a menu card would
  apply every branch of a decision at once.
- **`sequence`** — the beats are *steps*. Resolve in authored order;
  `resolve_card` is correct.

Other tags are descriptive (`setpiece`, `toll`, `night`, `intimate`, `sophia`,
`gm`) and carry no mechanics.

### Numbers are bounded before you read them

`engine/challenges/spec.py` derives a per-scene ceiling from each value's own
scale, and `deck.py` applies it to every band and every gate branch. For this
story that is:

| Value | Ceiling per beat |
|-------|------------------|
| `favor` `autonomy` `corruption` `knowledge` `desire` | ±17 |
| `equality_seed` | ±2 |
| `ashen_route` `labyrinth_lost`, all four clocks | ±1 |
| `time_debt_mortal_days` | ±10 |

Also: **four effects per outcome branch, maximum** (`spec.MAX_EFFECTS`), and a
flag counts as one. Several design beats list five or six deltas; where that
happened the beat keeps the four that carry its meaning and the rest moved to a
neighbouring beat or were dropped, with a comment saying which.

`ashen_route` is the one that changes how content is written: its ceiling is 1,
so the route cannot jump 0 → 2 in a single beat. It climbs one step per day —
Day 3 hears the offer (1, *aware*), Day 4 bargains (2, *bargained*), Day 5 goes
north (3, *deep winter*) — which is exactly the ladder the state dictionary
describes. That is a happy accident, not a workaround.

---

## Enums are spelled as flags

The state dictionary files `entry_mode`, `labyrinth_result`, `act2_compass`,
`day7_sophia_terms` and `lior_memory_price` as enums, and the engine has a
`track` effect kind and a `track` predicate for exactly that. **A deck beat
cannot write one.** `spec.ALLOWED_EFFECT_TYPES` deliberately excludes `track`
("an ending intent set by a dice table is not a scene, it is a hijack"), so a
`{type: track}` inside a gate branch is dropped before it reaches the
dispatcher.

So the days spell an enum as one flag per value, `<enum>_<value>` —
`entry_mode_guest`, `act2_compass_love_and_door`,
`labyrinth_result_peer_attempt`. `thorn_labyrinth.yaml` already did this and
this follows it rather than inventing a second convention.

**One exception.** `day7_sophia_terms = will_discuss_leave` is written as
`sophia_will_discuss_leave`, because E1a's gate in `data/rules/endings.yaml`
already reads that name and the existing gates are not being changed. The other
four values of that enum use the ordinary `day7_sophia_terms_*` spelling.

`ending_intent` and `ending_locked` are **not** written here at all. They are
the engine's, through `endings.set_intent` and `endings.lock`, which refuse an
ineligible id — the honesty rule Day 8 exists to enforce. Day 8's mirror card
and Day 9's point-of-no-return card set `ending_sworn` and gate on
`{ending: {eligible: ...}}` / `{ending: {locked: ...}}`; the write itself is a
tool call, not an effect.

---

## Wiring

Four things in this list were unwired when these files were authored. All four
are wired now, and they are recorded here rather than deleted because each was a
different way for authored content to be invisible.

1. **This directory is what `paths.decks` names.** It briefly was not:
   `game.yaml` pointed at `data/rules/decks`, so these ten files parsed,
   validated, and were dealt by nothing. The labyrinth's chamber deck moved in
   beside them rather than teaching `load_deck` to take a list of directories —
   to this engine a day chapter and a chamber deck are the same kind of thing.
   `tests/test_structural_systems.py` now reads the path from the manifest
   instead of repeating it, which is what let the drift go unnoticed.
2. **`menu` and `sequence` are honoured.** `deck.chosen_beats()` resolves
   exactly one beat on a `menu` card — the one the player picked — and all of
   them in order on a `sequence` card. Without it, Day 1's first morning applied
   every branch at once: the player both looked at their mortal home and refused
   to. With no choice supplied the first beat is taken and the fallback is
   logged, because a scene that resolves nothing leaves no trace to notice.
3. **The finale beats** in `data/rules/endings.yaml` (Speak · Act · Seal, per
   `DAY-09-FINALE.md:102`) now come through `endings.declared()`. It built its
   flattened view from a fixed key list and dropped them, so a renderer had to
   re-read the raw table — two readers of one file, free to disagree about it.
4. **Epilogues** load through `paths.epilogues` and `engine/game/epilogue.py`,
   which joins the index to the prose, substitutes the time line from state, and
   appends the hollow clause past the declared debt threshold.

## What is still not wired

Stated plainly, per CLAUDE.md rule 9.

1. **No screen draws an epilogue.** The engine produces a fully substituted
   `Epilogue`; the client has no component that renders one.
2. **Nothing calls the plan → negotiate → commit pipeline.** `engine/agents/`
   ships `plan.py`, `negotiate.py`, `knowledge.py` and `roster.py`, all tested;
   the live turn still runs the single-agent path.
3. **Six of the fourteen locations have no art plate**, including the entry
   `mortal_threshold`, so the opening screen draws a procedural placeholder.
   The generation prompts exist in `data/art/subjects.yaml`.
