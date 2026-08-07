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
8. **Prove with tests** — run `pytest` before declaring work complete. Expect green with exactly one `xfail` (a real defect, R-01, not a flaky test).
9. **Do not document a mechanism you did not wire.** Mark it **NOT WIRED** with its file. A design doc describing code that never runs is how this codebase got into trouble.
10. **Run `scripts/simulate.py` before changing a balance constant.** Every number here was originally chosen against a clock that did not tick.
11. **Windows-aware** — LM Studio at `http://localhost:1234/v1`; use `scripts/start.ps1` or `launcher.py --stack`.

## Project summary

Local-first AI RPG: deterministic hard engine + two autonomous agents (Storyteller + Assistant). ComfyUI/Grok images, local Voxtral TTS/STT — all generation off by default; the shipped art pack and text fallbacks are what runs out of the box. Player starts at the forest edge; evil ticks in the background whether they become a hero or a baker.

## Status

**PR1–PR12 complete. Overhaul phases P1–P11 complete.** 600+ tests passing, 1 expected failure.

There is no next PR. Open work is the issue list in
[docs/DESIGN_REVIEW.md](docs/DESIGN_REVIEW.md) — the live ones are the prompt
budget overflow (**R-01**), the unwired `SceneRulesEngine` (**R-02**), the clock
running at ~11.5 in-game hours per turn (**R-03**), the missing repeatable food
economy (**R-05**), and every playstyle converging on the same doomsday clock
(**R-06**).

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
