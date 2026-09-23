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

[Unreleased]: https://github.com/nihilistau/clockwork-dark/compare/v0.7.2...HEAD
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
