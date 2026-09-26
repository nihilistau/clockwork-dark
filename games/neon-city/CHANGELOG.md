# Changelog — NEON CITY: THE CROSSING

What changed in **NEON CITY: THE CROSSING**'s own content: everything under
`games/neon-city/`, plus the story-specific pieces that live elsewhere (its UI
plugin in `ui/src/stories/neon-city/`). Engine changes, and each release as a
whole, are in the [root CHANGELOG](../../CHANGELOG.md). Version numbers are
the repo's releases, and a release is listed here only if it changed this
story. The root file is authoritative from 0.4.0; for anything earlier,
`git log -- games/neon-city` is the authority.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.15.1] — 2026-09-26

### Added

- **This CHANGELOG**, linked from the story's README.

### Removed

- `BIBLE.md` §8 "SAFETY & RATING", with its suggested rating ceiling: a
  leftover of the layer removed in 0.3.0 (AGENTS.md rule 12, owner's
  decision). It was the last numbered section, so nothing is renumbered.
- **The negative-prompt keyword list** (owner's decision): `style.negative`
  in `data/art/subjects.yaml`, and every `NEGATIVE:` line of the regenerated
  `data/art/MISSING-PLATES.md`. The art prompts are positive-only.

### Changed

- **README audit.** It now names the story's three agents and its pipeline,
  its `death.yaml`, `survival.yaml` and lore corpus, and says where the six
  ending classes and the 75-subject art brief live.

## [0.15.0] — 2026-09-26

### Changed

- **The README said the story wore the Garden's skin.** It has drawn with its
  own plugin (`ui.plugin: neon-city`) since before 0.4.0; the README says so
  now.

## [0.13.0] — 2026-09-25

### Fixed

- `data/art/MISSING-PLATES.md` printed a sizes table of 1280x720 under a
  sentence saying it was read from `formats:`, where this story declares
  1344x768. It is regenerated from the generator's own plan, so the brief and
  `generate_art.py --game neon-city` list the same plates, at the story's
  size and at the same paths.

## [0.9.0] — 2026-09-23

### Fixed

- **A critical success could never be rolled.** `data/rules/skills.yaml`
  kept the graph template's `crit_success` margin of 10; a `standard` DC 13
  then needs a 23, and the best build here makes 22 on a natural 20. The
  margin is 6, the flagship's number, and a test now fails any story whose
  degree band no shipped build can reach.

## [0.8.0] — 2026-09-23

### Changed

- **Money reads in credits.** `data/tables/trade.yaml` declares
  `currency_format: "₵{n}"`, so receipts and quotes match the plugin's gold
  mono prices instead of the engine's "g".

### Fixed

- **Nobody was ever present.** Presence came only from procgen, which this
  story does not run, so the narrator was told nobody was in the room while
  the buy intent offered a present vendor's stock. Presence now comes from the
  schedules (an engine fix).

## [0.5.1] — 2026-09-20

### Fixed

- `game.yaml`'s `governance.directives` no longer names an interceptor
  removed in 0.3.0, which logged an "Unknown interceptor" warning on every
  governance build.

## [0.5.0] — 2026-09-20

### Changed

- **The timestamp and Collections reach the narrator.** An engine change
  makes the story's clocks (`timestamp`, `debt`) and its sealed threads part
  of the GM prompt; before, the narrator was never told either.

## [0.4.0] — 2026-09-20

### Changed

- **`NO FEED` where a plate is missing.** The story ships no plates, and the
  plugin's stage now draws the canon's dead screen instead of a gap.
- Onboarding is remembered per story, so meeting the flagship no longer
  counts as having met this story.
