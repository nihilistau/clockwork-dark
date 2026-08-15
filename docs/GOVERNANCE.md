# Governance, World Effects, Challenges, Telemetry

Four systems ported and reworked from the older sibling repo
(`nihilistau/the-clockwork-dark`, v0.9). This describes what they do, what is
wired, and — per CLAUDE.md rule 9 — what is **NOT WIRED**.

Authority reminder: the code wins. If this file disagrees with the modules, the
modules are right and this file is stale.

---

## 1. Governance pipeline — `engine/agents/governance.py`

One priority-ordered interceptor registry around an agent turn.

### The problem it solves

`engine/mcp/scene_rules_engine.py` implements R001–R005 and, until now, **nothing
called it**. The rules were documentation of an intent, not an enforced property.

Meanwhile the dispatch logic that should have called it existed twice:

| Chain | Location | What it did |
|---|---|---|
| PRE | `engine/lore/interceptors.py::run_pre_interceptors` | built a chain from `comms.interceptors`, sorted by priority, threaded a prompt through |
| MEDIA | `engine/media/interceptors.py::run_media_interceptors` | declared three interceptor classes with priorities, then **ignored all three** and called `MediaPipeline.process_tags` directly |

Both now delegate here. There is one implementation, one ordering rule, and one
failure policy.

### Phases

| Phase | Config key | Signature | Purpose |
|---|---|---|---|
| `pre` | `comms.interceptors` | `run_pre(state, prompt, *, player_action) -> str` | legacy prompt chain (lore inject, awareness gate) |
| `directive` | `governance.directives` | same | GM prompt shaping, built as **one** block |
| `commit` | `governance.commit` | `run_commit(ctx) -> ctx` | review the negotiated turn **before** the transaction commits; the only chain with veto authority |
| `post` | `governance.post` | `run_post(ctx) -> ctx` | audit a resolved turn |
| `media` | `governance.media` | `run_post(ctx) -> ctx` | media tag fan-out |

`commit` is called from `engine/agents/pipeline.py::_govern_commit`, ahead of
the `StateTransaction` that applies the accepted effects. `governance.commit`
is on the manifest `SETTING_ALLOWLIST` (`engine/games/manifest.py`), so a story
declares its own chain in `game.yaml`. Covered by
`tests/test_governance_commit.py`.

An interceptor that raises is logged and skipped. A hook that shapes a prompt or
records a metric must never take down the turn it was observing.

### Why `directive` is separate from `pre`

The obvious wiring — run the PRE chain over the assembled prompt — is issue
**R-01**. `StorytellerAgent._build_messages` documents it: that loop visits every
system message and runs *after* `build_storyteller_messages` fitted the prompt to
the token budget, so each shaper's block is appended once per system block and
none of the copies are counted. Measured at 7,550 tokens against a 6,198 budget.

So `build_directives(state)` starts from an **empty** string and returns a single
block. The caller inserts it into the budget like any other block.

### Built-in governors

- **`EvilPhaseTone`** (directive) — biases tone to the evil phase without naming it.
- **`DoomSignsInterceptor`** (directive) — surfaces what the Dark has actually
  done, read from the world-event ledger, so narration cannot drift from state.
- **`StorytellerMind`** (directive) — turns the agency knobs into GM directives.
- **`RulesGovernor`** (post) — runs R001–R005. **This is the call that did not
  exist** — `SceneRulesEngine` had a passing test suite and no caller for five
  PRs; this governor, run from `StorytellerAgent.run_turn` after `tx.commit()`,
  is what made it production code.
- **`MediaGovernor`** (media) — replaces the bypass described above.

### R003 and the telemetry that motivated it

R001/R004/R005 are defence in depth; the engine's own writers already maintain
them, so a violation means something bypassed a writer.

R003 is different in kind. When a model emits `"stat_changes": {"gold": 50}`,
the engine drops it — stats only move through `@skill` tools. Nothing breaks and
nothing is visible. That silence is the bug: a model claiming fifty gold on one
turn in three is a **prompt defect**, and the only way to know is to count it.
R003 records the claim as a `warning` violation and increments
`Oracle.record_unearned_claim`.

### Two hazards deliberately avoided from the upstream version

1. **Upstream validated the player's location against `CANONICAL_LOCATION_IDS`** —
   the five canon ids. `engine/game/procgen.py` generates real, reachable places
   (`deeper_forest`, `old_barrows`, `herb_glen`) that are legal and not canon, so
   that check would flag a violation on every turn spent foraging. Ours validates
   against the full graph via `SceneRulesEngine.validate_location`.
2. **`LOCATION_IDS` is a frozenset that a game swap *rebinds*.** `engine/games/caches.py`
   refreshes the copy held inside `scene_rules_engine`. The governor reads it
   *through the rules engine*; a `from ... import` here would reintroduce the
   stale-map bug in a second game. Covered by
   `test_r001_reads_the_location_set_through_the_rules_engine`.

---

## 2. World effects — `engine/world/world_effects.py`, `games/clockwork-dark/data/rules/doom_effects.yaml`

`evil_progress` used to be a number that went up and changed adjectives. A player
at 0.85 walked into the same square and met the same five villagers standing in
the same places.

A **beat** now changes the world when progress crosses its `at_progress`
threshold. Every effect lands on a `GameState` field that already exists, so it
serialises through `to_save_dict` with no migration:

| Effect | Lands on |
|---|---|
| `set_flags` | `state.flags` (via `effects.apply_effect`, the one validated writer) |
| `discoveries` | `state.flags["discovery_<key>"]` |
| `rumors` | `state.rumors`, deduped |
| `world_events` | `state.world_events` |
| `npc_moves` | `state.procgen.npcs[].location_id` — the village visibly empties |

Beats are idempotent: each sets `doom_beat_<id>` and is skipped forever after.
Idempotency is owned here, not by the caller.

### Two interop facts that shaped the schema

1. **`WorldSim.expire_events` deletes any world event with no `expires_day`**, on
   the next day tick. A straight port of the upstream schema wrote doom marks
   without one, so every permanent mark would have vanished within a day and
   `DoomSignsInterceptor` would narrate an empty world. Marks carry
   `PERMANENT_HORIZON_DAY`.
2. Our world events key on `event_id`, not `id`.

`npc_moves` destinations are validated against the live location graph. An
unvalidated move does not error — the NPC occupies an id `npcs_at` never returns,
so they are silently deleted from the world.

---

## 3. Challenges — `engine/challenges/`, `games/clockwork-dark/data/challenges/`

Multi-step encounters the Storyteller can compose and the engine owns. Kinds:
`skill_gauntlet`, `decision_tree`, `puzzle`, `dice_table`.

> **Reachable since 2026-08-15, and this section previously described a system
> no player could enter.** `set_pieces.start` / `resolve` / `available` had no
> caller anywhere in `engine/` — only `scripts/simulate.py` and the tests — so
> the flagship's two authored set-pieces, and the two `doom_resistance` grants
> that live on them, could not be reached by playing. There was also no
> challenge SKILL at all, so the gap was deeper than a missing choice.
>
> Two intent verbs close it (`engine/game/intents.py`): `set_piece` starts one
> from `available()`, and `challenge` advances the running one, suppressing
> every other verb while it is open — the same rule an encounter follows. A
> puzzle is the one verb whose target cannot be an enum, because its input is
> the player's own words; `intent_schema` already omits the enum for a verb
> with no options, so that needed no special case. `runner.present()` is new:
> a challenge that has already started still has to be renderable, or a player
> who saved mid-gauntlet reloads into a step nothing can draw.
>
> `resolve_challenge` calls `set_pieces.resolve`, **not** `runner.resolve` —
> only the former grants the terminal flag, and a gauntlet won without its flag
> is a gauntlet the player gets to win again. Held by
> `tests/test_wired_verbs.py` and `tests/test_reachability.py`.

**The model proposes; the engine bounds.** `spec.py` is the bounding layer:

- **Difficulty is a band, never a raw DC.** Upstream took an integer `dc` from the
  model. Bands route through `games/clockwork-dark/data/rules/skills.yaml`, so there is no number to
  inflate and difficulty stays reviewable in one place.
- **Rewards are clamped per effect and capped in count** (`EFFECT_CEILINGS`,
  `MAX_EFFECTS`, `MAX_ITEM_QTY`). Gold caps at 25. Upstream had no ceiling at all.
- **Disallowed effect types are dropped** — notably `ledger_fact`, which would let
  a challenge write itself into memory as established truth.
- **Size is capped** — steps, nodes, options, outcomes, text length, because a
  spec lands in `GameState` and is paid for in every save write forever.
- **Dead-end nodes are repaired into terminals** — a node you can enter and never
  leave is the location-graph bug again.

Clamping is preferred to rejection: refusing a challenge hands narration of the
outcome back to the model unrolled, which is what the two-phase turn loop exists
to prevent.

`runner.py` resolves through `checks.resolve` and `effects.apply_effects`, so
wounds, hunger, timed effects, archetype modifiers, advantage and the boon tables
all apply inside a challenge exactly as they do everywhere else. Rolls draw from
the `CHALLENGE` RNG stream, so composing one cannot shift the encounter around it.

### Set-pieces

A set-piece is a stored challenge behind a flag gate, which makes the doom clock
a loop rather than a counter:

```
doom beat -> sets a flag -> unlocks a set-piece -> grants a terminal flag
```

`scarecrow_wakes` fires at 0.30 and sets `scarecrow_awake`; that flag makes
`brass_scarecrow` available in `edgewood_square`; completing it sets
`set_piece_brass_scarecrow_done`, which forbids it forever. Every link is a flag
on `GameState`, so the whole loop persists through a save.

Authored specs go through the same validator as model-composed ones — a YAML file
is not more trustworthy than a model, just wrong less often.

### Storage

`GameState.challenge` (new field). A challenge survives a reload mid-gauntlet,
and ships to the client via `to_client_dict`.

**On the claim that "the UI can render the step":** no component reads
`state.challenge`, and that was true when this line was written too. It matters
less than it sounds, because the challenge's options now arrive as ordinary
choice chips through `legal_intents` — so the step IS playable and IS visible,
just as choices rather than as a bespoke panel. A dedicated panel would read
better and remains unbuilt; it is in the NOT WIRED table below rather than
implied by this sentence.

---

## 4. Telemetry — `engine/telemetry/oracle.py`

In-memory ring buffer plus running aggregates. `metrics()` reports turns,
violation rate, violations by rule, assistant intervention rate, how often the
companion was **unreliable**, gifts, latency, challenges started, and
`unearned_claims` per stat with counts and max size.

Nothing is persisted — these are numbers about a running process.

---

## Multi-game safety

An undeclared `paths.*` key resolves to **nothing**, and every loader treats
that as "this story ships none of this" — an empty table, no index, no rules.

It did not always. `config/default.yaml` used to name The Clockwork Dark's own
files as the default for 23 content keys, so a story that forgot `doom_effects`
got Edgewood's table: a brass scarecrow waking in a wheatfield the story does
not have. Nothing announced it. Measured before the fix, The Wicked Garden was
reading Edgewood's quests, prices and encounters.

Every path key in `config/default.yaml` is empty now except `saves`, which is an
output directory the engine owns rather than any story's content. A story
declares what it reads, and a story that declares nothing reads nothing.

`scripts/doctor.py`'s **Story paths** section reports any story still resolving
into another story's tree.

---

## Wiring

| System | Where it is called |
|---|---|
| `RulesGovernor` | `StorytellerAgent.run_turn`, after `tx.commit()`, so it audits the state the player actually ends the turn in. Violations ride out on `StorytellerTurnResult.governance` |
| `run_commit` | `engine/agents/pipeline.py::_govern_commit`, over the negotiated turn, before the `StateTransaction` applies its effects. `SafetyCeiling` is the shipped occupant of the chain |
| `Oracle.record_turn` | `engine/scenes/default_state.py`, after the turn resolves; served by `GET /api/metrics` (`engine/api/metrics.py`) |
| `build_directives` | one budgeted block in `engine/memory/context.py::build_storyteller_messages`, added beside `lore`. Deliberately **not** the PRE chain — that is R-01 |
| `world_effects.apply_pending_beats` | `engine/game/clock.py::advance_time`, directly after `EvilTicker.advance`. Not a turn handler: the clock also moves for travel, rest, unconsciousness and the background tick, and a doom clock that only advanced on narrated turns would stop for a player who slept through the week |
| `AssistantDirector` | replaces the flat roll in `AssistantAgent.run_turn`. `_check_gift` validates the item against **this game's** registry — the director's fallbacks name Clockwork Dark ids — and downgrades to a hint when it is absent; `_grant_gift` runs only once the companion has actually said something, so an unreachable model cannot leave an unexplained item in the pack |
| cache resets | `engine/games/caches.py` `RELOADERS`, alongside the LM Studio and locations resets |

Guarded by `test_beats_fire_from_the_clock_without_a_turn_handler` and
`test_the_director_matches_the_legacy_roll_on_a_calm_turn`. The first exists
because nothing else in the suite would notice if the clock call were deleted —
a whole content system would simply stop happening.

Formerly in this table, now wired: `Oracle.record_turn` and `/api/metrics`
(rows above); the notice board's server half —
`engine/scenes/default_api.py::notice_board`, served at
`GET /api/notices` from `engine/game/economy.py`'s snapshot,
`tests/test_notice_board.py`; and the rolled-d20 stills — all 20 plates and all
20 interface faces exist and are mapped in `games/clockwork-dark/data/art/manifest.yaml`
(`dice_plates` / `dice_faces`), held by `tests/test_dice_art.py`.

### NOT WIRED

| System | File | Needs |
|---|---|---|
| Notice board render | server half: `engine/scenes/default_api.py::notice_board` (wired, `GET /api/notices`). Client half: nothing | The browser side. Re-checked 2026-08-14: `grep -rn notices ui/src/` returns no fetch, no component and no overlay entry in any of the three plugins, so the route is reachable by curl and by no player. It is a story-shaped screen rather than a core one — the board is the flagship's — so it belongs in `ui/src/stories/clockwork-dark/` as an overlay entry, not in `ui/src/core/`. |
| Challenge panel | producer: `engine/game/state.py::to_client_dict` ships `challenge`. Consumer: nothing in `ui/src/` | A component reading `state.challenge` to draw the step, its progress and its options as a panel. **Not a playability gap** — since 2026-08-15 the options arrive as ordinary choice chips through `legal_intents`, so a gauntlet can be played start to finish without this. It is a presentation gap: a four-step gauntlet reads as four unrelated turns. |
| Scene panel | producer: `to_client_dict` ships `scene`. Consumer: nothing in `ui/src/` | Same shape and same non-blocking status as the row above, for the dealt card (`engine/content/director.py`). The card's prose reaches the player through the narrator, which is the design; what is missing is the "card 3 of 7" framing. |
| Negotiation / governance panels | producers: `engine/scenes/default_state.py` ships `negotiation` and `governance` on the turn payload. Consumers: nothing | An analyst-mode panel. `negotiation` carries lead, beats, resolutions and refusals for the three stories that run a pipeline, and the player currently has no way to know a second agent won, lost or gave something up. `governance` carries R001–R005 breaches. Both are debug-shaped rather than player-shaped, which is why they are last. |

Re-audited in full on 2026-08-15 against the tree, not against this file. The
2026-08-14 pass claimed one surviving row and was **wrong**: challenges were
documented above as a live system while `set_pieces.start` had no caller in
`engine/` at all, which is the failure mode a NOT WIRED table exists to
prevent — debt nobody wrote a row for is invisible, because there is no marker
to grep. `tests/test_reachability.py` is the machine-checked answer to that:
it walks the engine's own call graph and fails on a subsystem with no
production caller, so this table can no longer be the only thing standing
between an unwired system and a reader who believes the docs.

Version: v0.4.0 [2026-08-15]
