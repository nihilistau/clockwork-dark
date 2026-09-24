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

[Unreleased]: https://github.com/nihilistau/clockwork-dark/compare/v0.12.0...HEAD
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
