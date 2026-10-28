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

### Added

- Four people the lore already named are placed in the world (v0.25.0 T4, spec §3.3), declared in `data/world/npc_schedules.yaml` with routines covering every hour: Hallam the smith (the forge 06-18, the square 19-20, asleep on Well Row), Nessa Fallow (the Fallow holding mornings and evenings, the square 09-16 with the other children, asleep at the holding), old Wenna (the shrine 06-07 and 18-21, her Well Row doorstep by day, asleep there) and Edrin Fallow, Nessa's father (the Fallow holding all day, asleep 20-04). They are not in the procgen template, so no seed's village moves.
- At 0.88 (`tower_assembles`, `data/rules/doom_effects.yaml`) Edrin and Nessa leave the holding for the ditch camp, beside Sera's move to the square.
- The storyteller prompt's CAST section: one line for each of the four (`prompts/storyteller.md`); nothing else in the prompt moved.
- Portrait prompts for the four in `data/art/subjects.yaml` (no plate yet: they render on the procedural tile until their plates are made).
- Two secret places (v0.25.0 T5, spec §3.4): the works below the stump (`the_works`, ring 0, an hour from the clearing), known once the sealed seam's riddle is solved (`seam_opened`), and the Join (`the_join`, ring 3, an hour past the heartland road), known once the inward road is measured. In a player's run neither is offered as a road, drawn on the map or named in the prose before then (`data/rules/spoilers.yaml` masks each name until it is known; "the Join" case-sensitively). The no-session atlas route (`/api/codex/places` with no session) lists both, as it lists HUE & CRY's secrets: a codex with no player knows every place. Location prompts for both in `data/art/subjects.yaml` (no plate yet: the procedural tile).
- Every road is banded (spec §5.3): the 22 roads that carried `danger_dc: 0` with a `# needs band` note now carry 6 (the wood), 10 (the barrows and the toll road) or 14 (the heartland road), and the two new roads 12 (the works) and 14 (the Join). Five new encounter files take them, `wood.yaml`, `barrows.yaml`, `toll_road.yaml`, `heartland.yaml` and `works.yaml`, and `village.yaml` gains two rows for the walk out to the Fallow holding; the square's own rows are unchanged. Millhaven gate's market and barracks stay 0: they are doors. Every number in the new rows is a first value, measured in the release's balance pass. The new bands' six enemies (`barrow_cold`, `press_gang`, `toll_men`, `brass_hound`, `wrong_walker`, `the_works_engine`) draw the procedural tile until their plates are made.
- A find, `the_works_below` (whisper arc): standing in the works completes it, for awareness, a brass shard and a secret in the ledger.
- The first three door decks (v0.25.0 T6, spec §4.1-§4.3; `paths.decks`, `data/scenes/`), each repeatable, one card a visit, dealt only where its person is (`npc_here`): **the morning firing** (the bakery 04-09 while Maris is there: `H0` walks the larder for `banking_the_fire`'s first stage; `H1` asks the question, `stay` locking The Hearth Holds or, with that gate shut, `stay_anyway` locking The Dark Keeps Its Hours, and `not_yet` locking nothing; `Q0` shows up for the last quiet morning in its own hours; `Q1` locks The Named Wound whether you `tell_her` or `say_nothing`), **the count kept** (the shrine while old Wenna lights her candles: `W1`'s `give_it` locks The Long Witness) and **the muster roll** (the gate or the square while Sera is there: `M1`'s `strike_it` locks The Counted March). `H1` is not dealt while The Named Wound is open, so the two never compete for one morning. "Not yet" is never the last chance: each deck comes round again on the next visit.
- Every ending has a one-sentence `tease` (`data/rules/endings.yaml`), carried in the payload's gallery; it names no ending and keeps the reveal word back.
- The last three door decks (v0.25.0 T7, spec §4.2-§4.3): **the price** (repeatable, wherever Ilya is while the sacrifice is open: `S0` writes the price out; `S1` offers one beat per thing carried, the written name, the ninth pin or a brass shard, each writing `nf_sacrifice_chosen` and its own `sacrifice_offered_<item>`; `S2` pays the thing offered and still held, locking The Price Asked, or `not_yet`; `S1` comes round again for a run at `pay_it` with nothing offered on a card and for a thing offered and then sold), **the join** (repeatable, at the Join: `R2` walks it at midday for the inward road's stage; `J1`'s `set_it` sets the ninth pin and locks The Pin and the Join, `keep_it` ends nothing) and **the stopped wheel** (forced once by the declared event `the_last_hour`, the first day rolled with the doom reading at 1.0, dealt after any open encounter or hand: `Z1` locks The Stopped Wheel). The three `sacrifice_offered_*` flags are canon (`data/canon/state-dictionary.json`).
- The terminal death shows its ending: `data/rules/death.yaml`'s `terminal:` names `the_dark_keeps_its_hours`, so the second death while the world is `consuming` locks the fail-forward and its epilogue card follows (it set the run ended and showed nothing).

### Fixed

- Leaving the ninth pin no longer grants it (bug 1): `the_ninth_pin`'s `take_it_or_dont` stage granted the pin in its `on_complete` whether it was taken or left. The pin is now the `take_it` card beat's to grant (v0.25.0 T8); the stage keeps its doom resistance and the tinkers' +15.
- The sacrifice takes the thing offered (bug 2): `the_sacrifice`'s `pay_it` stage removed the written name whatever was chosen, and closed only once the written name was gone. The price's `S2` beat removes exactly the thing offered; the stage now closes on `nf_sacrifice_paid` alone, and the quest no longer locks The Price Asked itself (the card does).
- Four flags are no longer the narrator's to raise: `nf_ninth_taken`, `nf_ninth_left`, `nf_sacrifice_chosen` and `nf_sacrifice_paid` leave their stages' `narrative_flags` (§4.1); card beats write them.
- The inward road's join is a place (bug 4): `the_heartland_road`'s `walk_the_join` stage completed at Millhaven gate; it now completes at `the_join`, past the heartland road.
- The sealed seam's riddle counts its own answer (bug 6): the prompt said "six letters" for `time`; it says "four letters".
- Nessa's surname corrected (bug 3): `childs_drawing.yaml`'s summary, its first objective and its ledger fact now call her Nessa Fallow, as the lore does. The other family's lines (`lost_goat`, `militia_press`) are unchanged.
- Nessa is nine everywhere (bug 3's two extra lines, the controller's ruling): `childs_drawing.yaml`'s completion text and its "nine-year-old" ledger fact said six, against the cast line, the portrait and the lore table.
- The doom clock's moves place people: Ilya reaches the square at 0.50 and Sera at 0.88 (the engine fix is in the root CHANGELOG); before, their routines kept them where they were.

### Changed

- Every ending is locked by name at its door (v0.25.0 T6, §4.1): `banking_the_fire` and `the_last_quiet_thing` lose their id-less `ending_lock` (an id-less lock let the score rows pick the ending; the rows now only feed the gallery's closeness band). The gates move with the doors (§4.2): The Hearth Holds reads `larder_kept` (`nf_hearth_taking_stock`, which `H0` writes) for `book_closed`; The Long Witness reads `counted` (the Unnamed Saints at 30) and `stayed_three_counts` (day 27) for `stayed`; The Counted March loses `mustered_out`, and `served` also counts `stood_the_wall` (canon in `data/canon/state-dictionary.json`; Sera's bargain writes it from v0.25.0 T8); The Named Wound gains `baked` (the last quiet morning at its third stage, or done); The Price Asked reads `named`, `chose` and `paid`; The Pin and the Join's `join_walked` also holds once the inward road's walk stage has passed. Every changed clause has its own lock reason.
- `the_last_quiet_thing` opens on `what_edgewood_keeps` alone (with awareness 62): it no longer accepts `the_sacrifice` or `the_heartland_road`, which end the story at their own doors, so requiring either would leave The Named Wound unreachable.
- The caravan, the tinker's camp and the militia press are declared `events:` (`data/world/schedules.yaml`), each rolled once per in-game day crossed on its own stream, at the legacy rates measured per eligible day (v0.25.0 T1): caravan 0.768 from day 5, tinker 0.00465, press 0.173 while awareness is 20 or more. Their rates no longer depend on how a day was cut into background ticks. Each carries its own line of text; the caravan's rumour is Odran's. The unread `goods:` lists are gone. The pre- and post-change tables are in the root CHANGELOG and the schedules file's header.

## [0.24.0] — 2026-10-27

### Added

- Brass and gears sound palette (v0.24.0 T10, spec 9.2): the story declares `paths.sounds` (`games/clockwork-dark/data/sounds/sounds.yaml`), reusing the engine's CC0 Kenney files by `engine:` with a synthesised fallback for each; the palette is in the README's Sounds table. The phase badge, the Stage and the DiceToast fire the cues in `ui/src/stories/clockwork-dark/`.

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
