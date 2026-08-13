# {{title}}

Scaffolded from the **deck** template: Garden-shaped. No dice, no travel
economy, no doom — the machinery is authored day-decks, progress clocks that
end in forced scenes, threads (contracts the world remembers), gated endings
and the epilogue cards behind them.

```powershell
.\.venv\Scripts\python.exe launcher.py --game {{slug}}
```

## What to edit for what

| You want to change | Edit |
|---|---|
| The opening scene and the buttons | `game.yaml` → `entry.opening` |
| The narrator's voice, the host | `prompts/storyteller.md` |
| The meters and the clock (what they ARE) | `state.yaml` |
| What the clock DOES | `data/rules/clocks.yaml` |
| The day's cards | `data/scenes/day_one.yaml` |
| The contracts and the gift trap | `data/rules/threads.yaml` |
| How it can end, and the gates | `data/rules/endings.yaml` |
| The last screen | `data/epilogues/` |
| The stage set | `data/world/locations.yaml` |
| What the narration may not say yet | `data/rules/spoilers.yaml` |

## The couplings that make this shape work

The stubs are wired to each other on purpose — trace these before rewriting:

1. **Deck → clock.** The gallery card's `ask_who_is_missing` beat sets
   `asked_the_wrong_question`; `clocks.yaml` watches that flag and winds
   `suspicion`.
2. **Clock → deck.** `suspicion` at max forces `day_one` — a clock's
   `forces_scene` names a deck by its FILENAME id, and a forced scene naming
   nothing is a promise with no scene behind it.
3. **Deck → thread.** The winter garden card offers a gift; accepting one
   without asking its price seals `guests_debt` via `gift_obligation`.
4. **Thread → ending.** `the_guest_departs` is not completable while
   `guests_debt` is active. The debt is the obstruction, and the lock text
   tells the player so.
5. **State is declared twice, halves split.** `state.yaml` says what
   `suspicion` IS; `clocks.yaml` says what it DOES. Delete the state half
   and the clock fails silently.

## Growing it

A second day is a second file in `data/scenes/`. A second clock is a block
in two files (see coupling 5). Character agents (`agents.yaml`) give the
host their own voice and model call — `games/dev-story/agents.yaml` is the
worked example. The full-scale version of this shape is
`games/wicked-garden/`; the annotated bench for everything is
`games/dev-story/`.
