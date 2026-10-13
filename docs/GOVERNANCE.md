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
`tests/test_custody_predicate.py`; HUE & CRY's own jailbreak, since v0.17,
is `games/hue-and-cry/data/challenges/lantern_house.yaml`). Checked
at load through `quests.condition_problem`: an unknown predicate, a sibling
beside `all`/`any`/`none`, or one the gate cannot answer (`disposition`,
`days_in_stage`, `days_since_started` -- no ledger, no quest) logs and skips
the piece. An authored set-piece's challenge may use `release`,
`quash_reports` and `report` (v0.15, the structural set a squeeze's `on_break`
files through) and no other Law kind.

Authored specs go through the same validator as model-composed ones — a YAML file
is not more trustworthy than a model, just wrong less often.

Since v0.17 the content validator reads them too
(`engine/games/validation.py::check_set_pieces`, rules in
`set_pieces.set_piece_problems`), so doctor and `validate_content` report a
piece at a place the graph lacks, a malformed flag gate, a challenge the spec
rejects, an effect no set-piece may apply, or a `release` outside a challenge's
success outcome. The runtime loader is unchanged: it still keeps what it
always kept, and the validator is what says so.

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
the negotiation panel (`ui/src/core/panels/NegotiationPanel.jsx`, drawn in
the play screen's shelf region and silent unless a pipeline ran);
the rolled-d20 stills — all 20 plates and all
20 interface faces exist and are mapped in `games/clockwork-dark/data/art/manifest.yaml`
(`dice_plates` / `dice_faces`), held by `tests/test_dice_art.py`;
telling a released hosted tab why (v0.21.0, spec §6.5) -- `SessionStore._release` passes a reason to `on_release`, and hosted mode's hook (`engine/hosting/__init__.py::install_sessions`) emits `session_ended {"reason", "session_id"}` to the run's room before closing it: `elsewhere` (one live run per account: opened in another window, "Play here"), `ended` (an admin's end) and `idle` (the idle sweep), both "Resume" (`ui/src/core/link.js`, transitions 29-32), which is what the rows "Telling a released tab that its run opened elsewhere" and the admin-end half of "Telling a player that an admin ended their session" once asked for;
and premise security (stage/band/bypass) — `engine/world/jobs.py`'s `entry`
and `inside` stages read a feature's `known_shift` once casing found it, its
`shift` otherwise, and an `obstacle: true` feature blocks the `inside` stage
in its own right, exactly the wiring this row once asked for (v0.11.0);
and resuming an interrupted sentence (v0.17 T4) -- `law.serve_sentence`
counts every step it serves on the custody record through the
`custody_served` effect (`custody["served_hours"]`), and a second `serve`
after a scene stopped the first waits out only the rest, exactly the
served-hours field this row once asked for. Wired before it was reachable
in a shipped story: HUE & CRY's one interrupting deck, the gallows, still
ends the story, and its jailbreak takes no time, so it stops no sentence
either.

### NOT WIRED

| System | File | Needs |
|---|---|---|
| Challenge / scene panel | producers: `to_client_dict` ships `challenge` and `scene`. Consumer: `ui/src/core/parts/BeatFrame.jsx` draws the "Step 2 of 4" / "Card 3 of 7" line | A full panel (options, progress, card art) is still unbuilt. The framing chip is enough that a gauntlet no longer reads as four unrelated turns; options remain ordinary choice chips. |
| Governance panel | producer: `engine/scenes/default_state.py` ships `governance` on the turn payload. Consumer: nothing | An analyst-mode panel over the R001–R005 breaches. Debug-shaped rather than player-shaped, which is why it is last. Its sibling `negotiation` row left this table in v0.6.0 — and splitting them is the lesson: the row read "the player has no way to know a second agent won, lost or gave something up", and the answer to *that* was never a table. The player learns it from the prose, because `narration_block` now hands the narrator what was yielded and why; the panel is only the author's tuning surface. |
| Probabilistic declared world events | `engine/world/schedules.py::declared_events_due` | A story's `events:` block fires on `on_day`, `every_days` or a `when:` predicate -- all deterministic, from `advance_time`'s day roll (v0.8.0). A `probability:` key is not read. Wiring it needs a named `world_rng` stream per event and a decision about whether the roll happens on the day roll (replayable) or the background tick (the flagship's three hardcoded events, which are wall-clock). |
| Companion posture on a concession | producer: `negotiation.resolutions` names the agent that yielded, by roster id. Consumer: nothing, and it cannot be built as things stand | `assistant_presence` (`engine/scenes/default_state.py`) ships no agent id, so the client cannot tell whether the agent that gave way IS the companion in its column. Deliberately not guessed at in v0.6.0. Wiring it means threading the roster id onto the presence payload; the log's margin mark carries the "this turn was contested" signal until then. |
| The companion in the people strip | `ui/src/core/panels/PeopleStrip.jsx`; `engine/scenes/default_state.py::assistant_presence` | The payload's `assistant` block carries the character's portrait (`portrait_url(_character_agent_id())`, `pip` for HUE & CRY) but no display name, so the strip cannot label a card for the companion, and `GET /api/people` lists the place's NPCs, not the companion. Pip speaks inside the prose (the pipeline), which is where he lives until a story needs him on screen. |
| Which jurisdiction the player is standing in, on the poster | `engine/game/state.py::_law_block` | `clarity` is the watch HERE, but the block does not say which `wanted` row is here, so the poster (`ui/src/core/panels/WantedPoster.jsx`) cannot highlight it; adding it is a payload change outside S3. |
| Words on the core panels for a story with another register | `ui/src/core/panels/` | Core's panels print a few words of their own -- "Wanted", "Held", "A fine of", "Casing", "Prep" -- and every other word is the payload's. A story whose register wants other words for them (a different name for the poster, say) has no way to say so: a plugin can only decline the panel with `ui.panels` and draw its own. |
| The flagship's and NEON CITY's encounter LOOK | `ui/src/stories/clockwork-dark/parts/EncounterPanel.jsx`; `ui/src/stories/neon-city/parts/Stage.jsx` | v0.21.0 (spec §2.3) fixed how their approach buttons resolve (rule 1: each presses the narrator's intent-bearing choice) and added only the words "not offered this turn" to an unmatched one. How an unmatched approach looks, and their layout, are theirs to restyle in their overhauls (v0.25.0, v0.27.0); so are digit keys on their approaches (core's panel binds 1-9 when it holds the only moves, theirs bind none, as before v0.21.0). |
| The prose of a turn that finished while the server was RESTARTED | `ui/src/core/App.jsx` (the connection, `ui/src/core/link.js`: rejoin, then resume on the join's exact miss) | v0.21.0's reconnect recovers a turn that finished while the socket was down from the session's `last_turn` (the rejoin, spec §6.6). A server RESTART loses the session itself: the join misses, the page resumes the save, and the resume's canned opening line stands where that turn's prose was. The turn's effects are in the save (every turn autosaves); its prose is not, and nothing the save holds can give it back. |
| A story switched in another tab, then a reconnect | `ui/src/core/App.jsx` (spec §6.3 transition 18, `ui/src/core/link.js`); `engine/hosting/frontdoor/stories.py` (the one story choice per browser) | Beside "Two stories open in two tabs of one browser at once": after a story switch in another tab, this tab's reconnect reaches the OTHER story's worker, its join misses, and the resume names a save from the story it left. That answers `resume_failed`, whose message now reaches the start screen (v0.21.0). Nothing is lost; the player picks the story they want and loads the run from the menu. |
| An `npc_present` condition predicate | `engine/game/quests.py::_PREDICATES` (the shared condition grammar `threads.yaml`'s `requires` and `discharge_requires` also read, v0.10.0) | A thread's `requires` can gate on `at_location` but not on who else is standing there. `brask_bribe` (`games/hue-and-cry/data/rules/threads.yaml`) gates its `requires` on `at_location: lantern_house` and on something being `filed` in the Wick (v0.15.0), so it can be struck at his desk whether or not Brask himself is in. The four squeezes and the fences' credit (`pell_advance`, `marrow_slate`, v0.15.0) gate on `at_location` plus the `hour_between` their person's schedule has them there, awake -- the nearest proxy the grammar has, which an event moving that person would not close. Wiring it needs a predicate that reads the same presence roster the turn's own NPC block builds from. |
| `arrest.approaches` in a law file | `engine/world/law.py::load_spec` keeps `arrest["approaches"]`; nothing reads it | docs/AUTHORING.md §3.11 once described it as "the story's own default set of exits" merged into the arrest scene. No merge exists: the arrest encounter's exits come from its own encounter file only, and HUE & CRY's `watch_stop` declares all of them there. Wiring it means merging the block under the scene's own `approaches` in `encounter` when the scene opened is `arrest.encounter`, with the scene's own keys winning. |
| A check that a choice promising an action carries its intent | `engine/llm/schemas.py::storyteller_turn_schema` (`intent` is optional per choice); `schemas.conform` judges only an intent that is present | A model can offer "Follow the smoke toward Edgewood" with no `intent`, on every rung of the structured-output ladder, rung 1 included. Choosing it runs nothing and refuses nothing, so the narrator may write the walk while the save stays put -- rule 1's "never read that you walked somewhere you didn't", unguarded for intent-less choices. Pre-existing since the intent channel (v0.3.0). Wiring it needs a judgement no enum can make: which texts promise a mechanic (a classifier over choice text, or requiring an intent whenever a verb's targets are named in the text). Recorded in CLAUDE.md's deferred list. |
| Engine-side tool loop for non-LM Studio providers | `engine/agents/mechanics.py` (`mechanics_enabled`) | `llm.mcp` (Phase A: the model calls the engine's skills over MCP) runs only where the provider row has `mcp_integrations` -- LM Studio's native `integrations`, the only route that carries an MCP server. On vLLM, llama-server, Ollama or a generic server, `llm.mcp.enabled: true` turns Phase A OFF: one ERROR per process, a FAIL row in `scripts/doctor.py`, and the turn is the MCP-off turn, byte for byte (`tests/test_llm_mcp_gate.py`). Nothing runs the loop in the engine instead (`tools=` -> execute -> append the `tool` messages -> repeat): that is a new turn phase with its own budgets, failure modes and audit questions, for a flag that is off by default (spec §7). Intents (rule 1) carry mechanics on every provider. |
| More than one model server per process | `engine/llm/backend.py` (`get_backend`), with the compat, native and Ollama client singletons and `engine/llm/registry.py::get_registry` | `llm.provider` names ONE server, and every client, the registry, the health checks and the doctor are built from its row. A profile or a lane cannot point at a second server (the summarizer's small model on Ollama, say, with narration on vLLM). Wiring it needs a provider (and base URL and key) per profile, one client set and one registry per server, and a health check per server in the stack and the doctor. |
| Hired hands | spec §4 (docs/superpowers/specs/2026-09-23-hue-and-cry-design.md) | Explicitly optional there; not built. A job is walked solo, start to getaway. |
| Agenda moves posted on the notice board | `engine/scenes/default_api.py::notice_board` | Spec §5 lists "posted on the notice board" as one way the player learns of a move. The board serves labour only. An agenda move reaches the prose as a private sign where it was left (`prompts.agenda_block`) or as a public trace in the moved journal, and nowhere else. Wiring it needs a `trace.board: true` (or similar) that the board reads alongside its labour rows, masked through `agendas.mask_text` like every other piece of agenda text. |
| A `fence {most: hot_goods}` selector | `engine/world/agendas.py::_fence_candidates`, `SELECTOR_KEYS` | Spec §5 names it. Fences hold no stock (`engine/game/trade.py`), so there is nothing to count. The `fence` selector accepts `district` only, and any other key is a load error. |
| `disposition` and quest-progress predicates in agenda conditions | `engine/world/agendas.py::LEDGER_PREDICATES`, `PROGRESS_PREDICATES` | The agendas pass runs inside `advance_time`, which holds no StoryLedger and evaluates no quest. `disposition`, `days_in_stage` and `days_since_started` would be false there forever, so each is refused at load (naming the file) rather than left inert. Wiring them needs a ledger and quest progress in the pass's scope. |
| Thread renegotiation, cutting, the gift auto-thread, and The Wicked Garden's two undeclared templates | `engine/game/threads.py::renegotiate`, `transform`, `cut`, `cut_item`, `cut_arbitrary`, `accept_gift`; `engine/skills/builtin/scenes.py::strike_bargain`; `games/wicked-garden/data/rules/threads.yaml`; `games/wicked-garden/data/canon/state-dictionary.json` | The player's `bargain` verb (`strike_bargain`) seals a template as written, and `discharge` and the day-tick `expire_due` settle and break it -- so the Garden's `obligation_gift`, `ashen_service_owed` and `hospitality_dawn` (no `requires`) work. Nothing else in the lifecycle is reached: `renegotiate`/`transform` have no production caller (only `scripts/simulate_decks.py` calls `renegotiate`), so the Garden's renegotiations (`costly_gift`, `service_named`, `refuse`, `intel_only`) never happen; no production caller cuts a thread, so the `cutters` block only filters `can_cut_with` and the narrator's "severed only by" line, and D8's `shatter_it_with_the_knife` cuts nothing; `accept_gift` has no caller, so the `gift_obligation` auto-thread never seals. `briar_witness` (D6_06) and `three_nights_or_truths` (`bargain_at_the_threshold`) are named in the state dictionary and declared in no `threads.yaml`, so nothing can strike them. The Wicked Garden overhaul (v0.26.0) takes these up. |
| Self-registration, invite links, OAuth and proxy-header login for hosted mode | `engine/hosting/accounts.py` (the one writer of `users.json`), `engine/hosting/auth.py` (the login blueprint) | Hosted mode's accounts are made by the operator only (`scripts/users.py`, v0.20.0 T7; spec §6.1). There is no sign-up page, no invite token, no OAuth provider and no trust of a reverse proxy's `X-Remote-User`: a proxy header is safe only if nothing can reach the app but the proxy, a token link is a password in a URL, and OAuth puts a registered app and a third party into a local-first tool. Wiring any of them means a new writer path through `accounts.py` (never a second writer) and a door in the gate's open list, each with its own test. |
| Per-user media namespaces in hosted mode | `engine/media/providers/base.py` (stills named by a hash of their request), `engine/media/tts.py` (audio likewise), served by `engine/api/media.py` and `engine/api/art.py` | Generated stills and audio are ONE shared cache (spec §6.8): identical requests share a file, the routes need a login, and any logged-in player can fetch a file whose key they know. A namespace per account would cost the sharing and was not built (docs/HOSTING.md § Ownership and errors). |
| A player's place in the model server's queue | `engine/llm/gate.py` (`FifoSemaphore.position`); `engine/hosting/supervisor/queue.py` (`LaneQueue.snapshot`) | Hosted mode's lanes serve waiters in arrival order (v0.20.0 T9, spec §5.3), and the gate can say where a waiter stands; under the supervisor (T11) the queue's snapshot lists every lane's waiters in order, for the admin panel. Nothing tells the player: it needs a per-waiter event on every queue move across the supervisor's bus, which v0.21.0 left for a later release (its connection work was the riskier part of that release). A waiting player sees the turn pending, then the turn or the busy refusal. |
| Disk quotas per account in hosted mode | `engine/persistence/saves.py` (`save_store_for`, one store per account and story) | Spec §6.5: nothing caps the BYTES an account's saves and transcripts use. The count is capped (`hosting.max_saves_per_story`, `engine/session/store.py::check_save_room`, T9 fix round 1), every text field is held to `hosting.max_input_chars`, and the actions bucket bounds how fast runs and saves are made; a run's transcript still grows with the run. |
| Workers on another host; the bus beyond loopback | `engine/hosting/bus.py` (`BusServer` binds `127.0.0.1`; `BusClient` dials `CLOCKWORK_BUS_ADDR`) | The supervisor and every child it starts share one host (v0.20.0 T10, spec §14.1-§14.2): the bus is plain JSON lines over loopback TCP with a per-child-start token, which is safe because nothing off the machine can reach it. A worker on another host needs an encrypted, mutually authenticated link (TLS with a pinned certificate, say), a way to start and stop a remote process, and the lifeline's semantics over a network that drops connections without the process dying. |
| More than one worker process per story | `engine/hosting/supervisor/process.py` (`Child`: one per slug in `hosting.stories`) | One worker serves each story, on its threads (spec §5.1). A second process for a busy story would need the front door to pick between them and sessions pinned to one (a run lives in its worker's memory), and the one-live-run-per-account rule held across them. Until then a story's capacity is its worker's `hosting.threads` and the model server's lanes. Horizontal scaling's other parts -- sticky sessions at a load balancer, and a message queue in place of the loopback bus -- are not built either (spec Non-goals). |
| More than one story per process | `engine/games/registry.py` (`activate`: the active story is process-wide config, `set_overlay`); `engine/hosting/boot.py` (one story per worker, from the `CLOCKWORK_GAME` the supervisor sets) | Every content cache is keyed by the active story, and `engine/games/api.py` deliberately never switches it at run time, so hosted mode runs one worker process per story under the supervisor (v0.20.0, spec §14.1). A process serving several stories would need every cache and the config overlay keyed per story instead. |
| Serving a hosted instance under a URL sub-path | `engine/hosting/frontdoor/` (routes at the root); the client's absolute `/api/...` fetches (`ui/src/core/api.js`) and its Socket.IO connection at the root (`ui/src/core/socket.js`) | A hosted instance owns the root of its host name, which is why the front door routes by the story a player chose, not by path (v0.20.0, spec §14.5). Serving under `/clockwork/` needs a configurable base in the client and a `SCRIPT_NAME`-aware front door: hosting work, not UI work, so a later release (v0.21.0 left it). |
| Publishing the Docker image to a registry | `.github/workflows/ci.yml` (the `image` job builds, runs and stops it; it never logs in or pushes) | The image is built locally (`docker build -t clockwork-dark .`) and in CI, and `docker-compose.yml` sets `pull_policy: build` so Compose never asks a registry for it (v0.20.0, spec §8). Publishing needs a registry, credentials as CI secrets, and a tag policy. |
| Two stories open in two tabs of one browser at once | `engine/hosting/frontdoor/stories.py` (the choice in the signed cookie, `flask.session["story"]`) | The front door routes every request by ONE story choice in the browser's cookie (v0.20.0 T12, spec §14.5), so a browser plays one story at a time. A switch in one tab moves every tab's HTTP to the new story, while a WebSocket already open stays on the old story's worker (a tab that keeps playing there is moved at its next HTTP request, which reaches the new story and answers "session not found"); and the client's resume key (`clockwork_save_id`, one `localStorage` entry per origin, `ui/src/core/socket.js:48`) keeps only the story played last, so the other story loses auto-resume and must be loaded from the menu. A per-story Socket.IO path, with the client told its prefix, is the way out, in a later release: it needs the same configurable client base and `SCRIPT_NAME`-aware front door as the sub-path row (v0.21.0 left it). |
| Memory and CPU figures per process | `engine/hosting/supervisor/process.py` (`Child.row`, the story table: state, port, pid, uptime, restarts, last exit) | The story table, and so the admin panel's Stories page (v0.20.0 T15), shows each child's state, port, pid, uptime, crash restarts in the window and last exit, and nothing about what it uses. Reading memory and CPU portably needs `psutil` (not a dependency) or per-platform code (`/proc` on Linux, the Win32 process API on Windows). |
| Restarting the supervisor itself | `engine/hosting/supervisor/__main__.py` | The supervisor restarts its children; nothing restarts it. If it dies, every child's bus link closes and each exits (the lifeline), so the instance is down until the container's restart policy (the Docker image, v0.20.0 T18) or a systemd unit's `Restart=` starts it again -- which is the right layer for it, and why a held-down front door ends the supervisor rather than leave an instance that serves nothing. |
| The admin panel inside the React client | `engine/hosting/admin/` (server-rendered pages, `admin.css`, `admin.js`) | The panel (v0.20.0 T14, spec §14.7) is Jinja pages, one stylesheet and one small refresh script, with no build step, so it neither pre-empts v0.21.0's client overhaul nor gets rebuilt by it. Nothing under `ui/src` knows of it. v0.21.0 decided it stays server-rendered: the panel must stay free of the client's build and of its HTML sinks (`tests/test_ui_no_html_injection.py`, which is what lets it share the game's origin). Moving it into the client is left to a later release, should one want it. |
| Two-factor login for admins, and a network allowlist for `/admin` | `engine/hosting/admin/guard.py` | An admin proves who they are with their password, at login and again every `hosting.admin.reauth_minutes` (spec §14.7); there is no second factor (TOTP, WebAuthn). Nothing in the engine restricts `/admin` by address: an operator who wants it off the internet denies it at their reverse proxy (docs/HOSTING.md § The admin panel gives the Caddy and nginx lines). Both need new state per account and their own recovery path, for a small self-hosted group. |
| Downloading, restoring or deleting a single save in the panel | `engine/hosting/admin/saves.py` | The Saves page (v0.20.0 T15, spec §14.8) shows each account's saves per story through an allowlisted projection of each store's `index.json` (id, auto or manual, turn, written, save format, bytes on disk) and opens no save's own file. Handing a save's contents to an admin, or changing one, would put play in the panel (spec §14.10 rules that out); an account's saves are removed as a whole by a delete with purge (the Users page), and a player deletes their own from the game. |
| Setting `llm.api_key`, or any secret, in the admin panel | `engine/hosting/admin/model.py` (`EDITABLE`, `validate_base_url`) | The Model server page (v0.20.0 T16, spec §14.9) shows the API key only as set or not and where from ("set, from the environment (`CLOCKWORK_LLM_API_KEY`)", "set, from a file (`llm_api_key.txt`)"), through `ConfigManager.secret_source` -- never the value, its length or any part. The panel's allowlist holds no secret, and its URL rule refuses a base URL with `user:pass@` or a query, because the page shows the URL and the audit log records it old and new. A secret entered in a browser form would travel through the front door, the bus and the admin layer on disk; it goes in the environment or a key file (docs/MODEL_SERVERS.md), which the operator owns. The key follows a base URL an admin moves to another origin only when that apply ticks "send the API key to this host" (audited; the layer's `llm.api_key_origin`, `engine/config.py::_key_withheld`). |
| A story overlay's `llm.base_url` moving the API key to another origin | `engine/config.py` (`_key_withheld`) | `llm.api_key_origin` withholds the key only when the ADMIN layer moves the base URL to another origin (v0.20.0 T16). A story's own overlay that sets `llm.base_url` is not covered: the key follows it. No shipped story sets `llm.*`, and a story's files are the operator's own trusted content, so the key stays as it is; a story from an untrusted author should not be installed on a hosted instance holding a key. |
| Editing anything outside the `llm.*` allowlist in the admin panel | `engine/hosting/admin/model.py` (`EDITABLE`) | The panel edits eleven model-server keys (`llm.provider`, `llm.base_url`, the two lanes, `llm.context_tokens`, `llm.prefer_native`, five of `llm.profiles.big`), held in the admin layer and applied by draining and restarting the workers (v0.20.0 T16). `hosting.*` (who may log in, the stories, the limits), `stack.*`, speech, images and every other key stay in the operator's `CLOCKWORK_CONFIG` file or `config/local.yaml`: each would need its own validation and its own apply (most change what a worker serves, some what the front door does), and `hosting.*` in the layer could turn hosting on or keep it on by itself. A posted key outside the list is refused, and the layer refuses to load one. |
| Telling a tab that was DISCONNECTED when its run was released | `engine/hosting/__init__.py` (`session_ended` goes to the run's room); `ui/src/core/link.js` (transitions 13, 18) | `session_ended` (v0.21.0) reaches only the sockets in the run's room, and a tab whose socket was down at the release is in none. On its reconnect it rejoins its old id: if the release rebuilt another id, the join misses and 18 resumes the save automatically -- releasing the other window once, one round of the ping-pong §6.5 rules out (that window is told `elsewhere` and does not resume on its own, so it stops there); if a same-save resume elsewhere rebuilt the SAME id, the rejoin succeeds and two tabs sit in one live run (the local two-tabs finding's shape, in hosted mode). Telling it needs the server to remember recent releases per account and answer a join with the reason, or a join that names its tab. |
| A story stopped or restarted by the operator | `engine/hosting/supervisor/` (the drain and stop); `engine/hosting/frontdoor/proxy.py` (`UNAVAILABLE`, the 503); `ui/src/core/link.js` (transitions 4, 11) | A story's stop or restart (the Stories page, a model settings apply) drains and stops its worker, which sends no event: `session_ended` (v0.21.0) is the session store's, and a worker that goes away releases nothing. The player's page takes the connection banner's path instead: "Connection lost.", then "The server is not answering." with the front door's 503 words, "(story unavailable)", and when the worker is back it rejoins on its own, finds its run gone with the old process and resumes it from its autosave. Saying "stopped by the operator" in the banner would need the worker (or the front door) to tell each socket before it goes. |
| Metrics export (Prometheus, OpenMetrics), and alerting on a crash loop or a held-down story | `engine/hosting/supervisor/metrics.py` (`MetricsStore`, its named `QUERIES`) | Since v0.20.0 T17 the supervisor keeps the closed metrics schema (`engine/hosting/metrics_schema.py`) in `<storage.root>/hosting/metrics.sqlite3` and answers the admin panel's Metrics and Errors pages through named queries (spec §14.10). Nothing exposes them to a scraper: an export route would be a new door (the front door's, behind the gate, or a port of the supervisor's own) and a format of its own. Nothing alerts either: a crash loop is seen in the Stories page, the Errors page's process events, the supervisor's ERROR log line and the `story.held_down` audit row, and an operator who wants a page sends the supervisor's output (or the log file) to their own alerting. |
| Archiving the audit log beyond its kept files, and reading past 5000 rows in the panel | `engine/hosting/audit.py` (`rotation`, `read_recent`, `AUDIT_MAX_ROWS`) | Since v0.20.0 T14 fix round 1 `<storage.root>/hosting/audit.jsonl` rotates by size (`hosting.observability.audit_max_mb`) and keeps `hosting.observability.audit_keep` rotated files, deleting the oldest; the Audit page reads a bounded tail across them, back at most `AUDIT_MAX_ROWS` (5000) rows. Nothing copies a file elsewhere before it ages out, and the panel cannot page further back: the operator copies the rotated files by hand (docs/HOSTING.md § The audit log). |
| Per-account settings in hosted mode | `engine/api/settings.py` (`POST /api/settings` answers 403 hosted) | The Settings panel's keys describe the machine (pace, voice, model), and a save rewrites `config/local.yaml` and resets every cache under other players' turns, so hosted mode refuses it (spec §6.7) and `GET` says `writable: false`. Nothing stores a player's own preferences (a narration speed, say) per account. Wiring it needs a per-account settings file under `<root>/users/<id>/`, read per session, and a split of the keys into the machine's and the player's. |
| The static spoiler table's narration half | `engine/lore/interceptors.py::AwarenessGateInterceptor.run_post` | Only `tests/test_awareness_gate.py` calls it. The governance POST chain holds `RulesGovernor` alone, and `engine/agents/storyteller.py::run_turn` never gates the final narration. So a story's `spoilers.yaml` masks prompt regions wrapped in `mark_spoiler`, and not what the model writes. Streamed deltas (`on_delta`) would also reach the client before any post-mask. Wiring it needs a call after the retry loop, plus a decision on the stream: a hold-back buffer, or the authoritative `turn_update` replacing the streamed text. Agenda masking does not depend on it, because the narrator is never told a role's NPC until the player has earned it. |
| An overlay's action as an intent: barter, item use, crafting, posted work, a thread's paper | `ui/src/core/App.jsx` (the overlay's `onAct`), `ui/src/stories/clockwork-dark/screens/Trade.jsx`, `ui/src/stories/clockwork-dark/parts/Inventory.jsx`, `ui/src/stories/clockwork-dark/screens/Notices.jsx`, `ui/src/stories/neon-city/parts/PaperOverlay.jsx`; `engine/scenes/default_state.py::resolve_player_intent` (typed text resolves to `{}`) | Every overlay button sends the player's words as TYPED TEXT (`send("custom", text)`), and typed text declares no intent by definition, so no skill runs from it: outside LM Studio's `llm.mcp` mode only the narrator reads "You barter with the baker: buy bread", and the prose can tell of a trade, a crafted thing or a taken shift the save never made (rule 1; v0.21.0 final review finding 9). Wiring it: an overlay hands `onAct` an `{action, target}` intent and the server accepts it only when it is in `intents.legal_intents(state)`, as a chip's is. The flagship's overlays are the v0.25.0 overhaul's; NEON CITY's paper is the v0.27.0 overhaul's. |
| Display names in the negotiation panel | `ui/src/core/panels/NegotiationPanel.jsx`; producer `engine/agents/pipeline.py::PipelineResult.to_dict` | The panel names the lead, the agent that yielded and the rule by roster and rule id, de-underscored ("gm led; sophia → gm"): the payload carries no agent's display name. Deliberate while the panel is the author's tuning surface (collapsed by default); a player-facing version needs the roster's names on the payload (v0.21.0 final review finding 5). |
| Faction names on the flagship's sheet | `ui/src/stories/clockwork-dark/parts/Sheet.jsx` (Standing); producer `engine/game/state.py::to_client_dict` (`reputations`) | `reputations` is keyed by faction id and the payload carries no faction's display name, so the Standing rows read the id de-underscored. Wiring it: a `factions` name map (from the story's `data/world/factions.yaml`) on the payload, then the sheet reads it (v0.21.0 final review finding 4). The v0.25.0 flagship overhaul. |
| The social engine behind the `paths.social` seam (v0.22.0) | `engine/social/__init__.py::boot`; `engine/game/state.py::_phone_block`; `engine/game/rng.py` (`SOCIAL_*`); `engine/social/population.py`; `engine/social/creation.py`; `engine/social/behaviour.py`; `engine/social/events.py`; `engine/social/apps.py`; `engine/social/matching.py`; `engine/social/messaging.py`; `engine/social/relationships.py`; `engine/social/saves.py`; `engine/social/archive.py`; `engine/social/agreement.py`; `engine/social/memory.py`; `engine/social/voicing.py`; `engine/social/voicer.py`; `engine/social/inbox.py`; `engine/social/away.py`; `engine/social/media.py`; `engine/social/games/`; `engine/social/meets.py` | T1 laid the seam: every one of the seven `SOCIAL_*` streams is read now (`SOCIAL_POPULATION` since T3, `SOCIAL_MATCH` since T7, `SOCIAL_PACE` and `SOCIAL_BEHAVIOUR` since T8, `SOCIAL_MEDIA` since T19, `SOCIAL_GAME` since T22, `SOCIAL_MEET` since T24), and of the `social_*` effect kinds `social_profile` (T4), `social_queue` and `social_event` (T5), `social_settings` (T6), `social_person`, `social_app`, `social_match` and `social_unmatch` (T7) `social_message` and `social_read` (T8) `social_regard`, `social_stage`, `social_request` and `social_history` (T9), `social_memory` (T12), `social_voiced` (T14), `social_media_decision` and `social_media` (T19), `social_game` (T22) and `social_meet` (T24) have handlers (every kind of the release). `boot()` imports `population` (T3), `creation` (T4), `behaviour` and `events` (T5), `intents`, `payload` and `turn` (T6), `apps` and `matching` (T7) `messaging` (T8), `relationships` (T9) `archive` and `saves` (T10), `agreement` (T11), `memory` (T12), `voicing` (T13), `inbox` and `voicer` (T14), `away` (T16), `media` (T19), `games` (T22) and `meets` (T24). The event queue (T5) is walked by the clock; the kinds with a handler are `daily`, `see_like`, `likes_you` and `expire` (T7) `read`, `reply`, `initiate` and `double_text` (T8), `arc_beat` (T9), `game_move` (T22) and `meet_start` (T24); `events.daily_hooks` holds the likes reset and the day's likes-you (T7), the day's initiations (T8) relationships' morning step (T9: mood back to neutral, interest decay, drift, the cold wind-down and the fade) and media's (T19: budgets refilled, "later" requests kept or broken, one unasked medium at most) and the games' (T22: a game whose person left, ended or faded is abandoned); every `events.KINDS` kind has its handler (an event of a kind with none -- its module failed to import -- is dropped with an ERROR). The stored profile (`state.social["player"]`) is read by the population's filter and by matching (T7) and made by the client's setup wizard (T27, `ui/src/stories/read-receipts/NewRun.jsx`); its `name` is the run's `state.player_name`, seeded from a new game's `player_name` when the creation names none (T27, `social.creation.seeded_name`). Every app the phone lists has its screen since T29 (`ui/src/stories/read-receipts/`: Games with Tile Talk and This or That, Photos, Calendar, Contacts with the contact card, Settings); an app kind the client does not draw opens on `ui/src/stories/read-receipts/apps/Messenger.jsx::NotYet`. From T7 (`engine/social/matching.py`, `apps.py`): no person unmatches the player: `matching.unmatch(..., by="them")` exists and nothing calls it (no archetype or arc says to; a relationship ends by winding down, fading, an arc's `then` or the player's `end`). Likes you draws its likers only from people whose once-per-pair like-back is true, so Front Porch's browse deck loses the willing ones over a run and its matches per like fall; recorded in `apps.yaml`'s header, and the simulator's `like_to_match.front_porch` row measures matches per like with both paths together (T26). From T8 (`engine/social/messaging.py`): the player sends text, since T19 photos and videos (`photo_id`, `subject`) and since T21 voice notes (`audio_transcript`, cut to `media.yaml` `voice.max_seconds`; no audio kept); `ask` takes `what: number` or `exclusive` (T9), `photo`, `voice` or `video` (T19) and `meet` (T24: the engine picks the venue and the slot) (a game is started with `game_invite`, T22, never asked for); a due message (`voiced: false`) shows as pending until the voicing pass (T14) commits its words; `typing` reads `session.typing`, which a voicing call fills while it is in flight (T14). From T10 (`engine/social/saves.py`, `archive.py`): a thread's messages past `social.state_messages` move to `phone_archive.jsonl` at each phone save; the away advance (T16) saves at once through `save_now` itself: `social_settings` `away_since` returns `save_reason: away`, which nothing reads. A resume of a save whose live run (same owner, same save) is mid-turn does not wait for it: that run's flush before the load (`engine/session/store.py::SessionStore._flush_before_load`) is skipped, logged at INFO, so its phone changes since its last save (at most `social.autosave_seconds`, plus that turn's own) are not in the resumed run; that turn's own at-once save can still land over the save after the resume (the local two-tabs finding 7, CLAUDE.md), while the dirty timer skips it (no longer live). The voicing pass (`engine/social/voicer.py::_apply_reply`) has the same window, narrowed: a commit asks liveness under the old run's lock and again just before its save, but a local resume takes no lock of the old run, so one landing between the second check and the write lets the old run's save land after the resume. Hosted mode closes it (the old run's lock is taken or it is marked ending). From T9 (`engine/social/relationships.py`): a voiced reply's `regard` and `proposals` reach a person only through `apply_regard` and `apply_proposal`, which the voicing pass's commit calls (T14), and relationships.yaml `regard.fallback` (an engine-authored fallback reply's proposed warmth and trust, spec §10.2's ruling) goes through `apply_regard` the same way; a person's `mood` is read by T13's voice prompt and T19's media accept multiplier, both through `mood_now`; `meeting` is reached by a meet-up agreed and dating, friends and fling by `meets_good` (T24, `meets.py`). From T11 (`engine/social/agreement.py`): the agreement checks (spec §11.5) are run by T13's `voice` in every voicing pass, and the state-dependent ones (`STATE_CHECKS`) once more against the live state at the pass's commit (T14); `meeting_claimed` (T24) reads `AgreementView.agreed_meets` and `now`: "see you tonight" is judged there, against the meet-ups planned, not in `claims:`. `AgreementView.told` (the contacts the player named in this person's threads) and `stage_before` (the live stage left, for a person off a live stage) are filled by `view_from_state` and, the same way through one shared builder, by T13's `view_from_snapshot` (a test holds the two equal). `told` reads the messages kept in state and, for those spilled to `phone_archive.jsonl`, the names recorded in the person's `told` as they left (T12, `memory.note_told`); a name the player wrote before that person was a contact, in a message spilled before they became one, is not recorded. From T12 (`engine/social/memory.py`): a thread's summary (`thread_view` under the turn lock, `with_archive` and `summarize_thread` off it, `commit_summary`, `production_summary_fn`) and a reply's facts (`add_canon`, `add_knows`) are written by the voicing pass (T14): a reply's facts at its commit, and at most one thread's summary per pass, after its replies. A person's `canon`, `knows` and a thread's `summary` are read by T13's voice prompt (`voicing.messages`, through `memory.budgeted`). Canon folded into a summary is kept ahead of the conversation when the summary is cut (`cap_summary`), and only as long as the word cap leaves room for the fold lines themselves. A thread whose archive file is gone or unreadable keeps its summary where it is and logs a WARNING at each pass: it is never summarised past the missing messages again. From T13 (`engine/social/voicing.py`): `snapshot_of`, `voice`, `fallback_reply` and `production_llm_fn` (the `llm.profiles.texter` profile) are called by the voicing pass (T14); `texter.md`'s `post_meet` is emitted since T24 (and `ask_meet` is a proposal a reply makes in its own words; no decision emits the situation) (`game_banter` is emitted since T22; the media ones, `send_*` and `decline_*`, are emitted since T19, and RIGHT NOW names a media subject by its `media.yaml` label); a fallback's mood is `neutral` (an engine line carries no mood of its own). From T14 (`engine/social/voicer.py`, `inbox.py`): `drain_inbox` drops an item of a kind it has no handler for, with a log line (its kinds are `voiced` and, since T19, `media`). From T16 (`engine/social/away.py`): the resume frame's `lock_screen` is drawn by the client's lock screen (T27, its `text`); in local mode a resume rebuilds the same session id and registers it before its away advance, so a second tab already in that room (the two-tabs finding 7) can take the new run's turn lock in that window: the advance is then skipped (logged at WARNING) and the tab's action re-stamps `last_active_wall`, so that absence is lost; hosted mode cannot double-advance (each resume loads its own state, and the released run is ending, so its saves are refused). `lock_screen` counts the messages still in state, so one spilled to the archive by the away advance's own save is not counted (a thread past `social.state_messages` within one absence). From T22 (`engine/social/games/`): a person invites the player to a game through a voiced reply's `invite_game` proposal and, since T23, through a daily draw against their archetype's `games.invite_prob_per_day` (`games._queue_their_invites`; the invite itself is a `game_move` event with `invite: true`, made through `relationships.apply_proposal` when it lands); the draw and the request id it takes are new since T23 (T26's full pass measures with it). Which game an invite asks for is the one the pair has played least among the rows KEPT (`social.games_kept`), so a long run's older games are not counted. This or That (T23, `this_or_that.py`) deals five pairs and no more: a person may be dealt a pair they have answered before, in another game. A ghosted person makes no move while ghosted: the game waits on their turn, is re-armed when they come back (`games.rearm`, from messaging's reconnect) and is abandoned the next morning if they leave, and the player can resign it on either turn (`game_move {move: resign}`). The first Tile Talk move of a local run loads the word list inside that turn (about 1.5 s; hosted mode warms it at start-up); the client's Tile Talk and This or That screens are T29's (`ui/src/stories/read-receipts/games/`), each move a `game_move` the engine judges. From T24 (`engine/social/meets.py`): a meet-up proposed to a person who has gone quiet (ghosted) gets no answer at all (the ask is counted; no row, no line, no stage); a second `propose_meet` the same day costs nothing (`asks.repeat_warmth` is not charged: an answer with no odds has nothing for `repeat_mult` to lower, and re-proposing a counter's slot is how a counter is taken), only the per-day cap holds; `meeting_claimed`'s `today` phrases pass with any meet-up planned that day, whatever its slot ("see you tonight" at 08:00 with a 10:00 meet: accepted precision); a meet-up missed while away (one away advance across its slot) is a no-show like any other, its start notification naming its time and the no-show its own ("You missed ..."); their meet request lapses (answered no by the engine, at no cost, with an engine line -- none in a thread that is unlisted or whose person is gone or ended) at its slot's start or the first morning it can no longer be met, and its lapse event stops `wait {until: next}` only while the request is still open (`turn._stale_lapse`); and a person who unmatches, is blocked or is ended has every plan with them called off at no cost. The simulator's player asks to meet (`ask {what: meet}`, the engine picking) and goes to each meet-up that comes due; it never uses `propose_meet`, so a proposed slot and the engine's counter are covered by the tests alone, and no stub voice proposes anything (spec §10.5), so its photo, voice-note and video rows count the engine's own unasked media and a model's `offer_*` is unmeasured (T26). From T26 (`engine/social/media.py`, `archive.py`): a media row whose message a save has spilled reads it back from the archive (`_message_of`, `archive.archived_message`); one in neither (an archive file lost) is made a procedural tile, logged at INFO; and a voice note's transcript is written to its message only while that message is in state -- an archived one keeps its transcript on the media row alone (the archive is append-only); the client's Calendar is T29's (`ui/src/stories/read-receipts/calendar/Calendar.jsx`). |
| `ComfyUIClient`'s in-turn queue, kept without its submit | `engine/media/comfyui.py` (`ComfyUIClient.enqueue_image`), called by `engine/media/pipeline.py` | Since v0.22.0 T17 (spec §13.4) the in-turn queue contacts no server: its `/prompt` submit of a one-node stub graph (a lone CLIPTextEncode, which ComfyUI accepts and which produces nothing) is retired, and with `comfyui.enabled` on it answers a placeholder (or a cached URL) exactly as with it off, so no story's turn posts a workflow (`tests/test_comfy_client.py`, a flagship turn under `comfyui.enabled: true` making no HTTP request). The queue and its prompt building stay because the turn payload's `media.images` rows are built from them. Real generation is the art provider (`engine/media/providers/comfy.py`, behind the image worker and `media.live_generation`) and the phone's job worker (T18). |
| A person's voice kept across a TTS server change (v0.22.0 T21) | `engine/media/tts.py`; `engine/social/population.py::_voice_for` | A person's `voice_id` is drawn from `tts.voices` (config) of their sex each time the person is generated -- a pure function of the seed and their index, never stored -- so changing `tts.voices` (another TTS server with other voice names, a voice added or removed) can give an existing person a different voice, and a cached profile keeps its old one until the process restarts (`population.reset_profiles`). Reordering the list re-voices people too, not only adding or removing a voice: the draw picks by position among the voices of that sex. Not built: a voice recorded on the person at match and kept, or a mapping from old voice names to new. With no voice of their sex in the list, the person's voice notes are transcript tiles. |
| The ComfyUI client's phone side (v0.22.0) | `engine/media/comfy/client.py`, `engine/media/comfy/workflows.py`, `engine/media/comfy/jobs.py`, `engine/media/comfy/storage.py`, `engine/social/media.py` | T17 built the client (every route, bounded, a `ComfyError` by kind) and the workflow loader, and rebuilt the art provider on them; T18 built the job worker (`engine/media/comfy/jobs.py`: `comfyui.retries`, `phone_media.daily_job_cap`, `upload_image` for a workflow binding `reference_image`, `bad_type` and `cancelled`) and the owner-scoped storage (`storage.py`); T19 wired them to the phone (`engine/social/media.py`: the jobs, the hand-off, `media_ready`, resubmission on resume, the worker stopped on a hosted drain, the owner-scoped route). Since T21 a voice note is the speech worker's, not ComfyUI's (`engine/social/media.py::voice_due`, `engine/media/tts.py`): it never enters the media worker's queue, but each NEW note is one of the account's `phone_media.daily_job_cap` jobs per real day, counted with its images and videos (`MediaJobWorker.charge`; past the cap the note is its transcript tile, logged), and a resume's resubmission of a note still queued or speaking is retargeted to the newer run, never queued twice (`SpeechWorker.submit(key=)`). The people's voice budgets are no real-time bound (they refill per IN-GAME day, which a player can pass at will). The speech worker is one FIFO for every account: within the cap, one account's notes still delay another's, and a note waiting past `tts.job_timeout_seconds` is its tile. Since T20 `comfyui.workflows.video` is declared (`config/comfyui/video_wan.json`): a video is a job like a photo, its poster the first image file under `images` of the workflow's `output.poster_node` (the shipped template's first frame, node 12), else of the output node (never the clip itself, chosen before any fetch), else the procedural tile; the row carries it as `poster_url`. The player's camera roll (spec §3.3, "each is a media job") is NOT WIRED: only a photo the player SENDS is a job (`messaging._send_media`, a row `own`); the profile photos themselves stay procedural tiles. A row's `running` status is never written (the worker reports nothing between submit and its result): a row is `requested`, `submitted`, then `ready` or `fallback`. A job inside an HTTP call when a drain stops the worker still finishes and is handed off, through the hand-off's liveness check. The hand-off finds its run by session id in the process's store (`get_store`), so a run held by another store (a harness's) is never handed a result. A job writes only while its save's folder exists (a delete or purge before the job's pre-write check leaves it `failed`, writing nothing); the instant between that check and the write is covered only by the purge's own re-check. The media queue has no bound of its own: `phone_media.daily_job_cap` x the accounts playing per day, carried over midnight (no `queue_max`, unlike the voicing queue). That per-account count is kept in memory per worker process (`MediaJobWorker`'s `_spent`/`_day`), never persisted: a worker restart, or a hosted drain (`engine/hosting/__init__.py::_stop_media_worker`, then `reset_media_worker`), resets every account's count for the rest of the day (final review M3, recorded, behaviour unchanged). Phone media are kept per owner and SAVE ID, not per story (`media/phone/<owner>/<save_id>`, the plan's layout): deleting any story's save removes the phone media of a READ RECEIPTS save with the same id -- save ids are 12 random hex characters, so a collision is negligible, not impossible. The art provider does not retry an execution error (`retries` is the phone's). A wait past `comfyui.job_timeout_seconds` posts `/interrupt` with no body (spec §13.4 step 4, `ComfyClient.wait`), which stops whatever the server is running -- on a shared server, possibly another job (the art provider's, the phone's, or another tenant's) while this prompt stays queued; newer ComfyUI may accept a `prompt_id` in the body, and `POST /queue {"delete": [...]}` removes a pending prompt, but neither was verified, so the behaviour is kept. `comfyui.timeout_seconds` is httpx's per-phase timeout (connect, each read), not a total: a body that trickles bytes just inside it runs on, bounded only by `comfyui.max_bytes` (`/view`) or `comfyui.max_json_bytes` (every other reply). Not verified against a live ComfyUI (docs/MEDIA_SERVERS.md, T19). |
| The video workflow verified live | `config/comfyui/video_wan.json`; `config/default.yaml` (`comfyui.workflows.video`) | Since v0.22.0 T20 (spec §13.8) a video message is a job on the shipped `video` workflow: Wan 2.1 text-to-video (1.3B) on ComfyUI's native nodes (`UNETLoader`, `CLIPLoader` type `wan`, `VAELoader`, `ModelSamplingSD3`, `EmptyHunyuanLatentVideo`, `KSampler`, `VAEDecode`, `SaveWEBM`; the poster frame by `ImageFromBatch` and `SaveImage`, `output.poster_node: "12"`), 49 frames at 16 fps (about 3 s) at 480x832, binding `positive`, `seed`, `width`, `height`, `frames` and `filename_prefix`. It is checked against the stub alone (`tests/test_comfy_client.py`, `tests/test_comfy_jobs.py`, `tests/test_social_media.py`): no ComfyUI was listening on `comfyui.base_url` during T20, so the node types, their inputs, the model file names and the history shapes `SaveWEBM` and `SaveImage` answer are UNVERIFIED until run (docs/MEDIA_SERVERS.md). The poster is wired (T20 fix round 1: `workflows.Workflow.poster_node`, `jobs.MediaJobWorker._store_poster`) and checked against a stub history of the native shape -- the clip under `images` on node 10, the first frame on node 12 -- with the clip fetched once; whether a live ComfyUI answers that shape is unverified with the rest. |
| A voicing pass dropped after `social.voice.max_attempts` busy admissions | `engine/social/voicer.py` (`VoicingScheduler._after`) | Hosted, a pass that finds the narration queue busy is re-queued with backoff (2, 4, 8, 16, 32 s) and DROPPED at the sixth busy attempt (a `phone` metric `voice_pass`/`dropped`). Nothing was marked, so its messages stay due (the client shows "…"), and they wait for the player's next phone action (or, from T16, a resume) to request a pass again. No timer retries it. |
| Changing discovery during a run (READ RECEIPTS, v0.22.0) | `engine/social/intents.py` (no phone verb writes `player.discovery`); `ui/src/stories/read-receipts/settings/Settings.jsx` | The player's discovery (the ages and the distance a dating deck draws from) is set by the setup wizard at creation (`engine/social/creation.py`) and is read-only afterwards: the Settings app shows it with "It can't be changed during a run", and no `phone_action` changes it, so a deck already dealt never reshuffles under a new filter. Wiring it needs a verb (with the deck's re-deal and the profiles' cache key, `population._player_key`) that no task of v0.22.0 builds. |
| "Let time pass" in hosted mode, and its preference kept server-side (READ RECEIPTS, v0.22.0) | `ui/src/stories/read-receipts/settings/letTimePass.js`; `engine/social/payload.py` (`auto_wait`) | Spec §15.1: the preference is the client's, kept in the browser's localStorage (off by default; a blocked storage reads off), and offered only when the payload's `auto_wait` is true -- local mode. Hosted mode never offers it (each wait can create due messages and so a voicing admission), and no save, account or route keeps it, so it does not follow a player to another browser. `state.social.settings.auto_wait` (`engine/social/kinds.py::empty_slice`) is kept in the save and read by nothing since T29. |
| Interrupting a model call already sent | `engine/social/voicer.py` (`run_pass`) | A pass's `cancel` (the store's release, a hosted drain or shutdown, the run's room emptying) stops it making another call and committing anything more, but a voicing call already sent runs to its end: its answer is discarded when it returns. The worker thread is held for that call's length, bounded only by the model client's own HTTP timeout (the admission's deadline and the supervisor's reclaim free the TICKET, not the thread); a drain waits for it within its own `seconds` and otherwise answers not drained. |
| Voiced replies parked in a released session's inbox | `engine/social/inbox.py` (`SessionInbox`) | A reply whose commit could not take the turn lock within `social.voice.commit_retry_ms` waits in the session object's inbox for the next action or pass. The inbox is never saved: if the run is released first (the idle sweep, an end, a resume elsewhere) those replies are lost, and the save's due messages are voiced again by the resumed run's next pass -- one more model call, and possibly other words. |
| A due message whose person left before it was voiced | `engine/social/voicer.py` (`_voiceable`, `_withdraw`, `_apply_reply`) | A due message of a person who is unmatched, blocked or `ended` before it is voiced is WITHDRAWN the first time the voicer sees it (the check after the next phone action, a pass's snapshot, or the discard of a reply already in flight): `social_voiced` `op: withdraw` sets `voiced: "withdrawn"` with no words and drops its "New message" notification, so no "…" is left (a withdrawal outside an action's payload is pushed at once as a `phone_message` with the thread row and no message) and nothing voices it later, even after a reconnect; the engine's own counts (the double-text cap, the opener, the player's burst, "written in") treat it as never sent. The message itself stays in the thread's history (filtered out of the payload, the thread pages and the voice's tail), never shown; what they would have said is not said. |
| One narration ticket per account, in process | `engine/llm/gate.py` (the in-process lanes); `engine/social/voicer.py` (`run_pass`) | A voicing pass is admitted for its run's owner (`admit_turn(account=...)`). Under the supervisor the queue holds an account to one narration ticket across every story (`other_window`); in a single hosted process with no supervisor only the lane's limit applies, so a second pass of the same account answers plain `busy` (tested), and two accounts' passes share the lane like any turns. |
| Voice and video calls, live (READ RECEIPTS, v0.22.0) | `engine/social/intents.py` (no `call` verb) | The phone's catalogue has no verb that rings a person, and no app has a call capability (`engine/social/apps.py::CAPABILITIES` is `text`, `photo`, `voice`, `video`: a voice NOTE and a video MESSAGE, each a recorded medium in a thread). Spec §22. |
| Jealousy, or a person discovering the player's other relationships | `engine/social/relationships.py` | Each relationship is kept per person, and nothing reads one person's state when deciding another's: a person never learns of, or reacts to, the player's other matches, dates or an exclusive relationship elsewhere. The agreement check `another_person` (`engine/social/agreement.py`) only stops a reply from naming a contact the player never told this person about; it is a fact check, not a mechanic. Spec §22. |
| An authored friend contact (milestone texts from a character who is not a match) | `engine/social/population.py` (no authored-person loader) | Every person on the phone is generated from `population.yaml` and reached through a dating app; there is no loader for a hand-written character (a friend, a sibling) who texts the player at milestones. Spec §22. |
| Real-clock alignment of the in-game day | `engine/social/away.py` | The in-game clock is not tied to the real one: a new run starts at `creation.yaml`'s `start_hour` (19:00) on day 1 whatever the real hour, and an absence adds its real seconds times `social.away.rate`, capped at `social.away.max_hours`, so an in-game 08:00 can fall at any real hour. Ruled out by spec §15.4. |
| Shipped same-sex and any-sex populations, and a friendship app | `games/read-receipts/data/social/population.yaml` (`filter.sex: opposite`) | `engine/social/population.py` supports `filter.sex: same` and `any` (`FILTER_MODES`; a person's sex and name are drawn on their own stream keys, so the filter moves nothing else), and they are tested, but READ RECEIPTS ships `opposite` only (the owner's brief) and no other story declares `paths.social`. `friendship` is an intent a person may hold on either dating app (`apps.yaml` `culture.intent_weights`); no app is a friendship app. Spec §22. |
| Group chats | `engine/social/messaging.py` | A thread belongs to ONE person (`_new_thread`: `{thread_id, app, pid, ...}`); nothing holds a conversation with two or more people. Spec §22. |
| A person reacting to the player's bio edits after matching | `engine/social/matching.py` | The player may edit a dating profile's bio during a run (`engine/social/turn.py::edit_profile`), but a person reads the profile only for compatibility and like-back, which are decided before a match (the like-back is drawn once per pair): after the match nobody notices an edit, and nothing re-draws. Spec §22. |
| The `comfyui` phone media provider verified live | `engine/media/comfy/` (`client.py`, `workflows.py`, `jobs.py`, `storage.py`) | No ComfyUI server was listening on `comfyui.base_url` during v0.22.0 T17-T20 or since, so no image or video was ever generated through the phone's pipeline: it is verified against the stub alone (`tests/comfy_stub.py`, `scripts/comfy_stub.py`; docs/MEDIA_SERVERS.md § Verified). Its own row for the video template is above. |
| A third dating app's screens in READ RECEIPTS' client | `ui/src/stories/read-receipts/PlayScreen.jsx` | The engine runs any number of `kind: dating` apps from `apps.yaml` (its deck, likes, matches, expiry and threads), and the client draws the messenger, games, gallery, calendar, contacts and settings kinds generically, but it draws the two dating apps BY ID (`matchstick`, a swipe deck; `front_porch`, a browse deck): a third dating app's icon opens `ui/src/stories/read-receipts/apps/Messenger.jsx::NotYet`. docs/AUTHORING.md §3.15. |


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

Version: v0.5.4 [2026-10-13]
