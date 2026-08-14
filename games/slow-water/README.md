# The Slow Water

Nine days upriver on a funeral barge. You are a hired mourner — paid by the
day to weep for strangers so a family need not weep in public. By the second
day you know the Ravels are not grieving. The box in the hold does not hold
the man whose name is on it, and every person aboard is waiting to see
whether the professional weeper is the sort who counts.

Scaffolded from the **deck** template: Garden-shaped. No dice, no travel
economy, no doom — the machinery is authored day-decks, a progress clock
that ends in a forced scene, threads (contracts the world remembers), gated
endings and the epilogue cards behind them.

```powershell
.\.venv\Scripts\python.exe launcher.py --game slow-water
```

## How it was written

Scaffolded with `scripts/new_story.py`, then drafted from `BIBLE.md` with
`scripts/author.py --from-bible` and corrected with `--repair`. The bible is
kept in the tree because it is the input the drafting tool reads — changing
the story means changing the bible and re-drafting, not editing nine decks
by hand.

What the tool produced well: the day-deck prose, and the nine-day shape of
the arc. What it did not: the locations (thin, and wired to ids that did not
exist), the clock, the endings, the epilogues, the forced scene and the one
flag that couples a deck to the clock — all hand-authored here. Four defect
shapes it introduced are now caught by the validator rather than by reading,
and three of them are ungrammatical in the drafting schema; see
[docs/AUTHORING.md](../../docs/AUTHORING.md) §4.1. The one thing no check can
catch is in "Known weakness" below.

## What to edit for what

| You want to change | Edit |
|---|---|
| The premise the drafting tool works from | `BIBLE.md` |
| The opening scene and the buttons | `game.yaml` → `entry.opening` |
| The narrator's voice, the family | `prompts/storyteller.md` |
| The meters and the clock (what they ARE) | `state.yaml` |
| What the clock DOES | `data/rules/clocks.yaml` |
| A day's cards | `data/scenes/day_*.yaml` |
| The confrontation the clock forces | `data/scenes/the_reckoning.yaml` |
| The contracts and the gift trap | `data/rules/threads.yaml` |
| How it can end, and the gates | `data/rules/endings.yaml` |
| The last screen | `data/epilogues/` |
| The stage set | `data/world/locations.yaml` |
| What the narration may not say yet | `data/rules/spoilers.yaml` |

## The couplings that make this shape work

Trace these before rewriting — each is two files that must agree, and each
fails quietly rather than loudly when they stop agreeing:

1. **Deck → clock.** A hold card sets `counted_the_screws`; `clocks.yaml`
   watches that flag and winds `suspicion`. So does a composure above 85 —
   a mask that never slips is its own tell.
2. **Clock → deck.** `suspicion` at max forces `the_reckoning` — a clock's
   `forces_scene` names a deck by its **id**, not its filename, and a forced
   scene naming nothing is a promise with no scene behind it.
3. **Deck → thread.** Money pressed on you beyond the agreed rate seals
   `mourners_contract` via `gift_obligation`. Accepting without asking its
   price is the whole trap.
4. **Thread → ending.** `paid_in_full` is not completable while
   `mourners_contract` is active. The engagement is the obstruction, and the
   lock text tells the player so.
5. **State is declared twice, halves split.** `state.yaml` says what
   `suspicion` IS; `clocks.yaml` says what it DOES. Delete the state half
   and the clock fails silently.
6. **Endings → epilogues.** The two ending ids in `data/rules/endings.yaml`
   appear verbatim in `epilogue_index.yaml` and `epilogue_cards.yaml`. A
   locked ending with no row is an error and a blank last screen.

## Growing it

A tenth day is a tenth file in `data/scenes/`. A second clock is a block in
two files (see coupling 5). Character agents (`agents.yaml`) would give Iva
her own voice and model call — `games/dev-story/agents.yaml` is the worked
example, and it is the obvious next thing this story wants. The full-scale
version of this shape is `games/wicked-garden/`; the annotated bench for
everything is `games/dev-story/`.

## What is measured, and what is not

`scripts/simulate.py --game slow-water` walks the decks headlessly. Over 200
runs: all 10 decks dealt, **no orphan cards**, both endings reachable, no
epilogue gaps, and `suspicion` fills and forces `the_reckoning` in every run
— the clock→deck coupling is exercised, not assumed.

The ending split depends almost entirely on `--thread-rate`, which is the
walker's approximation of how often something seals a bargain mid-chapter:

| `--thread-rate` | `paid_in_full` | `the_other_column` | favor at end |
|---|---|---|---|
| 0.0 | 65 / 200 | 135 / 200 | 61 |
| 0.15 | 19 / 200 | 181 / 200 | 40 |
| 0.35 (default) | 7 / 200 | 193 / 200 | 25 |

**Read that as a caveat, not a balance claim.** The walker seals threads on a
timer because in the Garden an agent seals them mid-scene; this story ships
no `agents.yaml`, so the only thing that seals a contract here is the gift
trap, and the low rates are the representative ones. The decks by themselves
produce a roughly one-in-three earned ending, which is the intent. Tuning the
thread constants until the default rate looked better would be tuning to an
artifact of the harness.

What is genuinely untested: **how it plays.** The walker sweeps bands and
picks menu choices uniformly, so it measures reachability, not taste. No
claim about pacing, voice or whether the nine days earn their length has
been measured by anything but reading them.

## Known weakness: the days are nearly all sequences

Of the 23 cards across the nine drafted days, **none** is tagged `menu` — the
tag that makes the player pick which beat resolves. Every one is a
`sequence`, which plays automatically. The only menu card in the story is
`TR_02_what_you_do_about_it`, hand-authored in `the_reckoning`.

(One drafted card arrived tagged `[sequence, menu]` and carrying a single
beat, which is a menu of one; it was corrected to `sequence`.)

The drafting model writes consecutive moments well and alternatives poorly:
its sequence beats are written to follow each other rather than to exclude
each other, so they cannot simply be retagged. Converting one here would
offer the player three halves of the same paragraph.

Turn-level agency is unaffected — the narrator still offers 2–4 options every
turn, and `the_reckoning` (hand-authored) is a real menu. But the day-decks
themselves are closer to authored texture than to choices, and closing that
gap means rewriting beats as genuine alternatives, by hand or from a bible
that asks for them explicitly.
