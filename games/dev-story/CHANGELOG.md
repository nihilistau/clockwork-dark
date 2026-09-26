# Changelog — Dev Story

What changed in **Dev Story**, the bench: everything under
`games/dev-story/`. It uses the engine's default skin (`_engine`), so it has no
UI plugin of its own. Engine changes, and each release as a whole, are in the
[root CHANGELOG](../../CHANGELOG.md). Version numbers are the repo's releases,
and a release is listed here only if it changed this story. The root file is
authoritative from 0.4.0; for anything earlier, `git log -- games/dev-story`
is the authority.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.15.1] — 2026-09-26

### Added

- **This CHANGELOG**, linked from the README.

### Fixed

- `agents.yaml`'s negotiation comment named an engine "safety" rule that does
  not exist (the only structural rule is voice ownership); a leftover of the
  layer removed in 0.3.0 (AGENTS.md rule 12).

### Changed

- **README audit.** It no longer calls the bench a third row beside two big
  stories (six ship), and it names the three ending classes, the one deck,
  the `_engine` skin and the test that plays the bench to an ending.

### Removed

- **The negative-prompt keyword list** (owner's decision): `style.negative`
  in `data/art/subjects.yaml`, and every `NEGATIVE:` line of the regenerated
  `data/art/MISSING-PLATES.md`. The art prompts are positive-only.

## [0.13.0] — 2026-09-25

### Fixed

- **Sophia's generated portrait was shared with The Wicked Garden's.** Both
  stories have a `sophia` portrait, and the generated-art disk cache was keyed
  without the story. The cache key now includes it.
- `data/art/MISSING-PLATES.md` was regenerated from the same plan the art
  generator uses, so the brief and `generate_art.py --game dev-story` list
  the same plates at the same paths.

### Notes

- The engine's new repeatable decks change nothing here: a fixed 40-turn
  director walk of this story, recorded before the change, replays to the
  same hands and played flags.

## [0.8.0] — 2026-09-23

### Fixed

- **Nobody was ever present.** Presence came only from procgen, which the
  bench does not run, so its seven scheduled people never appeared in the
  PEOPLE HERE block. Presence now comes from the schedules (an engine fix).

## [0.5.1] — 2026-09-20

### Fixed

- `game.yaml`'s `governance.directives` no longer names an interceptor
  removed in 0.3.0, which logged an "Unknown interceptor" warning on every
  governance build.

## [0.5.0] — 2026-09-20

### Removed

- A section of the README describing a layer the engine removed in 0.3.0.
