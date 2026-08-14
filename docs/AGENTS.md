# The Agent Runtime

How two agents take one turn together.

Authority reminder: the code wins. If this disagrees with `engine/agents/**`,
the modules are right and this is stale.

---

## What this replaces

The two agents were **strictly sequential and one-directional**. The Storyteller
ran to completion and *committed*; then the Assistant was invoked with the final
narration string as its only input. Neither produced a plan. Neither could
object to the other. The Storyteller never saw the companion's output at all —
not that turn, not the next one, because the companion's line was never written
to the ledger.

That is enough for a narrator plus a hint system. It cannot express a second
character who wants something, who may write shared state under conditions, who
may lie in dialogue while the record keeps the truth, and whose intent has to be
reconciled with the world's before either of them speaks.

## The shape

```
input → safety → plans (per agent, private) → negotiate
      → commit (atomic) → narrate → choices → briefs
```

**A plan is inert.** Constructing one changes nothing. That is the property the
whole design rests on: a proposal that has already taken effect cannot be
argued with, only undone. Effects are *requested*; the commit phase runs them
through `effects.apply_effect` — still the single writer — with the proposing
agent recorded, so the state store's ACL and the effect receipt see who asked.

**`private` reasoning never leaves the agent.** `AgentPlan.to_dict()` withholds
it by default, because that output is what gets logged, journalled and sent to
telemetry — a private motive that leaks into any of those is one the other agent
eventually reads.

## Negotiation

Rules are **data**. "Her private scene completes; the world event becomes
aftermath" is one story's dramatic priority, not the engine's; written in Python
it would be one story's `if` chain in a module every story imports.

```yaml
negotiation:
  - name: private_scene_wins
    when: {sophia: speak, gm: interrupt}
    winner: sophia
    keep_loser_beat: true      # the world loses the lead, not its content
    detail: her scene completes; the event becomes aftermath
```

The engine ships only the rules that are structural rather than dramatic:

| Rule | Why it is not a story's to reorder |
|---|---|
| `safety_first` | A story that could rank itself above the player's stated limits would make the safety layer advisory. |
| `ownership` | An agent may not speak as a voice it does not own. Enforced at the point the *intent* is visible, so the attempt is recorded rather than silently dropped. |

Two deliberate details: a rule with an empty `when` is **inert, not universal**
— a rule matching everything would make table order silently load-bearing. And
a blocked turn still returns a lead and choices, because a negotiator that
returned nothing would force the caller to show an out-of-character refusal
instead of an in-world redirect.

Choices are **jointly authored**: both agents propose, duplicates collapse
case-insensitively, and ids are assigned positionally by the engine — the 1–4
keyboard shortcuts depend on position, so letting an agent choose ids would let
one agent's collide with the other's.

## Knowledge scopes

| Scope | For |
|---|---|
| `public_world` | Both agents. Granted implicitly — a scope system whose common case must be spelled out will be got wrong. |
| `gm_secrets` | The world's knowledge. A character who knows the world's secrets stops being a character. |
| `character_private` | One character's motive. The narrator must not read it, or the prose quietly confirms or contradicts a secret still being kept. |
| `player_facing` | What may reach the browser. Enforced by the state schema's `visibility`. |

An agent absent from the policy sees **only public** — forgetting to grant a
scope produces a slightly ignorant agent, not one reading the world's secrets.

Blocks are **dropped, not redacted**: a redacted block still tells the agent
something was there, and a model that can see the shape of a secret writes
around it in a way that reveals it.

Lore retrieval is scoped through `LoreChunk.tags` — a column stored since the
index was written and filtered on by nothing. Only tags that *name a scope*
gate a chunk, so an untagged or topically tagged chunk stays public and turning
scoping on cannot hide every existing lore file.

**Lies are tracked, not prevented.** A character agent may assert what the board
contradicts; `record_claim` writes it to the ledger marked false, so a later
scene can catch it out. Previously the companion's unreliability was a dice roll
whose *content* nothing recorded.

## A story declares its cast

```yaml
agents:
  gm:
    role: world
    voices: [narration, thornwake, lior]
    reads: [gm_secrets]
    writes: [favor]
  sophia:
    role: character
    voices: [sophia_dialogue]
    reads: [character_private]
    writes: [desire]
    writes_with_reason: [autonomy]
```

The roster **declares**; three existing layers enforce, and that separation is
deliberate — a roster that enforced anything itself would be a fourth place to
get it wrong.

| | Enforced by |
|---|---|
| voices | `negotiate.py`, at the point the intent is visible |
| reads | `knowledge.py`, filtering prompt blocks and lore retrieval |
| writes | `state/store.py`, whose per-value `owners` refuses **and logs the refusal**; who and why land on the effect receipt |

Two voices claimed by two agents, or a rule naming an agent that does not exist,
are both rejected at load — a rule that can never fire would sit in the table
looking like it works.

## Governance phases

`PHASE_COMMIT` runs over reconciled proposals **before** the transaction
commits, with authority to set `ctx.veto`. Everything else audits after the
fact: `PHASE_POST` has always run after `tx.commit()`, so it can record and
clamp but never stop the turn that did it.

Its default chain is deliberately **empty**. A hook that can veto a turn is the
most dangerous thing to ship on by default; a story gets one by asking.

## The pipeline, on a live turn

`engine/agents/pipeline.py` runs plan → negotiate → commit ahead of narration
for any story declaring two or more agents.

| Phase | What happens |
|---|---|
| Plan | Every declared agent proposes, concurrently, against the SAME pre-commit state and the same player action, seeing only what its knowledge scopes allow. `plan_schema()` is filled in per agent: `speaks_as` is enumerated to the voices it owns and `effects[].name` to the values it owns, so a claim it has no right to make is unsampleable rather than merely discouraged. |
| Negotiate | Safety first and not reorderable, then voice ownership, then the story's rule table in declared order, then highest confidence. Every decision is recorded as a `Resolution` — a turn whose shape has an explanation. |
| Commit | Accepted effects applied ONCE, inside one `StateTransaction`, through `apply_effect` with `by=` set to the proposing agent. Half-applying would leave a state neither agent proposed and no rule produced. |
| Narrate | Unchanged, except that `build_storyteller_messages(agreed_block=...)` hands the narrator what was settled. It reports the turn rather than re-deciding it, and a character's line goes in verbatim. |

The ordering is the point: an agent that has already written cannot be argued
with, so nothing is written until the argument is over.

`engine/agents/turn_loop.py` is **retired** — renamed `.bak`, out of the import
path. It was kept as the designated basis for this pipeline; the pipeline was
written fresh instead, so it stopped being pending and became redundant. Two
turn architectures no longer coexist in the tree.

**Permissions have one home.** A roster's `writes` / `writes_with_reason` are
folded into the schema's per-value `owners` by `engine/state/active.py`. They
used to be declared in two files that disagreed — the Garden's roster granted
`gm` ten values and its schema named owners for two, so the world agent could
not move `corruption` and Sophia's `autonomy` write was refused every time.

The store's write journal is **deleted** (`engine/state/store.py`): it was
per-store, `store_for()` builds a fresh store per call, so every record died
the moment its caller returned, and `clear_journal()` was called by nothing.
The two fields that made it worth having — `by` and `why` — ride out on the
effect receipt instead, which is what actually survives a turn. What stays in
the store is enforcement: the `owners` ACL and a WARNING-level log on every
refusal.

## NOT WIRED

| Thing | File | Status |
|---|---|---|
| Reasoning cost of structured plans | `engine/agents/pipeline.py` (the two plan calls), `engine/lmstudio/client.py` (the transport that cannot disable reasoning) | A JSON schema forces the OpenAI-compat transport, which cannot turn reasoning off. Two plan calls per turn pay that on hardware where reasoning is 800+ tokens. **Still unmeasured against a real model** — this is a cost that is not known, not a mechanism that is not called, and it is in this table so that the difference stays visible. |

Re-audited on 2026-08-14 against the tree. This row is the only one, and it is
the odd kind: everything it names IS wired and running. What is missing is a
measurement.

Version: v0.4.0 [2026-08-14]
