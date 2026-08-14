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

**PR1–PR12 complete. Overhaul phases P1–P11 complete. Overhaul II complete.**
**1730 passing, 19 skipped**, no expected failures (measured 2026-08-14), plus
**95 client tests** under `ui/tests/` run by `npm test --prefix ui`. Run both
for the real numbers rather than trusting this line — it has been stale before.

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

The client is now three plugins for four stories (`clockwork-dark`,
`wicked-garden`, `neon-city`; `dev-story` borrows the Garden's), the committed
`content/scenes/clockwork/static/dist` is rebuilt from `ui/src`, and `ui/` has
its own test suite for the first time — the plugin contract across every
shipped plugin, the core reducer, and the veiled-meter rule.

Also landed since: `craft_item` with degree outcomes, foraging that discovers
hidden-path travel shortcuts, carry weight priced on travel (never on rest),
the served notice board (`GET /api/notices`), and the safety layer wired
end-to-end — input review, a pre-commit `SafetyCeiling`, and narration review
with fade cards. The card now RENDERS (`ui/src/core/parts/FadeCard.jsx`, drawn
by `Play.jsx` under the log), which was the open half. See docs/SAFETY.md.

Four games ship: `clockwork-dark` (flagship), `wicked-garden` (the deck
exemplar), `neon-city` (NEON CITY: THE CROSSING — survival/expedition in the
NeonCity canon, graph-shaped with the timestamp/debt clocks and threads wired
in, and its own bespoke UI plugin: black canvas, cyan accent, gold mono ₵, the
heat ladder as chrome), and `dev-story` (the annotated bench, which borrows the
Garden's skin and is the shipped proof the borrow path still works). Pick one
with `launcher.py --game <slug>`.

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

See [docs/DESIGN_REVIEW.md](docs/DESIGN_REVIEW.md) for the measurements behind
each. Four **NOT WIRED** tables remain, one row apiece, each naming its file:
[GOVERNANCE.md](docs/GOVERNANCE.md) (the notice board's browser half),
[SAFETY.md](docs/SAFETY.md) (cosmetic rename on display labels),
[STATE.md](docs/STATE.md) (an ending's authored `tease:`, which no story
declares) and [AGENTS.md](docs/AGENTS.md) (the unmeasured reasoning cost of the
two plan calls).

## Verify a checkout

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py            # environment, config, content
.\.venv\Scripts\python.exe -m pytest tests\ -q          # fully green, no xfail
npm ci --prefix ui; npm test --prefix ui                # the client: plugins, reducer, veiled rule
npm run build --prefix ui                               # rebuild the COMMITTED dist after any ui/src change
.\.venv\Scripts\python.exe launcher.py --check          # local services and what each outage costs
.\.venv\Scripts\python.exe scripts\simulate.py --policy all --turns 200
```

The build output is `content/scenes/clockwork/static/dist`, and it is
**committed** so the game plays with no node installed. Nothing detects a stale
one: change `ui/src` without rebuilding and the change simply never reaches a
player.

## Canon IDs (do not rename)

- Agents: `clockwork_storyteller`, `clockwork_assistant`
- Locations: `forest_clearing`, `edgewood_square`, `edgewood_bakery`, `tinker_caravan`, `millhaven_gate`
- Evil phases: `dormant`, `stirring`, `spreading`, `consuming`
- Arcs: `quiet_life`, `whisper`, `march`, `convergence`
- Skills: `persuasion`, `stealth`, `sympathy`, `lore`, `craft`, `survival`, `nerve`
- Difficulty bands: `trivial`, `easy`, `standard`, `hard`, `severe`, `legendary`
