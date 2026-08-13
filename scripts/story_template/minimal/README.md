# {{title}}

Scaffolded from the **minimal** template: the smallest story this engine will
validate and play. Three rooms, two items, two agents, one meter.

```powershell
.\.venv\Scripts\python.exe launcher.py --game {{slug}}
```

## What to edit for what

| You want to change | Edit |
|---|---|
| The opening scene and the three buttons | `game.yaml` → `entry.opening` |
| The narrator's voice and the setting | `prompts/storyteller.md` |
| Alex's voice (an AGENT, not an NPC) | `prompts/alex.md` |
| Who exists, what they may say and write | `agents.yaml` |
| The meter | `state.yaml` |
| The map | `data/world/locations.yaml` |
| The objects | `data/items/things.yaml` |
| What the narration may not say yet | `data/rules/spoilers.yaml` |
| Names, spellings, decided facts | `CANON.md` |

## Growing it

Every subsystem is one `paths.*` line in `game.yaml` plus the files it names.
An undeclared key resolves to nothing — the engine's defaults name no story's
content, so nothing leaks in while you build.

- Quests, encounters, an economy → scaffold a throwaway story from the
  `graph` template and crib its stubs.
- Day-decks, clocks, threads, endings → same, from the `deck` template.
- The full worked example of **everything at once** is `games/dev-story/` —
  one small working instance of every subsystem, annotated. When a mechanism
  here is unclear, it is running there with the lights on.

## The two-agent pipeline

`agents.yaml` declares two agents, which is `MIN_AGENTS`, so every turn runs
plan → negotiate → commit and costs one extra model call. Delete the `alex:`
block *and* the `negotiation:` table to fall back to cheap single-narrator
turns — a rule naming a missing agent is a hard `RosterError`, not a silent
skip.
