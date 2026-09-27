# CLAUDE.md — The Clockwork Dark

@AGENTS.md

Everything above is imported from [AGENTS.md](AGENTS.md): the start-here reading
list, the twelve critical rules, the working conventions, verification and the
canon ids. They live there once, tool-neutral, so no second copy can drift.
**Change a rule in AGENTS.md, never here.** This file carries only what changes
release to release.

## Status

**v0.16.0** is the current release (CHANGELOG.md has every release since 0.4.0;
each story's own changes are in `games/<slug>/CHANGELOG.md`).

**3405 passing, 4 skipped in 19m27s** (v0.16.0, measured in a checkout
holding the gitignored `Design_files/`, which runs the Design_files-only
Garden test; a fresh worktree skips it, so 3404 pass and 5 skip there), no
expected failures (measured 2026-09-27, v0.16.0 release; one skip is the
stamina soft-lock test,
which covers only stories with no rest verb and now skips HUE & CRY too), plus **144 client tests** under `ui/tests/`
(`npm test --prefix ui`; `vitest` is a devDependency, so
`npm install --prefix ui` once first). Re-measure and restate these at every
release rather than trusting this line -- it has been stale before, in the
very sentence that warned about it.

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
accusation; still playable to its one shipped ending, `honest_after_all`,
with Act III and the eight endings landing in v0.17.0). Pick one with
`launcher.py --game <slug>`.

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
| v0.17.0 | Act III + eight endings: the Hanging Fair event and fair-day deck, the jailbreak, The Rope via `death.yaml`, per-ending tests | next |
| v0.18.0 | `simulate.py`'s thief policy -- and re-measure welshing's cost for a burglar shut out of both fences (owner decision in v0.15) | queued |
| v0.19.0 | Model-server agnostic: LM Studio plus vLLM, the llama.cpp server, Ollama and other OpenAI-compatible backends | queued |
| v0.20.0 | Linux as a first-class platform, and a hosted/web-served mode: auth, per-user sessions and saves, a production server, Docker | queued |
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
- `mortal_threshold`, the Garden's entry location, has no plate on purpose (it
  hosts the ten-card prologue), so a new player sees no scene art until the
  prologue ends.
- The studio review queue can keep one draft but does not draft from the
  browser.
- `hue-and-cry` ships no `death.yaml` until v0.17.0 (The Rope ending): the
  watch_stop's fight can push hp to 0 with no respawn until then, and so can
  hunger -- the measured candle-dipper reaches 0 hp on 5% of seeds, and the
  careful pickpocket on 95%, in ten days (CHANGELOG [0.14.0]
  cost-of-living table; [0.15.0] "Where hp goes to 0"). A welsher on a
  fence's credit reaches it on 45% (Pell's advance) to 82.5% (Marrow's
  slate) of seeds in ten days, starving; the fences' collectors cost it
  under an hp a run, so they are a rare way there, not the usual one.
- One of HUE & CRY's seven factions -- the Temple of the Everflame -- is
  declared for Acts I–III and moved by nothing yet
  (`data/world/factions.yaml`'s header). The Margrave's household and the
  Silk Row houses are moved since v0.15 by a squeeze left uncollected.
- A generated premise's secret, carried out of a job, is HELD (the
  `secret_held:<premise>:<secret>` flag and a `secret` ledger fact) and opens
  no thread: only the four anchors' secrets name a blackmail (`thread:`).
  Nothing reads a generated secret yet (none of v0.16's three decks does);
  Act III (v0.17.0) may.
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
  wrong naming) -- not to a count; the levers if Act III's fair needs the
  reveal sooner are the hint's place in casing (`premises._ordered_ids`)
  and the trail's density (`clues.yaml` `trail`/`herrings`).
- `death.yaml` is loaded, and so validated, only at the moment of death
  (`encounter.load_death_rules`): a malformed one is a ValueError on the turn
  the player dies, not at story activation. `scripts/doctor.py` and the
  validator (`check_death_rules`) catch it before that; nothing in the
  running engine does.
- A job/death seam that lands with that `death.yaml`:
  `test_no_job_takes_the_thief_to_zero_hp` passes trivially, because no
  measured policy takes the roof (the one entry that hurts).
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
- The agenda clocks' beats set flags (`ardane_warrant_sworn`,
  `silas_splits_the_company`, `magpie_spree_full`, ...) that no scene reads
  yet (none of v0.16's decks does); Act III's (v0.17.0) will. (The reveal is no longer on this
  list: since v0.16 the Lantern House front desk's accusation sets
  `magpie_unmasked`; catching the thief in the act is not built.)
- Ardane's `takes_a_statement` move can only file her OWN report at a fixed
  deed (`pickpocket`): a move has no way to name the deed a witness actually
  saw, so it cannot upgrade that row directly -- it adds a second, lesser
  one instead.
- Agenda moves are never posted to the notice board, and no `fence {most:
  hot_goods}` selector exists (fences hold no stock to count) -- both rows in
  docs/GOVERNANCE.md's NOT WIRED table.
- The Magpie's Hoard (v0.15, `data/tables/collections.yaml`) sets
  `magpies_hoard_complete` when all six pieces are carried, and nothing reads
  that flag until v0.17.0's The Legend ending; until then completing it pays
  the Honest Company's +8 and the narrator's reward line, and nothing else.
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
- The reveal's and the alibi's flags are for endings that do not exist
  yet: `magpie_named_wrongly`, `wrongly_accused_<suspect>` and
  `alibi_proven` are read by nothing but the desk and interrogation decks'
  own gates, and `magpie_unmasked` by those and the GM line's mask
  (`agendas.yaml`, `spoilers.yaml`), until v0.17.0's endings. The
  interrogation's reserved `Q3_the_evidence` slot was released unfilled
  (the accusation lives at the front desk).
- The Lantern House front desk (`lantern_house_desk.yaml`) is a repeatable
  deck, re-armed only when its `when:` is seen false: a card that becomes
  eligible while the thief is already standing in the Lantern House (the
  captain coming on duty, say) waits until they walk out and back in
  (`director.rearm`).
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
- The Wicked Garden deals `day_09_finale` twice (pre-existing).
- Survival's hunger/death is not cut-invariant (pre-existing).
- Set pieces (`paths.challenges`) aren't checked by `doctor.py` or
  `validate_content.py` (pre-existing).
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
