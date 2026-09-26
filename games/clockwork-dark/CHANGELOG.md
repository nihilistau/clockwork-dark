# Changelog — The Clockwork Dark

What changed in **The Clockwork Dark**'s own content: everything under
`games/clockwork-dark/`, plus the story-specific pieces that live elsewhere
(its UI plugin in `ui/src/stories/clockwork-dark/`, its art pack in
`content/scenes/clockwork/static/art/`). Engine changes, and each release as a
whole, are in the [root CHANGELOG](../../CHANGELOG.md). Version numbers are the
repo's releases, and a release is listed here only if it changed this story.
The root file is authoritative from 0.4.0; for anything earlier,
`git log -- games/clockwork-dark` is the authority.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.15.1] — 2026-09-26

### Added

- **This CHANGELOG and a README** (`games/clockwork-dark/README.md`) for the
  story, which had neither.

### Removed

- **The negative-prompt keyword lists** (owner's decision): `style.negative`
  in `data/art/subjects.yaml` and `negative_prompt` in
  `data/procgen_templates/comfyui.yaml`. The art prompts are positive-only.

## [0.15.0] — 2026-09-26

### Added

- **The `craft` verb reaches the flagship.** The engine's new crafting intent
  is offered wherever one of the story's 22 recipes can actually be made
  right there (station, tools and inputs in hand), and nowhere else.

### Fixed

- **The tinderbox never closed the road kit.** It is a `road_kit` member,
  but its row in `data/items/gear.yaml` did not name the set, so a tinderbox
  bought last closed nothing. It names `collection: road_kit` now; the new
  collections validator is what found it.

## [0.14.0] — 2026-09-26

### Changed

- `data/tables/labour.yaml`'s header documents the optional `when:` and
  `closed_text:` keys a job may now declare. No job here declares one, so the
  board is unchanged.
- A rest note with no bed in reach names the place by its display name
  ("Forest Clearing"), not its id (`forest_clearing`).

## [0.9.0] — 2026-09-23

### Fixed

- The trade quote's summary wrote money as "...c"; it now uses the story's
  own `currency_format` and reads "...g".

## [0.8.1] — 2026-09-23

### Changed

- Canon-id comments in `agents.yaml`, `game.yaml`,
  `data/world/locations.yaml` and `data/rules/spoilers.yaml` cite `AGENTS.md`,
  where the rules now live. No behaviour changed.

## [0.8.0] — 2026-09-23

### Fixed

- **Odran traded from a counter he never stood at.** His profile in
  `data/tables/trade.yaml` put him at `tinker_caravan`, which no hour of his
  schedule reaches. He trades in `edgewood_square` now, off the cart tail,
  while his schedule has him there. (Vendors trade at their counter only while
  they are present and awake, an engine change that also stopped the square
  offering Brindle's stall while she was in the forest.)
- **The procgen festival happens.** It was generated per seed and read by
  nothing; declared world events now fire it.

### Removed

- `npc_voices` and `mood` from the two few-shot examples in
  `prompts/examples.json`, because the turn schema no longer has either field.

## [0.7.2] — 2026-09-23

### Changed

- **Rumours reach their third-hand form in a session.** An engine change to
  gossip, measured on this story: its five scheduled villagers used to
  saturate after about four tellings, so the "heard it going round" form
  arrived in 12 of 40 runs. It arrives in 33 of 40 now (median turn 38).

## [0.7.0] — 2026-09-20

### Notes

- **Measured, and not done:** turning the companion into a pipeline
  participant (`pipeline: true`). The story declares no negotiation rules, so
  every turn would fall to the confidence fallback, and the Assistant's
  persona reacts to finished prose. It still leads no turns.

## [0.5.0] — 2026-09-20

### Removed

- A 31-line comment block in `game.yaml` that documented a manifest block the
  engine no longer has (removed in 0.3.0) and pointed at three deleted files.

## [0.4.0] — 2026-09-20

### Added

- **The notice board reaches the browser.** `Notices.jsx` is a clockwork-dark
  plugin overlay (`n`) with its own pinned-paper mark.
