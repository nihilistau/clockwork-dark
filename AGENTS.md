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
11. **Platform-neutral, server-agnostic.** Windows and Linux are both
    supported: no code assumes a path separator, a drive letter, a
    case-insensitive filesystem or an `.exe`, and every script has a
    PowerShell and a POSIX way in (`scripts/start.ps1`, `scripts/start.sh`).
    LM Studio at `http://localhost:1234/v1` is the default model server;
    vLLM, llama-server, Ollama and OpenAI-compatible servers are set by
    `llm.provider` (docs/MODEL_SERVERS.md). Local single-player is the
    default; hosted mode (`hosting.enabled`, docs/HOSTING.md) is opt-in.
    Use `scripts/start.ps1` / `scripts/start.sh` or `launcher.py --stack`.
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
one that opens a connection to the model server, or resolves or connects to
any host that is not loopback, fails unless marked `@pytest.mark.live`
(`_no_live_model_calls`, default-deny: stub the client instead). LM Studio's `mcp.json` is
redirected into every test's temp directory, a write outside it fails the
test, and a real skills server starts only under `@pytest.mark.mcp_server`
(`_no_owner_lm_studio_files`). A child process is sandboxed too
(`tests/conftest.py::pytest_configure`): every process the suite starts, by
any route, inherits the `CLOCKWORK_TEST_SANDBOX` marker, under which the
engine never reads or writes `config/local.yaml`, reaches no model server
(but a loopback stub the test registered with `sandbox_model_stub`) or other
service, and writes `mcp.json` only in the temp root (a marker the suite did
not set stops it at conftest import), and a `subprocess` child's
`CLOCKWORK_CONFIG` also ends in the sandbox layer (`CLOCKWORK_CONFIG` itself
is never exported in-process); the owner's real storage, `local.yaml` and
`mcp.json` are compared at session end (`_real_storage_is_untouched`). The
storage root is a temp directory everywhere -- except in a test marked
`default_storage_root` (`tests/test_local_mode_golden.py`) or a canary that
deletes the variable, which the audit hook still watches: per test
(`_no_test_writes_real_saves`) and, for a module-, class- or session-scoped
fixture set up before that, the session's own (`pytest_configure`); a
`--basetemp` that resolves under the real storage root is refused at
start-up (`pytest.UsageError`); an
audit hook records any write this process aims at the real root's
`saves/`, `users/`, `hosting/` or `media/`, failing that test, or the next
test's setup when it happened outside one. **A
canary that removes or weakens a guard runs only after every path that guard
protects -- the home directory (LM Studio's `mcp.json`), `_CONFIG_DIR`
(`config/local.yaml`), the storage root and the model endpoints -- is
redirected into the test's temp directory, in that process and its
children**, with the owner's `mcp.json` checked before and after: a
wrapper-removal canary without that wrote the owner's real `mcp.json` in
v0.20.0 T5. An in-process hosted-mode test builds its app through
`tests/hosted_app.py`: hosting is turned on by a `local.yaml` layer in a temp
`_CONFIG_DIR` (never the owner's file) and `CLOCKWORK_DATA_DIR` points at
`tmp_path`, so `users.json`, its lock and the cookie key exist nowhere else.
A test never counts, waits for or signals a process by a bare pid: the OS
reuses pids, so a child is its pid AND its creation time
(`tests/process_identity.py`, over `engine/hosting/process_identity.py`,
reported by every probe), and only a verified child is ever terminated --
engine code included (`engine/hosting/boot.py::stop_master`).

**Module state is classified.** One process serves many sessions on threads
(hosted mode), so a new module-level global or class instance, class-level
container, `lru_cache` function, or thread, timer or pool site in `engine/` is
classified in `tests/fixtures/module_state.yaml` in the same change -- per
context, locked, warmed (with its `WARMERS` loader in
`engine/games/caches.py`), or one of the verdicts that say why nothing is
needed (docs/DESIGN.md § Many sessions, one process).
`tests/test_module_state_inventory.py` fails until it is. A lazy getter is
double-checked under its own lock; a per-call flag is a `threading.local` or a
`ContextVar`, never a module bool. A new module lock takes its place in
`engine/locks.py`'s one lock order (and `tests/lock_order.py`'s copy) and is
registered with `renew_after_fork`; a thread holding a lock takes only a later
one, and a new per-object lock is a leaf (nothing taken under it). A cache in
`caches.py`'s `NULLED_ATTRIBUTES` is read once into a local and returned from
the local (`tests/test_cache_reset_race.py`): a reset nulls it with no lock.

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

Shared play-screen surfaces (the wanted poster, the job panel, the casing
board, the people strip, the encounter's approaches, the roll card, the
negotiation panel) are **engine panels enabled by data**: a story lists them
in its manifest's `ui.panels`, and a plugin that draws one itself names it in
`ownsPanels`. A new panel joins `engine/games/manifest.py::UI_PANELS` and
`ui/src/core/panels/registry.js` together, which
`tests/test_ui_panels_manifest.py` holds equal. A layout change is gated by
`npm run layout-check --prefix ui`, which probes the play screen at four sizes
(1366x768, 900x600, 390x844 and the landscape phone 844x390) and fails on a
panel over the choices or an unreachable control; it expects
`scripts/screenshot_runs.py --serve <slug> --exit-with-parent` running as a
background task (never a bare `&`) and drives the installed Chrome
(`playwright-core` downloads no browser). The README's captures come from the
same pair: `scripts/screenshot_runs.py` makes the runs with no model, and
`ui/tools/screenshots.mjs` (`npm run screenshots --prefix ui`) photographs
them. When several agents run the suite at once, give each its own
`--basetemp` directory (`ptmp-<agent>`): pytest wipes its basetemp at start,
so two runs sharing one delete each other's temp trees.

**Story content** lives under `games/<slug>/` and is written against
docs/AUTHORING.md, not against engine source. A story that does not declare a
`paths.*` key pays nothing for that system, and its turns stay byte-identical --
asserted by test for every optional system.

## Verify a checkout

Windows (PowerShell):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -c constraints.txt
.\.venv\Scripts\python.exe scripts\doctor.py            # environment, config, content
.\.venv\Scripts\python.exe -m pytest tests\ -q          # fully green, no xfail; time in CLAUDE.md
npm ci --prefix ui; npm test --prefix ui                # the client: plugins, reducer, veiled rule
npm run build --prefix ui                               # rebuild the COMMITTED dist after any ui/src change
.\.venv\Scripts\python.exe launcher.py --check          # local services and what each outage costs
.\.venv\Scripts\python.exe scripts\simulate.py --policy all --turns 200
.\.venv\Scripts\python.exe scripts\simulate.py --game hue-and-cry     # HUE & CRY's thief, over its own harnesses
docker build -t clockwork-dark .                         # the hosted image (Docker; docs/HOSTING.md § Docker)
```

Linux (POSIX `sh`; other POSIX systems, macOS included, should work but are untested):

```sh
.venv/bin/python -m pip install -r requirements.txt -c constraints.txt
.venv/bin/python scripts/doctor.py
.venv/bin/python -m pytest tests/ -q
npm ci --prefix ui && npm test --prefix ui
npm run build --prefix ui
.venv/bin/python launcher.py --check
.venv/bin/python scripts/simulate.py --policy all --turns 200
.venv/bin/python scripts/simulate.py --game hue-and-cry
docker build -t clockwork-dark .
```

The image build needs Docker and fetches the server's pinned wheels from
PyPI; `CLOCKWORK_DOCKER_SMOKE=1 pytest tests/test_docker_smoke.py -s` then
runs it end to end with a stub model server (docs/HOSTING.md § Docker,
Checking it).

`scripts/start.ps1` and `scripts/start.sh` do the install and the suite in
one step. Install with `-c constraints.txt` always: it pins the versions the
suite was proven green on (re-pinning is a CHANGELOG'd edit).

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
