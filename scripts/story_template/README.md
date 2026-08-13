# Story templates

Consumed by `scripts/new_story.py`, which copies one of these directories to
`games/<slug>/` and rewrites two tokens on the way: `{{slug}}` and `{{title}}`.
Nothing else is generated -- what you see in a template is what a new story
starts as, teaching comments included.

```powershell
.\.venv\Scripts\python.exe scripts\new_story.py my-story --template minimal
```

The end-to-end authoring guide — the manifest contract, every content type's
sharp edges, the LLM-assisted loop, and how to verify a story — is
[docs/AUTHORING.md](../../docs/AUTHORING.md). The templates teach their own
keys; that document teaches what cuts across them.

## Why these live here and not under games/

Everything under `games/` with a `game.yaml` is a real story:
`registry.discover()` offers it to the picker, `scripts/doctor.py` reports on
it, and the per-story tests sweep it (they parametrise over discovery, not over
a hardcoded list). A directory full of `{{slug}}` tokens must never be any of
those things, so the templates sit outside the games root where discovery
cannot reach them.

## The three shapes

| Template | Modelled on | What it ships |
|---|---|---|
| `minimal` | `games/dev-story/` | 3 rooms, 2 items, 2 agents, 1 meter, a spoiler table. The smallest thing that validates and plays a turn. |
| `graph`   | `games/clockwork-dark/` | a travel graph with hours, quests, encounters, an economy: vendors, jobs, forage and boon tables. |
| `deck`    | `games/wicked-garden/` | authored day-decks, progress clocks, threads, gated endings, epilogue cards. |

They are starting points, not fences: a graph story may add decks, a deck story
may add an economy. Every subsystem is keyed by one `paths.*` line in
`game.yaml`, and an undeclared key resolves to nothing -- the engine's defaults
name no story's content.

## The relationship to dev-story

**The templates are distilled; `games/dev-story/` is the full worked example.**
The bench ships one small working instance of every subsystem -- thirteen
locations, eight scheduled NPCs, a two-agent pipeline, a clock that forces a
scene, a thread with renegotiations, three gated endings and their epilogues --
each file annotated at a depth a template cannot afford. When a template's stub
is not enough to see how a mechanism behaves, the same mechanism is running in
dev-story with the lights on: launch it, edit the file, watch what changes.

Keep it that way around. When a subsystem changes shape, fix dev-story first
(the suite runs its rows, so it cannot silently rot), then re-distil whatever
the templates carry of it. A template that drifts from the bench is a template
that teaches the old engine.
