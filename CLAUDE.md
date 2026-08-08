# CLAUDE.md — The Clockwork Dark

This file guides Claude Code (and other coding agents) when working in this repository.

## Start here

1. **Read** [docs/DESIGN.md](docs/DESIGN.md) — vision, mechanics, glossary, architecture
2. **Read** [docs/DESIGN_REVIEW.md](docs/DESIGN_REVIEW.md) — what the overhaul found and what is still open
3. **Read** [docs/CLAUDE_CODE_BRIEF.md](docs/CLAUDE_CODE_BRIEF.md) — build spec and golden rules. Parts of it are historical and marked **CURRENT:** where they have drifted
4. For visual/asset work, use [docs/CLAUDE_DESIGN_BRIEF.md](docs/CLAUDE_DESIGN_BRIEF.md) instead

Authority order when they disagree: **the code**, then DESIGN.md, then
DESIGN_REVIEW.md, then CLAUDE_CODE_BRIEF.md.

## Critical rules

1. **Engine resolves mechanics; LLMs narrate.** All dice, combat, inventory, and travel go through `@skill` tools.
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

**PR1–PR12 complete. Overhaul phases P1–P11 complete. Overhaul II waves 1–2
complete.** ~1360 tests passing, no expected failures. Run `pytest` for the
real number rather than trusting this line — it has been stale before.

The engine/story seam is the current work. What landed: the multi-agent turn
(plan → negotiate → commit, `engine/agents/pipeline.py`), the finale chain
(lock → Speak·Act·Seal → epilogue), a story-declared UI plugin (`ui.plugin`),
and the removal of one story's content from the engine's defaults. What that
last one fixed is worth stating plainly, because it was invisible for months:
every story that omitted a `paths.*` key silently read The Clockwork Dark's
content, and every story that omitted `paths.prompts` got a narrator who
introduced itself as the Storyteller of The Clockwork Dark.

Two games ship: `clockwork-dark` (flagship) and `wicked-garden`. Pick one with
`launcher.py --game <slug>`.

`drowned-carillon` was **deleted**. It was the flagship with different nouns,
which made it a poor proof of the engine/story seam — it could not fail in any
way the flagship would not, and it had rotted unnoticed. The Wicked Garden is
the second story now, and it shares almost nothing with the flagship, which is
the point.

Closed: **R-01** (prompt budget overflow), **R-02** (`SceneRulesEngine` never
called), **R-03** (the clock — 10.02 → 4.40 mean h/turn, deaths 129 → 35),
**R-05** (no repeatable food economy — foraging closes it; the `pauper` policy
now survives 200 turns spending zero gold).

Still live: **R-06**. The doomsday clock diverges by playstyle far more than it
did — 467 turns to CONSUMING for a reckless player against 1109 for a cautious
one — but that is mostly the *turn cost* of those lives differing, not the rate.
Per in-game day the baker and the reckless player are still within 13%
(0.00564 vs 0.00635), because the location multiplier and the inaction bonus
remain the same size and opposite in sign. The cause named in the review is
untouched.

See [docs/DESIGN_REVIEW.md](docs/DESIGN_REVIEW.md) for the measurements behind
each, and the **NOT WIRED** tables in [docs/GOVERNANCE.md](docs/GOVERNANCE.md)
for what is built but not yet called.

## Verify a checkout

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py            # environment, config, content
.\.venv\Scripts\python.exe -m pytest tests\ -q          # green, 1 xfail
.\.venv\Scripts\python.exe launcher.py --check          # local services and what each outage costs
.\.venv\Scripts\python.exe scripts\simulate.py --policy all --turns 200
```

## Canon IDs (do not rename)

- Agents: `clockwork_storyteller`, `clockwork_assistant`
- Locations: `forest_clearing`, `edgewood_square`, `edgewood_bakery`, `tinker_caravan`, `millhaven_gate`
- Evil phases: `dormant`, `stirring`, `spreading`, `consuming`
- Arcs: `quiet_life`, `whisper`, `march`, `convergence`
- Skills: `persuasion`, `stealth`, `sympathy`, `lore`, `craft`, `survival`, `nerve`
- Difficulty bands: `trivial`, `easy`, `standard`, `hard`, `severe`, `legendary`
