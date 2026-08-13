# The Wicked Garden — world content

Everything in this tree is **world content**: places, objects, people, lore and
art direction. The mechanical spine — `game.yaml`, `state.yaml`, `agents.yaml`,
`data/rules/**` and `scenes/**` — is authored separately and is not described
here except where this content depends on it.

Source of truth for every id, in this order:

1. `Design_files/Wicked-Garden/docs/design/agents/state-dictionary.json`
   — **authoritative** over the prose docs wherever they disagree.
2. The design docs under `Design_files/Wicked-Garden/docs/design/`.
3. The concept pack under `Design_files/Wicked-Garden/concept/`.

Content is rated **explicit** — the ceiling and default declared in
`game.yaml`. Atmosphere, tension, power and threat are the spine, and the
narrator may take the marked hooks in the day chapters to the explicit
register the run is set to. The player can lower the working intensity at any
time from the Settings screen; lowering is always honoured, raising past the
declared ceiling never is.
Everyone depicted is an adult; the design says so repeatedly and so does this
content, including in the negative prompt of `art/subjects.yaml`.

---

## What is here

| File | Contents |
|------|----------|
| `world/locations.yaml` | 14 places — the 13 real locations plus the `unknown` sentinel. 42 edges. |
| `items/garden.yaml` | 23 items, the complete `inventory.item_ids` list. |
| `world/npc_schedules.yaml` | 8 NPCs on 24-hour routines. Sophia is **not** here — see below. |
| `world/factions.yaml` | 7 factions: the crowds the relationship board does not track. |
| `world/rumors.yaml` | 19 rumours across 3 awareness tiers. |
| `world/schedules.yaml` | The engine's three world-event slots, filled with Garden events. |
| `tables/collections.yaml` | 5 reliquary sets, a disjoint partition of all 23 items. |
| `lore/*.md` | 14 files, 95 chunks, scope-tagged. |
| `art/subjects.yaml` | One art source, two prompt dialects, covering all 14 places, 9 portraits and 23 items. |

---

## Sophia is an agent, not an NPC

She is the ninth name in the state board's `relationships` block and the only
one of the nine that is a **character agent**. She has no entry in
`world/npc_schedules.yaml` and must not get one: a scheduled Sophia would stand
in the Heart Grove "receiving petitioners" while the real one is in the
player's room. Where she is is a thing she decides.

She *does* have an entry in `art/subjects.yaml → portraits.sophia`, because a
face is not dialogue and that entry is the story's consistency lock.

No voice bible, no dialogue and no lines are authored anywhere in this tree.

---

## Knowledge scopes in the lore

This is the first content in the project to use `engine/agents/knowledge.py`.
The mechanism, exactly: `engine/lore/manager.py::chunk_markdown` extracts every
`#word` in a chunk as a tag, and `search(..., scopes=...)` withholds a chunk
**only** when one of its tags *names a scope* and the caller was not granted it.
Every other tag is ordinary metadata. An untagged chunk is public.

So there are three states a chunk can be in, and two of them require no markup:

| Chunk | Markup | Readable by |
|-------|--------|-------------|
| Public world knowledge | none | every agent |
| The world's secrets | `<!-- scope: #gm_secrets -->` | the GM agent only |
| Sophia's own interiority | `<!-- scope: #character_private -->` | the Sophia agent only |

The tag is carried in an HTML comment rather than as bare text because the
chunk body is fed verbatim into a prompt, and a naked `#gm_secrets` on its own
line reads to a model as an instruction.

Current split: **95 chunks — 78 public, 15 `gm_secrets`, 2 `character_private`.**

The two private chunks are `The Soft Century` and `Why This One`, both in
`lore/sophia_the_rose_sovereign.md`. They are the two facts that make her a
person rather than an antagonist, and the world narrator must not be able to
confirm or contradict either of them while she is still keeping them.

The fifteen `gm_secrets` chunks are the ones where the world knows something
the character does not, or knows the true version of something she believes a
prettier version of — most sharply `How She Actually Got The Seat` and `What
She Does Not Know About Her Own Reign`, both of which are *about* her and both
of which she is deliberately not allowed to read.

This only takes effect if `agents.yaml` grants the scopes. With no grants both
agents see the 78 public chunks and nothing else, which is the safe default.

---

## The location graph is a demiplane, not a road network

Three rules, each a sentence of the design spent as a number the loader already
enforces:

- **Toward her is free.** Every edge whose destination is `heart_grove` costs
  0 hours. Every edge leaving it costs 1–3.
- **Inward is shorter than outward.** The two directions of an edge carry
  different numbers throughout.
- **The door is one-way.** `mortal_threshold → gate_of_briars` is `one_way`
  and there is no return edge anywhere in the file. **Going home is an ending,
  not a travel action.** If the spine needs a travellable exit, that is a
  deliberate change to make here, not an oversight to repair.

`unknown` is declared as a real place with one `one_way` exit into
`guest_house`. Nothing can travel *to* it; a scene or an effect puts you there,
and the exit exists so a sentinel cannot become a soft-lock.

Every `danger_dc` is `0`. This story has no encounter tables and no dice, and
`tests/test_encounter.py` rightly asserts that a dangerous edge must have
content behind it. Pressure is carried by `hours` and `awareness_delta`.

---

## Awareness is the depth gauge

Nothing else in this story writes `state.awareness` — there is no doom ticker
and there are no encounters — so the only source is the `awareness_delta` on
travel edges, and those are weighted by depth (guest house 0, first court visit
2, labyrinth 3, Briar's Deep 4).

That makes the three rumour tiers in `world/rumors.yaml` a map rather than a
difficulty curve: the Garden tells you the truth in proportion to how far in
you have walked. A player who stays in the pretty rooms hears pretty things
until the bill arrives.

---

## Items

`value: 0` throughout, on purpose: there is no coin here and the Night Market
quotes prices in years and syllables. A non-zero value would let a barter
overlay sell the collar she fastened on your throat.

`use:` effects are restricted to `value`, `flag`, `ledger_fact`, `item` and
`remove_item`. `check_penalty`, `stat`, `awareness` and `heal_wound` are all
live engine kinds and all **dead in this story**, which declares no pools and
no checks. Every `value` name used appears in `state.yaml`; every `flag` name
used appears in the state dictionary's `flags.booleans`.

Four items are wearable and **none carries a skill bonus**, for the same
reason. What `equip:` buys here is a social fact held in state and visible to
both agents — and the engine's `charm` slot holds exactly one thing, so
`collar_soft_thorns`, `thorn_ring` and `ashen_clasp` are mutually exclusive.
That is the Act II dilemma expressed as one line of data.

Five items are deliberately verbless: `ashen_passport`, `seed_of_becoming`,
`briar_key`, `thorn_of_proof` and `true_name_shard_sophia_partial`. A key's
verb belongs to the door, and speaking her name is a scene with two agents in
it — not something to fire from a pause screen.

The three ids with no authored card are marked in the file where they are
defined:

| Id | Authored from | Role |
|----|---------------|------|
| `pressed_court_schedule` | `DAY-01-GUEST.md:76` | The reliquary tutorial object: first pickup, first `use:` verb, first evidence a guest was here before you. |
| `frost_thread` | `DAY-04-ASHEN.md:166` | The lighter half of the Ashen bargain — the passport is a route, this is one use of one. |
| `sap_sketch` | `DAY-06-ROOTS.md:72` | The only **player-made** object in the reliquary. Carries the `self_made` tag, which nothing else does. |

---

## Concept art: what exists, what does not

The story now ships its own art pack: `game.yaml` declares
`art_root: data/art/plates` and `art_manifest: data/art/manifest.yaml`, served
over `/story-art/...`. The live record of which subjects still lack a plate —
with generated prompts for each — is `art/MISSING-PLATES.md` (rebuild it with
`scripts/art_missing.py --game wicked-garden`); a missing plate falls through
to the procedural silhouette, which is the correct degradation.

The tables below map the source imagery in
`Design_files/Wicked-Garden/concept/`, which is where the shipped plates were
drawn from.

### Locations — 8 of 14 have a plate

| Id | Concept plate |
|----|---------------|
| `gate_of_briars` | `scenes/environments/env-gate-of-briars.jpg` |
| `heart_grove` | `scenes/environments/env-heart-grove.jpg` |
| `guest_house` | `scenes/environments/env-guest-house.jpg` (also `scenes/intimate/env-boudoir-rumpled-empty.jpg`) |
| `feasting_glade` | `scenes/environments/env-feasting-glade.jpg` |
| `mirror_pools` | `scenes/environments/env-mirror-pools.jpg` |
| `thorn_labyrinth` | `scenes/environments/env-thorn-labyrinth.jpg` |
| `winter_spindle` | `scenes/environments/env-winter-spindle.jpg` |
| `root_crypts` | `scenes/environments/env-root-crypts.jpg` |

**Needs generating (6):** `mortal_threshold`, `path_first_petals`,
`aviary_unsent`, `night_market`, `briar_deep`, `unknown`. Prompts for all six
are in `art/subjects.yaml`.

### Items — 22 of 23 have a plate

Every id in `items/garden.yaml` maps to a file under
`concept/items/individual/` on the obvious name (`item-collar-soft-thorns.jpg`
→ `collar_soft_thorns`), with three that do not match by hand:

| Id | Plate |
|----|-------|
| `salt_circle_chalk` | `item-salt-chalk.jpg` |
| `true_name_shard_sophia_partial` | `item-true-name-shard.jpg` |
| `pressed_court_schedule` | `item-court-schedule.jpg` |

**Needs generating (1):** `sap_sketch`.

**Orphan plate:** `concept/items/individual/item-black-fruit.jpg` has no
registry id. The black fruit is a feast beat (`flags.act1.ate_black_fruit`),
not a carried object, and the state dictionary does not list it — so it is
correctly absent from `items/garden.yaml`. The plate is useful as a **scene**
still, not an item icon.

### Portraits — 8 of 9 have a plate

`sophia` (`characters/sophia-reference-01.jpg`, canon face, plus four wardrobe
states and four expressions), `ashen_vale`, `mother_briar`, `lior`,
`thornwake`, `elias` (`elias-honeyed-01.jpg`), `mara_quill`,
`bloomkin_generic` (`bloomkin-01.jpg`).

**Needs generating (1):** `court_generic` — the court crowd appears only inside
composites.

Also in the pack and unmapped by anything here: `player-silhouette-back.jpg`,
seven scene composites, six UI mockups, the ending gallery (6 unlocked, 6
locked, 6 silhouettes), and the intimate set. The last of those is outside this
content's ceiling by design.

---

## Wiring status

Everything in this tree is **declared and loaded**: `game.yaml`'s `paths:`
block names `locations`, `items`, `lore`, `lore_db`, `art_subjects`,
`art_root`, `art_manifest`, `prompts`, `npc_schedules`, `world_rumors`,
`factions`, `world_schedules`, `tables`, `rules`, `threads`, `endings`,
`clocks`, `decks`, `epilogues` and `saves`.

The five world files were once authored-but-undeclared, and each fell back to
*Edgewood's* file — eight villagers placed at locations not in this graph,
gossip about grain tallies, reputation resolved against the Millhaven militia,
world events firing at `tinker_caravan`, and `collection:` keys that resolved
to nothing so no reliquary set could ever complete. That failure mode is why
the comment in `game.yaml` says DECLARE EVERYTHING THIS STORY SHIPS.

A note on `world/schedules.yaml`: the three keys in it —
`caravan_arrival`, `tinker_camp`, `militia_press` — are **hardcoded lookups**
in `engine/world/schedules.py`, not names of this story's choosing. The Brass
Coast renamed its three and, in doing so, wrote three event blocks the
simulator can never find. This file uses the engine's names and puts the
Garden's names in the comments.
