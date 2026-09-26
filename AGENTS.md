# AGENTS.md — The Clockwork Dark

The operating rules for any coding agent changing this repository. Tool-neutral: Claude Code reads it through `CLAUDE.md`'s import, and other agents read it directly.

Not to be confused with [docs/AGENTS.md](docs/AGENTS.md), which documents the IN-GAME agents (roster, plan, negotiate, commit).

Local-first AI RPG: a deterministic engine holds truth and LLM agents narrate it. Six stories ship under `games/<slug>/`; the engine is story-agnostic.

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
12. **Never add a content-rating or "safety" layer.** One was built on
    2026-08-13 and removed on 2026-08-15 at the owner's instruction (release
    v0.3.0, 5207 deletions). Do not rebuild it in any form: no intensity
    tiers, no ceiling, no boundary sheet, no fade control, no `safety:` block in
    a manifest, no register line in an authoring prompt.

    **Why it is a rule and not a preference.** It did not merely filter — it put
    content-rating language into the STORYTELLER system prompt on every turn
    (`"CONTENT LIMITS (product layer -- above every character's wants):
    Intensity in force: <tier>…"`) and into the story-DRAFTING prompt
    (`"Allusive at most; nothing explicit."`). Modelling "how explicit is this"
    as a first-class axis makes it the axis: the effect was narrators that
    treated the engine as a presumed sexual-content system. The test that
    asserted the prompt was unchanged skipped for exactly the three games where
    the injection fired, so it went unmeasured for two days.

    This is a LOCAL, single-player, single-author tool. The narration comes from
    whatever model the owner has loaded, on their own machine, for their own
    fiction. The register is set by `games/<slug>/prompts/storyteller.md` and by
    that model — it is not the engine's business, and it is not an agent's
    business to install a quieter version of one and document it as a feature.

    Note how it survived: each instance that came after inherited it as existing
    code, which this file's own authority order ranks above every document, and
    treated its unwired halves as debt to complete rather than as evidence
    nobody wanted it. If you find yourself specifying the fix for a missing
    piece of it, you have made that mistake.

## Working conventions

These are how every change lands. Each one exists because its absence cost
something measurable; the reasons are in CHANGELOG.md and docs/DESIGN_REVIEW.md.

**Releases.** A commit subject is a bare version number (`v0.8.1`); every detail
goes in the body. `CHANGELOG.md` is the authority from 0.4.0 on and is updated
IN THE SAME CHANGE as the code: work in progress goes under `## [Unreleased]`,
and a release renames that section to `## [x.y.z] — YYYY-MM-DD`. Bump
`pyproject.toml` and `ui/package.json` to the same number.
`tests/test_release_hygiene.py` fails the suite when these disagree. A MINOR
bump is something a player or an author would notice; a PATCH is repair.
Describe engine SCOPE in commit bodies, never a content-policy decision (see
rule 12). Nothing is pushed without the owner's explicit word.

**Docs move with the change.** Each story keeps `games/<slug>/CHANGELOG.md`
and `games/<slug>/README.md` for its own content; the root `CHANGELOG.md` and
`README.md` cover the engine and the release. Any change updates, in the same
commit, every doc it makes stale: the affected story's CHANGELOG
(`## [Unreleased]`) and README; the root CHANGELOG and README for an engine
change; CLAUDE.md when the status, the roadmap or the deferred list moves;
and this file when a rule or convention does. "Updated" means reviewed and
cleaned up, not appended to: anything no longer true or relevant is removed.
A release renames each touched story's `## [Unreleased]` to the release's
heading, as the root file does. It exists because docs that drifted from the
code were a finding in almost every review this repo has had.
`tests/test_release_hygiene.py` checks that every story keeps a README that
links its CHANGELOG, and a CHANGELOG whose `## [Unreleased]` sits above its
releases, whose release headings are written the root's way (em dash and
date), newest first, never repeated, each a version the root CHANGELOG has
and none newer than `pyproject.toml`'s.

**Tests.** A fix ships with a test that FAILED against the code before it, and a
guard is canary-checked by reintroducing the bug it guards. A test that
activates a story is cleaned up by `tests/conftest.py::_no_story_outlives_its_test`;
one that opens a connection to the model server fails unless marked
`@pytest.mark.live` (`_no_live_model_calls`).

**Time and randomness in new systems.** A new system advances on IN-GAME hours
inside `clock.advance_time`, never on the background world tick, which is
wall-clock by design (issue R-03). Whether a guard heard about a crime must
replay from the seed and the choices, not from how long the menu sat open.
Each system draws its own named stream from `engine/game/rng.py`.

**The three audit questions.** For any mechanic: (1) *is it called?* --
`tests/test_reachability.py` asks this mechanically of skills and constants,
not of plain functions; (2) *does the narration know?* -- a mechanic the prose
cannot refer to is one the player experiences as an unexplained event; (3)
*does the prose agree with the receipt?* -- the evaluator fails success
narrated over a failed check and arrival over a refused move.

**Debt is written down, not implied.** The repo carries zero TODO/FIXME markers
by convention. Unwired work is a row in a NOT WIRED table naming its file
(`docs/GOVERNANCE.md`, `docs/STATE.md`, `docs/AGENTS.md`), per rule 9.

**The client.** `ui/src` builds into the COMMITTED
`content/scenes/clockwork/static/dist`; rebuild and commit it in the same
change (see "Verify a checkout").

**Story content** lives under `games/<slug>/` and is written against
docs/AUTHORING.md, not against engine source. A story that does not declare a
`paths.*` key pays nothing for that system, and its turns stay byte-identical --
asserted by test for every optional system.

## Verify a checkout

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py            # environment, config, content
.\.venv\Scripts\python.exe -m pytest tests\ -q          # fully green, no xfail; time in CLAUDE.md
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
