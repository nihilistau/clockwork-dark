# Story State

How a story declares what its state IS, and how the engine reads and writes it.

Authority reminder: the code wins. If this file disagrees with
`engine/state/**`, the modules are right and this file is stale.

---

## The problem

`GameState` is a dataclass carrying `hp`, `stamina`, `hunger`, `wounds`,
`evil_phase`, `awareness` and a procgen result. That is **one story's answer,
welded into the engine**. A story built on eight 0–100 meters, four 0–5 progress
clocks and nine per-NPC relationship records had nowhere to put any of it —
`flags` is booleans only — while inheriting a dozen fields it would never read.

The multi-game layer could repoint 22 content files and nothing else, so a
second story could only ever be the first one with different nouns.

## The declaration

`games/<slug>/state.yaml`, optional. A story that ships none runs on the engine
spine, exactly as both games did before this existed.

```yaml
version: 1
meters:
  favor:   {min: 0, max: 100, default: 15, visibility: veiled, owners: [sophia]}
  hp:      {backing: field, path: stats.hp, min: 0, max: 20, visibility: public}
clocks:
  briar_hunger: {min: 0, max: 5, visibility: hidden}
tracks:
  ...
```

### `backing` is the migration strategy

| | |
|---|---|
| `field` | An existing typed attribute, addressed by a dotted path (`stats.hp`). Nothing moves. The ~10 modules that say `state.stats.hp` keep saying it. |
| `bag` | An entry in the generic `meters` / `clocks` / `tracks` containers on the spine. A story the engine has never heard of uses these exclusively. |

**The Clockwork Dark declares 14 values, all `backing: field`.** It is *described*,
not rewritten — which is the only reason this was safe to land under 949 existing
tests. A value can be flipped from `field` to `bag` later, one at a time, each
flip small enough to prove on its own. `tests/test_state_schema.py` asserts the
flagship stays entirely field-backed, so a drift without moving its readers
fails the suite.

### `visibility` replaces three hardcoded payload contracts

`to_client_dict`'s 21-key allowlist, the `turn_update` dict literal, and the
reducer's own shape were three independent lists — so a story could not show the
player a value the engine had not been taught about.

| | |
|---|---|
| `public` | Sent as a number, with bounds |
| `veiled` | Sent as a **band only**, never the integer — a meter read as a rose opening, not as 63/100 |
| `hidden` | Never leaves the server; the player meets it as fiction |

### `owners` is the per-agent write ACL

Empty means **engine-only**, and empty is the default: a story has to say a value
is agent-writable rather than forget to say it is not.

## The store

`engine/state/store.py`. One API over both backings — callers cannot tell which
they are touching.

```python
from engine.state.active import store_for

store = store_for(state)
store.get("favor")
store.adjust("favor", 8, by="sophia", why="she was amused", turn=12)
```

- **Writes clamp rather than raise.** A model proposing 140 on a 0–100 scale
  means "as high as it goes", not "crash the turn". The receipt carries
  `before`/`after`, so the overshoot is still visible.
- **Attribution lives on the effect receipt, not in the store.** The store's
  write journal was deleted — `store_for()` builds a fresh store per call, so
  every journal record died the moment its caller returned, and nothing ever
  read one. `by` and `why` ride out on the effect receipt
  (`engine/game/effects.py`), which is the artifact that survives a turn.
- **Refusals are logged, not just dropped.** A write by anyone not in a value's
  `owners` is refused at WARNING — an agent repeatedly trying to move a value
  it does not own is a prompt defect, and it is invisible if the attempt is
  only ever discarded.
- Never cache a store across a rollback: it holds the state by reference and a
  rollback replaces that object's contents in place.

## Prerequisites that had to be fixed first

Three defects silently discarded any state declared beyond the base dataclass.
Each failed in a way that looked like a content bug, and nothing in the suite
exercised a subclass, so all three were invisible. See
`tests/test_state_extension.py`.

1. `transaction.restore_in_place` iterated `fields(GameState)` literally, not
   `type(target)` — extended fields were reverted on **every evaluator retry and
   every tool savepoint**.
2. `StateTransaction.rollback` rehydrated through `GameState.from_dict`, so even
   a fixed restore loop was handed an object with nothing to copy.
3. `GameState.from_dict` named its six nested dataclasses one by one; a seventh
   came back from a save as a raw dict and failed later, elsewhere.

## What sits on top of it

| Container | System |
|---|---|
| `meters` / `clocks` | `engine/game/clocks.py` — progress clocks with predicates, auto-advance and forced setpieces. Wound from `clock.advance_time`, for the same reason doom beats are: a clock that only advanced on narrated turns would stop for a player who slept through the week. |
| `threads` | `engine/game/threads.py` — offer → terms → renegotiate → seal, with `transform` for an already-sealed contract. Expired on the day rollover from `clock.advance_time`. |
| `tracks` | Enum and list-valued story state, written through the `track` effect kind. |
| ending state | `engine/game/endings.py` — eligibility, continuous scores, soft `intent` then hard `lock`. |
| `social` (a phone story only) | `engine/social/` — the phone's slice, written only by the `social_*` effect kinds. Each person's memory is one dict per PERSON, `social.people[pid].memory` (v0.23.0, `engine/social/memory.py`): `current` (the open conversation, both sides, every app, `memory.verbatim` bubbles), `bridge` (the last `bridge_bubbles` of the one before), `episodes` (closed conversations' recaps `{id, kind, where, from_at, to_at, recap, topics, end_reason}`, at most `episodes_kept`), `story` (the oldest folded in, at most `story_words`), `open` (follow-ups `{id, kind, about, due_at, by}`, at most `open_max`), and `canon`, `knows`, `told` and `history`, and `shelved` (the archive shelves a dormant spell moved out whole, until they talk again); written by `social_memory` (and `social_history`), an empty part left out. A thread keeps its messages, never a summary. The slice carries its own `schema` (2 since v0.23.0; a v0.22.0 slice has none, read as 1, and `CURRENT_SAVE_VERSION` does not move); see "The phone slice's migration" below. Life events (v0.23.0 T17, `engine/social/life.py`, written only by `social_life`): `social.people[pid].life` and `social.player_life` (the player's, made by `setdefault` on the first event) hold `[{id, at, until?, supported?, request?}]`, the running events and a few past ones (`life_events.yaml` `kept.past`, pruned at every save with the ones still on cooldown kept); `people[pid].news` (`{id, text}`, told once) and `people[pid].job_now` (a job id) are left out when empty. |

### The phone slice's migration (v0.23.0)

`engine/persistence/saves.py::SaveStore.load`, after `GameState.from_dict` (which unpacks the slice,
`engine/social/packing.py`), calls `engine/social/migrate.py::upgrade` for a `paths.social` story whose
slice is not at schema 2: every route that resumes a run (local, hosted, `_flush_before_load`) goes
through it, before `SessionStore._build`, whose guard refuses a slice at any other schema. `_plan`
decides everything first, reading only; the `social_migrate` effect (`op: apply`, then `op: seal`, which
alone sets `schema: 2`, last) and the effects it builds on write it. A fault anywhere is a
`MigrationError`: the save is refused and logged, and its file is untouched. A slice already at schema 2
is left alone (idempotent); any other schema is refused. No file is touched: the run's
`phone_archive.jsonl` keeps every row.

| v0.22 | v0.23 |
|---|---|
| `location_id: home` | `apt_lounge` (`social_go` `op: place`, no clock) |
| `threads[*].summary`, `summary_through` | Joined, oldest thread first, into the person's `memory.story` (capped); dropped |
| A thread's tail | `memory.bridge`: the last `bridge_bubbles` voiced bubbles of the person's newest thread |
| Top-level `canon`, `knows`, `told`, `history` | Moved under `memory` |
| No `growth` | Depth from stage (matched, talking 0; numbers, meeting 1; dating, friends, fling 2; exclusive 3), openness 0, `pace` from the fixed attributes, which are materialised (`social_person`) |
| No `episode` | `episode: None`, `episodes_done` 0, `scenes_done` the person's done meets |
| `pending_read`, `initiated`, `asks_today`, the `social.meet` stream counter | Dropped |
| A player's message left unanswered (the newest thread's last spoken message) | A `read` queued at `convo.next_available`, unless they left or a reply is already due |
| Queue `read`, `meet_start`; an `initiate` of a retired situation | Dropped |
| Other queue events (`daily`, `expire`, `see_like`, `likes_you`, `game_move`, `arc_beat`, due replies) | Kept; a due decision gets `mode: quick` and loses `meet_id` |
| `meets` agreed or due | A `soon` plan (`plans.make(..., migrated=True)`), the venue and its kind kept |
| `meets` done / other; `counters.meet` | Counted in `scenes_done` / dropped (the history rows stay) |
| A recap card never voiced (`kind: recap`) | Dropped (nothing voices one since v0.23.0 T19) |
| A pending `meet` request | `when: soon`, its venue's `kind` and `venue`; `day` and `slot` dropped |
| `settings.auto_wait` | Dropped; `wake_for_messages` false |
| No `promises`, `plans`, `scene`, `household`, `phone_up`, `at_work` | Their empty values; `phone_up: true` |

Effects reach all of it through `effects.apply_effect(..., by=, turn=)`, which is
still the single writer, and which threads the writer id down to the store's
per-value `owners` ACL and onto the effect receipt.

## Wiring status

| Thing | Status |
|---|---|
| Agent write attribution | **Wired.** `engine/agents/pipeline.py` commits every accepted effect through `apply_effect(..., by=agent, turn=...)`, so the store's `owners` ACL and the receipt both see who asked. Writes outside the pipeline are `WRITER_ENGINE`, which is what they are. |
| The plan/negotiate pipeline | **Live.** `engine/agents/pipeline.py` runs plan → negotiate → commit ahead of narration for any story whose `agents.yaml` declares two or more pipeline participants. The Wicked Garden declares two (`gm` + `sophia`) and takes this path; the flagship's roster declares its canon pair with the companion at `pipeline: false`, so it has one participant and runs the single-agent turn unchanged. |

| `ui/` consuming the `meters` block | **Wired.** `ui/src/core/parts/Meters.jsx` draws the block generically and `MeterSheet` is core's DEFAULT right-hand column, so a story with no plugin at all gets a working sheet; The Wicked Garden's own `Ledger` reads the same block and falls through to core's renderer for any row it has no metaphor for. A `veiled` row renders as a five-step glyph row and never as a track, because a bar width is a number. |
| The two systems a number cannot describe | **Wired.** `threads` and `endings` ride out beside `meters` from `GameState._structural_block`, each key present only when the story declares the system behind it (`paths.threads`, `paths.endings`). `endings` is projected by `engine/game/endings.py::to_client`, which is `recompute`'s read-only twin. The Wicked Garden draws both — `ContractsOverlay` and `GalleryOverlay` — gated on the key's presence through the plugin contract's `when(state)`. |

## NOT WIRED

| Thing | File | Status |
|---|---|---|
| An ending's `tease:` | reader: `engine/game/endings.py::declared` → `to_client`. Consumers: `ui/src/stories/wicked-garden/parts/GalleryOverlay.jsx`, `ui/src/stories/neon-city/parts/RoadsOverlay.jsx`. Author: nobody | Read and shipped in the payload, and NO shipped story declares one — `grep -rn "tease:" games/` returns nothing, re-checked 2026-08-14. Both gallery screens fall back to a per-tier line. It is an authored line and the fallback is honest, but nothing exercises the real path yet. |

Re-audited on 2026-08-14 against the tree. One row survives; the rows for the
`meters` block, the `threads`/`endings` structural block, agent write
attribution and the plan/negotiate pipeline all moved into the wired table
above with their call sites.

Version: v0.5.0 [2026-08-14]
