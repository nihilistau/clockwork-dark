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
- Two secret places (v0.25.0 T5, spec §3.4): the works below the stump (`the_works`, ring 0, an hour from the clearing), known once the sealed seam's riddle is solved (`seam_opened`), and the Join (`the_join`, ring 3, an hour past the heartland road), known once the inward road is measured. In a player's run neither is offered as a road, drawn on the map or named in the prose before then (`data/rules/spoilers.yaml` masks each name until it is known; "the Join" case-sensitively). The no-session atlas route (`/api/codex/places` with no session) still lists both, as it lists HUE & CRY's secrets (`codex_places(None)` does not filter them, and the map asks it before a run has a session): recorded, not fixed, because the fix moves HUE & CRY's recording (CLAUDE.md, deferred; v0.26.0). Location prompts for both in `data/art/subjects.yaml` (no plate yet: the procedural tile).
- Every road is banded (spec §5.3): the 22 roads that carried `danger_dc: 0` with a `# needs band` note now carry 6 (the wood), 10 (the barrows and the toll road) or 14 (the heartland road), and the two new roads 12 (the works) and 14 (the Join). Five new encounter files take them, `wood.yaml`, `barrows.yaml`, `toll_road.yaml`, `heartland.yaml` and `works.yaml`, and `village.yaml` gains two rows for the walk out to the Fallow holding; the square's own rows are unchanged. Millhaven gate's market and barracks stay 0: they are doors. Every number in the new rows is a first value, measured in the release's balance pass. The new bands' six enemies (`barrow_cold`, `press_gang`, `toll_men`, `brass_hound`, `wrong_walker`, `the_works_engine`) draw the procedural tile until their plates are made.
- A find, `the_works_below` (whisper arc): standing in the works completes it, for awareness, a brass shard and a secret in the ledger.
- The first three door decks (v0.25.0 T6, spec §4.1-§4.3; `paths.decks`, `data/scenes/`), each repeatable, one card a visit, dealt only where its person is (`npc_here`): **the morning firing** (the bakery 04-09 while Maris is there: `H0` walks the larder for `banking_the_fire`'s first stage; `H1` asks the question, `stay` locking The Hearth Holds or, with that gate shut, `stay_anyway` locking The Dark Keeps Its Hours, and `not_yet` locking nothing; `Q0` shows up for the last quiet morning in its own hours; `Q1` locks The Named Wound whether you `tell_her` or `say_nothing`, and since T10's fix round 2 `not_yet` locks nothing), **the count kept** (the shrine while old Wenna lights her candles: `W1`'s `give_it` locks The Long Witness) and **the muster roll** (the gate or the square while Sera is there: `M1`'s `strike_it` locks The Counted March). `H1` is not dealt while The Named Wound is open, so the two never compete for one morning. "Not yet" is never the last chance: each deck comes round again on the next visit.
- Every ending has a one-sentence `tease` (`data/rules/endings.yaml`), carried in the payload's gallery; it names no ending and keeps the reveal word back.
- The last three door decks (v0.25.0 T7, spec §4.2-§4.3): **the price** (repeatable, wherever Ilya is while the sacrifice is open: `S0` writes the price out; `S1` offers one beat per thing carried, the written name, the ninth pin or a brass shard, each writing `nf_sacrifice_chosen` and its own `sacrifice_offered_<item>`; `S2` pays the thing offered and still held, locking The Price Asked, or `not_yet`; `S1` comes round again for a run at `pay_it` with nothing offered on a card and for a thing offered and then sold), **the join** (repeatable, at the Join: `R2` walks it at midday for the inward road's stage; `J1`'s `set_it` sets the ninth pin and locks The Pin and the Join, `keep_it` ends nothing) and **the stopped wheel** (forced once by the declared event `the_last_hour`, the first day rolled with the doom reading at 1.0, dealt after any open encounter or hand: `Z1` locks The Stopped Wheel). The three `sacrifice_offered_*` flags are canon (`data/canon/state-dictionary.json`).
- The critical path on cards (v0.25.0 T8, spec §4.3-§4.4): every quest stage on an ending's path that completed only when the narrator raised its flag has a card that writes it, dealt where and when the stage's other conditions hold. Seven repeatable decks, one card a visit, each due only when one of its cards can be dealt: **the bakehouse** (the bakery while Maris is there: `B1` asks for work), **Nessa's drawings** (the square or the bakery: `N1` sees the drawing, `N2` asks Nessa while she is there, `N3` keeps one), **the naming** (the square, the bakery or the caravan, 19-22: `G1` lays it out, `G2` says it aloud once the world is `spreading`, `G3` writes it down), **the village meeting** (the square: `V1` calls it by day or dusk, `V2` is the vote, stay, go or split, `V3` warns the four households on the copied list), **the levy table** (the gate or the square while Sera is there: `L1` watches the levy choose, `L2` the Weller boy, speak up, give his name or say nothing, `L3` gets near the list and `L4` copies it on a stealth roll, a failure costing the militia's standing, at the gate; `L5`-`L7` Sera's compromise, the last a choice, agree or refuse), **the ninth pin** (the caravan while Ilya is there: `T1` asks, `T2` pays once the tinkers' standing is 10, `T3` takes the pin or leaves it, and only `take_it` grants it) and **the inward road** (the gate, with a road map: `R1` measures it). The Pin and the Join, and paying the price with the pin, can be reached in play.
- **Sera's levy** (v0.25.0 T8, spec §5.1): a hidden clock, `the_levy` (0-6, `state.yaml`, `data/rules/clocks.yaml`), +1 the first time the militia press is seen and +1 at 3, 6, 9, 12 and 15 days after it. At 3 the clerk starts a second page; full, it deals **the press** once in the square, 08-17 (`data/scenes/the_press.yaml`, `P1_a_name_on_the_list`, read by a corporal of the militia, not the sergeant, who is at the gate in those hours: speak for the boy, persuasion, hard; get him out of sight, stealth; or let it be, each moving the militia's and Edgewood's standing). The press is never dealt with no levy owed. A v0.24.0 save whose first press is fifteen or more days old fills the levy on its first turn and is dealt the press in the square in its hours.
- **Sergeant Venn's bargain** (v0.25.0 T8, spec §5.1; `data/rules/threads.yaml`, `seras_bargain`, a Contract): struck at the gate 08-10 while the conscription list is open, a night on the wall inside three days for one Edgewood name off her list. Kept at the gate 22-03 it pays the militia +6, costs 20 stamina and writes `stood_the_wall`, which The Counted March's `served` reads, so "a night on the wall" is a way there; left unkept it breaks on its day (militia -8). Every number in the levy, the press and the bargain is a first value, measured in the release's balance pass.
- The terminal death shows its ending: `data/rules/death.yaml`'s `terminal:` names `the_dark_keeps_its_hours`, so the second death while the world is `consuming` locks the fail-forward and its epilogue card follows (it set the run ended and showed nothing).

### Fixed

- Leaving the ninth pin no longer grants it (bug 1): `the_ninth_pin`'s `take_it_or_dont` stage granted the pin in its `on_complete` whether it was taken or left. The stage keeps its doom resistance and the tinkers' +15. The pin is the `take_it` beat's to grant, on the ninth pin's `T3_take_it_or_dont` card (v0.25.0 T8); `leave_it` grants nothing.
- The sacrifice takes the thing offered (bug 2): `the_sacrifice`'s `pay_it` stage removed the written name whatever was chosen, and closed only once the written name was gone. The price's `S2` beat removes exactly the thing offered; the stage now closes on `nf_sacrifice_paid` alone, and the quest no longer locks The Price Asked itself (the card does).
- A v0.24.0 save whose narrator already raised `nf_sacrifice_paid` while still holding the written name completes `pay_it` with nothing removed (the stage no longer removes the name). Accepted: only an old save can reach it.
- Seven flags are no longer the narrator's to raise: `nf_ninth_taken`, `nf_ninth_left`, `nf_sacrifice_chosen` and `nf_sacrifice_paid` leave their stages' `narrative_flags` (§4.1); card beats write them. The whole-branch review (T14) found three more of the class: `nf_hearth_book_closed` (`banking_the_fire`'s `the_question`: raised by the narrator, it completed the stage with no ending locked, and The Hearth Holds' door and the fail-forward's morning door never came again) and `nf_press_spoke_up` and `nf_press_gave_name` (`militia_press`'s `the_weller_boy`: raised by the narrator, they skipped the L2 beats' reputation shifts).
- The overlays' small faults (v0.25.0 T14 review): a press's log line carries its verb ("Wear: Wool cloak", "Take off: Wool cloak"; both logged "Wool cloak"), an unpressable button no longer glows or sinks on hover and press, "The ways it ends" has its own door icon (it borrowed the Journal's), and a failed overlay read no longer says "Answer what is in front of you first". `data/rules/endings.yaml`'s MEASURED header gives T10's final figures (it gave the first table).
- The naming can no longer be laid out too early (v0.25.0 T9 fix round 1): `the_naming`'s `G1_lay_it_out` was dealt from awareness 52 in any phase, but `say_it_aloud`, the stage it opens, needs `spreading` and fails for good four days after it opens, and `lay_it_out`'s own doom resistance pushes `spreading` back. Laid out in `stirring`, the naming expired, and The Named Wound, The Price Asked and The Pin and the Join with it. `G1` (and the deck's `when:`) now waits for `spreading`.
- The inward road's join is a place (bug 4): `the_heartland_road`'s `walk_the_join` stage completed at Millhaven gate; it now completes at `the_join`, past the heartland road.
- The sealed seam's riddle counts its own answer (bug 6): the prompt said "six letters" for `time`; it says "four letters".
- Nessa's surname corrected (bug 3): `childs_drawing.yaml`'s summary, its first objective and its ledger fact now call her Nessa Fallow, as the lore does. The other family's lines (`lost_goat`, `militia_press`) are unchanged.
- Nessa is nine everywhere (bug 3's two extra lines, the controller's ruling): `childs_drawing.yaml`'s completion text and its "nine-year-old" ledger fact said six, against the cast line, the portrait and the lore table.
- The doom clock's moves place people: Ilya reaches the square at 0.50 and Sera at 0.88 (the engine fix is in the root CHANGELOG); before, their routines kept them where they were. A move does not wake anyone: each still counts as here only in their routine's waking hours. A v0.24.0 save already past either reading keeps both on their routines (its beats fired before a move placed anyone; CLAUDE.md, deferred).
- The Pin and the Join is reachable again (v0.25.0 T10, found by the doors harness: 0 of 40 pinner runs). `ward_charms` pinned Ilya home on its start and unpinned him when it ended, completed or failed; the ninth pin's quest holds him at the caravan by the same flag (`npc_pin_npc_ilya`) through its whole quest, and after the 0.50 move it is the only thing keeping him there. A ward-charms ending inside the pin's quest unpinned him in the square, so `T2_pay_for_it` was never dealt. `ward_charms` now pins nobody: its stages ask only for the caravan, and his routine has him there all but three afternoon hours (`tests/test_clockwork_dark.py::test_the_ninth_pins_hold_on_ilya_survives_the_ward_charms_ending`).

### Changed

- Every ending is locked by name at its door (v0.25.0 T6, §4.1): `banking_the_fire` and `the_last_quiet_thing` lose their id-less `ending_lock` (an id-less lock let the score rows pick the ending; the rows now only feed the gallery's closeness band). The gates move with the doors (§4.2): The Hearth Holds reads `larder_kept` (`nf_hearth_taking_stock`, which `H0` writes) for `book_closed`; The Long Witness reads `counted` (the Unnamed Saints at 30) and `stayed_three_counts` (day 27) for `stayed`; The Counted March loses `mustered_out`, and `served` also counts `stood_the_wall` (canon in `data/canon/state-dictionary.json`; written by Sera's bargain, v0.25.0 T8); The Named Wound gains `baked` (the last quiet morning at its third stage, or done); The Price Asked reads `named`, `chose` and `paid`; The Pin and the Join's `join_walked` also holds once the inward road's walk stage has passed. Every changed clause has its own lock reason.
- The ninth pin's price is the tinkers' standing (v0.25.0 T8, §4.3): `the_ninth_pin`'s `pay_for_it` read Ilya's disposition at 20, which only the model's `npc_disposition` patch writes, so no card-only run could pass it; it reads the tinkers' standing at 10 (the tinker shift, trade, collections and encounters raise it). A first value, measured in the release's balance pass. The objective still says Ilya's price is not coin.
- `the_last_quiet_thing` opens on `what_edgewood_keeps` alone (with awareness 62): it no longer accepts `the_sacrifice` or `the_heartland_road`, which end the story at their own doors, so requiring either would leave The Named Wound unreachable.
- The caravan, the tinker's camp and the militia press are declared `events:` (`data/world/schedules.yaml`), each rolled once per in-game day crossed on its own stream, at the legacy rates measured per eligible day (v0.25.0 T1): caravan 0.768 from day 5, tinker 0.00465, press 0.173 while awareness is 20 or more. Their rates no longer depend on how a day was cut into background ticks. Each carries its own line of text; the caravan's rumour is Odran's. The unread `goods:` lists are gone. The pre- and post-change tables are in the root CHANGELOG and the schedules file's header.
- **The overlays press intents** (v0.25.0 T11, spec §7.3-§7.4, §8.1; `ui/src/stories/clockwork-dark/`): the barter screen, the pack, its recipes and the notice board no longer send the player's typed words. Each button is an `{action, target}` the server lists (`GET /api/intents/overlay`) and the engine runs before the narrator speaks: Buy and Sell one row at a time, Eat, Use, Wear or Ready, Take off, Make it and Take the shift. A pair the server does not list is drawn and not pressable, saying why where it can (food the rules will not count, a recipe short of something, a price you cannot meet, a trader you have not met yet); while a card, an encounter, a set-piece or a job owns the turn nothing is pressable and the overlay says "Answer what is in front of you first." A shift posted elsewhere shows only where it is. Examine stays typed text. Retired: the pack's Offer and Drop (no verb gives or drops a thing), the tag-only Light, and the barter screen's balance beam and "Strike the bargain" (one turn carries one intent); each a docs/GOVERNANCE.md NOT WIRED row.
- **The encounter, the sheet, the ways it ends, the people and the ending's plate** (v0.25.0 T12, spec §8.2-§8.6; `ui/src/stories/clockwork-dark/`): an approach the narrator did not offer this turn is drawn unlit (dashed, in the phase's muted ink, unnumbered, "not offered this turn") and cannot be pressed; while the choice row below is empty, keys 1-9 press the offered approaches in order, never while a turn runs. Under 900px wide the encounter's art is a 4:1 letterbox, and under 420px tall its log keeps the last two rounds. The sheet's Standing rows read each faction's own name and its band's word (`GET /api/factions`), falling back to the id and the number until it answers. A new overlay, **The ways it ends** (`e`), lists only the doors open now, each with its title, tease and closeness, and once a run is locked, that ending; never a locked or silhouette row, and the fail-forward only once it is the locked ending (the hiding is the client's: the payload ships every tier, a docs/GOVERNANCE.md NOT WIRED row). Who is here is drawn under the sheet (core's people strip, in its ledger shape, drawn by the plugin's Ledger slot rather than declared in `ui.panels`, which rides the catalogue and would move the local-mode recording). The ending screen draws the ending's gallery plate (`EndingArt`, the `gallery` art kind) in place of the line that printed its key; until the plates are painted it is the frame's empty plate.
- **The balance pass measured every door** (v0.25.0 T10, rule 10; `scripts/simulate_doors.py`, 40 seeds, one scripted policy per ending; every table, the levers tried and the misses left are in the root CHANGELOG): all 34 cards are answered; the Hearth, the stay-anyway door, the Long Witness, the Named Wound, the Price Asked and the Stopped Wheel are each reached by 90-100% of their policy's runs, the Counted March by 90% (another ending locks in 10%), the Pin and the Join by 57.5%. One lever was kept (below, the walk to the Join); the three others tried (the convergence gate at awareness 100, its stages' doom resistance doubled, the march's militia at 16) were measured and reverted.
- The walk to the Join names its hour and gives five days (v0.25.0 T10 fix round 1, a measured lever): `the_heartland_road`'s `walk_the_join` objective says "at midday" (its 10-15 window was named only by the `R2` card dealt inside it) and `expires_after_days` is 5, not 3, as the ninth pin's `pay_for_it` has: the Join is six road hours past the last bed, and failing the walk shuts The Pin and the Join for good. Measured over all nine door policies: the pinner 37.5% -> 42.5%, every other row unchanged.
- The Named Wound's door can wait (v0.25.0 T10 fix round 2): `Q1_tell_her_or_dont` gains a third answer, "Not this morning" (`not_yet`), which locks nothing and has no effect; the card comes round on a later morning. It is dealt at the bakery at dawn once The Named Wound is open, and a dealt card is the whole turn, so with only `tell_her` and `say_nothing` a player working the shift there had to end the story. The two answers that end it are unchanged. Measured: the pinner, which worked the dawn shift on its way to the Join, 42.5% -> 57.5%.

### Tests

- Every ending is reached through its door (v0.25.0 T9, spec §12.1): the flagship joins HUE & CRY in `tests/test_finales.py`'s `COMPLETE_DOORS`, with ten door rows (the morning firing's `stay`, `stay_anyway`, `tell_her` and `say_nothing`, the count kept's `give_it`, the muster roll's `strike_it`, the price's `pay_the_name`, the join's `set_it`, the stopped wheel's last morning, and the second death in `consuming`) and 24 unearned rows, one for every gate clause of every earned ending, each walking the real door with that one clause unmet (`tests/clockwork_doors.py`).
- Every ending is reached by cards alone (§4.4, §12.2; `tests/clockwork_walks.py`): eight walks from a new game, the turn's own order an hour at a time, with the narrator's flag-raising and dispositions patched to fail; the presence sweep (`slow`, ten seeds, days 1-60) holds each door deck's person gate true only where npc_sim places that person, and a static check that each door deck with a person reads `npc_here`.
- The nine v0.24.0 saves (§12.4, `tests/test_clockwork_dark_saves.py`): each plays a turn, saves and reloads; the caravan and Odran kept with no second caravan; the works known or the seam offered; H1 dealt at five; the price re-offered at S1 and paid; the old press's levy full on the first turn and the press dealt in the square (`8_old_press`); the locked Hearth kept.

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
