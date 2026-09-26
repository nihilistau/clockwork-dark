# Governance, World Effects, Challenges, Telemetry

Four systems ported and reworked from the older sibling repo
(`nihilistau/the-clockwork-dark`, v0.9). This describes what they do, what is
wired, and — per AGENTS.md rule 9 — what is **NOT WIRED**.

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

It delegates here. There is one implementation, one ordering rule, and one
failure policy.

A MEDIA phase existed too, and was deleted in v0.8.0 rather than wired. It
replaced a bypass in `engine/media/interceptors.py` -- three interceptor classes
declared with priorities, then ignored -- and was then bypassed in turn: the
turn has always called `MediaPipeline.process_storyteller_turn` directly. Two
layers of hooks, neither called, and no story declared `governance.media`.

### Phases

| Phase | Config key | Signature | Purpose |
|---|---|---|---|
| `pre` | `comms.interceptors` | `run_pre(state, prompt, *, player_action) -> str` | legacy prompt chain (lore inject, awareness gate) |
| `directive` | `governance.directives` | same | GM prompt shaping, built as **one** block |
| `commit` | `governance.commit` | `run_commit(ctx) -> ctx` | review the negotiated turn **before** the transaction commits; the only chain with veto authority |
| `post` | `governance.post` | `run_post(ctx) -> ctx` | audit a resolved turn |

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

A set-piece may also carry `requires:` -- any condition in the shared grammar
(`engine/challenges/set_pieces.py::is_available`, via
`quests.evaluate_condition`), AND-ed with the flag and location gates. It is
how a gate asks something no flag records: a break-out gated `{in_custody:
true}` is offered only in the cell (the worked example in AUTHORING §3.11 and
`tests/test_custody_predicate.py`; HUE & CRY's own jailbreak is v0.17.0
content, not shipped). Checked
at load through `quests.condition_problem`: an unknown predicate, a sibling
beside `all`/`any`/`none`, or one the gate cannot answer (`disposition`,
`days_in_stage`, `days_since_started` -- no ledger, no quest) logs and skips
the piece. An authored set-piece's challenge may use `release`,
`quash_reports` and `report` (v0.15, the structural set a squeeze's `on_break`
files through) and no other Law kind.

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
| `run_commit` | `engine/agents/pipeline.py::_govern_commit`, over the negotiated turn, before the `StateTransaction` applies its effects. The chain ships empty (`_DEFAULT_CHAINS` in `engine/agents/governance.py`); a story gets a pre-commit hook only by naming one |
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
(rows above); the notice board — server half at `GET /api/notices`, client
half at `ui/src/stories/clockwork-dark/screens/Notices.jsx` (overlay `n`);
the challenge/scene framing chip (`ui/src/core/parts/BeatFrame.jsx`);
the negotiation panel (`ui/src/core/parts/NegotiationPanel.jsx`, rendered by
`Play.jsx` and silent unless a pipeline ran);
the rolled-d20 stills — all 20 plates and all
20 interface faces exist and are mapped in `games/clockwork-dark/data/art/manifest.yaml`
(`dice_plates` / `dice_faces`), held by `tests/test_dice_art.py`;
and premise security (stage/band/bypass) — `engine/world/jobs.py`'s `entry`
and `inside` stages read a feature's `known_shift` once casing found it, its
`shift` otherwise, and an `obstacle: true` feature blocks the `inside` stage
in its own right, exactly the wiring this row once asked for (v0.11.0).

### NOT WIRED

| System | File | Needs |
|---|---|---|
| Challenge / scene panel | producers: `to_client_dict` ships `challenge` and `scene`. Consumer: `ui/src/core/parts/BeatFrame.jsx` draws the "Step 2 of 4" / "Card 3 of 7" line | A full panel (options, progress, card art) is still unbuilt. The framing chip is enough that a gauntlet no longer reads as four unrelated turns; options remain ordinary choice chips. |
| Governance panel | producer: `engine/scenes/default_state.py` ships `governance` on the turn payload. Consumer: nothing | An analyst-mode panel over the R001–R005 breaches. Debug-shaped rather than player-shaped, which is why it is last. Its sibling `negotiation` row left this table in v0.6.0 — and splitting them is the lesson: the row read "the player has no way to know a second agent won, lost or gave something up", and the answer to *that* was never a table. The player learns it from the prose, because `narration_block` now hands the narrator what was yielded and why; the panel is only the author's tuning surface. |
| Probabilistic declared world events | `engine/world/schedules.py::declared_events_due` | A story's `events:` block fires on `on_day`, `every_days` or a `when:` predicate -- all deterministic, from `advance_time`'s day roll (v0.8.0). A `probability:` key is not read. Wiring it needs a named `world_rng` stream per event and a decision about whether the roll happens on the day roll (replayable) or the background tick (the flagship's three hardcoded events, which are wall-clock). |
| Companion posture on a concession | producer: `negotiation.resolutions` names the agent that yielded, by roster id. Consumer: nothing, and it cannot be built as things stand | `assistant_presence` (`engine/scenes/default_state.py`) ships no agent id, so the client cannot tell whether the agent that gave way IS the companion in its column. Deliberately not guessed at in v0.6.0. Wiring it means threading the roster id onto the presence payload; the log's margin mark carries the "this turn was contested" signal until then. |
| Wanted-poster UI chrome | producer: `engine/game/state.py::to_client_dict` ships `law` (`guise_label`, `wanted` by jurisdiction label, `custody`, `clarity` -- the one word for how good a likeness the watch holds of the face worn here) when a story declares `paths.law`. Consumer: nothing | The payload exists and is real -- the narrator's `law_block` (`engine/agents/prompts.py`) already speaks the same facts in prose. Nothing in `ui/src` renders a wanted band, a guise chip, a clarity word or a custody panel from it. Reader: `hue-and-cry` (v0.21.0, the UI/UX overhaul), whose generic engine panels are where this was always meant to land. |
| An `npc_present` condition predicate | `engine/game/quests.py::_PREDICATES` (the shared condition grammar `threads.yaml`'s `requires` and `discharge_requires` also read, v0.10.0) | A thread's `requires` can gate on `at_location` but not on who else is standing there. `brask_bribe` (`games/hue-and-cry/data/rules/threads.yaml`) gates its `requires` on `at_location: lantern_house` and on something being `filed` in the Wick (v0.15.0), so it can be struck at his desk whether or not Brask himself is in. The four squeezes and the fences' credit (`pell_advance`, `marrow_slate`, v0.15.0) gate on `at_location` plus the `hour_between` their person's schedule has them there, awake -- the nearest proxy the grammar has, which an event moving that person would not close. Wiring it needs a predicate that reads the same presence roster the turn's own NPC block builds from. |
| `arrest.approaches` in a law file | `engine/world/law.py::load_spec` keeps `arrest["approaches"]`; nothing reads it | docs/AUTHORING.md §3.11 once described it as "the story's own default set of exits" merged into the arrest scene. No merge exists: the arrest encounter's exits come from its own encounter file only, and HUE & CRY's `watch_stop` declares all of them there. Wiring it means merging the block under the scene's own `approaches` in `encounter` when the scene opened is `arrest.encounter`, with the scene's own keys winning. |
| Job panel UI | producer: `engine/game/state.py::to_client_dict` ships `job` (`active`: `premise_name`, `stage_label`, `stages`, `at`, `alarm`, or `None` between jobs; plus a stable top-level `prep`, earned by casing whether or not a job is open) when a story declares `paths.jobs`. Consumer: nothing | The payload exists and is real -- the narrator's `job_block` (`engine/agents/prompts.py`) already speaks the same facts in prose: the house, the stage, the obstacle, what is moving the odds, which flashback paid off, the alarm. Nothing in `ui/src` renders stages, alarm or prep from it. Reader: `hue-and-cry` (v0.21.0, the UI/UX overhaul), whose generic engine panels are where this was always meant to land, same as the Law's wanted-poster chrome above. |
| Hired hands | spec §4 (docs/superpowers/specs/2026-09-23-hue-and-cry-design.md) | Explicitly optional there; not built. A job is walked solo, start to getaway. |
| Agenda moves posted on the notice board | `engine/scenes/default_api.py::notice_board` | Spec §5 lists "posted on the notice board" as one way the player learns of a move. The board serves labour only. An agenda move reaches the prose as a private sign where it was left (`prompts.agenda_block`) or as a public trace in the moved journal, and nowhere else. Wiring it needs a `trace.board: true` (or similar) that the board reads alongside its labour rows, masked through `agendas.mask_text` like every other piece of agenda text. |
| A `fence {most: hot_goods}` selector | `engine/world/agendas.py::_fence_candidates`, `SELECTOR_KEYS` | Spec §5 names it. Fences hold no stock (`engine/game/trade.py`), so there is nothing to count. The `fence` selector accepts `district` only, and any other key is a load error. |
| `disposition` and quest-progress predicates in agenda conditions | `engine/world/agendas.py::LEDGER_PREDICATES`, `PROGRESS_PREDICATES` | The agendas pass runs inside `advance_time`, which holds no StoryLedger and evaluates no quest. `disposition`, `days_in_stage` and `days_since_started` would be false there forever, so each is refused at load (naming the file) rather than left inert. Wiring them needs a ledger and quest progress in the pass's scope. |
| The static spoiler table's narration half | `engine/lore/interceptors.py::AwarenessGateInterceptor.run_post` | Only `tests/test_awareness_gate.py` calls it. The governance POST chain holds `RulesGovernor` alone, and `engine/agents/storyteller.py::run_turn` never gates the final narration. So a story's `spoilers.yaml` masks prompt regions wrapped in `mark_spoiler`, and not what the model writes. Streamed deltas (`on_delta`) would also reach the client before any post-mask. Wiring it needs a call after the retry loop, plus a decision on the stream: a hold-back buffer, or the authoritative `turn_update` replacing the streamed text. Agenda masking does not depend on it, because the narrator is never told a role's NPC until the player has earned it. |

### Deliberately deferred -- the Law (v0.10.0)

Behaviour that is wired and measured, left as it is on purpose, and written
down so nobody mistakes it for an oversight.

| Behaviour | File | Why it stays, and what it costs |
|---|---|---|
| An arrest charges only the file of the jurisdiction the player was stopped in | `engine/world/law.py::sentence_for`, the `arrest` effect in `engine/game/effects.py` | Custody is laid by the watch that made the stop, and the gaol may stand in another district. Paying or serving discharges only those charged deeds, so a prisoner released at the gaol can still be wanted by the gaol's OWN district and be stopped again in the lobby. Recorded rather than changed (release ruling, 2026-09-24). |
| Talk is capped at 48 in-game hours per `advance_time` call | `engine/world/law.py::MAX_PROPAGATION_HOURS` | `propagate` is cut-invariant only for calls of 48 hours or less: one 72h call talks for 48 hours, three 24h calls for all 72. No shipped caller moves the clock more than 24 hours at once (rest, a served day -- sentences are served meal by meal -- a world tick is capped at `world.tick_max_hours`), so nothing reaches the cap today. A future caller that does should step the clock in days. |

Re-audited in full on 2026-08-15 against the tree, not against this file. The
2026-08-14 pass claimed one surviving row and was **wrong**: challenges were
documented above as a live system while `set_pieces.start` had no caller in
`engine/` at all, which is the failure mode a NOT WIRED table exists to
prevent — debt nobody wrote a row for is invisible, because there is no marker
to grep. `tests/test_reachability.py` is the machine-checked answer to that:
it walks the engine's own call graph and fails on a subsystem with no
production caller, so this table can no longer be the only thing standing
between an unwired system and a reader who believes the docs.

Version: v0.5.2 [2026-09-25]
