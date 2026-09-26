# Changelog — HUE & CRY

What changed in **HUE & CRY**'s own content: everything under
`games/hue-and-cry/`. It uses the engine's default skin (`_engine`) until
v0.21.0's UI overhaul, so it has no UI plugin of its own yet. Engine changes,
and each release as a whole, are in the [root CHANGELOG](../../CHANGELOG.md),
which also carries every measured table this file only summarises. Version
numbers are the repo's releases, and a release is listed here only if it
changed this story. The root file is authoritative from 0.4.0 (this story
first shipped in 0.9.0); `git log -- games/hue-and-cry` is the authority for
anything this file does not place.

Like the README, this file names the secret places (the README's tables list
them and the ways in) and never says who the Magpie is.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.15.1] — 2026-09-26

### Added

- **This CHANGELOG**, linked from the README.

### Changed

- **README audit.** The "skeleton" framing is gone (four engine features and
  three v1.0 stages have shipped on it since); the Margrave's household and
  the Silk Row houses are no longer listed as unmoved factions (a squeeze left
  uncollected moves them since 0.15.0); the balance section names all seven
  harnesses; and the "not yet" list matches CLAUDE.md's deferred list.

### Removed

- **The negative-prompt keyword list** (owner's decision): `style.negative`
  in `data/art/subjects.yaml`. The art prompts are positive-only.

## [0.15.0] — 2026-09-26

The guild economy, the third of the v1.0 stages.

### Added

- **The Porters' Hall bench.** The `craft` verb makes lockpicks, smoke
  pellets, a lamplighter's coat (a new guise) and a forged Margrave's Hill
  gate pass (a jobs tool on the Hill only) from makings sold by the two fences
  or found in the Snuffs' middens (`data/recipes/workshop.yaml`). A set of
  picks costs under half Marrow's price; nothing sells for more than its
  makings.
- **The Magpie's Hoard.** Six famous pieces the ballad says were never fenced:
  four in the anchors' strongrooms, two found by standing in secret places
  (`data/tables/collections.yaml`, `data/quests/the_magpies_hoard/`). Named,
  so hot for good; an arrest takes them all back. Carrying all six pays the
  Honest Company's good opinion once. An agenda's robbery never takes a piece.
- **Blackmail.** A house's secret carried out of a job is held, and each
  anchor's is a squeeze on its owner, struck at their door in their hours and
  collected there inside two days. Left uncollected, the squeezed party swears
  a `blackmail` report (severity 3) to the Watch, all but Mother Gannet, and
  their people turn on you.
- **The fences' credit.** Pell Hollis's advance (ten crowns, thirteen back in
  three days) and Marrow's slate (five, eight back in two), repaid in coin at
  her counter. Welsh on one and neither fence buys from you or lends again,
  and her collectors walk the streets for you until you pay.

### Changed

- **Brask names no price to a clean record.** His bribe is offered only while
  the Wick's drawer holds something against you.

### Fixed

- **A found place kept its cover name** in the awareness gate, and the lore
  paired a cover name with its place in one sentence. A test keeps every
  secret's cover and name out of the same lore chunk; rebuild the story's
  `lore.db` with `seed_lore.py --clear`.
- The fences' collectors' daytime rows spoke of the night.

### Notes

- Measured together at the end (`simulate_hoard.py` is new): no earlier bound
  moved. Welshing on a fence still nets a purses-only pickpocket a few kept
  days, and the owner let that stand. Hunger takes the careful pickpocket
  who never borrows to 0 hp on 95% of seeds in ten days; a welsher reaches
  it on 45% (Pell) to 82.5% (Marrow); with no `death.yaml`
  until v0.17.0 nothing follows. The tables are in the root CHANGELOG.

## [0.14.0] — 2026-09-26

The living city, the second of the v1.0 stages.

### Added

- **Somewhere to sleep, and something to eat.** A pallet at Old Nance's
  flophouse (1 cr), a free bunk over the Porters' Hall for anyone the Honest
  Company has no quarrel with, rooms at the Snuffed Wick and over the Tallow
  Barge (3 cr), the cell's plank bench, and a rough night anywhere, always
  (`data/rules/survival.yaml`). The story's first rest verb: before it, it had
  none, and walking was free. Bread and eel pie from Dock Mag, ship's biscuit
  at Hollis's; hunger runs at 2 an hour and every street costs stamina.
- **Scrounging and the secret ways.** Two hours in the gutters of five
  streets (`data/tables/forage.yaml`), and every secret place can now be
  found: a yard grating or the cells' drain to the Undercroft, a drainpipe or
  a loading crane to the Rooftop Road, the Rooftop Road or the churchyard wall
  to the Old Bell Tower. Turn one still offers none of them.
- **Honest work and luck.** Four employers, each open only in the hours it
  keeps (`data/tables/labour.yaml`), and the city's boons and complications
  on a natural 20 or 1. An honest day covers bread and a flophouse bed with a
  little over; thieving pays more.
- **The streets at night.** Every public street carries a danger rating, and
  five night scenes can meet you there (`data/encounters/streets.yaml`):
  cutpurses, a press-gang, a drunk Lantern, the lamplighter's warning and
  Silas Crook's toll-men. Each has a way out that needs no roll, coin, item
  or hour, and none takes more than 3 hp.
- **Factions and lore.** Seven factions (`data/world/factions.yaml`) and a
  42-chunk lore corpus in eight files (`data/lore/`). Three factions (the
  Temple, the Margrave's household, Silk Row) were declared for later acts
  and moved by nothing yet.

### Notes

- Measured together at the end with the new `simulate_scrounge.py`,
  `simulate_labour.py` and `simulate_streets.py`; no earlier bound moved.
  Hunger can take a thief to 0 hp on some seeds, and with no `death.yaml`
  until v0.17.0 nothing follows.
- A save from before 0.14 keeps its generated world, so it never gains the
  rooftop and grating paths; the arrest reveal of the Undercroft still
  reaches it.

## [0.13.0] — 2026-09-25

### Changed

- **The secret places stay secret.** On turn one travel offered "The
  Undercroft, 1h" by name; the three secret places are now off the map and
  out of travel until known (the `data/world/locations.yaml` header says
  how). Nothing in the story made them known until 0.14.0.
- `generate_art.py --game hue-and-cry` now plans the story's 91 plates
  (19 locations at four dayparts, 15 portraits). None is generated yet.

## [0.12.0] — 2026-09-25

Agendas: the city moves whether or not you do.

### Added

- **Three agendas on hidden clocks** (`data/rules/agendas.yaml`,
  `data/rules/clocks.yaml`, a new `state.yaml`). The Magpie, a thief chosen
  by the seed and never revealed or stored, robs a shining house most nights,
  and the watch takes the Magpie for you: a player who never steals a spoon
  is `noticed` in two days and `sought` in about five. Captain Ardane tightens
  her net and, pushed far enough, swears out a warrant. Silas Crook cleans out
  the Honest Company's own ward and pounces if you rob Mother Gannet.
- **The Magpie's mask.** No trace or effect names who the Magpie is, in any
  seed. `magpie_unmasked` lifts the mask, and nothing sets it yet.
- The anchor premises name their owners, and `prompts/storyteller.md` gains
  "THE CITY MOVES WITHOUT YOU".

### Notes

- Measured with the new `simulate_agendas.py` (40 seeds x 10 days). The law
  and jobs harnesses now measure with agendas off, so their bounds still mean
  what they did.

## [0.11.0] — 2026-09-24

Jobs and flashbacks.

### Added

- **Burglary** (`data/rules/jobs.yaml`). `burgle` opens a job on any unrobbed
  house and walks it stage by stage: the approach, a way in (door, window,
  roof or cellar), whoever is inside, the strongroom, the getaway. Every
  security row of all eight house types and four anchors does something to a
  named stage, casing earns prep, three flashbacks spend it, and an alarm
  brings the Watch. The Treasury has its own vault floor.
- **The burglar's kit:** lockpicks and smoke pellets, sold by Marrow.
- **Mother Gannet's first contract:** any house on Silk Row inside three days,
  fifteen crowns net of the Company's cut. The Honest Company becomes the
  story's first faction.
- The `burglary` deed, severity 3.

### Notes

- Measured with the new `simulate_jobs.py` (four burglars, 40 seeds). Every
  number in `jobs.yaml` was set against it; the table is in its header and the
  root CHANGELOG.

## [0.10.0] — 2026-09-24

The Law.

### Added

- **The Lantern Watch** (`data/rules/law.yaml`): three watch-houses, wanted
  bands per guise per district, the guises `self`, `magpie` and `porter`, and
  a Watch that believes from the first morning that you are the Magpie.
- **The Lantern's stop** (`data/encounters/watch_stop.yaml`): run, talk,
  bribe, surrender or fight, opened only by a Lantern who knows your face.
- **Sergeant Brask's bribe** (`data/rules/threads.yaml`): twelve crowns in the
  biscuit tin, and the Wick's reports go missing.
- Dock Mag, the first honest vendor (a porter's smock), and Marrow's Magpie
  mask.

### Notes

- Measured with the new `simulate_law.py` (careful, reckless and briber
  thieves, 40 seeds x 10 days). Tuning moved cooling, the wanted thresholds,
  recognition and the arrest's price; the tables are in the root CHANGELOG.

## [0.9.0] — 2026-09-23

The story's first release.

### Added

- **The skeleton.** Tallowmere's eleven districts (three secret), fourteen
  scheduled people covering all 24 hours, two pipeline agents (the city and
  Pip the jackdaw), three archetypes, an opening whose three choices each
  carry an intent, and one ending reachable end to end, `honest_after_all`,
  with its epilogue. Art prompts for every district and person; no plates.
- **Premises, pockets and fences.** Eight premise types and four anchors
  (Vessaline House, the Margrave's Treasury, Mother Gannet's House, the
  Captain's Office), each with a household that keeps real hours, security by
  tier, loot and a secret; purses by role; loot valued in crowns; and the two
  fences, Pell Hollis and Marrow.

### Fixed

- `crit_success` was unreachable (the graph template's margin of 10); it is
  6, the flagship's number.
