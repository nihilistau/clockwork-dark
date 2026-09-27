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

## [0.16.0] — 2026-09-27

Acts I and II, the fourth of the v1.0 stages: the opening, the initiation,
the small room, the Magpie's trail, and the front desk's alibi and
accusation.

### Added

- **Acts I and II, as arcs the narrator can see.** `hue_and_cry` (Act I, the
  default) and `honest_work` (Act II, opening on `guild_initiated`) declare
  `narrate: true` in `data/quests/arcs.yaml`, so while one is the active arc
  the GM prompt carries its name and blurb. `the_way_out` stays a door at
  order 0 and `the_magpies_hoard` a side arc, so neither takes the active arc
  from an act. Neither act has a quest yet, so pacing is unchanged. The
  initiation deck (below) sets `guild_initiated`.
- **The Honest Company takes you in: the initiation deck**
  (`data/scenes/initiation.yaml`, `paths.decks`). This is the story's first
  deck and Act I's second beat. It is dealt once, on the first turn the
  thief stands in the Snuffs free and unsworn while Mother Gannet holds court
  at the long table: 18:00 to 04:00, per her schedule (from noon she does the
  accounts, and before that she sleeps). Mother Gannet and the Company are
  sure you are the Magpie, and that is why they want you.
  - When an arrival meets it: every way off the barge reaches the Snuffs by
    10:00–11:00 on day one, so the Company receives them that evening. The
    exception is a fumbled run answered by surrender, which serves three
    days and meets it on the evening of day four.
  - Before the deck is dealt, Gannet's contract and the guild bunk say the
    Company receives newcomers after dark.
  - It is never dealt in the cells (the cells deal the interrogation, below):
    a thief who came quietly meets it after release. It is never dealt over a burglary or over an open encounter,
    such as a Lantern's stop on the way in. It waits for either to end and
    is dealt on the next turn (an engine guard, root CHANGELOG).
  - The cards: tea at the long table, then a proving in front of the back
    room, then the oath, then supper or the Magpie's ballad.
  - The gates: persuasion, sympathy, stealth, craft, nerve and lore.
  - Every card has an answer that asks no dice. A failed roll costs a crown
    or some stamina, never the oath.
  - The oath always lands. It sets `guild_initiated`, which opens Act II
    (`honest_work`).
  - The rolls decide only how warmly the Company takes you:
    - every roll won: `honest_company` +8 or +9
    - the roll-free answers: +4
    - every roll lost: +2
  - No card names or implies a Magpie candidate (asserted).
- **The small room: the interrogation deck**
  (`data/scenes/interrogation.yaml`), the story's second deck and the first
  shipped deck anywhere to be `repeatable`. Every arrest ends in it: it is
  scheduled by `when: {in_custody: true}` and dealt on the first turn of
  every stay in the cells, once a stay, and re-armed the first turn the thief
  is seen free (the v0.13 `repeatable` seam; no engine change). An arrest that
  closes a Lantern's stop deals it on that same turn, and so does coming
  quietly off the barge.
  - Who asks, by the hour and read off the schedule (asserted against it):
    Captain Ardane at 06:00-13:00 and 18:00-23:00, Sergeant Brask at the
    front desk at 16:00-18:00, and otherwise the Lantern who brought you in,
    at the duty desk. Exactly one interrogator at any hour.
  - The cards: the book and the file (whose front says what the Watch
    believes -- `linked` self/magpie -- so it says MAGPIE until something
    breaks the link), then the interrogator's questions: nerve and
    persuasion against the file.
  - Outcomes: every petty sheet (severity 1) against your face or a face
    linked to it quashed (`quash_reports ... linked, max_severity: 1`), or
    only the Wick's; the file kept; or a caught lie written into the
    Magpie's file as one more lift (`report ... guise: magpie`, up the Rise
    or in the Wick). A burglary or a struck Lantern is never quashed.
  - **The sentence stands** (controller's ruling). The fine and the days are
    fixed by `arrest` at the door, and no card effect writes custody, so the
    room changes the file -- what is still filed when you walk out, and so
    how soon a Lantern knows you again -- and never the fine or the days.
  - Nobody is stuck: while a card is open `pay_fine` and `serve` are hidden,
    every menu card has a roll-free answer, the sequence card asks no dice,
    and the hand always ends; both ways out come back (asserted for every
    answer, every roll won and lost).
  - The two slots Task 5 reserved: `Q4_the_alibi` is filled (the alibi,
    below); `Q3_the_evidence` is released unfilled -- the accusation lives
    at the Lantern House desk, and a released thief is standing there.
  - No card names or implies a Magpie candidate (asserted).
  - **Unmeasured by the harnesses.** `simulate_law`, `simulate_agendas`
    and `simulate_labour` answer arrests through `execute_intent` and never
    deal this deck, so they cannot see what the room does to the file (how
    much the quashes and the added lifts move the wanted bands after
    release). Their numbers are unchanged with the deck in place (40 seeds,
    checked) only because they never reach it. `scripts/simulate_acts.py`
    deals it on every arrest (Task 8, below). The cards move no crown and no
    hour, so a stay's cost in coin and time is what it was.
- **Off the barge: the opening's three choices are real** (`game.yaml`
  `entry.opening`, through the engine's new authored-choice keys).
  - **Run**: a stealth check (standard), and `resisting_watch` committed pass
    or fail -- Brask and Tully are on the quay at eight, so a Lantern files it
    on the Quay about four runs in five. Get away and the Quay has you
    `noticed` until the next morning; fumble it and the Lantern's stop
    (`watch_stop`) begins there and then, with its five ways out.
  - **Talk**: persuasion (hard). Talk him down and nothing is written; fail
    and he writes the Magpie into his book anyway -- a `pickpocket` report
    against `magpie` on the Quay at 0.3 -- and the sergeant waves you on.
  - **Come quietly**: no longer a walk to the Lantern House but an arrest on
    the quay, on that same blurred charge: three crowns or a day in the cells,
    then out as from any arrest. It learns the cell drain, as every arrest does.
  - Every way leaves the player free to walk to the Snuffs within four
    actions (after an arrest, once the interrogation's two cards are
    answered). The Honest Company receives them there after dark (the
    initiation deck, above). No line of it names a Magpie candidate.
- **The reveal and the alibi: the Lantern House front desk**
  (`data/scenes/lantern_house_desk.yaml`), the story's third deck and its
  second `repeatable` one. It is dealt when the thief walks into the Lantern
  House FREE and a card there has something to offer, and again on a later
  visit (the director re-arms it once its `when:` is seen false: walk out,
  walk back in). A thief released from the cells is already standing there.
  - **The alibi** (`D1_the_alibi`). When the Magpie robbed a house while
    you sat in a cell, the Watch's own duty book proves it. Presented (no
    roll), it `law_discharge {alibi: true}`s exactly those robberies and sets
    `alibi_proven`, with a ledger fact. **Ruling: the alibi alone does not
    unlink you from the Magpie.** It proves you were not the Magpie on THOSE
    nights; breaking the Watch's belief is the accusation's job, so the file
    still says Magpie. **One card per belief** (Task 8): an alibi can still
    be open after a right naming, so each door ships the book twice --
    `D1_the_alibi`/`Q4_the_alibi` while the file says Magpie, and
    `D1_the_alibi_struck`/`Q4_the_alibi_struck`, whose words say the Watch
    no longer takes you for the Magpie, once it does not. Same discharge. **Once per alibi earned:** the card is gated on the
    engine's new `alibi {open: true}` (a robbery whose deed is still on the
    books), so a presented alibi is not offered again, and a robbery in a
    later stay earns, and offers, another. "Say nothing" keeps it for the
    next visit. The interrogation's new `Q4_the_alibi` is the same card
    for a thief arrested again before presenting it, and its effects are
    the desk's, word for word (asserted equal). The book's spine gained a
    third beat, `the_red_ink`: on every later arrest the file shows the
    nights the duty book cleared, in red.
  - **The accusation** (`D2_name_wren`, `D2_name_silas`,
    `D2_name_imelda`). Put the trail on Captain Ardane's desk and name the
    Magpie. Offered only when all of these hold:
    - the captain is in and awake (06:00–13:00, 18:00–23:00);
    - Evidence is at 2 or more ("some") -- measured by Task 8 (below); the
      first cut was a provisional 3 ("strong");
    - the found clues favour a suspect (`clues_favour`, at least one clue,
      and more than for anyone else). The card offered is that suspect's,
      by public name. At most one suspect is favoured at a time, so the
      player names the one their own trail points to. The gate on
      `clues_favour` is also the herring guard: the meter alone would open
      on red herrings.
    - Whether the name is right is decided by the seed (`agenda_role`), and
      the narrator learns it only from the outcome.
  - **Named rightly**, the spine happens: `magpie_unmasked`, then
    `law_unlink {a: self, b: magpie}`. The Magpie's reports stay on the
    Magpie's file and stop counting against you at once, and from the next
    prompt the GM line says who the Magpie is. Two ledger facts: who the
    Magpie is, and that the captain believed you.
  - **Named wrongly**, it costs: `magpie_named_wrongly`,
    `wrongly_accused_<suspect>`, and a `false_witness` report against your
    own face in the Wick at 1.0. On a clean face that is `noticed` for about
    two days and never `sought` -- but no accuser's face is clean: the Watch
    still links it to the Magpie, so the false witness stacks on everything
    the Magpie has done in the Wick in your name, and typically leaves the
    accuser a band worse, usually `sought` or worse, where a Lantern can
    know you on the way out (Task 8's table, below). The Watch's belief
    stands. Never a soft-lock: nothing here arrests, and the story's
    one ending reads none of these flags.
  - **A second try is allowed (owner's decision), but only for something
    new.** The suspect named wrongly is never offered again, and nobody else
    is until a clue has been carried out SINCE: the wrong naming clears
    `clue_fresh`, which every clue carried out sets again (clues.yaml's new
    `fresh_flag`). This is the gentler of the two rules offered. "A higher
    evidence band" was rejected because the meter tops out at 5 and could
    leave a thief nothing higher to show. With the wrongly named suspect set
    aside, the lead is counted among the others (`clues_favour
    {excluding}`), so a herring the thief was wrong about stops standing in
    front of the real Magpie.
  - Every card has a roll-free answer ("not yet", "say nothing"), and no
    answer arrests, moves or holds the thief (asserted for every answer,
    right and wrong).
  - **Flags for v0.17's endings:**
    - `magpie_unmasked`: named rightly; the Watch's belief is broken.
    - `magpie_named_wrongly`: named wrongly at least once.
    - `wrongly_accused_wren`, `wrongly_accused_silas`,
      `wrongly_accused_imelda`: whom. Count them for how many wrong
      namings: at most two, because the last suspect standing is the
      Magpie.
    - `alibi_proven`: an alibi presented, at the desk or in the cells.
    - `clue_fresh`: bookkeeping for the retry, not an ending's business.
  - Secrecy: before the reveal no card names the Magpie. A suspect's card
    names only that suspect, is dealt only when the player's own clues
    favour them, and says whether the naming was right only in the
    outcome. Nothing sexes the Magpie (the guard covers the new file).
  - The earlier harnesses never walk into the Lantern House free or accuse
    anybody: `simulate_jobs` (with and without agendas), `simulate_law
    --agendas` and `simulate_agendas` gave identical tables before and
    after this change (40 seeds, JSON compared, wall-clock columns aside).
    `scripts/simulate_acts.py` measures the reveal (Task 8, below).
- **`false_witness`, a deed at severity 3** (`data/rules/law.yaml`): naming
  the wrong Magpie to the captain. First set by `resisting_watch`'s
  arithmetic on a clean face (at 2 it would cool under `noticed` before the
  thief left the building; at 3 it is `noticed` in the Wick for about two
  days), then measured on the faces that actually accuse -- all linked to
  the Magpie -- by Task 8 and kept at 3 (below); charged, it is nine crowns
  or three days.
- **`resisting_watch`, a deed at severity 3** (`data/rules/law.yaml`),
  measured with `scripts/simulate_law.py --opening a`: noticed through the
  next morning, never sought on its own (table in the root CHANGELOG).
- **The Magpie's trail** (`data/premises/clues.yaml`, spec §3; the engine
  seam is `engine/world/clues.py`, root CHANGELOG). Every run hides eight
  clues in the 27 generated houses: four pointing at whoever the seed made
  the real Magpie and two red herrings at each of the other two suspects.
  Five rows are written per suspect, the same sentences whether that suspect
  is guilty or not: lamp-wick ends, lamp-soot, a pole's brass ferrule, a
  short ladder's feet, a snuffer's ring; a dozen Wickmarket pie papers, a
  Company tally-chit with its mark cut anew, flophouse back-stair mud, a
  Snuffs taproom token, a porters' rota written over in another hand;
  violet sealing-wax, a gilded temple taper, a silversmith's appraisal slip
  struck through twice, the silversmith's blue tissue, a torn place card
  from a Hill supper. A clue describes and never accuses: no name, alias or
  trade word, and no pronoun (asserted, and the sex guard now covers the
  file). **Nor is any clue a man's or a woman's thing**: a first draft's
  waistcoat thread, paste cufflink, cane dent, bay rum and pomade, and kid
  glove button were cut in review, because the Watch takes the player for
  the Magpie and a clue that sexes the Magpie sexes the player. Each clue
  points at its suspect through trade, place or habit; a wordlist test
  holds dress and grooming words out of the file. A clue's text fits the
  ledger's fact length, and the fact leads with it. The anchors hold none
  (Vessaline House is a suspect's own home).
  - Casing a clue house to the end says "something here doesn't belong",
    and stops saying it once the clue is carried out;
    the strongroom shows the clue cased or not; a job carried out keeps it
    (`clue_found:<id>`, a `clue` ledger fact) and raises **Evidence**.
  - **`evidence`**, a new veiled meter in `state.yaml`, 0..5: the prompt's
    Condition line and the sheet read it as a band word (one clue is
    "faint", four or more "utmost"), never a number.
  - Whom the found clues favour is `clues_favour`, a condition only: the
    narrator is never told where a clue points, and the GM line names nobody
    until `magpie_unmasked` (asserted in seeds that make each suspect the
    Magpie, with all eight found).
  - The interrogation header's `Q3_the_evidence` note now says the value
    is declared; its gate name is unchanged. It also warns that the meter
    rises for red herrings too, so `{value: evidence, min: N}` can open on
    herrings alone and should be paired with `clues_favour`; for the same
    reason the getaway line tells the narrator what the trail adds up to,
    never what you have on the real Magpie.
  - The accusation at the Lantern House desk (below) reads it.
  - **Measured (40 seeds).** `simulate_hoard.py` is byte-identical.
    `simulate_jobs.py`'s outcome rates are identical for every policy; only
    greedy moved, because it cases until watching tells it nothing more and
    a clue house now has one more thing to tell (one more two-hour watch,
    one more loitering roll): deeds filed a job 0.75 → 0.74, runs ending
    sought or worse 37.5% → 32.5%, wanted 2.5% → 5%; with `--agendas`,
    greedy's arrests a job 8.9% → 7.6% and sought or worse 80% → 82.5%.
    What the harness thieves find, reading only (no policy hunts clues):
    blind 0.65 clues a run (52.5% of runs find one; 27.5% lean toward the
    real Magpie), careful 0.6 (45%; 20%), greedy 0.2 (20%; 7.5%),
    greedy_bare none. Three jobs a run find little; Task 8 measures an
    investigator who hunts them (below).

### Changed

- **One clue reworded** (`violet_wax`): "the costly scented kind" of
  sealing-wax is now "the costly kind". Scent is grooming, and the clue
  wordlist test missed "scented" until v0.16 T7 made it match; the wordlist
  also gained pearl, locket, necklace and paste, and dropped "stays" and a
  bare "powder" (both ordinary words far more often). No placement moved:
  the trail samples ids, not text.
- `data/rules/agendas.yaml`'s header no longer says nothing sets
  `magpie_unmasked`: the accusation does.
- `game.yaml`'s header no longer calls the story a skeleton.
- **The acts say what is so** (`data/quests/arcs.yaml`; final review). Act
  I's blurb now arrives on the morning barge, the one the opening lands you
  from (it said evening). Act II's no longer says every Magpie robbery
  "lands on your name": it files them against your face "for as long as it
  takes the two of you for one", which stays true after a right naming.
- **Coming quietly shows its chip.** The opening's (c) carries no intent,
  so its button showed no consequence; it now reads `arrest · The Lantern
  House`, from its own authored `on_pass`.
- **The struck duty book** (`D1_the_alibi_struck`, `Q4_the_alibi_struck`)
  no longer says the nights stay marked against the Magpie's name: the
  alibi strikes those robberies off every file, the Magpie's as well.
- `data/rules/clocks.yaml`'s header no longer says the story ships no decks:
  no clock beat forces a scene, and both decks are scheduled by their own
  `when:`.
- **Two of the Company's offers now wait for its oath** (`guild_initiated`):
  - the guild bunk (`sleep_guild_bunk`, `data/rules/survival.yaml`). It still
    also needs a standing of 0 or better. Until the oath it is a rough night.
  - Mother Gannet's Silk Row contract (`gannet_silk_row`,
    `data/rules/threads.yaml`). Before the oath, a strike at the Snuffs is
    refused in her words, not with the generic "not here".
- **Rule 6 still holds.** The flophouse, a rough night, the short rest and
  the cell bench wait for nothing, in every district (asserted).
- **Ruling: the Porters' Hall bench stays open to everyone.** It is paid
  bench time, sworn or not. The v0.15 hoarder and the `craft` verb depend on
  it, and gating it would silently re-price v0.15's measured economy
  (asserted: no recipe reads `guild_initiated`).
- **Measured (rule 10, 40 seeds, before and after).**
  - These output byte-identical tables:
    - `simulate_jobs.py --policy all`
    - `simulate_hoard.py`
    - `simulate_labour.py --policy all` on the default flophouse bed
    - `simulate_agendas.py --policy all`, apart from its wall-clock
      "slowest day" column
  - No harness strikes Gannet's contract. The hoarder's squeeze on her
    (`gannet_ious`) is not gated, and the hoarder uses the bench, which
    stays open.
  - One harness relied on the gated bunk from its first night:
    `simulate_labour.py --bed bunk`. Harnesses drive intents, not
    `run_turn`, so nothing would ever deal them the deck. That policy now
    takes the oath as a harness step, the way a player does: the deck is
    dealt the first night it comes home to the Snuffs while Gannet holds
    court, and every card gets its roll-free answer. Every seed of every policy is
    sworn, on day 1 (porter, dipper, scrounger) or day 2 (careful and both
    credit policies, which come home after midnight).
    - Every bunk night is still under a roof (`bed_nights` 1.0).
    - The bounds moved slightly up, because some seeds get the oath's supper:
      - porter saves 1.02 cr a day (was 0.97); dipper 0.99 (0.93)
      - careful keeps 39% of days (33%), and 57.5% of its runs reach 0 hp
        (62.5%)
      - scrounger keeps 99% (98%); careful_pell 95% (94%); careful_marrow
        70% (69%)
    - `data/tables/labour.yaml`'s header restates the porter's bunk saving.
    - Re-measured after the deck moved to 18:00–04:00: the bunk and
      flophouse tables are identical, because every policy comes home after
      dusk.
  - Every labour policy now reports `initiation_due_day`: the first day a
    played turn would deal the deck. It is 1.0 for porter, dipper and
    scrounger, and 2.0 for careful and both credit policies. Task 8's
    investigator (`simulate_acts.py`) is dealt it and sworn on day 1 on
    every seed, or day 4 after a fumbled run's three days in the cells.

- **Acts I–II, measured (Task 8), and the evidence bar tuned 3 -> 2.**
  `scripts/simulate_acts.py`'s investigator plays the spine on purpose: off
  the barge, sworn to the Company, casing the city's houses for clues,
  burgling each clue house it learns of, and taking the trail to Captain
  Ardane's desk. 40 seeds x 12 days per barge choice (the full table is in
  the root CHANGELOG):

  | | run | talk | come quietly |
  |---|---|---|---|
  | opening passed / arrested | 50% / 8% | 28% / 0% | 100% / 100% |
  | sworn to the Company | day 1 (day 4 after a fumbled run's 3 days) | day 1 | day 1 |
  | clues carried out by day 6 / 10 / 12 | 1.2 / 2.3 / 2.5 | 1.4 / 2.3 / 2.5 | 1.4 / 2.3 / 2.5 |
  | first naming right / wrong | 62% / 12% | 62% / 12% | 65% / 12% |
  | unmasked by day 8 / 10 / 12 | 28% / 43% / 60% | 30% / 45% / 60% | 33% / 48% / 60% |
  | an alibi opened (and presented) | 18% | 20% | 15% |

  - **The bar is 2 ("some"), and the lead** (`data/scenes/lantern_house_desk.yaml`):
    since a tie favours nobody, 2 means two clues that agree (agree, not
    necessarily true: two herrings can open a wrong naming). T7's
    provisional 3 asked for no stronger case (its weakest lead is those two
    plus one pointing elsewhere), so by construction no more accurate a
    first naming, only a third house: 48% unmasked by day 12 against 60% at
    2, and wrong first no less often (19% pooled, 18-20% per opening,
    against 12%). 4 gives 21%; 1, 89%
    but 42% wrong -- a guess. The trail itself is slow (a clue is the last
    thing casing learns, so one costs ~3 houses cased) and is left as it is.
  - **`false_witness` stays at 3, and its claim is restated**
    (`data/rules/law.yaml`, the desk's header). "Never `sought` alone" held
    for a clean face only; every accuser is still linked to the Magpie, so
    the report stacks on the Magpie's Wick file. At every name offered, a
    wrong naming would have left 87% of accusers at `sought` or worse (42%
    before it) -- typically a band worse. None of the 15 real wrong-namers
    was arrested before day 12. 2 would leave a quarter feeling nothing; 4
    puts every one at `sought` or worse.
  - **The duty book comes in two** (`D1_the_alibi_struck`,
    `Q4_the_alibi_struck`): after a right naming the card no longer says the
    file still says Magpie.
  - Every earlier harness re-run at 40 seeds: identical, no bound moved.

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
