# Content Limits

*The product layer. It sits above every agent, and no character's motivation
reaches it.*

**Version:** v0.2.1 [2026-08-14] · **Code:** `engine/safety/` · **Tests:**
`tests/test_safety.py`, `tests/test_safety_shipped_games.py`,
`tests/test_safety_wiring.py`, `tests/test_governance_commit.py`

---

## What this is

A boundary sheet and an intensity ceiling, expressed as **data**, enforced by
**structure**, and off by default.

It exists because the engine had no content controls of any kind — a grep for
`safety|intensity|hard_limit|boundar|consent` across `engine/` returned a
token-budget constant and some sentence-boundary logic — and because a second
story is being added whose design specifies the full ladder. The architecture
here is that design's, not an invention: see
`Design_files/Wicked-Garden/docs/design/04-ITEMS-AND-SYSTEMS.md` (Safety
Systems), `06-UI-UX.md` (Adult Scene UX), `agents/STATE-BOARD.md` (the
enforcement rule) and `voice/SOPHIA-VOICE-BIBLE.md` (character vs product).

### The four claims, and where each is enforced

| Claim | Enforced by | Not by |
|---|---|---|
| A character's motivation never raises the ceiling | `policy.Actor` — the only mutator takes an actor and `AGENT` is a `min()`. `SafetyPolicy` is frozen. `BoundarySheet` has no subtract. | a line in a system prompt |
| Content above the session's setting collapses to summary | `gate.SafetyGate._decide` step 2 — one comparison, one place | four copies in four call sites |
| A faded scene still applies its mechanical outcomes | `Verdict` has no effects field; `governor._fade` touches no plan | a comment asking readers to be careful |
| A block comes back as an in-world redirect | `redirect.Redirect` carries a beat and a fallback line, never an apology | a refusal string |

### Nothing is on by default

A policy with no limits and a `suggestive` ceiling is **inert**. An inert policy
short-circuits to `ALLOW` at every surface, contributes **no prompt text**, and
draws **no RNG**. The flagship declares nothing and is inert; The Wicked Garden
declares `ceiling: explicit, default: explicit` in its `game.yaml` and is
deliberately not — declaring a rating is asking for the layer to run.
`tests/test_safety_shipped_games.py` asserts that each story gets exactly the
policy its manifest declares, and that an inert policy stays free.

There is deliberately **no `safety.enabled` flag**. An off switch on a safety
layer is one config typo away from turning hard limits off, and the layer costs
nothing when there is nothing to enforce. "Off" is a data state.

---

## The ladder

```
suggestive  <  explicit  <  extreme
```

`IntensityTier` is an ordered type, not a string, because `"extreme" <
"suggestive"` is `True` alphabetically and that bug fails in the one direction
that matters. Parsing never raises; junk lands on `suggestive`, so a typo makes
the game tamer, never coarser.

Two things can tell the layer what tier a piece of content **is**:

1. the caller declares one (`review_beat(text, declared="explicit")`);
2. `safety.tier_markers` — surface forms that say "at least this intense".

Markers may only ever **raise** the estimate, never lower a caller's own
declaration. They ship **empty**: writing down the words that mark explicit
content is the story owner's job, not the engine's. The key is declared in
`config/default.yaml` rather than omitted so the seam is visible and turning it
on is a config edit, not a code change. An empty marker set is not a hole — the
ceiling still enforces the tier a caller declares, and hard limits are enforced
regardless.

---

## The boundary sheet

```yaml
boundaries:
  hard_nos:
    - topic: some_topic          # the id that appears in logs and verdicts
      nouns: [word, "a phrase"]  # surface forms, matched on word boundaries
      note: why                  # for the log, never for the player
  soft_nos:
    - topic: collars
      nouns: [collar]
      substitute: throat-garland # cosmetic rename; identical mechanics
  green_lights: [topic]          # lifts a soft no. Never lifts a hard one.
```

A bare string is also legal (`hard_nos: [self-harm]`) and means topic-and-noun.

**Layering.** Config, then the story's manifest, then the player — same
"later wins" ordering `engine/config.py` uses for YAML layers. Merging is
**monotone on limits**: `BoundarySheet.merged_with` is the only combining verb
and it has no subtract, no `without`, no `clear`. Green lights resolve by layer:
a player's green light lifts a story's soft no; a player's soft no cancels a
story's green light; **no green light from any layer touches a hard no** — that
rule has no ordering, because "meta-consent is absolute" does not have one.

**`substitute` is soft-only.** A hard no is about a thing, not a word;
honouring a rename there would generate the content and launder the label. A
`substitute` declared on a hard no is dropped with a warning.

---

## The five dispositions of a turn

| Disposition | When | Prose | Mechanical outcomes |
|---|---|---|---|
| `ALLOW` | nothing to do | as written | **apply** |
| `SUBSTITUTE` | every soft hit offered a rename | renamed | **apply** |
| `FADE` | above the tier, or a soft hit with no rename | summary card | **apply** |
| `REDIRECT` | a hard no is present | in-fiction interruption | **do not apply** |

`FADE` applying its outcomes is the detail most implementations get wrong
(`06-UI-UX.md:208` — "Summary card if Fade used: mechanical outcomes still
apply"). A fade is a change of **camera**, not of **world**. It is enforced by
shape rather than by care: `Verdict` has no effects field, no deltas field and
no state handle, so there is nothing in it for a caller to apply and therefore
nothing that can fail to be applied. `governor._fade` is four lines and none of
them mention `effects`. `governor._redirect` is the one path that clears them.

If two things in a turn need different dispositions, the **strictest** governs
(`governor._stricter`), so the order plans happen to be iterated in cannot
change the answer.

---

## API

```python
from engine.safety import SafetyGate

gate = SafetyGate.for_state(state)          # per-session, cached policy
gate = SafetyGate.for_session(session_id)   # when there is no state to hand

gate.inert                       -> bool    # nothing to enforce; skip everything

gate.review_input(text)          -> Verdict # player input, before planning
gate.review_plan(plan)           -> Verdict # an AgentPlan (duck-typed)
gate.review_beat(text, declared=..., tags=...)  -> Verdict
gate.review_narration(text, declared=...)       -> Verdict

gate.rename(display_text)        -> str     # cosmetic substitution
gate.fade_card(verdict, summary=..., outcomes=...) -> FadeCard | None
gate.directive_text()            -> str     # standing constraint for the GM prompt
```

```python
verdict.disposition      # Disposition
verdict.allowed          # bool
verdict.outcomes_apply   # bool  <- True for FADE
verdict.blocked          # bool
verdict.redirect         # beat for the narrator, when blocked
verdict.fallback         # usable prose when there is no model
verdict.summary_hint     # instruction for the summariser, when faded
verdict.reasons          # ("hard:topic", "ceiling:extreme>suggestive", ...)
verdict.substitutions    # {"collar": "throat-garland"}
verdict.to_dict()        # for the turn journal and telemetry
```

`reasons` goes to the **log**, never to the player. The character must not
recite the player's own limit sheet back at them
(`SOPHIA-VOICE-BIBLE.md:98` — "safety is UI, not her morality monologue").

### The ratchet

```python
policy.with_intensity(tier, actor=Actor.PLAYER)  # may raise, up to the ceiling
policy.with_intensity(tier, actor=Actor.AGENT)   # min(). always. no exceptions
policy.with_intensity(tier)                      # defaults to AGENT
policy.with_limits(sheet)                        # union only
```

`Actor.AGENT` is the default so a caller who forgets the argument gets the
restrictive behaviour. `Actor.STORY` is refused at runtime — a story's authority
is exercised through `resolve()` at load time, and a runtime story-level raise
would be a story rewriting a player's dial mid-scene.

### It cannot take a turn down

Every public method is wrapped. An exception inside this package is logged and
turned into a documented fallback, never re-raised. Fallbacks differ per seam,
because "safe" means a different thing at each:

- `review_input` → `ALLOW`. It is the first of several checks; refusing to let
  a player type because of a bug in the matcher is an outage dressed as caution.
- `review_beat` / `review_narration` / `review_plan` → `FADE`. It is the one
  disposition that is simultaneously safe and non-blocking: the turn completes,
  the outcomes still apply, and the prose the layer failed to inspect is not
  shipped.
- `rename` → the input, unchanged.
- `directive_text` → `""`.
- An **inert** policy falls back to `ALLOW` everywhere, so a story with nothing
  configured cannot be made worse by a bug in a layer it is not using.

### What the directive block says, and does not

It names the tier and the limit **topics**. It never lists the limit **nouns**.
Enumerating the exact surface forms a player does not want to read puts those
words in the context window, where the sampler can reach them — a prompt that
lists what not to write is a prompt that has written it. The topics are enough
to steer; the enforcement is the gate, not the paragraph. That is the
"structurally, not by prompt text" requirement applied to the prompt text
itself.

---

## Attach points

Five. Two are already declared for this layer by
`engine/agents/governance.py::TurnContext` (`intensity`, `safety_block`) and
`engine/agents/negotiate.py::NegotiatedTurn` (`blocked`, `block_reason`).

### 1. Player input

Wired: `engine/scenes/default_state.py::_review_input`, called at
the top of the turn handler, before anything is planned.

A hard-no hit here is a `REDIRECT`, which means the turn **still runs**: the
player asked for something the session has ruled out, and the fiction declines
rather than the interface refusing. The redirect **beat** — never
`verdict.reasons`, which name the player's own limits — is threaded into the
turn as the pipeline's `safety_block`, so the narrator declines in-world.

### 2. `PHASE_DIRECTIVE` — the standing constraint

`SafetyDirective`, priority 10, so it sits at the top of the directive block
rather than after three paragraphs of evil-phase tone. Built from an empty seed
and budgeted by `context.build_storyteller_messages` like every other block —
it does not go near `run_pre`, which is R-01.

Contributes `""` for an inert policy, so neither shipped game pays a token.

### 3. `PHASE_COMMIT` — the decision

`SafetyCeiling`, priority 10. Reads `ctx.plans`, `ctx.negotiated`,
`ctx.narration`. Writes `ctx.intensity`, `ctx.safety_block`, `ctx.metadata`.

Runs **before** `tx.commit()`, which is the whole point: `PHASE_POST` runs after
the commit, so a hook there can record that something was wrong but cannot stop
it. A ceiling that can only file a report is not a ceiling.

It deliberately does **not** set `ctx.veto`. A veto rolls the whole transaction
back including the clock; a limit reached mid-scene should cost the player the
scene, not the hour. The redirect path clears the offending plan's effects
instead — the same refusal at the right granularity.

### 4. Narration — the last line

Wired: `engine/agents/storyteller.py::run_turn`, after the retry loop and
**before** `tx.commit()`, reviews the final prose. `REDIRECT` rolls the
transaction back and ships the in-fiction fallback line — "this did not
happen" is made true, not asserted. `FADE` keeps every mechanical outcome
(nothing touches the transaction), replaces the prose with the fade line, and
attaches the built card as `StorytellerTurnResult.fade_card`, which rides out
in the turn payload as `fade_card` beside `safety`. `SUBSTITUTE` runs
`gate.rename` over the prose. An inert policy short-circuits: no review, no
RNG, no new payload keys.

Weakest of the surfaces, because by the time there is prose the turn is already
planned. It exists because the earlier surfaces read intent and this one reads
what was actually written.

### 5. Display strings — cosmetic substitution

```python
# wherever an item, location or choice label is rendered for the player
label = SafetyGate.for_state(state).rename(item.display_name)
```

`DAY-01-GUEST.md:152` — an item renames itself when its noun lands on a player
limit, "same mechanics, cosmetic rename from boundaries". `rename` is a pure
string function whose only parameter is display text: **it cannot be handed an
id**, so the renamed thing cannot diverge mechanically from the thing.
`tests/test_safety.py::TestCosmeticSubstitution::test_rename_cannot_be_handed_an_id`
asserts the signature.

---

## Wiring status

The mechanism is wired into the running turn. Where each seam lives:

| What | Where |
|---|---|
| Both hooks registered | `engine/agents/governance.py`, bottom of module — `register_safety_interceptors()` runs at import, after `interceptor`/`register` are defined |
| Commit chain read from config | `engine/agents/governance.py::GovernancePipeline.from_config` reads `governance.commit`; `config/default.yaml` names `SafetyCeiling` there and `SafetyDirective` in `governance.directives` |
| The commit chain is called | `engine/agents/pipeline.py::_govern_commit` runs `GovernancePipeline.run_commit` over the negotiated turn **before** the `StateTransaction` commits; `governance.commit` is on the manifest `SETTING_ALLOWLIST` (`engine/games/manifest.py`) so a story can declare its own chain. Tests: `tests/test_governance_commit.py` |
| Stale policies dropped on a game swap | `engine/games/caches.py` `RELOADERS` includes `engine.safety.reset_policies` |
| Player-input review | `engine/scenes/default_state.py::_review_input` — attach point 1 |
| Narration review + fade card | `engine/agents/storyteller.py::run_turn`, after the retry loop, before the commit — attach point 4 |
| The RNG stream | `SAFETY_REDIRECT = "safety.redirect"` lives in `engine/game/rng.py` with the other named streams; `engine/safety/redirect.py` imports it |
| The player dial | `safety.intensity.player` in `config/default.yaml`, written by the Settings screen (`engine/api/settings.py`), clamped to the story ceiling at policy construction |
| Fade-card render | `ui/src/core/parts/FadeCard.jsx`, drawn by `Play.jsx` under the log from `state.fadeCard`. Per-turn and not sticky: the card belongs to the scene that faded. Typeset as an authored beat rather than as a warning — a fade is a cut, not an error — and the outcomes are the loudest thing on it, because a player who reads a fade as "nothing happened" re-does something already done |

### NOT WIRED

| What | File | Status |
|---|---|---|
| Cosmetic rename on display | producer: `engine/safety/boundaries.py::BoundarySheet.rename` (wired for prose). Consumer: none — `ui/src/core/parts/ChoiceRow.jsx`, `ui/src/core/parts/Meters.jsx` and every story's inventory view render raw labels | attach point 5 — `gate.rename` covers narration prose, but display labels (items, locations, choices) are rendered without it. Re-checked 2026-08-14: `grep -rn rename ui/src/` returns nothing at all. A later UI phase |

---

## Configuration

### `config/default.yaml`

| Key | Default | What |
|---|---|---|
| `safety.intensity.ceiling` | `suggestive` | highest tier a story with no `safety:` block may be played at |
| `safety.intensity.default` | `suggestive` | where a new session's dial starts |
| `safety.intensity.player` | `"story"` | the player's standing dial, written by the Settings screen into `config/local.yaml` (`engine/api/settings.py`). `"story"` means "follow the active story's default"; a tier name overrides it, clamped to the story ceiling — lowering is always honoured, raising past the ceiling never is |
| `safety.fade.available` | `true` | offer the Fade control (the automatic collapse happens regardless) |
| `safety.aftercare.default` | `false` | request an aftercare beat after an intense scene |
| `safety.boundaries.hard_nos` | `[]` | deployment-wide limits |
| `safety.boundaries.soft_nos` | `[]` | |
| `safety.boundaries.green_lights` | `[]` | |
| `safety.tier_markers.explicit` | `[]` | surface forms marking the tier — see above |
| `safety.tier_markers.extreme` | `[]` | |

### `games/<slug>/game.yaml`

A **top-level** `safety:` block, not a `settings:` entry:

```yaml
safety:
  intensity:
    ceiling: extreme      # what THIS story is written for. `max` is accepted
                          # for compatibility; `ceiling` is the documented
                          # spelling and the one The Wicked Garden declares
                          # (engine/safety/policy.py)
    default: suggestive   # where its dial starts
  boundaries:
    hard_nos: [{ topic: ..., nouns: [...] }]
    soft_nos: [{ topic: ..., nouns: [...], substitute: ... }]
  tier_markers:
    explicit: [...]       # replaces the engine's; genre-specific by nature
  redirects:              # replaces the shipped pack
    - { id: moth, tags: [interruption], beat: "...", line: "..." }
  fade_available: true
  aftercare: false
```

**Why top level and not `settings:`.** `GameManifest` keeps every unknown
top-level key verbatim in `extras` — that is also how `ui:` reaches the games
API without the dataclass learning about it — so a story declares its content rating with **no
change to `engine/games/manifest.py`** and, more importantly, without the block
passing through `config_overlay()`, which would make a story's rating a config
value that a stale `config/local.yaml` could move. `to_dict()` emits `extras`,
so `GET /api/games` shows a story's rating to a picker for free.

If the maintainer prefers `settings:` instead, the `SETTING_ALLOWLIST` entries
would be `safety.intensity.ceiling`, `safety.intensity.default`,
`safety.fade.available`, `safety.aftercare.default` — all four describe the
story's shape and a wrong value costs the player nothing but a different game,
which is that list's stated test. `safety.boundaries.*` should **not** go on it:
a story that could write into `safety.boundaries` through the config overlay
would be a story writing a config key that a player's own sheet later merges
with, and the layering would have two homes.

### Player settings

Passed to `resolve(player=...)` and installed with `set_policy(policy,
session_id=...)`:

```python
resolve(player={
    "intensity": "explicit",
    "boundaries": {"hard_nos": [...], "soft_nos": [...], "green_lights": [...]},
    "fade_available": True,
    "aftercare": False,
})
```

The sheet lives in a process-local store keyed by `GameState.session_id`
(`engine/safety/policy.py`), **not on `GameState`**. Putting it in the state
object would put it in the save file, in the state schema's `owners` table, and
therefore within reach of anything that can propose a state delta. The thing
that must sit above the agents must not be stored in the thing the agents write
to. `tests/test_safety.py::TestResolution::test_the_boundary_sheet_is_not_game_state`
asserts it.

---

## Scope

The **suggestive tier and the machinery** are what ships here. The shipped
redirect pack is genre-neutral by construction — a door, a sound, an errand, a
change of weather — and no prompt pack, marker vocabulary or scene content for
the explicit tiers is authored in this package. Those are the story owner's to
write, and the config keys are declared empty so that writing them is a data
edit.
