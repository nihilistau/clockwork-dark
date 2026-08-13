# Dev Story — the bench

A sandbox story for testing the engine. Not a game: a house, a university, eight
people, and one small working instance of every subsystem, so you can change a
thing and see what it does without 5,300 lines of authored content answering
first.

```powershell
.\.venv\Scripts\python.exe launcher.py --game dev-story --port 5599
```

This story ships. It used to be gitignored; it is committed now because it is
the full worked example the story templates (`scripts/story_template/`) are
distilled from, and because it puts a third row under every per-story test —
one that shares almost nothing with either big story. Break it freely on a
branch; the suite runs its rows, so leave it working on main.

Writing a story of your own? The end-to-end guide — manifest contract, content
types, the authoring tools, verification — is
[docs/AUTHORING.md](../../docs/AUTHORING.md); this README is its worked
example.

---

## What to edit for what

| You want to change | Edit |
|---|---|
| The opening scene and the three buttons | `game.yaml` → `entry.opening` |
| The narrator's voice, the setting, the cast descriptions | `prompts/storyteller.md` |
| Sophia's own voice (she is an AGENT, not an NPC) | `prompts/sophia.md` |
| Who exists, what they may say, what they may write | `agents.yaml` |
| The two meters and the clock | `state.yaml` |
| The map | `data/world/locations.yaml` |
| Where the other seven people are, hour by hour | `data/world/npc_schedules.yaml` |
| A progress clock that fills and forces a scene | `data/rules/clocks.yaml` |
| A contract with a lifecycle | `data/rules/threads.yaml` |
| How the story can end, and what the gates are | `data/rules/endings.yaml` |
| The last screen | `data/epilogues/` |
| Authored scene cards, gates and bands | `data/scenes/campus_day.yaml` |
| Items, quests | `data/items/`, `data/quests/` |
| What the awareness gate hides | `data/rules/spoilers.yaml` |
| The pictures | `data/art/manifest.yaml`, `data/art/subjects.yaml` |

Everything is small on purpose. If a change here does not do what you expected,
the cause is the engine or your edit — there is nothing else in the room.

---

## The two things most worth knowing

**The multi-agent pipeline is ON.** `agents.yaml` declares two agents (`world`
and `sophia`), which is `MIN_AGENTS`, so every turn runs
plan → negotiate → commit before the narrator writes a word. That costs **one
extra model call per turn**. Delete the `sophia:` block *and* the `negotiation:`
table to turn it off — a rule naming a missing agent is a hard `RosterError`,
not a silent skip.

**Sophia is an agent; the other seven are NPCs.** That is the sharpest
distinction in this engine and the bench exists to make it visible:

- an **NPC** is a row in `npc_schedules.yaml`. It has a location per hour and an
  activity string. It says nothing it was not written to say, and costs nothing.
- an **agent** is a row in `agents.yaml` with a persona and permissions. It
  plans against the same state the narrator does, negotiates, and may move
  meters it owns. It costs a model call per turn.

Sophia is deliberately absent from `npc_schedules.yaml`. Put her back and you
get two of her — a scheduled one in the library and a live one in the room.

---

## Meters

`influence` and `popularity`, both 0–100, both starting at 50, both public so
the raw number reaches the browser (a story would use `veiled`; a bench wants
the number).

Neither declares `owners:`. `agents.yaml` says who may write them, and
`engine/state/active.py::_with_roster_grants` folds that into the schema at
load. A flat `owners:` list cannot express *"only with a reason"*, and
`influence` is exactly that for Sophia — the one permission here worth watching.

---

## Art

Every picture is a **placeholder copied from The Wicked Garden**. Eight Sophia
plates stand in for eight characters — deliberately eight *different* files, so
you can see at a glance which id resolved. Twelve of the thirteen locations have
no plate at all and fall through to the procedural silhouette.

That is the useful state, because the prompts are written:

```powershell
.\.venv\Scripts\python.exe scripts\art_missing.py --game dev-story
```

writes `data/art/MISSING-PLATES.md` — every gap, with a ready-to-paste prompt in
both dialects at the right pixel size. Generate what you want to look at.

---

## Intensity

`game.yaml` declares its own `safety:` block (`ceiling: extreme`,
`default: explicit`). That is a **story-level** decision and it lives here
rather than in `config/default.yaml`, which is the engine's answer for every
story that declares nothing — raising it there moves the ceiling for The
Clockwork Dark and The Wicked Garden too, and fails
`tests/test_safety_shipped_games.py`.

`hard_nos` is deliberately absent. Limits belong to the player, set in the
boundary sheet at the start of a run.

---

Version: v0.3.0 [2026-08-13]
