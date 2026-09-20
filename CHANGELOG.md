# Changelog

All notable changes to The Clockwork Dark.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html) —
loosely, since nothing imports this as a library. A MINOR bump is a release the
player or the author would notice; a PATCH is repair.

**Entries before 0.4.0 were written after the fact**, from the commits
themselves. Nothing was kept at the time, so they are shorter and less certain
than what follows. `git log` is the authority for anything before 0.4.0; this
file is the authority from 0.4.0 on.

## [Unreleased]

## [0.6.0] — 2026-09-20

### Added

- **The narrator is told what the other side gave up.** `Resolution` exists to
  record "the companion wanted to interrupt and the world won", and its own
  docstring says that without it "the only evidence is prose that reads slightly
  differently" — but `narration_block` sent lead, beats, the speaker's verbatim
  line, receipts and the blocked flag, and never the resolutions. The prose
  could not read differently because it was never told. It now receives what
  yielded, to whom, and the reason the *author* wrote for that rule, with an
  instruction to SHOW it rather than report it. Only resolutions with a loser:
  the confidence fallback records a winner and nobody yielding, and dressing
  that as a concession would have the narrator dramatise a sacrifice that did
  not happen.
- **A margin mark on a contested turn** (`NarrativeLog.jsx`). State, not words —
  no engine-authored sentence goes into the log beside the narrator's prose.
  The store keeps `negotiation` per turn, deliberately not sticky, unlike
  `ending`.
- **A negotiation panel for the author** (`ui/src/core/parts/NegotiationPanel.jsx`),
  rendered by `Play.jsx` and silent unless a pipeline ran — so the flagship and
  any single-participant story never see it. Collapsed by default; prints lead,
  who yielded to whom, the rule's authored reason, beats, refusals and vetoes.
  Closes the `negotiation` half of a **NOT WIRED** row in `docs/GOVERNANCE.md`.

### Fixed

- **Every image in The Wicked Garden was invisible, and always had been.** Core
  ships `.paint__img { opacity: 0 }` and raises it on `.is-loaded`; the Garden's
  stage plate and Sophia's portrait both rendered bare `className="paint__img"`,
  so the art fetched, decoded, occupied its frame and never appeared. Nothing
  failed — the request was 200, `complete` was true, `naturalWidth` was 640 — so
  it read as "this story ships no art" rather than as a defect. Found by looking
  at the running game, which is the only thing that could have found it.
  `ui/tests/plugin-contract.test.js` now fails on any `<img class="paint__img">`
  with no way to raise it, across core and every plugin.

### Known gaps

- The companion column does **not** show a posture when the companion is the
  agent that gave way. `assistant_presence` ships no agent id, so the client
  cannot tell whether the yielding agent is the one in its column, and guessing
  was the wrong answer. Recorded as its own NOT WIRED row with what wiring it
  would take.

## [0.5.1] — 2026-09-20

### Fixed

- **The removed layer was still named in config, in four shipped games and in
  all three story templates.** `governance.directives` listed `SafetyDirective`
  and `governance.commit` listed `SafetyCeiling`, so every governance build
  logged two "Unknown interceptor named in config, skipping" warnings and every
  freshly scaffolded story inherited a dead name — the same
  templates-teach-the-bug shape that CLAUDE.md already records for the intent
  loop. Worse, `tests/test_story_surface.py` *asserted* the stale name was
  present, which locked it in: the suite would have failed if anyone removed it.
  Found from a log line while working on something else, because the earlier
  sweeps grepped for module paths and this was a bare string in YAML.
- `governance.commit` is now `[]`, which is what `_DEFAULT_CHAINS` in
  `engine/agents/governance.py` has always shipped. Config and code had
  disagreed about whether a pre-commit veto hook ships by default; the code was
  right, and says why.
- `tests/test_governance_commit.py`'s docstring claimed "the configured chain
  contains the ceiling", which stopped being true at v0.3.0.

## [0.5.0] — 2026-09-20

### Added

- **Sealed contracts reach the narrator.** `engine/game/threads.py` is 1,220
  lines and three shipped stories declare a `threads.yaml`; a sealed thread
  gates choices, charges its terms and comes due on a named day — and no
  narrator had ever been told one existed. `threads.summary` has said in its own
  docstring since it was written that it is "trimmed for a prompt block or a UI
  list"; only the UI half was built. There is now a `CONTRACTS YOU ARE UNDER`
  block, carrying terms, counterparty, seal, due day and cutters, and
  withholding the effect hooks exactly as `summary` already did.
- **Clocks reach the GM line.** `engine/game/clocks.py` is 844 lines and the
  narrator got none of it. A `WHAT IS CLOSING IN` block now reports each clock
  qualitatively, banded through the same `Spec.band` the client projects a
  veiled meter with, so GM and player never hold two vocabularies for one
  number. THE LONG CON's `the_frame` can now be felt filling instead of dealing
  an authored interrogation out of a clear sky.
- **The clock labels nobody read.** Every shipped clock table carries a
  `label:` — "How this ends up being your fault", "The roots are counting",
  "Winter, being patient" — eight across five games, and no engine module had
  ever loaded one. They are GM-facing by construction, saying what a clock
  *means*, which is what a narrator needs and what the player-facing label in
  `state.yaml` deliberately does not say. They are what the new block prints.
- **Pressure has a direction.** `story_pressure` reached the prompt as one of
  three words, so a story easing off after a crisis and a story winding toward
  one read identically. The GM line now says "restless, and rising" or "and
  easing". `story_pressure_prev` is written in exactly one place —
  `clock.advance_time`, the single writer of world time — because
  `update_story_pressure` runs several times per turn and a naive "remember the
  last value" would compare a turn against itself and report every story as
  steady.
- **`tests/test_reachability.py` now walks constants, not just calls.** v0.3.0
  left two orphans behind and nothing noticed: `rng.SAFETY_REDIRECT`, a seeded
  stream whose own comment said it was consumed by a module that no longer
  existed, and `storyteller.FADE_FALLBACK_LINE`, a canned line citing a deleted
  contract document. Neither failed anything, and both read to the next session
  exactly like a feature somebody had not finished wiring. The sweep is
  restricted to UPPER_CASE names on purpose — seven results instead of
  seventy-four — and carries a positive control plus an allowlist that rots if
  a row becomes read or disappears.

### Removed

- The last four remnants of the removed prompt layer: a 31-line comment block in
  `games/clockwork-dark/game.yaml` teaching the full `safety:` manifest syntax
  and pointing at three deleted files, an `## Intensity` section in
  `games/dev-story/README.md`, and the two orphan constants above. The manifest
  block was the sharpest of them — an authoring tutorial for a system that does
  not exist, sitting in a shipped game.
- Dead RNG streams `LOOT`, `LABOUR` and `TRADE`, and `ledger.SOURCE_PLAYER`.
  Nothing drew or wrote any of them. Work and trade price their outcomes from
  the tables outright, which is *why* neither has a stream; the comment claiming
  otherwise now says so.

### Fixed

- `CLAUDE.md`'s status line read "2020 passing, 18 skipped in 3m38s" for a month
  after v0.3.0 deleted three test files, in the same sentence that warns the
  reader it has been stale before. Measured: **1867 passing, 4 skipped**, and
  **127 client tests** against two different wrong numbers (126 and 95) in the
  same document.

## [0.4.0] — 2026-09-20

### Added

- **Accept one draft.** `POST /api/studio/draft/accept` promotes a single draft
  entry into the live tree, with `Author.promote_one` doing the placement so the
  studio and `scripts/author.py --promote` cannot disagree about where a file
  lands. `--promote` is all-or-nothing and refuses while any error stands; the
  review queue exists precisely so an author can keep one and discard the rest.
- **The notice board reaches the browser.** `GET /api/notices` has been served
  since Overhaul III and no player could see it. `Notices.jsx` is a
  clockwork-dark overlay (`n`) with its own pinned-paper mark. Closes a
  **NOT WIRED** row in `docs/GOVERNANCE.md`.
- **Challenge and scene framing.** `BeatFrame.jsx` draws the "step 2 of 4" /
  "card 3 of 7" line, so a gauntlet reads as one thing rather than four
  unrelated turns. It invents nothing: titles, cursors and lengths all come off
  the turn payload. The full panel remains unbuilt and stays in the table.
- **THE LONG CON gets its own ledger** and theme, instead of wearing the graph
  template's right column.

### Changed

- **Onboarding is remembered per story, not globally.** The flag was one key for
  the whole install, so meeting the flagship taught the client that you had met
  NEON CITY too, and four of the five games never introduced themselves.
- **NEON CITY says `NO FEED`** where a plate is missing, rather than rendering a
  gap. The game ships zero art plates against 75 subjects; this makes the
  absence read as the canon's own dead screen instead of as a broken image.
- **Core copy stopped speaking for the flagship.** The default player name was
  `Traveler` and the seed hint said "Same seed, same village" — one story's
  nouns in the engine's own neutral client. Now `You` and "same world".

### Fixed

- `engine/studio/api.py` inserted `scripts/` into `sys.path` inside its request
  handlers, so every scaffold and every accept pushed another copy of the same
  string onto a process-wide list that nothing popped. Both call sites now go
  through one idempotent `_script_module`.

## [0.3.1] — 2026-08-15

### Added

- The engine-scope rule in `CLAUDE.md` (rule 12), so that a later session
  finding the absence undocumented does not reintroduce what 0.3.0 removed.

## [0.3.0] — 2026-08-15

### Removed

- **Prompt composition is story-owned.** The engine no longer injects register
  or content-tier directives into the storyteller prompt or the story-drafting
  prompt. The package, config block, per-game blocks, settings dial and client
  card that carried them are gone — 40 files, 5,207 deletions. Register is set
  by `games/<slug>/prompts/storyteller.md` and by the model the owner has
  loaded, which is not the engine's business.

The governance commit chain keeps its veto: a hook can still block a turn, and
nothing is written when one does.

## [0.2.0] — 2026-08-15

Reconstructed from `git log`; see those commits for detail.

- **Overhaul III — reachability.** Three subsystems and eleven registered skills
  had no production caller: the deck system (so the Wicked Garden could not be
  finished by playing it), `clocks.forced_scenes`, `set_pieces` and `threads`.
  All wired, with `tests/test_reachability.py` walking the engine's own call
  graph so it stays that way. The suite dropped from 15m32s to a third of that
  once four paths that were reaching a live LM Studio from tests were closed.
- **THE LONG CON** — the first hybrid: a full graph city that also declares
  decks and a clock.
- **A studio** — author a story without a terminal.

## [0.1.0] — 2026-06-20 … 2026-08-14

Reconstructed from `git log`; see those commits for detail.

The engine and the first games: deterministic core (single writers for time and
state, seeded RNG streams), the two-agent turn, the multi-agent
plan → negotiate → govern → commit pipeline, quests, economy, survival,
encounters, endings and epilogues, the React client with per-story plugins,
and five shipped games.

[Unreleased]: https://github.com/nihilistau/clockwork-dark/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/nihilistau/clockwork-dark/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/nihilistau/clockwork-dark/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.2.0...v0.3.0
