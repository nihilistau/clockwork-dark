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
| `post` | `governance.post` | `run_post(ctx) -> ctx` | audit a resolved turn |
| `media` | `governance.media` | `run_post(ctx) -> ctx` | media tag fan-out |

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
- **`RulesGovernor`** (post) — runs R001–R005. **This is the call that did not exist.**
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

## 2. World effects — `engine/world/world_effects.py`, `data/rules/doom_effects.yaml`

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

## 3. Challenges — `engine/challenges/`, `data/challenges/`

Multi-step encounters the Storyteller can compose and the engine owns. Kinds:
`skill_gauntlet`, `decision_tree`, `puzzle`, `dice_table`.

**The model proposes; the engine bounds.** `spec.py` is the bounding layer:

- **Difficulty is a band, never a raw DC.** Upstream took an integer `dc` from the
  model. Bands route through `data/rules/skills.yaml`, so there is no number to
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
and ships to the client via `to_client_dict` so the UI can render the step.

---

## 4. Telemetry — `engine/telemetry/oracle.py`

In-memory ring buffer plus running aggregates. `metrics()` reports turns,
violation rate, violations by rule, assistant intervention rate, how often the
companion was **unreliable**, gifts, latency, challenges started, and
`unearned_claims` per stat with counts and max size.

Nothing is persisted — these are numbers about a running process.

---

## Multi-game safety

Both `paths.doom_effects` and `paths.challenges` are declared in **both** game
manifests. An undeclared path falls back to the engine default, which is
Edgewood's table — that would have The Drowned Carillon's flood tide waking a
brass scarecrow in a wheatfield it does not have. The Carillon files are
deliberately empty and say so.

---

## Wiring

| System | Where it is called |
|---|---|
| `RulesGovernor` | `StorytellerAgent.run_turn`, after `tx.commit()`, so it audits the state the player actually ends the turn in. Violations ride out on `StorytellerTurnResult.governance` |
| `build_directives` | one budgeted block in `engine/memory/context.py::build_storyteller_messages`, added beside `lore`. Deliberately **not** the PRE chain — that is R-01 |
| `world_effects.apply_pending_beats` | `engine/game/clock.py::advance_time`, directly after `EvilTicker.advance`. Not a turn handler: the clock also moves for travel, rest, unconsciousness and the background tick, and a doom clock that only advanced on narrated turns would stop for a player who slept through the week |
| `AssistantDirector` | replaces the flat roll in `AssistantAgent.run_turn`. `_check_gift` validates the item against **this game's** registry — the director's fallbacks name Clockwork Dark ids — and downgrades to a hint when it is absent; `_grant_gift` runs only once the companion has actually said something, so an unreachable model cannot leave an unexplained item in the pack |
| cache resets | `engine/games/caches.py` `RELOADERS`, alongside the LM Studio and locations resets |

Guarded by `test_beats_fire_from_the_clock_without_a_turn_handler` and
`test_the_director_matches_the_legacy_roll_on_a_calm_turn`. The first exists
because nothing else in the suite would notice if the clock call were deleted —
a whole content system would simply stop happening.

### NOT WIRED

| System | Needs |
|---|---|
| `Oracle.record_turn` and `/api/metrics` | both in `content/scenes/clockwork/clockwork_scene.py`. `record_unearned_claim` **is** live — `RulesGovernor` calls it on every R003 violation |
| Notice board | not built. The contract catalogue it would serve from exists; the render does not |
| Rolled-d20 stills | faces 6, 8, 11, 16 and 18 do not exist under `static/art/dice/`, and the art manifest maps only a generic `dice_roll` |
