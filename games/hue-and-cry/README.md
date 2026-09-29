# Hue & Cry

Tallowmere, a candle-making port lit by the Everflame. You step off the
morning barge, a Lantern of the Watch shouts "the Magpie!", and the whole city
decides you are its most famous thief. Register: Quest for Glory warmth, real
stakes -- wry and affectionate, and the gallows are real.

```powershell
.\.venv\Scripts\python.exe launcher.py --game hue-and-cry
```

Design: `docs/superpowers/specs/2026-09-23-hue-and-cry-design.md` §6.
What changed, release by release: [CHANGELOG.md](CHANGELOG.md).

It draws with the engine's default skin (`ui.plugin: _engine`) until v0.21.0's
UI overhaul builds the wanted poster, job panel and casing board as engine
panels. No art plates ship yet: `data/art/subjects.yaml` briefs 19 locations
and 15 portraits, and `generate_art.py --game hue-and-cry` plans them.

## What ships now

The story was built alongside four engine features -- premises (v0.9), the
Law (v0.10), jobs and flashbacks (v0.11), agendas (v0.12) -- and is being
finished as a run of point releases: living city v0.14, guild economy v0.15,
Acts I--II v0.16 (the opening, the initiation, the small room, the Magpie's
trail, and the front desk's alibi and accusation) and Act III with the
eight endings v0.17 (the Hanging Fair, the gallows, the jailbreak and
`death.yaml`), so a run can now be finished eight ways. Its screens come
with v0.21's UI overhaul, and its art pack and live play with v1.0.0. Here
is what is in it today:

| What | Where |
|---|---|
| Eleven districts, three of them `secret: true` | `data/world/locations.yaml` |
| Fourteen scheduled people, all 24 hours; watch roles `captain` / `sergeant` / `watch` | `data/world/npc_schedules.yaml` |
| Two pipeline agents -- the city and Pip -- so every turn negotiates | `agents.yaml`, `prompts/` |
| Three archetypes: Cutpurse, Silver-tongue, Bruiser | `data/rules/archetypes.yaml` |
| The opening on Tallow Docks, Act I's first beat (v0.16): **run** (stealth; a Lantern who sees you bolt files `resisting_watch` on the Quay, and a fumble begins his stop on the spot), **talk** (persuasion, hard; fail and he writes the Magpie into his book, blurred) or **go quietly** (an arrest there and then: three crowns or a day in the cells). Every way leaves you free to walk to the Snuffs within a few turns, by mid-morning of day one (a fumbled run you surrender to costs three days in the cells first) | `game.yaml` → `entry.opening`, `data/rules/law.yaml` |
| The Honest Company takes you in (v0.16), Act I's second beat: the first turn in the Snuffs while Mother Gannet holds court (18:00–04:00), free and not yet sworn, deals the initiation deck -- so a thief off the morning barge meets the Company that evening, and until then her contract and the guild bunk say the Company receives newcomers after dark -- tea at the long table with a Company that is sure you are the Magpie, a proving in front of the back room (steal her thimble, open the strongbox, stare down the doorman, or just carry the crates), and the oath, then supper or the Magpie's ballad. Every card has an answer that asks no dice; the oath always lands, sets `guild_initiated` and opens Act II, and the rolls decide only how warmly the Company takes you (+2 to +9 standing) | `data/scenes/initiation.yaml`, `data/quests/arcs.yaml` |
| All eight endings, each with Speak/Act/Seal and an epilogue card, each through its own door, and every one but the fail-forward EARNED. **Cleared** (v0.17): name the Magpie rightly at the front desk, and at the Hanging Fair the Watch takes the real thief on the Green -- stay and see it done, or walk away and it is offered again when you come back; after the fair, the captain clears your name at the front desk instead (a wrong name left standing on the captain's desk keeps it out of reach until a right one takes it off). **A Lantern** (v0.17): the Magpie named rightly, the Watch's good opinion (five good rounds of the lamps with Wren), and the captain's own file never used against her -- then Captain Ardane offers you a badge at the front desk -- or, if you would rather, just clears your name -- and "not yet" is never the last chance. **Honest After All**: the evening barge takes only a thief who never stole in Tallowmere -- no purse, no house, no squeeze, no hand on the Everflame's heart, whether or not anybody saw -- with a clean enough record of their own (below `sought` in every watch-house for what you did -- the Magpie's robberies pinned on you do not count), square with the fences (no credit open, no welsh), one honest wage earned in the city, and not the Everflame's heart in the pack -- otherwise the bargemaster says why, and the barge sails without you. **The Rope** (`the_rope`), the fail-forward -- taken at the fair, hanged at the fair, and told like a Quest for Glory death screen, through `death.yaml`'s terminal block (below) or the gallows on the fair's last morning (the Hanging Fair, below). **Partners** (v0.17): follow the trail to the Magpie's own door instead of the captain's and say it -- rightly, and the Magpie takes you on (wrongly, and that suspect's people hear of it); then at the Hanging Fair the two of you take the Everflame's heart off the palace steps together -- or, once the fair is over, out of the Everflame itself, up the Hill after dark (sell the Magpie out to the captain first and it is gone for good). **The Legend** (v0.17): lift the heart alone at the Showing (a severe stealth roll) and get it home to the Snuffs before the Watch takes it back -- the Magpie's Hoard carried whole makes the legend a little larger. **Guildmaster** (v0.17): sworn to the Company, trusted by the Hall (5 of its good opinion), and Mother Gannet's measure taken -- her Silk Row job done, or her strike fund's secret in your hands -- and she offers you her needles at the long table, any evening from the Hanging Fair on (she names nobody before it); not while Silas Crook's rise has won. **The Dapper's City** (v0.17): Silas's rise complete, and at the fair you stand with him -- or stand against him and lose; stand against him and win, and he is stopped, and Guildmaster opens again | `data/rules/endings.yaml`, `data/epilogues/`, `data/quests/the_way_out/`, `data/quests/the_hanging_fair/`, `data/scenes/fair_day.yaml`, `data/scenes/lantern_house_desk.yaml`, `data/scenes/the_confrontation.yaml`, `data/scenes/the_last_job.yaml`, `data/scenes/porters_hall.yaml`, `data/tables/labour.yaml` |
| The Hanging Fair (v0.17), Act III: a declared world event on days 10-12, on Gallows Green, which opens Act III (`the_hanging_fair`, whose ACT line the narrator sees from then on). The first turn you stand on the Green free while it is on deals the fair deck: the crowd, the ballad (whose verse says what the Watch believes of you -- the Magpie, or, after a right naming, a stranger it took for one), and the Showing of the Flame -- watch the Everflame's heart catch the sun on the palace steps, or go up the Hill for it (stealth, severe, once). Win and the heart is yours, filed as the Magpie's `sacrilege`; lose and a Lantern had your wrist, `sacrilege` on your own face, `sought` for the rest of the fair. Walk off the Green and back while the fair is on and the deck is dealt again, with whatever has come due since. An arrest at the fair is questioned as any arrest is. A thief the Watch was already holding when the fair came is walked down to the Green at nine on its last morning: The Rope, unless the fine is paid or the cells are broken out of first (the jailbreak, below) -- serving does not wait the fair out (a sentence that would run past nine stops there) | `data/world/schedules.yaml`, `data/scenes/fair_day.yaml`, `data/scenes/the_gallows.yaml`, `data/quests/arcs.yaml` |
| The jailbreak (v0.17): a third way out of the cells, beside the fine and the wait, offered while you are held once the interrogation is answered. Lift the sleeping Lantern's keys off their nail and walk past the duty desk (stealth, then nerve); after the first time the keys are chained, and it is a rusted window bar and the yard wall (craft, then stealth) on every stay after. About one try in three, and one try a day. Out, you stand free on the Lantern House's back step with an `escape` on file in the Wick (`sought` as you walk out) and everything the arrest charged still on it; caught, a hiding (3 hp), the door locked again and no second try before midnight -- rest, pay, serve, or try again tomorrow. The cells heal nothing, and a hiding that kills is a death: the bench again before the fair, The Rope during it. On the fair's last morning it is the only way past the gallows without the fine | `data/challenges/lantern_house.yaml`, `data/rules/law.yaml` |
| The Everflame's heart (v0.17): named, shiny and a `relic` -- no counter in the city will buy it, fence or honest -- stolen only at the fair, and taken back by the Watch at any arrest. Not a piece of the Magpie's Hoard | `data/items/goods.yaml`, `data/tables/trade.yaml` |
| Death, since v0.17: hp 0 -- hunger, a street fight, a fall off a roof -- is a setback, not a game over. You wake the next morning on the step of Old Nance's flophouse in the Snuffs, half a purse lighter, with stiff hands, a sore ankle (-1 stealth, craft and survival for three days) and a charity crust. Die in the cells and you wake on the bench still held: dying is not a way out. The one death that ends the story is dying held while the Hanging Fair is on: that is The Rope | `data/rules/death.yaml` |
| Art prompts for every district, person and premise type; no plates yet | `data/art/` |
| Thirty-one premises a run -- eight generated types and four anchors (Vessaline House, the Margrave's Treasury, Mother Gannet's House, the Captain's Office) -- each with a household that keeps real hours, security by tier, loot and one secret | `data/premises/` |
| Pockets: alertness and purse by role, six days of heat | `data/rules/thievery.yaml` |
| Loot and purse goods, valued in crowns; crests and seals are `named` and stay hot | `data/items/goods.yaml` |
| The two fences, Pell Hollis (Wickmarket) and Marrow (the Snuffs); money reads "12 cr". Since v0.18 a fence pays about half a hot thing's worth -- 0.53 of its value at Pell's, 0.63 at Marrow's, so a 15-crown haul fetches 8 to 9.5 -- and Pell more once it has cooled (0.71); burglary pays | `data/tables/trade.yaml`, `data/economy.yaml` |
| The Lantern Watch (v0.10): three watch-houses, wanted bands, guises (your face, the Magpie's mask, a porter's smock), arrest to the Lantern House | `data/rules/law.yaml` |
| The Lantern's stop -- run, talk, bribe, surrender or fight -- opened by a patrol that knows your face, or by a fumbled run off the barge | `data/encounters/watch_stop.yaml` |
| Dock Mag, the first honest vendor, selling porters' smocks; Marrow's Magpie mask | `data/economy.yaml`, `data/items/guises.yaml` |
| Sergeant Brask's price: a bribe that loses your file -- offered only while the Wick's drawer holds something against you (v0.15) | `data/rules/threads.yaml` |
| Jobs (v0.11): `burgle` a house and walk it stage by stage -- get there unseen, get in (door, window, roof or cellar), get past whoever is inside, open the strongroom, get clear -- with every house's security moving the odds, casing earning prep, three flashbacks to spend it on, and an alarm that brings the Watch; the Treasury has its own vault floor | `data/rules/jobs.yaml` |
| The Magpie's trail (v0.16): every run hides eight clues in the city's generated houses -- four left by whoever the seed made the real Magpie, and two red herrings pointing at each of the other two suspects. A clue describes and never accuses (a twist of lamp-wick ends, a Company tally-chit with its mark cut anew, a crumb of violet sealing-wax) and is never a man's or a woman's thing, so one proves nothing; only the tally leans. Casing a clue house to the end says "something here doesn't belong"; the strongroom shows the clue whether you cased it or not, and a job carried out keeps it, raising your Evidence (a band word: none, faint, some, strong, utmost). Burglary is the investigation, and the front desk's accusation (below) is where it ends | `data/premises/clues.yaml`, `state.yaml` |
| The burglar's kit, sold by Marrow: lockpicks (15 crowns; worth 6 to resell since v0.18, so no counter pays more than 5 for a set) and smoke pellets | `data/items/tools.yaml`, `data/economy.yaml` |
| The Porters' Hall bench (v0.15): `craft` lockpicks, smoke pellets, a lamplighter's coat (a new guise) and a forged Margrave's Hill gate pass (a jobs tool on the Hill only) from makings sold by the two fences or found in the Snuffs' middens, open to anyone who pays for the bench time, sworn or not -- a set of picks for under half Marrow's price, and nothing that sells for more than its makings | `data/recipes/workshop.yaml`, `data/rules/jobs.yaml` |
| The Magpie's Hoard (v0.15): six famous shines the ballad says the Magpie took and never fenced -- four in the anchors' strongrooms, two found by standing in secret places. Named, so hot for good: kept, not fenced, and an arrest takes them all back. Carry all six at once and the Honest Company thinks the better of you | `data/tables/collections.yaml`, `data/quests/the_magpies_hoard/` |
| Blackmail (v0.15): a house's secret, cased and carried out of its job, is held -- and each anchor's is a squeeze on its owner (Lady Imelda, Mother Gannet, Captain Ardane, Steward Quill), struck at their door in their hours and collected there inside two days. Left uncollected, the squeezed party swears a `blackmail` report to the Watch (all but Mother Gannet) and their people turn on you | `data/rules/threads.yaml`, `data/premises/anchors/`, `data/rules/law.yaml` |
| The fences' credit (v0.15): Pell Hollis's advance (ten crowns, thirteen back in three days) and Marrow's slate (five, eight back in two), paid in coin at her counter. Welsh on one and neither fence buys from you or lends to you again, and her collectors walk the streets for you -- after dark, and by day in the fences' own districts -- until you pay | `data/rules/threads.yaml`, `data/tables/trade.yaml`, `data/encounters/streets.yaml` |
| Somewhere to sleep (v0.14): a pallet at Old Nance's flophouse in the Snuffs (1 cr), a free bunk over the Porters' Hall for the Honest Company's sworn members while it has no quarrel with them (since v0.16; the flophouse and a rough night never wait for the oath), a room at the Snuffed Wick or over the Tallow Barge (3 cr), the plank bench in the cells while you are held, and a rough night anywhere, always -- plus bread and eel pie from Dock Mag's basket and ship's biscuit at Hollis's. Hunger runs at 2 an hour, and every street now costs stamina | `data/rules/survival.yaml`, `data/items/food.yaml`, `data/economy.yaml` |
| Scrounging and the secret ways (v0.14): two hours in the gutters of the docks, Wickmarket, the Snuffs, Gallows Green or Chandlers' Rise for bread, candle ends and the odd lost button -- and the hidden ways in: a drainpipe and a loading crane to the Rooftop Road, a yard grating to the Undercroft, the churchyard wall to the Old Bell Tower. The cells' drain reveals the Undercroft to anyone arrested; the Rooftop Road reveals the tower | `data/tables/forage.yaml`, `data/items/scrounge.yaml`, `data/procgen_templates/tallowmere.yaml`, `data/world/locations.yaml` |
| Honest work and luck (v0.14): carry for Dock Mag's gang on the quay (mornings, a crown or two and the end of the loaf), dip candles at Marsh & Daughters on the Rise (mornings), run errands for the Wickmarket stalls (market hours), or go round the lamps with Wren at dusk -- each open only in the hours its employer keeps, posted on the notice board, two shifts a day. An honest day covers bread and a flophouse bed with a little over; thieving pays more. Natural 20s and 1s draw Tallowmere's luck: a dropped crown, a Lantern's blind eye, a pie across the counter, tallow on the step, a crown lighter, and a jackdaw with opinions | `data/tables/labour.yaml`, `data/tables/boons.yaml`, `data/tables/complications.yaml` |
| Factions and the city's memory (v0.14): seven groups keep an opinion of you -- the Honest Company, the Lantern Watch, the Worshipful Company of Chandlers, the Wickmarket stallholders (each moved by honest work or a fight with a Lantern), the Margrave's household and the Silk Row houses (moved since v0.15 by a squeeze left uncollected), and the Temple of the Everflame (moved since v0.17 by the Everflame's heart taken off the palace steps) -- and a lore corpus the narrator can draw on: the city, the Everflame, the Magpie's legend, the Watch, the Company, the Hanging Fair, the guilds, and the hidden city (the narrator's alone) | `data/world/factions.yaml`, `data/lore/*.md` |
| The small room (since v0.16): every arrest ends in the Lantern House's interrogation, dealt on the first turn of every stay in the cells. Captain Ardane asks when she is in the house and awake, Sergeant Brask at his desk in the late afternoon, and the Lantern who brought you in at the duty desk otherwise. Nerve and persuasion can lose the petty sheets against you (every one, or the Wick's), a caught lie writes one more lift into the Magpie's file -- yours while the Watch believes you are the Magpie -- and a plain answer changes nothing. The fine and the days stand: the room moves the file, never the sentence. Every card has an answer with no roll, and paying or serving comes back once the cards are answered. If the Magpie robbed a house while you sat in a cell on an earlier stay and you have not yet shown it, the duty book is on the table there too (the same alibi as the front desk's, below), and a file that has cleared you once remembers it in red | `data/scenes/interrogation.yaml` |
| The Lantern House front desk (since v0.16), walked into free -- the reveal and the alibi. **The alibi:** when the Magpie robbed while you were in the cells, the Watch's own duty book proves it, and those robberies come off your file (once per alibi earned; it clears the nights, and while the Watch still takes you for the Magpie the file still says so -- after a right naming the book changes nobody's mind, and those nights' robberies are struck off every file, the Magpie's as well). **The accusation:** while Captain Ardane is in and awake, with Evidence at "some" or better and your found clues leaning toward one suspect -- two clues that agree (agree, not necessarily true: two herrings can open a wrong naming), at the least -- put the trail on her desk and name that suspect as the Magpie. Named rightly, the Watch stops believing you are the Magpie -- its robberies stay on its file, not yours -- and the story knows who the Magpie is. Named wrongly, she files a false witness against your face -- on top of everything the Magpie has done in the Wick in your name, since the Watch still links the two, so it typically costs a band and often leaves you `sought` -- and the Watch's belief stands; she will hear another name only once you have carried out a clue since, and never the same one twice. Every card can be answered "not yet", and walking out and back in offers it again | `data/scenes/lantern_house_desk.yaml`, `data/rules/law.yaml` |
| Mother Gannet's job, offered to the Company's sworn (since v0.16; before the oath she says why not): any house on Silk Row for the Honest Company, fifteen crowns net of its cut, three days to do it; left undone it costs the Company's good opinion | `data/rules/threads.yaml`, `data/world/factions.yaml` |

## What it deliberately does not ship yet

Each of these is a later release's job, and CLAUDE.md's "Deliberately
deferred" list carries the engine-side rows:

- **The endings are measured.** `scripts/simulate_endings.py` plays eleven
  policies to the ending each run locks (the table is in the
  [CHANGELOG](CHANGELOG.md)): every ending is reached by the policy that
  plays for it, from The Rope's 7.5% (a reckless pickpocket) to Honest
  After All's 100% (a porter), and the fair stays on day 10. A run that
  earns nothing by two days after the fair simply goes on: nothing ends it
  but a door. The interrogation's reserved `Q3_the_evidence` slot is left
  unfilled: the accusation lives at the front desk.
- **Naming the Magpie to the captain shuts Silas's door.** A thief who has
  done so is never dealt Silas's move at the fair, so cannot stand against
  Silas there either: if Silas's rise has won, Guildmaster stays shut for
  that thief.
- **The trail reads slowly, measured and left.** A house gives its clue up
  only on the last watch, so a clue costs about three houses cased to the
  end: a deliberate investigator (`scripts/simulate_acts.py`) unmasks the
  Magpie by day 12 on 60% of runs, and a retry after a wrong naming almost
  never lands in time.
- **The front desk deals on the way in.** A card that becomes due while you
  are already standing in the Lantern House (the captain coming on duty,
  say) waits until you walk out and back in.
- **The warning is in the cells only.** The fair is on day 10 of every run;
  from day 7 the interrogation's bill on the wall says the Watch keeps its
  thieves for it, and nothing else announces it (no rumour, no notice).
- **Flags nothing reads yet.** Completing the Magpie's Hoard sets
  `magpies_hoard_complete`, which only colours The Legend (its closeness and
  its last line) and opens no door; the captain's warrant and the Magpie's
  spree beats set flags nothing reads yet (Silas's is read since v0.17: The
  Dapper's City); and of the reveal's and the alibi's flags,
  `wrongly_accused_*` and `alibi_proven` are read only by the decks' own
  gates. The Temple's good opinion is moved and read by nothing.
- **A generated house's secret opens no thread.** It is held when carried out
  of a job; only the four anchors' secrets name a blackmail.
- **A purses-only living still starves, on purpose.** The careful
  pickpocket (`scripts/simulate_labour.py`) dies 2.90 times a run over 14
  days, every time of hunger (v0.18 measured the causes). Since v0.17 it
  wakes on Old Nance's step and goes on. The owner keeps this as pressure
  (v0.14). A careful thief who takes a porter's shift when hungry keeps
  11.9 of 14 days and dies once in 40 runs, so a living exists one shift
  away.
- **A burglar lives better than a pickpocket, and worse than a porter.**
  Since v0.18 the fences pay about half a hot haul's worth
  (`data/tables/trade.yaml`), so the fencing burglar keeps 7.25 of 14 days
  (the pickpocket 4.33, the porter 13.05) and ends with 13 crowns. It still
  dies 0.7 times a run, of hunger, mostly penniless and before dawn in its
  Snuffs bed, on the lean nights between hauls.
- **A quiet death at the fair.** Starving in the cells while the fair is on
  is The Rope, and that turn's prose gets no death receipt (a card's or a
  challenge step's death does), so the story goes straight to the ending's
  beats. A prisoner serving a sentence is fed, so only one who sat unfed in
  the cell reaches it.
- **Hired hands** (spec §4) are not built: a job is walked solo.
- **No bespoke screens.** The Law and the job reach the client payload and the
  prose; no panel draws them until v0.21.0.

The threads that do ship are Brask's bribe, Mother Gannet's job, the four
squeezes and the two lines of credit. The graph template's stubs were removed
rather than left in place -- they described a mill and a hedge-berry wood.

The ids above are pinned: later features read the districts, the fence ids
(`npc_pell_hollis`, `npc_marrow`) and the watch roles by name.

## Balance

Every HUE & CRY system is measured by its own headless harness, with no model,
over 40 seeds of in-game days (AGENTS.md rule 10). None of them writes a
save.

| Harness | Policies | Numbers set against it |
|---|---|---|
| `scripts/simulate_law.py` | `careful`, `reckless`, `briber` (`--opening a\|b\|c` takes a barge choice first) | `data/rules/law.yaml` |
| `scripts/simulate_jobs.py` | `blind`, `careful`, `greedy`, `greedy_bare` | `data/rules/jobs.yaml` (table in its header) |
| `scripts/simulate_agendas.py` | `idle`, `careful`, `reckless` | `data/rules/agendas.yaml`, `data/rules/clocks.yaml` |
| `scripts/simulate_scrounge.py` | `scrounger`, `mornings` | `data/tables/forage.yaml` (table in its header) |
| `scripts/simulate_labour.py` | `porter`, `dipper`, `careful`, `scrounger`, `careful_pell`, `careful_marrow`, and since v0.18 `careful_porter` (a porter's shift when hungry), `burglar` (the fencing burglar: robs a house a day and lives on what the fences pay), `burglar_pell`, `burglar_marrow` (the same, welshing on that fence's line) (`--endings`: what the earned endings read, day by day) | `data/tables/labour.yaml` (table in its header), `data/rules/endings.yaml` |
| `scripts/simulate_streets.py` | `wanderer` | `data/encounters/rules.yaml`, `data/encounters/streets.yaml` |
| `scripts/simulate_hoard.py` | `hoarder` | `data/tables/collections.yaml`, the squeezes in `data/rules/threads.yaml` |
| `scripts/simulate_acts.py` | `investigator` (`--opening a\|b\|c`; `--gate N` tries the desk's evidence bar) | `data/scenes/lantern_house_desk.yaml`, `false_witness` in `data/rules/law.yaml` (tables in their headers) |
| `scripts/simulate_endings.py` | `investigator_a/b/c`, `lantern`, `partner`, `heister`, `loyalist`, `dapper`, `porter`, `reckless`, `runner` -- each plays for one ending, to two days past the fair (`--fair-day N` tries the fair on another day; `--break-out all\|none`) | the Hanging Fair's day (`data/world/schedules.yaml`), the eight endings' gates (`data/rules/endings.yaml`); the table is in the CHANGELOG |
| `scripts/simulate.py --game hue-and-cry` | `thief` (the default: `simulate_endings`' `heister`), `thieves` (`heister`, `investigator_a/b/c`, `loyalist`: the agenda collisions' five), `living` (`simulate_labour`'s `porter`, `careful`, `careful_porter`, `burglar`, `burglar_pell`, `burglar_marrow` instead: kept days, deaths by cause and day, hauls and loot left unsold, credit and collectors), any `simulate_endings` policy, or `all`; `--seeds N` (from `--seed`, default 0), `--days N` | nothing of its own: one report over the harnesses above -- `simulate_endings`' table plus each policy's worst wanted band, jobs carried out, clues, deaths and respawns and gold; a `collisions` block (where the Magpie, Ardane and Silas met the player: `simulate_endings.COLLISIONS`, per run -- not `simulate_agendas`' per-job `collision_rate`. At 40 seeds x 14 days over `thieves`: the Magpie on a house you cased or burgled 36%, there with you that night 4.5%, the same day 9%, robbed while you are held 10.5%, Ardane's net over hot goods 84% or a marked thief 92%, Silas's split on a sworn thief 25%; full table in the CHANGELOG); and the days `simulate_labour`'s careful pickpocket keeps on its own coin. `--policy living` at 40 seeds x 14 days, kept days and deaths a run: porter 13.05 / 0, careful_porter 11.88 / 0.03, burglar 7.25 / 0.70, burglar_pell 6.62 / 1.43, burglar_marrow 6.65 / 1.40, careful 4.33 / 2.90 |

The law, jobs, agendas and acts harnesses take `--set KEY=VALUE` to try a number
without editing the file; every one takes `--json` for the raw table. The measured tables are in [the root
CHANGELOG](../../CHANGELOG.md) under the release that set them (summarised in
this story's [CHANGELOG.md](CHANGELOG.md)), and `tests/test_hue_and_cry.py`
asserts the Law's floors, the jobs, scrounging and cost-of-living bounds,
the investigator's, and every ending's reach by a policy that plays for it;
`tests/test_simulate_thief.py` the agenda collisions, the burglar's and the welshers' headlines and the careful pickpocket's.
`scripts/simulate.py`'s own policies are flagship-owned; since v0.18.0
`--game hue-and-cry` runs this story's harnesses instead, through the last
row above.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_hue_and_cry.py -q
```

`tests/test_hue_and_cry.py` holds the story's shape and its measured bounds;
the story also has a row in every per-story test, and `tests/test_finales.py`
drives each of its endings through its own door (the barge, the real Magpie
at the fair, Cleared at the desk after it, the captain's badge, the death in
the cells at the fair, the gallows, the heart taken with a partner at the
fair or by night after it, the heart carried home, Gannet's needles, and
Silas's move) -- and walks each earned
ending's door with its gate unmet, to prove it stays shut.
