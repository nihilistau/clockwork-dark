# HUE & CRY — design

Status: **approved in conversation 2026-09-23, section by section.** This file is
the written form of that approval. Where it and the code later disagree, the
code wins (CLAUDE.md authority order) and this file gets corrected.

## Goal

Six releases, in order. Originally planned as three (v0.8, one v0.9 covering
all four engine features, v1.0); re-cut per-feature after v0.9.0 shipped, so
each feature ships as its own release rather than sitting unpushed for weeks
while the rest of the batch finishes. Re-cut again (owner, 2026-09-25) once
the four engine features shipped: what was a single v1.0.0 at the end now
ships as its own run of point releases, for the same reason as the first
re-cut -- content, UI and art are as large a batch as the four engine
features were, and `v1.0.0` is tagged only once the last of them lands:

| Release | What | Why this order |
|---|---|---|
| **v0.8** | The audit fixes (§1) | Presence and the evaluator are prerequisites: a thief story in which the narrator does not know who is in the room cannot be built |
| **v0.9.0** | Premises (§3), plus the HUE & CRY skeleton | Shipped -- proven first because a thief needs a city before it needs a law, a job or an agenda |
| **v0.10.0** | The Law (§2) | Next -- reads the `noticed`/witness groundwork Premises and thievery already lay down |
| **v0.11.0** | Jobs & flashbacks (§4) | Depends on Premises (a job opens on a premise) and the Law (an alarm summons the watch) |
| **v0.12.0** | Agendas (§5) | Last of the four -- deterministic world motion, proven once the other three systems exist to move around |
| **v0.13.0** | Engine seams for HUE & CRY's finish (§6): secret places, custody + jailbreak, forced/repeatable decks, a terminal death, the clarity word, `generate_art --game` | Shipped -- closes the small seams the four engine features left before §6's content can be built on them |
| **v0.14.0** | Living city: survival, forage + Rooftop Road's hidden paths, labour, boons, night encounters, factions, city lore | Next |
| **v0.15.0** | Guild economy: crafting, the Magpie's Hoard, blackmail and fence-credit threads, Brask's gate | |
| **v0.16.0** | Acts I--II: arcs, initiation deck, interrogation deck, the Magpie reveal, the alibi beat | |
| **v0.17.0** | Act III + eight endings: the Hanging Fair event and fair-day deck, the jailbreak, The Rope via `death.yaml`, per-ending tests | |
| **v0.18.0** | `simulate.py`'s thief policy | |
| **v0.19.0** | The HUE & CRY UI plugin: wanted poster, casing board, job panel, portraits | |
| **v1.0.0** | HUE & CRY finished (§6): the art pack (~55 Grok plates) and live play | Tagged only once this lands |

Every feature is **generic**: a story that does not declare its `paths.*` key
pays nothing and its turns stay byte-identical, asserted by test the way
`tests/test_scene_director.py` asserts it for decks.

## Non-goals

- Retrofitting the Law onto the four existing stories. neon-city's `heat` is the
  natural later candidate; recorded as **NOT WIRED** in `docs/GOVERNANCE.md`.
- Converting the flagship's doom clock into an agenda.
- Moving world ticks off wall-clock time (R-03's fix, deliberate).
- Any content-rating layer, in any form (CLAUDE.md rule 12).

## Cross-cutting rules for everything below

1. **The new systems advance on in-game hours inside `clock.advance_time`,
   never on the background world tick.** Whether a guard hears about a crime
   must replay from the seed and the choices, not from how long the menu was
   open. Each system draws its own `world_rng` stream: `LAW`, `AGENDA`, `JOB`;
   premises draw on their own `PREMISES` stream, seeded after every `PROCGEN`
   draw so the flagship (which declares no premises) still generates a
   byte-identical village.
2. **Every state write goes through `effects.apply_effect`** (rule 3). New
   effect kinds are added there, not beside it.
3. **Every mechanic reaches the narrator** as a prompt block with band words for
   veiled values, and reaches the player as a UI surface. "Is it called?" and
   "does the narration know?" are both acceptance criteria.
4. **Every new entry point has a production caller** — `tests/test_reachability.py`
   must pass with no new allowlist row.
5. **Illegal targets are unsamplable.** New verbs join `engine/game/intents.py`
   with enums built per turn from what the engine will accept; an intent that is
   illegal at execution produces an engine-authored refusal.

---

## §1 — v0.8, the audit release

All repair, no new mechanics. Each group ships with tests that fail against the
code before it.

**A1. People are present in every story.** `present_npc_ids`
(`engine/memory/context.py:59`), `_npcs_present_block`
(`engine/agents/prompts.py:302`) and `known_npc_ids`
(`engine/scenes/default_state.py:~738`) take the cast from `npc_sim` instead of
returning early on an empty `state.procgen.npcs` — which is empty for every
story but the flagship. The flagship keeps its procgen villagers merged in. This
turns on, for four stories at once: dossiers, `ledger.meet`, disposition,
gossip, and a cast gate that no longer rejects an NPC standing at their own
stall. `_dossier` looks names up by npc id, not by proper noun, so it stops
printing `npc_maris (npc_maris)`.

**A2. The evaluator reads outcomes.** Every rolling receipt counts as a roll
(`work`, `forage`, `challenge`, `card`, `encounter`, not only `roll_dice` /
`resolve_skill_check`). A narrow contradiction check flags prose that states
the OPPOSITE of the receipt — success narrated over a failed check, arrival
over a refused move — and fires only on unambiguous opposites, measured against
fixtures of both kinds.

**A3. "The world moved" block.** One prompt block fed by the return values
currently discarded: clock-beat `text:` (`clock.py:172`), world-event text
(filtered to the player's location, capped, expiring), promises that expired
unkept (`default_state.py:763`), veiled meters crossing a band, reputation band
changes, and a present NPC holding fresh gossip about the player. One line
each, only on the turn it happened.

**A4. Leaks closed.** `pipeline.narration_block` honours the receipt's
`visibility`, so veiled meters reach the narrator as band words. `receipts_block`
gets a per-kind summariser instead of a dict dump (a forage receipt measured
~1,600 chars including DCs). `scene_begin` stops listing the hand.

**A5. Storyteller disposition is story-declared.** `cruelty_bias` and
`reward_generosity` become optional `settings:` keys. A story that sets neither
gets no disposition line — today "be merciful with consequences" reaches every
story, noir included, because nothing writes the field and its default trips
the `<= 0.2` test. The patience ratchet gets a floor that recovers.

**A6. Correctness.** Vendors trade only where their schedule places them.
`merge_choices` reserves a slot for agent choices. `economy.py` writes
reputation through `apply_effect`. A deck that deals nothing is marked spent. A
forced scene with no target warns once, not every turn. A pipeline failure
degrades the turn instead of killing it. The objectives block names the real
`flag` intent and omits raised flags. The currency label comes from the story.
Flagship words leave the tone scorer and `"her words"`.

**A7. World events are story-declarable.** `world/schedules.py` fires only three
hardcoded flagship ids. Any story's `world_schedules` may now declare an event
with a location, a window and `text:`. The flagship's procgen festival — which
nothing reads — fires on its day through the same path.

**A8. Dead code.** The unread turn-schema fields `npc_voices`, `mood`,
`image_tag` (grep `ui/src` first); `engine/agents/turn_loop.py.bak`;
`stack.wait_timeout_seconds`; the unused import in `storyteller.py`; stale
docstring and `Version:` lines. The orphan comment at `default_state.py:835` is
a remnant of the removed layer and is **deleted, not completed** (rule 12).
`MediaGovernor` has no caller: deleted, not wired. Hunger uses the story's own
thresholds.

---

## §2 — The Law

`engine/world/law.py`, driven by `data/rules/law.yaml` via a new `paths.law`.

```yaml
roles: [watch, sergeant, captain, magistrate]   # schedule roles that ARE the law
reporters: {vendor: 0.3, servant: 0.5}          # chance a witness goes straight to the watch
jurisdictions: {dockside: [tallow_docks, wickmarket], ...}
deeds:
  pickpocket: {severity: 1}
  loitering:  {severity: 0}      # casing: remembered, never reported alone
  burglary:   {severity: 3}
  fencing:    {severity: 2}
  assault_watch: {severity: 5}
wanted:
  bands: [unknown, noticed, sought, wanted, hunted]
  thresholds: [0, 2, 5, 9, 14]
  cool_per_day: 1.5
precision: {1: 1.0, 2: 0.6, 3: 0.3}              # per hop
arrest:
  gaol: lantern_house_cells
  approaches:                                     # encounter-shaped, same schema
    run:       {skill: stealth,    band: standard}
    talk:      {skill: persuasion, band: hard}
    bribe:     {cost_per_severity: 5}
    surrender: {}
    fight:     {skill: nerve, band: hard, deed: assault_watch}
  fine_per_severity: 6
  days_per_severity: 1
```

Every number in this block is a **starting point, not a decision**: each is set
by `scripts/simulate.py` runs with the new thief policy before it ships
(CLAUDE.md rule 10).

**Deeds and witnesses.** An intent may carry `deed: <kind>`; the thief verbs emit
one automatically. On execution the engine computes candidate witnesses —
everyone `npc_sim` places there at that hour, plus any premise household at
home — and rolls each on `LAW`, weighted by light (`time_of_day`), the margin of
the player's stealth result, and the current guise. Each witness gets an
**engine-sourced** ledger fact (`kind="witness"`). The narrator receives who saw
and how clearly BEFORE it writes; "nobody saw" is a result the prose must honour.

**Guises.** What a witness files is the guise worn: `self`, `magpie`, or any item
with a `guise:` field (a porter's smock files as "a porter"). Changing guise is
an intent. Being seen changing links the two guises in that witness's memory.
The watch starts the story holding the link `self = magpie`; breaking it with
evidence is the spine.

**Reports.** A law pass inside `advance_time` moves witness facts person to
person on in-game hours, reusing `gossip.retell` / hop decay. Witness facts are
owned by this pass; the background gossip skips `kind="witness"` so nothing
travels twice. A witness fact reaching an NPC whose role is in `roles` becomes a
**report** (district, deed, severity, precision). `reporters` short-circuits.

**Wanted** per guise per jurisdiction = Σ severity × precision, stored as a
veiled value family; cools `cool_per_day` with no fresh report. A bribed
sergeant quashes reports through a **thread** — corruption is a contract with
terms.

**Patrols and arrest.** Law NPCs' schedules are their patrols. Arriving where a
law NPC stands while the current guise is ≥ `sought` rolls recognition on `LAW`,
weighted by precision. A hit runs a contested scene through `encounter.py`
machinery with the `arrest.approaches` (run/stealth, talk/persuasion, bribe/coin,
surrender, fight/nerve — itself a severity-5 deed). Arrest: move to `gaol`,
confiscate stolen-provenance goods, offer fine / serve (days through
`advance_time`) / break out (a deck or set piece). A sentence always ends and the
cells have rest (rule 6).

**Narrator:** LAW block — witnesses to the last deed and their clarity, wanted
band per guise here, law NPCs present. **Player:** wanted chrome (§6).

## §3 — Premises

`paths.premises` → `data/premises/{types,anchors}/*.yaml`. Generated once at new
game on the `PREMISES` stream (drawn after `PROCGEN`, never on it), stored on
`GameState`.

A district location declares what it holds:

```yaml
silk_row:
  premises: {count: 6, types: {townhouse: 3, counting_house: 2, manor: 1}}
  anchors: [vessaline_manor]
```

A premise is a **target inside a district, never a travel-graph node** — map,
travel, validation and location art are untouched.

A **type** declares: name pools; wealth tiers (scaling everything below); a
**household** (roles with routine templates — these become real schedule rows
merged through the path procgen villagers already use, so they are present,
witness, gossip, can be lifted, and are named in the ledger); **security** drawn
by tier (lock DC, bolts, dog, watchman, strongroom, bells, warded chest);
**loot** by tier (real registry items); **one secret** from a pool (a lever: an
item or fact that opens a blackmail thread or feeds a quest). **Anchors** are
authored premises with the same schema and hand-written contents.

The spine hooks the generator: the seed hides the real Magpie's trail in a few
generated premises, so casing and burglary are also the investigation.

**Verbs.** `case <premise>` (1–3 h in the district): reveals the next intel item
in seeded order — occupancy windows, one security feature at a time, loot hints,
that a secret exists — stored on the premise and filed as an engine fact; emits
`loitering`. `lift <npc>`: stealth vs alertness on a present NPC, purse table
per role, `pickpocket` deed.

**Provenance.** Goods taken in a deed carry `{from, whom, day}` in a provenance
ledger. Honest vendors refuse hot goods and may report the attempt (`fencing`
deed). Fences (`fence: true` trade profile) buy at a cut set by heat. Heat fades
over days; named pieces stay hot until a specialist fence launders them.

**Narrator:** DISTRICT block — premises here and what is known of each.
**Player:** a casing board panel with an "empty now" marker computed from
schedules. One plate per premise type × day/night.

## §4 — Jobs & flashbacks

`paths.jobs` → `data/rules/jobs.yaml`; runtime in `engine/world/jobs.py`,
stream `JOB`.

`burgle <premise>` opens a job held in state. Each turn's choices ARE the current
stage's approaches (enum built from the stage). Five stages derived from the
premise: **approach** (street witnesses at that hour), **entry** (door, window,
roof, cellar — skill + band from security), **inside** (household members home
now are the obstacles), **the score** (strongroom lock/ward, loot draw, the
secret if known), **getaway**.

Intel and carried tools modify stages (a known unlatched window: hard → trivial;
lockpicks drop a band; the cook's night off removes an obstacle). The narrator
is told which prep paid off.

A per-job **alarm** clock: a failed approach yields noise (alarm +), seen (that
household member becomes a Law witness), hurt, or abort. Full alarm wakes the
house and summons the watch after a district-set delay.

**Flashbacks.** `flashback <kind>` mid-job, kinds authored in `jobs.yaml`, each
with a legality test against real history (`visited`, trade profiles, casing
count, threads, disposition): *bribed a servant*, *planted a tool*, *knew the
rota*, *a friend inside*. Cost: the veiled `prep` meter (earned by casing,
restored between jobs), coin where apt, and **exposure** — the retroactively
bribed servant becomes a real witness. Never time: the clock only moves forward
(rule 2).

**Guild contracts are threads**: premise + target item + fee + deadline + the
guild's cut. Anchored premises are authored jobs with extra stages. **Hired
hands** (optional): a guild NPC removes one stage's check, takes a cut via a
thread, and is a witness who may later sell you out.

**Narrator:** JOB block — stage, obstacle, what prep did, alarm band.
**Player:** job panel — stages, alarm, prep.

## §5 — Agendas

`paths.agendas` → `data/rules/agendas.yaml`; `engine/world/agendas.py`, inside
`advance_time`, stream `AGENDA`. Deterministic and authored — no model planning;
the roster's LLM agents are separate and unchanged.

An agenda: **owner** NPC, **goal**, a **clock** (the existing clock machinery —
thresholds, beats, `forces_scene` for free), **moves** (gate predicate, target
selector, effects via `apply_effect`, what it leaves behind), **reactions**
(triggers on engine events: a report reached the captain; the player robbed a
premise the guildmaster owns; wanted ≥ hunted). Selectors are deterministic:
`premise {district, wealth_min, not: robbed}`, `fence {most: hot_goods}`,
`witness {knows: self}`.

**Visibility.** Moves the player could know — witnessed, heard via gossip
reaching someone present, or posted on the notice board — enter the §1 A3 block.
Moves nobody told them about stay in state as discoverable clues; the narrator
gets only the clock's GM-facing `label:` and band, with the standing instruction
to foreshadow, never reveal (the `_clocks_block` pattern).

## §6 — HUE & CRY

Slug `hue-and-cry`. Register: **QfG warmth, real stakes** — wry, affectionate,
funny in the moment; the gallows are real and betrayal lands.

**Tallowmere**, a candle-making port lit by the Everflame, a holy fire kept in
the Margrave's palace. The Magpie only ever steals things that shine.

**Districts (11):** Tallow Docks (entry; customs-house anchor), Wickmarket (shops,
two fences), The Snuffs (slum, flophouse, guild hidden here), Silk Row
(townhouses, counting-houses), Chandlers' Rise (trade halls, Temple of the
Everflame), The Lantern House (watch HQ, gaol), Margrave's Hill (palace wings,
treasury anchor), Gallows Green (hangings, the Hanging Fair), The Undercroft
(sewers, `secret: true`), The Rooftop Road (procgen hidden paths), Old Bell Tower
(`secret: true`).

**Cast (~14):** Captain Ardane of the Lantern Watch ("Lanterns"); Mother Gannet,
head of *the Honest Company of Night Porters* (a thieves' guild that is a
porters' union on paper — hence the porter's smock); Silas Crook "the Dapper",
the upstart; two fences; a bribable sergeant; the Margrave's steward; Wren the
lamplighter; Lady Imelda Vessaline; others. **Pip**, a one-eyed jackdaw who
insists he is a magpie — the companion, and a **pipeline** agent, so every turn
negotiates city vs Pip.

**The real Magpie is chosen by the seed** from Wren, Silas and Imelda. The
agenda, the robbery pattern and the evidence trail follow; `spoilers.yaml` masks
the name until earned.

**Spine**, ~10–12 in-game days. **I — Hue and Cry:** off the barge, a Lantern
shouts "the Magpie!"; the opening's three choices declare intents (run — a
stealth check and a deed; talk — persuasion; come quietly). The guild takes you
in, believing it too. Initiation is a deck. **II — Honest Work:** contracts as
threads, casing and jobs, the Magpie's robberies landing on your name, evidence,
the upstart, the captain's clock. **III — The Hanging Fair:** an A7 world event;
the Everflame's heart on display; the fair day is a deck forced by the event.

**Endings (8, all reachable, each with an epilogue):** Cleared · Partners · The
Legend · Guildmaster · The Dapper's City · Honest After All · A Lantern · The
Rope (fail-forward, QfG death-screen humour). Held by `tests/test_finales.py`.

**Also used:** archetypes (Cutpurse, Silver-tongue, Bruiser); the seven default
skills; light survival (flophouse, guild bunks, taverns); scrounging forage
nodes; crafting at the guild workshop (lockpicks, smoke pellets, disguises,
forged passes); a collection (*the Magpie's Hoard*, six legendary shinies);
threads (contracts, bribes, blackmail, fence credit); seven factions; night
street encounters; the jailbreak set piece; the interrogation deck (forced on
arrest); agenda clocks; city lore via RAG; notice board (jobs and wanted
posters); labour, trade, boons. **Not used:** the doom clock (its phases are
flagship canon; Ardane's agenda does that job).

**UI plugin `hue-and-cry`:** warm wax-and-parchment skin, seal-red accent; a
**wanted poster as chrome** whose sketch sharpens as the watch's precision
rises; the casing board; the job panel.

**Art:** ~55 Grok plates — 11 districts × day/night, 14 portraits, 8 premise
types × day/night, key items. The entry location has a plate.

## Acceptance

- `pytest` fully green, no xfail; `npm test --prefix ui` green; committed `dist`
  fresh.
- `tests/test_reachability.py` passes with no new allowlist row.
- Byte-identical turns for stories that declare none of the new paths.
- Seed replay: the same seed and choices produce the same witnesses, reports,
  agenda moves and job rolls, independent of background ticks.
- `scripts/simulate.py` gains a thief policy; agenda collisions measured across
  ≥40 seeds and reported in the CHANGELOG.
- All eight endings driven to epilogue by test.
- Played live against LM Studio; every plate seen rendering in the browser pane.
- CHANGELOG entry per release; commit subjects are version numbers.
