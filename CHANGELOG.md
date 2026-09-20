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

## [0.7.0] — 2026-09-20

### Added

- **Gossip travels, and gets further from its source as it goes.** A fact used
  to make exactly one hop — `spread` refuses when the listener already knows it,
  so a listener could never become a teller, and gossip was a star around the
  player rather than anything that moved. It can now pass onward, and each
  telling is worded for how far it has come:

      hop 1  heard from Maris: you asked about the tinker
      hop 2  heard from Corwin, who had it from Maris: they say you asked
             about the tinker
      hop 3  heard it going round: someone was asking about the tinker

  **The content never changes.** What decays is who vouches for it and how
  firmly, so a narrator can write somebody cagey about a source or
  overconfident about something they got third-hand — and the engine never
  records a falsehood a later turn might state as fact. A rumour allowed to go
  *wrong* would put claims in the ledger that the player can check against real
  state and catch out.
- `MAX_HOPS` is what makes onward telling safe to allow. Without a cap, letting
  a fact hop again turns the thing the module's own docstring insists must
  "feel like weather" into the broadcast network it says it must not be:
  everything reaches everybody, and the interesting state is the uneven one.
  `SPREAD_CHANCE` is untouched, so only one thing changed at a time.
- Nobody is told their own news. Once a rumour can travel more than one hop it
  can circle back — measured, and it read as "heard from Maris, who had it from
  Odran" sitting in *Odran's* own memory.

### Changed

- **The companion is held to its declared length.** `ASSISTANT_TURN_SCHEMA`
  exists to enforce the "1–3 sentences" rule — its own comment says prose alone
  "never reliably holds" it — and nothing ever passed it to a model; the v0.5.0
  audit found it as an unreferenced constant. It **cannot** be wired as written:
  a `response_format` forces the OpenAI-compatible transport, and the companion
  is on the native route because "156 of this call's 200 tokens went to
  REASONING and the reply was cut off mid-sentence" is measured at its call
  site. Wiring it would buy the cap and pay for it with a starvation somebody
  already fixed. The rule is enforced in code instead, at a sentence boundary —
  which a `maxLength` could never do, since a JSON string truncated at 240 stops
  mid-word. Its allowlist row now records a decision rather than debt.

### Notes

- **Measured, and not done:** flipping the flagship's companion to
  `pipeline: true`. The pipeline does engage with two participants — but the
  flagship declares **zero** negotiation rules, so every turn would fall through
  to the confidence fallback, which is a coin flip dressed as a rule. Its
  companion's persona is also written to react to *finished* prose, so its plans
  would be poorly grounded. The roster's own comment — "it leads no turns" — was
  right, and the audit suggestion that prompted this was not.

## [0.6.2] — 2026-09-20

### Fixed

- **Sophia had a painted portrait that had never once been shown.**
  `assistant_presence` resolved the companion's picture from `form` — the
  Assistant Mind's current face, one of The Clockwork Dark's five, defaulting to
  `"cat"`. A story whose companion is a named CHARACTER keys her portrait on her
  own id, so The Wicked Garden asked for a cat, got `""`, and drew its fallback
  wash over an unshown `portraits/sophia.jpg`. Resolved from the roster's
  declared character now, which covers the opening and resume frames too — the
  first frames a player sees. The flagship is unchanged: it declares no roster,
  so the lookup falls back to `form` exactly as before.

  Same disease `Companion.jsx` already documents for the `form` CAPTION —
  "the flagship's state leaking through a slot this story shares with it". The
  caption was fixed; nobody noticed the portrait had it too. Empty is a legal
  answer from a portrait lookup, which is why nothing ever failed.
- **A choice that echoes its own intent id is relabelled from the author's
  text.** Measured live on a 3B model: the Garden's choices rendered as
  `follow_the_scent`, `name_it_aloud`, `turn_away_hard` — the model had copied
  the intent enum's target ids into the display text, while the beats they came
  from carry authored prose and `legal_intents` had it all along. Showing the
  model's copy of an id while holding the author's sentence is the wrong way
  round for an engine whose premise is that it resolves and the model narrates.
  Only an exact id match; real writing is never second-guessed.
- **Schema field names leaked into the prose as tags.** Measured live and
  rendered on screen: `...this garden that is not yours.</narration>}<action>You
  examine the merchant's stall.` This is the same failure
  `strip_embedded_envelope` exists for, in tag notation instead of JSON — so
  that guard could not see it, and `strip_trailing_debris` leaves it because the
  tail is full of words. `strip_scaffold_tags` anchors on the turn schema's own
  key names rather than on "looks like a tag", because a story is allowed to
  contain `<`.
- **The build-freshness guard could not be satisfied.** Bumping
  `ui/package.json` in step with `pyproject.toml` put
  `test_the_committed_build_is_not_behind_its_source` into a state no rebuild
  could clear: the version string is not bundled, so `npm run build` produces
  byte-identical output, dist is never dirty, never committed, and the file
  stays permanently "ahead". A guard that cannot be satisfied is one somebody
  deletes. A version-only change is ignored now; a dependency change still
  fails exactly as before. Its `_git` helper also decoded git's output with the
  locale encoding — cp1252 here — which was harmless while it read only ASCII
  path names and turned `package.json`'s em-dash into U+FFFD the moment it read
  a file.

### Notes

- The Garden's scene art works everywhere it exists — 19 scene plates, all
  serving. `mortal_threshold` is one of six locations the manifest lists as
  having no plate *on purpose*, and it is both the entry location and where the
  10-card prologue plays out, so a new player sees no scene art until the
  prologue ends. That is content, not code, and it is the single most visible
  art gap in the repo.

## [0.6.1] — 2026-09-20

### Fixed

- **A model with no reasoning knob silenced an agent, and a two-agent story ran
  on one.** The starvation net switches to the native transport and sends
  `reasoning="off"` — and not every model accepts the parameter at all:

      Model 'lfm2.5-vl-3b-uncensored.gguf@q8_0' does not expose reasoning
      configuration.   (type=invalid_request, param=reasoning)

  Measured against the live server: **30 of 42 local LLMs publish no `reasoning`
  block**, so the net was guaranteed to fail for most of them. The 400 became an
  exception, the planner logged "No plan, treating as silent", and The Wicked
  Garden negotiated with one agent instead of two. Nothing failed anywhere.
- **Root cause was in the parser, two layers up.** `registry._capabilities`
  flattened the whole `capabilities.reasoning` block to its `default` string, so
  "exposes no reasoning at all" and "exposes it, defaulting to off" both arrived
  downstream as `""`. The fact needed to avoid the 400 was in a payload the
  engine already fetched, and was parsed away. `ModelInfo` now carries
  `reasoning_configurable` and the server's own `allowed_options`.
- `native.reasoning_for` omits the key for a model that cannot take it, and
  refuses a value outside `allowed_options` — gemma publishes `["off","on"]`, so
  `"low"` is a legal native level and an illegal value for that model. An
  unknown model is unchanged: an empty registry means the server was
  unreachable, and quietly dropping the parameter there would make a network
  outage look like a capability decision.
- **The retry now buys room instead of asking for less.** `wire_cap` returns the
  content budget *unchanged* when reasoning is off, so even without the 400 the
  second attempt would have carried 320 tokens where the attempt that starved
  carried 3,520. For a model that thinks whatever you ask it, the retry now
  sizes its ceiling from what the model *measurably just spent* thinking plus
  the full content budget — no magic multiplier. With no measurement it stands
  down rather than spend a player's turn on a coin flip.
- `ModelRegistry.cached` looks a model up without touching the network, because
  a lookup while building a request body must not put discovery inside the
  request it is about to send.

Verified live, not only against fixtures: the same Garden turn that previously
logged the 400 now logs `Planned (agent=gm)`, `Planned (agent=sophia)` and
`Turn negotiated (lead=gm, agents=2, resolutions=1)`.

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

[Unreleased]: https://github.com/nihilistau/clockwork-dark/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.6.2...v0.7.0
[0.6.2]: https://github.com/nihilistau/clockwork-dark/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/nihilistau/clockwork-dark/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/nihilistau/clockwork-dark/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/nihilistau/clockwork-dark/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.2.0...v0.3.0
