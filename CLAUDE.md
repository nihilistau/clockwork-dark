# CLAUDE.md — The Clockwork Dark

@AGENTS.md

Everything above is imported from [AGENTS.md](AGENTS.md): the start-here reading
list, the twelve critical rules, the working conventions, verification and the
canon ids. They live there once, tool-neutral, so no second copy can drift.
**Change a rule in AGENTS.md, never here.** This file carries only what changes
release to release.

## Status

**v0.19.0** is the current release (CHANGELOG.md has every release since 0.4.0;
each story's own changes are in `games/<slug>/CHANGELOG.md`).

**4344 passing, 5 skipped in 33m21s** (v0.19.0, measured in a checkout
holding the gitignored `Design_files/`, which runs the Design_files-only
Garden test; a fresh worktree skips it, so 4343 pass and 6 skip there; the
time was taken after the final-review fixes, the earlier 33m50s with the
client tests, the doctor and `simulate.py` running beside it, and `tests/test_simulate_thief.py` adds about four minutes), no
expected failures (measured 2026-09-30, v0.19.0 release; one skip is the
stamina soft-lock test, which covers only stories with no rest verb and so
skips HUE & CRY too, and one is `tests/test_llm_live.py`, skipped unless
`CLOCKWORK_LIVE_LLM` names the configured model server), plus **145 client
tests** under `ui/tests/` (`npm test --prefix ui`; `vitest` is a
devDependency, so `npm install --prefix ui` once first). Re-measure and
restate these at every release rather than trusting this line -- it has
been stale before, in the very sentence that warned about it.

Six stories ship, and every one can be played to an ending
(`tests/test_finales.py`): `clockwork-dark` (the flagship), `wicked-garden`
(the deck exemplar), `neon-city` (NEON CITY: THE CROSSING), `the-long-con` (THE
LONG CON, the first graph/deck hybrid), `dev-story` (the annotated bench) and
`hue-and-cry` (HUE & CRY, now with jobs — `burgle` a house, stage by stage,
with flashbacks and a guild contract, on top of the Lantern Watch — and
agendas: a seed-chosen thief robs the city by night under the Magpie's name,
Captain Ardane hunts, Silas Crook works the guild, all of it authored and
deterministic, never a model plan — and, since v0.14, a living city: beds and
bread, scrounging, honest work, night streets, seven factions and the city's
lore, with its three secret places findable — and, since v0.15, a guild
economy: the `craft` verb at the Porters' Hall bench, the Magpie's Hoard,
four blackmail squeezes and the fences' credit — and, since v0.16, Acts I
and II: the barge opening's three choices made real, the Honest Company's
initiation deck, the Lantern House's interrogation deck on every arrest, the
Magpie's trail laid through the houses, and the front desk's alibi and
accusation — and, since v0.17, Act III: the Hanging Fair on Gallows Green
(days 10–12), the gallows for a thief held since before it, the jailbreak,
and `death.yaml` (hp 0 respawns in the Snuffs; dying held at the fair is The
Rope), with all eight endings, each through its own door and each earned:
Cleared, A Lantern, Honest After All, Partners, The Legend, Guildmaster, The
Dapper's City and The Rope, the fail-forward — and, since v0.18, burglary
pays (the owner's decision: the fences pay about half a hot haul's value)
and `scripts/simulate.py --game hue-and-cry` runs its thief policies.
HUE & CRY is finishable; its screens, art and live play are still to come). Pick one with
`launcher.py --game <slug>`.

Since v0.19.0 the engine is model-server agnostic (`engine/llm/`, the
`llm:` config block): LM Studio stays the default, and llama.cpp's
`llama-server`, Ollama, vLLM and any other OpenAI-compatible server can
narrate every story, each through its row of `engine/llm/providers.py`.
Which of those facts were verified live, and how to run each server, is
[docs/MODEL_SERVERS.md](docs/MODEL_SERVERS.md).

## In flight

**HUE & CRY**, approved 2026-09-23, re-cut per feature after v0.9.0 shipped so
nothing sits unpushed for weeks; re-cut again (owner, 2026-09-25) once the
four engine features shipped, so v1.0.0 no longer waits at the end of the
roadmap as one release -- it ships as its own run of point releases, tagged
only once the last of them lands:

| Release | What | State |
|---|---|---|
| v0.8 | The audit release: presence in every story, outcome-aware evaluator, the "world moved" journal, leaks, dead code | **shipped** |
| v0.9.0 | Premises, plus the HUE & CRY skeleton | **shipped** |
| v0.10.0 | The Law | **shipped** |
| v0.11.0 | Jobs & flashbacks | **shipped** |
| v0.12.0 | Agendas | **shipped** |
| v0.13.0 | Engine seams for HUE & CRY's finish: secret places, custody + jailbreak, forced/repeatable decks, a terminal death, the clarity word, `generate_art --game` | **shipped** |
| v0.14.0 | Living city: survival, forage + Rooftop Road's hidden paths, labour, boons, night encounters, factions, city lore | **shipped** |
| v0.15.0 | Guild economy: crafting, the Magpie's Hoard, blackmail and fence-credit threads, Brask's gate | **shipped** |
| v0.16.0 | Acts I–II: arcs, the opening, initiation deck, interrogation deck, the Magpie's trail, the reveal and the alibi beat | **shipped** |
| v0.17.0 | Act III + eight endings: the Hanging Fair event and fair-day deck, the jailbreak, The Rope via `death.yaml`, per-ending tests | **shipped** |
| v0.18.0 | `simulate.py`'s thief policy, agenda collisions measured, welshing's cost for a fencing burglar and the careful pickpocket's deaths measured; the fences made to pay (owner decision) and the lockpick money loop closed | **shipped** |
| v0.19.0 | Model-server agnostic: LM Studio plus vLLM, the llama.cpp server, Ollama and other OpenAI-compatible backends | **shipped** |
| v0.20.0 | Linux as a first-class platform, and a hosted/web-served mode: auth, per-user sessions and saves, a production server, Docker | next |
| v0.21.0 | UI/UX overhaul, together with HUE & CRY's screens: the wanted poster, job panel and casing board as generic engine panels, portraits | queued |
| v0.22.0 | The Clockwork Dark overhaul | queued |
| v0.23.0 | The Wicked Garden overhaul | queued |
| v0.24.0 | NEON CITY overhaul | queued |
| v0.25.0 | THE LONG CON overhaul | queued |
| v0.26.0 | Dev Story overhaul | queued |
| v1.0.0 | All six stories finished, each with its art and live play -- `hue-and-cry`'s being a thief mistaken for "the Magpie" in the candle-port of Tallowmere, eight endings, a ~55-plate Grok art pack -- tagged only once this lands | queued |

Re-cut once more by the owner on 2026-09-26: the platform releases (v0.19.0
backends, v0.20.0 Linux and hosting) land before v1.0.0, and the UI/UX
overhaul merges with what was HUE & CRY's own UI-plugin release into
v0.21.0, so the shared surfaces are built once, as engine panels.

Re-cut again by the owner on 2026-09-26 (during v0.16.0): after the UI/UX
overhaul, each of the other five stories gets the full HUE & CRY treatment,
one a release (v0.22.0–v0.26.0): a design spec, its story and characters,
the engine systems apt to it, every ending reachable and tested, measured
balance, reviews, UI screens and art. A large story may take two minors,
which shifts the later numbers. v1.0.0 now means all six stories finished,
with art and live play for each. The owner does not approve each
overhaul's design: write the spec, have it reviewed (opus), build it, and
keep going.

**The README is kept current at every release through v1.0.0** (owner
instruction, 2026-09-26): status, features and roadmap each release; new
screenshots after v0.21.0's UI overhaul; the backends (v0.19.0) and hosting
(v0.20.0) documented when they land.

Every change updates the docs it makes stale: the story's CHANGELOG/README,
the root CHANGELOG/README, this file and AGENTS.md (AGENTS.md "Docs move with
the change").

Spec: [docs/superpowers/specs/2026-09-23-hue-and-cry-design.md](docs/superpowers/specs/2026-09-23-hue-and-cry-design.md).
Plans live in `docs/superpowers/plans/`; each release is executed
subagent-driven, one fresh subagent per task with review between (v0.14.0's
last three tasks and its release were finished inline, at the owner's word).

## Deliberately deferred

Recorded rather than fixed, so nobody mistakes them for forgotten work:

- neon-city ships **zero** art plates against 75 subjects, its entry location
  included.
- The Wicked Garden's deck walker never reaches 7 of its 23 endings in 1000
  runs (E2b, E2c, E3a, E3b, E3c, E4d, E5a; 9 in 200), and deals every card
  (`scripts/simulate_decks.py --game wicked-garden`, measured 2026-09-26;
  this line said "11 unreachable, 4 orphan cards" before).
- The Garden's bargains work only as written: `bargain` strikes, `discharge`
  settles, falling due breaks. Its renegotiations, the knife's cut, the gift
  auto-thread (`accept_gift`) and two undeclared templates (`briar_witness`,
  `three_nights_or_truths`) are NOT WIRED (docs/GOVERNANCE.md); the v0.23.0
  Wicked Garden overhaul takes them up.
- `mortal_threshold`, the Garden's entry location, has no plate on purpose (it
  hosts the ten-card prologue), so a new player sees no scene art until the
  prologue ends.
- The studio review queue can keep one draft but does not draft from the
  browser.
- HUE & CRY's Temple of the Everflame is moved since v0.17 T6 (the heart
  taken off the palace steps, -10) and READ by nothing yet but the save and
  the `reputation` predicate (`data/world/factions.yaml`'s header): no
  ending, price or card asks the Temple's opinion.
- A generated premise's secret, carried out of a job, is HELD (the
  `secret_held:<premise>:<secret>` flag and a `secret` ledger fact) and opens
  no thread: only the four anchors' secrets name a blackmail (`thread:`).
  Nothing reads a generated secret: none of v0.16's decks does, and v0.17's
  endings read only an anchor's (Guildmaster, Mother Gannet's IOUs).
- `survival.sleep_until` looks only for a rest entry named `sleep_bed`, so in
  HUE & CRY (whose beds have their own names) it always sleeps rough.
- A HUE & CRY save from before v0.14 keeps the world it was generated with,
  so it never gains the rooftop and grating hidden paths; only the arrest
  reveal of the Undercroft reaches it.
- Likewise a HUE & CRY save from before v0.16 has no Magpie's trail: its
  premises carry no `clue`, so casing never hints and no job finds one
  (`engine/world/clues.py::row_for`; loads and plays, asserted).
- The Magpie's trail reads slowly, measured and left (v0.16 T8,
  `scripts/simulate_acts.py`): a house gives its clue up only on the LAST
  watch, so a clue costs ~3 houses cased to the end and a deliberate
  investigator carries out ~2.5 by day 12. 40% of such runs have not
  unmasked the Magpie by day 12, and a retry after a wrong naming almost
  never lands in time (1 run in 40). The evidence bar was set to the lead -- two
  clues that agree (agree, not necessarily true: two herrings can open a
  wrong naming) -- not to a count. v0.17's endings harness kept it against
  the fair (`scripts/simulate_endings.py`: Cleared open for 68-73% of
  investigators, locked on 27-29 of 40); the levers, should the reveal need
  to come sooner, are the hint's place in casing (`premises._ordered_ids`)
  and the trail's density (`clues.yaml` `trail`/`herrings`).
- The wanted-poster UI: the payload exists (`to_client_dict`'s `law` key,
  `clarity` included) and the narrator already speaks it in prose; no plugin
  renders it until v0.21.0's UI overhaul.
- The job panel UI: the payload exists (`to_client_dict`'s `job` key — house,
  stage, alarm, prep) and `prompts.job_block` already speaks the same facts
  in prose; no plugin renders it until v0.21.0's UI overhaul, same as the
  wanted-poster above.
- Hired hands (spec §4): explicitly optional there and not built. A job is
  walked solo, start to getaway.
- An engine quirk a job's own measurement ran into and left alone
  (`jobs.yaml`'s header, AUTHORING §3.12): the watch's delay counts whole
  in-game hours (`jobs.now_hour` floors), so a stage of fractional hours can
  bring it up to an hour late.
- Some agenda clock beats set flags no scene or ending reads yet:
  `ardane_warrant_sworn`, `ardane_doubles_the_watch`, `magpie_spree_full`
  and `magpie_emboldened` (clocks.yaml). `silas_splits_the_company` is read
  since v0.17 T6 (The Dapper's City, Guildmaster, the fair's F4). (The
  reveal is no longer on this list: since v0.16 the Lantern House front
  desk's accusation sets `magpie_unmasked`; catching the thief in the act is
  not built.)
- Ardane's `takes_a_statement` move can only file her OWN report at a fixed
  deed (`pickpocket`): a move has no way to name the deed a witness actually
  saw, so it cannot upgrade that row directly -- it adds a second, lesser
  one instead.
- Agenda moves are never posted to the notice board, and no `fence {most:
  hot_goods}` selector exists (fences hold no stock to count) -- both rows in
  docs/GOVERNANCE.md's NOT WIRED table.
- The Magpie's Hoard's `magpies_hoard_complete` is read since v0.17 T6 only
  by The Legend's closeness `score` and its Seal beat's text
  (`data/rules/endings.yaml`): it opens no door and gates no ending, so a
  thief who carries the Hoard but never lifts the heart gets the Company's
  +8 and the reward line, and nothing else.
- The fences' credit (v0.15, `pell_advance`, `marrow_slate`) is repaid in
  coin, not in goods: nothing in the condition grammar can say "carrying hot
  goods worth V" and no effect can hand over unnamed goods, so the debt is
  counted in crowns (threads.yaml's header). Selling the fence the goods is
  how a thief raises it.
- A craft roll's `crit_failure` pays the recipe's full output
  (`engine/skills/builtin/mechanics.py::_craft_yield` reads only `failure`
  as a failed batch; pre-existing, found in v0.15's review). Latent: no
  shipped story's `skills.yaml` degree table has a `crit_failure` row, so
  a story that adds one would pay a fumbled batch in full.
- A recipe that goes illegal between the menu and its execution (the station
  left, an input spent) gets the dispatcher's generic "not a legal craft
  target" refusal (`engine/agents/tool_dispatcher.py`), which lists raw
  recipe ids, rather than `_craft_refusal`'s own reason. Still a refusal
  that reaches the prose (rule 1), only a less specific one.
- A `spoilers.yaml` row's `location:` naming a place that is not secret (no
  hidden path, known from the start) lifts the row on turn one, so it masks
  nothing; `check_spoilers` (`engine/games/validation.py`) refuses an
  unknown place but gives no warning for a known, non-secret one.
- Every intent verb shows at most eight options (`intents._MAX_OPTIONS`).
  `buy` cuts stock in id order and `sell` in inventory order, so a counter
  with more than eight rows, or a pack with more than eight saleable
  things, hides the rest. HUE & CRY's counters are held to eight by
  `test_every_counter_offers_all_of_its_stock`; nothing guards other
  stories, the validator gives no advisory, and a thief carrying bench
  makings can crowd loot out of Marrow's `sell` list.
- Some of the reveal's and the alibi's flags still wait for endings:
  `wrongly_accused_<suspect>` and `alibi_proven` are read by nothing but the
  desk, interrogation and (since v0.17 T6) confrontation decks' own gates. (Since v0.17 T5 Cleared and A
  Lantern read `magpie_unmasked`, and Cleared `magpie_named_wrongly`.) The
  interrogation's reserved `Q3_the_evidence` slot was released unfilled
  (the accusation lives at the front desk).
- The Lantern House front desk (`lantern_house_desk.yaml`) is a repeatable
  deck, re-armed only when its `when:` is seen false: a card that becomes
  eligible while the thief is already standing in the Lantern House (the
  captain coming on duty, say, or A Lantern's badge right after a right
  naming at the same desk) waits until they walk out and back in
  (`director.rearm`).
- HUE & CRY's Act III arc, D4 (Cleared after the fair, v0.17 T5),
  Guildmaster's `the_fair_has_come` and Partners' `the_last_job` (v0.17 T8
  fix round 1) read `event_seen: hanging_fair`, which the quests pass
  records only at a turn that ends while the fair is on. A single action
  that began before day 10 and ended after day 12 would miss it; none exists today (the longest, a
  served sentence, is stopped by the gallows at nine on day 12).
- `clues_favour {excluding: [...]}` accepts ids that are not candidates of
  the role and ignores them, and `clues.yaml`'s `fresh_flag` accepts any
  flag name but a `clue_found:` one (`engine/world/clues.py`); neither is
  cross-checked against the story.
- The casing board's `of` count (`premises` casing receipt, `"of"`) is one
  higher on a house holding a clue, as it is on one holding a secret: it
  shows that a house holds something more, never whose (accepted in v0.16
  T6's review).
- A bed's `requires`/`cost`/`fallback`/`refusals` (a `survival.yaml` rest
  entry) and an arc's `narrate:` are read at run time and checked by
  neither `validate_content.py` nor `doctor.py`: a misspelt fallback or a
  malformed refusal row is skipped, and `narrate` is read truthily.
- Every story's opening payload now carries `frame: "opening"`
  (`default_state.opening`, the authored-choice gate): its turns are
  unchanged, but the opening payload is not byte-identical to v0.15's.
- `scripts/simulate_decks.py` builds a bare `GameState`, so its walks start
  on the flagship's phantom `quiet_life` arc, not the story's default arcs
  (`quests.seed_default_arcs` runs only in `procgen.new_game_state`).
  Judged harmless in v0.16 T1's review.
- HUE & CRY's careful pickpocket still starves, by the owner's v0.14
  decision (deliberate pressure, not tuned). Measured in v0.18 T3 at 40
  seeds x 14 days (`simulate.py --game hue-and-cry --policy living`): it
  dies 2.90 times a run, and every death is hunger -- none in the street,
  the cells or at the fair -- at 05:00 in bed or at 21:00 waiting for the
  night's purse, first on day 6.2, never before day 5. It keeps 4.33 of 14
  days. The fences' new pay (below) barely reaches it: its marks' goods
  are cheap, and it banks the extra coin rather than eating it. A careful thief who takes a porter's shift when hungry
  (`careful_porter`) keeps 11.9 (the honest porter 13.1) and dies once in
  40 runs, so a living exists for one who adapts. Measured and kept.
- Welshing on a fence's credit still nets a purses-only pickpocket kept
  days: +3.1 on Pell's line and +1.2 on Marrow's over 10 days, unchanged
  by the fences' new pay. The owner accepted that in v0.15 because the cost
  falls on a burglar. v0.18 T3 measured it there, after the fences were
  made to pay (v0.18 T3 fix round 1, `data/tables/trade.yaml`: a hot haul
  now fetches about 0.53 of its value at Pell's and 0.63 at Marrow's, not
  0.25 and 0.28). Over 14 days the fencing burglar who welshes:
  - keeps fewer days (-0.62, -0.60);
  - dies 0.7 more a run;
  - ends 9.5-11 crowns poorer;
  - fences about 30 crowns less, because neither fence buys again.

  Over 10 days the advance still buys it +0.4-0.5 kept days. The credit is
  unchanged (CHANGELOG [0.18.0]).
- The fencing burglar still dies 0.7 times a run, all hunger, while
  keeping 7.25 of 14 days (the careful pickpocket 4.33, the porter 13.05)
  and ending with 13 crowns on average. Its death log (gold and place,
  v0.18 T3 fix round 2) says why: 17 of its 28 deaths over 40 runs came
  with no coin in hand, and 17 came at 04:00-06:00 in its Snuffs bed
  before the quay's breakfast. The 11 with coin held 1-12 crowns, 9 of
  them in that same pre-dawn bed, when its two carried meals (`STOCK`,
  every labour policy's rule) were gone and no counter was open. So it
  mostly starves on the lean nights between hauls. Recorded, no policy
  changed.
- A fence pays slightly more than an honest counter for a CLEAN thing:
  Pell 0.75 and Marrow 0.7 of value, against Dock Mag's and the city's 0.5.
  The engine has one sell spread per vendor and no separate clean rate,
  and v0.18 T3 raised the fences' spreads so that stolen goods pay
  (`data/tables/trade.yaml`). It is at most a crown more on a scrounged
  find, and no policy exploits it.
- A death in the cells during HUE & CRY's Hanging Fair is The Rope, whatever
  took hp to 0. The hanging itself has a scene since v0.17 T3 (the gallows
  deck, `data/scenes/the_gallows.yaml`, dealt at nine on the fair's last
  morning to a thief held since before it), but hunger inside a stretch of
  hours still gives that turn's prose no death receipt (a card beat's death
  does get one, v0.17 T1), so a thief who starves in the cell goes straight
  to the ending module's beats (AUTHORING §3.5). Narrowed, not closed: a
  prisoner serving a sentence is fed, so only one who sat unfed in the cell
  reaches it; flagged in `death.yaml`'s header.
- The bounders still CLAMP rather than reject (right for a model's output
  mid-turn): text past its cap and an outcome's effects past four are cut
  at load. Authored text has its own cap (`spec.MAX_AUTHORED_TEXT`, 1500,
  v0.17 T8 fix round 3; model text keeps `MAX_TEXT`, 400). Every cut is
  recorded in the bounder's adjustments and
  `validation.check_truncated_content` reports it as an ERROR for decks
  (card title and text, beats, outcomes), ending modules, thread templates,
  opening choices and set-pieces. Not covered: quest, encounter, epilogue
  and lore text, which pass through no bounder.
- A thief who names the Magpie to the captain (`magpie_unmasked`) is never
  dealt HUE & CRY's `F4_silas_makes_his_move` (it is The Dapper's City's
  door, and that ending shuts on the naming), so cannot stand against Silas
  at the fair either: if Silas's rise has won, Guildmaster stays shut for
  that thief (v0.17 T6, `data/rules/endings.yaml`).
- A locked run is dealt no door -- but only POOL doors (`deck.eligible_cards`,
  v0.17 T6): a REQUIRED card that locks an ending is still dealt, because the
  Wicked Garden's recorded walk re-deals its required finale lock after the
  run is locked. HUE & CRY's `the_gallows` `G1_the_last_morning` is required
  and locks `the_rope`, so it could still be dealt to a locked run (its lock
  refused). And a deck whose `when:` reads an ending's eligibility (HUE &
  CRY's `porters_hall`, the desk's badge branch) still comes due after the
  lock and deals nothing (spent, "no cards were eligible"). Both reachable
  only by an API or harness caller that plays on past an ending.
- `validation.check_law_effects` checks a `report`'s deed, guise and
  jurisdiction, a `wanted` condition and a `committed_deed` only against a
  law file: in a story with no `paths.law` it checks none of them, though at
  runtime such a report is refused ("no watch to report to") and such a
  condition is false. Only the engine-only effects are reported there.
- The Wicked Garden deals `day_09_finale` twice (pre-existing).
- Survival's hunger/death is not cut-invariant (pre-existing).
- The legacy `lmstudio:` alias is removed in v0.21.0: until then each config
  layer's `lmstudio:` block (and `stack.services.lmstudio`) is read as
  `llm:` with a WARNING, and a `lmstudio.*` read is answered from `llm.*`
  (`engine/config.py::migrate_legacy_llm`, `_READ_ALIASES`).
- The `engine.lmstudio` shim is removed in v0.21.0, with the config alias
  above: since v0.19.0 the package is `engine/llm/` (`native.py` became
  `lmstudio_native.py`), and `engine/lmstudio/__init__.py` only aliases
  each old module path to the same `engine.llm` module object. Nothing in
  the repo uses it (`tests/test_llm_package_shim.py`).
- A Settings panel save rewrites `config/local.yaml` whole through
  `yaml.safe_dump` and drops its comments (pre-existing;
  `engine/api/settings.py::apply_settings`). Keeping them needs a
  round-trip YAML parser. Since v0.19.0 a file that does not parse is
  refused rather than overwritten.
- Provider cells verified live: LM Studio's (the golden, recorded on
  v0.18.0, and `tests/test_llm_live.py` re-run against it at the v0.19.0
  release on `nvidia/nemotron-3-nano-4b`), llama-server's
  (v0.19.0 T8, `llama.cpp server b7966`, the Windows Vulkan build) and
  Ollama's (T8, `Ollama 0.34.4`, the portable Windows build), with their
  fixtures `recorded` -- bar `mcp_integrations` on both and Ollama's
  proxy pass-through `auth`, which no run had. Ollama's authored three-model
  discovery server, a `format`-ignoring probe answer, a proxy's 401 and a
  leading inline `<think>` stay `authored`: no live Ollama could give them
  (`PROVENANCE.yaml` notes say why).
- **vLLM live verification -- v0.20.0, Linux.** Its cells stay unverified
  (`verified=""`, † in docs/MODEL_SERVERS.md) and its fixtures `authored`
  (owner decision, 2026-09-29); a generic OpenAI-compatible server has no
  one server to verify against.
- Ollama's thinking models think BEFORE its `format` grammar binds (measured,
  T8): `qwen3:4b` spent 4881 tokens on the probe's one-line question and
  over 16,000 characters on a narration turn, starving the `big` profile's
  4400-token cap; the turn is recovered by `think: false` on the same
  `format`, which binds at once, so each such turn pays one wasted think.
  llama-server binds the grammar from the first token instead. Recorded, not
  tuned: `llm.profiles.big.reasoning: "off"` is the owner's lever
  (docs/MODEL_SERVERS.md § Ollama).
- `backend._retry_with_room` stands down on servers that report no
  reasoning-token count: llama-server (`usage` has no
  `completion_tokens_details`, b7966) and Ollama (`eval_count` is thinking
  and answer together, 0.34.4), measured in T8. A request that starved with
  the reasoning-off patch on stops after one request there: measured room
  needs a count, and the patch is the whole net.
- `llama-server --reasoning-format none` with a model whose template opens
  `<think>` in the prompt (Qwen3-4B-Thinking-2507) sends the thinking with
  no opening tag. A whole answer is split at the orphan `</think>`; a
  STREAM is not (holding it would show the player nothing until it ended),
  unless it carried an untrusted patch, so its thinking reaches the player.
  Documented as a flag not to run (docs/MODEL_SERVERS.md § Inline
  `<think>`); the default reasoning format splits it server-side.
- `llm.mcp` (Phase A) is LM Studio-only: on any other provider
  `llm.mcp.enabled` turns it OFF, with one ERROR and a doctor FAIL row
  (`engine/agents/mechanics.py::mechanics_enabled`). No engine-side tool
  loop exists (a GOVERNANCE NOT WIRED row), nor more than one model server
  per process (another).
- The golden's legacy scenario 23 differs from its v0.18 recording by one
  URL, sanctioned (v0.19.0 T6): v0.18 health-checked a fixed
  `localhost:1234` whatever `lmstudio.base_url` said, and the probe is now
  derived from `llm.base_url` (`tests/test_llm_golden_lmstudio.py`,
  `SANCTIONED_URL`). The shipped variant is byte-identical.
- Ollama's gpt-oss-style models (`think: "low" | "medium" | "high"`,
  ignoring `true`/`false`) are handled only when declared
  (`llm.declared_models.<id>.reasoning`, docs/MODEL_SERVERS.md § Ollama).
  **Not live-verified**: the owner declined the 14 GB `gpt-oss:20b`
  download in v0.19.0 T8, so the effort strings and
  `reasoning_off_trusted: false` stay as Ollama's docs describe them.
- An UNTRUSTED reasoning-off patch keeps the full cap (spec §5.2): on vLLM,
  llama-server and (since T8) Ollama, an `off` request for a model with no
  `declared_models` `reasoning` listing `off` sends the patch
  (`enable_thinking: false`, `think: false`) but still pays the reasoning
  budget, so turns are slower than they need be on a template that honours
  it, until the owner declares it. Chosen over starving every turn on one
  that does not. Measured on both servers (T8): a template that ignores it
  (Qwen3-4B-Thinking-2507, Ollama's own `qwen3:4b`) thinks anyway and the
  thinking arrives inside the answer, closed by an orphan `</think>`; the
  client moves it to the reasoning channel
  (`client.InlineThinkSplitter(forced_open=True)`, both transports), reads
  an unclosed answer cut at the cap as starved (unless the request carried
  a grammar and it starts as JSON: with no grammar a cut answer, prose or
  JSON, from a model that honoured the patch is lost, the accepted
  trade-off, T9), and warns once per model. Such a stream is held until it is
  decided only when the request carried no grammar (fix round 1): an
  ungrammared `off` stream to an undeclared model -- rung 3 narration under
  `reasoning: off` -- reaches the player all at once, not as it streams. A verified `reasoning_off` cell, or
  Ollama's `thinking` capability, no longer makes the patch trusted.
  Declaring `reasoning: ["on"]` for such a model is worse, not better
  (measured on Ollama: the probe starves, rung 3), and the docs say so.
- LM Studio gains the format block only under `structured_output: off`:
  its `json_object` rung and the turn after a failed `auto` probe carry no
  shape in the prompt, because the golden pins both requests to v0.18's
  bytes (scenarios 05 and 08; `backend.format_block_due`). Every other
  provider gets the block on rungs 2 and 3. The reply is conformed on
  every rung, LM Studio's included.
- A choice whose TEXT promises an action but whose reply carries no
  `intent` survives on every rung, rung 1 included: `intent` is optional
  in the turn schema, so "Follow the smoke toward Edgewood" can be offered
  with no mechanic behind it, and picking it moves nobody and refuses
  nothing -- the prose may then narrate a walk that did not happen.
  Pre-existing (v0.3.0's intent design), not introduced by v0.19.0's
  `conform`, which can only judge an intent that is there. A GOVERNANCE
  NOT WIRED row names the gap.
- llama-server's multi-model router mode (per-model `status` in
  `/v1/models`, `/props?model=`) is not supported: discovery treats every
  listed model as loaded and sizes them all from one `/props`
  (`engine/llm/discovery.py`; docs/MODEL_SERVERS.md). One server per
  model.
- LM Studio passes inline `<think>` through untouched when its reasoning
  split (the Developer setting that sends `reasoning_content`) is off, so an
  ungrammared compat reply (a tools request, or the native route
  unavailable) can carry the model's thinking -- and any `[IMAGE:]` tag
  written in it -- into the prose. Pre-existing since v0.18. The `lmstudio`
  row's `inline_think` stays `pass` (`engine/llm/providers.py`) because
  stripping would change LM Studio's parsed responses, which the golden
  pins; the owner's lever is LM Studio's reasoning-split setting
  (docs/MODEL_SERVERS.md § Inline `<think>`).
- HUE & CRY's choice list can briefly overlap the casing board in the
  browser (seen in v0.19.0 T9's browser play). UI scope: v0.21.0's UI
  overhaul.
- The NOT WIRED tables: [docs/GOVERNANCE.md](docs/GOVERNANCE.md),
  [docs/STATE.md](docs/STATE.md), [docs/AGENTS.md](docs/AGENTS.md).

## What the passes found

The full accounts -- measured, with the reasoning -- are in
[docs/DESIGN_REVIEW.md § Findings after the overhaul](docs/DESIGN_REVIEW.md#findings-after-the-overhaul).
The one-line index, because each is a mistake worth not repeating:

- **A test IS a caller.** Three subsystems and eleven skills had no production
  caller and full test coverage; `tests/test_reachability.py` now walks the
  engine's own call graph, constants included.
- **Reached is not narrated.** Threads, clocks and -- in four of five stories --
  presence itself were enforced and invisible to the prose.
- **Narrated is not agreed.** The evaluator asked whether a roll existed, never
  whether the prose matched it; `work` reported how a shift went under the key
  meaning whether it happened.
- **Tests were talking to LM Studio** while believing they were mocked; the
  conftest guard asserts at teardown because the pipeline's forgiveness
  swallowed a raise.
- **State outlived its test** twice: a module memo (`_DOOM_DECLARED`) and a story
  activation. Both have autouse fixtures now.
- **A veneer hid a template.** THE LONG CON sold "Hedge Berries" as cigarettes
  through a `name:` key nothing read.

## Machine notes (this workstation)

- The default pytest temp directory is unreadable here (WinError 5, environmental).
  Pass `--basetemp="C:/Users/Knack/AppData/Local/Temp/claude/ptmp"`.
- Heredocs and `python -c` strings lose backticks to shell command
  substitution; write commit messages and patch scripts to a file first.
