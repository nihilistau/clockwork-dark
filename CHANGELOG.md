# Changelog

All notable changes to The Clockwork Dark.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html) —
loosely, since nothing imports this as a library. A MINOR bump is a release the
player or the author would notice; a PATCH is repair.

**Entries before 0.4.0 were written after the fact**, from the commits
themselves. Nothing was kept at the time, so they are shorter and less certain
than what follows. `git log` is the authority for anything before 0.4.0; this
file is the authority from 0.4.0 on.

## [Unreleased]

## [0.15.0] — 2026-09-26

**HUE & CRY: the guild economy**, the third of the v1.0 stages. A thief in
Tallowmere now has something to build, something to collect and something to
hold over people: a bench at the Porters' Hall where the new `craft` verb
turns fence-bought makings into picks, smoke, a lamplighter's coat and a
forged Hill pass; the Magpie's Hoard, six famous shines to carry home and
never fence; a secret carried out of a job held as a lever, and four
squeezes on the people who matter; and the fences' credit, a lifeline that
turns on a welsher. Brask names no price to a clean record now. The engine
seams it needed are generic (`filed`, `secret_held`, `repeatable`,
`broken_text`, `refusals`, `refuses_to_buy`, `districts`, `min_chance`, a
collections validator), and the flagship gains the `craft` verb wherever it
can actually make something. Every number was measured, and re-measured
together at the end; no earlier bound moved. Welshing on a fence still nets a
purses-only pickpocket a few kept days, and the owner let that stand (below).
Neither the balance harnesses nor the test suite write saves any more.

### Added

- **`filed`, a condition predicate: is there anything on file?**
  `{filed: {jurisdiction, guise?, linked?}}` is true while a live report row
  matches, read through `law.report_matcher` -- the one row matcher the
  `quash_reports` effect now uses too, so a gate and the bribe it guards
  agree on which rows are meant. False in a story with no Law, with no
  jurisdiction (a blank or whitespace-only one included: it used to strip
  to "no filter" and match every drawer), or naming a jurisdiction or guise the Law does not know; an
  agenda naming one is refused at load, and a lawless story's agenda may not
  use it at all.
- **`craft`, an intent verb: making something is a choice now.**
  `craft_item` was an optional storyteller skill no choice could reach
  (`tests/test_reachability.py` allowlisted it as "needs a recipe-selection
  surface first"; that row is gone). The verb's enum is built per turn from
  `mechanics.craftable_here` -- the recipes whose station is here (or which
  have none), whose tools are held and whose inputs are carried -- asked of
  the same refusal rule `craft_item` applies (`_craft_refusal`), so an
  unaffordable recipe is unsamplable, and one that goes illegal before it
  runs (the station left, an input spent) comes back as the engine's refusal
  and reaches the prose as one. `craft_item` now reports the attempt under
  `ok` (a spoiled batch happened; `success` is how it went), adds the
  recipe's `name` and a `spent` list, and has a receipt line: what was
  made, how well, and what was spent. It is in the evaluator's
  `ROLLING_SKILLS`, because the check rolls inside it. With nothing
  craftable the verb is absent altogether, so every story without
  `paths.recipes` keeps byte-identical turns (asserted per story).
  **The Clockwork Dark gains the verb** wherever the player can actually
  make something: at the forge or the bakery with the tools and the stock,
  or anywhere for a stationless recipe (five wild mushrooms to dry, say).
  Its opening pack crafts nothing, so a new run's first turns are unchanged.
- **HUE & CRY: the Porters' Hall bench.** The story declares
  `paths.recipes` (`data/recipes/workshop.yaml`): four recipes, all
  `station: the_snuffs`, all `craft` -- file a set of lockpicks (bent wire
  and a file tang), roll two smoke pellets (candle ends for the tallow, and
  saltpetre), cut a **lamplighter's coat** (rags and brass buttons) and
  forge a **Margrave's Hill gate pass** (a vellum offcut, candle ends for the
  seal). Every input comes from a fence or the gutters, never an honest
  counter: Marrow sells wire, file tangs and rags; Pell Hollis sells vellum,
  saltpetre, buttons and candle stubs; the Snuffs' middens now turn up bent
  wire and saltpetre among the odd finds (`forage.yaml` `tenements`,
  uncommon). New items `bent_wire`, `saltpetre` (scrounge.yaml),
  `file_tang`, `vellum_offcut` (goods.yaml), `lamplighters_coat`
  (guises.yaml) and `forged_pass` (tools.yaml). The coat is a new guise,
  `lamplighter` (`law.yaml`): wear it and a witness files "a lamplighter".
  The pass is a jobs `tools` row -- approach and the door, -1 -- limited to
  Margrave's Hill by the new `districts` key (below). Nobody sells a coat or
  a pass; the bench is the only way to one. The `craft` verb reaches
  HUE & CRY only at the bench with the makings in hand; everywhere else its
  turns are byte-identical (asserted: the docks' opening, the bench
  empty-handed, the makings away from it).
- **`districts` on a jobs `tools` row.** Optional, a name or a list: the
  tool applies only to jobs on premises standing in those districts. Each
  must be a location that `districts.yaml` puts a house in -- an unknown
  place, or one with no premise, is a load fault naming the file. A row
  without it applies everywhere, as before (asserted); docs/AUTHORING.md
  §3.12. `premises.house_districts()` answers the loader.
- **HUE & CRY: the Magpie's Hoard.** The story's one collectable set
  (`data/tables/collections.yaml`, new): six famous shines off the Watch's
  list that the ballad says the Magpie took and never fenced -- the Lantern
  House Knocker, the Margrave's Swan Salt, the Nightingale Comb, the
  Chandlers' Loving Cup, the Mitre of Saint Wick and the Harbourmaster's
  Chain (goods.yaml, each `shiny`, `named` and `collection:
  magpies_hoard`). Four rest in the anchors, so in every seed: the Captain's
  Office, the Margrave's Treasury, Vessaline House (a piece stolen FROM the
  house and returned by the Watch) and Mother Gannet's House. Two are found
  in secret places by standing there -- under the Old Bell Tower's cracked
  bell and on a grating in the Undercroft -- as quests that start and finish
  on arrival (`data/quests/the_magpies_hoard/`, a side arc that opens only on
  a visit to one of them, so the journal says nothing before the place is
  known). Named pieces stay hot for good, so the Hoard is kept, not fenced;
  it counts only what is carried, and pays once. Completing it: the Honest
  Company +8, the flag `magpies_hoard_complete` (read by nothing until
  v0.17.0's The Legend -- CLAUDE.md), and a ledger fact; its reward line
  reaches the prose whether the last piece came by a burglary (the receipt
  line) or a find (the quest event's text, `quests._with_closed_sets`). No word of it names a secret place or any of the three people the
  seed may make the Magpie (asserted). `goods.yaml`'s "shiny: nothing reads
  it yet" now says what does: the Magpie's agenda (`loot_tag: shiny`).
- **`check_collections`, a validator for collectable sets.** There was none.
  Every set's members must be items, `counts` may name only members, an
  item's `collection:` must name a declared set, and every member must name
  its own set in its item row. `check_collections_data` is the reusable
  half (tests/test_items.py feeds it broken tables).

- **A secret carried out of a job is held: `secret_held`.** Before, a
  cased secret reached the job's score receipt as prose and nothing else --
  no state, no memory, and no line the narrator was ever given. Now the
  score's line says it was FOUND (and is the thief's only if they get
  clear), and the getaway that carries the job out (`clean` or `noisy`)
  writes, through `apply_effect`, the flag `secret_held:<premise>:<secret>`
  and an engine-sourced ledger fact of `kind: secret` (the kind
  `LedgerFact` already declared) about the premise's owner, through the
  ledger the `job_stage` skill passes. Held at the getaway and not at the
  score: a thief caught leaving the Captain's Office must not squeeze the
  captain over a file the Watch just took back (review, fix round 1).
  Caught, aborted, hurt, uncased or a failed score: nothing held.
  `{secret_held: {premise?, secret?}}` joins the shared grammar beside
  `premise_robbed`. The getaway's line says the thief came away holding the
  secret and, where it opens a thread, who it is a lever over
  (`receipt["held"]`, `receipt["lever"]`, a name) -- never a price, since
  whether a squeeze can be struck is its thread's own gate. No new draw, so
  a seed replays the same. Stories without jobs never write the flag (asserted for the flagship
  and the synthetic Law-only story).
- **`thread:` on a premise secret.** `{id, text, thread?}`: the template
  holding the secret opens. Checked at load: it must be a template in the
  story's `threads.yaml`, and its `requires` must read `secret_held` for that
  secret (an anchor's clause may name its own premise too), or the premise
  file fails naming itself -- a lever offered before it is held, or never,
  is the inert shape. docs/AUTHORING.md §3.10 and §3.12.
- **HUE & CRY: four squeezes.** Each anchor's secret names a `Blackmail`
  thread (a new tag), sourced by the person it squeezes and struck only
  where and when that person is awake and receiving (their schedule rows),
  with the secret held:
  - **The butler's memoir** (`vessaline_memoir`) -- Lady Imelda, in her
    parlour or at the silversmith's window; twenty crowns, collected at the
    window of an afternoon. It turns on her butler's book about the rest of
    the Row and on nothing that says whether she is the Magpie (asserted:
    no `magpie`, `debt`, `owes`, `ruin`, `motive` or `thief` in its words).
  - **The strike fund's IOUs** (`gannet_ious`) -- Mother Gannet, in the
    Porters' Hall; twelve crowns, and the Company's goodwill -5 the moment
    it is struck (`on_seal`: the guild bunk wants 0 or better).
  - **The captain's own file** (`ardane_magpie_file`) -- Captain Ardane, at
    her desk or in her office, only while the Watch holds something on you
    somewhere (`filed`, all three jurisdictions asked). Her price is looking
    away: `quash_reports`, `linked`, with NO jurisdiction -- every
    watch-house, because all four officers and the sergeant answer to her,
    where Brask's drawer is only the Wick's.
  - **The mint-master's ledger** (`quill_light_crowns`) -- Steward Quill, at
    his table on the terrace; twenty-five crowns.
  Left uncollected for two days, each has teeth: the Row, the Hill and the
  captain file `blackmail` in their own jurisdiction (the Rise, the Rise,
  the Wick) at precision 1.0, and each squeezed party's people think 10
  worse of you (`silk_row`, `margraves_household`, `lantern_watch`); Mother
  Gannet does not go to the Watch -- nobody in the Snuffs does -- and the
  Company takes another 10. Two of the three factions CLAUDE.md listed as
  moved by nothing are moved now; only the Temple waits for the Acts.
- **`blackmail`, a Law deed, severity 3.** Decided against the deed list
  (`law.yaml`, pickpocket 1, fencing 2, burglary 3, assault_watch 5): a
  squeeze is a crime, and the Watch should be able to hear of it -- but a
  squeeze is struck in private, so its only witness is its victim, and it
  is never committed on the street as a deed with bystanders. It is FILED,
  whole, by the victim, in the thread's `on_break`: the one moment the
  victim has both the reason and the time to go to the Watch. Precision
  1.0: they saw your face. Severity measured (`scripts/simulate_hoard.py
  --severity`: one report up the Rise, then quiet days, the band each
  morning): 1 files nothing a Lantern notices; 2 is `noticed` the day it
  is filed; **3** is `noticed` for two days alone, and beside a lift seen
  up the Rise it is `sought` -- recognised on sight -- the day it lands
  and `noticed` four days more; 4 makes a squeeze alone a stop. Three,
  burglary's weight: a crime against a house, never against the Watch.
  (Restated in Task 8 from that committed replay: the first draft's
  "three days alone" and "sought for five or six" came from a scratch
  script and do not reproduce. `test_the_blackmail_deed_weighs_what_law_yaml_says`
  holds the replay.)

- **HUE & CRY: the fences' credit.** Two `Credit` threads (a new tag),
  each struck only at its fence's own counter while she is trading there
  (`at_location` plus her schedule's hours) and only while no copy of it is
  open:
  - **Pell Hollis's advance** (`pell_advance`), Wickmarket, 08:00-23:00: ten
    crowns across the counter when struck (`on_seal`), thirteen back across
    it inside three days.
  - **Marrow's slate** (`marrow_slate`), the Snuffs, 17:00-01:00: smaller
    and dearer -- five crowns, eight back inside two.
  Settled in coin at her counter, in her hours, with the crowns in hand
  (`discharge_requires`), and then offered again. **Repaid in coin, not
  goods** -- the honest fallback the brief allowed: nothing in the condition
  grammar can say "carrying hot goods worth V", and no effect can hand over
  unnamed goods, so the debt is counted in crowns and the interest is the
  price (30% over three days, 60% over two). Left unpaid (or broken
  early) it breaks, with teeth. **The word goes round the fences:** neither
  fence buys from you (a flag both trade profiles' new `refuses_to_buy`
  read; their shelves stay open) and neither stands you credit again. **Her
  collectors walk the streets after dark for you:** two new street scenes,
  `pells_collectors` and `marrows_lads` (`data/encounters/streets.yaml`,
  the Docks, the Snuffs and Wickmarket, 18:00-06:00, weight 30,
  `requires_flag` on the break's flag, so nobody who never welshed ever
  draws them and the ENCOUNTER stream is unchanged for them, asserted).
  They take coin on account, chase or hurt (never more than three hp, a
  -2 stealth wound at worst -- the lifting hand), and paying the whole
  debt clears the flag and opens the fences again. **By day too** (owner,
  fix round 2): `pells_collectors_by_day` and `marrows_lads_by_day`, the
  same scenes (a YAML merge of the night rows), only in Wickmarket and the
  Snuffs, 06:00-18:00, at a `min_chance` floor of 10% -- 8.3% of a
  welsher's day legs into those districts, against 9-18% of a night leg
  from 20:00 to 03:00 and 22% at its worst (04:00, Wickmarket to the
  Snuffs); `scripts/simulate_streets.py --collectors` prints the table,
  hour by hour. (Earlier drafts said 13-18% and 14-18%; neither was the
  whole range.) Every one has a way out
  that needs no roll, coin or flag. Pell's stallholder neighbours think 5
  worse of you (`market_stalls`). The narrator hears the break once, in the
  thread's own `broken_text` (who is waiting after dark, and why), the
  collectors' own intro names the fence and the sum, and at a fence's
  counter afterwards the PEOPLE HERE line says she buys nothing from you,
  and why. No credit state gates rest (rule 6, asserted: a rough night
  everywhere and a paid flophouse bed after welshing on both). Both survive
  the thread bounder whole.
- **`repeatable: true` on a thread template.** A line of credit, not a
  once-a-run contract: offered again as soon as no copy of it is open, never
  while one is. Without it a struck template is still never offered again.
  Validated as a bool (`"yes"` would load as once-a-run). docs/AUTHORING.md
  §3.4.
- **`broken_text:` on a thread template.** The narrator's line when the
  thread breaks, journalled once through `engine/game/moved.py` (kind
  `promise`) -- a thread that comes due on the day tick otherwise breaks in
  silence, its `on_break` applied and nothing in the prose saying why.
  Carried on the thread only when declared, so every other thread keeps its
  shape and breaks exactly as before (asserted). Told on any break -- came
  due, broken early or cut -- so worded true for all three. **Every HUE &
  CRY thread with an `on_break` carries one** (asserted): the credit
  threads, Mother Gannet's contract, and the four squeezes, whose lines say
  who went to the Watch (so the narrator can explain the heat) -- Lady
  Imelda's about her butler's memoir and nothing else, and none naming or
  hinting at the Magpie (asserted).
- **`min_chance` on an encounter row.** While the row is eligible for a
  leg, the leg rolls at least that chance (`encounter.row_floor`,
  `leg_chance`, which `roll_for_encounter` now uses), capped at
  `trigger.max_chance`, only on an edge with a `danger_dc`. A row no one
  matches raises nothing. So every leg of a player who never welshed rolls
  exactly the v0.14 chance and draws exactly the v0.14 scene, at every hour
  (asserted draw for draw against the old formula on a seeded stream). The
  validator refuses a value outside (0, 1]. docs/AUTHORING.md §3.7.
- **`refusals: [{when, text}]` on a thread template.** When its
  `requires:` fails and a row's `when` holds, `strike_bargain` refuses in
  that row's words instead of "not here and now". HUE & CRY's credit lines
  say "no fence stands credit to a known welsher -- not until the debt is
  paid" while either welsh flag is set (asserted). Validated like any
  condition, no ledger predicates.
- **`refuses_to_buy: {when, text}` on a trade profile.** While `when` holds
  (the shared grammar) the vendor buys nothing from the player: `quote` and
  `sell` refuse in her own words (never a `fencing` deed), the `sell` verb
  leaves her out so the refusal is unsamplable, and the narrator's PEOPLE
  HERE line carries it. Her shelves stay open. The validator refuses a
  block with no `text` or `when`, or a `when` the grammar cannot answer
  here (an unknown predicate, or one that needs a ledger).
  docs/AUTHORING.md §3.10.

### Changed

- **A thread may file a `report`.** `report` joins `quash_reports` in
  `engine/challenges/spec.py::STRUCTURAL_EFFECT_TYPES`, the kinds authored
  content (threads, deck gates, set pieces) may use and a model-composed
  challenge may not. Without it the thread bounder dropped a squeeze's
  `on_break` report with only a logged adjustment -- the blackmail deed
  filed nothing. It has no magnitude to clamp (severity comes from the law
  file), and a model-composed challenge still drops it (asserted: a dice
  table must not frame the player). docs/AUTHORING.md §3.11 and
  docs/GOVERNANCE.md say so. Every squeeze is asserted to survive the
  bounder whole; the steward's price was written at 30 and the bounder
  clamps gold at 25 in this story, so it is 25.
- **Brask names no price to a clean record.** HUE & CRY's `brask_bribe`
  now requires `{filed: {jurisdiction: wick, guise: self, linked: true}}`
  beside the desk, so the `bargain` verb offers it (and `strike_bargain`
  accepts it) only while the Wick's drawer holds something against you or
  against the Magpie, whom the watch takes for you. Before, it could be
  struck and paid with nothing filed, quashing nothing; that row leaves
  CLAUDE.md's deferred list. His `discharge_requires` asks the same `filed`
  clause beside the twelve crowns, so a file that goes before payday (the
  captain's squeeze quashes it, say) cannot be paid for: the thread comes
  due and, having no `on_break`, ends without charge.
  `test_brask_takes_no_price_once_his_file_is_gone`. The captain's own
  squeeze is deliberately NOT gated so: her discharge refused would force a
  break, which files a report and costs -10.
- **A set closes by any door its last piece comes in.** Collection payouts
  moved from `inventory.grant` into the `item` effect, which every grant
  goes through: a job's getaway, a quest reward and a boon now close a set
  on the spot (before, only `grant` did, and the rest waited for the
  `collections` skill), and the payout rides the receipt as `collections`.
  A job's getaway receipt carries it up, and the narrator's receipt line
  now reads any set a receipt closed, in its `reward_text`
  (`prompts.summarise_receipt`). `evaluate_collections` takes the caller's
  ledger, so a set's `ledger_fact` lands when a quest hook closes it, and
  when a job's getaway does: `jobs.resolve_stage` takes a `ledger`, which
  the `job_stage` skill passes from the engine. A quest event whose hook
  closed a set carries the set's `reward_text` in its text
  (`quests._with_closed_sets`), which is what the ledger and the client get.
- **An agenda's robbery never takes a collectable set's piece.** An agenda
  robs by recording a hit, not by moving items, and the thief who burgles
  the house afterwards found it bare -- so HUE & CRY's Magpie, robbing the
  Captain's Office, Gannet's House or Vessaline House first, quietly erased
  that house's Hoard piece from the run. Now the score on an emptied house
  takes exactly the loot rows that are set pieces (`jobs._left_by_agendas`,
  no JOB draw, generic to any story), and the narration says the house was
  robbed of everything but them (`prompts`: the score, the close line and the
  job block).
  `scripts/simulate.py --policy all --turns 200` is byte-identical for The
  Clockwork Dark.

- **`strike_bargain` refuses a template already struck, and says why.**
  `can_strike` asked only the template's `requires:`, so the skill would seal
  a second copy of a contract the `bargain` verb had stopped offering; it now
  asks the verb's own once-a-run rule (or, for a `repeatable` template, "no
  copy open") first, and `offerable` reads it through `can_strike`. The
  refusal names the gate that is shut (`threads.strike_refusal`): "already
  struck and still open -- settle it first", "already struck once", or
  "cannot be struck here and now" -- never the last for the first two.

### Fixed

- **The balance harnesses and the test suite filled the owner's save
  folder.** Both wrote real runs into `data/saves/<slug>/` -- about 29,700
  of them in `hue-and-cry/` alone, nobody's play, crowding the load menu's
  index. The owner has cleared them. Two leaks, two fixes:
  - **The harnesses** wrote one save per seed (`SessionStore().create`'s
    first save, through `simulate_law.Thief`, which every harness's player
    is built on). `DefaultSessionStore` now takes an optional `save_store`
    for one instance, and the harnesses hand it one that keeps nothing (no
    path, so nothing to configure or clean up). The measured runs are
    unchanged: a save reads the state and never writes it.
    `test_a_harness_run_leaves_the_save_store_untouched` plays a short day
    of every harness and asserts no save is written.
  - **The tests** wrote one for every session they created or turn they
    played (autosave): `paths.saves` is an engine output no story overlay
    moves, and only a handful of tests redirected their own store. A new
    autouse fixture, `tests/conftest.py::_no_test_writes_real_saves`,
    points `saves.saves_base` -- the one function every save root is built
    from -- at a per-test temp directory and drops the cached store on the
    way in and out; a test that names its own `SaveStore(root=...)` (the
    legacy-migration tests) is untouched. A breach fails the test at
    teardown (a save failure is logged and forgiven, so nothing in the test
    body can be trusted to see it), by two O(1) checks about this process
    only: an audit hook (`sys.addaudithook`) records every write-mode
    `open`, `mkdir`, `rename`/`replace` and `remove` aimed under the real
    directory, and the redirect must still be in force (`saves_base` and
    the cached store's root outside it). It does not scan the directory, so
    it costs the same with the owner's thousands of saves as with none, and
    the owner's own game autosaving mid-suite fails nothing. The redirect
    is held by the fixture's own `MonkeyPatch`: the teardown check found
    that a test calling `monkeypatch.undo()` mid-body
    (`test_forced_and_repeatable_decks`) undid it along with its own spy,
    so the rest of that test saved into the owner's folder
    (`test_a_tests_own_monkeypatch_undo_keeps_the_saves_redirect`).
    `test_the_saves_guard_sees_a_write_into_the_real_directory` is its
    canary (each write aims at a folder that does not exist, so nothing
    lands). After a full-suite run, `data/saves/*` is still empty.
- **The `craft` verb re-parsed every recipe file on every build.**
  `mechanics._load_recipes` read the recipe YAML each time
  `craftable_here` built the verb -- three or four `legal_intents` calls a
  turn, ~30 ms each for the flagship's 22 recipes. It is memoized now on
  the recipe directory and every file's name and mtime (a story switch, an
  edit, an added or removed file all reload), and nulled on activation and
  between tests (`engine/games/caches.py`). A flagship `legal_intents`
  went from 36.4 ms to 2.8 ms a call.
- **The collectors' day rows spoke of the night.** `pells_collectors_by_day`
  and `marrows_lads_by_day` were YAML merges of the night rows and inherited
  "see you another night", "they let you go -- tonight" and "They let you
  by, tonight" -- in a noon street (audit questions 2 and 3). The day rows
  now restate `approaches` (the unchanged ones by YAML anchor, the two whose
  words were the night's in full) and Marrow's lads' intro, day-true.
  Mechanics identical (checked field for field but the text).
  `test_no_daytime_street_scene_speaks_of_the_night` fails any row that can
  only fire by day and says "night" anywhere in its words.
- **A found place kept its cover name.** The awareness gate rewrote on
  awareness alone, so once HUE & CRY's Undercroft was found the travel
  choices called it "The Undercroft" while every gated GM line still said
  "the old drains". A `spoilers.yaml` row may now carry `location: <id>`;
  the gate drops the row for a player who knows that place
  (`locations.is_known`), in gated prompt regions. The three
  hue-and-cry secret rows name their places; `check_spoilers` refuses a
  `location:` that is not in the graph. No other story's rows name a place,
  so their gated prompts are byte-identical (asserted per story).
- **The lore paired a cover name with its place.** `the_hidden_city.md`
  said "the old drains ... the Undercroft" in one sentence, teaching the
  narrator they are one place; it no longer does, and a test keeps every
  secret's cover and name out of the same chunk. Rebuild the story's
  `lore.db` with `CLOCKWORK_GAME=hue-and-cry python scripts/seed_lore.py
  --clear`.
- **The flagship's tinderbox never closed the road kit.** It is a
  `road_kit` member whose item row did not say so, and a set settles only on
  an item that names its set, so a tinderbox bought last closed nothing.
  The new collections validator found it; `gear.yaml` names the set now.
- **`recall_subject` never had a ledger in a live session.** It reads the
  session's memory off the engine (`getattr(engine, "ledger", None)`), and
  nothing ever put it there, so in every session it answered "no ledger in
  this session". `SessionStore._build` now sets `engine.ledger` to the
  session's ledger; the `job_stage` skill reads it the same way.

### Measured — the fences' credit

`scripts/simulate_labour.py` gains `careful_pell` and `careful_marrow`: the
careful pickpocket's own day, plus one line of credit struck whenever that
fence will stand it one and its purse is under 3 crowns, repaid at her
counter the moment it holds the debt. `--no-credit` runs each as its own
control (the same visits to her counter, no line ever struck), and
`collectors_met` counts the collectors' street scenes, night and day, that
came for it. Flophouse beds, agendas off, 40 seeds. Kept days are counted
as DAYS (days fed and under a roof, per run), because a share of a longer
run is not comparable with a share of a shorter one:

| policy | run | kept days | gain over control | earned / day | end gold | broken | collectors met |
|---|---|---|---|---|---|---|---|
| careful_pell `--no-credit` | 10 d | 0.7 | -- | 1.36 cr | 2.30 | -- | -- |
| **careful_pell** | 10 d | **5.4** | **+4.7** | 1.20 cr | 1.85 | 95% | 0.53 |
| careful_pell `--no-credit` | 20 d | 1.0 | -- | 1.39 cr | 2.92 | -- | -- |
| **careful_pell** | 20 d | **5.8** | **+4.8** | 1.25 cr | 3.10 | 95% | 1.20 |
| careful_marrow `--no-credit` | 10 d | 0.7 | -- | 1.36 cr | 2.17 | -- | -- |
| **careful_marrow** | 10 d | **3.1** | **+2.4** | 1.18 cr | 1.27 | 93% | 0.50 |
| careful_marrow `--no-credit` | 20 d | 1.0 | -- | 1.44 cr | 3.52 | -- | -- |
| **careful_marrow** | 20 d | **3.4** | **+2.4** | 1.27 cr | 2.50 | 93% | 1.32 |
| porter (honest) | 20 d | 18.4 | -- | 2.37 cr | 7.42 | -- | -- |

**Welshing still beats never borrowing, and the teeth do not erode the
gain.** A careful pickpocket who takes Pell's advance and never repays it
keeps about 4.7 more days fed and roofed than one who never borrows. Over
20 days the gain is +4.8, the same. Marrow's slate gives +2.4 at both
lengths. Nothing claws the gain back. The ten crowns of bread are eaten in
the first week; after that the welsher's days look like the control's.

What welshing does cost it:
- 93-95% of lines break.
- No fence buys from it again: earnings are about 0.15-0.19 cr a day lower.
- Neither fence lends to it again.
- The collectors find it about once in ten days and about 1.2-1.3 times in
  twenty. That is by day too, in the fences' districts, since fix round 2.
  But they rarely find more than a crown or two on a thief who lives on
  less than it needs, and it usually outruns them.

At 20 days a Marrow welsher holds less coin than its control. A Pell welsher
holds a little more (3.10 against 2.92), because its lost sales are
cheap goods and its lost crowns are its rent.

Welshing is never a living: 5.8 kept days out of 20, against an honest
porter's 18.4.

**The owner's decision, for v0.15.0: this stands.** Welshing on a fence's
credit still nets a purses-only pickpocket about 5 kept days over never
borrowing (Pell's advance) or about 2 (Marrow's slate), and the owner
accepted that for this release. The real cost of welshing falls on a thief
who needs a fence -- a burglar with a haul to sell, shut out of both
counters -- and v0.18.0's thief policy is where that is measured. Nothing
in v0.15.0 re-tunes the credit to close the gap.

**Where hp goes to 0** (Task 8; `simulate_labour.py` now reports
`runs_at_zero_hp` and `collectors_hp_lost`). Hunger, not the collectors:
the careful pickpocket who never borrows reaches 0 hp on 95% of seeds in 10
days (97.5% in 20), on bread it cannot afford. On credit it starves less --
Pell's advance 45% of seeds in 10 days, Marrow's slate 82.5%; 97.5% for both
in 20 -- and the collectors cost it 0.15-0.45 hp a run in 10 days and
0.3-0.6 in 20 (three hp is the most one meeting takes). A starving welsher
meeting the collectors is a way to 0 hp, but a rare one; the everyday way
is the empty purse. Both wait on v0.17.0's `death.yaml` (CLAUDE.md).

(Earlier drafts of this entry said kept days "halve" between 10 and 20
days. They did as a share -- 54% to 29% -- only because the run doubled;
in days they did not move.)

The policy never sets the advance aside to repay it, and for this earner
that changes nothing. A purses-only pickpocket takes in about 1.4 cr a day
and spends about 1.6 on bread and a bed. It could find thirteen crowns by
the third day only by leaving the advance unspent. That returns it to where
the control is, three crowns poorer. The credit helps it only if it is
spent, and a spent advance is one it cannot repay.

The controls reproduce the v0.14 `careful` row exactly (1.36 / 7% / -0.28
at 10 days), so no draw moved. The difference is the credit, not the walk
to her counter.

A note on method: control figures from runs made eight at a time once
drifted by a hundredth in earnings on two rows, and the table uses solo
re-runs for those rows. Task 8 re-checked it on a clean tree (a detached
worktree at `wip T7: fix round 2`): the two controls run four times each,
all eight at once, came out byte-identical, and equal to the table. No
engine path could cause the drift; content edited mid-batch is the likely
cause, and every Task 8 figure was measured in a worktree nobody edited.

`tests/test_hue_and_cry.py::test_pells_advance_is_a_lifeline_and_a_trap`
holds four things over 8 seeds x 8 days:
- the lifeline;
- the trap;
- the lower earnings;
- the gap to the porter.

### Measured — the bench

An exact expectation rather than a sample: every d20 face through HUE & CRY's
skills.yaml DCs and degree table at each recipe's band, for a thief at +0
craft (every archetype, fed and rested), inputs at the cheapest fence price,
a failed attempt's salvage credited at that price (`tests/test_hue_and_cry.py`
`_per_attempt`, the same arithmetic the tests assert):

| recipe | band | hours | coin a try | made a try | coin each | at a counter | best a counter pays |
|---|---|---|---|---|---|---|---|
| lockpicks | easy | 4 | 9 | 1.00 | **7.25** | 15 (Marrow) | 5 |
| smoke pellets (x2) | standard | 2 | 3 | 1.10 | 2.7 | 4 (Marrow) | 1 |
| lamplighter's coat | standard | 3 | 4 | 0.70 | 5.1 | nobody | 1 |
| forged Hill pass | hard | 3 | 4 | 0.45 | 8.9 | nobody | 2 |

So a set of picks from the bench costs under half of Marrow's 15 and four
hours his counter does not. Against the v0.14 cost of living ([0.14.0]: a
careful pickpocket keeps ~1.4 cr a day, a porter ~2.3), the 7.75 crowns saved
are five or six days' keep; the four hours are a sixth of a day's bread
(~0.3 cr) and an evening not spent casing. Nothing on the bench is a mint:
everything made sells for less than its bought makings cost, unhaggled and
haggled -- at the 20% cap on both sides the picks cost 6.5 and fetch 6, which
is why the tang is 7 crowns and not 6 (at 6, a double haggle cleared a
quarter-crown a set).

The middens' two new finds were measured against HEAD before them (40 seeds
x 10 days, a detached worktree at `wip T3`): `simulate_scrounge.py`'s
scrounger 1.01 -> 1.02 cr a day and mornings 0.66 -> 0.65, food a day, hungry
days, min hp and every secret way's share and day unchanged (the finds are
uncommon rows, so the draws are the same and only which odd thing turns up
moves); `simulate_labour.py` identical for porter, dipper and careful, the
scrounger's end gold 4.53 -> 4.50; `simulate_jobs.py` byte-identical (no
policy carries a pass, and the careful thief's picks are still on Marrow's
counter). No bound in tests/test_hue_and_cry.py moved.

**Found on the way: the `buy` verb shows eight things a place.** Adding the
bench's makings to Marrow's counter (five rows before, ten in the first
draft) pushed `rag_bundle` and `smoke_pellet` off the end of the enum
(`intents._MAX_OPTIONS`, cut in id order): stock nobody could choose, and
the pellet gone from its only counter. Caught by this task's own
buy-everything test before it shipped. The makings were split between the two fences so each
holds eight, docs/AUTHORING.md §3.7 says so, and
`test_every_counter_offers_all_of_its_stock` fails if a row is cut again.

### Measured — the Hoard against the jobs harness

`simulate_jobs.py`, 40 seeds, re-run against the run before the Hoard: only
the greedy thief's haul moved, because only it robs an anchor -- the
Treasury's 780 -> 980 crowns (the Swan Salt), its "all" row 277.4 -> 320.6.
Every other cell of every policy is identical (`data/rules/jobs.yaml`'s
table restated). `simulate_agendas.py` identical but for wall-clock timings:
the Magpie chooses a house by the `shiny` tag, and every anchor it may rob
already held a shiny piece. Re-run once more after an agenda's robbery
stopped taking set pieces: `simulate_agendas.py` again identical but for
timings (it counts collisions, not what a collision leaves), and
`simulate_jobs.py` byte-identical (agendas off). How often a run completes
the Hoard is measured below (the guild economy, all at once).

### Measured — the guild economy, all at once (Task 8)

**Every HUE & CRY harness, re-run at 40 seeds** -- on the release branch's
head (`wip T7: fix round 2`) and on the `v0.14.0` tag, each in a detached
worktree nobody edited during the batch:

| harness | v0.14.0 | v0.15 head | moved because |
|---|---|---|---|
| simulate_law | careful below `sought` 100%; reckless `wanted` by day 4 75%; reckless / briber arrested 82.5% / 82.5% | identical (but wall-clock timings) | -- |
| simulate_jobs | careful tier 1-2 carried out 80.8% / caught 0%; blind caught 36.7%; prepped Treasury 20% | identical, but the greedy Treasury haul 780 -> 980 cr | the Swan Salt (the Hoard, above) |
| simulate_agendas | idle `sought` by day 6 80%; Magpie 9.8 houses a run; reckless net at `utmost` 65% | identical (but timings) | -- |
| simulate_scrounge | scrounger 1.01 cr a day, mornings 0.66 | 1.02, 0.65 | the middens' two new finds (the bench, above) |
| simulate_labour | porter 94% kept, +0.05 cr a day; dipper 87%; careful 7%; scrounger end gold 4.53 | identical; scrounger end gold 4.50 | the same finds |
| simulate_streets | night legs 19.7% a scene, 0.09 cr lost a night leg | byte-identical | -- |

No bound in `tests/test_hue_and_cry.py` moved, and none is restated. (One
correction to [0.14.0]'s restatement table: its "after" cells for the jobs
harness, 80.6% and 36.5%, are not what the v0.14.0 tag measures -- the tag
gives 80.8% and 36.7%, the table's "before".)

**A concurrent determinism re-check.** The fences' credit measurement (above)
once saw a hundredth of drift between runs made eight at a time. On the
clean worktree, `careful_pell --no-credit` and `careful_marrow --no-credit`
(40 seeds x 10 days) were each run four times, all eight at once: every copy
of each came out byte-identical (and equal to the table). No drift.

**Crafted against bought tools**: the bench's table above (the exact
per-attempt expectation). A set of picks from the bench costs 7.25 crowns
and four hours against Marrow's 15; nothing on the bench sells for more than
its makings.

**Fence-credit kept days**: the credit table above -- +4.7 days over 10 (+4.8
over 20) on Pell's advance, +2.4 on Marrow's slate, 93-95% of lines broken,
and the owner's decision beside it.

**The Magpie's Hoard in a twelve-day run** (`scripts/simulate_hoard.py`, new:
the `hoarder` robs the four anchors one a night, easiest first, the
simulate_jobs greedy way -- lockpicks and smoke pellets, cased until casing
tells it nothing more, in at eleven, never walking away -- and goes at the
Treasury carrying the **forged Margrave's Hill pass**, v0.15's own tool for
it (jobs.yaml: -1 at the Hill's approach and door). Nobody sells a pass, so
it makes one as a player would: the makings for five tries bought at Pell
Hollis's counter on day one (20 crowns), then the Porters' Hall bench of a
morning until a try takes. It scrounges the streets whose hidden paths lead
to the secret places, walks to one the moment it knows the way, and keeps
everything; fed and rested, and handed its kit's price on day one, as the
jobs harness is; agendas off; 40 seeds. `--no-pass` is the control: the
same thief without the pass, which is what this entry first reported):

| | 12 days | 20 days | control (`--no-pass`), 12 / 20 days |
|---|---|---|---|
| **Hoard completed** | **2.5%** (1 run of 40) | **10%** (mean day 18) | 5% / 10% |
| the Hill pass made (mean day) | 92% (1.2), 2.0 tries a run | 92% (1.2) | -- |
| Treasury tries carrying it | 70% | 83% | -- |
| pieces held at the end, mean | 3.2 | 2.1 | 2.5 / 2.2 |
| runs ending with no piece | 20% | 45% | 40% / 45% |
| Mother Gannet's House carried out / caught a try | 100% / 17% | 100% / 17% | 100% / 11% (both) |
| the Captain's Office | 100% / 11% | 100% / 11% | 98-100% / 11% |
| Vessaline House | 48% / 80% | 68% / 83% | 48% / 79%, 70% / 82% |
| **the Margrave's Treasury** | 2% / 90% (0.25 tries a run) | **20% / 92%** (2.6 tries) | 5% / 91% (0.57), 12% / 96% (2.9) |
| the Old Bell Tower found (mean day) | 88% (4.5) | 92% (5.2) | 80% (4.4), 88% (5.3) |
| the Undercroft found (mean day) | 78% (4.2) | 100% (7.3) | 92% (4.5), 98% (5.1) |
| arrests a run | 0.28 | 0.88 | 0.5 / 1.05 |

The one twelve-day completion closed on the twelfth night's getaway, in the
small hours of day 13.

**What the pass buys: a little, late.** Over twenty days it takes the
Treasury from 12% of runs to 20%, and a try there from 96% caught to 92%.
Over twelve it buys nothing measurable: the day at the bench pushes every
job back a night, so the Treasury -- robbed last -- is reached a quarter as
often (0.25 tries a run against 0.57), and twelve-day completion is 2.5%
against the control's 5% (one run against two: noise, at 40 seeds). The
Treasury stays the wall -- caught on nine tries in ten with the pass or
without -- and Vessaline House nearly as hard. And **an arrest takes the
whole Hoard back**: every piece is `named`, so hot for good, and
`{type: arrest}` takes every hot thing carried (watch_stop.yaml). That is
why a fifth to a half of runs end holding nothing -- they held pieces until
a stop went wrong. A thief who wants the Hoard wants the Treasury last, a
pass in its coat, and no Lantern in between.

**Blackmail yield** (the same runs, with the pass: a secret carried out is
squeezed the next day at its owner's door and collected there on the spot,
so almost none broke):

| squeeze | secret held (12 d) | pays when collected |
|---|---|---|
| The strike fund's IOUs (Mother Gannet) | 100% | 12 cr, and the Honest Company -5 on striking |
| The captain's own file (Captain Ardane) | 100% (collected in 92%) | no coin: each collection makes about 3 Watch reports go missing, in every watch-house |
| The butler's memoir (Lady Imelda) | 40% | 20 cr |
| The mint-master's ledger (Steward Quill) | 0% (15% over 20 days) | 25 cr |

20.0 crowns a twelve-day run from squeezes (28.75 over twenty; the control
22.25 and 28.0) -- almost all of it Mother Gannet's twelve and, in two runs
of five, Lady Imelda's twenty, because the richest squeeze sits behind the
hardest door. The captain's is the one a thief with a file on it most
wants: it pays in files, not crowns. `scripts/simulate_hoard.py --severity`
replays the `blackmail` deed's weight (the deed's entry above, restated
from it).

**The collectors' share of a welsher's legs**, hour by hour:
`scripts/simulate_streets.py --collectors` (no dice -- the table the draw is
made from, for a fresh thief). 8.3% of every day leg into Wickmarket or the
Snuffs (06:00-16:00), 4-8% at dusk, 9-18% of a night leg from 20:00 to
03:00 (the most on Wickmarket to the Snuffs), and 22% at 04:00, the worst
hour. The same for both fences.

## [0.14.1] — 2026-09-26

A documentation release: the GitHub README, rewritten. No engine, content or
client change.

### Changed

- **README.md** now leads with what the engine is (a deterministic engine
  that resolves, local models that narrate) and shows it: a table of the six
  stories and what sets each apart, the systems grouped by what they do, a
  turn-loop diagram, getting started kept to what `launcher.py` and
  `scripts/start.ps1` actually do, and the roadmap to v1.0.0 in the owner's
  order, every item there marked planned.
- **docs/images/** adds 13 images (952 KB): 11 captures of the running UI
  (opening screens, maps, one deck card -- taken with no model server, so no
  generated narration is shown) and two montages of committed art plates.

## [0.14.0] — 2026-09-26

**HUE & CRY: the living city**, the second of the v1.0 stages. Tallowmere
becomes somewhere you can live, not just rob: a bed (and, for the first time
in this story, a rest verb -- rough sleep is never refused), bread to buy, the
gutters to scrounge, honest work that pays thin but true, luck that turns,
streets that are dangerous after dark, seven factions with an opinion of you,
and the city's lore for the narrator. The three secret places can finally be
found. Every number was set by measurement and re-checked together at the
end; no earlier bound moved.

### Fixed

- **A rest note named a place by its id.** When a bed was out of reach the
  rest receipt said "(no bed at forest_clearing)"; it now uses the place's
  display name, in every story -- the flagship's and NEON CITY's note text
  changes by exactly that (ids never reach the narrator).
- **Rest could be refused or handed out by a slip.** A misspelt rest kind
  fell back to the first entry without asking its gates (a story whose first
  rest is a priced bed gave it away free), and a `requires:` that raised
  would have propagated out of `rest()`. Both now downgrade along the
  fallback chain; rest is never refused (rule 6).
- **A found way was spelt as an id.** The forage discovery line read "a
  quicker way through to the undercroft"; it now uses the place's name.
- **The narrator's town-wide work list ignored hours.** Work elsewhere that
  keeps hours (`when:`) now says whether it is `open_now`, so the narrator
  no longer hears that Wren is taking on hands at eight in the morning. Jobs
  that keep no hours read exactly as before.
- **A typo in `hidden_path_placements` would strand a secret place.** The
  validator (doctor) now checks each pinned `from` and `leads_to` is a place
  in the story's graph.

### Added — HUE & CRY: somewhere to sleep (v0.14 task 1)

- **A rest verb in Tallowmere.** HUE & CRY shipped no `survival.yaml`, so it
  had no rest verb at all (and, because of that, walking was free). It now
  ships `games/hue-and-cry/data/rules/survival.yaml`: a pallet at Old Nance's
  flophouse in the Snuffs (1 cr), a free bunk over the Porters' Hall for anyone
  the Honest Company has no quarrel with (standing 0 or better), a room at the
  Snuffed Wick or over the Tallow Barge (3 cr), the plank bench in the cells
  while held, `rest_short`, and `sleep_rough` anywhere, always, ungated (rule
  6). Every one-hour street now costs 5 stamina, which is the engine's rule for
  a story that can restore it. Starvation bites at the flagship's 0.4 hp an
  hour rather than the engine default of 1.0 (no `death.yaml` yet).
- **Meals.** `data/items/food.yaml`: heel of bread (1 cr) and eel pie (2 cr)
  from Dock Mag's basket, ship's biscuit (1 cr) at Pell Hollis's into the
  evening, each with an `eat:` row.
- **Engine: priced and gated beds** (`engine/game/survival.py`). A rest entry
  may declare `cost: N` (paid at the door through the `gold` effect; the
  receipt gains `paid` and the narrator's receipt line says "paid 1 cr for the
  bed") and `requires:` (a condition in the shared grammar). Unmet, either
  downgrades to `fallback` — never a refusal — and the fallback chain is itself
  checked. Stories that declare neither are unchanged key for key.
  docs/AUTHORING.md §3.14 documents `survival.yaml` for the first time.

Measured (a scripted day: simulate_law's careful and reckless days, 40 seeds x
10 days, agendas off, the thief buying two heels of bread each morning with its
own coin instead of being fed by the harness):

| policy | bed | coin in/run | end gold | unfed days (of 9) | min hp | arrests/run |
|---|---|---|---|---|---|---|
| careful | bunk | 10.1 | 2 | 5.8 | 1 | 0 |
| careful | flophouse | 10.6 | 0 | 7.3 | 0 | 0 |
| careful | rough | 9.6 | 1 | 5.9 | 0 | 0 |
| reckless | bunk | 28.8 | 13.5 | 0.03 | 20 | 0.80 |
| reckless | flophouse | 28.6 | 6 | 0.40 | 14 | 0.82 |
| reckless | rough | 28.1 | 13 | 0.00 | 20 | 0.95 |

A careful pickpocket (about 1.3 cr a day, coin plus goods at a fence) cannot
feed itself on purses alone against a ~2 cr bread floor; a reckless one (3.5)
can, and pays for the flophouse. Honest pay (task 3) is set against this floor.
The v0.10–v0.12 bounds in `tests/test_hue_and_cry.py` are unmoved: the
harnesses still feed and rest their thief each morning, and no route they walk
comes near the stamina floor.

### Added — HUE & CRY: scrounging and the secret ways (v0.14 task 2)

- **Every secret place can be found.** Since v0.13 the Undercroft, the
  Rooftop Road and the Old Bell Tower stayed off the map and out of the travel
  options until known, and nothing in the story ever made them known, so no
  player could reach them. (A HUE & CRY save from before v0.14 keeps the world
  it was generated with, so it never gains the new rooftop and grating paths;
  the arrest reveal of the Undercroft reaches it, and a new game has all of
  them.) Each now has at least one legitimate way in, all
  through mechanisms the engine already had:
  - **the Undercroft** — scrounging the Snuffs can turn up a yard grating (a
    hidden path), and every way the Lantern's stop ends in the cells sets
    `location_known:the_undercroft`: the drain in the cell floor
    (`data/encounters/watch_stop.yaml`; the cell's rest line now mentions
    it). The road is there to take once the Watch lets you go.
  - **the Rooftop Road** — scrounging Wickmarket (a drainpipe up the back of
    the pie shop) or Chandlers' Rise (a loading crane) finds a hidden path.
  - **the Old Bell Tower** — `known_when` on the tower: standing on, or having
    stood on, the Rooftop Road reveals it; scrounging Gallows Green can find
    the gap in the burnt churchyard's wall.
  Turn one still offers none of them, from any district, on any seed.
- **Scrounging.** `data/tables/forage.yaml`: two hours and six stamina in the
  gutters of the five streets tagged `scrounge` (the docks, Wickmarket, the
  Snuffs, Gallows Green, Chandlers' Rise — never Silk Row, the Hill, the
  Lantern House or a secret place) for a heel of bread, a bruised apple, a
  ship's biscuit, candle ends and rags a counter takes for a crown, and now
  and then a brass button, a pawn ticket, beeswax tapers or a silver thimble.
  New items in `data/items/scrounge.yaml`. The forage ground and the hidden
  paths come from the story's first `paths.procgen_templates`
  (`data/procgen_templates/tallowmere.yaml`, the margin only — no villagers,
  buildings or festival).
- **Engine: pinned hidden paths** (`engine/game/procgen.py`,
  `engine/game/foraging.py`). Row N of a template's `hidden_path_placements`
  (`{from, leads_to, labels}`, each optional) pins hidden path N; a pinned
  path starts at its `from` — when that place can be foraged — instead of
  wherever the round-robin deal puts it. A pin changes which pool a draw is
  taken from, never how many draws there are, and a template without
  placements generates exactly what it did: the flagship's world is pinned
  byte for byte for three seeds (`tests/test_secret_locations.py`).
  docs/AUTHORING.md §3.7 documents hidden paths as the third reveal.
- **`scripts/simulate_scrounge.py`**: `scrounger` (four streets a day, lives
  on it) and `mornings` (two streets, the pickpocket's sideline), on the
  production channel, not fed by the harness.

Measured (simulate_scrounge, 40 seeds x 10 days, agendas off):

| policy | attempts/day | sold cr/day | food/day | value/hr | hungry days (of 10) | min hp |
|---|---|---|---|---|---|---|
| scrounger | 4.0 | 0.97 | 38.1 | 0.37 | 0.38 | 15 |
| mornings | 2.0 | 0.64 | 22.4 | 0.46 | 0.72 | 0 |

Food is hunger taken off by what was found (a day's hunger is 48). Twelve
hours in the gutters every day feeds a thief most of the way and earns under
a crown — less than a careful pickpocket's ~1.3 cr, and nothing like a
flophouse, a tool or a job; a half-day of it still goes hungry (one seed
starved to 0 hp: no `death.yaml` until v1.0). The first cut measured 2.75 cr
and 70 food a day, a better living than stealing, and was cut to this;
`tests/test_hue_and_cry.py` bounds both sides. A scrounger finds the Rooftop
Road on 100% of seeds (mean day 2.5), the Undercroft's grating on 97% (2.5),
the churchyard wall on 68% (3.4).

HUE & CRY's premises do not move: they draw on their own stream after every
PROCGEN draw, and the world minus its new margin is pinned for three seeds as
measured before the templates existed. The Law, jobs and agendas harnesses
report the same tables as before this change (their thieves never scrounge).

### Added — HUE & CRY: honest work, luck and trade (v0.14 task 3)

- **Honest work in Tallowmere.** `games/hue-and-cry/data/tables/labour.yaml`
  gives the story its first labour table: carrying for Dock Mag's gang on
  Tallow Docks (6 h, nerve, 2 cr and the end of the loaf, +1 Honest Company
  standing when it goes well), dipping candles at Marsh & Daughters on
  Chandlers' Rise (6 h, craft, 4 cr), running errands for the Wickmarket
  stalls (3 h, persuasion, 1 cr) and going round the lamps with Wren at dusk
  (3 h, lore, 1 cr). Two shifts a day, each posting once. They are on the
  notice board (`/api/notices`) and in the `work` enum only in the hours the
  employer is scheduled at the counter: Mag from first light until noon, the
  vats from 06:00 until 13:00, the stalls 08:00–17:00, and Wren in the market
  at 18:00. A test holds each posting to its employer's schedule.
- **Engine: a job can keep hours** (`engine/game/economy.py`). A labour job
  may declare `when:` (a condition in the shared grammar, most often
  `hour_between`) and `closed_text:`. Unmet, the job is shut like any other
  gate: off the board and out of the enum, and `work` refuses it in the
  `closed_text` words at no cost. No other story declares one, so their jobs
  are offered exactly as before. `intents._work`'s docstring had claimed
  since v0.8 that the board filters "on the hour"; nothing did until now.
  docs/AUTHORING.md §3.7 documents it; the graph template and the flagship's
  labour header list the keys.
- **Tallowmere's luck.** `boons.yaml` (a natural 20): breath to spare, a
  dropped crown, a Lantern's blind eye (half a day of the Watch's cooling, on
  stealth or persuasion), an eel pie across the counter, the wax taking first
  time, a porter's nod (+2 standing, on nerve). `complications.yaml` (a
  natural 1): tallow on the step (−1 to checks for a day), a crown lighter,
  the long way round (−5 stamina), and a one-eyed jackdaw with opinions about
  buttons. The jackdaw is Pip, and flavour only: Pip is a pipeline agent with
  his own voice, so no die face makes him do anything. No complication
  touches the Law (a botched lift already has the Watch's consequences); the
  one boon that does only cools.
- **`scripts/simulate_labour.py`**, the cost-of-living harness v0.14's
  survival task left as scratch scripts. Four policies on the production
  channel — `porter` (the quay, then the lamps), `dipper` (the vats, then the
  errands), `careful` (simulate_law's pickpocket, goods sold to Marrow) and
  `scrounger` — each buying its own bread and bed, never fed by the harness;
  `--bed flophouse|bunk|rough`, `--agendas`.
- No trade or price change was needed: bread (1 cr) and pie (2 cr) already
  priced the day, and the porter's in-kind pay is Mag's own heel of bread.

Measured (simulate_labour, 40 seeds x 10 days, agendas off, flophouse beds;
"kept" is a day that ended fed and under a roof):

| policy | earned cr/day | food cr/day | bed cr/day | fed | roofed | kept | saved cr/day | min hp |
|---|---|---|---|---|---|---|---|---|
| porter | 2.38 | 1.21 | 0.97 | 99% | 97% | 97% | +0.20 | 12 |
| dipper | 3.09 | 1.98 | 0.89 | 95% | 89% | 89% | +0.22 | 0 |
| careful | 1.36 | 0.99 | 0.65 | 22% | 67% | 8% | −0.28 | 0 |
| scrounger | 1.14 | 0.18 | 0.97 | 98% | 97% | 95% | +0.04 | 14 |

An honest day covers bread and Old Nance's pallet on nearly every day with a
fifth of a crown over; a porter in the free guild bunk saves about 1.1 cr a
day. A reckless pickpocket lifts ~3.5 cr a day and a careful job fetches 7–10
at a fence, so thieving pays more, with its risk; a careful pickpocket on
purses alone keeps one day in twelve. Rejected by measurement: the porter's
wage priced by Honest Company standing (a neutral 0.85 floors 2 cr to 1: 1.66
cr a day, 84% kept, −0.32 a day, 0 hp) and candle-dipping at 3 cr (79% kept,
−0.31 a day). `tests/test_hue_and_cry.py` bounds the porter and the dipper
(8 seeds x 8 days).

**Restated:** the scrounging entry above says twelve hours in the gutters is
"nothing like a flophouse". That was measured sleeping rough. With a bed to
pay for, the same scrounger covers the 1-crown pallet on 97% of nights and
keeps 95% of days, saving nothing. It is a subsistence with a roof, and still
never a tool, a job or a crown put by (`forage.yaml`'s header says so too).

Boons and complications fire on every check in the city, so the v0.10–v0.12
harnesses were re-run with them at 40 seeds. Every bound holds, with drift
of a point or two:

| harness | measure | before | after |
|---|---|---|---|
| simulate_law | careful below `sought` (seed-days) | 100% | 100% |
| | reckless `wanted` by day 4 | 77.5% | 75% |
| | reckless / briber runs with an arrest | 80% / 80% | 82.5% / 82.5% |
| simulate_jobs | careful tier 1–2 carried out / caught | 83.3% / 0% | 80.8% / 0% |
| | blind tier 1–2 caught | 36.7% | 36.7% |
| | prepped Treasury carried out | 20% | 20% |
| simulate_agendas | idle `sought` by day 6 | 80% | 80% |
| | reckless net at its top band | 60% | 62.5% |
| simulate_scrounge | scrounger food/day, sold cr/day | 38.1, 0.97 | 38.4, 0.97 |

### Added — HUE & CRY: the streets at night (v0.14 task 4)

- **Night streets.** Every public street in Tallowmere now carries a
  `danger_dc` (its rougher end's: 6 for any street touching the Docks or the
  Snuffs, 4 for the rest of the low town, 2 on the Rise, Silk Row and the
  Hill); the three secret ways stay at 0, so the Undercroft and the roofs are
  how a thief keeps off the streets. `data/encounters/rules.yaml` gains the
  `trigger:` block (0.05 a point of danger, x0.15 by day, x0.3 at dawn, x0.5
  at dusk, x1.0 at night, less 0.02 a point of stealth), and
  `data/encounters/streets.yaml` ships five scenes: **cutpurses** who think
  you are easy (any street, any hour), a **press-gang** off the Fair Candace
  (arriving on the Docks, 22:00-04:00), a **drunk Lantern** (the watched
  streets, 21:00-02:00; hitting him commits `assault_watch` through the
  `deed` effect -- and, since he is no scheduled Lantern, the effect's new
  `report_precision: 0.6` has him tell the watch-house himself, blurred,
  when no Lantern on duty saw it, so the blow is never unfiled -- and losing
  to him is the cells), **old Wix the
  lamplighter's warning** (17:00-22:00; chestnuts, supper on the kerb, and a
  word about where not to walk) and **Silas Crook's toll-men** (the Snuffs,
  the Docks and Wickmarket, 20:00-03:00; paying the toll costs Honest
  Company standing, beating them earns it). Approaches through the existing
  skills and costs; outcomes through effects. Every scene has a way out that
  needs no roll, coin, item or hour (no soft-lock), no outcome takes more
  than 3 hp (no `death.yaml` until v0.17), and every arrest reveals the
  Undercroft, as the Lantern's stop does.
- **Engine: `on_roads: false`** (`engine/game/encounter.py::matches`). A row
  with no `triggers` matches every leg, and HUE & CRY's `watch_stop` has none
  because the Law's patrol opens it -- so the moment a street had danger it
  would have been drawn as a free Lantern stop out of nowhere. The key keeps a
  row off every road; `begin` still opens it. No other story writes it, and
  a test holds every flagship row matching exactly as before. docs/AUTHORING.md
  §3.7 documents road danger by the hour (the `trigger:` formula already had a
  `time_of_day` table, so no night-only edge key was needed) and the key.
- **`scripts/simulate_streets.py`**: a fresh thief walks one public street an
  hour, day and night, on the production channel, answering every scene with
  `run`; it reports the scene rate by daypart and by district, the scenes
  dealt, robberies, arrests and hp. The Law harness's thief
  (`simulate_law.Thief`, which the jobs, agendas, scrounge and labour
  harnesses share) now answers a street scene met on a walk the way it
  answers the Lantern (`run`, or the first way out needing no roll) instead
  of standing in it forever.

Measured (simulate_streets, 40 seeds x 3 days, 2537 legs):

| daypart | legs | a scene | | night, arriving at | a scene |
|---|---|---|---|---|---|
| dawn | 237 | 4.2% | | the Docks | 28.4% |
| day | 1031 | 0.3% | | the Snuffs | 28.6% |
| dusk | 357 | 9.0% | | Wickmarket | 22.2% |
| night | 912 | 19.7% | | Silk Row | 16.0% |
| | | | | Chandlers' Rise | 8.8% |
| | | | | Margrave's Hill | 7.2% |

A robbery in 23% of scenes, 0.09 cr lost per night leg, 0.44 arrests per 100
night legs, no hp lost to a scene. The first cut (cutpurses at weight 10 with
an easy `run`) robbed in 11% of scenes, 0.06 cr a night leg -- a night you
could ignore. A robbery takes two crowns: at three, the honest porter walking
home from the lamps through the Snuffs kept 92% of days, saved nothing, and
one run starved to 0 hp.

**Restated** (every v0.10-v0.14 harness at 40 seeds, before this task and
after; the harnesses walk at night):

| harness | measure | before | after |
|---|---|---|---|
| simulate_law | careful below `sought` (seed-days) | 100% | 100% |
| | reckless `wanted` by day 4 | 75% | 75% |
| | reckless / briber runs with an arrest | 82.5% / 82.5% | 82.5% / 82.5% |
| simulate_jobs | careful tier 1-2 carried out / caught | 80.8% / 0% | 80.6% / 0% |
| | blind tier 1-2 caught | 36.7% | 36.5% |
| | prepped Treasury carried out | 20% | 20% |
| simulate_agendas | idle `sought` by day 6 | 80% | 80% |
| | reckless net at its top band | 62.5% | 65% |
| simulate_scrounge | scrounger food/day, sold cr/day | 38.4, 0.97 | 37.3, 1.01 |
| simulate_labour | porter kept / saved cr a day / min hp | 97% / +0.20 / 12 | 94% / +0.05 / 12 |
| | dipper kept / saved cr a day | 89% / +0.22 | 87% / +0.10 |
| | scrounger kept | 95% | 93% |

Every asserted bound holds. The honest life moved most, and on purpose: the
porter's walk home at nine crosses the Snuffs, and one night in a few meets
someone. It still keeps 94% of days.

### Added — HUE & CRY: factions and the city's memory (v0.14 task 5)

- **Seven factions.** `data/world/factions.yaml` now declares the rest of
  the city beside the Honest Company: the Lantern Watch, the Worshipful
  Company of Chandlers, the Wickmarket stallholders, the Temple of the
  Everflame, the Margrave's household and the Silk Row houses. Each is wired
  only where something already in the story touches it -- a good shift at
  Marsh & Daughters is +1 with the Chandlers, Wickmarket's errands +1 with
  the stallholders, going round the lamps with Wren +1 with the Watch (the
  lamp ordinance is theirs), and striking a drunk Lantern -10 with the Watch.
  The Temple, the household and Silk Row are declared for Acts I-III and
  moved by nothing yet (recorded in CLAUDE.md, so they are not mistaken for
  finished). No wage or price is set by any standing; the labour harness
  numbers are unchanged.
- **Tallowmere's lore.** `paths.lore` / `paths.lore_db` and eight files in
  `data/lore/` (42 chunks): the city, the Everflame, the Magpie's legend,
  the Lantern Watch, the Honest Company, the Hanging Fair, the guilds and
  trade, and the hidden city. The secret places, the flame's heart and the
  Company's split are `gm_secrets` -- the narrator's, never Pip's -- and no
  sentence in the corpus puts a Magpie candidate beside the Magpie (asserted
  by test). `lore.db` is gitignored like every story's; build it with
  `CLOCKWORK_GAME=hue-and-cry python scripts/seed_lore.py`.

### Measured — HUE & CRY: the living city, all at once (v0.14 task 6)

Every harness re-run at 40 seeds on the finished v0.14 city (sleep, scrounging,
honest work and luck, night streets, factions, lore), on the production
channel. Every figure below reproduced the tables the earlier v0.14 tasks
recorded; no bound moved and none was restated.

**What a life in Tallowmere costs** (10 days, a flophouse bed; "kept" = fed
and under a roof that night; `scripts/simulate_labour.py`,
`scripts/simulate_scrounge.py`):

| way of getting by | earned / day | kept | saved / day | lowest hp |
|---|---|---|---|---|
| a porter for Dock Mag (two shifts) | 2.34 cr | 94% | +0.05 cr | 12 |
| a dipper at Marsh & Daughters | 3.10 cr | 87% | +0.10 cr | 0 on some seeds |
| a scrounger (full days) | 1.10 cr | 93% | -0.05 cr | 12 |
| a careful pickpocket (purses only) | 1.36 cr | 7% | -0.28 cr | 0 on some seeds |

An honest life is possible and thin; purses alone are not a living -- the
careful pickpocket needs jobs (`simulate_jobs`: tier 1-2 hauls 5.9 and 24.4 cr,
never caught) or honest work beside them. The reckless pickpocket earns about
3.5 cr a day and is wanted by day 4 on 75% of seeds (`simulate_law`). Where hp
reaches 0 there is still no respawn: `death.yaml` lands with v0.17.

**What the night costs** (`scripts/simulate_streets.py`, 2537 legs): a scene
on 19.7% of night legs (28% arriving at the Docks or the Snuffs, 7% on the
Hill), 9.0% at dusk, 4.2% at dawn, 0.3% by day; a robbery in 23% of scenes,
0.09 cr lost per night leg, 0.44 arrests per 100 night legs, no hp lost.

**The Law, jobs and agendas under the living city** (40 seeds): careful
thief below `sought` on 100% of seed-days; reckless `wanted` by day 4 on 75%,
arrested in 82% of runs; careful burglar caught on 0% of jobs; an idle player
`sought` by day 6 on 80% for the Magpie's work; Magpie robberies 9.8 a run;
the Magpie's roles over 90 seeds Wren 31, Silas 35, Imelda 24.

## [0.13.0] — 2026-09-25

**Engine seams for HUE & CRY's finish**, the first of the v1.0 stages: v1.0.0
no longer ships as one release at the end of the roadmap. From here it ships
as point releases — this release's engine seams, then living city, guild
economy, Acts I–II, Act III and its eight endings, the thief policy for
`simulate.py`, the bespoke UI plugin, and finally the art pack and live play —
tagged `v1.0.0` only once the last of those lands (owner, 2026-09-25; see the
spec's Goal section). This release closes the small seams the shipped systems
were still missing before content can be built on them: a secret place now
stays secret until something in play actually finds it; a custody predicate
and a jailbreak set-piece can free a held player; a declared world event can
force a scene and a deck can be dealt more than once; a death can end the run
in an ending with its epilogue shown, instead of a blank last screen; the
watch a death's hours bring no longer closes the arrest scene it just opened;
the wanted poster gets a word for how clearly the watch knows a face; and the
art generator now works for any story, not only the flagship.

### Fixed

- **A save already on THE LONG CON's cold-room stage can finish the case**
  (engine + content; `engine/game/locations.py::is_known`, `known_when:`,
  docs/AUTHORING.md §3.7). The drying room was revealed by a flag the
  `the_cold_room` stage set in its `on_enter` -- which a v0.12 save already
  on that stage had run under v0.12, with no reveal in it. Such a save could
  never be offered the room, and the stage's `complete_when` stands in it:
  the case could not finish. A secret place may now declare `known_when:`, a
  condition in the shared grammar that `is_known` asks afresh every time
  (derived, never stored), and the drying room declares the case at or past
  that stage; the one-shot flag is gone. `known_when` is checked at load --
  the loader logs and ignores a bad one, the validator reports it naming the
  graph file: known predicates, no combinator beside a sibling, not empty,
  only on a `secret: true` place, and none that needs a ledger or a quest
  (`disposition`, `days_in_stage`, `days_since_started`).
- **A terminal death's gate-skipping lock is its own, not the whole death's**
  (engine; `encounter.terminal_lock_in_progress`, `effects._e_ending`). The
  `ending_lock` effect honoured `terminal: true` for as long as any death was
  being handled -- including a respawn's hours, where an event, a card or a
  job tick could have written one and locked an ending nobody earned. It is
  now honoured only around the one lock `_terminal_ending_death` applies. A
  terminal death also closes the dying encounter now (a dead player is in no
  scene); custody stays, and a fall that killed mid-job closes the job
  `hurt`, as the docstring and AUTHORING §3.5 now say instead of "everything
  stays as it fell".
- **A finished run stops dying** (engine; `encounter._check_death_inner`). A
  terminal death leaves hp at the threshold, and every later hour re-ran it:
  another "You do not get up." and another refused lock, per hour. A run
  with `state.ended` set runs no death rules.
- **`clarity_words` refuses a digit or a repeated word** (engine;
  `law._load_clarity_words`). "Never a number" was only true of YAML
  numbers: `"2 witnesses"` loaded. Two thresholds sharing a word (case and
  edge spaces ignored) are a rise the player cannot hear. Both are load
  errors naming `law.yaml`.
- **Set-piece `requires:` refuses what it can never answer** (engine;
  `set_pieces._requires_problem`, `quests.condition_problem`).
  `is_available` evaluates with no ledger and no quest record, so
  `disposition`, `days_in_stage` and `days_since_started` there were unmet
  forever -- a piece that loads and is never offered. They are refused at
  load, as agendas already refused them. Set pieces, jobs' flashbacks,
  agendas, death.yaml's terminal and a location's `known_when` now share one
  public walker and check (`quests.condition_clauses`,
  `quests.condition_problem`) instead of four private copies reading the
  grammar's private keyword lists.
- **`generate_art.py`'s manifest editor refuses what it would get wrong**
  (tooling; `scripts/generate_art.py::merge_manifest_text`, `promote_plates`).
  A quoted key the entry finder missed (`"npc_brask":`) got a second, bare
  entry appended, and the re-parse -- where the last duplicate wins -- passed
  it; the re-parse now refuses duplicate keys. A manifest YAML cannot read
  raised a traceback past the CLI; it is a reported error now. A plate whose
  path would resolve outside `paths.art_root` is refused before any file is
  written. The flagship's `--promote --dry-run` said "promoted N"; it says it
  would, and promoted nothing.
- **The validator reads a reveal in `narrative_flags`** (engine;
  `validation.location_refs`). AUTHORING said a `location_known:<id>` listed
  in a stage's `narrative_flags` was checked as a location reference; only
  flag effects were. Both are now.
- **Generated art is cached per story** (engine;
  `engine/media/providers/base.py::ImageRequest.story`, `cache_key`). The
  disk-cache key was story-blind, so The Wicked Garden and Dev Story -- both
  with a `sophia` portrait -- shared one cached image, served to both at
  runtime and, through `generate_art.py --promote`, copyable into the wrong
  pack. A request now records the story running when it is made, and every
  story's key includes its slug except the flagship's, which keeps the
  original formula exactly so no image already cached for it is orphaned
  (asserted against known keys).
- **`art_missing.py` and the generator agree on what is missing** (tooling;
  `scripts/art_missing.py`). The brief counted a subject present the moment its
  id appeared in the manifest, whether or not the file existed, named the dawn
  plate `scenes/<id>.jpg` where the generator writes `scenes/<id>-dawn.jpg`,
  and printed a sizes table of 1280x720 for every story under a sentence saying
  it was read from `formats:` (NEON CITY's is 1344x768). It now briefs from
  `generate_art.plan_plates`, so both tools list the same plates at the same
  paths, and its paste block uses `times:`. The three committed briefs were
  regenerated; each lists the same subjects as before. `--out` writes the brief
  elsewhere.
- **The watch a death's hours bring stays at the door** (engine;
  `encounter._check_death_inner`, `encounter.resolve_approach`). A respawn's
  hours run `jobs.tick`, which can close an open job `caught` and open the
  arrest scene; the dying scene was ended AFTER those hours, so the same
  death closed the arrest scene it had just let open. The dying scene now
  ends before the hours, and `resolve_approach` clears only the scene its
  round played. Recorded as deferred in CLAUDE.md since v0.11.0.
- **A hidden path found by foraging is offered as travel** (engine;
  `foraging.shortcut_targets`). `intents._travel` read `to_id` from rows that
  carry `leads_to`, so a found path never offered the leg it opened to a
  place with no road -- `move_to` would walk it, nothing named it. The enum
  now offers it, labelled with what `move_to` charges (the shorter of road and
  path), and the map draws the same legs from the same function, so map and
  travel agree after foraging too. The flagship's options change only once a
  path is found; a fresh run's travel and map payload are unchanged.

### Added

- **Secret places stay secret until found** (engine;
  `engine/game/locations.py::is_known`, `KNOWN_FLAG_PREFIX`, docs/AUTHORING.md
  §3.7). `secret: true` was a promise only the map kept: `codex_places`
  withheld the place and its roads, while `intents._travel` built its enum
  from the raw graph -- so on turn one of HUE & CRY the model was offered
  "The Undercroft, 1h" by name, and THE LONG CON offered the drying room from
  the first visit to Harbour Road, three stages before the case sends anyone
  there. One predicate now decides whether a place is known -- not secret,
  stood in, visited, revealed, or the end of a discovered hidden path -- and
  the travel enum, the map payload and the resume choices all ask it. A story
  with no secret place is byte-identical (the flagship's travel options and
  map payload hash the same across all 20 locations before and after).
  `location_known:<id>` reveals a secret place, written by the ordinary
  `flag` effect from any hook, card or set piece, or raised by the narrator
  through a stage's `narrative_flags` -- a flag rather than a new effect
  kind, so it round-trips saves with the same prefix shape as foraging's
  `hidden_path_found:`; the validator reads its suffix as a location
  reference (a typo is a load error) and does not report a reveal as
  write-only (`ENGINE_READ_FLAG_PREFIXES`). A secret place may instead
  declare `known_when:` (see Fixed): THE LONG CON reveals the drying room
  that way, once the case reaches the `the_cold_room` stage. HUE & CRY's
  three secrets have no reveal yet (see CLAUDE.md, Deliberately deferred).
- **`move_to` refuses a secret place nobody has found** (engine;
  `GameEngine.move_to`). Any caller naming an unknown secret place gets an
  engine refusal ("You know of no way there." -- it does not name the place),
  which reaches the narrator as every refused move does, instead of a silent
  walk the travel enum would never have offered.
- **An art generator for any story: `generate_art.py --game <slug>`**
  (tooling; `scripts/generate_art.py::plan_plates`, `promote_plates`,
  `merge_manifest_text`, docs/AUTHORING.md §3.9). The script was
  flagship-shaped: no `--game`, five hardcoded Edgewood NPC ids, every
  location doubled across two evil phases, and `--promote` writing only item
  plates into the flagship's `things/`. Now any other story is planned from
  its own `paths.art_subjects` -- each location at every daypart its
  `times:` declares (one `base` plate if it declares none), every portrait,
  every item, nothing else -- and HUE & CRY plans 91 plates (19 locations x 4
  dayparts, 15 portraits). `--dry-run` lists kind, subject, daypart and target
  path and writes nothing; `--only locations:tallow_docks` / `--only
  portraits` and `--dayparts day,night` narrow it (an undeclared subject is an
  error, not an empty plan); `--missing` (default on) skips what
  `shipped.lookup` already resolves. `--promote` copies each generated plate
  from the cache under the story's `paths.art_root` as JPEG fitted to its
  `formats:` size, and writes it into `paths.art_manifest` as
  `locations.<id>.times.<daypart>`, `portraits.<id>` or `items.<id>` --
  editing only the lines of the entries it changes, so comments outside
  those entries survive, and re-parsing the result before writing anything. The
  flagship (the default, and `--game clockwork-dark`) keeps its plan: `--all
  --list` and `--all --prompts` print byte-identical output before and after,
  and nothing on its path activates a story.
- **Tests cannot launch the real Grok CLI** (tests;
  `tests/conftest.py::_no_real_grok_cli`). The model-server guard watches
  sockets; the Grok image provider shells out to a CLI that does its own
  networking, so an unstubbed test would have started a real generation (or,
  with no `grok` installed, passed quietly on a failed result). The
  provider's `subprocess` is now a refusing shim in every test not marked
  `live`, recorded and re-asserted at teardown like the socket guard; its
  canary is `test_the_conftest_guard_catches_a_real_cli_call`.
- **How clearly the watch knows your face, in words** (engine + authoring;
  `engine/world/law.py::clarity_word`, `best_precision`, docs/AUTHORING.md
  §3.11). The `law` payload gains `clarity` beside `wanted`: one word for the
  face worn, in the jurisdiction the player stands in, from the best
  precision among the live reports the watch there holds on it or on a face
  it links to it (a discharged or quashed deed draws nothing). It is what
  v1.0's wanted poster will sharpen its sketch by -- a word, never the
  number. `law.yaml` may author `clarity_words` (ascending, at least two
  strings); the default is "nothing", "a rumour", "a description", "a
  likeness" (no digit, no word twice), with the first meaning no live report and the rest splitting
  precision (0, 1] evenly, so the shipped hops 0.3 / 0.6 / 1.0 land one on
  each. The narrator's wanted line speaks the same word ("...: sought; it
  has a description of you."), so prose and poster cannot disagree.
  `recognition` now reads its precision through the same `best_precision`
  rather than its own loop. A story with no Law is unchanged: no `law` key,
  no line.
- **A death can end the story in an ending** (engine + authoring;
  `engine/game/encounter.py::_terminal_ending_death`, `endings.lock(...,
  terminal=True)`, docs/AUTHORING.md §3.5). `death.yaml` may declare
  `terminal: {when: <condition>, ending: <id>}`: a death that satisfies
  `when` (read before any respawn) ends the run, locks that ending and plays
  its module, so its epilogue shows -- the flagship's `phases`/`flag`
  terminal set `state.ended` and nothing else, a blank last screen. The lock
  skips the ending's own `requires`/`completable` (the death is its
  eligibility) through the `ending_lock` effect's `terminal: true`, which is
  refused anywhere but the death's own lock (see Fixed). A misspelt ending, an unknown
  predicate or a malformed `when` is a load error naming `death.yaml`, and
  the content validator reports the same (`check_death_rules`). The
  flagship's terminal and respawn and neon-city's respawn are byte-identical
  (sha256 of the death record and the full save, measured before and after).
- **A declared world event can force a scene** (engine + authoring;
  `engine/world/schedules.py::_declared_event`,
  `engine/game/clocks.py::event_forced_scene`, docs/AUTHORING.md §3.3 and
  §3.7). `forces_scene: <deck or card id>` on an entry of the
  `world_schedules` `events:` block rides the event's payload and is read by
  the same `clocks.forced_scenes` a clock beat's promise is answered through
  -- one path, not two. The promise stands only while the event is active.
  The validator (`check_declared_event_scenes`) requires the id to name a
  deck or card, and reports one declared in a story with no decks against
  the schedules file.
- **Decks can deal again: `repeatable: true`** (engine + authoring;
  `engine/content/director.py::rearm`, `Deck.repeatable`, docs/AUTHORING.md
  §3.3). A repeatable deck is still spent by its deal, and re-arms only once
  its trigger -- its `when:`, or an active world event forcing it -- has been
  seen false since: one deal per rising edge. A deck gated
  `{in_custody: true}` deals on each arrest and never twice in one stay. The
  fall is recorded by clearing the played flags through `apply_effect`, so it
  rides the save; it is read at the turn, so how the clock was cut between
  turns cannot change it. A clock-forced deck never re-arms (its promise is
  permanent). The validator reports a non-bool `repeatable`. No shipped deck
  or event opts in, and the-long-con, wicked-garden and dev-story deal
  byte-identically: a fixed 40-turn director walk of each, recorded before
  this change, replays to the same hands and played flags
  (`tests/test_forced_and_repeatable_decks.py`).
- **`in_custody` is a condition predicate** (engine + authoring;
  `engine/world/law.py::_p_in_custody`, docs/AUTHORING.md §3.11).
  `{in_custody: true}` holds exactly while the watch holds the player; the
  `arrest` effect writes the custody record and sets no flag, so nothing
  authored could ask it before. False in a story with no Law, whatever
  `state.law` carries. `engine.world.law` joins `quests._GRAMMAR_MODULES`, and
  the agendas validator counts it as a Law predicate.
- **Set-pieces take a `requires:` condition** (authoring;
  `engine/challenges/set_pieces.py`). Any shared-grammar condition, ANDed with
  the existing location and flag gates and evaluated only for a piece that
  declares one; its predicate names are checked at load (an unknown one, a
  sibling beside a group combinator, or one needing a ledger or a quest logs
  and skips the piece).
- **An authored set-piece may pay `release`** (engine;
  `engine/challenges/spec.py`, `AUTHORED_CHALLENGE_EFFECT_TYPES`). A
  break-out gated `requires: {in_custody: true}` is offered in the cell and
  its success frees the player -- custody cleared, nothing discharged, nothing
  else charged. `set_pieces.start` now validates with `authored=True`, which
  also admits the structural kinds (`ending_*`, `quash_reports`) as threads
  and deck gates already had; every magnitude clamp is unchanged. `release`
  is NOT structural: a model-composed challenge, a thread and a deck gate
  still drop it. The flagship's set-pieces bound identically on both paths
  (asserted), and no shipped set-piece declares `requires:`, so every story's
  turns are unchanged.

## [0.12.0] — 2026-09-25

**Agendas.** Tallowmere moves whether or not you do. A thief chosen by the
seed — one of three people, never revealed, never stored — robs the city's
shining houses by night, and the watch takes the Magpie for you: a player
who never steals a spoon is `noticed` in two days and `sought` in about
five. Captain Ardane hears the reports, reads the files, tightens her net
and, pushed far enough, swears out a warrant. Silas Crook works the guild
from inside, cleaning out the Honest Company's own ward and pouncing if you
rob Mother Gannet yourself. None of it is a model plan: every move and
reaction is authored data, evaluated deterministically on in-game hours,
replaying identically from the same seed and the same choices. The narrator
learns of it only the way the player could — a private sign where it was
left, a rumour once it is common talk — and never the number behind it.

### Added

- **Agendas: the data, the state and seed-chosen roles** (engine;
  `paths.agendas`, `engine/world/agendas.py`, effect kind `agenda_mark`,
  `GameState.agendas`). A story that declares `paths.agendas` names one file:
  `roles` -- hidden identities the seed chooses from a list of scheduled NPCs
  (`stable_rng(seed, "agenda:<role>")`, derived on every read and never
  stored, so a save neither changes nor reveals who the Magpie is), each with
  an optional `mask` (what agenda text calls the chosen NPC until
  `unmask_when` holds) -- and `agendas`, each an owner (an NPC or a role), a GM-facing goal,
  a clock the story declares `visibility: hidden` with a row in
  `paths.clocks`, moves on a cadence (`every_hours`, `start_hour`,
  `at_hours`, a `when` gate, a `premise`/`fence`/`witness` selector, effects,
  a clock `advance`, an optional `robs` and a `trace`) and edge-triggered
  reactions. Every content fault is a ValueError naming the file: an unknown
  owner or role member, an undeclared, untabled or non-hidden clock, an
  unknown predicate anywhere in a gate, a `disposition` gate (the agendas pass
  has no ledger), an unknown selector key, a `premise` selector without
  premises, a `witness` selector or Law predicate without a Law, a cadence
  below one hour, a bad `trace.where`. `agenda_mark` is the only writer of the
  pass's bookkeeping. A story without `paths.agendas` carries only an empty
  `agendas` in its save.
- **Agendas: moves on the clock** (engine; `agendas.Walk`/`begin`/`advance`,
  `candidates`/`select`, effect kinds `agenda_hit` and `agenda_trace`, rng
  stream `AGENDA`, moved-journal kind `agenda`). `advance_time` now opens the
  agendas pass. For each whole hour crossed, each due move fires when all of
  these hold:
  - its cadence has elapsed, or it has never fired and `start_hour` has passed;
  - `at_hours`, if given, includes the hour of day;
  - `when` holds;
  - its selector finds a target.

  Selectors pick from sorted candidates. One candidate draws nothing; several
  draw once on `AGENDA`. The `premise` selector filters on district, type,
  tier, loot tag and owner; with `not_robbed` it skips houses robbed by the
  player *or* by an agenda, and the house of the player's OPEN job (the
  Magpie could otherwise empty a strongroom under the thief's hands, mid-job).
  `fence` finds a vendor with `fence: true`.
  `witness` finds an NPC holding a live sighting of a face linked to `knows`.

  When a move fires:
  - its effects apply, with `{target}`, `{target_name}`, `{target_district}`,
    `{target_jurisdiction}` and `{owner}` filled in;
  - its hidden clock moves through `value`. A beat it crosses fires at the
    end of that hour, so a `reset_to` or a beat's flags are in place before
    the next hour's moves;
  - `robs: true` records the robbery through `agenda_hit`. It goes in the
    agenda's own `hits`, never in the player's `jobs.robbed`;
  - its trace is written through `agenda_trace` (ids `t<n>` from
    `state.agendas["trace_seq"]`). A `public: true` trace is also journalled
    as common talk.

  The pass is walked INSIDE the Law's pass, hour by hour (`law.propagate`
  gains an optional `each_hour` hook). A report a move files therefore cools
  and travels exactly as if it had come from a shorter call: twelve one-hour
  calls and one twelve-hour call leave `state.agendas` and the clocks
  identical, and `state.law` identical within a day (a Law row's `day` is the
  day the call ends, so a call that crosses midnight stamps a later `day`
  than hourly calls would; no agenda predicate reads it). The walk takes at
  most 48 hours per call, the Law's cap.
  The first call on a new state or an old save walks only the hours that call
  crosses, never the past.
- **Agendas: reactions** (engine; `agendas._try_reaction`, in `Walk`). At
  every hour the pass walks, after that hour's moves, each agenda (sorted)
  evaluates its reactions (declared order). A reaction fires when its `on`
  turns from false to true; the first evaluation of a condition already true
  counts, and `once: true` fires at most once ever, otherwise it fires again
  after falling and rising. Firing applies its effects (`{owner}` filled in)
  and its clock `advance`; a beat that crosses fires at the end of the hour
  with the moves' beats. `truth` is written through `agenda_mark` only when
  it changes, so a reaction that never held leaves nothing in the save.
  Because reactions follow the moves, one answers a move of the same hour --
  a lift's report raising `wanted`, the robbery as an `agenda_hit` -- and
  `reported_to npc_ardane` fires in the very hour the Law's talk carries the
  word to him. Twelve one-hour calls and one twelve-hour call still agree,
  with reactions that set a flag a later move reads and that wind a clock
  across a `reset_to` beat. No predicate an agenda may use reads a Law row's
  `day` stamp.
- **A house an agenda robbed is bare when you get there** (engine;
  `jobs.emptied`, `resolve_stage`, `job_stage`'s `emptied`). Before, a player
  job on a house the Magpie had already robbed drew its full take, and the
  prose contradicted the town talk. Now `burgle` still opens it (the thief
  need not know), but the score finds nothing: its receipt carries
  `emptied: true`, no loot is drawn and no `JOB` draw is spent on loot. The
  narrator is told in words -- the stage summary ("found it already bare:
  someone had been there first"), the JOB block while the job is open, and
  the close line. The job still counts as done: a clean or noisy getaway
  records the house in `jobs.robbed`, so Mother Gannet's Silk Row contract
  pays on a house the Magpie emptied.
- **A bribe that lost the only file silences the witness.** `reported_to` and
  the `witness` selector treated a deed as dead only if it was quashed in the
  jurisdiction where it was DONE. The Law files a report where the watchman
  HEARD it, so a lift up in town told to the captain in the village is filed
  in the village, and quashing the village's file left the captain acting on
  it. A sighting is now dead when its deed is discharged, or quashed
  somewhere with no report of it standing anywhere; filed in two houses and
  lost in one, it is still live.
- **The agendas loader rejects more inert shapes:**
  - `days_in_stage` and `days_since_started` gates (the pass evaluates no
    quest);
  - an `agenda_hit` naming an undeclared agenda, or a premise id no seed can
    lay out (`premises.possible_ids`);
  - a Law-writing effect (`report`, `witness`, `quash_reports`, ...) in a
    story with no Law;
  - any `agenda_*` bookkeeping effect written into a move;
  - a placeholder nothing can fill: a target placeholder without a `select`,
    an unknown name, or an id-valued placeholder in a trace's prose (a
    trace may use only `{target_name}`);
  - a trace (private or public) containing any role candidate's display name
    or any declared alias, of any candidate -- matched as the mask matches.
    The mask guards only the seed's chosen NPC; this makes "no sign names a
    candidate" a schema invariant, including a sign in an agenda a candidate
    owns outright;
  - a reaction YAML read with a bare `on:` key (the boolean true): the error
    says to quote it, `"on":`, instead of "a reaction needs an `on` trigger".
- **Condition predicates `wanted`, `reported_to`, `agenda_hit`**, and an
  `owner` filter on `premise_robbed`. `wanted {guise?, jurisdiction?, min}` is
  the Law's wanted band here at or above `min`; `reported_to {npc, guise?}` is
  a live (not discharged, not quashed) witness row held by that person for a
  face the watch links to `guise`; `agenda_hit {agenda?, premise?, district?}`
  reads the premises an agenda has robbed.
- **Premise owners.** An anchor premise may declare `owner: <scheduled npc>`
  (validated at load); `premises.owner(state, id)` answers the anchor's owner,
  else the first household member.
- **Agendas: the narrator sees only what the player could know** (engine;
  `prompts.agenda_block`, effect kind `agenda_trace_seen`,
  `agendas.signs_here`/`mask_text`/`masked_terms`/`revealed`).
  - **Signs where they were left.** A private trace waits at its location.
    Standing there, the narrator gets "SIGNS HERE (the world moved without
    you; work in what fits, never explain it):" with the unseen ones (at most
    five). They get the same two steps as the moved journal: prompt
    assembly records what it rendered, so an evaluator retry sees the same
    signs, and the turn records them seen through `agenda_trace_seen` once
    the narrator has written. A public trace is never a sign; it went to the
    moved journal, unlocated, as common talk.
  - **Progress** reaches the narrator only as the agenda clock's `label` and
    band in the GM-only `_clocks_block`. It never gets the goal, an id or a
    number.
  - **The secret is the link, not the name.** Until a role's `unmask_when`
    holds, no agenda-authored text (a sign, or a public trace in the moved
    journal) names the role's chosen NPC. Their display name, and any
    `mask.aliases` declared for THAT candidate, reads as `mask.instead`.
    Matching is word-bounded, and it is read from state every prompt. The
    name is case-sensitive, so "a wren on the sill" stays a bird. A leading
    "the"/"The" is not case-sensitive and is swallowed, so "The Wren" reads
    "The Magpie". An alias written with its article ("the lamplighter")
    requires that article. At a sentence start the replacement is
    capitalised. The other candidates are never touched. The cast block, the
    storyteller prompt, the client roster and the narration are not touched
    either, because masking one person's name everywhere would point at
    them.
  - **Once earned**, the GM-only line gains "WHO THE MAGPIE IS (the player has
    earned this; name them freely): Wren, the lamplighter.", and agenda text
    names them normally.
  - **The loader** now requires `unmask_when` on a `mask` (a mask that can
    never lift is a load error naming the file). It also accepts an optional
    `aliases: {<candidate>: [names]}`, keyed by candidate so that one
    person's nickname is never masked when the seed chose another.
  - **Unchanged without agendas.** A story with no `paths.agendas` builds the
    same prompt.
  - **NOT WIRED rows** in docs/GOVERNANCE.md:
    - agenda moves on the notice board;
    - `fence {most: hot_goods}`;
    - `disposition` and quest-progress predicates in agenda conditions;
    - the static spoiler table's narration half:
      `AwarenessGateInterceptor.run_post` has no production caller.
- **HUE & CRY: the city moves without you** (content; `games/hue-and-cry/`
  `data/rules/agendas.yaml`, `data/rules/clocks.yaml`, new `state.yaml`,
  anchor `owner`s, `prompts/storyteller.md`). Three agendas, each on a hidden
  clock:
  - **The Magpie** is one of Wren, Silas Crook and Lady Imelda Vessaline,
    chosen by the seed. Most nights between 01:00 and 03:00 it robs a
    tier-2 to tier-4 house with shining loot (never the Treasury: the
    Everflame is v1.0's). Each robbery files a half-seen burglary against the
    Magpie's face where the house stands, and the watch takes the Magpie for
    you (`law.yaml` `links`). So a player who never steals a spoon is
    `noticed` in two days and `sought` in about five. The robbery is town
    talk by breakfast: a public trace, "the Magpie had <house> in the night,
    and left a single black feather on the sill".
  - **Captain Ardane** winds `ardane_net` when:
    - a live sighting reaches her;
    - the Magpie's file first reaches `sought`, and later `hunted`, in the
      Wick wards or up the Rise;
    - the Magpie touches Margrave's Hill (fired in 36 of 40 idle runs within
    ten days, median day 4.5);
    - she reads the files every other morning, while the file stands at
      `wanted` anywhere;
    - she takes a statement every fourth day from someone who has seen the
      Magpie's face. The statement is her own half-seen report, and it leaves
      a watchman's chalk mark on a wall where the deed was seen.

    At 6 the Watch doubles its shifts. At 12 she swears out a warrant: a
    clear, sworn burglary on the Magpie's file in the Wick and the Rise.
  - **Silas Crook** has his people clean out a tier-1/2 house in the Snuffs
    every other night. Each one costs your standing with the Honest Company
    (-2), and the Snuffs ask where the Magpie was. Once his rise reaches 3,
    he goes for the strike fund in Mother Gannet's House. He pounces once,
    for -5 and two points of his clock, if you rob a house Gannet owns.
  - **No trace or effect names any of the three candidates, in any seed.**
    The mask (`instead: "the Magpie"`, with per-candidate aliases) guards
    the one place a name could slip in: a house's own name. The Wren alias
    is lower-case "the lamplighter" on purpose, because four taverns are
    "The ... Lamplighter". The unmask flag is `magpie_unmasked`, and
    **nothing sets it this release**: the reveal is v1.0's.
  - No forced scenes; there are no decks yet. The beats set flags and write
    to the moved journal.
  - Anchor owners: `gannets_house` npc_gannet, `vessaline_manor` npc_imelda,
    `captains_office` npc_ardane, `margraves_treasury` npc_steward_quill.
  - `storyteller.md` gains "THE CITY MOVES WITHOUT YOU". It covers warmth,
    real stakes and never explaining the machinery, and it points at no
    candidate.
- **`scripts/simulate_agendas.py`** (rule 10). A 40-seed x 10-day harness on
  the production channel: `simulate_jobs.Burglar`, which is
  `simulate_law.Thief`. Three policies:
  - `idle` never steals and measures the hook;
  - `careful` is the Law's careful thief, plus a cased burglary on days 3, 5,
    7 and 9;
  - `reckless` is the Law's reckless thief, plus a blind burglary at 23:00
    on even days.

  `--set <agenda>.<move>.<key>=N` patches a number for one process. Measured,
  final numbers:

  | | idle | careful | reckless |
  |---|---|---|---|
  | Magpie robberies / run | 9.8 (8..11) | 9.7 | 9.9 |
  | first noticed / sought (median day) | 2 / 5 | 2 / 5 | 1 / 2 |
  | `sought` by day 6 | 80% | 95% | 100% |
  | seed-days below `sought` | 42% | 40% | 16% |
  | player jobs; collision with the Magpie (any agenda) | -- | 127; 9% (16%) | 140; 7% (11%) |
  | Ardane top band (utmost, >= 10 of 12) reached by day 10 | 0% | 0% | 60% (median day 9) |
  | Ardane strong (>= 8) | 0% | 0% | 92% (median day 6) |
  | Ardane full (warrant) | 0% | 0% | 22% |
  | Silas moves / run; Company standing | 3.3; -6.9 | 3.1; -6.6 | 3.0; -6.3 |
  | traces / run (max), all unseen | 13.0 (15) | 12.8 (15) | 15.6 (17) |
  | runs with an arrest | 2% | 0% | 88% |

  Over 90 seeds the Magpie is Wren 31 times, Silas 35 and Imelda 24.
  Captain Ardane's `the_hill_is_touched` fires in 36 of 40 idle runs within
  ten days (median day 4.5).

  **Re-measured after the final fixes** (no mid-job theft; an emptied house
  draws nothing, so a seed's later `JOB` rolls shift). `idle` is unchanged.
  What moved, before -> after: careful robberies 9.8 -> 9.7, jobs 126 -> 127,
  collisions 10% (18%) -> 9% (16%), runs with an arrest 2% -> 0%; reckless
  Ardane top band median day 8 -> 9, warrant 25% -> 22%, Silas 3.1 -> 3.0
  moves and -6.6 -> -6.3 standing. Every bound in `tests/test_hue_and_cry.py`
  still holds; no constant changed.

  **First tuning.** Every Ardane reaction was level-edged, `reads_the_files`
  ran daily, `takes_a_statement` every two days, hunted gave +2 and the clock
  max was 10. A reckless thief filled the net by day 4 (top band day 4), and
  the clock counted the churn of bands dipping and recovering rather than
  the case. Now each reaction fires once, `hunted` gives +1, files are read
  every 48h, statements are taken every 96h and the max is 12. Traces are
  never pruned, and ten days leave at most 17.
- **The Law and jobs harnesses measure with agendas OFF** (`simulate_law.py`
  v0.3.0 `agendas_off()` / `--agendas`; `simulate_jobs.py` v0.2.0
  `--agendas`). With the Magpie on, a careful pickpocket is below `sought` on
  42% of seed-days, not 100%: the Magpie's robberies land on its name as they
  land on anyone's. That v0.10 bound measured the thief's OWN conduct, so it
  is still asserted with agendas off. It is RESTATED with them on
  (`test_with_the_magpie_on_a_careful_thief_is_sought_like_anyone`): careful
  is within ten points of a player who never steals (40% vs 42% over the
  harness's 40 seeds; the test's 12 seeds measure 39% vs 40%), and
  reckless stands out (16%). The other Law bounds hold either way (on:
  reckless wanted by day 4 70%, arrested 78%, briber 75%). Job outcomes
  barely move with agendas on, but they are not identical: `greedy` makes
  79 jobs rather than 80 (true before the final fixes too), and since a score
  on a house the Magpie emptied draws nothing (and spends no `JOB` draw),
  blind's haul falls 13.2 -> 12.4 and careful's 14.7 -> 13.2, with a point or
  two of drift in their outcome shares (40 seeds, `simulate_jobs.py
  --agendas`). `deeds_filed` would also count the Magpie's burglaries as the
  job's. The switch patches
  `agendas.declared`, because an empty `paths.*` overlay key is answered from
  the manifest (`engine/config.py`). A test guards that it really switches
  the pass off.

## [0.11.0] — 2026-09-24

**Jobs & flashbacks**, the third of the four v0.9 engine features, proven
against HUE & CRY: Tallowmere's houses can now be burgled. `burgle` opens a
job on any unrobbed premise and walks it stage by stage — approach, entry,
past whoever's inside, the strongroom, the getaway — its odds moved by what
was really cased and what is really carried, its failures raising a per-job
alarm that can wake the house and send for the Lantern Watch. A Blades-style
`flashback` mid-job may only claim a preparation the player's own history
makes plausible — a bribed servant, a planted tool, a rota learned in
advance — spending a veiled `prep` meter earned only by casing. Mother
Gannet's guild strikes its first contract on the back of it. The narrator
and the player's own screen see the same house, stage, obstacle and alarm
the engine does, in words, never a number.

### Added

- **Jobs: the data and opening a job** (engine; `paths.jobs`,
  `engine/world/jobs.py`, effect kinds `job_open` and `job_close`, verb
  `burgle` → skill `begin_job`). A story that declares `paths.jobs` names one
  file: five derived stages with their hours, the band each premise tier
  starts from, the entry approaches, what each security feature and carried
  tool does to a stage, the alarm and prep meters, flashbacks, and an anchored
  premise's own extra stages (spliced in after its `after` stage). The loader
  fails naming the file for an unknown band or skill, a feature no premise
  declares, a tool the registry lacks, an `anchors` key that is not an
  anchored premise, a flashback `requires` naming an unknown predicate, band
  lists that do not fit their meter, a tier some premise can have with no
  band, a jobs file in a story without premises, and — where a Law is
  declared — an `alarm.deed` the Law does not know. `burgle` offers the
  unrobbed premises of the player's district and opens a job held in the
  new saved `jobs` field; while a job is open it owns the turn
  (`intents.scene_owns_turn`), so ordinary verbs are withdrawn and the Law's
  patrol does not stop a player mid-burglary. Every refusal (no jobs, held,
  a job already open, a scene running, unknown house, wrong district,
  already robbed) spends no time. A closed job whose score was carried out
  (`clean`/`noisy`) marks the premise robbed. Three condition predicates join
  the shared grammar for flashbacks and contracts: `premise_cased`,
  `premise_robbed`, `job`. Stages, the alarm and flashbacks themselves land
  in the following changes. A story without `paths.jobs` is unchanged apart
  from an empty `jobs` field in its save.
- **Jobs: stages, the alarm, the score and the getaway** (engine;
  `jobs.resolve_stage`/`abort`/`tick`/`band_for`, `checks.shift_band`, effect
  kinds `job_stage` and `job_alarm`, RNG stream `job`, verbs `job` → skill
  `job_stage` and `abort` → skill `abort_job`). An open job now walks its
  stages one turn at a time: `job` offers the current stage's approaches (the
  story's ways in at the entry, else the stage's one approach) and `abort`
  walks away with nothing, spending no time. Each stage spends its in-game
  hours before it rolls, so the household inside is whoever is home by then.
  The band is the premise tier's, walked by the stage, every security feature
  that applies (a cased one at its known shift), every carried tool that
  applies and any banked flashback shift, and each step that moved it comes
  back as a reason in words. A success advances cleanly; a partial advances
  at a cost (the alarm rises a little); a failure does not advance, raises
  the alarm further, gets the thief SEEN by the household member in the way
  (a real Law witness) or, at an entry the story marks `hurts: true` (a new
  optional per-entry key), is a fall that costs hp under the story's death
  rules; a death while a job is open (a fall, or the stage's hours taking
  the last hp) closes it `hurt` beside the custody release in
  `encounter.check_death`, so the thief never wakes still offered the house.
  Inside, whoever is no longer at home by the roll is dropped from the queue
  first, so only someone present is rolled against or can see the thief. One
  stage turn files at most one Law deed, however many saw it. A
  full alarm wakes the house, which shouts for the watch; after the story's
  delay in further in-game hours -- the job's own stage hours, since the
  wall-clock world tick (`run_turn`'s background tick) does not run while a
  job is open and is re-stamped so no burst of hours arrives when it closes
  -- the job closes `caught` and the Law's arrest scene opens -- with no
  Law, it closes `aborted` and nothing is filed, and the narrator hears
  that the house woke, not that the player walked away (`job_close` stamps
  `by: player` only for `abort`). The score draws loot on the
  new stream and names the house's secret if casing found one; a good getaway
  carries the loot out hot (theft provenance written), marks the house robbed
  and commits the alarm's deed on the street. Anchored premises' extra stages
  roll their authored skill and band. No authored scene is dealt while a job
  is open, and none can take the turn from one.
- **Jobs: prep and flashbacks** (engine; `jobs.legal_flashbacks`/`flashback`/
  `prep_band`, effect kind `job_prep`, verb `flashback` → skill
  `call_flashback`, predicates `premise_cased`/`premise_robbed`/`job` proven
  in the shared grammar). The veiled `prep` meter is earned only by casing --
  `premises.case` pays `prep.per_case` into it, capped at `prep.max`, and only
  on a watch that actually learned something, never a refused one. Mid-job,
  `flashback <kind>` calls on something arranged beforehand: it spends prep
  (and coin, where named) through effects, banks its `effect` into the
  current stage -- a shift into the band, or the first obstacles gone from
  `inside`, initialised the same deterministic way a roll there would be --
  and marks the kind used for the rest of the job. `legal_flashbacks` is what
  the verb offers: a kind whose stage matches, not used yet, affordable, and
  whose `requires` (`{district}`/`{premise}` filled from the open job) the
  shared condition grammar accepts. `exposure: household` draws one member of
  the premise on the `JOB` stream and, only where a Law is declared, commits
  the alarm's deed with them `certain` -- a real, named witness; with no Law,
  nothing is drawn or filed. A flashback never calls `advance_time`: the
  present stage's odds and its costs change, but no hour passes. A story
  without `paths.jobs` pays nothing for any of this, casing included.
- **Jobs: the narrator and the player see the job** (engine;
  `prompts.job_block`, `jobs.stage_words`/`stage_labels`/
  `current_obstacle_label`/`flashback_label_this_turn`, `state.py`'s `job`
  payload, `evaluator.contradicts`). The world-state block gains a JOB
  section whenever one is open or closed this turn: the house by name, the
  stage in words (never its id or a difficulty band), the obstacle in the
  way (a household member by display name, a security feature by its own
  authored `text` -- never the bare id), the reasons moving this stage's
  odds (`band_for`'s own words), which flashback paid off -- by its label,
  on the turn it was called only -- and the alarm, as a word; a job that
  just closed says how. A security feature's reason ("cased already"/"not
  yet cased") now names it by the same authored `text` the obstacle line
  uses, rather than its id with underscores swapped, so the two lines never
  disagree. `to_client_dict` ships the same facts as `job`:
  `{"active": null | {premise_name, stage_label, stages, at, alarm},
  "prep": "<band>"}`, `prep` living ONLY at the top level (not duplicated
  inside `active`) since it is earned by casing whether or not a job is
  open. A story that declares no `paths.jobs` sees no `job` key at all, and
  the flagship's payload stays byte-identical. `contradicts` gains a fourth
  anchored opposite: a clean, silent entry claimed over an ENTRY `job_stage`
  receipt whose `outcome` is `noisy`/`seen` (undone by a contrastive
  "but"/"until"/"though"/"yet" later in the same sentence, so honest prose
  that owns up to the noise a clause later is not caught), and getting
  inside claimed over an ENTRY stage receipt whose `advanced` is `False` --
  both entry-only, since at every later stage the thief is already in: a
  failed roll there is honestly narrated as such, and noise at the maid or
  the strongroom says nothing about how quietly they got in.
  Anchored the same way as the Law's own `_CLAIMS_UNSEEN`. A flashback now
  stamps `active.last_flashback` (`{label, turn}`) through `job_stage`,
  mirroring the Law's `last_deed.turn`.
- **Jobs: authored jobs and guild contracts** (engine; `engine/world/jobs.py`'s
  `_load_features`/`_load_tools`, docs). A `features` or `tools` row may now
  name an anchor's own stage id (`anchors.<id>.stages[].id`), not only the
  five derived stages — a security feature or a carried tool on the vault
  floor is read exactly the same way as one on the front door: the feature's
  known shift once cased, the tool's shift, banked flashback shifts, summed
  and clamped once with the anchor's own authored band. Naming a stage that
  is neither of the five nor any anchor's own is still a load fault naming
  the file. Three rows that used to load and then do nothing (or worse) are
  now load faults naming the file too: a feature on an anchor's stage whose
  own anchor's `security` does not declare it (no premise that reaches that
  stage could carry it), `obstacle: true` on any stage but `inside` (it
  blocked `inside` while its shift applied nowhere), and `entries` on a
  feature or tool whose stage does not include `entry` (the filter binds only
  there). A guild contract needed **no new engine surface**: it is a plain
  `paths.threads` template whose `requires` gates where it can be struck,
  whose `discharge_requires` reads the existing `premise_robbed` predicate
  (filtering by premise, type and district together) so it cannot be settled
  until a job has actually robbed a matching house, whose `on_discharge` pays
  the fee net of the Guild's cut as one `gold` effect, and whose `on_break`
  sours the Guild as one `reputation` effect once `due_in_days` passes
  unpaid — `threads.expire_due`, already run on every day tick, breaks it
  exactly as it breaks any other bargain. `docs/AUTHORING.md` gains a
  `paths.jobs` section (§3.12) written against the loader as it actually is,
  with the contracts-as-threads recipe and a worked example.
- **HUE & CRY's jobs, measured** (content and a harness; `games/hue-and-cry`
  declares `paths.jobs` → `data/rules/jobs.yaml`, new
  `scripts/simulate_jobs.py`). Tallowmere's houses can be burgled: `burgle`
  opens a job on any unrobbed house in the district, and it is walked stage by
  stage — the approach, a way in (the door, a window, over the roof with a
  fall to pay for failing, or through the cellar), whoever is inside, the
  strongroom, the getaway. Every security row of all eight house types and
  four anchors now does something to a named stage, cased and uncased (the
  greasy step, the hanging tapers, the fat old mastiff, the Margrave's bell
  floor), and `tests/test_hue_and_cry.py` fails the suite if a new row ships
  without a line. The Treasury gains its own stage, `vault_floor` ("the vault
  floor on its springs"), carrying its `bell_floor` row; Vessaline House gets
  none (its French lock is a harder strongroom, which is what it is). The
  Treasury's household now lists its night guard first, so the one man a
  `bribed_servant` flashback can have bought is the one on the door. New
  items `lockpicks` (door, cellar and strongroom; kept) and `smoke_pellet`
  (one getaway; spent), sold by Marrow in the Snuffs at 15 and 4 crowns. The
  Law gains the `burglary` deed at severity 3. Mother Gannet's first contract
  (`gannet_silk_row`): struck at the Porters' Hall, any house on Silk Row
  inside three days, fifteen crowns once one has been robbed (twenty less the
  Company's quarter), and left undone it sours `honest_company`. It is struck
  only while no Silk Row house has been robbed (`requires`' `none:` group),
  since the discharge cannot tell a robbery done for the contract from one
  done before it. `bribed_servant` asks `premise_cased` (you watched this
  house), not `visited` its street. Any house,
  not only a townhouse: Silk Row's houses are drawn per seed and on 7 of the
  first 300 seeds it drew no townhouse, which made a townhouse contract one
  that could only break; every seed has Silk Row houses to rob (asserted over
  300 seeds). HUE & CRY now declares `paths.factions`
  (`data/world/factions.yaml`) with that one faction, so the break costs a
  standing the story owns instead of logging "Unknown faction" (asserted:
  breaking the contract logs no warning). No Tallowmere vendor declares a
  faction, so no price moves. The
  storyteller prompt gains a paragraph on how a job feels in Tallowmere.

  **Measured** (AGENTS.md rule 10) with `scripts/simulate_jobs.py`, 40 seeds,
  every action through `tool_dispatcher.execute_intent`: `blind` (tier-1/2,
  uncased, empty-handed, whenever, by the door, never walks away), `careful`
  (lockpicks, cases to two lines, waits for the empty hour, best way in,
  flashbacks, walks away from a roused house), `greedy` (the careful method
  plus a smoke pellet, fully cased, a tier-3+ house then the Treasury at
  23:00, never walks away) and `greedy_bare` (the Treasury the blind way).
  Share of jobs; "caught" is the watch at the door, "arrested" is losing the
  Lantern's stop after it; haul is the registry value carried out.

  First tuning (the plan's starting numbers):

  | policy / rows | clean | noisy | caught | aborted | mean alarm | flashbacks | prep at start | deeds filed | arrested | haul |
  |---|---|---|---|---|---|---|---|---|---|---|
  | blind tier 1 | 10% | 49% | 41% | 0% | 2.61 | 0 | 0 | 0.39 | 15% | 5.7 |
  | blind tier 2 | 2% | 20% | 79% | 0% | 3.66 | 0 | 0 | 0.79 | 10% | 25.1 |
  | careful tier 1 | 27% | 58% | 0% | 14% | 1.75 | 0.87 | 2.25 | 0.56 | 0% | 6.0 |
  | careful tier 2 | 11% | 44% | 0% | 45% | 2.84 | 2.17 | 2.3 | 0.77 | 0% | 22.8 |
  | greedy tier 3 | 0% | 29% | 71% | 0% | 3.54 | 2.92 | 3 | 1.25 | 8% | 97.1 |
  | greedy tier 4 | 0% | 0% | 100% | 0% | 4.0 | 2.6 | 3 | 0.93 | 20% | - |
  | greedy Treasury | 0% | 0% | 100% | 0% | 4.0 | 2.45 | 3 | 1.0 | 12% | - |
  | bare Treasury | 0% | 0% | 100% | 0% | 4.0 | 0 | 0 | 0.88 | 12% | - |

  Last tuning (what ships):

  | policy / rows | clean | noisy | caught | aborted | mean alarm | flashbacks | prep at start | deeds filed | arrested | haul |
  |---|---|---|---|---|---|---|---|---|---|---|
  | blind tier 1 | 16% | 62% | 22% | 0% | 2.71 | 0 | 0 | 0.41 | 7% | 5.8 |
  | blind tier 2 | 3% | 47% | 50% | 0% | 4.10 | 0 | 0 | 0.74 | 8% | 24.1 |
  | careful tier 1 | 23% | 70% | 0% | 7% | 1.82 | 0.84 | 2.23 | 0.46 | 0% | 5.8 |
  | careful tier 2 | 14% | 61% | 0% | 25% | 2.88 | 2.19 | 2.3 | 0.58 | 0% | 24.4 |
  | greedy tier 3 | 8% | 75% | 17% | 0% | 2.62 | 2.17 | 3 | 0.46 | 0% | 95.7 |
  | greedy tier 4 | 0% | 60% | 40% | 0% | 3.8 | 2.93 | 3 | 1.07 | 0% | 234.4 |
  | greedy Treasury | 0% | 20% | 80% | 0% | 4.78 | 2.92 | 3 | 0.8 | 18% | 780 |
  | bare Treasury | 0% | 0% | 100% | 0% | 5.0 | 0 | 0 | 0.88 | 12% | - |

  Runs ending `sought` or worse anywhere: blind 30%, careful 32%, greedy
  38%, bare 0%; `wanted` or worse 8% / 10% / 2% / 0%. (Re-measured after
  absent household members stopped being rolled against: only `blind`, which
  goes in whenever it arrives, moved -- tier 2 from 58% caught to 50%.) No run took the thief
  below full hp. What moved and why is in `jobs.yaml`'s header: `tier_band`
  3/4/5 from hard/severe/legendary to standard/hard/severe, `alarm.max` 4 → 5
  (a fifth word, "restless"), `score.shift` 0 → -1, `treasury_guards`
  `known_shift` 1 → 0, `vault_floor` severe → hard. `burglary` stayed at
  severity 3 (at 2, only 2–10% of runs reached `sought`; at 4 a careful burglar
  ended a quarter of its runs `wanted`), and `watch_delay_hours` stayed at 2.
  The Law's v0.10.0 table is untouched (no harness there burgles).

  **Not reached, and reported rather than bent:** the plan asked for a
  careful thief who finishes tier-1/2 jobs CLEAN most of the time. The engine
  closes a job clean only when every roll was a full success — a `partial`
  gets through but raises the alarm, and any alarm at the getaway is `noisy`
  — and an empty house is still four rolls. With every roll forced to
  `trivial` and the thief's best skill, careful measured 28–32% clean. What
  ships is a careful thief who carries the take out 83% of the time and is
  never caught — a roused house is walked away from (`aborted`, 7–25%) rather
  than pressed, and the quirk below is why that abort always beats the watch
  there — and a clean night that stays rare. `tests/test_hue_and_cry.py`
  asserts that shape (carried out ≥ 60%, caught ≤ 10%, blind caught ≥ 20%,
  the bare Treasury never, the prepped one sometimes) over the first 12 seeds.

  Engine quirks the measurement ran into, recorded (jobs.yaml header,
  AUTHORING §3.12) and not changed: the watch's delay counts whole in-game hours (`jobs.now_hour`
  floors), so a stage of fractional hours can bring it up to an hour late;
  and `abort` on a roused house ends the job before the watch arrives — the
  deed and its witnesses stand, but nobody comes to the door, which is
  exactly the door the careful thief's own "never caught" line above walks
  out of.

## [0.10.0] — 2026-09-24

**The Law**, the second of the four v0.9 engine features, proven against HUE
& CRY: Tallowmere gets a watch that sees, remembers, spreads word and can put
you in the cells. A lift, a casing or an unwelcome offer to a fence is now a
witnessed deed; word of it travels person to person; the watch adds it to a
wanted level per guise per district that cools with quiet days; a mask fools
the watch until it does not; and a Lantern who knows your face opens a stop
with five ways out, one of which is the cells and a charge sheet you can pay
off or serve out. The narrator and the player's own screen both see the same
facts the watch does, in the story's words, never a number.

### Added

- **Deeds and witnesses** (engine; `law.commit_deed`, effect kind `witness`,
  RNG stream `law`). In a story with a Law, a lift is a `pickpocket` deed,
  casing a house is `loitering` and offering hot goods to an honest vendor is
  `fencing`. Everyone awake where it happens may see it — less often at dusk
  and night, less often the better the stealth roll; a caught hand is always
  seen by its mark and a clean one never is. A witness who is the watch
  reports at once, a `reporters` role at its chance, and the refusing vendor
  always. Every witness and report of one deed shares a deed id, and the
  wanted score counts each deed once, at its clearest report, however many
  saw it. A deed inside a house is filed with its street's watch. Loitering
  is remembered and never reported on its own. The lift,
  case and sell receipts gain `seen_by` and `reported`; the narrator's receipt
  lines carry no ids (rendering who saw is a later task). Stories without a
  Law are unchanged.
- **Reports travel** (engine; `law.propagate`, called from
  `clock.advance_time`). In a story with a Law, what a witness saw moves person
  to person, one remove per in-game hour, between people awake in the same
  room through that hour: each deed a person holds may be told with
  `spread_per_hour` (default 0.3), at the next hop's precision, never past hop
  3 and never to anyone who already holds it. Reaching the watch files a
  report where that watchman stands, so a baker's sighting can raise the
  town's wanted level by nightfall. The watch's memory now cools on the clock
  too, hour by hour, so a report filed late in a long sleep is not forgiven by
  the hours before it. Both run on the hours that actually passed — twelve
  one-hour turns and one twelve-hour sleep leave the Law identical, and a long
  sleep carries talk two days at most. The `witness` effect accepts a told
  copy only if someone holds that deed one hop nearer and at that hop's
  precision, and the copy keeps the sighting's deed, severity, guise and
  place. Stories without a Law never enter the pass.
- **Wanted per guise per district** (engine; `paths.law`,
  `engine/world/law.py`). A story may declare one law file — jurisdictions,
  deeds and their severities, wanted bands and thresholds, guises, the watch's
  starting links, arrest — validated at load, every fault naming the file. The
  wanted level per guise per jurisdiction is Σ severity × precision over the
  reports filed there (each file cooling on its own), shared by guises the
  watch believes are one person, and spoken as a band word, never a number.
  New effect kinds `report`, `quash_reports` and `law_cool`; new saved field
  `GameState.law` (empty for a story with no Law, and for old saves). A quash
  lasts: the deeds it lost are remembered per jurisdiction (`law.quashed`)
  and that watch-house refuses to re-file them when a witness's gossip
  reaches one of its watchmen — another district's watch still can.
- **Guises** (engine; verb `guise`, skill `change_guise`, effect kinds
  `law_guise` and `law_link`, `law.change_guise`). In a story with a Law, the
  player may put on any guise whose item is carried, or their own face,
  costing no time. The verb offers exactly those, never the one already
  worn. If anyone present and available notices the change, the watch's
  belief updates — the old face and the new one are joined in `links`, from
  then on read together by `wanted_score` and `same_person` — the same roll
  `commit_deed` uses, on the same `law` stream. A committed deed always files
  whichever guise is worn at the time. `law_link` seeds `state.law["links"]`
  from the file's own starting belief the first time it writes, rather than
  replacing it with a set of one; both new effects are symmetric,
  deduplicated and independently validated. Stories without a Law never offer
  the verb.
- **Patrols, arrest and custody** (engine; `law.recognition`, `law.patrol`,
  effect kinds `arrest` and `release`, verbs `pay_fine` and `serve`, skills
  `pay_fine` and `serve_sentence`). Once a turn, after the chosen intent and
  before narration, each watchman present and awake rolls on the `law` stream
  to know the face the player wears: `recognise[band]` × the clearest report
  the watch holds on that face (or a linked one) in this jurisdiction. Bands
  the file does not list never roll, and nothing rolls while held or while a
  scene is open. A hit opens the story's `arrest.encounter` and tells the
  narrator who knew which face; a law file naming a missing encounter fails at
  load, naming the file, wherever the story declares `paths.encounters` (a
  scene that vanishes after load warns once). An `arrest` outcome moves the player to the gaol,
  confiscates every HOT unit carried (a mixed stack keeps its cool ones; the
  `provenance` effect gains `newest: true` for this) and sets custody: fine =
  `fine_per_severity` × S and days = `days_per_severity` × S (at least one
  when S > 0), where S is the severity charged here against that face and its
  linked faces, each deed once. While held, travel is neither offered nor
  accepted by `move_to`, and no house is offered to `case`; rest is still
  offered. `pay_fine` (offered only with
  the coin) and `serve` (days × 24 hours through `advance_time`, a meal at a
  time with the prisoner fed before each, so a sentence never starves anyone)
  close exactly the deeds the arrest charged — recorded in custody — through
  the new `law_discharge` effect, which drops their reports and witness rows
  and remembers them so neither `report` nor `witness` accepts them again.
  Deeds committed from the cell stay filed; a bare `release` (a story's
  break-out) closes nothing; a death's respawn ends custody. No roll happens
  while an encounter, a dealt card or a set-piece owns the turn
  (`intents.scene_owns_turn`, shared with the verb catalogue), nor on a turn
  that began inside one, so escaping a stop is not followed by the same stop.
  Stories without a Law never reach the patrol.
- **A deed from authored content** (engine; effect kind `deed`). `{type:
  deed, deed: <kind>}` commits a deed through `law.commit_deed`, so a
  scene's outcome can be a crime; `seen_by_watch: true` makes every awake
  law-role person present a certain witness. Refused for a kind the law file
  does not list. The watch_stop's fight uses it.
- **The narrator and the player see the Law** (engine; `prompts.law_block`,
  `evaluator.contradicts`, `to_client_dict`'s `law` key). In a story with a
  Law, the world-state block gains a `THE LAW:` section — never a score, a
  precision or an id — with only the lines that apply: who saw the deed
  committed THIS turn, by display name ("clearly" at precision 1.0, "only a
  glimpse" otherwise) — every deed, seen or not, updates `law.last_deed`
  (stamped with the turn when seen, cleared when not), so an unseen lift
  names nobody and a deed from an earlier turn
  says nothing; the wanted
  band for the guise currently worn, in this jurisdiction, once it is above
  the story's own floor band; the law-role people standing here; and
  custody, if held, as the story's own money and the days in words. The
  evaluator now catches a clean-getaway claim ("unseen", "no one noticed",
  "you slip away unnoticed"…) narrated over a receipt whose result carries
  `noticed: true` — `lift_purse`'s own word for a caught hand — alongside
  its existing checks, without flagging honest caught-prose. The player's
  own payload gains a `law` key (`guise_label`, `wanted` by jurisdiction
  label — an optional `labels:` map in the law file, else a humanised id —
  and `custody`), omitted entirely for a story with no Law so the flagship's
  payload stays byte-identical. Nothing renders it yet; see
  docs/GOVERNANCE.md's NOT WIRED table.
- **HUE & CRY's Law, measured** (story; `paths.law`, `paths.encounters`,
  `paths.threads` in `games/hue-and-cry/game.yaml`). Tallowmere gets its
  Lantern Watch: three watch-houses (the Quay, the Wick wards, up the Rise;
  the three secret places answer to none), the respectable city as reporters
  and the Low Town not, guises `self` / `magpie` / `porter` with the Watch
  believing from the first morning that you are the Magpie. A Lantern who
  knows your face opens `watch_stop`, the Lantern's stop, with five ways out
  in the story's register: run (stealth, easy), talk (persuasion, hard; a
  partial buys another sentence), bribe (three crowns a severity of the
  charge he would lay, no roll), surrender, and fight (nerve, hard) — which
  is `assault_watch` whether you win or lose.
  A failed run, a failed talk, surrender and a lost fight are the cells.
  Dock Mag, the first honest vendor, sells the porter's smock on the quay;
  Marrow sells a Magpie mask he swears is a fair-day copy. Sergeant Brask's
  price (`brask_bribe`): strike it at his desk in the Lantern House, then
  settle it with twelve crowns in the biscuit tin and every report the Wick
  holds against you — and against the Magpie while the Watch believes you
  are one — goes missing. An arrest costs three crowns a severity, at most
  30, or at most three days in the cells. The narrator's prompt gains
  a paragraph on how the Lanterns and being wanted feel in this city.
- **The Law's numbers, measured** (`scripts/simulate_law.py`, new; AGENTS.md
  rule 10). A headless harness that plays HUE & CRY through
  `execute_intent` and the real patrol: 40 seeds x 10 in-game days, a
  CAREFUL thief (one lift a night in the Snuffs in a porter's smock put on
  unseen) and a RECKLESS one (three lifts every afternoon in Wickmarket in
  its own face, lingering among the Lanterns), both running from every
  stop, and a BRIBER — the reckless thief paying every Lantern it can.
  `--set key=value` tries a number without editing the file. What moved
  from the plan's starting numbers: `wanted.cool_per_day` 1.5 -> 0.5,
  `wanted.thresholds` [0,2,5,9,14] -> [0,2,4,7,11], `recognise`
  0.25/0.5/0.8 -> 0.03/0.06/0.12 (it rolls per Lantern per turn, and
  Wickmarket at lunch holds four), `reporters` from two roles to the
  respectable city, the stop's `run` from `standard` to `easy`, and (fix
  round 1) the arrest from six crowns and one day a severity uncapped to
  three crowns a severity capped at 30 and three days, with the street bribe
  scaled at three a severity.
  `tests/test_hue_and_cry.py` asserts the floors over the first 12 seeds.

  First tuning — the plan's starting numbers:

  ```
  careful (40 seeds)
  | day | median band (wick) | witnessed | reported | s/day |
  |---|---|---|---|---|
  | 1 | unknown | 0.00 | 0.00 | 0.016 |
  | 2 | unknown | 0.85 | 0.00 | 0.022 |
  | 3 | unknown | 0.78 | 0.00 | 0.031 |
  | 4 | unknown | 0.78 | 0.00 | 0.034 |
  | 5 | unknown | 0.78 | 0.00 | 0.038 |
  | 6 | unknown | 0.88 | 0.00 | 0.040 |
  | 7 | unknown | 0.68 | 0.00 | 0.042 |
  | 8 | unknown | 0.85 | 0.00 | 0.043 |
  | 9 | unknown | 0.82 | 0.00 | 0.045 |
  | 10 | unknown | 0.85 | 0.00 | 0.046 |
  below sought on 100% of seed-days; wanted by day 4 on 0% of seeds; first sought median day None (40 never); arrests/run 0, runs with an arrest 0%; stops/run 0; min hp after a sentence None (0 served); slowest day 0.059s

  reckless (40 seeds)
  | day | median band (wick) | witnessed | reported | s/day |
  |---|---|---|---|---|
  | 1 | unknown | 0.95 | 0.78 | 0.052 |
  | 2 | noticed | 0.91 | 0.73 | 0.064 |
  | 3 | noticed | 0.97 | 0.82 | 0.070 |
  | 4 | unknown | 0.94 | 0.78 | 0.085 |
  | 5 | unknown | 0.81 | 0.71 | 0.069 |
  | 6 | unknown | 0.89 | 0.84 | 0.087 |
  | 7 | unknown | 1.00 | 0.62 | 0.080 |
  | 8 | unknown | 0.67 | 0.67 | 0.111 |
  | 9 | unknown | 0.50 | 0.50 | 0.376 |
  | 10 | unknown | 0.00 | 0.00 | 0.000 |
  below sought on 98% of seed-days; wanted by day 4 on 0% of seeds; first sought median day 4 (34 never); arrests/run 1, runs with an arrest 100%; stops/run 2.73; min hp after a sentence 20 (40 served); slowest day 0.376s
  ```

  Final tuning — as shipped (after review fix round 1: sentence caps, a
  scaled bribe, and a third policy, BRIBER, the reckless thief paying every
  Lantern it can afford and running otherwise):

  ```
  careful (40 seeds)
  | day | median band (wick) | witnessed | reported | s/day |
  |---|---|---|---|---|
  | 1 | unknown | 0.00 | 0.00 | 0.019 |
  | 2 | unknown | 0.85 | 0.00 | 0.024 |
  | 3 | unknown | 0.78 | 0.00 | 0.033 |
  | 4 | unknown | 0.78 | 0.00 | 0.036 |
  | 5 | unknown | 0.78 | 0.00 | 0.040 |
  | 6 | unknown | 0.88 | 0.00 | 0.041 |
  | 7 | unknown | 0.68 | 0.00 | 0.042 |
  | 8 | unknown | 0.85 | 0.00 | 0.045 |
  | 9 | unknown | 0.82 | 0.00 | 0.049 |
  | 10 | unknown | 0.85 | 0.00 | 0.048 |
  below sought on 100% of seed-days; wanted by day 4 on 0% of seeds; first sought median day None (40 never); arrests/run 0, runs with an arrest 0%; stops/run 0; min hp after a sentence None (0 served, longest None days; 0 fines paid); bribes/run 0, 0% of lifted income; slowest day 0.079s

  reckless (40 seeds)
  | day | median band (wick) | witnessed | reported | s/day |
  |---|---|---|---|---|
  | 1 | noticed | 0.95 | 0.83 | 0.057 |
  | 2 | sought | 0.90 | 0.77 | 0.071 |
  | 3 | sought | 0.93 | 0.85 | 0.085 |
  | 4 | wanted | 0.95 | 0.80 | 0.095 |
  | 5 | wanted | 0.90 | 0.76 | 0.094 |
  | 6 | noticed | 0.93 | 0.81 | 0.103 |
  | 7 | noticed | 0.90 | 0.85 | 0.101 |
  | 8 | noticed | 0.96 | 0.81 | 0.101 |
  | 9 | sought | 0.89 | 0.85 | 0.092 |
  | 10 | sought | 0.96 | 0.78 | 0.092 |
  below sought on 44% of seed-days; wanted by day 4 on 78% of seeds; first sought median day 2 (0 never); arrests/run 0.85, runs with an arrest 80%; stops/run 6.5; min hp after a sentence 20 (25 served, longest 3 days; 9 fines paid); bribes/run 0, 0% of lifted income; slowest day 0.18s

  briber (40 seeds)
  | day | median band (wick) | witnessed | reported | s/day |
  |---|---|---|---|---|
  | 1 | noticed | 0.95 | 0.83 | 0.055 |
  | 2 | sought | 0.90 | 0.77 | 0.070 |
  | 3 | sought | 0.93 | 0.85 | 0.084 |
  | 4 | wanted | 0.95 | 0.80 | 0.092 |
  | 5 | wanted | 0.91 | 0.75 | 0.097 |
  | 6 | wanted | 0.93 | 0.81 | 0.110 |
  | 7 | unknown | 0.91 | 0.85 | 0.098 |
  | 8 | unknown | 0.96 | 0.81 | 0.096 |
  | 9 | noticed | 0.91 | 0.85 | 0.092 |
  | 10 | sought | 0.95 | 0.79 | 0.093 |
  below sought on 45% of seed-days; wanted by day 4 on 78% of seeds; first sought median day 2 (0 never); arrests/run 0.82, runs with an arrest 80%; stops/run 6.45; min hp after a sentence 20 (27 served, longest 3 days; 6 fines paid); bribes/run 0.25, 19% of lifted income; slowest day 0.199s
  ```

  Careful stays below `sought` on 100% of seed-days (target >= 60%);
  reckless is `wanted` by day 4 on 78% of seeds (>= 60%) and arrested at
  least once in 10 days on 80% (50%..95%) — and so is the briber, whose
  bribes cost it 19% of what it lifted: coin is a choice, not a pass. No
  sentence is longer than three days (`arrest.max_days`); a quarter of the
  reckless arrests end in a paid fine (three crowns a severity, capped at
  30). A sentence never dropped hp (min 20 of 20); the slowest in-game day,
  with 98 people and rumour resolved hourly, took 0.2 s. Before the fix the
  same harness measured sentences up to 27 days and no fine ever paid.
- **A thread can require something to be settled** (engine;
  `discharge_requires` on a thread template, `threads.can_discharge`). A
  condition from the shared grammar; while it does not hold the `discharge`
  verb does not offer the thread and `threads.discharge` refuses, writing
  nothing — a bribe whose settlement pays the sergeant is not settled by an
  empty purse (the `gold` effect clamps at zero). Templates without the key
  seal threads of exactly the old shape.
- **A thread can require something to be struck** (engine; `requires` on a
  thread template, `threads.can_strike`). A condition from the shared
  grammar; while it does not hold the `bargain` verb does not offer the
  template and `strike_bargain` refuses, sealing nothing. HUE & CRY's
  `brask_bribe` requires `at_location: lantern_house` — Brask names his price
  at his desk — and quashes only the Wick's files.
- **Sentence caps** (engine; optional `arrest.max_days` and `arrest.max_fine`
  in a law file, integers of at least 1, applied last in
  `law.sentence_for`). HUE & CRY sets 3 days and 30 crowns.
- **An approach can cost more the more the Watch has on you** (engine;
  `cost_per_severity` on an encounter approach, `encounter.approach_cost`).
  Adds that many crowns per severity of `law.charged_severity` for the face
  worn in this jurisdiction — the charge an arrest would lay — to any flat
  `cost_gold`; checked for availability, reported as the approach's
  `cost_gold`, and paid on taking it. Nothing changes for an approach
  without the key. HUE & CRY's street bribe is 3 a severity.

### Fixed

Bugs in code that shipped in 0.9.0 or earlier. Faults found and fixed inside
this release's own new code are folded into the entries above rather than
listed as fixes to something no player ever had.

- **A thread's authored structural effects were silently dropped.** Thread
  hooks were bounded with the model-composed challenge allowlist, so an
  `ending_intent`, `ending_lock` or `ending_module` in a template's
  `on_seal`/`on_discharge`/`on_break` never ran. Thread hooks come only from
  the story's own `threads.yaml`, so they are now bounded as authored content
  (`_bound_effects`, `authored=True`); `quash_reports` joins the authored-only
  structural types, which is how Brask's bribe quashes anything at all. A
  model-composed challenge still cannot use any of them, and magnitude clamps
  are unchanged. Every other Law kind in a thread hook is still dropped, with
  a logged adjustment (docs/AUTHORING.md §3.11).
- **A struck thread was offered again forever.** `threads.offerable` looked
  for a `template_id` no sealed thread carries (it is `template`), so the
  "a template already sealed is not offered again" rule never held.
- **"Death rules missing" is logged once per path**, not after every
  encounter round in a story that ships no `death.yaml` (HUE & CRY's waits
  for v1.0; until then a lost fight can leave hp at zero with no respawn).

2406 passing, 3 skipped, plus 144 client tests (measured 2026-09-24).

## [0.9.0] — 2026-09-23

The first of the four v0.9 engine features, proven against HUE & CRY as it
grows: **Premises**, plus the skeleton the rest of v0.9 builds on. A thief
story now has a city to run in — houses to case, purses to lift, and fences
to sell to — and the casing board reaches the client. The Law, Jobs &
flashbacks and Agendas ship as their own releases (v0.10.0–v0.12.0); each
feature ships as its own release now rather than sitting unpushed for weeks
while the rest of v0.9 finishes (see the spec's release table).

### Added

- **HUE & CRY's premises, pockets and fences** (content; `games/hue-and-cry/`).
  The first story to declare `paths.premises`, `paths.thievery`, `paths.items`,
  `paths.tables` and `paths.economy` together, so every v0.9 thief mechanic
  now has a city to run in. Eight premise types (`data/premises/types/`:
  townhouse, chandlery, counting-house, tavern, warehouse, temple house,
  manor, palace wing), each with name patterns, tiers, a household whose
  routines keep real hours in real districts, security by tier, loot by tier
  and a pool of five or six secrets; four hand-written anchors -- Vessaline House
  (Silk Row), the Margrave's Treasury (Margrave's Hill), Mother Gannet's House
  (the Snuffs) and the Captain's Office (the Lantern House); eight districts
  holding houses, the three secret places holding none. The empty windows are
  DESIGNED per type, not emergent: a townhouse empties for three hours in the
  afternoon, a chandlery for three in the evening, a warehouse for four, a
  counting-house for five (and is never below tier two for it); a tavern and a
  temple house for two; manors, palace wings, Vessaline House and the Treasury
  never. `data/rules/thievery.yaml` gives alertness and a purse to every role
  the schedules and households use, `data/items/goods.yaml` forty-one goods valued
  in crowns (crests, seals, plate, letters and the mint's pieces carry `named`
  and stay hot), and `data/tables/trade.yaml` + `data/economy.yaml` make the
  two scheduled fences real: Pell Hollis (Wickmarket; good spread, mean hot
  cut) and Marrow (the Snuffs; scrap spread, but a crest is a lump of silver
  by morning, so he pays more for a hot signet). `trade.currency_format` is
  `"{n} cr"`. One art subject per premise type (`premise_<type>` under
  `locations:` in `data/art/subjects.yaml`, day and night); prompts only, and
  no reader asks for them yet -- they are the v1.0 art brief.

  **Measured across seeds 0-39** (40 runs, `premises.generate` through
  `new_game_state`, occupancy read through `premises._occupancy_text`):
  31 premises per run (27 generated + 4 anchors, every run); 81.2 household
  people per run (74-88); 1240 premise names generated, 663 distinct across
  all runs, and none repeated within a run; tiers T1 35.2% / T2 33.1% /
  T3 18.1% / T4 9.2% / T5 4.4%; mean empty window 2.46 h over every premise
  (2.92 h over the premises that ever empty); **637 of 1240 premises (51.4%)
  have an empty window of at least three hours**, the worst single seed
  32.3%; 192 (15.5%) are never empty. The crowd those households make, since
  every member is a real presence in a district: the busiest district-hour
  across the 40 seeds holds 16 household people (Chandlers' Rise), 21 people
  in all counting the scheduled cast -- which is why PEOPLE HERE is now
  capped (below). (Re-measured after review round 1: the new `craft` pool
  reshuffles every name a seed draws.) `tests/test_hue_and_cry.py`
  asserts the floors -- 50% in aggregate (the measured number rounded down)
  and 30% on every seed (the brief's line) -- and that every district that
  should hold houses holds at least three, every anchor stands where the spec
  puts it, the great houses are never empty, every loot and purse item exists
  with a real value, a signet is `named`, both fences buy a hot signet (Marrow
  for more), money reads "12 cr", and every type has a day-and-night art
  subject.

  **Review round 1.** Names that misread: a `craft` name-pattern field
  (`engine/world/premises.py::_PATTERN_FIELDS`) holds the candle city's
  workshop trades, so a chandlery signs "Wick-Twister" and never "Bargeman",
  and the palace's "{craft}s' Window" always pluralises; the one late
  Margravine's apartments are a fixed name, at most one per run. Canon: the
  Everflame Prism exists once, in the Treasury (dropped from palace loot; the
  palace secret now records it being carried there); the reliquary lamp and the
  master chandler's seal read as one-per-parish / one-per-master objects; the
  temple secret that had the Everflame go out is replaced with a house-local
  one; Vessaline House's secret is the butler's and gives Lady Imelda no
  motive, because the seed, not static content, picks the Magpie. Minors:
  palace guards stand two overlapping shifts and sleep, the mint-master
  sleeps, the spyglass is used at first light when Ardane is at the Lantern
  House, the steward carries a silver pencil rather than a merchant's signet,
  no purse rolls zero gold. `tests/test_hue_and_cry.py` gains a test for each;
  the fence test now quotes at an hour each fence's schedule has her at the
  counter.
- **PEOPLE HERE is capped for generated households**
  (`engine/agents/prompts.py::_npcs_present_block`). Every scheduled cast
  member is still listed individually; generated household people (a
  `premise` key on the procgen row) are listed up to
  `MAX_GENERATED_PRESENT` (4) and the rest become one "- and N more townsfolk
  about their business" line. The flagship's villagers carry no `premise` key,
  so a story without premises renders the byte-identical block
  (`tests/test_people_here_cap.py`).
- **The casing board** (client). `GameState.to_client_dict` gains a
  `premises` key -- `[{id, name, type_label, known, of, empty_now}]` for the
  houses in the player's current district -- but only when the running story
  declares `paths.premises`; the key is absent entirely otherwise, so the
  flagship's payload is unchanged. `known` carries the TEXTS a watch has
  already learned, in learning order, never an id and never a line nobody
  has watched for yet (`engine/game/state.py::GameState._premises_block`).
  `empty_now` reads the household against the live world clock this instant
  (new `engine/world/premises.py::empty_now`), a different question from the
  occupancy INTEL line's longest-empty-run-of-the-day. `ui/src/core/store.js`
  mirrors `world.premises` onto `state.premises` exactly as `metersOf`
  mirrors `world.meters`; the new `ui/src/core/parts/CasingBoard.jsx` renders
  it beside `NegotiationPanel` in `ui/src/core/screens/Play.jsx`, and renders
  nothing for a story or a district with none. `tests/test_casing_board_payload.py`
  and `ui/tests/casing-board.test.jsx` are new.

  **Review round 1** found `type_label` falling back to the raw type/anchor
  id when a premise type or anchor declared no `label` -- an id reaching the
  player's screen. Fixed at the source rather than papered over at read time:
  `label` is now REQUIRED on both a premise type and an anchor
  (`engine/world/premises.py::_load_type`/`_load_anchor`), raising the same
  `_fail(...)` ValueError naming the file as every other required key
  (`district`/`name`/`tier` on an anchor). **Data contract change**: an
  existing premises tree missing `label` on any type or anchor now fails to
  load; none ships yet, so nothing is broken by this. `_premises_block` reads
  `spec["label"]` with no fallback at all. `tests/test_premises.py` gains two
  fault tests (a type and an anchor missing `label`, each asserting the
  ValueError names its file).
- **The HUE & CRY skeleton** (`games/hue-and-cry/`), the story v0.9's four
  engine features will be built against. Tallowmere's eleven districts (three
  `secret: true`), fourteen scheduled people covering all 24 hours with the
  watch roles `captain`/`sergeant`/`watch`, two pipeline agents (the city and
  Pip the jackdaw) so every turn negotiates, three archetypes, an opening whose
  three choices each declare an intent (stealth check, persuasion check, travel
  to The Lantern House), and one ending reachable end to end —
  `honest_after_all`, locked by the evening-barge quest, with its epilogue. Art
  prompts for every district and person; no plates. The graph template's mill
  economy, forage, labour and encounter stubs were removed rather than
  reskinned. `tests/test_finales.py` and `tests/test_presence_every_story.py`
  carry hard-coded story lists and gain a `hue-and-cry` row; the new
  `tests/test_hue_and_cry.py` holds the skeleton's shape.
- **Routines and interiors for generated people** (`engine/world/npc_sim.py`).
  A procgen NPC dict may now carry `routine`/`home` in the same shape as a
  schedule row, so a generated household member follows an hour-by-hour
  routine instead of standing at their `location_id` forever; a schedule row
  still wins outright. New `npc_sim.interior_id(district_id, premise_id)` and
  `npc_sim.is_interior(location_id)` name a premise's interior as
  `"{district}/{premise_id}"` — a person home inside one resolves there and
  no longer appears in the district's public presence, with no special case
  needed in `npcs_at` (an interior id never string-equals its district's).
  Flagship procgen villagers carry no `routine` key and are unaffected.
  `tests/test_premise_households.py` is new.
- **The premises generator** (`engine/world/premises.py`). A story declaring
  `paths.premises` (a directory: `districts.yaml`, `names.yaml`, `types/`,
  `anchors/`) gets its districts filled at world generation with seeded
  premises — name, wealth tier, security features (tier N draws N), loot rows
  from the item registry, one secret — plus hand-written anchors, stored as
  `ProcgenResult.premises` and kept by a save round trip. Every household
  member becomes a procgen NPC whose `@home`/`@work` routine is resolved to
  real ids, so `npc_sim` places them with no new code. Draws come from a new
  `PREMISES` stream after every `PROCGEN` draw, so the flagship (which declares
  none) generates a byte-identical village. Unknown items, districts, types,
  anchors or routine locations, and a tier with too few security features,
  raise a `ValueError` naming the file. Lookups `premises.at/get/spec`.
  `tests/test_premises.py` is new.
- **`case` — watching a house** (`engine/world/premises.py::case`, skill
  `case_premise` in the new `engine/skills/builtin/thievery.py`). Offered in a
  district holding premises with something still unknown, labelled "watch
  <name>". Each watch spends `CASE_HOURS = 2` through `advance_time` and
  reveals the next intel line in an order seeded per run and premise:
  occupancy first ("empty from 10:00 to 16:00", the longest run of hours no
  household member resolves home; "never empty" if none), then each security
  feature, the most valuable loot by name, and that a secret exists. Refuses,
  spending no time, outside the house's district or once all is known. Learned
  ids live in the new `GameState.premise_intel`, written only by the new
  `intel` effect kind. The narrator gets a `PREMISES HERE (what you know):`
  block (`prompts.district_block`) listing known intel only, never ids, tiers
  or unlearned loot, and a one-sentence `case_premise` receipt. A story
  without `paths.premises` sees neither verb nor block. `tests/test_casing.py`
  is new.
- **`lift` and provenance** (`engine/world/thievery.py`, skill `lift_purse`).
  A story declaring `paths.thievery` (one YAML file: `alertness` bands by
  role, `purses` by role with a required `default`, `hot_days`) offers "lift
  <name>'s purse" for every present, awake person outside a premise interior.
  A lift rolls stealth at the mark's role's band and spends no time; success
  draws one purse row on the new `THIEVERY` stream (coin through `gold`, an
  item through `item`), a partial takes coin only, halved (min 1), and a
  failure takes nothing and reports `noticed: true` — narrated only; the Law
  release reads it. The receipt says the attempt happened under `ok` and how
  it went under `success`, so a caught hand is narrated rather than read as a
  refusal (the v0.8 `work` lesson); `lift_purse` joins the evaluator's
  `ROLLING_SKILLS` and gets a one-sentence receipt with the mark's name and no
  ids or rolls. The `item` effect accepts optional `stolen_from: {whom,
  where}` and appends one `{whom, where, day}` per unit to the new
  `GameState.provenance`; the new `provenance` effect kind consumes records
  oldest first, which is what a sale below consumes. `thievery.heat` is `hot`
  within `hot_days` or while the item is tagged `named`, `cool` after, `""`
  if never stolen. Unknown items or bands, or no `default` purse, raise a
  `ValueError` naming the file. A story without `paths.thievery` sees no verb
  and an unchanged prompt. `tests/test_thievery.py` is new.
- **Fences and honest vendors** (`engine/game/trade.py`, new
  `thievery.heat_split`). `trade.quote`/`trade.sell` now read, per unit
  rather than per item, how much of a carried stack is `clean` (never
  stolen), `cool` (stolen, aged past `hot_days`) or `hot` (stolen and still
  fresh, or `named`), through one shared helper (`trade._plan_sale`) so the
  two can never disagree about a mixed stack. An honest vendor (no
  `fence: true`) sells clean and cool units at the ordinary price and refuses
  the whole sale, in its own voice, only when it would have to reach into the
  hot ones (`"<vendor> won't touch it -- not this week"` when nothing clean
  is left, `"<vendor> will take the clean ones, not the rest"` when some
  is). A fence (`fence: true`, optional `fence_cut: {hot, cool}`, default
  0.5/0.8) sells hot units first, then cool, then clean, pricing each
  category at its own cut — a clean unit is never discounted, even at a
  fence. `sell` consumes one `provenance` record per STOLEN unit actually
  sold (never for a clean one), through the `provenance` effect kind, which
  is what a sale pays to launder — `remove_item` (a complication, not a
  sale) still never touches it. The `_sell` intent labels a target `(hot)`
  exactly when the single unit that target would move is a hot one, reading
  the same `unit_kind` `quote` computes. A story without `paths.thievery`
  sees an all-clean split for everything, so its sell path is unchanged, and
  a `quote` for more units than the ledger has any record of — the
  possession-free "what would this fetch" question `browse` and a bare price
  check have always been able to ask — prices the whole request as clean
  rather than refusing or discounting it. Fixed alongside: the `provenance`
  effect's receipt read `item_id.replace('_', ' ')` instead of the registry
  name, and `REFUSAL_KEY_FOR_ACTION["sell"]` named a key (`"ok"`)
  `trade.sell` has never returned, so a refused sale never reached the
  narrator as one — it now reads `"success"`, which is what the skill
  actually reports. `tests/test_fences.py` is new.

  **Review round 1** found the first cut of this read `thievery.heat` — the
  item's single, worst-case answer — and applied a refusal or a fence cut to
  an ENTIRE requested quantity: selling one clean ring and one stolen ring
  together had an honest vendor refuse both, and a fence discount both. The
  per-unit split above is the fix.

### Fixed

- **`REFUSAL_KEY_FOR_ACTION["buy"]` had the same latent bug `"sell"` did
  before this task** (v0.9.0 review, round 1): it named `"ok"`, a key
  `trade.buy` has never returned (it reports a refusal — can't afford it,
  not stocked — under `success`, same as `trade.sell`), so a refused
  purchase reached the narrator as a successful one, the same class of
  defect as v0.8's `work` mistake. Now reads `"success"`.
  `tests/test_fences.py` carries both a canary (the old key genuinely misses
  a real refusal) and an `execute_intent` end-to-end proof.

- **`crit_success` was unreachable in three stories.** The graph template's
  `min_margin: 10` over a `standard` DC 13 needs a total of 23; the best builds
  in HUE & CRY and NEON CITY roll 22 on a natural 20 and THE LONG CON's 21, so
  the band could not be rolled — the flagship's own old bug, copied by
  scaffolding. All three and the template now use the flagship's 6.
  `tests/test_checks.py::test_every_declared_degree_is_reachable_by_some_shipped_build`
  hardcoded the flagship, which is why nothing failed; it now parametrises over
  every discovered story with a skills table and reads the arithmetic from the
  engine (`apply_archetype`, `gather_modifiers`).

**Final-review fixes** (whole-branch review before release):

- **`trade.quote`'s `summary` writes money through `currency_label`** instead
  of a hardcoded `"c"` (`engine/game/trade.py`). Changes the flagship's quote
  summary text from "...c" to "...g", matching its `currency_format`; a
  content-only story tweak, not a behaviour change.
- **Lift offered the wrong people in a crowd** (`engine/game/intents.py::_lift`,
  `engine/world/thievery.py::marks`). Over `_MAX_OPTIONS` (8) marks, the verb
  kept the first eight in `known_npc_ids` order, which lists every procgen
  NPC ahead of the schedule — so a crowd could push named cast (Silas Crook,
  Pell Hollis, a Lantern) out of the `lift` options while PEOPLE HERE still
  named them standing right there. `marks()` now sorts scheduled NPCs first
  (`npc_sim.is_scheduled`, shared with `prompts._npcs_present_block`'s own
  scheduled/generated split so the two can never disagree) before truncating.
  `tests/test_thievery.py::test_the_named_cast_survives_a_crowd_over_the_option_cap`
  is new.
- **Lifting was free and unlimited — a real money exploit** (10 lifts on the
  same marks took a fresh character's gold 5 to 21 in one in-game hour,
  repeated indefinitely). Controller ruling: a mark the player has already
  attempted (success, partial or noticed) is not offered again the same
  in-game day. Recorded through `apply_effect`'s `flag` kind
  (`lifted_<npc_id>_d<day>`), read by `marks()` and refused by `lift()` in its
  own voice ("`<name>` is watching their purse now"); clears on the next
  day's `advance_time` and survives a save round trip, since `state.flags` is
  ordinary saved state. `tests/test_thievery.py` gains the same-day refusal,
  next-day availability and save-round-trip tests; `test_a_seed_replays` now
  exercises the same mark across a day boundary instead of twice in one day.
- **The `_sell` intent's label printed a bare price** (`"for 1"`) while
  `_buy`'s used `trade.currency_label` (`"6 cr"`) (`engine/game/intents.py`).
  `_sell` now reads the same helper.
  `tests/test_wired_verbs.py::test_the_sell_label_reads_the_storys_currency_like_buy_does`
  is new.

2174 passing, 3 skipped (measured 2026-09-24, after the final-review fixes above).

## [0.8.1] — 2026-09-23

Housekeeping: the files that describe the repo now agree with it, and a test
keeps them agreeing.

### Added

- **`AGENTS.md`**, the tool-neutral operating rules for any coding agent: the
  start-here reading list, all twelve critical rules, the working conventions
  (releases, the changelog, tests, time and randomness in new systems, the three
  audit questions, where debt is written down), verification and canon ids.
  Other agents read it directly; `CLAUDE.md` imports it with `@AGENTS.md`, so
  the rules exist once and cannot drift. Not to be confused with
  `docs/AGENTS.md`, which documents the in-game agents. The rule text was moved
  programmatically and diffed byte-identical, rule 12 included.
- **`tests/test_release_hygiene.py`.** Fails the suite when the CHANGELOG has no
  `[Unreleased]` section, when its newest release disagrees with
  `pyproject.toml` or `ui/package.json`, when releases are out of order, when
  `CLAUDE.md` does not state the current version, when `CLAUDE.md` stops
  importing `AGENTS.md`, when `AGENTS.md` loses any of the twelve rules, or when
  the declared Python floor is one the suite is not running on. Every one of
  those has been wrong before while the suite was green.

### Changed

- **`CLAUDE.md` is an instruction file again.** Its Status section had grown to
  ~370 lines of history. That history moved verbatim to
  `docs/DESIGN_REVIEW.md` ("Findings after the overhaul"); `CLAUDE.md` keeps the
  current release, the measured counts, what is in flight, what is deliberately
  deferred, a one-line index of the findings, and this machine's notes.
- **Rule citations point at `AGENTS.md`** across engine, tests, scripts and
  story YAML (34 in 24 files, plus the canon-id pins), because that is where
  the rules live now. History -- CHANGELOG, the moved findings, the spec and
  plan -- is left as written, and `ui/src` comments are left alone so the
  committed build is not made stale by a comment.
- **README.md** stopped hardcoding test counts (it claimed 2020 and 126), lists
  all five simulator policies instead of three, and its documentation table
  names every document including CHANGELOG, AUTHORING, GOVERNANCE, STATE and
  both AGENTS files.

### Fixed

- **The declared Python floor was false.** `pyproject.toml` said
  `requires-python = ">=3.13"` and the README said 3.13; the venv the entire
  suite runs on is 3.11.9. It says `>=3.11` now, which is the floor that is
  actually tested.

### Removed

- **Seven duplicate design-system export zips** from `Design_files/`, redundant
  with the extracted design system beside them. The design system itself stays
  tracked -- the flagship's UI plugin cites it -- and its top-level readme is
  `README.md` rather than `readme (3).md`. The `.gitignore` comment no longer
  claims nothing in that folder is committed.
- A stale local branch left by an earlier session's agent, already fully merged.

## [0.8.0] — 2026-09-23

The audit release. No new mechanics: every item is a place where the engine
knew something and the prose did not, or said one thing and did another. It is
also the groundwork for HUE & CRY (`docs/superpowers/specs/2026-09-23-hue-and-cry-design.md`),
whose whole game is who saw you -- which cannot be built on a narrator that does
not know who is in the room.

### Fixed

- **In four of five stories, nobody was ever present.** `present_npc_ids` and
  the PEOPLE HERE block returned early whenever `state.procgen.npcs` was empty,
  and only the flagship runs procgen. So in the Garden, NEON CITY, THE LONG CON
  and dev-story the narrator read *"PEOPLE HERE: (world not yet generated)"*
  while the buy intent offered a present vendor's stock; the cast gate then
  failed any prose naming her and the retry told the model to remove her; no
  dossier was built and nobody was ever met; and every fact the model filed
  against a person lost its subject, because `known_npc_ids` came from the same
  empty list -- so gossip had nothing to spread. Presence now comes from the
  schedules. One call, `npc_sim.display_name`, is where every narrator-facing
  name comes from, and it never returns an id: the dossier printed
  `npc_maris (npc_maris)` because `ledger.names` is keyed by proper noun and
  was being looked up by id.
- **The Wicked Garden's cast had no names.** Its eight schedule rows carried
  neither `name` nor `role`, so presence rendered `ashen_vale: ashen_vale
  (visitor)` -- and its own `role_defaults` for `bloomkin` and `court` could
  never match a row. A guard now fails any shipped story with a nameless
  scheduled person.
- **The evaluator could not tell success from failure.** Only `roll_dice` and
  `resolve_skill_check` counted as rolls, so a real `work` shift honestly
  narrated as a success scored mechanics 0.2 and forced a retry -- pushing the
  narrator AWAY from reporting outcomes. And nothing compared prose to receipt:
  "You succeed" over a failed check passed. Every rolling skill counts now, and
  a deliberately narrow check fails success-over-failure and
  arrival-over-a-refused-move, with a counter-control suite of honest failure
  prose it must not flag. `continuity` reaches the payload, which `to_dict` had
  dropped.
- **A shift worked badly was narrated as never having happened.** `work`
  reported how the shift WENT under `success`, which is the key the intent
  layer reads to decide whether it HAPPENED -- so the narrator was told "did
  NOT happen" while the hours and stamina were really spent. It says `worked`
  for the second question now.
- **Veiled numbers reached the narrator.** `narration_block` printed `name
  after` for every committed value, ignoring the receipt's `visibility` field;
  veiled values render as band words now and hidden ones not at all.
  `receipts_block` dumped any unrecognised result as a Python dict -- a forage
  receipt measured ~1,600 characters, DC and "stamina 94" included. Every
  receipt is one sentence now, and an unknown skill leaks nothing. The
  `scene_begin` receipt no longer lists the hand.
- **"Be merciful with consequences" went to every story on every turn.**
  `cruelty_bias` defaulted to 0.2, nothing ever wrote it, and 0.2 trips the
  merciful branch. The governance test proved it without meaning to: it had to
  set the knob to 0.35 by hand to get silence. Both knobs are optional story
  settings now (`storyteller.cruelty_bias`, `storyteller.reward_generosity`);
  a story that sets neither gets no disposition line. Patience, which only ever
  fell, recovers on a turn where the pressure comes down.
- **Vendors traded from wherever their counter was, whoever was standing
  there.** `vendors_at` read the static trade table, so the flagship offered
  "sell to Brindle" in the square at 11:00 while her schedule had her in the
  forest. A scheduled vendor trades at their counter, while there, awake.
  Measuring every vendor against its schedule found a shop that could never
  have opened honestly: Odran's counter was `tinker_caravan`, which no hour of
  his routine reaches -- he hawks off the cart tail in the square. A guard
  holds every shipped story to it.
- **An agent's choice was lost whenever the narrator wrote four.** The
  narrator's choices went first with a limit of four; a slot is reserved now.
- **Reputation had two writers and two clamps.** `economy.work` called
  `reputation.adjust` around `apply_effect` (rule 3), and the effect kind
  clamped to a global -100..100 while `adjust` used the faction's own bounds.
  One implementation now, reached only through `apply_effect`.
- **The director looped on promises it could not keep.** A deck that dealt
  nothing came due every turn, and a forced scene naming nothing logged a
  WARNING every turn forever.
- **One bad agent effect killed the whole turn.** `run_pipeline` re-raises a
  commit failure after rolling it back and nothing caught it. The negotiation
  is lost for that turn; the turn is not.
- **The objectives block named a tool the model cannot call**
  (`set_narrative_flag`) and listed flags already raised; its bare `except`
  hid quest bugs without a log line.
- **Money was always "g".** Currency is `trade.currency_format` per story --
  NEON CITY `₵`, THE LONG CON `$`. The sale receipt said "c".
- **The tone scorer rewarded the flagship's nouns**, and the negotiated-line
  instruction said "her words" of every agent.
- **A test that activated a story leaked it into the next file.** Nineteen
  files call `registry.activate`; most never undo it, and the suite passed only
  because alphabetical order ran flagship files first -- measured when a new
  file ending on NEON CITY failed 22 of `test_livelihood.py`'s 41 tests, each of
  which passes alone. An autouse fixture deactivates whatever a test changed,
  and only then (a blanket reset was measured once at 3m40s -> 6m35s).

### Added

- **The world moved** (`engine/game/moved.py`). A per-turn journal each system
  writes in its own words, rendered once as SINCE YOU LAST LOOKED: clock-beat
  and world-event `text:` (about fifteen authored lines that reached no
  narrator), clock rumours, promises broken, a veiled meter crossing a band,
  a faction band change, and gossip overheard in the player's own room. Marked
  when a prompt renders it and cleared once the narrator has written, so an
  evaluator retry sees the same lines. HAPPENING NOW prints the story's words,
  not `- briar_pulse at None (since day 1)`, and a forced scene no longer
  carries the fallback text *"The story owes you: D8_06_briar_threshold"*.
- **Story-declared world events.** An `events:` block in `world_schedules`:
  `on_day`, `every_days`/`first_day`, or a `when:` predicate. Fired from the
  day roll with no randomness, so they replay from the seed. Expiry runs on the
  day roll too. The flagship's procgen festival -- generated per seed, read by
  nothing -- now happens. Probabilistic events are NOT WIRED
  (`docs/GOVERNANCE.md`).

### Removed

- **The MEDIA governance phase**, `MediaGovernor`, `governance.media`, and the
  whole of `engine/media/interceptors.py`. The phase was built to replace a
  bypass and was then bypassed itself: the turn has always called
  `MediaPipeline.process_storyteller_turn` directly. Reached by tests alone,
  which the reachability gate does not see -- it sweeps skills and constants,
  not plain functions.
- **`npc_voices`, `mood` and `image_tag` from the turn schema.** Sampled every
  turn, read by nothing. The flagship's one `npc_voices` example was a copy of
  dialogue already in its narration.
- `engine/agents/turn_loop.py.bak`, `stack.wait_timeout_seconds`, an unused
  import, and an orphan comment from the removed layer -- deleted, not
  completed (rule 12). **`docs/AUTHORING.md` still told authors every template
  sets `governance.directives: [SafetyDirective, StorytellerMind]`**; the
  templates had been fixed and the sentence had not.

2016 passing, 3 skipped.

## [0.7.2] — 2026-09-23

### Changed

- **A rumour now finishes travelling inside a session.** v0.7.0 shipped the
  three-hop decay and the third form — "heard it going round" — almost never
  arrived. Measured over 40 runs of 80 tellings: a second hop in 37, a third in
  **12**. And raising `SPREAD_CHANCE` from 0.35 to 0.8 did not move it at all
  (9–13 of 40 across the whole sweep); it only made the same small number of
  tellings happen sooner. **The cast was the cap, not the dice.** Dedupe was
  keyed on the fact alone, so a listener who had heard something could never
  hear it again — and the flagship schedules five NPCs, which a fact saturates
  in about four tellings, leaving the third-hand version nowhere to go.

  Dedupe is keyed on the fact **and the hop** now: you may hear a story again
  if the version reaching you is further from its source than the one you hold.
  That is not a repeat — "someone was asking about the tinker", arriving after
  you were told who and when, is new information about how far the thing has
  travelled. Bounded three ways: strictly more degraded each time, `MAX_HOPS`
  overall, and `MAX_HEARD_PER_SUBJECT` on the record.

      third hop   12/40 -> 33/40 runs, median turn 38
      notes/80    7.6   -> 9.6 mean

  `SPREAD_CHANCE` is **unchanged at 0.35**. The sweep showed the dial was never
  the problem, and one thing changed at a time.

### Fixed

- **A raw NPC id could reach the narrator.** Gossip attributed a telling to
  `names.get(speaker) or speaker`, so an NPC the ledger had not named yet was
  written into the note as `npc_villager_3` — and these notes reach the prompt
  through `_dossier`, which means a prompt that can put that string on the
  player's screen. Same class as a choice rendering its own intent id (v0.6.2).
  The story's schedule name is used when it declares one, and "somebody"
  otherwise, which is safe and true: if nobody has named this person, nobody
  has named them. The fact TEXT is still carried verbatim — rewriting an
  authored fact would be a different and much worse bug.

## [0.7.1] — 2026-09-23

### Changed

- **THE LONG CON stopped selling mushrooms as cigarettes.** Its items and tables
  were the graph template's, and a veneer hid it: `economy.yaml` carried noir
  display names — `"Cigarettes, loose"`, `"A watch with the name filed off"` —
  over `hedge_berries` and `old_coin`. That `name:` key is **read by nothing**;
  `trade.py` takes every display name from `inventory.name_of(item_id)`, so the
  player browsing a 1940s fence was offered "Hedge Berries".
- **The goods are now levers, not groceries.** The story ships no
  `survival.yaml` — `rest_kinds()` is empty and nothing eats — so a registry of
  four food items was an economy with nothing to buy. Coin now buys the only two
  things this city sells: cigarettes hand around for `heat -4`, bonded rye left
  on a desk for `standing +6`, and somebody else's press pass for `standing +5`
  and `heat +7`, once a day. That is the counterplay the case lacked: every
  quest stage in `the_case/` adds heat and spends standing, and nothing spent
  the other way.
- **Work is work the city has.** The single job hauled sacks at a mill that does
  not exist here. It is nights on the weighbridge and the door at the Cadenza
  now, at locations with NPCs and hours. A job cannot move a meter —
  `economy.py` reads no `effects:` key — so the weighbridge pays partly in
  cigarettes and the *item* carries the effect. Wage into item into meter, with
  nothing invented in between.

### Fixed

- **The only vendor profile in the city described a man who is not in it.**
  `trade.yaml` declared `npc_miller`, "The Miller", who appears in no schedule,
  no quest and no stock table; `browse` answered *"Nobody trades here as
  npc_miller."* Meanwhile Georgie Pell, who has stock in `economy.yaml` and
  stands on the harbour road from 18:00, had no profile and traded on the global
  spread. `economy.yaml` and `trade.yaml` are both keyed on NPC ids and nothing
  made them agree.
- Two new tests hold that seam: a vendor profile must name an NPC the story
  **schedules**, and a vendor with stock must **have** a profile. Both were
  proved by putting `npc_miller` back and watching them fire.
- **`tests/test_livelihood_per_game.py` never ran against this story.** Its
  `GAMES` tuple held one entry, so a game declaring `paths.economy`,
  `paths.tables` and jobs was never driven through the file written to check
  exactly those. It holds two now, with foraging split out — THE LONG CON is a
  city with no ground to forage on.

### Removed

- `data/tables/forage.yaml` — 86 lines of leaf litter, hedge berries and
  seasonal yields in a story where no location carries a `forage` or `wild` tag,
  so the table could never fire, feeding a hunger mechanic the story does not
  have. Deleted rather than re-themed: scavenging could be written, but
  re-theming it would have produced content that still cannot run.

## [0.7.0] — 2026-09-20

### Added

- **Gossip travels, and gets further from its source as it goes.** A fact used
  to make exactly one hop — `spread` refuses when the listener already knows it,
  so a listener could never become a teller, and gossip was a star around the
  player rather than anything that moved. It can now pass onward, and each
  telling is worded for how far it has come:

      hop 1  heard from Maris: you asked about the tinker
      hop 2  heard from Corwin, who had it from Maris: they say you asked
             about the tinker
      hop 3  heard it going round: someone was asking about the tinker

  **The content never changes.** What decays is who vouches for it and how
  firmly, so a narrator can write somebody cagey about a source or
  overconfident about something they got third-hand — and the engine never
  records a falsehood a later turn might state as fact. A rumour allowed to go
  *wrong* would put claims in the ledger that the player can check against real
  state and catch out.
- `MAX_HOPS` is what makes onward telling safe to allow. Without a cap, letting
  a fact hop again turns the thing the module's own docstring insists must
  "feel like weather" into the broadcast network it says it must not be:
  everything reaches everybody, and the interesting state is the uneven one.
  `SPREAD_CHANCE` is untouched, so only one thing changed at a time.
- Nobody is told their own news. Once a rumour can travel more than one hop it
  can circle back — measured, and it read as "heard from Maris, who had it from
  Odran" sitting in *Odran's* own memory.

### Changed

- **The companion is held to its declared length.** `ASSISTANT_TURN_SCHEMA`
  exists to enforce the "1–3 sentences" rule — its own comment says prose alone
  "never reliably holds" it — and nothing ever passed it to a model; the v0.5.0
  audit found it as an unreferenced constant. It **cannot** be wired as written:
  a `response_format` forces the OpenAI-compatible transport, and the companion
  is on the native route because "156 of this call's 200 tokens went to
  REASONING and the reply was cut off mid-sentence" is measured at its call
  site. Wiring it would buy the cap and pay for it with a starvation somebody
  already fixed. The rule is enforced in code instead, at a sentence boundary —
  which a `maxLength` could never do, since a JSON string truncated at 240 stops
  mid-word. Its allowlist row now records a decision rather than debt.

### Notes

- **Measured, and not done:** flipping the flagship's companion to
  `pipeline: true`. The pipeline does engage with two participants — but the
  flagship declares **zero** negotiation rules, so every turn would fall through
  to the confidence fallback, which is a coin flip dressed as a rule. Its
  companion's persona is also written to react to *finished* prose, so its plans
  would be poorly grounded. The roster's own comment — "it leads no turns" — was
  right, and the audit suggestion that prompted this was not.

## [0.6.2] — 2026-09-20

### Fixed

- **Sophia had a painted portrait that had never once been shown.**
  `assistant_presence` resolved the companion's picture from `form` — the
  Assistant Mind's current face, one of The Clockwork Dark's five, defaulting to
  `"cat"`. A story whose companion is a named CHARACTER keys her portrait on her
  own id, so The Wicked Garden asked for a cat, got `""`, and drew its fallback
  wash over an unshown `portraits/sophia.jpg`. Resolved from the roster's
  declared character now, which covers the opening and resume frames too — the
  first frames a player sees. The flagship is unchanged: it declares no roster,
  so the lookup falls back to `form` exactly as before.

  Same disease `Companion.jsx` already documents for the `form` CAPTION —
  "the flagship's state leaking through a slot this story shares with it". The
  caption was fixed; nobody noticed the portrait had it too. Empty is a legal
  answer from a portrait lookup, which is why nothing ever failed.
- **A choice that echoes its own intent id is relabelled from the author's
  text.** Measured live on a 3B model: the Garden's choices rendered as
  `follow_the_scent`, `name_it_aloud`, `turn_away_hard` — the model had copied
  the intent enum's target ids into the display text, while the beats they came
  from carry authored prose and `legal_intents` had it all along. Showing the
  model's copy of an id while holding the author's sentence is the wrong way
  round for an engine whose premise is that it resolves and the model narrates.
  Only an exact id match; real writing is never second-guessed.
- **Schema field names leaked into the prose as tags.** Measured live and
  rendered on screen: `...this garden that is not yours.</narration>}<action>You
  examine the merchant's stall.` This is the same failure
  `strip_embedded_envelope` exists for, in tag notation instead of JSON — so
  that guard could not see it, and `strip_trailing_debris` leaves it because the
  tail is full of words. `strip_scaffold_tags` anchors on the turn schema's own
  key names rather than on "looks like a tag", because a story is allowed to
  contain `<`.
- **The build-freshness guard could not be satisfied.** Bumping
  `ui/package.json` in step with `pyproject.toml` put
  `test_the_committed_build_is_not_behind_its_source` into a state no rebuild
  could clear: the version string is not bundled, so `npm run build` produces
  byte-identical output, dist is never dirty, never committed, and the file
  stays permanently "ahead". A guard that cannot be satisfied is one somebody
  deletes. A version-only change is ignored now; a dependency change still
  fails exactly as before. Its `_git` helper also decoded git's output with the
  locale encoding — cp1252 here — which was harmless while it read only ASCII
  path names and turned `package.json`'s em-dash into U+FFFD the moment it read
  a file.

### Notes

- The Garden's scene art works everywhere it exists — 19 scene plates, all
  serving. `mortal_threshold` is one of six locations the manifest lists as
  having no plate *on purpose*, and it is both the entry location and where the
  10-card prologue plays out, so a new player sees no scene art until the
  prologue ends. That is content, not code, and it is the single most visible
  art gap in the repo.

## [0.6.1] — 2026-09-20

### Fixed

- **A model with no reasoning knob silenced an agent, and a two-agent story ran
  on one.** The starvation net switches to the native transport and sends
  `reasoning="off"` — and not every model accepts the parameter at all:

      Model 'lfm2.5-vl-3b-uncensored.gguf@q8_0' does not expose reasoning
      configuration.   (type=invalid_request, param=reasoning)

  Measured against the live server: **30 of 42 local LLMs publish no `reasoning`
  block**, so the net was guaranteed to fail for most of them. The 400 became an
  exception, the planner logged "No plan, treating as silent", and The Wicked
  Garden negotiated with one agent instead of two. Nothing failed anywhere.
- **Root cause was in the parser, two layers up.** `registry._capabilities`
  flattened the whole `capabilities.reasoning` block to its `default` string, so
  "exposes no reasoning at all" and "exposes it, defaulting to off" both arrived
  downstream as `""`. The fact needed to avoid the 400 was in a payload the
  engine already fetched, and was parsed away. `ModelInfo` now carries
  `reasoning_configurable` and the server's own `allowed_options`.
- `native.reasoning_for` omits the key for a model that cannot take it, and
  refuses a value outside `allowed_options` — gemma publishes `["off","on"]`, so
  `"low"` is a legal native level and an illegal value for that model. An
  unknown model is unchanged: an empty registry means the server was
  unreachable, and quietly dropping the parameter there would make a network
  outage look like a capability decision.
- **The retry now buys room instead of asking for less.** `wire_cap` returns the
  content budget *unchanged* when reasoning is off, so even without the 400 the
  second attempt would have carried 320 tokens where the attempt that starved
  carried 3,520. For a model that thinks whatever you ask it, the retry now
  sizes its ceiling from what the model *measurably just spent* thinking plus
  the full content budget — no magic multiplier. With no measurement it stands
  down rather than spend a player's turn on a coin flip.
- `ModelRegistry.cached` looks a model up without touching the network, because
  a lookup while building a request body must not put discovery inside the
  request it is about to send.

Verified live, not only against fixtures: the same Garden turn that previously
logged the 400 now logs `Planned (agent=gm)`, `Planned (agent=sophia)` and
`Turn negotiated (lead=gm, agents=2, resolutions=1)`.

## [0.6.0] — 2026-09-20

### Added

- **The narrator is told what the other side gave up.** `Resolution` exists to
  record "the companion wanted to interrupt and the world won", and its own
  docstring says that without it "the only evidence is prose that reads slightly
  differently" — but `narration_block` sent lead, beats, the speaker's verbatim
  line, receipts and the blocked flag, and never the resolutions. The prose
  could not read differently because it was never told. It now receives what
  yielded, to whom, and the reason the *author* wrote for that rule, with an
  instruction to SHOW it rather than report it. Only resolutions with a loser:
  the confidence fallback records a winner and nobody yielding, and dressing
  that as a concession would have the narrator dramatise a sacrifice that did
  not happen.
- **A margin mark on a contested turn** (`NarrativeLog.jsx`). State, not words —
  no engine-authored sentence goes into the log beside the narrator's prose.
  The store keeps `negotiation` per turn, deliberately not sticky, unlike
  `ending`.
- **A negotiation panel for the author** (`ui/src/core/parts/NegotiationPanel.jsx`),
  rendered by `Play.jsx` and silent unless a pipeline ran — so the flagship and
  any single-participant story never see it. Collapsed by default; prints lead,
  who yielded to whom, the rule's authored reason, beats, refusals and vetoes.
  Closes the `negotiation` half of a **NOT WIRED** row in `docs/GOVERNANCE.md`.

### Fixed

- **Every image in The Wicked Garden was invisible, and always had been.** Core
  ships `.paint__img { opacity: 0 }` and raises it on `.is-loaded`; the Garden's
  stage plate and Sophia's portrait both rendered bare `className="paint__img"`,
  so the art fetched, decoded, occupied its frame and never appeared. Nothing
  failed — the request was 200, `complete` was true, `naturalWidth` was 640 — so
  it read as "this story ships no art" rather than as a defect. Found by looking
  at the running game, which is the only thing that could have found it.
  `ui/tests/plugin-contract.test.js` now fails on any `<img class="paint__img">`
  with no way to raise it, across core and every plugin.

### Known gaps

- The companion column does **not** show a posture when the companion is the
  agent that gave way. `assistant_presence` ships no agent id, so the client
  cannot tell whether the yielding agent is the one in its column, and guessing
  was the wrong answer. Recorded as its own NOT WIRED row with what wiring it
  would take.

## [0.5.1] — 2026-09-20

### Fixed

- **The removed layer was still named in config, in four shipped games and in
  all three story templates.** `governance.directives` listed `SafetyDirective`
  and `governance.commit` listed `SafetyCeiling`, so every governance build
  logged two "Unknown interceptor named in config, skipping" warnings and every
  freshly scaffolded story inherited a dead name — the same
  templates-teach-the-bug shape that CLAUDE.md already records for the intent
  loop. Worse, `tests/test_story_surface.py` *asserted* the stale name was
  present, which locked it in: the suite would have failed if anyone removed it.
  Found from a log line while working on something else, because the earlier
  sweeps grepped for module paths and this was a bare string in YAML.
- `governance.commit` is now `[]`, which is what `_DEFAULT_CHAINS` in
  `engine/agents/governance.py` has always shipped. Config and code had
  disagreed about whether a pre-commit veto hook ships by default; the code was
  right, and says why.
- `tests/test_governance_commit.py`'s docstring claimed "the configured chain
  contains the ceiling", which stopped being true at v0.3.0.

## [0.5.0] — 2026-09-20

### Added

- **Sealed contracts reach the narrator.** `engine/game/threads.py` is 1,220
  lines and three shipped stories declare a `threads.yaml`; a sealed thread
  gates choices, charges its terms and comes due on a named day — and no
  narrator had ever been told one existed. `threads.summary` has said in its own
  docstring since it was written that it is "trimmed for a prompt block or a UI
  list"; only the UI half was built. There is now a `CONTRACTS YOU ARE UNDER`
  block, carrying terms, counterparty, seal, due day and cutters, and
  withholding the effect hooks exactly as `summary` already did.
- **Clocks reach the GM line.** `engine/game/clocks.py` is 844 lines and the
  narrator got none of it. A `WHAT IS CLOSING IN` block now reports each clock
  qualitatively, banded through the same `Spec.band` the client projects a
  veiled meter with, so GM and player never hold two vocabularies for one
  number. THE LONG CON's `the_frame` can now be felt filling instead of dealing
  an authored interrogation out of a clear sky.
- **The clock labels nobody read.** Every shipped clock table carries a
  `label:` — "How this ends up being your fault", "The roots are counting",
  "Winter, being patient" — eight across five games, and no engine module had
  ever loaded one. They are GM-facing by construction, saying what a clock
  *means*, which is what a narrator needs and what the player-facing label in
  `state.yaml` deliberately does not say. They are what the new block prints.
- **Pressure has a direction.** `story_pressure` reached the prompt as one of
  three words, so a story easing off after a crisis and a story winding toward
  one read identically. The GM line now says "restless, and rising" or "and
  easing". `story_pressure_prev` is written in exactly one place —
  `clock.advance_time`, the single writer of world time — because
  `update_story_pressure` runs several times per turn and a naive "remember the
  last value" would compare a turn against itself and report every story as
  steady.
- **`tests/test_reachability.py` now walks constants, not just calls.** v0.3.0
  left two orphans behind and nothing noticed: `rng.SAFETY_REDIRECT`, a seeded
  stream whose own comment said it was consumed by a module that no longer
  existed, and `storyteller.FADE_FALLBACK_LINE`, a canned line citing a deleted
  contract document. Neither failed anything, and both read to the next session
  exactly like a feature somebody had not finished wiring. The sweep is
  restricted to UPPER_CASE names on purpose — seven results instead of
  seventy-four — and carries a positive control plus an allowlist that rots if
  a row becomes read or disappears.

### Removed

- The last four remnants of the removed prompt layer: a 31-line comment block in
  `games/clockwork-dark/game.yaml` teaching the full `safety:` manifest syntax
  and pointing at three deleted files, an `## Intensity` section in
  `games/dev-story/README.md`, and the two orphan constants above. The manifest
  block was the sharpest of them — an authoring tutorial for a system that does
  not exist, sitting in a shipped game.
- Dead RNG streams `LOOT`, `LABOUR` and `TRADE`, and `ledger.SOURCE_PLAYER`.
  Nothing drew or wrote any of them. Work and trade price their outcomes from
  the tables outright, which is *why* neither has a stream; the comment claiming
  otherwise now says so.

### Fixed

- `CLAUDE.md`'s status line read "2020 passing, 18 skipped in 3m38s" for a month
  after v0.3.0 deleted three test files, in the same sentence that warns the
  reader it has been stale before. Measured: **1867 passing, 4 skipped**, and
  **127 client tests** against two different wrong numbers (126 and 95) in the
  same document.

## [0.4.0] — 2026-09-20

### Added

- **Accept one draft.** `POST /api/studio/draft/accept` promotes a single draft
  entry into the live tree, with `Author.promote_one` doing the placement so the
  studio and `scripts/author.py --promote` cannot disagree about where a file
  lands. `--promote` is all-or-nothing and refuses while any error stands; the
  review queue exists precisely so an author can keep one and discard the rest.
- **The notice board reaches the browser.** `GET /api/notices` has been served
  since Overhaul III and no player could see it. `Notices.jsx` is a
  clockwork-dark overlay (`n`) with its own pinned-paper mark. Closes a
  **NOT WIRED** row in `docs/GOVERNANCE.md`.
- **Challenge and scene framing.** `BeatFrame.jsx` draws the "step 2 of 4" /
  "card 3 of 7" line, so a gauntlet reads as one thing rather than four
  unrelated turns. It invents nothing: titles, cursors and lengths all come off
  the turn payload. The full panel remains unbuilt and stays in the table.
- **THE LONG CON gets its own ledger** and theme, instead of wearing the graph
  template's right column.

### Changed

- **Onboarding is remembered per story, not globally.** The flag was one key for
  the whole install, so meeting the flagship taught the client that you had met
  NEON CITY too, and four of the five games never introduced themselves.
- **NEON CITY says `NO FEED`** where a plate is missing, rather than rendering a
  gap. The game ships zero art plates against 75 subjects; this makes the
  absence read as the canon's own dead screen instead of as a broken image.
- **Core copy stopped speaking for the flagship.** The default player name was
  `Traveler` and the seed hint said "Same seed, same village" — one story's
  nouns in the engine's own neutral client. Now `You` and "same world".

### Fixed

- `engine/studio/api.py` inserted `scripts/` into `sys.path` inside its request
  handlers, so every scaffold and every accept pushed another copy of the same
  string onto a process-wide list that nothing popped. Both call sites now go
  through one idempotent `_script_module`.

## [0.3.1] — 2026-08-15

### Added

- The engine-scope rule in `CLAUDE.md` (rule 12), so that a later session
  finding the absence undocumented does not reintroduce what 0.3.0 removed.

## [0.3.0] — 2026-08-15

### Removed

- **Prompt composition is story-owned.** The engine no longer injects register
  or content-tier directives into the storyteller prompt or the story-drafting
  prompt. The package, config block, per-game blocks, settings dial and client
  card that carried them are gone — 40 files, 5,207 deletions. Register is set
  by `games/<slug>/prompts/storyteller.md` and by the model the owner has
  loaded, which is not the engine's business.

The governance commit chain keeps its veto: a hook can still block a turn, and
nothing is written when one does.

## [0.2.0] — 2026-08-15

Reconstructed from `git log`; see those commits for detail.

- **Overhaul III — reachability.** Three subsystems and eleven registered skills
  had no production caller: the deck system (so the Wicked Garden could not be
  finished by playing it), `clocks.forced_scenes`, `set_pieces` and `threads`.
  All wired, with `tests/test_reachability.py` walking the engine's own call
  graph so it stays that way. The suite dropped from 15m32s to a third of that
  once four paths that were reaching a live LM Studio from tests were closed.
- **THE LONG CON** — the first hybrid: a full graph city that also declares
  decks and a clock.
- **A studio** — author a story without a terminal.

## [0.1.0] — 2026-06-20 … 2026-08-14

Reconstructed from `git log`; see those commits for detail.

The engine and the first games: deterministic core (single writers for time and
state, seeded RNG streams), the two-agent turn, the multi-agent
plan → negotiate → govern → commit pipeline, quests, economy, survival,
encounters, endings and epilogues, the React client with per-story plugins,
and five shipped games.

[Unreleased]: https://github.com/nihilistau/clockwork-dark/compare/v0.15.0...HEAD
[0.15.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.14.1...v0.15.0
[0.14.1]: https://github.com/nihilistau/clockwork-dark/compare/v0.14.0...v0.14.1
[0.14.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/nihilistau/clockwork-dark/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.7.2...v0.8.0
[0.7.2]: https://github.com/nihilistau/clockwork-dark/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/nihilistau/clockwork-dark/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.6.2...v0.7.0
[0.6.2]: https://github.com/nihilistau/clockwork-dark/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/nihilistau/clockwork-dark/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/nihilistau/clockwork-dark/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/nihilistau/clockwork-dark/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/nihilistau/clockwork-dark/compare/v0.2.0...v0.3.0
