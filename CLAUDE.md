# CLAUDE.md — The Clockwork Dark

This file guides Claude Code (and other coding agents) when working in this repository.

## Start here

1. **Read** [docs/DESIGN.md](docs/DESIGN.md) — vision, mechanics, glossary, architecture
2. **Read** [docs/DESIGN_REVIEW.md](docs/DESIGN_REVIEW.md) — what the overhaul found and what is still open
3. **Read** [docs/CLAUDE_CODE_BRIEF.md](docs/CLAUDE_CODE_BRIEF.md) — build spec and golden rules. Parts of it are historical and marked **CURRENT:** where they have drifted
4. For visual/asset work, use [docs/CLAUDE_DESIGN_BRIEF.md](docs/CLAUDE_DESIGN_BRIEF.md) instead
5. For story/content work — creating a story, editing a `games/<slug>/` tree,
   or using the authoring tools — read [docs/AUTHORING.md](docs/AUTHORING.md)
   first. It is the document that replaces reading engine source for that job

Authority order when they disagree: **the code**, then DESIGN.md, then
DESIGN_REVIEW.md, then CLAUDE_CODE_BRIEF.md.

## Critical rules

1. **Engine resolves mechanics; LLMs narrate.** A choice that moves, spends or risks anything declares a structured `intent` (`engine/game/intents.py`); the engine executes it through the `@skill` entry points BEFORE the next narration and hands the receipt back as prompt input. The enums are built per turn from what the engine will actually accept, so an illegal target is unsamplable. An illegal-at-execution intent produces an engine-authored **refusal** that reaches the prose — never a silent no-op. Do NOT reach for `tool_calls`: the turn grammar forbids that key, which is exactly how "a narration turn cannot change the world" survived for months.
2. **`clock.advance_time` is the only writer of world time.** `world_day`, `world_hour` and `time_of_day` are derived read-only properties.
3. **`effects.apply_effect` is the only writer of game state.** Quest rewards, boons, encounter outcomes and death all funnel through it.
4. **Never use bare `random`.** Use `world_rng(state, STREAM)` so a seed replays and one system's rolls do not shift another's.
5. **Never hardcode** ports, model names, or paths — use `config/default.yaml` via `get_config()`. Machine-specific paths go in `config/local.yaml` (gitignored, deep-merged).
6. **Never gate rest.** It is the only thing that restores stamina; a gate rebuilds a soft-lock the game shipped with.
7. **Reuse patterns** from [CosySim](https://github.com/nihilistau/CosySim) and [Archives of Anubis](https://github.com/nihilistau/Achieves-Of-Anubis) before writing new code.
8. **Prove with tests** — run `pytest` before declaring work complete. Expect fully green, no `xfail`.
9. **Do not document a mechanism you did not wire.** Mark it **NOT WIRED** with its file. A design doc describing code that never runs is how this codebase got into trouble.
10. **Run `scripts/simulate.py` before changing a balance constant.** Every number here was originally chosen against a clock that did not tick.
11. **Windows-aware** — LM Studio at `http://localhost:1234/v1`; use `scripts/start.ps1` or `launcher.py --stack`.

## Project summary

Local-first AI RPG: deterministic hard engine + two autonomous agents (Storyteller + Assistant). ComfyUI/Grok images, local Voxtral TTS/STT — all generation off by default; the shipped art pack and text fallbacks are what runs out of the box. Player starts at the forest edge; evil ticks in the background whether they become a hero or a baker.

## Status

**PR1–PR12 complete. Overhaul phases P1–P11 complete. Overhaul II complete.
Overhaul III (reachability) complete.**
**2020 passing, 18 skipped in 3m38s**, no expected failures (measured
2026-08-15), plus **126 client tests** under `ui/tests/` (`npm test --prefix ui`,
which needs `npm install --prefix ui` once — `vitest` is a devDependency). Run
both for the real numbers rather than trusting this line; it has been stale
before.

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
has run once. The 95 above is measured, not inherited: 4 files, 95 passing
(store, veiled, narrative-log, plugin-contract), re-measured 2026-08-15.

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
the served notice board (`GET /api/notices`), and the safety layer wired
end-to-end — input review, a pre-commit `SafetyCeiling`, and narration review
with fade cards. The card now RENDERS (`ui/src/core/parts/FadeCard.jsx`, drawn
by `Play.jsx` under the log), which was the open half. See docs/SAFETY.md.

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
each. Four **NOT WIRED** tables remain, each naming its file:
[GOVERNANCE.md](docs/GOVERNANCE.md) (the notice board's browser half, plus the
challenge/scene/negotiation panels — all presentation gaps, none of them
playability gaps, because those systems reach the player as ordinary choice
chips), [SAFETY.md](docs/SAFETY.md) (cosmetic rename on display labels, **the
player boundary sheet**, and **the Fade control** — the last two were documented
as player-facing and neither exists: `set_policy` has no production caller and
`fade_available` has no reader, so the limits sheet is permanently empty),
[STATE.md](docs/STATE.md) (an ending's authored `tease:`, which no story
declares) and [AGENTS.md](docs/AGENTS.md) (the unmeasured reasoning cost of the
two plan calls — its MCP row is gone, retired by wiring the caller rather than
by rewording the claim).

**These tables are no longer the only guard, and that is the point.** The
2026-08-14 audit declared GOVERNANCE.md down to one surviving row while
challenges sat documented as live with no caller anywhere in `engine/`. Debt
that nobody writes a row for is invisible in a repo that records debt in prose
and has zero TODO/FIXME markers by convention — there is nothing to grep.
`tests/test_reachability.py` answers that mechanically now.

Still open and deliberately deferred, recorded here rather than fixed: THE LONG
CON's tables and items are still the graph template's (it sells mushrooms as
cigarettes); neon-city ships **zero** art plates against 75 subjects, its entry
location included; the Garden has 11 of 23 endings unreachable and 4 orphan
cards; `engine/studio/api.py:14` documents a `POST /api/studio/draft/accept`
route that does not exist, so there is still no path from the studio to live
content.

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

## Verify a checkout

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py            # environment, config, content
.\.venv\Scripts\python.exe -m pytest tests\ -q          # fully green, no xfail, ~3m20s
npm ci --prefix ui; npm test --prefix ui                # the client: plugins, reducer, veiled rule
npm run build --prefix ui                               # rebuild the COMMITTED dist after any ui/src change
.\.venv\Scripts\python.exe launcher.py --check          # local services and what each outage costs
.\.venv\Scripts\python.exe scripts\simulate.py --policy all --turns 200
```

The build output is `content/scenes/clockwork/static/dist`, and it is
**committed** so the game plays with no node installed. Change `ui/src` without
rebuilding and the change never reaches a player — so
`test_the_committed_build_is_not_behind_its_source`
(`tests/test_ui_contract.py`) fails the suite when any build input carries a
commit the build does not, and names the files that are ahead. It reads git
history rather than mtimes, because a fresh clone has no meaningful mtimes, and
it skips cleanly where history cannot be read: no `.git`, no `git` on PATH, or a
rebuild still sitting uncommitted. Rebuild and commit `dist` in the same change
and it passes.

## Canon IDs (do not rename)

- Agents: `clockwork_storyteller`, `clockwork_assistant`
- Locations: `forest_clearing`, `edgewood_square`, `edgewood_bakery`, `tinker_caravan`, `millhaven_gate`
- Evil phases: `dormant`, `stirring`, `spreading`, `consuming`
- Arcs: `quiet_life`, `whisper`, `march`, `convergence`
- Skills: `persuasion`, `stealth`, `sympathy`, `lore`, `craft`, `survival`, `nerve`
- Difficulty bands: `trivial`, `easy`, `standard`, `hard`, `severe`, `legendary`
