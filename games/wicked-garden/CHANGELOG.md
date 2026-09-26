# Changelog — The Wicked Garden

What changed in **The Wicked Garden**'s own content: everything under
`games/wicked-garden/`, plus the story-specific pieces that live elsewhere
(its UI plugin in `ui/src/stories/wicked-garden/`). Engine changes, and each
release as a whole, are in the [root CHANGELOG](../../CHANGELOG.md). Version
numbers are the repo's releases, and a release is listed here only if it
changed this story. The root file is authoritative from 0.4.0; for anything
earlier, `git log -- games/wicked-garden` is the authority.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.15.1] — 2026-09-26

### Added

- **This CHANGELOG and a README** (`games/wicked-garden/README.md`) for the
  story, which had neither.

### Changed

- **`data/scenes/README.md`'s gap list is current.** It names the endings the
  deck walker never reaches (measured 2026-09-26: 7 of 23 in 1000 runs, 9 in
  200; no orphan cards) and `day_09_finale` being dealt twice, and no longer
  points at a `data/rules/decks/` directory that is gone.

### Removed

- From `data/README.md`: a paragraph, and a clause in the art section,
  describing a manifest setting and a Settings-screen control that do not
  exist; the layer they belonged to was removed in 0.3.0 (AGENTS.md rule 12).
  Also a sentence about a "Brass Coast" story that this repo has never
  shipped.
- **The rest of that layer's leftovers** (AGENTS.md rule 12, owner's
  decision). Rating tokens and references to a fade control, limits and a
  manifest ceiling are gone from the card and beat text of days 0, 1, 2, 3, 4,
  5, 6, 8 and 9 (text the narrator reads), and so are the bare "Suggestive"
  register labels there (days 3 and 4); likewise from the E3a ending beats in
  `data/rules/endings.yaml`, and from the comments in `epilogue_cards.yaml`,
  `data/art/manifest.yaml`, `data/art/subjects.yaml` and `agents.yaml` (which
  also named an engine "safety" negotiation rule that does not exist). The
  canon `state-dictionary.json` loses the boundaries, intensity, fade and
  aftercare fields and the rows that read or ranked them. No id, flag, gate or
  number changed.
- **The negative-prompt keyword lists** (owner's decision): `style.negative`
  and `style.variants.mortal.negative` in `data/art/subjects.yaml`, and every
  `NEGATIVE:` line of the regenerated `data/art/MISSING-PLATES.md`. The art
  prompts are positive-only; every figure is still stated as an adult in the
  positive prompt, and `data/README.md` now says so.

## [0.13.0] — 2026-09-25

### Fixed

- **Sophia's generated portrait was shared with Dev Story's.** Both stories
  have a `sophia` portrait, and the generated-art disk cache was keyed without
  the story, so one cached image served both. The cache key now includes the
  story.
- `data/art/MISSING-PLATES.md` was regenerated from the same plan the art
  generator uses, so the brief and `generate_art.py --game wicked-garden`
  list the same plates at the same paths. It lists the same subjects as
  before.

### Notes

- The engine's new repeatable decks change nothing here: a fixed 40-turn
  director walk of this story, recorded before the change, replays to the
  same hands and played flags.

## [0.8.1] — 2026-09-23

### Changed

- Rule citations in `data/items/garden.yaml` and `data/scenes/README.md`
  point at `AGENTS.md`, where the rules now live.

## [0.8.0] — 2026-09-23

### Fixed

- **The cast had no names.** The eight rows in
  `data/world/npc_schedules.yaml` carried neither `name` nor `role`, so
  presence rendered `ashen_vale: ashen_vale (visitor)` and the story's own
  `role_defaults` for `bloomkin` and `court` never matched a row. Every row
  is named now, and a guard fails any shipped story with a nameless scheduled
  person.
- **Nobody was ever present.** Presence came only from procgen, which this
  story does not run, so the narrator read "PEOPLE HERE: (world not yet
  generated)". Presence now comes from the schedules (an engine fix).

## [0.6.2] — 2026-09-20

### Fixed

- **Sophia's painted portrait was never shown.** The companion's picture was
  resolved from the flagship Assistant's `form` (defaulting to `"cat"`), so
  the Garden drew its fallback wash over an unshown `portraits/sophia.jpg`.
  It is resolved from the roster's declared character now, on the opening and
  resume frames too.
- **Choices that echoed their intent ids** (`follow_the_scent`,
  `name_it_aloud`, measured live on a 3B model) are relabelled from the
  author's beat text.

### Notes

- 19 scene plates serve. `mortal_threshold`, the entry location and home of
  the ten-card prologue, has no plate on purpose, so a new player sees no
  scene art until the prologue ends.

## [0.6.1] — 2026-09-20

### Fixed

- **The Garden negotiated with one agent instead of two** on any model that
  exposes no reasoning setting: the request was refused, the planner logged
  "No plan", and the turn went on without Sophia. Verified live afterwards:
  both `gm` and `sophia` plan, and the turn negotiates with two agents.

## [0.6.0] — 2026-09-20

### Fixed

- **Every image in the Garden was invisible.** The plugin's stage plate and
  Sophia's portrait rendered `paint__img` with no way to raise its opacity,
  so the art loaded and never appeared (`ui/src/stories/wicked-garden/`).
  A client test now fails on any such image in any plugin.

## [0.5.1] — 2026-09-20

### Fixed

- `game.yaml`'s `governance.directives` no longer names an interceptor
  removed in 0.3.0, which logged an "Unknown interceptor" warning on every
  governance build.

## [0.5.0] — 2026-09-20

### Changed

- **The story's clocks and contracts reach the narrator.** An engine change
  makes the authored clock `label:`s (for example "The roots are counting")
  and the sealed threads in `data/rules/threads.yaml` part of the GM prompt;
  before, neither had ever been read into it.
