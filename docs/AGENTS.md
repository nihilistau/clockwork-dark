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
agent recorded, so the state store's ACL and journal see who asked.

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
| writes | `state/store.py`, whose per-value `owners` refuses **and journals** |

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

## NOT WIRED

| Thing | Status |
|---|---|
| The pipeline on a live turn | `plan`, `negotiate`, `roster` and `knowledge` are built and tested. The live path is still `StorytellerAgent.run_turn`, the single-agent design. No shipped story declares an `agents.yaml`. |
| `engine/agents/turn_loop.py` | Still unwired, still the designated basis for the pipeline. See its own header. |
| Structured plan emission | `plan_schema()` exists; no agent is asked to fill it in yet. Note the cost when it is: a schema forces the OpenAI-compat transport, which cannot turn reasoning off. |

Version: v0.1.0 [2026-08-08]
