# Changelog — THE LONG CON

What changed in **THE LONG CON**'s own content: everything under
`games/the-long-con/`, plus the story-specific pieces that live elsewhere (its
UI plugin in `ui/src/stories/the-long-con/`). Engine changes, and each release
as a whole, are in the [root CHANGELOG](../../CHANGELOG.md). Version numbers
are the repo's releases, and a release is listed here only if it changed this
story. The root file is authoritative from 0.4.0; for anything earlier,
`git log -- games/the-long-con` is the authority.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.15.1] — 2026-09-26

### Added

- **This CHANGELOG**, linked from the story's README.

### Changed

- **README audit.** The drying room is revealed when the case reaches its
  stage, not when you first stand in it (since 0.13.0); the README also names
  the three ending classes, the veiled meters, the UI plugin and the story's
  test rows, and says plainly that it declares no art paths.

## [0.13.0] — 2026-09-25

### Fixed

- **The drying room was offered before the case sent anyone there.** Travel
  built its options from the raw graph, so the first visit to Harbour Road
  offered the secret room three stages early. It now stays off the map and out
  of travel until the case reaches `the_cold_room`, through the room's own
  `known_when:` in `data/world/locations.yaml`.
- **A save already on the cold-room stage can finish the case.** The reveal is
  derived from the quest's stage rather than stored, so a save made before the
  reveal existed knows the room with nothing to migrate.

## [0.9.0] — 2026-09-23

### Fixed

- **A critical success could never be rolled.** `data/rules/skills.yaml`
  kept the graph template's `crit_success` margin of 10; the best build here
  makes 21 on a natural 20 against the 23 a `standard` check needed. The
  margin is 6, the flagship's number.

## [0.8.1] — 2026-09-23

### Changed

- The canon-skill comment in `data/rules/skills.yaml` cites `AGENTS.md`.

## [0.8.0] — 2026-09-23

### Changed

- **Money reads in dollars:** `currency_format: "${n}"` in
  `data/tables/trade.yaml`.

### Fixed

- **Nobody was ever present.** Presence came only from procgen, which this
  story does not run; it comes from the schedules now (an engine fix), so the
  narrator knows who is in the room and gossip has somebody to spread through.

## [0.7.1] — 2026-09-23

### Changed

- **The city stopped selling mushrooms as cigarettes.** The items and tables
  were the graph template's under noir display names in a `name:` key that
  nothing reads, so a 1940s fence offered "Hedge Berries". The goods are now
  levers: cigarettes handed round (`heat -4`), bonded rye left on a desk
  (`standing +6`) and somebody else's press pass (`standing +5`, `heat +7`,
  once a day), the counterplay
  to a case whose every stage adds heat and spends standing.
- **Work is work this city has:** nights on the weighbridge and the door at
  the Cadenza, instead of a mill that does not exist here. The weighbridge
  pays partly in cigarettes, so the item carries the effect.

### Fixed

- **The only vendor profile described a man who is not in the city.**
  `trade.yaml` declared `npc_miller`, while Georgie Pell, who has stock and
  keeps the harbour road from 18:00, had no profile. Pell has one now, and two
  tests hold the seam.

### Removed

- `data/tables/forage.yaml`: leaf litter and hedge berries in a story with no
  ground to forage on and no hunger to feed.

## [0.5.1] — 2026-09-20

### Fixed

- `game.yaml`'s `governance.directives` no longer names an interceptor
  removed in 0.3.0, which logged an "Unknown interceptor" warning on every
  governance build.

## [0.5.0] — 2026-09-20

### Changed

- **The frame can be felt filling.** An engine change puts `the_frame`'s
  label ("How this ends up being your fault") and band into the GM prompt, so
  the interview no longer arrives out of a clear sky.

## [0.4.0] — 2026-09-20

### Added

- **Its own ledger and theme** in the UI plugin
  (`ui/src/stories/the-long-con/`), instead of the graph template's right
  column.
