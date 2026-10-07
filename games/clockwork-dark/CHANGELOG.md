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

## [0.21.0] — 2026-10-07

### Changed

- The save browser's "the pattern is quiet" line is this story's own now
  (its plugin's `saveMeta`, v0.21.0): core prints it for no other story.
- The encounter's approach buttons are `aria-disabled` while a turn runs or
  the connection is down (they read core's `controlsOff`), not `disabled`,
  so a focused one keeps focus; an approach not offered this turn is now
  dimmed as well.
- The Settings pace slider ("How fast the dark spreads") now holds the
  shipped 0.028: its range is 0.001-0.05 (it stopped at 0.02, so the thumb
  sat at its end and a touch eased the world to 0.02), its marks are the
  rates measured when 0.028 was chosen (0.006 Dormant, 0.020 Stirring,
  0.028 Spreading: where the median 200-turn run ended) and its hint says
  only that. The rate itself is unchanged.
- `--accent-brass` in the consuming phase lifted to #5c723b (was #5a6f3a):
  as a panel mark it measured 2.90:1 on the card, under WCAG's 3:1
  (`ui/tests/contrast.test.js`).
- The encounter's approach buttons now resolve through their intent: each
  presses the narrator's choice that carries it, so the engine takes the
  approach before the turn is narrated (it used to send the approach's words
  as typed text, which resolved nothing). An approach the Storyteller did not
  offer this turn says "not offered this turn" and cannot be pressed, and only
  the choices the buttons press are hidden: any other choice stays on screen.
  The panel's look is otherwise unchanged.
- A live deck's or challenge's line (the beat frame) has its own row in the
  play column (v0.21.0's named areas) instead of taking the narrative log's
  flexible row. The encounter's 7:3 split and its 14rem floor, and the
  narrow-screen fallback, are kept, rewritten against the seven named rows.
- The 12px between the scene still and the log is now the log's margin, inside
  its row rather than a gap outside both, so the split measures about 61.6/38.4
  (276/172px at 1366x768, was 268.8/179.2): accepted as part of the new
  margins.

### Fixed

- "Step into the clearing" is on screen at 1366x768 (it sat below the fold
  and the page scrolled with no cue): the start card tightens on a short
  window (v0.21.0 final fix wave).
- The scene caption, its alt text, the sheet's Place line and the notice
  board's "Posted elsewhere" name places ("Edgewood Square"), not ids; two
  traders of one name get numbered tabs, and a vendor opening a sentence is
  capitalised ("The baker deals in it.").
- The overlays' comments no longer say the engine resolves barter, item
  use, crafting and posted work: they send typed text, which runs no skill.
  Recorded as NOT WIRED (docs/GOVERNANCE.md); the intent path is the v0.23.0
  overhaul's.

## [0.20.0] — 2026-10-06

- `saves:` removed from `game.yaml`; the engine owns where saves go (`storage.root`, v0.20.0), and runs still land in `data/saves/clockwork-dark/`. No content change.

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
