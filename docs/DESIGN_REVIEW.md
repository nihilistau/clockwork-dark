# Design Review — what the overhaul found

**Document type:** Honest record. Not a changelog.
**Covers:** overhaul phases P1–P11, applied to a codebase that had shipped
PR1–PR12 and 97 passing tests.
**Date:** 2026-08-14
**Suite:** 97 → 1,707 passing, 19 skipped, no expected failures — plus 86
client tests under `ui/tests/`. (The count has dated quickly every time it was
written down; run `pytest` and `npm test --prefix ui` for the real numbers
rather than trusting this line.)

---

## The finding behind all the other findings

The game did not work, and every test passed.

Not "had bugs" — did not work. `advance_time` was
`state.world_day += int(days_elapsed)`, the only production caller passed
`0.25`, and `int(0.25) == 0`. The calendar never moved. Nothing downstream of
the calendar moved either: not the evil ticker the whole premise rests on, not
hunger, not timed-effect expiry, not wound healing, not NPC schedules, not quest
deadlines. A player could sit in Edgewood for a thousand turns and it would
still be eight o'clock on the first morning of the world.

The tests passed because each unit was correct in isolation. `EvilTicker.advance`
had a test that passed it `days_elapsed=1.0` and asserted progress went up, and
it did. Nothing tested that anything ever called it with a number that survived
an `int()`.

And DESIGN.md described the mechanism in confident detail, because a design
document has no way to notice that the thing it describes is not running.

That is the shape of nearly every issue below: **a component that works, a
document that describes it, and no wire between them.** The overhaul's rule
became — if a doc claims a mechanism, there must be a test that exercises it
through the production path, not through the unit's own front door.

---

## Issues found and fixed

Severity is about consequence to a player, not about how hard it was to find.

### F-01 · critical · The world clock did not advance
`engine/game/clock.py`, `engine/game/state.py`

Described above. Fixed by making time a single float, `world_clock_hours`, with
`world_day`/`world_hour`/`time_of_day` as **derived read-only properties** —
there is no longer a field to increment wrongly — and by making
`advance_time(state, hours)` the only writer, with the evil ticker, survival,
expiry sweep, NPC refresh and death check hanging off it so no caller can forget
a step.

Second-order defect found while fixing it: death handling advances the clock
itself (unconsciousness costs hours), which re-enters `advance_time`. Unguarded,
each nested call ran the death check again. Measured jumping **day 2 to day 123
in a single 8-hour step.** Now behind a thread-local re-entrancy guard.

### F-02 · critical · Save round trips destroyed hidden state
`engine/game/state.py`, `engine/persistence/`

`to_dict(include_hidden=)` served both the browser and the disk, and dropped
both `AgentMind` structures. Every save/load reset evil progress, awareness and
the Assistant's trust to defaults. Compounding it, the client called
`/api/game/new` on every socket reconnect, so a dropped connection silently
discarded the run.

Fixed by splitting into `to_save_dict()` (lossless, persistence only) and
`to_client_dict()` (redacted allowlist, browser only), which must never be
merged again; and by `SessionStore.resume(save_id)` on reconnect.
`tests/test_state.py` asserts the round trip on a fully non-default state and is
not permitted to hand-patch omissions.

### F-03 · critical · "No migration" was never a viable decision
`engine/persistence/migrations.py`

DESIGN.md Key Decision #11 read *"JSON save v1, no migration"*. It was already
untrue when it was written: saves existed, the schema changed under them
repeatedly, and `GameState.from_dict` splatted raw dicts into the constructor —
so one added field made every existing save unloadable with a bare `TypeError`.

Fixed with a forward-only chain: each step is `v → v+1`, must be total, runs **in
memory on load** so a failed migration never destroys the original on disk, and
is never deleted. Plus atomic writes and backup recovery, and unknown keys
ignored on load. `CURRENT_SAVE_VERSION` is 2.

### F-04 · critical · Stamina was a countdown to a dead save
`engine/game/survival.py`

Travel spent stamina (`max(1, hours * 5)`). **Nothing in the codebase raised
it.** The round trip to Millhaven costs 40, so after five of them the player sat
at 0 with every travel edge refusing on "Not enough stamina" and no action in
the game capable of giving any back. A permanent soft-lock, reachable inside the
first hour of play.

The fix is deliberately *not* passive regeneration. Awake regen is zero, and the
knob is in `games/clockwork-dark/data/rules/survival.yaml` so the decision is visible in data rather
than implied by an absent line of code. Rest is the only thing that restores
stamina, it costs hours, and hours are what the evil clock eats. Rest **never
refuses**: a bed you cannot reach downgrades to sleeping rough. Any gate on rest
rebuilds the soft-lock — see R-04.

### F-05 · critical · The Storyteller could not remember its own last turn
`engine/memory/`

Turn history was recorded and read by nothing. Every turn began with the model
knowing nothing about what it had just said, who the player had met, or what
they were in the middle of.

Fixed with `StoryLedger` (facts with decay and salience, pinned names, NPC
relations, promises, open threads, rolling turn buffer), a rolling LLM summary
for evicted turns, a token budget with a fixed eviction order, and
`build_storyteller_messages` assembling it all **stable-content-first** so the
KV prefix cache survives between turns — the old prompt put HP and the current
hour in the middle of the standing rules, so nothing cached and every turn
reprocessed the entire prompt.

Sub-finding: the first summarizer reused the Storyteller's own callable, which
is prompted to produce game turns and duly answered a summarization request with
narration JSON — which then became the summary, verbatim. It now runs on a
dedicated `small`-profile call, falling back to deterministic compression when
LM Studio is unreachable.

### F-06 · major · The model set its own difficulty
`engine/game/checks.py`, `engine/agents/tool_dispatcher.py`

`resolve_skill_check(skill, dc, modifier)` let the narrator hand in a raw DC,
which the dispatcher patched with three hardcoded lines: `base_dc = 12`, `+2` if
stealth, `+1` if persuasion. That is a difficulty system with two entries, no
situational awareness, and a knob the narrator could turn on itself — a model
that wanted the player to succeed simply asked for a lower number. Exhaustion,
injury, hunger, darkness and the evil phase touched a roll not at all.

Now the model names a **band** and everything after that is engine business.
Seven skills, six bands, modifiers itemised in the receipt so the deltas visibly
sum to the number applied to the die, and four degrees including **partial** —
which is not success.

### F-07 · major · Skill metadata was decorative
`engine/skills/registry.py`, `engine/agents/tool_dispatcher.py`

`trigger` and `category` were recorded and never enforced; the dispatcher
executed anything present in the registry. `advance_world_tick`, with an
unbounded `days` argument, was fully callable from narration — a time machine.
Negative values rewound the calendar; large ones jumped the world straight to
CONSUMING in a single call.

Fixed with a per-skill `agents` allowlist enforced in the dispatcher, plus
bounds on the tick itself. Refusals come back as legible receipts naming what
was refused and why, so the model can correct itself rather than repeat the call.

### F-08 · major · Quests, arcs and encounters were documentation
`engine/game/quests.py`, `engine/game/encounter.py`

`GameState.quests`, `active_arc` and `arcs_unlocked` had existed since PR7 with
**no writer anywhere**. Four arcs were a table in DESIGN.md and nothing else.
The only pacing formula in the game keyed off `flags.main_quest_started`, a flag
nothing ever set — a permanently dead term. Every travel edge had carried a
`danger_dc` since the graph was written and nothing had ever read it, so the
Millhaven road at midnight during `consuming` was exactly as safe as the walk to
the bakery at noon on day one. `stats.hp` had never been decremented by any code
path in the project's history, and `state.ended` had never been set to `True`.

Built: a quest engine with 24 quests across the four arcs, where **every**
`complete_when` predicate is engine-evaluable and the model's only lever is
`set_narrative_flag` — scoped to the *current* stage of an *active* quest, so it
cannot raise stage four's flag during stage one and skip the intervening
fiction. Encounters as short contested scenes off `danger_dc`. Wounds with names
and heal dates instead of a hit-point countdown. Death as a setback with an
explicit, single terminal case.

### F-09 · major · Sessions shared state
`engine/game/engine.py`, `engine/game/rng.py`, `engine/lore/`

The active engine was a module-level global. Under Socket.IO threading, one
session could rebind it while another was blocked on a multi-second LLM call, so
skills resolved against the wrong player's state. Replaced with a `ContextVar`.

Randomness was worse. The world sim rebuilt `random.Random(seed + world_day *
9973)` on every tick — and because the day never advanced (F-01), every tick
drew the identical first float forever: the caravan either never came or came
every single tick, fixed at world generation. All three schedule rolls then
consumed that one frozen draw in order, so they were perfectly correlated.
Replaced with named per-stream counters seeded from `state.rng_seed`: the same
save replays identically, consecutive draws differ, and adding an encounter roll
cannot shift the caravan schedule.

### F-10 · major · A rejected draft kept its side effects
`engine/game/transaction.py`

The Evaluator could reject a narration and trigger a retry, but the tool calls
from the rejected draft had already run. The player was moved, drained and
wounded by a paragraph they never saw. Now snapshotted and rolled back before
the retry.

### F-11 · major · The JSON contract could not be parsed
`engine/agents/storyteller.py`, `engine/lmstudio/schemas.py`

The loose-parse fallback was `(\{[^{}]*"narration"[^{}]*\})`, whose `[^{}]*`
forbids nested braces — but the mandated payload always contains
`"choices": [{...}]`. The fallback could therefore never match, so whenever the
model omitted the code fence (the single most common local-model deviation) the
player was shown raw JSON as narration.

Replaced with a brace-counting scanner, and the contract itself moved into a
per-turn **JSON Schema**. That removed several classes of failure at once: no
zero-choice soft-lock (`minItems: 2`), no secret length rubric the evaluator was
scoring against silently, and no hallucinated characters (`npc_id` is an enum
built from the NPCs actually present, so voicing someone who is not in the room
is unsampleable).

Removed from the contract: `stat_changes`, `items_gained`, `items_lost`,
`skill_check`/`dc_mod`. The model was asked for all four and the engine threw
all four away, so their only function was to create an incentive to try.

### F-12 · major · Raw bytes took the turn down
`engine/media/tts.py`, `content/scenes/clockwork/clockwork_state.py`

The TTS client returned audio bytes, which went into the turn payload, which is
`jsonify`'d and emitted. Any turn that produced audio failed entirely — not
degraded, failed. Audio is now written to disk and crosses the socket as a URL,
and `tests/test_vertical_slice.py` asserts every payload of an 80-turn
playthrough is serializable.

### F-13 · minor · Narration appeared all at once, then twice
`engine/agents/json_stream.py`, `engine/agents/tag_buffer.py`

The client listened for `narration_delta` and no server code ever emitted it, so
the player watched a frozen screen for the whole completion and then the
paragraph appeared at once. Streaming now decodes narration out of the JSON
object as it arrives; a `streamed: true` flag tells the client to finalize the
live entry rather than append the paragraph a second time underneath it; and a
tag buffer holds back partial `[IMAGE:...]` markers split across chunks so they
never reach the player's log.

### F-14 · minor · Content faults could remove content silently
`engine/game/quests.py`, `engine/game/encounter.py`, `engine/game/checks.py`

A YAML typo in one quest removed every quest; an unreadable encounter band
removed the others. Loaders now skip the bad file, log it, and keep the pack.
Rules caches are keyed on `(path, mtime)` so a content edit or a repointed
config path invalidates them without the module having to be registered in a
cache-reset list it does not own.

Deliberate asymmetry: an **unknown quest predicate is treated as unmet**. A
stage guarded by a predicate this build does not understand must stay shut,
never fall open.

### F-15 · minor · Archetype was a cosmetic choice
`engine/game/procgen.py`

`archetype` was generated, serialized, and read by nothing but a display line in
the prompt. Every character in the game was mechanically identical. Archetypes
now stamp stats and a starting kit, and contribute a small skill affinity that
appears by name in check receipts.

---

## Open issues

These were not fixed by the overhaul itself. They are recorded here rather
than left for the next reader to rediscover; the ones marked **FIXED** were
closed by later work, each with a **Now:** note giving the call site, in the
style R-03 set. R-06, the last one live, closed with the engagement work —
none remain open.

### R-01 · major · The prompt is fitted, then inflated past the budget — FIXED
`engine/agents/storyteller.py::_build_messages`

`build_storyteller_messages` fits the prompt to the token budget. `_build_messages`
then runs the PRE interceptors over the system blocks, and
`LoreInjectInterceptor` appends retrieved lore chunks there — **after** the fit.
The budget never sees them.

Measured over a 40-turn playthrough against this repo's seeded lore DB:

| | assembled | sent | budget |
|---|---|---|---|
| peak tokens | ~6,140 | **~7,550** | 6,198 |

7,550 + `reserve_output: 900` is 8,450 against a `context_tokens` of 8,192. The
prompt overflows the window, and it does so more the longer you play, because
the lore block grows as the ledger and turn buffer already have.

Recorded as a **non-strict `xfail`** in
`tests/test_vertical_slice.py::test_the_prompt_that_is_sent_also_fits_the_budget`.
Non-strict because it passes on a checkout whose lore DB is unseeded — which is
itself worth knowing: the bug is invisible until someone runs
`scripts/seed_lore.py`.

Fix: the interceptor output has to go through `BlockSet.fit`, not around it —
either run the PRE pass before assembly, or re-fit after it. This was found by
the vertical slice and not fixed here because it lives in `engine/`.

**Now:** fixed. Lore retrieval moved into `engine/memory/context.py`, inside
the budget; only the awareness gate runs after fitting. The `xfail` became a
regression guard
(`tests/test_vertical_slice.py::test_the_prompt_that_is_sent_also_fits_the_budget`).

### R-02 · major · `SceneRulesEngine` is dead code with a passing test suite — FIXED
`engine/mcp/scene_rules_engine.py`, `tests/test_skill_enforcement.py`

Rules R001–R005 are implemented and tested. **No production path calls them.**
Grep `get_rules_engine` and the only non-test hits are the module's own
definition, the package `__init__`, and the cache-reset list in
`engine/config.py`. DESIGN.md claimed for five PRs that it "rejects stat changes
not backed by tool calls". It does not, because nothing asks it to.

This is the most dangerous kind of dead code, because it has coverage. A passing
test suite for something nothing calls does not read as dead — it reads as
proven.

Decide one way or the other: wire it in front of `effects.apply_effect` as a
second layer of defence, or delete the module and its tests. R001/R002 duplicate
checks `GameEngine.move_to` already performs, so only R003–R005 are worth
keeping. Do not leave it as it is.

**Now:** wired, the first way. `RulesGovernor` (`engine/agents/governance.py`)
runs R001–R005 in the governance POST chain, called from
`StorytellerAgent.run_turn` after `tx.commit()` so it audits the state the
player actually ends the turn in; violations ride out on
`StorytellerTurnResult.governance`, and R003 counts unearned stat claims into
`Oracle.record_unearned_claim`. R001 validates against the full live location
graph through the rules engine (procgen places are legal), and the caches
rebind the location set on a game swap — see docs/GOVERNANCE.md for both
hazards.

### R-03 · major · The clock ran at ~11.5 in-game hours per turn — FIXED
`config/default.yaml` `world.tick_hours` · `engine/world/world_sim.py::realtime_tick_hours`

**Was:** a flat `REALTIME_TICK_HOURS = 6.0`, granted once per turn whenever 60s
of real time had passed. Instrumenting `advance_time` with a caller-frame
recorder over 200 turns × 4 policies gave the breakdown for `reckless`, the
policy that produced the headline 11.5:

| term | h/turn | share |
|---|---|---|
| background tick | 6.00 | 52% |
| death respawn (10h × 50 deaths) | 2.50 | 22% |
| travel | 1.58 | 14% |
| rest | 1.24 | 11% |

One constant was 60% of every hour the game advanced, and **no player action
came within a factor of two of it**. The earlier note here — and DESIGN.md —
blamed the 8-hour sleep; that was wrong for three of the four policies.

The second term was not independent. Hunger runs at 2.0/hour, so 6h of tick was
12 hunger per turn before the player did anything; starvation supplied nearly
every death, and every death bought another 10 hours.

**Now:** `world.tick_hours: 2.0`, and the tick is **proportional to real elapsed
time** rather than a step function — a 61-second turn and a ten-minute turn used
to cost identically — capped by `world.tick_max_hours` so an open tab over lunch
cannot advance the calendar by days. `scripts/simulate.py` reads the same config
key instead of restating the literal, which is how the instrument used to tune
the clock could measure a different clock than the one that shipped.

Measured, `--turns 200 --seed 42`:

| policy | h/turn before | after | deaths before | after |
|---|---|---|---|---|
| baker | 8.87 | **4.16** | 13 | **0** |
| cautious | 10.31 | **3.21** | 35 | **4** |
| pauper | 9.38 | **3.77** | 31 | **1** |
| reckless | 11.54 | **6.46** | 50 | **30** |
| **mean / total** | **10.02** | **4.40** | **129** | **35** |

The mean fell 56% for a 67% cut, because collapsing the starvation cascade was
worth more than the direct arithmetic.

Two vertical-slice assertions were recalibrated, both of which had been passing
*because of* this bug: the clock test asserted `day >= 5` after 40 turns (only
reachable at 6h/turn) and now asserts against the configured rate; the quest
test required a per-run completion, which needed the flagship 7-day bakery stage
to fit inside 40 turns. It now asserts a stage advance per run plus one full
completion across the runs — see the docstring for why that is not a weakening.

### R-04 · structural · Rest must never gain a gate
`engine/game/survival.py`

Not a defect — a standing constraint that is easy to violate by accident. Rest
is the only source of stamina. The obvious "realistic" additions — needing a
bed, needing safety, needing food to rest — each rebuild F-04 exactly. The rules
file downgrades instead of refusing, and
`tests/test_vertical_slice.py::test_rest_is_always_a_legal_action_at_zero_stamina`
asserts it from the final state of both playthroughs.

### R-05 · major · There is no repeatable income, so the player starves — FIXED
`games/clockwork-dark/data/economy.yaml`, `games/clockwork-dark/data/rules/survival.yaml`, `engine/game/procgen.py`

The live balance problem, and the simulator's loudest finding.

Hunger accrues 2/hour, which at ~11.5 hours per turn is ~23 points per turn on a
100-point scale. A loaf costs 2 gold and removes 35. The player starts with 5
gold. **There is no repeatable, gold-free food source anywhere in the game.**
Foraging is generated into `ProcgenResult.forest` and reachable by no skill;
vendor `buys` lists name items nothing produces; quest rewards are one-shot.

The observed steady state, in every policy:

| policy (200 turns, seed 42) | deaths | turns starving | end gold |
|---|---|---|---|
| baker | 122 | 65 / 200 | 0 |
| cautious | 100 | 89 / 200 | 0 |
| reckless | 189 | 85 / 200 | 0 |

Gold reaches zero within a handful of turns and never returns. From then on the
player starves, drops to 0 hp, respawns at 35% hp with half their (zero) gold and
a fresh −2 wound, and starves again. `games/clockwork-dark/data/rules/death.yaml` already anticipated
this and feeds you 45 hunger points on respawn — which buys about two turns.
Skill success rates collapse under the stacked starvation and wound penalties:
craft **7.6%**, survival **13.9%**, persuasion **4.3%**.

This is not a tuning problem. Three candidate fixes, roughly in order of how
well they fit the fiction:

1. A **forage** skill reading the forest nodes procgen already generates. Free
   food for time spent, which is the resource the game wants you to spend.
2. **Wages** for the bakery apprenticeship — small, repeatable, per shift —
   rather than a single 6-gold payment on completion.
3. **Meals as part of the work.** Maris feeds her hands. This is the cheapest
   change and the most in keeping with Edgewood.

None of these are in `engine/` and none were made here.

**Now:** fix 1 landed as the `forage` skill (`engine/game/foraging.py`,
`engine/skills/builtin/livelihood.py`) reading the forest nodes procgen
already generates, plus repeatable labour through the `work` skill
(`games/clockwork-dark/data/tables/labour.yaml`, `engine/game/economy.py`).

The canary is the `pauper` policy, and its numbers today (200 turns, seed 42):
**zero starvation deaths** (one death, from something else) against the 122–189
above, 93 meals foraged, 7 turns hungry and 3 starving out of 200, and it ends
holding 52 gold on a starting 5. It works no shifts at all.

**Corrected here rather than left standing:** this note used to say the pauper
"survives 200 turns spending zero gold". It does not, and has not since the
shared `_common_upkeep` in `scripts/simulate.py` grew an unconditional bakery
restock — the run makes one purchase, 12 gold. The claim the canary actually
supports is the one that matters and is unaffected: food has a free tier, and
being broke is no longer fatal.

### R-06 · major · Every playstyle converges on the same doomsday clock — FIXED
`config/default.yaml`, `engine/game/evil_ticker.py`, `engine/game/locations.py`

The design says evil advances faster around a disengaged player
(`inaction_bonus`, up to ×1.35) and faster near the Heartlands
(`evil_multiplier`, 0.7 at the bakery to 1.2 at Millhaven). Both are true. They
are also **the same size and opposite in sign**, so they cancel:

| policy | effective rate/day | CONSUMING at day |
|---|---|---|
| baker, never leaves the bakery | 0.0095 | 83 |
| cautious | 0.0101 | 79 |
| reckless, lives on the Millhaven road | 0.0105 | 76 |

Under 10% spread between the two extremes the game offers. A player's choices
change what they see on the way, but not when the world ends.

Related: Convergence unlocks on `min_phase: spreading`, which fires around day
50 for everyone including the baker who never leaves the village. Arcs only ever
open doors, so nothing is taken away — but "awareness-gated story arcs" is only
half true, and the half that is not true is the half that was supposed to
protect the quiet-life player.

Suggested direction, not applied: widen the location multiplier range, or make
`inaction_bonus` a *deceleration* for engagement rather than an acceleration for
disengagement, so that pushing back visibly buys time.

**Now:** both halves of the suggested direction landed, and the clock answers
to conduct. Measured with `scripts/simulate.py`, 200 turns, seed 42 (the new
`hero` policy pursues quests and set-pieces; `reckless` is unchanged as the
exposed-but-unengaged control):

| policy (200 turns, seed 42) | before: evil/day | after: evil/day | after: final evil | deaths |
|---|---|---|---|---|
| hero (engaged) | — | 0.0070 | 0.18 (dormant) | 4 |
| cautious | 0.0053 | 0.0068 | 0.18 (dormant) | 3 |
| baker | 0.0056 | 0.0143 | 0.50 (spreading) | 0 |
| pauper | 0.0044 | 0.0193 | 0.56 (spreading) | 1 |
| reckless | 0.0064 | 0.0149 | 0.70 (spreading) | 24 |

The baker's world now falls **2.03×** faster per in-game day than the hero's
(was: every policy within 13%), exposure still costs (reckless ≥ baker), and
the median run ends in SPREADING instead of everyone parking in DORMANT.
What changed:

1. **The location band widened** past the point where the inaction bonus can
   cancel it: hearth ring 0.25–0.4, mid ring 0.8–1.2, the Millhaven road and
   beyond 1.6–2.2 (`games/clockwork-dark/data/world/locations.yaml`).
2. **Engagement buys time.** A new `GameState.doom_resistance` (0–100, hidden,
   neutral zero) is granted only through the new `doom_resistance` effect kind
   — quest rewards scaled by arc (whisper +12, march +18, convergence +25,
   plus per-stage milestones; the community-tending Quiet Life quests +6–8 and
   the bakery apprenticeship deliberately 0) and set-piece victories (+12,
   ceiling 15 in the spec bounder). `EvilTicker.advance` replaces the bare
   inaction bonus with `engagement_factor = inaction_bonus × (1 −
   resistance/100 × world.evil_engagement_slowdown_max)`, hard-floored at 0.25
   — pushing back buys time, it never stops the clock — and decays the
   resistance at `world.doom_resistance_decay_per_day` inside the same
   advance, so the reprieve is spent, not kept. Both knobs are in the
   manifest `SETTING_ALLOWLIST`.
3. **The base rate came back up** (0.006 → 0.028) because the widened band and
   the slowdown halved the typical effective multiple, and because at 0.006
   every 200-turn run ended DORMANT, which made both mechanisms unobservable.
   The sweep behind the number is in `config/default.yaml`.
4. **`plot_involvement` now measures the player, not the world.** The arc term
   read `active_arc`, which climbs on world state (`min_phase: spreading`), so
   the baker was collecting Convergence's 35 involvement points for standing
   in a village while the world fell — slowing their own doom exactly when it
   should have run free. It now counts the furthest arc the player has a quest
   record in (`engine/game/plot.py`).

The related paragraph above also moved: the Whisper arc's ten-day quarantine
(and the caravan's 8%/day arrival roll) were sized for an eighty-day world and
spent a third of a forty-day one before pushing back was possible; they are
three days and 25%/day now. No regression on R-05's canary: `pauper` still
survives 200 turns at zero gold, and the reckless death count (24) is inside
its old band because its world stops just short of CONSUMING — push the base
rate one more notch (0.032) and it does not, which is measured in the config
comment as the reason the rate stops where it does.

**Re-measured 2026-08-14** on the shipped constants
(`world.evil_base_rate_per_day: 0.028`, `evil_engagement_slowdown_max: 0.75`,
`doom_resistance_decay_per_day: 2.25`) with
`scripts/simulate.py --policy all --turns 200 --seed 42`: hero 0.00704, cautious
0.00678, baker 0.01432, pauper 0.01931, reckless 0.01487; deaths 4 / 3 / 0 / 1 /
24. Baker ÷ hero = **2.03×**, unchanged. The table above is current.

One correction to it: the R-05 line in this block said the pauper "still
survives 200 turns at zero gold". It survives, with zero starvation deaths, but
it is not gold-free — see R-05 for the measurement and why the canary still
holds.

### R-07 · minor · `evil_base_rate_per_day` is defensible but a little fast — SETTLED
`config/default.yaml`

Full analysis and the recommendation are below. **Now:** settled twice — lowered
to 0.006 as recommended, then raised to 0.028 by the R-06 engagement work, for
the reason the recommendation's own second caveat named. See the note at the end
of that section.

---

## Recommendation: `world.evil_base_rate_per_day`

**Currently 0.01. Recommend 0.006.**

Measured with `scripts/simulate.py`, 80 turns × 3 policies, seed 11, sweeping the
base rate. Effective rate lands at 0.96–1.06× base, so the constant does what it
says.

| base rate | CONSUMING at in-game day | ≈ turns | evil at day 40 | phase at day 40 |
|-----------|--------------------------|---------|----------------|-----------------|
| 0.012 | 64–69 | ~140 | 0.46 | stirring, nearly spreading |
| **0.010 (current)** | **76–83** | **~165** | **0.38** | **stirring** |
| 0.008 | 95–104 | ~205 | 0.31 | stirring |
| **0.006 (recommended)** | **125–138** | **~275** | **0.23** | **stirring** |
| 0.005 | 150–165 | ~330 | 0.19 | dormant |
| 0.004 | 187–206 | ~410 | 0.15 | dormant |

**Why lower it.**

At 0.01, CONSUMING arrives on in-game day ~80, which at ~11.5 hours per turn is
~165 turns. For a local-LLM game at 30–60 seconds a turn, that is one and a half
to three hours of continuous play — the endgame phase inside a single sitting.
That contradicts "the player is never required to stop it": a phase ladder that
every playstyle climbs at the same rate, within one session, is a timer, not a
consequence. It also crowds the fiction — SPREADING's refugees and militia
drafts land on day ~50, before most of the Quiet Life quest chain can finish.

At 0.006 the forty-day baker ends at 0.23 — solidly STIRRING, which is exactly
the texture DESIGN.md's phase table promises for that stretch ("livestock
stillborn with brass teeth; tinkers sell ward charms"). SPREADING moves to day
~83 and CONSUMING to ~130, so the endgame becomes something a long campaign or
an inward-pushing player reaches, rather than something that arrives on
schedule.

**Why not lower still.** At 0.004–0.005 the world is still DORMANT on day 40. A
player who spends six weeks in Edgewood should be able to *feel* something has
changed, even if they never learn what. That is the whole premise.

**Two caveats on this recommendation.**

1. It is a second-order fix. R-03 (the clock at ~11.5 h/turn) and R-06 (every
   playstyle converging) both matter more, and both would change what the right
   rate is. If `REALTIME_TICK_HOURS` drops, revisit this number rather than
   keeping it.
2. It changes nothing about R-05. The player still starves to death every three
   turns; they just do it in a less corrupted world.

**Applied, then superseded.** `config/default.yaml` shipped 0.006 for a while
and now ships **0.028**. Both caveats above came true, in order: R-03 dropped
the clock from ~11.5 to ~3–5.6 h/turn, and R-06's engagement work halved the
typical effective multiple — so at 0.006 every 200-turn run ended DORMANT and
both new mechanisms were unobservable. The sweep behind 0.028 is in the config
comment beside the constant. This section is kept as written because the
*reasoning* is still the reasoning; only the number moved, and it moved for the
reason the caveats predicted.

---

## What replaced the old review

The previous version of this file was a twelve-issue review of DESIGN.md v0.1.0
by a design-doc reviewer, dated 2026-06-20, closing with *"Open issues: 0"*. All
twelve issues were about the document's internal consistency: PR dependency
ordering, missing schema fields, manifest drift between docs, t-shirt sizes on
the PR plan.

Every one of them was correctly identified and correctly fixed, and not one of
them was a bug in the game — because a document review cannot find a bug in
code. The document it reviewed was internally consistent, complete, well
cross-referenced, and describing a game whose clock did not tick.

It is not preserved here. Leaving "Open issues: 0" at the top of the review file
for a codebase in this condition is the exact failure mode this document exists
to correct, and keeping it alongside the list above would only invite someone to
read the reassuring half.

For the record, its twelve issues were: PR10/PR12 missing PR7+PR8 dependencies;
Evaluator scope split between PR3 and PR5; `story_pressure` and `PlotFormula`
undefined; `evil_multiplier`/`awareness_delta` missing from the location schema;
PR1/PR2 file-ownership drift; ambiguous skill paths and unspecified
`SceneRulesEngine` rules; skill/tag manifest drift between the two briefs; lore
interceptor specified before the RAG seed; undefined dice tables and inventory
schema; missing save-versioning and JSON-fallback decisions; missing
`ProcgenResult` schema and cutscene gate; and no t-shirt sizes on the PR plan.
All twelve are addressed in the current DESIGN.md.

---

## Findings after the overhaul

*Moved here verbatim from CLAUDE.md's Status section in v0.8.1, where it had
grown to ~370 lines of history inside an instruction file. CLAUDE.md now
carries the current status only; CHANGELOG.md carries each release.*

**PR1–PR12 complete. Overhaul phases P1–P11 complete. Overhaul II complete.
Overhaul III (reachability) complete.**
**2016 passing, 3 skipped in 4m49s**, no expected failures (measured
2026-09-23), plus **138 client tests** under `ui/tests/` (`npm test --prefix ui`,
which needs `npm install --prefix ui` once — `vitest` is a devDependency). Run
both for the real numbers rather than trusting this line; it has been stale
before — and was again: it read "2020 passing, 18 skipped" for a month after
v0.3.0 deleted three test files, in the sentence that warns you about exactly
that.

**THE GAME WAS SMALLER IN PLAY THAN IT WAS ON DISK, AND EVERY TEST WAS GREEN.**
Three whole subsystems and eleven registered skills had no production caller.
Each was well covered in isolation, which is exactly why nothing failed: a test
IS a caller, so a well-tested dead subsystem looks identical to a live one.

- **`engine/content/deck.py`** — `draw`/`resolve_card` were reached only by
  `scripts/simulate_decks.py` and the tests. The Wicked Garden's 11 decks / 136
  cards / 386 beats are the largest body of authored prose in the repo, and its
  only `ending_lock` sits on a card in `day_09_finale`. **The game could not be
  finished by playing it.**
- **`clocks.forced_scenes()`** — six shipped `forces_scene:` beats raised a
  world event nothing answered; 100% pending across a 40-run walk. The Garden's
  four named card-id *fragments* rather than ids, so they could never have
  resolved. THE LONG CON's entire "graph city with a deck in the middle of it"
  pitch is this coupling.
- **`engine/challenges/set_pieces.py`** — no caller, no challenge SKILL at all,
  while `docs/GOVERNANCE.md` documented it as live. Two of the flagship's four
  non-quest `doom_resistance` grants live behind it.
- **`engine/game/threads.py`** — 1177 lines, three games shipping
  `threads.yaml`, nothing that could ever create a thread, so every `thread` /
  `no_thread` gate was permanently false.

And `SKILL_FOR_ACTION` carried seven verbs while forage, work (17 jobs), sell,
haggle and craft (22 recipes) were implemented, data-complete and unreachable.
**`buy` was reachable and `sell` was not** — the economy was a pure sink with no
faucet. Meanwhile `scripts/simulate.py`, which set every balance constant in
`config/default.yaml`, drove sell/forage/work/set_piece directly: the numbers
were tuned against a game nobody could play.

All of it is wired now — `engine/content/director.py` deals a scene inside
`run_turn`, and eight new intent verbs (`card`, `sell`, `work`, `forage`,
`set_piece`, `challenge`, `bargain`, `discharge`) reach the rest. Inert by
CONSTRUCTION for the graph stories: `deck_ids()` reads `paths.decks`, the
flagship and NEON CITY declare none, so `due()` returns on its first line and
their turns are byte-identical — asserted in `tests/test_scene_director.py`
rather than assumed.

**`tests/test_reachability.py` is what makes it stay fixed.** It walks the
engine's own call graph — `engine/` only, since tests and scripts are precisely
the callers that hid the problem — and fails on a load-bearing entry point with
no production caller. It carries a positive control (`encounter`, unquestionably
live) because a detector that can only answer "dead" is not a detector, and an
explicit allowlist where an exception is deliberate, each row with its reason.

**It walks CONSTANTS too, since v0.5.0.** A call graph can only ask about things
that are called, and v0.3.0 — the largest deletion in this repo's history — left
two orphans that nothing noticed: `rng.SAFETY_REDIRECT`, a whole seeded stream
whose own comment said it was consumed by a module that no longer existed, and
`storyteller.FADE_FALLBACK_LINE`, a canned narration line citing a deleted
contract document. Neither failed anything. Both read, to the next session,
exactly like a feature somebody had not finished wiring — which is the
inheritance pattern rule 12 exists to break. The sweep is restricted to
UPPER_CASE names deliberately (seven results instead of seventy-four: a gate
that cries wolf is a gate somebody deletes) and its allowlist rots if a row
becomes read or disappears.

**THE NEXT CLASS AFTER "UNREACHABLE" IS "REACHED BUT UNNARRATED".** Overhaul III
fixed systems a player could not cause to run. What survived it was quieter:
systems that ARE live, ARE enforced, and were invisible to the narrator, so the
engine built pressure the prose could not spend. `threads.py` (1,220 lines,
three stories shipping a `threads.yaml`) gated choices and charged terms while
no narrator was ever told a contract existed — `threads.summary` has said since
it was written that it is "trimmed for a prompt block or a UI list", and only
the UI half was built. `clocks.py` (844 lines) filled in silence, so THE LONG
CON's `the_frame` dealt an authored interrogation out of a clear sky. Both reach
the prompt now (`prompts.obligations_block`, `prompts._clocks_block`), and the
eight GM-facing `label:` strings in the shipped clock tables — "How this ends up
being your fault", "The roots are counting" — are live for the first time; no
engine module had ever loaded one. Held by `tests/test_prompt_pressure.py`.

When auditing, "is it called?" is the first question and not the last. The
second is **"does the narration know?"** A mechanic the prose cannot refer to is
a mechanic the player experiences as an unexplained event.

**The widest instance of it was presence itself** (v0.8.0). `present_npc_ids`
and the PEOPLE HERE block returned early on an empty `state.procgen.npcs`, and
only the flagship runs procgen -- so in four of five stories nobody was ever in
the room: no dossier, no meeting, a cast gate that rejected a vendor standing
at her own stall, and every model-filed fact about a person dropped for want of
a known subject. Presence comes from the schedules now, and every
narrator-facing name from `npc_sim.display_name`, which never returns an id.
The same release made the engine's discarded return values speak:
`engine/game/moved.py` is a per-turn journal each system writes in its own
words (clock beats, world events, broken promises, band crossings, overheard
gossip), marked when rendered and cleared once narrated.

A third audit question fell out of that pass: **"does the prose agree with the
receipt?"** The evaluator only asked whether a roll existed. It now fails
success narrated over a failed check and arrival over a refused move -- and the
same pass found `work` reporting how a shift WENT under the key that means
whether it HAPPENED, so a bad shift was narrated as never having occurred.

**Every shipped game can now be played to an ending** — `tests/test_finales.py`,
over all five, driving `ending_lock → ending_module → epilogue`. Two of the five
could not do this at all before: THE LONG CON declared no `endings:`, no
`epilogues:` and its only quest had no `on_complete` (four stages, then
nothing), and dev-story declared three endings and emitted neither effect.

**THE SUITE RUNS IN A THIRD OF THE TIME IT DID, AND NOTHING WAS DELETED TO DO
IT.** It was 15m32s. 69% of that — 643.8s — was `test_turn_intent_per_game.py`
making real, blocking HTTP calls to LM Studio while believing it was mocked;
that file is now 11.6s and still asserts exactly what it did. Four separate
paths were reaching the model server from tests:

1. `run_turn` called `run_pipeline` with no `llm_fn`, so every story roster
   planned against the real backend. There was no way for any caller to stub
   the pipeline's agents. It now passes `session.storyteller.llm_fn`.
2. Two files stubbed the Storyteller and left the Assistant live.
3. Prompt budgeting (`default_budget` → `resolve_profile` → registry) queries
   the model list to size a prompt, BEFORE the injected `llm_fn` short-circuit —
   so no amount of agent stubbing could have helped.
4. `chat_probe`'s rewrite moved posting onto an `httpx.Client` instance, which
   silently un-mocked seven `test_lmstudio_health.py` tests. They had been
   passing against the live server, in the file that opens "Everything here is
   mocked".

None of it failed anything. The pipeline swallows model outages by design and
the real server answers much like the fixtures, so the only symptom was the
clock — and quiet non-determinism, since a live model's plans vary per run.

**`tests/conftest.py::_no_live_model_calls` is what makes it stay fixed**: any
test opening a connection to the configured model server fails, unless marked
`@pytest.mark.live`. It records the breach and asserts at TEARDOWN, because the
first version raised at the call site and the pipeline's own error tolerance
swallowed it — the guard was defeated by exactly the forgiveness that hid the
bug. Discovery, the native probe and the summarizer are pinned to deterministic
offline answers beside it; `test_vertical_slice.py` had pinned the summarizer
for itself since it was written ("a playtest must not depend on a local model
being up") and was the only file that did.

**`npm test` needs its devDependencies installed**, which a `ui/node_modules`
carrying only the runtime does not have — `vitest` is a devDependency and the
script fails with "'vitest' is not recognized" until `npm install --prefix ui`
has run once. The 138 above is measured, not inherited: 6 files, 138 passing
(store, veiled, narrative-log, choice-row, negotiation-panel, plugin-contract),
re-measured 2026-09-20.

Two fixes landed from playing against a live LM Studio. **The evaluator checks
the cast** (`engine/agents/cast.py`): the persona's "never introduce a named
character who is not present" was unenforced, and a measured turn 0 in
`forest_clearing` opened on `Ilya's lantern` — an NPC three locations away,
imported from the few-shot examples. The absent set is the same
`present_npc_ids` call the turn schema's `npc_id` enum is built from, so no
second notion of "present" exists. **The LM Studio routes are deliberate**
(`engine/lmstudio/routes.py`): the model list is `GET /api/v1/models` and
nothing else, validated by the SHAPE of the body, because this server answers
routes it does not serve with 200 and an error blob — `/v1/models` was firing
one `Unexpected endpoint or method` ERROR per doctor run.

The engine/story seam is done. What landed: the multi-agent turn
(plan → negotiate → commit, `engine/agents/pipeline.py`), the finale chain
(lock → Speak·Act·Seal → epilogue), a story-declared UI plugin (`ui.plugin`),
and the removal of one story's content from the engine's defaults. What that
last one fixed is worth stating plainly, because it was invisible for months:
every story that omitted a `paths.*` key silently read The Clockwork Dark's
content, and every story that omitted `paths.prompts` got a narrator who
introduced itself as the Storyteller of The Clockwork Dark.

**The intent loop is now proven in every game, not just the flagship**
(`tests/test_turn_intent_per_game.py`, parametrised over
`registry.discover()`). The MECHANISM was always story-agnostic; the AUTHORING
was not. Only the flagship's opening had ever declared an `intent`, so The
Wicked Garden's "Step through" — which *is* the crossing its whole first act
hangs on — was a sentence handed to a narrator with the engine never asked, and
NEON CITY and dev-story opened the same way. All three templates under
`scripts/story_template/` taught the bug too, so a fresh scaffold inherited it.
Every opening that means a mechanic now declares one, and each is driven
through a real `run_turn` with the outcome read off `GameState`.

Two things that fell out of doing it. **A story with no `survival.yaml` could
walk itself into a stamina soft-lock**: travel spent stamina, no rest verb
exists for such a story, and the Garden measured a refusal on its FOURTEENTH
leg with nothing able to give any back — CLAUDE.md rule 6's soft-lock rebuilt
by absence instead of by a gate. `GameEngine.move_to` now prices stamina only
where `survival.rest_kinds()` is non-empty; the flagship and NEON CITY are
untouched. And **the legality probe was noisy**: asking whether `rest` or
`check` was legal logged a WARNING per turn naming `survival.yaml`/`skills.yaml`
for the two stories that deliberately ship neither. A fixed-name file absent
from a rules directory that EXISTS is now DEBUG ("ships none of this"); a
declared rules directory that does not exist is still a WARNING.

The client is three story plugins (`clockwork-dark`, `wicked-garden`,
`neon-city`) plus **the engine's own** (`_engine`), which is what a story gets
when it declares no `ui.plugin` and what `dev-story` wears. That last one
replaced a bad pair of options: run on bare `CORE_ONLY` and look broken rather
than plain, or borrow another STORY's plugin and inherit its voice with its
spacing. `_engine` is a real skin that deliberately has no world — quiet
neutral palette, a wordmark that renders the running story's name, onboarding
about what a turn is rather than about any fiction. Nothing shipped borrows
another story's plugin now, so that path is held by
`ui/tests/plugin-contract.test.js` rather than by a running game.

The committed `content/scenes/clockwork/static/dist` is rebuilt from `ui/src`,
and `ui/` has its own test suite — the plugin contract across every shipped
plugin, the core reducer, and the veiled-meter rule.

Also landed since: `craft_item` with degree outcomes, foraging that discovers
hidden-path travel shortcuts, carry weight priced on travel (never on rest),
and the served notice board (`GET /api/notices`).

Five games ship: `clockwork-dark` (flagship), `wicked-garden` (the deck
exemplar), `neon-city` (NEON CITY: THE CROSSING — survival/expedition in the
NeonCity canon, graph-shaped with the timestamp/debt clocks and threads wired
in, and its own bespoke UI plugin: black canvas, cyan accent, gold mono ₵, the
heat ladder as chrome), `the-long-con` (THE LONG CON — noir, and the first
HYBRID: a full graph city that also declares decks and a clock, so `the_frame`
filling deals an authored interrogation mid-run through `forces_scene`) and
`dev-story` (the annotated bench). Pick one with `launcher.py --game <slug>`.

`slow-water` was **deleted** after doing its job. It was a proving run for the
story-creation suite, not a story anyone should maintain: scaffolded, drafted
from a bible, repaired, promoted, hand-finished. Drafting it found four shapes
the model produces that **load, validate and play** while doing nothing or
saying the quiet part out loud — an `on_fail` behind a gate that cannot fail, a
`value` effect wearing an item row's fields, a beat that gates and bands, and
`text: composure +1` in the slot the player reads. Three are now ungrammatical
in the drafting schema; all four are caught by `engine/games/validation.py` for
hand-written content. The lessons outlived the story: see
[docs/AUTHORING.md](docs/AUTHORING.md) §4.1.

`drowned-carillon` was **deleted**. It was the flagship with different nouns,
which made it a poor proof of the engine/story seam — it could not fail in any
way the flagship would not, and it had rotted unnoticed. The Wicked Garden is
the second story now, and it shares almost nothing with the flagship, which is
the point.

Closed: **R-01** (prompt budget overflow), **R-02** (`SceneRulesEngine` never
called), **R-03** (the clock — 10.02 → **3.91** mean h/turn across the five policies,
deaths 129 → **32** total, re-measured 2026-08-14),
**R-05** (no repeatable food economy — foraging closes it; the `pauper` policy
now takes **zero starvation deaths** in 200 turns, forages 93 meals, works no
shifts and ends on 52 gold from a starting 5. It is not literally gold-free —
one 12-gold purchase, through the bakery restock every policy shares — and the
older "spending zero gold" line has been corrected in DESIGN_REVIEW.md),
**R-06** (the doomsday clock now
answers to conduct: widened per-location multipliers plus earned
`doom_resistance` put the disengaged baker at 2.03× the engaged hero's evil
per in-game day — 0.0143 vs 0.0070 — where every playstyle used to land
within 13%; the median 200-turn run ends in SPREADING; measured by the new
`hero` policy in `scripts/simulate.py`).

The design review's open-issue list is empty.

Closed in Overhaul III, beyond the reachability work above: **the turn payload
disagreed with the save** (quest rewards applied AFTER `to_client_dict`, so the
screen showed the purse from before the reward and a quest-fired ending reported
a turn late); **one LM Studio blip pinned "Storyteller unreachable" for the whole
session** (`_llm_failed` was set in `__init__` and never lowered);
**`POST /api/game/choice` ran turns with no session lock**; **the save index was
an unlocked read-modify-write** on a process-wide singleton, so concurrent
autosaves lost each other, and it was 537 KB / 1302 rows re-parsed and fsynced
every turn with nothing that ever pruned one; **prompt eviction popped the
running summary before turn history**, inverting `EVICTION_ORDER`, and
everything appended after `fit()` was outside the budget it computed; **a
safety-REFUSED input still committed both agents' effects**; **every duration ran
a day long** (`{days: 1}` lasted two — fixed at the conversion via
`effects.duration_day`, NOT at the sweep comparator, because
`economy._record_shift` stamps `expires_day = world_day` for "today only" and a
`<=` there would reset the work cap every intra-day tick); and **`crit_success`
was mathematically unreachable** — margin 10 over DC 13 needs a total of 23
against a best-in-game +4, so it was a 5% band for one archetype and impossible
for the rest, with `forge_bellows`'s payout, its 1.6× wage, three reputation
rows and `craft_item`'s batch bonus all dead behind it.

Re-measured after the duration fix: **31 deaths across the five policies**
(baseline 32) and the R-06 doom asymmetry holds at **1.96×** engaged-to-
disengaged (baseline 2.03×). Nothing material moved.

The MCP tool layer landed: `engine/mcp/skills_server.py` reflects the `@skill`
registry into a real MCP server (`fastmcp`, SSE, in-process so skills still
resolve through `get_active_engine()`), and `native.py`/`backend.py` learned
LM Studio's `integrations` parameter. `integrations` is a reason to INSIST on
the native transport rather than to avoid it: it is the only route that reads
the key, and the only one that can turn reasoning off.

**A turn now calls it.** `engine/agents/mechanics.py` is Phase A — mechanics,
reasoning off, tools, no grammar — and it runs BEFORE the `StateTransaction`
opens in `storyteller.run_turn`, so a skill it resolves is not rolled back by an
evaluator retry that LM Studio would never hear about. Its receipts reach Phase
B through `prompts.receipts_block`, the block that has said "MECHANICAL RESULTS
-- AUTHORITATIVE" since it was written. Off by default (`lmstudio.mcp.enabled`),
byte-identical to the old turn when off, and degrading to `[]` and a logged
warning on every failure. Proven live by `scripts/two_phase_live_proof.py`: the
model called `query_evil_state`, the receipt reached the prompt, and the
narration reported `dormant` instead of guessing at it.

**Ephemeral MCP was re-tested and is genuinely unusable here** (2026-08-15).
All seven forms — SSE and streamable-HTTP, `localhost`, `127.0.0.1`, `[::1]`,
the LAN IP, the hostname, and a URL already in `mcp.json` — return "URL
resolves to a non-public address". The LAN IP settles it: routable and still
refused, so the check covers RFC1918, not just loopback. A *closed* port gets
HTTP 400 with no connection attempted, which puts the refusal at address
validation. `mcp.json` is required; entries are written atomically under the
`engine-skills-` prefix, backed up once per process, and removed on release.

See [docs/DESIGN_REVIEW.md](docs/DESIGN_REVIEW.md) for the measurements behind
each. Three **NOT WIRED** tables remain, each naming its file:
[GOVERNANCE.md](docs/GOVERNANCE.md) (the notice board's browser half, plus the
challenge/scene/negotiation panels — all presentation gaps, none of them
playability gaps, because those systems reach the player as ordinary choice
chips), [STATE.md](docs/STATE.md) (an ending's authored `tease:`, which no story
declares) and [AGENTS.md](docs/AGENTS.md) (the unmeasured reasoning cost of the
two plan calls — its MCP row is gone, retired by wiring the caller rather than
by rewording the claim).

**These tables are no longer the only guard, and that is the point.** The
2026-08-14 audit declared GOVERNANCE.md down to one surviving row while
challenges sat documented as live with no caller anywhere in `engine/`. Debt
that nobody writes a row for is invisible in a repo that records debt in prose
and has zero TODO/FIXME markers by convention — there is nothing to grep.
`tests/test_reachability.py` answers that mechanically now.

Still open and deliberately deferred, recorded here rather than fixed:
neon-city ships **zero** art plates against 75 subjects, its entry location
included; the Garden has 11 of 23 endings unreachable and 4 orphan cards; and
`mortal_threshold`, the Garden's ENTRY location and where its ten-card prologue
plays out, is one of six the art manifest lists as having no plate on purpose —
so a new player sees no scene art until the prologue ends. The studio review
queue can now keep one draft (`POST /api/studio/draft/accept`); it still does
not draft from the browser.

**THE LONG CON's tables were the graph template's, and the veneer hid it.**
Closed in v0.7.1. It sold mushrooms as cigarettes literally: `economy.yaml`
carried noir display names (`"Cigarettes, loose"`, `"A watch with the name filed
off"`) over the template's `hedge_berries` and `old_coin` — and `trade.py` takes
every display name from `inventory.name_of(item_id)`, so that key was read by
NOTHING and the player was offered "Hedge Berries" in a 1940s crime story. Three
more things were wrong underneath it: the only vendor profile named
`npc_miller`, who exists nowhere in the story (`browse` answered "Nobody trades
here as npc_miller") while the fence who does stand there had no profile; the
one job hauled sacks at a mill the city does not contain; and `forage.yaml` was
86 lines matching no location tag, in a story whose `rest_kinds()` is empty and
where nothing eats. The goods now move `heat` and `standing` through `use:`
blocks, which is the counterplay the case lacked — every quest stage adds heat
and spends standing, and nothing spent the other way.

`tests/test_livelihood_per_game.py` is what makes it stay fixed, and the reason
it did not catch this is worth keeping: its `GAMES` tuple held one entry, so a
story that declares `paths.economy`, `paths.tables` and jobs was never once
driven through it. Two new tests hold the seam the old ones missed — a vendor
profile must name an NPC the story SCHEDULES, and a vendor with stock must have
a profile, because `economy.yaml` and `trade.yaml` are both keyed on NPC ids and
nothing made them agree.

**One order-dependent test was found and fixed rather than recorded.**
`test_world_advances_over_a_session` passed alone, passed in the full suite,
and failed in between, watching `advance_time` produce exactly zero evil. The
config, the active slug and the loaded locations were IDENTICAL in the passing
and failing cases, which is why it read as flakiness rather than as state: the
only difference was `evil_ticker._DOOM_DECLARED`, a module-level memo of
"does the running story have a doom clock at all". `tests/test_scene_seam.py`
monkeypatches `entry_manifest` to a synthetic manifest without activating
anything, something asks `doom_enabled()` inside that window, and the answer —
False, because that manifest declares no doom — outlives the patch. The
registered invalidator only runs on activation, and nothing activated.

An autouse fixture in `tests/conftest.py` now nulls every memo in
`caches.NULLED_ATTRIBUTES` after each test. Deliberately NOT
`reset_all_caches()`: that also reruns the LM Studio reloaders, which are
config-derived rather than manifest-derived, cannot be poisoned this way, and
cost the suite 3m40s → 6m35s plus two prompt-budget failures when a cleared
profile cache resolved the budget from config fallbacks. The scoped version
costs about 30s (3m40s → 4m10s) and is held by a PAIR of tests in
`test_session_isolation.py` — the first poisons the memo and deliberately does
not clean up, the second asserts the world still ticks — because the obvious
single-test version passes with or without the fixture and guards nothing.

