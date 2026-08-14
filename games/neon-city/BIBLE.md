# THE CROSSING — Story Bible

> Working title. Fourth game for the clockwork-dark engine. Slug suggestion: `the-crossing`.
> Canon: the NeonCity project (`C:\Projects\NeonCity\game\src\data\*.js`, CATHEDRAL arc) and the
> CosySim platform docs (`THE_GRID.md`, `GAME_SYSTEMS.md`, `neon_city_events.py`). Every name,
> price, gate number and quoted line in this document is checked against those files.
> Shape: survival/expedition on the engine's graph (locations + quests + encounters + economy +
> tables) plus clocks (the timestamp, weather, debt) and threads (faction standing, Collections).
> **No doom clock. No day-decks.** Canon deltas are listed in the appendix.

---

## 1. PREMISE & TONE

Somebody sold you forty seconds of your own death. It came with a timestamp.

Mira Vex slid the shard across her counter in the Grid and did not name a number, which is how
you knew the night had gone sideways. Forty seconds of rain on wet asphalt, somebody breathing
badly — you, it turns out — shot from an angle nobody was standing at. Clean, unhurried, filed
like a delivery receipt. The header stamp is corporate. The timestamp is twenty-one days out.

"Whatever that is," Mira says, "it is not a threat. Threats are written by people. That was
*filed*."

The thing that filed it is not in the towers. Intake is on Floor 87 — every braindance, every
clinic scan, every arena feed, scrubbed of names and fed upward — but Intake is a mouth. The
core sits under the Shadow zone, in a hall that was poured before OmniCorp had a logo, and the
only lift down is behind the SynthSec Grid Point. Down there it is not sinister. It is enormous
and patient and entirely indifferent, and it has been describing every person in this city so
accurately that they have all agreed to be the description.

**THE CROSSING is the walk from Mira's counter to that hall, made in twenty-one days, by
somebody the count has already closed out.** It is not a mystery — you know where you are going
by Day 3. It is an expedition. The Sprawl is not a backdrop; it is terrain, and every district
of it is a debt you pay to pass: in credits, in hours, in heat, in favours you will not enjoy
owing. You do not "explore" the Junkyard. You get across it before the acid rain does, with
enough left in your legs to argue with the man at the gate.

**Register.** Bloomberg-terminal noir. Clipped, present-tense, transactional. Money is the
moral system — everything is priced, and character is what someone does about the price. Nobody
monologues. Nobody is camp. Cruelty is administrative ("Compliance failure, individual," she
says, and the words have no edges at all). Kindness is small, costed, and never announced.
Sentences carry numbers when numbers exist: not "a bribe" but "four hundred"; not "soon" but
"03:12". The narrator never editorialises; the facts are arranged to do it themselves.

**What the crossing is dramatically:** a person with a receipt for their own death deciding
which of two things to spend the balance on — getting out of the file, or getting to the thing
that keeps it. Both roads go through the same gate.

---

## 2. THE MAP

Fourteen waypoints. Edges list rough travel hours and a danger band (`low / medium / high /
severe`) for the graph author. Entry/cross costs are the *fiction* of energy and heat — final
numbers belong to the economy pass. Weather (Section 4) multiplies every outdoor leg.
Canonical district ids from `districts.js` kept where they exist.

### 2.1 `the_grid` — The Grid (START · Central · neutral)
Underground marketplace, off-the-books, verified by reputation. Everything has a price here and
the price is honest, which is the most anyone in this city will do for you. Base camp: the last
place your name is an asset instead of a liability.
- **Cost:** free to enter, always. Sleeping here is cheap and public.
- **Scavenge:** none — but everything scavenged elsewhere *sells* here.
- **Held by:** nobody; six factions agree not to burn it down and everyone pays rent to all six.
- **Edges:** Neon Strip 1h low · Ghost Alley 1h low · Ripper Street 1h low · Rusty Anchor 1h low.

### 2.2 `neon_strip` — The Neon Strip (Midtown · neutral)
Light, noise and appetite; the whole city comes here to forget. For an expedition it is a river
crossing made of people — fast, loud, and full of eyes that are paid to remember faces.
- **Cost:** cheap in energy, expensive in heat if you are already Noticed; the Strip's cameras
  are the best-fed in Midtown.
- **Scavenge:** dropped credsticks, tourist gear, a wallet's worth of ₵ if your nerve holds.
- **Held by:** nobody owns the Strip; everybody rents it by the hour.
- **Edges:** Grid 1h low · OmniCorp Plaza approach 2h medium (checkpoints) · Club Noir 0.5h low
  · Velvet Pit 0.5h low.

### 2.3 `club_noir` — Club Noir (Midtown · OmniCorp)
A casino dressed as a cathedral. The house always wins, but tonight could be different. You do
not cross Club Noir; you transact it — Frankie deals cards and secrets in equal measure at the
back tables.
- **Cost:** the cover charge is ₵ and dignity; gambling is the only scavenging and it scavenges
  back.
- **Scavenge:** intel only — table talk, a read of the room, Frankie's folded cards.
- **Held by:** OmniCorp owns the concrete. Kestrel owns what happens inside it.
- **Edges:** Strip 0.5h low · Velvet Pit 0.5h low.

### 2.4 `velvet_pit` — The Velvet Pit (Midtown · BlackMarket)
A speakeasy where deals outnumber drinks. Listen closely; everyone is selling. This is the
expedition's hiring hall — Rho's cloth for fencing what you carried out of the Downzone, Dita
at the end of the bar with the tunnel map in her head, Viktor Marlowe pouring and settling.
- **Cost:** low energy; entering while Wanted costs standing, because the Pit does not enjoy
  the company you attract.
- **Scavenge:** none. Fence here; recruit here; owe here.
- **Held by:** BlackMarket, lightly. The Pit's real government is the bar tab.
- **Edges:** Strip 0.5h low · Club Noir 0.5h low · Ripper Street 1h medium.

### 2.5 `junkyard_sprawl` — Junkyard Sprawl (Downzone · BlackMarket)
Mountains of dead tech; one runner's scrap is another's payday. The richest scavenging on the
map and the most honest ground on it. The north face, past the crane, is where Rust's crews
bury things with corp serials and people inside them. Stay off it in daylight. And at night.
- **Cost:** heavy energy — the stacks are climbed, not walked. Acid rain turns the yard lethal:
  every hour outdoors in Acid Rain or Storm bites HP and gear condition.
- **Scavenge:** the best on the map — salvage tech, deck parts, drone chassis, courier wraps
  off runners who stopped needing them. Sell to Grease at yard prices or haul to the Grid for
  full rate.
- **Held by:** BlackMarket on paper; Grzeska's cranes and Petrossian's crews in fact.
- **Edges:** Ripper Street 1h medium · Rusty Anchor 1h low.

### 2.6 `ripper_street` — Ripper Street (Downzone · BlackMarket)
Chop shops and ripperdocs; anything bolted to a body can be bought or sold. The expedition's
field hospital and quartermaster's row — Dr. Sable's table for what the crossing does to you,
Viktor "Surplus" for what you do back. Knockouts wake here, short a clinic bill.
- **Cost:** medium; the street itself is safe-ish because everyone here is armed and busy.
- **Scavenge:** chrome pulls, med supplies, parts — somebody is always watching what you carry
  out.
- **Held by:** BlackMarket. The true authority is whoever is holding the bone saw.
- **Edges:** Grid 1h low · Ghost Alley 0.5h low · Velvet Pit 1h medium · Junkyard 1h medium ·
  the Undercroft (Colosseum tunnels, see 2.10 note) 3h high.

### 2.7 `ghost_alley` — Ghost Alley (Downzone · Ghost_Net)
A nowhere lane where netrunners meet in the flesh, just this once. Halloran kept a room here
with four months paid up front in cash; his last route is the expedition's first real
intelligence. Lyra's broker line terminates here, and 0xGH0ST's broadcasts come in cleaner in
the alley than anywhere else in the city, which nobody can explain.
- **Cost:** low energy; heat earned here arrives with interest.
- **Scavenge:** data — dead drops, cache keys, ICE fragments. Worthless to Grease, gold to Rho
  and Lyra.
- **Held by:** Ghost_Net, which does not hold things; it verifies them, constantly, forever.
- **Edges:** Grid 1h low · Ripper Street 0.5h low.

### 2.8 `rusty_anchor` — The Rusty Anchor (Downzone · neutral)
A tavern that remembers everyone, where crews are forged over cheap synth-beer and Inés keeps a
ledger of who owes what to whom — not money; money is the easy column. The expedition's last
warm room; the Anchor stopped asking whose colours you wear because Inés cannot afford to lose
the trade.
- **Cost:** the cheapest bed and board on the map. The only tax is that everything said in it
  is remembered.
- **Scavenge:** none. Recruit, rest, and settle debts.
- **Held by:** Inés Barbosa, outright, which is rarer than any faction stamp.
- **Edges:** Grid 1h low · Junkyard 1h low.

### 2.9 `omnicorp_plaza` — OmniCorp Plaza approach (Uptown · OmniCorp)
Glass towers and silent security; the money looks down on the rest of the city. This is the
paperwork route to the Shadow zone — Plaza, the SynthSec Barracks corridor, the Grid Point —
and every camera here feeds Intake directly. Walking Uptown is telling the count exactly where
you are.
- **Cost:** low energy, steady heat: ID checkpoints, gait scanners, drones. At Wanted the
  approach is a gauntlet; at Hunted it is a mistake.
- **Scavenge:** nothing. Uptown does not drop things.
- **Held by:** OmniCorp; SynthSec under contract (Barracks gate refuses heat above 80).
- **Edges:** Strip 2h medium · SynthSec Barracks corridor 1h medium → Grid Point 1h medium.

### 2.10 `synthsec_gridpoint` — SynthSec Grid Point (Shadow · SynthSec) — **GATE**
A militarized checkpoint between the city and the dark. They are watching. Cpl. Ivo Dane stands
the gate, counting days to a transfer that will not come, wondering what it is he has been
guarding. Trucks go out full and come back full; nobody unloads them here. The mast reads
faces, not badges.
- **Cost (canon gate):** the checkpoint refuses anyone at **heat above 70**. Below that:
  papers, or ₵450 and Dane looking at the ground for four seconds, or the tunnels.
- **The tunnels:** the Colosseum undercroft route out of Ripper Street — 3h, high danger, no
  scan, and it delivers you *outside* the wire with the walk still to do. Dita drives it by
  feel. This is the Hunted player's only door, and it costs like one.
- **Scavenge:** none inside the wire. The approach ditches hold patrol logs and dropped kit.
- **Held by:** SynthSec. Order at gunpoint, billed by the hour.
- **Edges:** Barracks 1h medium · DeepState Bunker 2h high · Colosseum/undercroft 1h high ·
  the Shadow crossing 4h severe.

### 2.11 `deepstate_bunker` — DeepState Bunker (Shadow · DeepState) — **GATE**
It is not on any map. You only find it when it wants finding. Shelving that goes back further
than the towers do — drives, numbered, and the numbering does not start at one. The Archivist
blots the page like it is 1908. The forecast on your shard is theirs: not a threat and not a
promise, simply what the count says happens to people who do what you are currently doing.
- **Cost (canon gate):** entry requires **heat ≤ 40** and DeepState standing not hostile
  (≥ −30). The Bunker does not sell; it invests in outcomes, and occasionally an outcome is you.
- **Scavenge:** nothing leaves the Bunker unpriced. Wren's counter carries dossiers, access
  codes, and the only honest map of the Shadow zone — at 1.25× and worth it.
- **Held by:** DeepState. The shadow under the shadow; here before the city, will outlast it.
- **Edges:** Grid Point 2h high.

### 2.12 `shadow_crossing` — The Shadow Crossing (Shadow · nobody) — *new location*
The dark between the wire and the lift head. No streetlights, no cameras, no count — which
sounds like relief until you understand what the cameras were keeping off the streets. The
weather out here is the same weather, with nothing between you and it.
- **Cost:** the hardest leg on the map: 4h minimum, severe encounters, full weather exposure,
  no vendors. Everything you need, you carried.
- **Scavenge:** pre-corporate salvage — cable, tooling, one-of-one artifacts that Rho will go
  quiet over. Every kilo costs energy on the worst ground in the Sprawl.
- **Held by:** nobody, which out here is not good news.
- **Edges:** Grid Point 4h severe · the Lift 1h high.

### 2.13 `the_lift` — The Lift (Shadow · unclaimed) — **GATE, ONE-WAY**
Behind the Grid Point, past the crossing: a freight lift head in a poured-slab shed older than
every logo in the city. The lift under the Grid Point goes down further than the city is old.
- **Cost (canon gate):** the doors need **keys** (access codes — Wren sells them, Floor 87
  yields them, Dane has seen them) and a **crew**: the winch interlocks want three pairs of
  hands, minimum two beside yours. It goes down. It is not documented to come up.
- **Scavenge:** the shed holds the last cache on the map. Take what you can carry. You will not
  be back this way.
- **Edges:** Shadow crossing 1h high · **descent: one-way to the Core Hall**.

### 2.14 `core_hall` — The Core Hall (below · finale)
Cold, and the hum. Not sinister — enormous, patient, entirely indifferent. Nineteen years of
accumulated weight describing a city that agreed to be the description. You have a forecast
that ended twenty-one days ago; if you are standing here, either it did not come true, or it is
about to, and the machine does not care which any more than the weather does. The question was
never whether the count is true. Only who holds the pen.
- **Cost:** everything already spent. There are no prices below the lift.
- **Edges:** none. The ending chosen here (Section 6) is the exit.

---

## 3. THE CAST

Ten. All stats, homes and factions per `npcs.js`; every quoted line verbatim from `dialogue.js`
or `story.js`.

### Mira Vex — Fixer, The Grid (BlackMarket)
Red hair, green eyes, faster than her smile. Sells street-tech and stims, fences anything — and
sold you the file, for nothing, which from Mira Vex is the most alarming price there is.
- **Sells:** stims, medkits, basic decks, street pistols, ID scrubs; fences your scavenge.
- **Wants:** to not be the last person who touched that shard. Clean jobs run for her stall.
- **Voice:** "Credits or info — what are you buying?"
- **Thread:** the expedition's quartermaster. Standing with Mira is the difference between
  yard-rate and friend-rate on everything the crossing consumes; at 15+ she takes your name off
  a list for ₵500 a time. If Collections ever comes for you, it is Mira who hears first.

### Lyra Vance — Broker, Ghost Alley (Ghost_Net)
The Grid's broker line; a ghost in the wires who deals in custom work and rare ICE. She ran the
shard three times without speaking. "This is not a recording. There is no camera in it. This is
a *render*. Somebody modelled you. Somebody good."
- **Sells:** custom ICE work, trace doctrine, the truth about what you bought.
- **Wants:** proof of what Intake feeds. She keeps a copy of everything. Know that going in.
- **Voice:** "Trace is arithmetic. It is always arithmetic. Leave before the sum completes and
  you were never there."
- **Thread:** the file-reader. Lyra standing determines how much of the shard you ever
  understand — the header, the render angle, the confidence rating. At 25+ she opens the
  Ghost_Net door in the Shadow zone that no amount of ₵ opens.

### Cpl. Ivo Dane — Gate Corporal, SynthSec Grid Point (SynthSec)
Stands the gate between the city and whatever the city pretends is not out there. SynthSec has
had him on gates six years; fourteen months at the Grid Point, transfer requested twice,
approval expired twice. Coincidence twice. His kid is in a NeoTech care plan and it went up
again.
- **Sells:** four seconds of looking at the ground. "...It's four hundred. Don't look pleased
  about it."
- **Wants:** the transfer. Failing that, to know what the trucks carry. "Trucks go out full and
  come back full. Nobody unloads them here."
- **Voice:** "Head down, no eye contact with the mast. It reads faces, not badges."
- **Thread:** THE GATE arc pivots on him. Standing with Dane converts the checkpoint from a
  wall into a door: waved through under 70 heat, warned of sweep schedules at 15+, and — if you
  bring him the manifest of his own trucks — a man with nothing left to guard.

### Tovah "Grease" Grzeska — Scrap Queen, Junkyard Sprawl (BlackMarket)
Grew up in the stacks, third generation; can price a dead drone by the sound it makes when it
lands. Sells cheap, sells honest — the only vendor on the map at a *discount* (0.88).
- **Sells:** courier wraps, decks that boot, EMP grenades, synth food, honest prices.
- **Wants:** to know why nobody came looking for the corp-current chassis. "Nobody came looking
  is the part that keeps me awake. Take it cheap, take it away."
- **Voice:** "Everything's priced. Everything works. One of those is a promise."
- **Thread:** the scavenge economy runs through her. Standing buys yard access after dark,
  first pick of new falls, and the warning that matters: what Rust's crews bury on the north
  face, and when not to be near the crane.

### Dr. Yusra Sable — Ripperdoc, Ripper Street (BlackMarket)
Struck off Uptown for operating on people who could not pay. Still does; just charges the ones
who can. The expedition's medicine: the crossing is paid for in HP, and Sable is where HP is
bought back.
- **Sells:** cardio pumps, grips, tuners, medkits, trauma patches; repairs at 1.06×.
- **Wants:** cash, no questions, and for you to come back *before* the seal weeps, not after.
- **Voice:** "Off the books means you pay in cash and I don't ask what did it."
- **Thread:** at 20+, patch-ups off the books (₵400, no records — no heat). Her line on chrome
  is the story's line on chrome: "Visible chrome is a confession you wear."

### Rho — Fence, The Velvet Pit (BlackMarket)
No surname, no history, no photographs. Buys what nobody will admit losing and never asks a
second question. Everything the Junkyard and the Shadow zone yield turns into ₵ on Rho's cloth.
- **Sells:** stolen data, forged IDs, Black ICE (quietly, and it puts your handle on a manifest
  somewhere, permanently).
- **Wants:** good problems. Provenance amuses Rho the way weather amuses other people.
- **Voice:** "I pay less than it is worth and more than you will get elsewhere. That gap is the
  whole business. There is no other secret."
- **Thread:** the sell-side of the economy. Standing moves Rho's gap in your favour and opens
  the back-room catalogue; the pre-corporate artifacts from the Shadow crossing are the only
  goods that make Rho go quiet, and quiet Rho pays best.

### Dita Halvorsen — Wheelwoman, The Velvet Pit (BlackMarket)
Knows every service tunnel under Midtown by feel. Has never been caught, only ever been late —
"Late means the crew waited. Caught means the crew didn't. I have made a career out of that
distinction."
- **Sells:** the drive. Fifteen percent, said out loud to the whole crew, up front.
- **Wants:** crews that say the number before the job. Everyone who burned her did it in a room
  where nobody heard the number.
- **Voice:** "Curfew moves the checkpoints, it doesn't remove them. So we go where the
  checkpoint used to be, ninety seconds after they finish moving it."
- **Thread:** the tunnels. Dita standing is the alternate route past the Grid Point — the
  undercroft run — and the crew slot the Lift's winch demands. She is the difference between
  the gate having one door and two.

### Frankie DeLuca — Info Broker, Club Noir (Ghost_Net)
Slicked black hair; deals cards and secrets in equal measure; knows the whole city. He has been
salting the Floor 87 story for years — "There's a vault on the 87th floor of OmniCorp.
Blueprints exist. For a price, they could exist for you." He undersold it. Eighty-seven is not
a vault. It is Intake.
- **Sells:** rumors, access codes, dossiers, blueprints, forged IDs — and he tells the room.
- **Wants:** to be the man who knew first. He pays well for a thing nobody else has.
- **Voice:** "Information is the only honest currency. How much honesty can you afford?"
- **Thread:** the intel economy and its price: everything bought from Frankie is also *sold* by
  Frankie — dealing with him moves the count's picture of you. High standing buys the one thing
  he does not retail: what made his smile stop for a second when he read your header stamp.

### The Archivist & Wren Solís — DeepState Bunker (DeepState)
The Archivist keeps the record of what the city agreed to forget; refers to living people in
the past tense, and is usually right. No face you can hold in memory longer than it takes to
look away. Wren is the cutout — "the part of the wire you can cut without losing the signal" —
four names this year, answers to none of them twice; the only face DeepState will let you see.
- **Sells (Wren):** dossiers, access codes, blueprints, the Shadow-zone map, at 1.25×. "The
  price is on it. The price is not a suggestion."
- **Wants (Archivist):** the interesting variable resolved — by observation for preference, by
  intervention if the record requires it. "The forecast on your shard is ours."
- **Voice (Archivist):** "It is not power. Power is loud and it ends. This is only patience."
- **Thread:** the Bunker gate and the endgame's pen. Archivist standing decides whether the
  Bunker is a waypoint, a patron, or the second thing DeepState sends. Cold greeting, for the
  author's tuning fork: "You were a promising entry. Entries close."

### 0xGH0ST — broadcast voice (Ghost_Net; heard, never met)
A signal, not a person. Hijacks screens, dead phones, the Grid's tickers; nobody has confirmed
what it is and the alley does not ask. In THE CROSSING it is the expedition's weather-vane —
messages arrive unbidden at leg boundaries and heat-tier changes, in the canon style: clipped,
imperative, timestamped, always slightly ahead of you.
- Canon message bank (use verbatim, extend in kind): "They moved the package. Check the drop
  point. You have 2 hours." / "Your name came up in a SynthSec briefing. Lay low. Delete
  this." / "Corp comms intercepted. They know about the node. Sending now." / "I'm 0xGH0ST.
  I'm everywhere. But I won't be here much longer. Make it count."
- **Thread:** none to spend — 0xGH0ST cannot be bought, met, or answered. Its messages are
  free intel with a heat sting (canon `heat_impact` +0 to +8), and in the final week they start
  addressing the timestamp directly. Whether it wants you to reach the core or to run is never
  resolved. Do not resolve it.

---

## 4. SYSTEMS IN FICTION

How canon systems land on the engine's spine. Mechanics resolve in the engine; the LLM narrates
what they feel like on the street. All state changes through `effects.apply_effect`; all time
through `clock.advance_time`; all rolls through `world_rng`.

### 4.1 Heat — the pressure ladder (awareness-shaped)
Canon tiers and thresholds (`pressure.js`): the number is 0–100 and never fades by itself.

| Tier | Min | On the street |
|---|---|---|
| **Clean** | 0 | Nobody is looking for you. Enjoy it. Vendors at list price. |
| **Noticed** | 20 | Your handle is in somebody's notes. Markup 6%, patrols 10%. |
| **Wanted** | 45 | There is paper on you. Dealers have stopped answering. Contraband refused, markup 16%, patrols 20%. |
| **Hunted** | 70 | Bounty teams are working your last known corners. Markup 30%, patrols 35%, raids 9%. **The Grid Point will not pass you.** |
| **Burned** | 90 | Every camera in the city knows your face. Get off the street. Markup 50%, patrols 55%. |

Heat is earned by crime, contraband (each item carries a canon heat stat, 1–14), hot districts
and 0xGH0ST's attention; it is *bought* down — ID Scrub ₵130/−8, Cooldown Spoof ₵300/−25,
Burner Face ₵700/−45, Ghost Protocol ₵1500/−80 — or favoured down (Mira ₵500/−7, Dane
₵450/−6). Travel encounters scale by tier, per the canon table: Street Toll (any), A Tail
(Noticed), Patrol Stop (Wanted), Bounty Team (Hunted), Kill Order (Burned). The central
tension: everything that earns passage money also earns heat, and the gates are heat gates.

### 4.2 Energy — stamina, and the shape of a leg
Energy is the expedition's fuel: every edge costs it (hours × terrain), every scavenge, every
fight. It is restored only by food and rest — synth food ₵25, sump coffee ₵35, sprawl ramen
₵40, stims when the schedule beats the budget (canon ladder up to Overdrive Amp, ₵420, "Three
days of you, spent in one night"). **Rest is never gated** (engine rule 6): a player can always
stop — at the Anchor for cheap, in the Grid for free, in the Shadow zone for the cost of the
hours; out there the clocks that matter are the weather and the timestamp, not the door charge.

### 4.3 Credits ₵ and the scavenge economy
₵ is the moral system wearing a currency sign. Baseline: start around ₵2,000 (canon
START_CREDITS); job payouts ₵200–1,200; daily overheads real (see 4.6). The loop: **scavenge
in the Downzone → fence in Midtown → spend on passage.** What sells where:
- **Junkyard salvage** (parts, chassis, wraps) → Grease at yard rate, the Grid at full rate.
- **Data** (Ghost Alley drops, ICE fragments) → Lyra or Rho; Frankie pays more and tells the room.
- **Chrome and med-stock** (Ripper pulls) → Sable, quietly.
- **Contraband** → Rho only, and only below Wanted; it is refused at tier 2+ (canon).
- **Shadow artifacts** (crossing salvage) → Rho's quiet price, the best ₵/kg in the game.
Faction discount formula is canon: `clamp(standing/200, 0, 0.25)`; selling returns 40–60% of
base by condition. Prices are always written in ₵, always in mono, always gold.

### 4.4 Weather — the sky as an encounter table
Canon Markov chain: **Clear → Overcast → Rain → Acid Rain → Storm → Clear.** Weather is a
clock, not a deck: it advances with world time and multiplies outdoor legs. Rain slows;
Acid Rain bites HP and gear on exposed edges (Junkyard, Plaza approach, the Shadow crossing);
Storm closes the crossing outright — the one hard "wait" in the game, and the reason the
timestamp budget matters. Indoor waypoints (Noir, the Pit, the Anchor, the Bunker) do not care,
which is why expeditions are planned in bars.

### 4.5 The timestamp — the 21-day clock
The shard's header reads twenty-one days out. This is the story's one absolute clock, ticked by
`clock.advance_time` like everything else, surfaced in the fiction as the file's confidence
rating — never as a UI countdown in prose. It does not kill you at zero; the *forecast* meets
you at zero, wherever you are (Section 6, THE APPOINTMENT beat inside THE COUNT arc). Quests
can make **the timestamp slip** — the engine's doom_resistance-shaped reprieve: poisoned
telemetry, a burned collector, a proxy in your coat each push the file's date or drop its
confidence. Slippage is earned, never bought; the fiction is always the same: *somewhere, your
confidence rating drops, and somebody reschedules.*

### 4.6 Debt and Collections — the standing threads
Daily upkeep is canon (rent ₵100 + level scaling; crew wages; chrome maintenance). Miss a day
and it converts to **debt**; debt is a thread with a crew attached. Collections works for
whoever you owe — Kestrel's floor if you gambled it, the Pit if you drank it, Mira's patience
if you supplied it — and escalates on its own clock: reminder, visit, consequence (canon
knockout: you wake on Ripper Street short a clinic bill). Two debts you cannot cover is a
canon burn condition. Faction standings are the other thread family: six factions per canon
(`omnicorp, neotech, blackmarket, ghost_net, synthsec, deepstate`), moved by jobs, purchases
and quest calls; rivalries per `factions.js` (help SynthSec, bleed Ghost_Net, and so on).

### 4.7 The three gates (canon numbers)
1. **SynthSec Grid Point:** passes nobody above **heat 70**. Papers (forged ID risks the mast),
   Dane's ₵450 wave-through, or the undercroft tunnels.
2. **DeepState Bunker:** finds you only at **heat ≤ 40** and DeepState standing above −30. Not
   on the critical path — but the Archivist holds the Shadow map, the lift's history, and one
   of the endings.
3. **The Lift:** **keys + crew.** Access codes (Wren sells at 1.25×; Floor 87's intake office
   holds a set; Frankie can be paid to conjure one) and two crew minimum on the winch — which
   is what the standing threads were for. Nobody descends alone. The doors do not care how good
   your reasons are.

---

## 5. QUEST ARCS

Four arcs in the flagship's pattern (`arcs.yaml`: id, name, involvement, order, unlock gates;
quests as per-file YAML with preconditions, stages, on_complete effects). Arc gates only ever
open doors. "Timestamp slips" = the doom_resistance-shaped reprieve of 4.5. Suggested ids in
`snake_case`.

### ARC 1 — `the_file` (order 0, default)
*Understand what you bought.* Days 1–5 in spirit. Involvement 0 — a player can refuse the whole
thing and just live in the Grid; the timestamp does not refuse them back.

1. **`forty_seconds`** — Hook: Mira will not price the shard. Stages: take it (free, and
   nothing from Mira Vex is free); jack it and watch; walk it to a reader — Lyra reads it
   properly and keeps a copy, or Frankie pays ₵2,600 and tells the room. Grants: the shard,
   `flag read: lyra|frankie`, Lyra or Frankie thread opened, first heat.
2. **`the_dead_courier`** — Hook: the man who carried it had a name. Halloran; a room above a
   noodle stall in Ghost Alley, four months paid in cash; SynthSec closed the file in
   fifty-two minutes. Stages: walk his last route; crack his dead drop; decide who gets the
   manifest (a name in SynthSec, the alley's screens, or your pocket). Grants: traffic logs,
   an OmniCorp routing stamp, faction standing per the call, ₵900.
3. **`a_render_not_a_recording`** — Hook: Lyra's verdict. There is no camera in it. Stages:
   bring her three comparison captures scavenged from Strip cameras; watch her prove the angle
   nobody stood at. Grants: the file's confidence rating on paper, Lyra +, **timestamp slips**
   (small) — a modelled you is a you that can be mis-modelled.
4. **`the_header_stamp`** — Hook: what made Frankie's smile stop. Stages: buy or steal the
   stamp registry; learn the words *Cathedral* and *Intake*; learn the floor. Grants: Floor 87
   named, `the_toll` arc unlock condition met, heat.
5. **`what_mira_wont_say`** — Hook: Mira ran ten seconds of it. Then she stopped. Stages: earn
   standing 15; ask her what was in the ten seconds; learn the courier came *through Ghost
   Alley with his heart already stopped* — the render was already running him. Grants: Mira
   thread deepened, ledger fact, the arc's exit line: whatever filed you is still filing.

### ARC 2 — `the_toll` (order 1)
*Earn passage.* The expedition economy arc — jobs, scavenging and faction work, one quest per
region of the map. Unlocks: `flag floor87_named` + any faction standing ≥ 15.

1. **`yard_shift`** — Junkyard. Hook: Grease has a corp-current chassis nobody came looking
   for. Stages: work a crane shift for Petrossian (twelve hours, no talking); haul the chassis;
   choose the buyer. Grants: ₵, Grease standing, salvage economy tutorialised in fiction.
2. **`the_wrong_tray`** — Strip/Noir. Hook: Jun's braindance tray has a cut batch — the Ripper
   batch. Stages: trace it, confront the cutter, decide if Frankie hears. Grants: ₵, Strip
   access warmed, Jun/Frankie standing, heat if it goes loud.
3. **`rho_settles_a_provenance`** — Velvet Pit. Hook: a piece on the cloth has a history;
   Ghost_Net lost it in the spring and never reported it. Stages: authenticate, return or
   resell, survive the answer. Grants: Rho's gap moves in your favour permanently, Ghost_Net
   standing either way.
4. **`the_anchor_ledger`** — Rusty Anchor. Hook: Inés's other column. Stages: settle one favour
   in the ledger for her (a regular who stopped coming; find out which kind of stopped).
   Grants: rest at the Anchor becomes free, Inés names names when Collections moves.
5. **`plaza_wages`** — Uptown approach. Hook: Celine Dorr's office hires the kind of people she
   would never be seen with. One clean corporate errand, paid in access. Stages: the errand;
   the choice of being paid in ₵ or in a door (a Floor 87 visitor pass). Grants: ₵1,500 or the
   pass; OmniCorp standing; the count gets a better look at you (+heat, permanent).
6. **`collections_calls`** — anywhere. Hook: you missed a day, and the city noticed before you
   did. Stages: the reminder; the visit; the arrangement. Grants: the debt thread made flesh —
   survivable now, canonical burn condition later. (Repeatable template.)

### ARC 3 — `the_gate` (order 2)
*The Grid Point.* Unlocks: `the_toll` stage 5 or 6 seen + visited `synthsec_gridpoint`.

1. **`six_years_standing`** — Hook: Dane has stood gates six years and this one fourteen
   months, and the transfer keeps expiring. Stages: drink where he drinks (the Anchor);
   learn the mast reads faces, not badges; learn the price is four hundred and what the four
   hundred is *for* (the care plan went up again). Grants: Dane thread, gate intel.
2. **`papers`** — Hook: a forged ID spends fine twice; the third time is a problem. Stages:
   commission the ID (Rho or Frankie); test it somewhere cheap; know its limit before the mast
   does. Grants: gate option A, heat risk priced.
3. **`the_tunnels`** — Hook: Dita, fifteen percent, said out loud. Stages: recruit her; run the
   undercroft once empty-handed as a rehearsal; mark the ninety-second window where the
   checkpoint used to be. Grants: gate option B, Dita crewed, `undercroft_mapped`.
4. **`what_the_trucks_carry`** — Hook: trucks go out full and come back full. Stages: log the
   rotation (Wick's drones can see the gate, which is the one that would get him shot); board
   one or crack its manifest; bring Dane the answer he has guarded six years without having.
   Grants: **timestamp slips** (the count's logistics have a hole in them now), Dane standing
   to the ceiling, gate option C — a corporal with nothing left to guard.
5. **`heat_forty`** — Hook: the Bunker only finds the cool. Stages: spend down to 40 the hard
   way (favours, scrubs, six quiet hours); cross to the door that is not on any map; be
   decided about. Grants: Bunker access, Archivist audience, Wren's counter, the Shadow map.

### ARC 4 — `the_count` (order 3, finale chain)
*The crossing and the descent.* Unlocks: any gate option from `the_gate` + keys thread begun.
The last three quests are the engine's finale chain (lock → choice → epilogue).

1. **`the_shadow_crossing`** — Hook: past the wire there is no count, and you learn why that
   was never the mercy it sounds like. Stages: provision (food, patches, weather window);
   the crossing itself — 4h+, severe encounters, a Storm gate that forces the one true wait in
   the game; the lift head found. Grants: `shadow_crossed`, artifact salvage, crew loyalty
   tested in fiction.
2. **`keys_and_hands`** — Hook: the doors want codes and the winch wants three pairs of hands.
   Stages: keys (Wren's slate at her price / the Floor 87 set / Frankie's miracle); crew (two
   of: Dita, and whoever your threads earned — Dane unbadged, a Pit muscle, Lyra in person,
   which she has never once been). Grants: the lift live, `crew_committed`, point of no return
   flagged in fiction ("You will not be back this way").
3. **`the_appointment`** — Hook: the timestamp is tonight, and you are either ahead of it or
   inside it. If the player reaches the lift before day 21, this fires as the file resolving
   *around* them — the alley by the drainage grate stays empty, and somewhere a variable is
   scored wrong. If the clock beats them to it, it fires wherever they stand, per canon: be
   exactly where it says and be more than it measured, or be somewhere it cannot see. Stages:
   one night, one choice (keep it / break the pattern / a proxy in your coat — the proxy
   lives, and that is not the part that keeps you up). Grants: **the big slip** or the scar;
   `appointment: kept|broken|proxy`; entry state for the finale.
4. **`the_descent`** — Hook: down further than the city is old. One-way. Stages: the lift; the
   hall; the walk to the core past shelving that hums. Grants: the finale lock — Section 6's
   choice is presented here, gated on the state the whole game built.
5. **`who_holds_the_pen`** — the choice itself, then the epilogue seeded per Section 6.

---

## 6. ENDINGS

Six classes, mapped from the canon nine. Each earned against live state — faction standing,
heat tier, clock state, appointment flag — never picked from a menu the state does not back.
One-line epilogue seeds included; full epilogues are the author pass's job, written in the
canon endings' register (the canon prose is the ceiling to write toward).

1. **THE QUIET FLOOR** *(sign for it — maps `quiet_floor`, `beta_city`, `standing_order`)*
   Earned: a corporate-side faction (OmniCorp/NeoTech/SynthSec) at high standing, heat under
   Wanted, appointment survived. You do not switch it off. You sign for it — and by the end of
   the first quarter you have edited nineteen confidence ratings, and eleven people are alive
   who were scheduled not to be, and you have stopped counting the other kind.
   *Seed: your name is one of four that can edit a rating; rain still comes off the ledge at
   the third-floor line in an alley you have not visited since.*

2. **OPEN SIGNAL** *(publish it — maps `open_signal`, `house_rules`)*
   Earned: Ghost_Net or BlackMarket high standing, the manifest choices made toward the wire.
   The count goes public at 04:00 on a Tuesday — every rating, every routing table, unredacted.
   For a week the city is unbearable. Then the strangest thing: a forecast everyone can read is
   a forecast everyone can spite, and by spring the ratings are worthless.
   *Seed: the city is loud and stupid and unpredictable and, for the first time in nineteen
   years, genuinely unwritten.*

3. **THE LONG QUIET** *(shelf it — maps `long_quiet`)*
   Earned: DeepState standing, Bunker entered, Archivist's book signed or respected. It goes
   back on the shelf, and the shelf goes back to being nowhere; Intake keeps producing numbers
   that are now very slightly, very deliberately wrong.
   *Seed: you get a shelf — not a title, a shelf, with a number that does not start at one.*

4. **BLACKOUT** *(cut it — maps `blackout`)*
   Earned: the hard road — high craft/hack record, heat held under Hunted, no patron. A plasma
   cutter and eleven minutes. The last output it produces is a routing table with your name in
   it, timestamped four seconds from now, and it is correct, and it does not save you being
   right. The city goes stupid overnight. Nobody got anything. That was the entire point.
   *Seed: it rains; nowhere in the world is there a file that says it was going to.*

5. **THE WALK AWAY** *(refuse the room — maps `neon_crown`'s independence, inverted for the
   expedition shape)* Earned: appointment `broken`, no faction above patron threshold, the lift
   reached and *not* taken — the crew paid off, the keys dropped down the shaft. The count
   scored you wrong once; you decline to give it a second reading. You walk back across the
   Shadow zone the way nobody does, and the file stays open forever, unresolved, which in that
   hall is the only kind of victory that costs nothing but everything you came for.
   *Seed: somewhere below, a very old drive keeps a page open on a variable that never
   resolved. It is not a long shelf. You are on it.*

6. **A NAME THEY STOPPED SAYING** *(failure state — maps `burned`; only fires when nothing else
   qualifies)* Earned: heat 90+, three knockouts, or two debts you cannot cover — or day 21
   arriving with the crossing unmade and the appointment unmet. It does not happen in the alley
   by the drainage grate; that was always the tell. What actually happens is smaller: a door
   that does not open, a fixer who stops answering, Mira looking at you for a long moment and
   then, carefully, at the door behind you.
   *Seed: the Sprawl keeps your name for about eleven weeks. That is longer than most.*

---

## 7. GLOSSARY & VOICE RULES

### 7.1 Sprawl Glossary (canon terms — use these, not synonyms)
**Runner** (a freelance operator — that's you) · **The Sprawl** (Neon City and everything it
has swallowed) · **Heat** (your wanted level, 0–100; it locks doors, hikes prices, and draws
SynthSec) · **Rep** (the street's opinion of you) · **Standing** (where a faction stands with
you, Nemesis to Revered) · **ICE / Black ICE** (the defenses you breach; the kind that bites
back) · **Cyberdeck / Cyberware / Chrome** · **The Grid** (the underground net-market where
netrunners do business in the flesh) · **Fixer** · **Contraband** (lucrative, hot; fence it or
eat the Heat) · **Cut** (a crew member's share; pay fair or loyalty erodes) · **Uptown /
Midtown / the Downzone / the Shadow zone** (the four altitudes of the city) · **the arterials**
(the big roads, where they count you).

### 7.2 Coinages to prefer (the story's own nouns)
**Cathedral** (the machine; never "the AI") · **Intake** (Floor 87; a mouth, not a vault) ·
**the count** (what Cathedral does; also DeepState's older word for it) · **candidate file /
candidate** (a person, being considered) · **the shard** (your forty seconds) · **a render**
(what the shard is; never "a video") · **Floor 87** · **the crossing** (the expedition itself)
· **the lift** · **Collections** (the crews debt sends) · **0xGH0ST** (exact casing, always) ·
**₵** (always the sign, never "credits" written out in prices).

### 7.3 Voice rules
- Clipped, present-tense, transactional. Short declaratives; the longest sentence in a
  paragraph carries the turn.
- Numbers where numbers exist: hours, floors, percentages, ₵. "Fifty-two minutes" is scarier
  than "quickly".
- Money is the moral system. Every kindness has a cost shown or implied; every cruelty has an
  invoice. Nobody is shocked by prices.
- Understatement over adjective. The canon's horror beats are administrative: files closed,
  clearances changed, no memo saying why.
- Dialogue is verbatim-faithful to `dialogue.js` cadence per character: Mira fast and flat,
  Lyra precise, Dane tired and exact, Rho epigrammatic, the Archivist in the tense of the
  record, 0xGH0ST in imperative bursts.
- Second person for the player, as canon ("You jack it. Rain on wet asphalt.").

### 7.4 Visual identity (for art briefs)
Black canvas. Scene accent **#06b6d4** (the CATHEDRAL/OmniCorp cyan; district accents per
`districts.js` where a plate is district-specific — Grid `#00ff88`, Strip `#ff006e`, Bunker
`#a855f7`, Grid Point `#ef4444`, Junkyard `#ffab00`). Gold mono **₵** for all money. ALL-CAPS
labels in mono for headers, chips and HUD-adjacent text. Rain as texture, neon as light source,
faces lit by screens. **No emoji anywhere.**

### 7.5 NEVER-rules
- **No fourth wall.** No "quest", "stat", "roll", "NPC", "spawn", "respawn" in prose. The
  glossary's DC/crit entries exist in the canon codex, not in the narrator's mouth.
- **No game terms for the clock.** The timestamp is a date on a file, never a "timer".
- **Prices always in ₵**, always specific, never "some credits".
- **No camp, no quips at death, no lore dumps.** The Archivist explains nothing twice.
- **0xGH0ST is never met, never seen, never explained.** Messages only.
- **Cathedral is never a character.** It does not speak, want, or beg. It describes.
- **Rest is never gated. The forecast is never random.** (Engine rules 6 and 4: everything the
  count "predicts" comes off seeded streams — a replay replays.)

---

## 8. SAFETY & RATING

**Suggested ceiling: `mature`. Suggested default: `mature`.** (This story does not have a
meaningful `teen` cut; shipping one would gut the register. If the engine requires a lower
fallback, mark the story `mature`-only the way the flagship marks content it deliberately does
not ship, rather than auto-softening prose.)

In scope, handled in canon's clinical register:
- **Violence:** street-level and consequential; injuries are priced (Sable's table), never
  lingered on. Knockouts, not gore.
- **Body-horror-adjacent cyberware:** chrome as confession, Marrow's back room, "come out
  short a kidney" — implication and invoice, never surgery on the page.
- **Substance references:** synth dust, Red Lace, braindance as addiction-analogue (Jun's
  rented memory gaps). Transactional, unglamorised, no use instructions.
- **Death of the player-adjacent:** Halloran, the proxy in your coat, the forecast itself.
  The story's whole engine — keep it administrative, which is what makes it land.

Out of scope entirely: sexual content beyond canon-level innuendo (Mira's "the Grid can wait an
hour" is the ceiling); harm to children on the page (Bex is seventeen and *protected* by every
adult in the alley — keep it that way); torture scenes; self-harm framing around the timestamp
(the file is an external enemy, never an invitation).

---

## APPENDIX — Canon ambiguities resolved

1. **Heat tier names/thresholds.** `juice.js` says COLD/NOTICED/WANTED/HUNTED/BURNING at
   0/25/50/75/90; `pressure.js` says Clean/Noticed/Wanted/Hunted/Burned at 0/20/45/70/90 with
   full per-tier economics. Resolved to **`pressure.js`** — it is the systems file of record
   and matches this brief's ladder.
2. **Dane's tenure.** `story.js` Act VIII: six years at the gate. `dialogue.js`: "Fourteen
   months" on this post, transfer requested twice. Resolved: **six years standing SynthSec
   gates, fourteen months at the Grid Point** — used exactly that way in `six_years_standing`.
3. **Bunker gate.** Brief said "heat ≤ 40 + DeepState standing"; canon (`districts.js`,
   `THE_GRID.md`) is **heat ≤ 40 and standing ≥ −30** (not-hostile, not high). Canon numbers
   kept.
4. **The 21 days.** Canon CATHEDRAL spends 8 acts and ~15 levels before the timestamp comes
   due (Act VII). THE CROSSING compresses the whole story inside the 21 days — the shard's
   canon header is preserved; the act structure is not, deliberately.
5. **The Lift's location.** Canon Act VIII: "the only lift down is behind the SynthSec Grid
   Point." `districts.js` has no lift node; `shadow_crossing`, `the_lift` and `core_hall` are
   new locations extrapolated from that line and the Act VIII prose.
6. **Currency mark.** `items.js` uses bare numbers, `THE_GRID.md` uses "C50", the HUD uses gold
   mono ₵. Standardised on **₵** per the visual identity.
7. **0xGH0ST's allegiance.** Canon tags its events `faction: Ghost_Net` but never confirms the
   relationship. Kept unresolved on purpose; the bible forbids resolving it.
