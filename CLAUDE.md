# CLAUDE.md — The Clockwork Dark

@AGENTS.md

Everything above is imported from [AGENTS.md](AGENTS.md): the start-here reading
list, the twelve critical rules, the working conventions, verification and the
canon ids. They live there once, tool-neutral, so no second copy can drift.
**Change a rule in AGENTS.md, never here.** This file carries only what changes
release to release.

## Status

**v0.14.1** is the current release (CHANGELOG.md has every release since 0.4.0); it is v0.14.0 plus the rewritten README.

**3030 passing, 4 skipped in 13m15s**, no expected failures (measured
2026-09-26, v0.14.0 release; the fourth skip is the stamina soft-lock test,
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
lore, with its three secret places findable; still playable to its one
shipped ending, `honest_after_all`, with the rest of its content landing
across v0.15.0–v1.0.0). Pick one with `launcher.py --game <slug>`.

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
| v0.15.0 | Guild economy: crafting, the Magpie's Hoard, blackmail and fence-credit threads, Brask's gate | next |
| v0.16.0 | Acts I–II: arcs, initiation deck, interrogation deck, the Magpie reveal, the alibi beat | queued |
| v0.17.0 | Act III + eight endings: the Hanging Fair event and fair-day deck, the jailbreak, The Rope via `death.yaml`, per-ending tests | queued |
| v0.18.0 | `simulate.py`'s thief policy | queued |
| v0.19.0 | The HUE & CRY UI plugin: wanted poster, casing board, job panel, portraits | queued |
| v1.0.0 | `hue-and-cry` finished: a thief mistaken for "the Magpie" in the candle-port of Tallowmere, eight endings, bespoke UI plugin, ~55-plate Grok art pack, live-played -- tagged only once this lands | queued |

Spec: [docs/superpowers/specs/2026-09-23-hue-and-cry-design.md](docs/superpowers/specs/2026-09-23-hue-and-cry-design.md).
Plans live in `docs/superpowers/plans/`; each release is executed
subagent-driven, one fresh subagent per task with review between (v0.14.0's
last three tasks and its release were finished inline, at the owner's word).

## Deliberately deferred

Recorded rather than fixed, so nobody mistakes them for forgotten work:

- neon-city ships **zero** art plates against 75 subjects, its entry location
  included.
- The Wicked Garden has 11 of 23 endings unreachable and 4 orphan cards.
- `mortal_threshold`, the Garden's entry location, has no plate on purpose (it
  hosts the ten-card prologue), so a new player sees no scene art until the
  prologue ends.
- The studio review queue can keep one draft but does not draft from the
  browser.
- `hue-and-cry` ships no `death.yaml` until v0.17.0 (The Rope ending): the
  watch_stop's fight can push hp to 0 with no respawn until then, and so can
  hunger -- the measured candle-dipper and careful pickpocket reach 0 hp on
  some seeds (CHANGELOG [0.14.0] cost-of-living table).
- Three of HUE & CRY's seven factions -- the Temple of the Everflame, the
  Margrave's household and the Silk Row houses -- are declared for Acts I–III
  and moved by nothing yet (`data/world/factions.yaml`'s header).
- `survival.sleep_until` looks only for a rest entry named `sleep_bed`, so in
  HUE & CRY (whose beds have their own names) it always sleeps rough.
- A HUE & CRY save from before v0.14 keeps the world it was generated with,
  so it never gains the rooftop and grating hidden paths; only the arrest
  reveal of the Undercroft reaches it.
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
  renders it until v0.19.0's bespoke UI.
- Sergeant Brask's bribe (`brask_bribe`) can be struck with a clean record —
  the thread's `requires` gates on standing at his desk, not on having
  anything to bribe him about — and quashes nothing when there is nothing
  filed to quash.
- The job panel UI: the payload exists (`to_client_dict`'s `job` key — house,
  stage, alarm, prep) and `prompts.job_block` already speaks the same facts
  in prose; no plugin renders it until v0.19.0's bespoke UI, same as the
  wanted-poster above.
- Hired hands (spec §4): explicitly optional there and not built. A job is
  walked solo, start to getaway.
- An engine quirk a job's own measurement ran into and left alone
  (`jobs.yaml`'s header, AUTHORING §3.12): the watch's delay counts whole
  in-game hours (`jobs.now_hour` floors), so a stage of fractional hours can
  bring it up to an hour late.
- The Magpie's reveal: `magpie_unmasked` (agendas.yaml's role mask) is set
  by nothing in v0.12 -- the unmasking is v1.0 content (the interrogation
  deck, or the thief caught in the act). Until then the GM line never says
  who the Magpie is. The agenda clocks' beats set flags (`ardane_warrant_sworn`,
  `silas_splits_the_company`, `magpie_spree_full`, ...) that only v1.0's
  scenes will read.
- Ardane's `takes_a_statement` move can only file her OWN report at a fixed
  deed (`pickpocket`): a move has no way to name the deed a witness actually
  saw, so it cannot upgrade that row directly -- it adds a second, lesser
  one instead.
- Agenda moves are never posted to the notice board, and no `fence {most:
  hot_goods}` selector exists (fences hold no stock to count) -- both rows in
  docs/GOVERNANCE.md's NOT WIRED table.
- The Magpie keeps robbing while the player serves a sentence: its
  robberies land on the player's name from inside a cell. v1.0 content
  answers it with an alibi beat (a night in the cells as proof), not the
  engine.
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
