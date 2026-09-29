# Changelog — HUE & CRY

What changed in **HUE & CRY**'s own content: everything under
`games/hue-and-cry/`. It uses the engine's default skin (`_engine`) until
v0.21.0's UI overhaul, so it has no UI plugin of its own yet. Engine changes,
and each release as a whole, are in the [root CHANGELOG](../../CHANGELOG.md),
which also carries every measured table this file only summarises. Version
numbers are the repo's releases, and a release is listed here only if it
changed this story. The root file is authoritative from 0.4.0 (this story
first shipped in 0.9.0); `git log -- games/hue-and-cry` is the authority for
anything this file does not place.

Like the README, this file names the secret places (the README's tables list
them and the ways in) and never says who the Magpie is.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.18.0] — 2026-09-29

### Added

- **`scripts/simulate.py --game hue-and-cry`** (v0.18 T1): this story's
  harnesses in one report, from the repo's own balance entry point.
  `--policy thief` (the default) is `simulate_endings`' heister, and any of
  its eleven policies, or `all`, may be named; `--seeds`, `--days`, `--json`.
  Each policy reports `simulate_endings`' table plus its worst wanted band,
  jobs carried out, clues, deaths and respawns and gold, and the report
  closes with the days `simulate_labour`'s careful pickpocket keeps on its
  own coin. No policy is written twice, and nothing is saved. The README's
  harness table has the row. At 40 seeds x 14 days: The Legend on 20%
  (unchanged from the endings table), 2.4 jobs carried out a run, worst
  band `hunted` on 16 seeds; the careful pickpocket keeps 31% of its days
  and dies 2.90 times a run, 95% of runs at least once (restated at the
  fences' new pay, v0.18 T3 fix round 2; it was 30% and 2.92 at T1; the
  root CHANGELOG has the rest).
- **Agenda collisions, measured** (v0.18 T2): where the Magpie, Ardane and
  Silas meet the thief, read from state (`simulate_endings.COLLISIONS`;
  `simulate.py --game hue-and-cry --policy thieves` prints the `collisions`
  block). 40 seeds x 14 days, agendas on, share of runs (mean first day):

  | Collision | heister | investigators (a/b/c) | loyalist | all |
  |---|---|---|---|---|
  | the Magpie robs a house you cased or burgled | 10% (d2.8) | 60/52/55% (d8.5-8.9) | 0% | 36% (d8.4) |
  | ... while you were there that night (20:00-05:00) | 0% | 8/8/8% | 0% | 4.5% (d7.7) |
  | ... within the same noon-to-noon day | 0% | 18/12/15% | 0% | 9% (d7.7) |
  | a Magpie robbery while you are held (the alibi) | 0% | 18/20/15% | 0% | 10.5% (d7.9) |
  | Ardane's doubled watch or warrant over a thief with hot goods or `sought`+ | 100% | 92/90/90% | 85% | 92% (d8.2) |
  | ... over a thief with hot goods, whatever the band | 92% | 92/88/85% | 62% | 84% (d8.1) |
  | Silas splits the Company under a sworn thief | 30% | 10/20/20% | 45% | 25% (d7) |

  The Magpie was there first in 101 of 122 house collisions; true
  co-presence is half the same-day figure; Ardane's net always meets the
  thief under the doubled watch, never first under the warrant, and the
  hot-goods row is the one the player's own thieving decides; Silas's split
  always lands on day 7. The root CHANGELOG has the definitions.
- **The burglar's credit, and the careful pickpocket, measured** (v0.18 T3;
  `simulate.py --game hue-and-cry --policy living`, the root CHANGELOG has
  the full table). `scripts/simulate_labour.py` gains:
  - the fencing burglar, the first policy that sells its hauls to live on;
  - the same burglar welshing on Pell's advance or on Marrow's slate;
  - a careful pickpocket who takes a porter's shift when hungry.

  Each death is now read for its cause. At 40 seeds x 14 days, with the
  fences' new pay (below):
  - **Burglary beats pickpocketing, and honest work stays the safe road.**
    The burglar keeps 7.25 days against the careful pickpocket's 4.33, and
    dies 0.7 times a run against 2.9. It earns 3.71 cr a day and ends with
    13 crowns. The honest porter keeps 13.05 days and never dies.
  - **Welshing now costs a burglar more than it gains.**
    - Kept days: -0.62 (Pell) and -0.60 (Marrow) against never borrowing.
    - Deaths: +0.7 a run.
    - Coin: it ends 9.5-11 crowns poorer.
    - Once the line breaks, neither fence buys. It fences 19.7-22.4 crowns
      a run instead of 51.7, and ends with 57-62 crowns of loot it cannot
      sell.
    - Over 10 days the advance still buys a little bread (+0.4-0.5 kept).
  - **The owner's v0.15 decision, restated.** Welshing still nets a
    purses-only pickpocket kept days (+3.1 Pell, +1.2 Marrow over 10 days,
    unchanged by the new pay). For a burglar, who needs a fence, it does
    not. The credit is unchanged.
  - **The careful pickpocket's deaths** (2.90 a run; the v0.14 pressure, not
    tuned) are all hunger: at 05:00 in bed or at 21:00 waiting for the
    night's purse, from day 5 on. None come in the street, the cells or at
    the fair.
  - **A careful thief who adapts keeps fed.** Taking a porter's shift when
    hungry, it keeps 11.9 of 14 days (the porter 13.1) and dies once in 40
    runs.

### Changed

- **The fences are made to pay** (v0.18 T3 fix round 1, the owner's
  decision; `data/tables/trade.yaml`). Pell Hollis's spread goes from 0.55
  to 0.75 and her cuts from 0.45/0.8 to 0.7/0.95. Marrow's spread goes from
  0.4 to 0.7 and her cuts from 0.7/0.85 to 0.9/0.92.
  - A hot haul now fetches 0.53 of its value at Pell's and 0.63 at
    Marrow's, where it fetched 0.25 and 0.28. A 15-crown haul is about 8
    and 9.5 crowns.
  - That is the "7 to 10 at a fence once it is hot" that
    `data/economy.yaml`'s lockpicks note always promised. The note had
    left out the spread, and is corrected.
  - Pell is still the better buyer once a thing has cooled (0.71 against
    0.64), and Marrow the better for tonight's haul.
  - Pell's spread stops at 0.75, and the lockpicks' registry value drops
    from 10 to 6 (fix rounds 2-3), so the Porters' Hall bench cannot mint
    coin, even argued to the haggle cap. In the best hands (+2 craft) a set
    made from bought makings costs 6.63, or 5.92 haggled. No counter pays
    more than 4 for one, or 5 haggled. Marrow still sells them for 15.
  - Only the pickpocket's lifted goods and the burglar's hauls sell
    differently. The jobs, hoard, endings and scrounge harnesses print
    exactly what they printed before.

## [0.17.0] — 2026-09-28

Act III and the eight endings, the fifth of the v1.0 stages: the story can
now be finished, eight ways. The Hanging Fair (days 10-12, Gallows Green)
opens Act III with the fair deck, the Showing of the Flame and the
Everflame's heart; the gallows takes a thief the Watch held from before it;
the Lantern House cells gain a jailbreak, one try a day; and `death.yaml`
makes hp 0 a respawn in the Snuffs, or The Rope when it comes in the cells
at the fair. Every ending -- Cleared, A Lantern, Honest After All,
Partners, The Legend, Guildmaster, The Dapper's City and The Rope -- has
Speak/Act/Seal, an epilogue card and a door that opens only while it is
earned, and `scripts/simulate_endings.py` measures which policy reaches
which (Measured, below). Honest After All, the one ending before, is now
earned: no thieving at all, a clean record of your own, square with the
fences, and an honest wage.

### Added

- **The Rope (`the_rope`), the fail-forward.** Taken at the fair, hanged at
  the fair, and told like a Quest for Glory death screen: warm, wry and fond
  of the player. Speak (your true last words, which the crowd takes for
  exactly what the Magpie would say), Act (the jackdaw goes for the hangman's
  brass button), Seal (the story looks at the pies, and up on the Hill
  something that shines goes missing). An epilogue row
  (`gallery_key: hanging_fair`) and a card that laughs with you -- the
  ballad sells four hundred copies, and Captain Ardane takes the file back
  out of the drawer. `fail_forward` moves from `honest_after_all` to
  `the_rope` (`data/rules/endings.yaml`). `honest_after_all` is gated since
  v0.17 Task 5 (below).
- **`data/rules/death.yaml`: death, at last.** Until now hp 0 had no
  consequence at all.
  - **Ordinary hp 0 respawns.** Hunger, a street fight and a fall off the
    roof all respawn. You wake eight hours later on the step of Old Nance's
    flophouse in the Snuffs, at 8 hp and 30 stamina, half a purse lighter,
    with a charity crust (hunger -60) and stiff hands and a sore ankle (-1
    to stealth, craft and survival, healed on the third day). The numbers
    and why they were chosen are in the file's header.
  - **Held when you fell, you wake still held** (`respawn.in_custody`, a new
    engine key, at the owner's word). You wake on the plank bench at the
    Lantern House, and the fine, days and charge stand. The interrogation is
    not dealt again, because the stay never ended. The stay ends the usual
    way: paid, served or broken out. Dying is not a way out of the cells.
    The engine's default would have released the thief and walked them free
    to the Snuffs, with the charge still filed unless a sentence being
    served had already discharged it. That was judged not acceptable (a
    free escape), and this is the fix.
  - **The one death that ends the story** is dying while the Watch holds you
    and the Hanging Fair is on (`terminal.when: {all: [{in_custody: true},
    {event_active: hanging_fair}]}`). It locks The Rope past its gates and
    plays its module. `hanging_fair` is the Hanging Fair's declared event
    (below: days 10-12).
  - Rule 6 is untouched: every bed, the cells' bench and a rough night stay
    as they were.
  - **Known gap: a quiet death on fair day.** A death in the cells while the
    fair is on is The Rope whatever brought hp to 0. If the cause is hunger
    inside a stretch of hours (a rest, waiting), the turn's prose gets no
    death receipt (a card beat's death does get one), so the story jumps straight to the
    scaffold, with the ending module's beats as the only explanation. The
    hanging itself now has its own scene (the gallows, below), so the gap is
    narrowed to a thief who starves in the cell during the fair. Recorded in
    CLAUDE.md and in death.yaml's header.
- **The Rope's death door** is registered in `tests/test_finales.py`'s
  per-ending doors and driven through the real death path: the clock walked
  into the declared fair, not a stand-in event. Its hanging door (below) is
  its second row.
- **The Hanging Fair, and Act III** (v0.17 Task 3). A declared world event,
  `hanging_fair` (`data/world/schedules.yaml`, the story's first
  `paths.world_schedules`): day 10, three days long, on Gallows Green, raised
  by the calendar's day roll. Day 10 was proposed here: after most
  initiations (night one to four) and around the measured investigator's
  unmasking (mean day 9, 60% by day 12), with every fair ending landing on
  day 10-13, inside a 12-16 day run. Task 8 measured it against days 8 and
  12 and kept it (Measured, below). Three days, as the lore has it, so a thief across the city or in the cells
  has time to reach the Green or get out first. No flagship caravan, tinker
  or militia is staged: the file declares `events:` only.
  - **Act III, `the_hanging_fair`** (`data/quests/arcs.yaml`, order 3,
    narrated), opens on `event_seen: hanging_fair` and so stays the act after
    the fair. Its ACT line says nothing about what the Watch believes of you
    (a right naming may have broken that by then) and nothing about who the
    Magpie is.
  - **The fair deck** (`data/scenes/fair_day.yaml`), forced by the event and
    waiting on its own `when:` (the event, the Green, free): dealt on the
    first turn you stand on Gallows Green during the fair, and again on each
    return (it is `repeatable`: walk off the Green and back and whatever has
    come due since -- a door card for a Magpie unmasked on day 11 -- is
    offered; the Showing is `once`, and the spine tells the fair only the
    first time, then just the ballad and a line). The spine is
    the crowd, the ballad (whose verse reads the Watch's belief off the
    Law's links: your nose on the woodcut, or, after a right naming, a new
    verse about a stranger it took for the Magpie), the Showing of the Flame
    seen from the Green, and the gallows in bunting. Then the Showing itself:
    watch the Everflame's heart catch the sun (no roll), or go up the Hill
    for it -- stealth, `severe`. Won: the heart, a ledger fact, and a
    `sacrilege` report against the Magpie's mask up the Rise (0.6). Lost: a
    Lantern had your wrist, `sacrilege` against your own face in the Wick
    (1.0), `sought` for the rest of the fair. Every card has a way through
    with no roll. An arrest during the fair still deals the interrogation.
  - **A warning, where it is needed.** From day 7 until the fair comes, the
    interrogation's spine has a bill on the wall: whoever the Watch is still
    holding when the fair comes goes down to the Green on its last morning.
    That is the one place a thief at risk of the gallows stands, and nothing
    else announces the fair.
  - **Ending doors reserved for Tasks 5 and 6.** The deck's header reserves
    `F3_the_real_magpie` (Cleared, A Lantern), `F4_silas_makes_his_move` (The
    Dapper's City), `F5_gannets_stake` (Guildmaster) and
    `F6_the_heist_together` (Partners), and says what each may read. None is
    a card yet. The heist is built; its lock is The Legend's getaway, T6's.
    (Since Task 5, F3 is built -- Cleared's door only, below; A Lantern's
    door is the front desk.)
  - **The gallows** (`data/scenes/the_gallows.yaml`): The Rope's hanging
    door. Dealt in the cell from nine on the fair's last morning (day 12) to
    a thief the Watch was already holding when the fair came
    (`held_before_event: hanging_fair`, a new engine predicate). One card --
    how you go down the Hill: head up, arguing your case, or looking for the
    jackdaw -- every answer roll-free, each locking `the_rope` by name and
    playing its module. A thief taken DURING the fair is questioned and may
    pay or serve like anyone else. Until nine on the last day a held thief
    can still pay the fine (or break out, Task 4); serving does not wait the
    fair out, because a sentence now stops when a scene falls due in the
    middle of it (engine, root CHANGELOG), and this is that scene.
  - **The Everflame's heart** (`everflame_heart`, `data/items/goods.yaml`):
    named, shiny, and a `relic`, a new tag no counter deals in
    (`never_traded_tags: [relic]` in `data/tables/trade.yaml`; fence or
    honest). Stolen from the Margrave's household, so hot for good and taken
    back by the Watch at any arrest. Not a piece of the Magpie's Hoard, and
    in no house: the Treasury's header already said it is not there.
  - **`sacrilege`**, severity 5 (`data/rules/law.yaml`, beside
    `assault_watch`), filed only by the heist. Its bands, by the file's own
    arithmetic, are in the law file's header.
- **The jailbreak** (v0.17 Task 4, `data/challenges/lantern_house.yaml`, the
  story's first `paths.challenges`). A third way out of the Lantern House
  cells, beside the fine and the wait, offered through `set_piece` only
  while you are held (`requires: {in_custody: true}`) and once the
  interrogation's cards are answered. On the Hanging Fair's last morning it
  is the only way past the gallows for a thief who cannot pay: the gallows
  is dealt at nine to a thief still held, and a thief who broke out before
  nine is not.
  - **Two skill gauntlets, never a dice table.** The ring on the nail
    (stealth, then nerve: lift the sleeping Lantern's keys, then walk past
    the duty desk as if somebody sent for you) until it has once worked;
    then, on every stay after, the window bar (craft, then stealth: a supper
    spoon on a rusted bar, then the yard wall). The first retires by its
    `grants_flag` (`broke_out_of_the_lantern_house`); the second reads that
    flag and grants none, so no stay is ever without it. Both steps are
    `easy`: about one try in three for every archetype (the table is in the
    file's header).
  - **Success:** `release` -- you stand free on the Lantern House's back
    step -- and a fresh `escape` report, filed against your own face in the
    Wick at full precision. A break-out discharges nothing, so everything
    the arrest charged is still on file too.
  - **Failure:** a hiding, `hp -3`, the door locked again, and **no second
    try until tomorrow** (`retry: next_day`; midnight reopens it). The fine
    and the days stand, the bench is still a bed (rule 6), and `serve` still
    ends the stay. One try a day because a try costs no time: rolled again
    and again inside one turn, nine thieves in ten walked out of every stay,
    for less than the fine. A thief the Watch saves up for the fair still has
    a try on day 10, day 11 and day 12 before nine. The cells heal nothing,
    and a hiding can kill a thief already low, checked on the step that took
    it -- before the fair you wake on the same bench, still held; held at the
    fair it is The Rope. The failure texts say nothing of how badly you are
    hurt, so they read true either way.
  - **Failure costs hp, not days,** because the engine has no authored way
    to lengthen a stay (the custody record's `days` is the arrest's alone).
  - **`escape`**, severity 4 (`data/rules/law.yaml`): `sought` in the Wick as
    you walk out, and felt for three days. Measured; the table is in the law
    file's header.
  - The lore gains "Going Out Without Leave" (`the_lantern_watch.md`).
- **Endings I: Cleared, A Lantern, and Honest After All earned** (v0.17 Task
  5). Every one through its own door, every door locking its ending by name
  and opening only while the ending is earned -- the door asks
  `{ending: {eligible: <id>}}` itself, so the gate is written once, in
  `data/rules/endings.yaml`, whose header has the rulings.
  - **Cleared** (`cleared`). Requires the Watch's belief broken:
    `magpie_unmasked`, which only a right naming at the front desk sets. An
    alibi is not enough -- it clears the nights you were held and leaves the
    Watch believing you are the Magpie (v0.16's ruling). While a wrong name
    you gave the captain stands uncorrected (`magpie_named_wrongly` without a
    right naming after it) the ending is out of reach, and the gallery says
    why. **Two doors.** During the fair, `F3_the_real_magpie`
    (`fair_day.yaml`, roll-free) is dealt on the Green while Cleared is
    earned -- the Magpie you named is there, and the Watch closes in. See it
    done (locks Cleared, then Speak/Act/Seal: the captain says your name out
    loud with "not" in front of the other one; the young Lantern shakes your
    hand; a new verse of the ballad) or walk away, and it is offered again on
    your next return to the Green (not `once`: the owner's decision -- a door
    gated on its own ending's eligibility cannot be walked through twice).
    After the fair, `D4_cleared_at_the_desk` (`lantern_house_desk.yaml`,
    the captain's hours): the captain burns the old drawing and reads your
    name out to the front room -- so a thief who names the Magpie after the
    fair, or walked away from F3, still has a door (controller's ruling).
    Neither card names anybody: both come only after the unmasking, when the
    narrator's GM line already names the Magpie; the beats and card name no
    place, so both doors tell them true.
  - **A Lantern** (`a_lantern`). Requires `magpie_unmasked`, the Watch's good
    opinion (`lantern_watch` 5 or more: five good rounds of the lamps with
    Wren, measured below), and the captain's own file never struck against
    her (no `ardane_magpie_file` thread, in any status). **The door is the
    front desk:** `D3_the_badge` (`lantern_house_desk.yaml`), dealt free
    while Captain Ardane is in and the ending is earned. Take the badge and
    swear the oath (locks A Lantern), or keep it back and it is offered again
    next visit. A thief who has earned the badge has earned Cleared too, so
    the badge card offers both (T5 review round 2): take the badge, or ask
    only for your name cleared (locks Cleared) -- one card, a choice the
    player can see. D4 serves the Cleared-only thief after the fair.
  - **Honest After All**, gated at last: a clean name (below `sought` in all
    three watch-houses, counting YOUR OWN deeds only -- the owner's decision:
    the Magpie's robberies the Watch pins on you while it links you to the
    Magpie do not count, a heist you pulled under the Magpie's mask does, and
    `noticed` will do; the engine's new `wanted {own: true}`), square
    with the fences (no credit open, no welsh on either book), and an honest
    wage earned. **The door stays the evening barge**, whose stage now waits
    on the ending; an unearned thief is simply not taken, nothing is locked,
    and the narrator hears why in the bargemaster's terms (the stage's new
    `refusals`, an engine seam: the objective line says "Not yet: ...", and
    the flag that would say "aboard" is not offered while it holds). Its
    epilogue card and Seal no longer assume the Magpie is still unknown.
  - **The labour record.** Every posting's new `effects` writes
    `honest_wage_earned` on the degrees it pays (`data/tables/labour.yaml`);
    a botched shift is no wage. Nothing else changes about work.
  - Each has an epilogue row and card (`magpie_taken`, `lantern_badge`), a
    row in `tests/test_finales.py`'s per-ending doors (Cleared two), and a
    row in its `UNEARNED_DOORS`: the same door walked with the gate unmet
    stays shut.

- **Endings II: Partners, The Legend, Guildmaster, The Dapper's City**
  (v0.17 Task 6). All eight of the design's endings are declared now, each
  with Speak/Act/Seal, an epilogue row and card, a door that locks it by name
  and opens only while it is earned, a row in `tests/test_finales.py`'s
  per-ending doors and one in its `UNEARNED_DOORS`. No hand can hold two
  doors: the gates keep every pair that shares a deck apart (asserted over
  every combination of the facts they read).
  - **Partners** (`partners`). Follow the trail to the Magpie's own door
    instead of the captain's: a new repeatable deck,
    `data/scenes/the_confrontation.yaml`, dealt at the suspect's haunt at an
    hour they are there (Wren up the garret stair, Silas in the flophouse
    taproom, Lady Imelda in her parlour or at the silversmith's window),
    free, on the accusation's own bar (evidence 2, the clues favouring that
    suspect, a suspect named or confronted wrongly set aside). Say it --
    "I know what you are, and I want in" -- and whether you are right is
    decided only then, by `agenda_role` in the beat's own gate. Rightly: the
    Magpie takes you on (`partners_with_the_magpie`, a ledger fact), and from
    the next line the narrator is told who the Magpie is (the mask's
    `unmask_when` now reads the partnership as well as the right naming);
    the Watch is told nothing. Wrongly: the lead is spent (`clue_fresh`),
    that suspect is set aside, and their people hear of it -- 5 off the
    Lantern Watch (Wren), the Honest Company (Silas) or the Silk Row houses
    (Lady Imelda); nothing arrests and no ending closes. The door is the
    fair's `F6_the_heist_together`: at the Showing, the heart taken with the
    Magpie (roll-free; re-offered until taken). Requires the partnership and
    the heart not already taken alone; out of reach for good once you name
    the Magpie to the captain (you have sold them). A partner is offered F6
    and not F2 -- one Showing card, one choice.
  - **The Legend** (`the_legend`). Lift the heart alone at the Showing (F2,
    severe stealth, as before) and get it home: the heist starts a new quest,
    `data/quests/the_hanging_fair/the_heart_goes_home.yaml`, and reaching the
    Snuffs with the heart, free, locks the ending. Taken first, the Watch has
    the heart back and the getaway fails. Its closeness score and its Seal
    read `magpies_hoard_complete` -- the Hoard flag's first reader.
  - **Guildmaster** (`guildmaster`). Sworn to the Company; the Hall's good
    opinion at 5 or more (measured below); Mother Gannet's measure taken --
    her Silk Row job done and paid, or the strike fund's IOUs held or struck;
    and no heart in the pack. Out of reach while Silas Crook's rise has won.
    The door is a new repeatable deck, `data/scenes/porters_hall.yaml`: the
    long table any evening Gannet holds court (18:00-04:00) while the ending
    is earned. Every clause can be met before the fair, so the fair's
    reserved `F5_gannets_stake` was released unbuilt.
  - **The Dapper's City** (`the_dappers_city`). Silas's rise complete
    (`silas_splits_the_company`) and sworn to the Company; never for a thief
    who named the Magpie to the captain or threw in with the Magpie. The door
    is the fair's `F4_silas_makes_his_move`: stand with him, or stand against
    him in front of the Company and lose (a hard persuasion roll failed) --
    both lock it. Stand against him and win, and he is stopped
    (`silas_stopped`): the Company +5, his two agenda moves stop, The
    Dapper's City shuts and Guildmaster opens again. Keep out of it and it is
    offered again.
  - **The Temple of the Everflame moves** at last: the heart taken off the
    palace steps, alone or with a partner, costs 10 of its good opinion.
  - **Honest After All is empty-handed** (T6 review round 1): a new clause,
    `empty_handed` (no Everflame's heart in the pack), and a fourth barge
    refusal to match. After a right naming the heist's sacrilege is filed on
    the Magpie's file alone, so an unmasked thief's own record read clean and
    the barge would have taken the relic aboard as Honest After All.
  - **The front desk honours a wrong confrontation** (T6 review round 1): a
    suspect confronted wrongly at their door is set aside at the desk as one
    named wrongly is, and a wrong confrontation spends the lead there too
    (a second naming waits for a clue carried out since) -- so the right
    suspect surfaces at the desk without a false naming first.
  - **Measured by Task 8 (below):** Guildmaster's gate can be met in the
    first week (a won initiation and Gannet's Silk Row job), and its door is
    open any evening, so a run can end as Guildmaster on days 2-4, before
    Act III -- 45% of the harness loyalist's runs do.
- **All eight, held (v0.17 Task 7): the endings audited as a set.** Tests,
  no new mechanism:
  - **One set of ids.** `endings.yaml`'s classes, the epilogue index's ids
    and classes, and the prose file's cards are the same eight, each index
    title its ending's label; every ending has Speak/Act/Seal, and all 24
    beats (both branches of the Legend's Hoard-gated Seal) resolve through
    the deck engine with no unknown effect.
  - **Every ending through its real door** (`tests/test_finales.py`
    `ENDING_DOORS`, all eight, `COMPLETE_DOORS` enforcing it), and **every
    gate clause has an unearned row**: 26 `UNEARNED_DOORS` rows, each
    leaving out exactly the clause it names -- asserted as the ONLY reason
    the ending is not eligible -- and a coverage test that fails if a
    clause of any earned ending has no row. Two clauses cannot fail alone,
    and the rows say why: Cleared's `no_wrong_name_standing` (its `any`
    includes the unmasking it requires), and The Legend's `still_free`
    (an arrest takes the heart with it, so a held thief fails `the_heart`
    too).
  - **`resolve()` never picks an unearned ending**: a seeded sample of 120
    states over every fact the gates read, oaths sworn and then broken --
    `resolve` answers an ending whose own gate holds, or The Rope, and
    `lock` refuses everything the report does not call eligible.
  - **The Rope, in one place**: its two doors (the death at the fair, the
    hanging) are driven rows; an ordinary hp 0 -- free on any day, free at
    the fair, or held the day before it -- respawns (held, if held), locks
    nothing and shows no epilogue.
  - **Secrecy**: the GM line names the Magpie only after the right naming
    or the partnership, whatever else the thief has done (a played-out
    ending included); no sentence of any ending text -- the gallery's, the
    module's or the card's -- pairs "Magpie" with a candidate; nothing
    shows a module or card before its lock; no deck or card anywhere
    decides presence by `agenda_role` (only six beat gates read it); the
    no-sex guard is pinned to read Act III's files.
- **The endings, measured (v0.17 Task 8).** `scripts/simulate_endings.py`
  (committed) plays eleven policies from the morning barge to two days past
  the fair and reads the ending each run locks; the table is under
  Measured, below. Every ending is reached by a policy that plays for it,
  none crowds out the rest, and day 10 is kept for the fair; three of its
  findings the owner ruled on (fix round 1, next). Tests:
  - every ending is reached, through its door, by the policy that plays for
    it on a pinned seed; the harness replays byte for byte; it reads the
    fair the story declares; and no policy's code reads the Magpie's role,
    a clue's `points_to`, `clues_favour`, or an ending's eligibility (the
    table alone reads that).
  - **`resolve()`, the combinations the sample never reached** (T7's
    review): a partner who then names the Magpie at the desk falls to
    Cleared; a thief bound for the barge who then lifts the heart, to The
    Legend; Gannet's needles earned and then Silas's rise won, to The
    Dapper's City -- each sworn while eligible, broken, and the pick and the
    locks asserted. Cleared sworn on a right naming survives a later wrong
    one (the right naming stands over it); before any right naming it can
    be neither sworn nor picked. The sampled property test now checks every
    pick and every eligible ending against what each ending needs and
    forbids in terms of the facts applied, written from the design (it had
    asked the gate itself, which agreed with `endings.eligible` by
    construction).
- **Three rulings on what the harness found (v0.17 Task 8, fix round 1;
  the owner's).**
  - **Honest After All means no thieving at all.** A new first clause,
    `never_stole`: no lift, burglary or fencing the thief ever COMMITTED,
    seen or unseen, and no hand laid on the Everflame's heart at the
    Showing, won or lost. The engine now counts every deed it commits
    before it looks for a witness (`committed_deed`, root CHANGELOG), and
    the Showing's heist sets `laid_a_hand_on_the_heart` on both branches
    (its ledger fact moves to the getaway's `on_start`, the same turn: an
    outcome keeps four effects). The own-record clause (`a_clean_name`)
    stays beside it: the Watch's file also holds what is not thieving -- a
    Lantern knocked down, a jailbreak, a false name at the desk, a squeeze
    sworn to. The barge's first refusal says so, in the bargemaster's
    terms, first because it never cools: nobody is told to wait for the
    Watch to forget a theft. (The measured runner, a reckless pickpocket
    after one honest shift, boarded on 30 of 40 runs, 22 of them the
    evening of its first purses; now on none.)
  - **Gannet waits for the fair.** Guildmaster gains `the_fair_has_come`
    (`event_seen: hanging_fair`): she names a successor only once the
    Hanging Fair has come, at it or after it, and the gallery says why. The
    Porters' Hall door reads the ending's eligibility, so it stays shut
    until then. (Measured: 18 of the loyalist's 40 runs had taken the chair
    on days 3-7; now none before day 10.)
  - **Partners after the fair: the last job.** A second door,
    `data/scenes/the_last_job.yaml` `L1_the_heart_by_night`: once the fair
    has come and gone, on Margrave's Hill after dark (the clock's night,
    20:00-05:00 since fix round 2; 22:00-04:00 before), a
    partner is dealt the heart out of the Everflame itself -- make the
    noise, and the Magpie does the rest. Gated on Partners' own eligibility,
    repeatable, "not yet" never the last chance; never open during the fair
    (F6 is the door then). Legible: the partnership's own words now say
    where ("at the Hanging Fair, or after it, up the Hill after dark"), and
    F6's "not yet" says the same. Partners' Act beat has two tellings (the
    Showing's while the fair is on, the night's after it); its Speak and
    Seal are true of both. (Measured: 2 of the partner's 40 runs threw in
    with the Magpie on the last night and had nowhere to go; both now end
    as Partners, by night.)

- **Fix round 2 (v0.17 Task 8; the controller's rulings on the review).**
  - **A squeeze is thieving.** `never_stole` also reads any Blackmail-tagged
    thread, in any status: a squeeze paid commits and files nothing, so only
    the thread remembers it. The barge has a matching refusal, second, in the
    bargemaster's words.
  - **"After dark" means the dark.** The last job's window widens from
    22:00-04:00 to the clock's whole night, 20:00-05:00, so the partnership's
    words and the Hill's hours agree; its header quotes what shipped.
  - **Nothing authored is cut short in silence** (root CHANGELOG). The
    validator's new check found eight HUE & CRY cards whose text the loader
    had been cutting at 600 characters -- `F1`, `F3`, `F4`, `F6`, `I1`,
    `P1`, `G1` and `L1` -- which had cost the narrator, among other lines,
    F3's "nothing on this card arrests anyone but the Magpie", F6's and
    L1's "MENU" instruction, and the gallows' "name no suspect as the real
    Magpie". Since fix round 3 authored text has its own cap (root
    CHANGELOG), and all eight cards are back to their authored text, whole:
    those lines now reach the narrator.
  - **Re-measured:** `simulate_endings` at 40 seeds is identical, policy
    for policy, to fix round 1's table below (no harness policy squeezes
    anyone, and the partners who reach the Hill after the fair arrive after
    22:00 anyway); every earlier harness is byte-identical.

### Measured (rule 10)

- **The endings (v0.17 T8), 40 seeds, fair days 10-12, each run to the end
  of day 14,** `scripts/simulate_endings.py` (committed; agendas on; runs
  out of 40; the policies are in its header -- each acts only on what a
  player sees, and takes a door because a card or the gangplank offered it):

  | policy (opening) | Cleared | A Lantern | Honest | Partners | Legend | Guildmaster | Dapper's | Rope | none |
  |---|---|---|---|---|---|---|---|---|---|
  | investigator (a) | 29 | | | | | | | 2 | 9 |
  | investigator (b) | 27 | | | | | | | 2 | 11 |
  | investigator (c) | 28 | | | | | | | 1 | 11 |
  | lantern (c) | 8 | 12 | | | | | | | 20 |
  | partner (b) | | | | 20 | | | | | 20 |
  | heister (b) | | | | | 8 | | | | 32 |
  | loyalist (b) | | | | | | 18 | 10 | | 12 |
  | dapper (b) | | | | | | | 17 | | 23 |
  | porter (b) | | | 40 | | | | | | |
  | reckless (a) | | | | | | | | 3 | 37 |
  | runner (a) | | | | | | | | 3 | 37 |

  (Restated after fix round 1, above. Before it: partner 18 Partners and 22
  none; loyalist 24 Guildmaster, 5 Dapper's, 11 none; runner 30 Honest
  After All, 1 Rope, 9 none. Every other row is unchanged.)

  **Reach.** Every ending is reached by at least one policy that plays for
  it: Cleared 72.5% at best (29/40), Honest After All 100%, Partners 50%,
  Guildmaster 45%, The Dapper's City 42.5%, A Lantern 30%, The Legend 20%,
  The Rope 7.5% (3/40, the reckless pickpocket and the runner alike; 10%
  for the reckless one with nobody breaking out, below). The Rope is reached by five policies, every time by the gallows
  on the fair's last morning, never by a death in the cells (the harness
  feeds its prisoners). No ending crowds out another: each policy's own
  ending, or none, is all but every run; "none" is a run that has earned
  nothing by day 14 (the trail unread, the heart dropped, Silas never
  risen) and would go on.

  **When each locks** (mean day; the days seen): Cleared 10.7-10.9 (days
  10/11/12/13/14 on 17-19/4-6/1/1/2-4 runs of each investigator: 24 through
  the fair's `F3`, 3-5 at the desk's `D4` after it; the lantern's 8 on day
  14, its fallback). A Lantern 12.8 (days 11-14, `D3`). Partners 10.7 (18
  on days 10-12 through `F6`; 2 by night after the fair through
  `the_last_job`'s `L1`, on day 14 and in the small hours after it). The
  Legend 10 (all 8 on the fair's first day, the getaway home). Guildmaster
  10.7 (days 10/12/13/14 on 14/1/2/1 runs: none before the fair). The
  Dapper's City 10 (`F4`, all on day 10: the dapper's 17 and the
  loyalist's 10 who stood against Silas and lost). Honest After All: the
  porter's 40 on day 10 (it boards the evening it has seen the fair). The
  Rope 12 (the gallows).

  **How early each ending is open** (the first end of day it was eligible,
  read by the table, never by a policy): Honest After All from day 1.4 for
  every porter (its first paid shift) and, until its first purse, 1.3 for
  78% of runners; Guildmaster from day 10.7 for 45% of loyalists (from 5.5
  for 60% before fix round 1); The Dapper's City from day 7 for 42.5% of
  sworn porters (Silas's rise, as T6 measured); Cleared from day 9.2-9.6
  for 68-73% of investigators; Partners from 8.9 for 50% of partners; A
  Lantern 12.8, 30%; The Legend on day 10, 20%.

  **Guildmaster before Act III** (carried from T6): before fix round 1, 18
  of the loyalist's 40 runs ended as Guildmaster before the fair -- 12 on
  day 3, 5 on day 4, 1 on day 7 -- every one sworn on its first night and
  Gannet's Silk Row job done and paid. The owner ruled she waits for the
  fair (above): now none does, and 18 of 40 take the chair from day 10
  (14 of them that night). The loyalist's other runs: 10 stood against
  Silas at the fair and lost (The Dapper's City, 5 before), 12 end with
  nothing -- Silas's rise won and not stood against, or the Hall's good
  opinion short.

  **The barge and a thief's own deeds** (carried from T5): before fix round
  1 the runner -- the reckless pickpocket after one honest shift on its
  first morning -- asked at the gangplank 164 times over its 40 runs: refused
  106 times for its own record (`sought` somewhere, on 13 runs), 28 for no
  wage, and taken aboard on 30 runs, 22 of them the evening of its first
  day's purses (a lift nobody reported was on no file). Since the owner's
  ruling it is refused all 431 times it asks, on all 40 runs, for having
  stolen (`never_stole`, the barge's first refusal), and stays in the city:
  held at some hour of the fair on 37.5% of runs, and hanged on 3 (1
  before). The porter is never refused.

  **The fair's day, measured and kept at 10.** The same eleven policies
  with the fair moved (`--fair-day N`, the gallows' last morning with it;
  each run to its fair's last day + 2; re-run after fix round 1, before it
  in brackets where it moved):

  | fair begins | Cleared (best investigator) | A Lantern | Partners | Legend | Guildmaster | Dapper's (dapper) | Rope (best) |
  |---|---|---|---|---|---|---|---|
  | day 8 | 24 | 5 | 18 [15] | 8 | 12 [19] | 17 | 2 |
  | **day 10** | **29** | **12** | **20 [18]** | **8** | **18 [24]** | **17** | **3** |
  | day 12 | 30 | 17 | 24 [18] | 8 | 18 [25] | 17 | 2 [1] |

  Earlier, fewer investigators have unmasked by the fair and the
  lamplighter has fewer rounds behind it, and Guildmaster -- waiting for
  the fair since fix round 1 -- goes to 12 loyalists, 14 losing to Silas at
  it instead; later, the trail endings gain a little, Partners' last
  job catches more late partnerships, the run is two days longer, and The
  Rope thins (fewer reckless thieves are held from before a later fair to
  its last morning). Day 10 keeps every ending at 7.5% or more; day 8 drops
  A Lantern to 12.5%, day 12 The Rope to 5%. The gallows' `min_day` is
  unchanged (the test that holds it to the fair's last day stands).

  **The fair, the gallows, the jailbreak, the heist.** On the Green during
  the fair: every heister, dapper, porter and loyalist (day 10), 60% of
  investigators (the unmasked, day 10.3), 47.5% of partners, a third of
  lamplighters. Held at some hour of the fair: 5-10% of investigators, 65%
  of reckless thieves (most taken during it, and so questioned, not
  hanged), 37.5% of runners. Hanged: 11 of the 440 runs. The jailbreak: the
  reckless thief tried it in 38 runs (73 tries, 24 escapes, 33%), the
  runner in 38 (67 tries, 23 escapes); with nobody breaking out
  (`--break-out none`) the reckless thief hangs on 4 runs instead of 3 (the
  runner's control was measured before fix round 1: 1 either way). The investigators pay or serve, as `simulate_acts`'
  investigator always has (T4 left the choice here); breaking out
  (`--break-out all`) would have saved one of the two hanged in openings a
  and b each (7 and 8 tries, 2 escapes each), and moves Cleared by one run. The heist: every heister tries the heart on the fair's
  first morning; the severe roll wins it on 8 of 40, and all 8 get it home
  to the Snuffs (The Legend). No heister was arrested before the fair (3
  careful jobs each).

  **Not measured here: welshing's cost for a burglar shut out of both
  fences** (the owner's v0.15 decision). No policy in this harness sells to
  a fence or runs a line of credit; it stays with v0.18.0's thief policy
  (CLAUDE.md's roadmap row), starting from T2's figures below.

  **Every earlier harness, re-run at 40 seeds against the commit before**
  (a scratch worktree): `simulate_acts` (every opening), `simulate_law`
  (every policy, and `--break-out` careful/c and reckless),
  `simulate_labour` (every policy; `--endings --days 12 --agendas`, all
  policies and the bunked porter), `simulate_hoard`, `simulate_jobs`,
  `simulate_agendas`, `simulate_scrounge` and `simulate_streets` are
  byte-identical apart from wall-clock timing columns. No bound moved.
  `simulate_acts` gained three seams (`choose_beat`, `CASING_ENDS` and, in
  fix round 1, `trail_done`) whose defaults are its own. **Re-run after fix
  round 1** (the deed count, the new clauses and door, the heist's flag):
  every one of them is byte-identical again apart from timing -- none of
  their policies' tables reads Honest After All but `simulate_labour
  --endings`, whose porter and dipper never steal and whose pickpockets
  already never qualified (no wage, or on credit).

- **Endings II (v0.17 T6), 40 seeds x 12 days,** `scripts/simulate_labour.py
  --endings --days 12 --policy porter --bed bunk --agendas` (committed): a
  porter sworn to the Company on its first night, on the quay every day,
  Silas's agenda on.

  | end of day | 3 | 5 | 8 | 10 | 12 |
  |---|---|---|---|---|---|
  | `honest_company` >= 5 (`hall_trusts`) | 20% | 8% | 10% | 20% | 30% |
  | Silas's rise has won (`silas_won`) | 0% | 0% | 42% | 42% | 42% |

  5 is Guildmaster's number. The standing falls as Silas robs the Company's
  ward (-2 a house), so a porter who only works holds it on a fifth of seeds
  by the fair; standing against Silas (+5, and his robbing stops) or the
  Hoard (+8) carry a thief well over it. From the same walk (a scratch read
  of the standing): at 4 or more 60/38/22/28/45%, at 6 or more
  5/8/5/8/18% -- 4 is the roll-free oath and no more, 6 one seed in twelve at
  the fair. Silas wins on 42% of seeds, every one by day 8.
  `simulate_acts --opening all` (40 seeds, 12 days) is byte-identical to the
  commit before, apart from wall-clock timing: its investigator never stands
  at a suspect's haunt at their hour with a lead, is never sworn with
  Silas's rise complete at the fair, and never earns Guildmaster, so no new
  card is dealt to it. Task 8 measures the eight endings as a distribution.
- **Endings I (v0.17 T5), 40 seeds x 12 days,** `scripts/simulate_labour.py
  --endings --days 12 [--agendas]` (committed; share of seeds at the end of
  each day):

  | policy, end of day | 3 | 5 | 8 | 10 | 12 |
  |---|---|---|---|---|---|
  | porter, `lantern_watch` >= 5 (off or on) | 0% | 8% | 50% | 70% | 85% |
  | porter, Honest After All earned, agendas off | 100% | 100% | 100% | 100% | 100% |
  | porter, Honest After All earned, agendas ON | 100% | 100% | 100% | 100% | 100% |
  | porter, whole file below `sought`, agendas on (for comparison) | 70% | 53% | 5% | 0% | 5% |
  | dipper, earned (off or on) | 98% | 100% | 100% | 100% | 100% |
  | careful pickpocket, earned (either) | 0% | 0% | 0% | 0% | 0% |
  | careful on Pell's credit, earned (either) | 0% | 0% | 0% | 0% | 0% |

  The lamps: 5 is five good rounds; `lantern_watch` means 5.7 on day 10 for
  a thief who walks the lamps every evening, and 0 for one who never does
  (at 4: 80% by day 8, near a formality; at 6: 75% by day 12). The barge:
  every honest worker has the wage from its first paid shift (the dipper's
  one miss is a day-one botched shift), the careful pickpocket never works,
  and Pell's borrower is on credit or welshed on 97.5% of its days. With the
  agendas on, the Magpie's robberies still land on the face the Watch links
  to it -- the whole file is `sought` somewhere on 30% of seeds by day 3 and
  95% by day 8, as the comparison row shows -- but since fix round 1 (the
  owner's decision) Honest After All reads the thief's own record only
  (`wanted {own: true}`), so an honest worker keeps the barge open all run.
  Before the fix it closed on 47% by day 5 and 95% by day 8. **Not yet
  measured: a thief refused for their OWN deeds.** No simulate_labour policy
  commits a reportable deed of its own (the careful pickpocket's purses are
  unwitnessed on these seeds), so no row above shows the clean-name clause
  shutting anyone out; Task 8 measured it with a thieving policy (above).
  `simulate_acts --opening all` (40 seeds, 12 days) is
  byte-identical to the commit before: its investigator never lamplights, so
  the badge is never dealt; it never boards the barge; and F3 moves nothing
  it measures (Task 8 extends it past the fair and reads the endings).

**death.yaml (v0.17 T2).** 40 seeds, agendas off. Everything is re-run against the code before
death.yaml.

- **simulate_labour, 10 days, flophouse.** The harnesses now count deaths as
  they happen (`simulate_law.counting_deaths`), because a respawn restores hp
  inside the hour that reached 0 and the sampled `min_hp` no longer shows it.
  "At 0" is now a death.

  | policy | kept_days | fed_days | end gold | at 0 hp / died | deaths/run |
  |---|---|---|---|---|---|
  | porter | 0.94 → 0.94 | 0.99 → 0.99 | 5.47 → 5.47 | 0% → 0% | 0 |
  | dipper | 0.87 → 0.87 | 0.96 → 0.97 | 5.90 → 5.92 | 5% → 5% | 0.07 |
  | careful | 0.07 → 0.26 | 0.22 → 0.51 | 2.17 → 3.65 | 95% → 95% | 1.9 |
  | scrounger | 0.93 → 0.93 | 0.97 → 0.97 | 4.50 → 4.50 | 0% → 0% | 0 |
  | careful_pell | 0.54 → 0.57 | 0.68 → 0.72 | 1.85 → 2.58 | 45% → 52.5% | 0.53 |
  | careful_marrow | 0.31 → 0.38 | 0.45 → 0.59 | 1.27 → 2.75 | 82.5% → 87.5% | 1.3 |

  The careful pickpocket still reaches 0 on 95% of seeds, about twice a run.
  It now wakes and goes on instead of lying at 0 hp for the rest of the ten
  days, so it keeps more days (0.07 → 0.26), lifts more (1.36 → 1.50 cr a
  day) and ends richer. The credit policies die slightly more often than
  they sat at 0 before (a respawn that wakes them starving again can reach 0
  twice). The honest days (porter, scrounger) do not move, and the dipper's
  one starving seed now respawns.

  With `--bed bunk` (the guild's free bed), porter, dipper, scrounger and
  careful_pell are unchanged (0 deaths).

  | policy | kept_days | at 0 hp / died | deaths/run |
  |---|---|---|---|
  | careful | 0.39 → 0.53 | 57.5% → 72.5% | 0.85 |
  | careful_marrow | 0.70 → 0.71 | 10% → 20% | 0.2 |

  More runs "reach 0" than the old sampling showed. This is not separated
  further here. Two things plausibly add to it: the "before" column read hp
  only between actions, so a 0 touched inside a long stretch of hours and
  climbed back from (a bed's +1) was never counted; and a respawn's half
  purse can starve a thief who would not otherwise have starved.
- **Welshing's gain over never borrowing shrank.** The owner accepted it for
  v0.15. Over the 10 flophouse days it was about +4.7 kept days (Pell's
  advance) and +2.4 (Marrow's slate). It is now about +3.1 and +1.2 (careful
  0.26, Pell 0.57, Marrow 0.38). The credit lines did not change: the
  respawn keeps the no-credit baseline alive, so it no longer lies at 0 hp
  for the rest of the run. v0.18.0's thief policy re-measures welshing
  anyway, and should start from these figures.
- **simulate_streets (3 days), simulate_jobs (every policy) and
  simulate_acts (all three openings, 12 days):** byte-identical tables. None
  of them reaches 0 hp (streets min 20, jobs min 20, acts min 10–12), so
  none has a death to respawn.

- **The Hanging Fair in the harnesses (v0.17 T3), 40 seeds.** Against the
  commit before it (a scratch worktree): `simulate_agendas` (every policy,
  10 days) is byte-identical apart from its wall-clock timing column --
  its runs end as the fair begins. `simulate_acts` (12 days, all three
  openings) moves only where an investigator walks across the Green during
  the fair and is dealt the fair deck (each card answered is one more turn,
  so one more patrol roll, and later draws shift): alibis presented 0.175 ->
  0.125 (a), 0.2 -> 0.15 (b), 0.15 -> 0.125 (c); houses cased 7.72 -> 7.70
  (a), 7.53 -> 7.50 (b); clue jobs 3.48 -> 3.42 (c); and in opening c one
  run's evidence reads "some" instead of "plenty" from its day-9 slot on
  (slots are filled when the loop next reads them, after a sentence served
  into the fair). The unmasking (by day and mean day), the namings, min hp
  (10-12) and deaths (0) do not move, and every acts bound in
  `tests/test_hue_and_cry.py` holds. No harness plays the fair's choices yet;
  Task 8 extends simulate_acts past the fair.
- **The jailbreak (v0.17 T4), 40 seeds, 10 days, agendas off.**
  `simulate_law --break-out` (a held thief tries the jailbreak until it walks
  out or is down to 3 hp, then pays or serves): the harness's cutpurse
  clears a try 0.36 (careful, taken quietly off the barge: 37 escapes in 103
  tries, 3 of 40 beaten down to the floor and paying) to 0.38 (reckless: 54
  in 144). With `--set deeds.escape=N`, the Wick's band on a quietly-taken
  thief's face as it walks out, and after: at 3 `noticed`, gone by the next
  morning; at 4 `sought`, `noticed` for three mornings; at 5 `sought`,
  `noticed` for four, and the careful thief below `sought` on 91% of its
  seed-days instead of 100%. A reckless thief is `hunted` already when the
  stop comes, so the escape moves no band at any severity, and 9-10 of its
  54 escapes are back in a cell within a day. 4 ships.

  **Re-measured with one try a day** (fix round 1; a failure closes it for
  the day, and the harness's thief then pays or serves rather than sit a
  day unserved): 13 of 40 careful thieves taken off the barge walk out (0.33
  of arrests; the other 27 pay the fine), and 16 of 43 reckless arrests
  (0.37; 17 serve, 10 pay, 3 back in a cell within a day). Every escape
  still walks out `sought` (careful) or `hunted` (reckless): the severity
  table above holds, only fewer escape. Before, it was 37 of 40. Without the flag
  nobody breaks out: `simulate_law` (every policy) and `simulate_acts`
  (every opening, 12 days) are byte-identical to the commit before, apart
  from wall-clock timing and the law harness's new count of clock advances
  per served day (3.0; the test holds it at 4 or fewer, in place of a
  wall-clock guard). The investigator in `simulate_acts` does not break out
  (it pays or serves, as before); Task 8 decides whether it should.

### Changed

- **A wrong naming spends the lead at the confrontation too** (v0.17 T7,
  carried from T6's review): the confrontation's second-try bar now mirrors
  the front desk's, `any: [none: [magpie_named_wrongly,
  magpie_confronted_wrongly], clue_fresh]`. Before, only a wrong
  confrontation spent it, so a thief who named the wrong suspect at the desk
  could confront the next one at once with no fresh clue.
- **The Dapper's City's `nobody_stopped_him` reason no longer says "the
  Magpie"** next to Silas's name (v0.17 T7): it reads "you already have a
  partner of your own up on the roofs". No ending text now pairs the Magpie
  with a candidate in one sentence.
- **The Showing (F2) is not dealt while Partners' door is open** (v0.17 T6):
  a partner is offered the heart with the Magpie (F6) instead. Its heist
  now also costs the Temple of the Everflame 10.
- **The Magpie's mask lifts on a partnership too** (`agendas.yaml`
  `unmask_when: any: [magpie_unmasked, partners_with_the_magpie]`), and
  **Silas Crook's two moves wait on `silas_stopped`**: beaten at the fair,
  he stops robbing the Company's ward.
- **The fair deck's header**: F4 and F6 built, F5 released (Guildmaster's
  door is the Porters' Hall), and a door re-offered on its own ending may
  also be one whose won branch shuts that ending (F4).

- **The evening barge takes only a thief who has earned Honest After All**
  (v0.17 Task 5, above). Until now anyone could board it from the first
  evening; the barge's header, stage and epilogue say what changed.
- **The evening barge locks `honest_after_all` by name.**
  `data/quests/the_way_out/the_evening_barge.yaml`'s `on_complete` was an
  id-less `ending_lock`, which asks `endings.resolve()` -- harmless with one
  ending, and the gallows once `honest_after_all` is gated and The Rope is
  the fail-forward. Every authored `ending_lock` in this story now names a
  declared ending (`tests/test_hue_and_cry.py`), and the barge is the
  story's first row in `tests/test_finales.py`'s per-ending doors.

## [0.16.0] — 2026-09-27

Acts I and II, the fourth of the v1.0 stages: the opening, the initiation,
the small room, the Magpie's trail, and the front desk's alibi and
accusation.

### Added

- **Acts I and II, as arcs the narrator can see.** `hue_and_cry` (Act I, the
  default) and `honest_work` (Act II, opening on `guild_initiated`) declare
  `narrate: true` in `data/quests/arcs.yaml`, so while one is the active arc
  the GM prompt carries its name and blurb. `the_way_out` stays a door at
  order 0 and `the_magpies_hoard` a side arc, so neither takes the active arc
  from an act. Neither act has a quest yet, so pacing is unchanged. The
  initiation deck (below) sets `guild_initiated`.
- **The Honest Company takes you in: the initiation deck**
  (`data/scenes/initiation.yaml`, `paths.decks`). This is the story's first
  deck and Act I's second beat. It is dealt once, on the first turn the
  thief stands in the Snuffs free and unsworn while Mother Gannet holds court
  at the long table: 18:00 to 04:00, per her schedule (from noon she does the
  accounts, and before that she sleeps). Mother Gannet and the Company are
  sure you are the Magpie, and that is why they want you.
  - When an arrival meets it: every way off the barge reaches the Snuffs by
    10:00–11:00 on day one, so the Company receives them that evening. The
    exception is a fumbled run answered by surrender, which serves three
    days and meets it on the evening of day four.
  - Before the deck is dealt, Gannet's contract and the guild bunk say the
    Company receives newcomers after dark.
  - It is never dealt in the cells (the cells deal the interrogation, below):
    a thief who came quietly meets it after release. It is never dealt over a burglary or over an open encounter,
    such as a Lantern's stop on the way in. It waits for either to end and
    is dealt on the next turn (an engine guard, root CHANGELOG).
  - The cards: tea at the long table, then a proving in front of the back
    room, then the oath, then supper or the Magpie's ballad.
  - The gates: persuasion, sympathy, stealth, craft, nerve and lore.
  - Every card has an answer that asks no dice. A failed roll costs a crown
    or some stamina, never the oath.
  - The oath always lands. It sets `guild_initiated`, which opens Act II
    (`honest_work`).
  - The rolls decide only how warmly the Company takes you:
    - every roll won: `honest_company` +8 or +9
    - the roll-free answers: +4
    - every roll lost: +2
  - No card names or implies a Magpie candidate (asserted).
- **The small room: the interrogation deck**
  (`data/scenes/interrogation.yaml`), the story's second deck and the first
  shipped deck anywhere to be `repeatable`. Every arrest ends in it: it is
  scheduled by `when: {in_custody: true}` and dealt on the first turn of
  every stay in the cells, once a stay, and re-armed the first turn the thief
  is seen free (the v0.13 `repeatable` seam; no engine change). An arrest that
  closes a Lantern's stop deals it on that same turn, and so does coming
  quietly off the barge.
  - Who asks, by the hour and read off the schedule (asserted against it):
    Captain Ardane at 06:00-13:00 and 18:00-23:00, Sergeant Brask at the
    front desk at 16:00-18:00, and otherwise the Lantern who brought you in,
    at the duty desk. Exactly one interrogator at any hour.
  - The cards: the book and the file (whose front says what the Watch
    believes -- `linked` self/magpie -- so it says MAGPIE until something
    breaks the link), then the interrogator's questions: nerve and
    persuasion against the file.
  - Outcomes: every petty sheet (severity 1) against your face or a face
    linked to it quashed (`quash_reports ... linked, max_severity: 1`), or
    only the Wick's; the file kept; or a caught lie written into the
    Magpie's file as one more lift (`report ... guise: magpie`, up the Rise
    or in the Wick). A burglary or a struck Lantern is never quashed.
  - **The sentence stands** (controller's ruling). The fine and the days are
    fixed by `arrest` at the door, and no card effect writes custody, so the
    room changes the file -- what is still filed when you walk out, and so
    how soon a Lantern knows you again -- and never the fine or the days.
  - Nobody is stuck: while a card is open `pay_fine` and `serve` are hidden,
    every menu card has a roll-free answer, the sequence card asks no dice,
    and the hand always ends; both ways out come back (asserted for every
    answer, every roll won and lost).
  - The two slots Task 5 reserved: `Q4_the_alibi` is filled (the alibi,
    below); `Q3_the_evidence` is released unfilled -- the accusation lives
    at the Lantern House desk, and a released thief is standing there.
  - No card names or implies a Magpie candidate (asserted).
  - **Unmeasured by the harnesses.** `simulate_law`, `simulate_agendas`
    and `simulate_labour` answer arrests through `execute_intent` and never
    deal this deck, so they cannot see what the room does to the file (how
    much the quashes and the added lifts move the wanted bands after
    release). Their numbers are unchanged with the deck in place (40 seeds,
    checked) only because they never reach it. `scripts/simulate_acts.py`
    deals it on every arrest (Task 8, below). The cards move no crown and no
    hour, so a stay's cost in coin and time is what it was.
- **Off the barge: the opening's three choices are real** (`game.yaml`
  `entry.opening`, through the engine's new authored-choice keys).
  - **Run**: a stealth check (standard), and `resisting_watch` committed pass
    or fail -- Brask and Tully are on the quay at eight, so a Lantern files it
    on the Quay about four runs in five. Get away and the Quay has you
    `noticed` until the next morning; fumble it and the Lantern's stop
    (`watch_stop`) begins there and then, with its five ways out.
  - **Talk**: persuasion (hard). Talk him down and nothing is written; fail
    and he writes the Magpie into his book anyway -- a `pickpocket` report
    against `magpie` on the Quay at 0.3 -- and the sergeant waves you on.
  - **Come quietly**: no longer a walk to the Lantern House but an arrest on
    the quay, on that same blurred charge: three crowns or a day in the cells,
    then out as from any arrest. It learns the cell drain, as every arrest does.
  - Every way leaves the player free to walk to the Snuffs within four
    actions (after an arrest, once the interrogation's two cards are
    answered). The Honest Company receives them there after dark (the
    initiation deck, above). No line of it names a Magpie candidate.
- **The reveal and the alibi: the Lantern House front desk**
  (`data/scenes/lantern_house_desk.yaml`), the story's third deck and its
  second `repeatable` one. It is dealt when the thief walks into the Lantern
  House FREE and a card there has something to offer, and again on a later
  visit (the director re-arms it once its `when:` is seen false: walk out,
  walk back in). A thief released from the cells is already standing there.
  - **The alibi** (`D1_the_alibi`). When the Magpie robbed a house while
    you sat in a cell, the Watch's own duty book proves it. Presented (no
    roll), it `law_discharge {alibi: true}`s exactly those robberies and sets
    `alibi_proven`, with a ledger fact. **Ruling: the alibi alone does not
    unlink you from the Magpie.** It proves you were not the Magpie on THOSE
    nights; breaking the Watch's belief is the accusation's job, so the file
    still says Magpie. **One card per belief** (Task 8): an alibi can still
    be open after a right naming, so each door ships the book twice --
    `D1_the_alibi`/`Q4_the_alibi` while the file says Magpie, and
    `D1_the_alibi_struck`/`Q4_the_alibi_struck`, whose words say the Watch
    no longer takes you for the Magpie, once it does not. Same discharge. **Once per alibi earned:** the card is gated on the
    engine's new `alibi {open: true}` (a robbery whose deed is still on the
    books), so a presented alibi is not offered again, and a robbery in a
    later stay earns, and offers, another. "Say nothing" keeps it for the
    next visit. The interrogation's new `Q4_the_alibi` is the same card
    for a thief arrested again before presenting it, and its effects are
    the desk's, word for word (asserted equal). The book's spine gained a
    third beat, `the_red_ink`: on every later arrest the file shows the
    nights the duty book cleared, in red.
  - **The accusation** (`D2_name_wren`, `D2_name_silas`,
    `D2_name_imelda`). Put the trail on Captain Ardane's desk and name the
    Magpie. Offered only when all of these hold:
    - the captain is in and awake (06:00–13:00, 18:00–23:00);
    - Evidence is at 2 or more ("some") -- measured by Task 8 (below); the
      first cut was a provisional 3 ("strong");
    - the found clues favour a suspect (`clues_favour`, at least one clue,
      and more than for anyone else). The card offered is that suspect's,
      by public name. At most one suspect is favoured at a time, so the
      player names the one their own trail points to. The gate on
      `clues_favour` is also the herring guard: the meter alone would open
      on red herrings.
    - Whether the name is right is decided by the seed (`agenda_role`), and
      the narrator learns it only from the outcome.
  - **Named rightly**, the spine happens: `magpie_unmasked`, then
    `law_unlink {a: self, b: magpie}`. The Magpie's reports stay on the
    Magpie's file and stop counting against you at once, and from the next
    prompt the GM line says who the Magpie is. Two ledger facts: who the
    Magpie is, and that the captain believed you.
  - **Named wrongly**, it costs: `magpie_named_wrongly`,
    `wrongly_accused_<suspect>`, and a `false_witness` report against your
    own face in the Wick at 1.0. On a clean face that is `noticed` for about
    two days and never `sought` -- but no accuser's face is clean: the Watch
    still links it to the Magpie, so the false witness stacks on everything
    the Magpie has done in the Wick in your name, and typically leaves the
    accuser a band worse, usually `sought` or worse, where a Lantern can
    know you on the way out (Task 8's table, below). The Watch's belief
    stands. Never a soft-lock: nothing here arrests, and the story's
    one ending reads none of these flags.
  - **A second try is allowed (owner's decision), but only for something
    new.** The suspect named wrongly is never offered again, and nobody else
    is until a clue has been carried out SINCE: the wrong naming clears
    `clue_fresh`, which every clue carried out sets again (clues.yaml's new
    `fresh_flag`). This is the gentler of the two rules offered. "A higher
    evidence band" was rejected because the meter tops out at 5 and could
    leave a thief nothing higher to show. With the wrongly named suspect set
    aside, the lead is counted among the others (`clues_favour
    {excluding}`), so a herring the thief was wrong about stops standing in
    front of the real Magpie.
  - Every card has a roll-free answer ("not yet", "say nothing"), and no
    answer arrests, moves or holds the thief (asserted for every answer,
    right and wrong).
  - **Flags for v0.17's endings:**
    - `magpie_unmasked`: named rightly; the Watch's belief is broken.
    - `magpie_named_wrongly`: named wrongly at least once.
    - `wrongly_accused_wren`, `wrongly_accused_silas`,
      `wrongly_accused_imelda`: whom. Count them for how many wrong
      namings: at most two, because the last suspect standing is the
      Magpie.
    - `alibi_proven`: an alibi presented, at the desk or in the cells.
    - `clue_fresh`: bookkeeping for the retry, not an ending's business.
  - Secrecy: before the reveal no card names the Magpie. A suspect's card
    names only that suspect, is dealt only when the player's own clues
    favour them, and says whether the naming was right only in the
    outcome. Nothing sexes the Magpie (the guard covers the new file).
  - The earlier harnesses never walk into the Lantern House free or accuse
    anybody: `simulate_jobs` (with and without agendas), `simulate_law
    --agendas` and `simulate_agendas` gave identical tables before and
    after this change (40 seeds, JSON compared, wall-clock columns aside).
    `scripts/simulate_acts.py` measures the reveal (Task 8, below).
- **`false_witness`, a deed at severity 3** (`data/rules/law.yaml`): naming
  the wrong Magpie to the captain. First set by `resisting_watch`'s
  arithmetic on a clean face (at 2 it would cool under `noticed` before the
  thief left the building; at 3 it is `noticed` in the Wick for about two
  days), then measured on the faces that actually accuse -- all linked to
  the Magpie -- by Task 8 and kept at 3 (below); charged, it is nine crowns
  or three days.
- **`resisting_watch`, a deed at severity 3** (`data/rules/law.yaml`),
  measured with `scripts/simulate_law.py --opening a`: noticed through the
  next morning, never sought on its own (table in the root CHANGELOG).
- **The Magpie's trail** (`data/premises/clues.yaml`, spec §3; the engine
  seam is `engine/world/clues.py`, root CHANGELOG). Every run hides eight
  clues in the 27 generated houses: four pointing at whoever the seed made
  the real Magpie and two red herrings at each of the other two suspects.
  Five rows are written per suspect, the same sentences whether that suspect
  is guilty or not: lamp-wick ends, lamp-soot, a pole's brass ferrule, a
  short ladder's feet, a snuffer's ring; a dozen Wickmarket pie papers, a
  Company tally-chit with its mark cut anew, flophouse back-stair mud, a
  Snuffs taproom token, a porters' rota written over in another hand;
  violet sealing-wax, a gilded temple taper, a silversmith's appraisal slip
  struck through twice, the silversmith's blue tissue, a torn place card
  from a Hill supper. A clue describes and never accuses: no name, alias or
  trade word, and no pronoun (asserted, and the sex guard now covers the
  file). **Nor is any clue a man's or a woman's thing**: a first draft's
  waistcoat thread, paste cufflink, cane dent, bay rum and pomade, and kid
  glove button were cut in review, because the Watch takes the player for
  the Magpie and a clue that sexes the Magpie sexes the player. Each clue
  points at its suspect through trade, place or habit; a wordlist test
  holds dress and grooming words out of the file. A clue's text fits the
  ledger's fact length, and the fact leads with it. The anchors hold none
  (Vessaline House is a suspect's own home).
  - Casing a clue house to the end says "something here doesn't belong",
    and stops saying it once the clue is carried out;
    the strongroom shows the clue cased or not; a job carried out keeps it
    (`clue_found:<id>`, a `clue` ledger fact) and raises **Evidence**.
  - **`evidence`**, a new veiled meter in `state.yaml`, 0..5: the prompt's
    Condition line and the sheet read it as a band word (one clue is
    "faint", four or more "utmost"), never a number.
  - Whom the found clues favour is `clues_favour`, a condition only: the
    narrator is never told where a clue points, and the GM line names nobody
    until `magpie_unmasked` (asserted in seeds that make each suspect the
    Magpie, with all eight found).
  - The interrogation header's `Q3_the_evidence` note now says the value
    is declared; its gate name is unchanged. It also warns that the meter
    rises for red herrings too, so `{value: evidence, min: N}` can open on
    herrings alone and should be paired with `clues_favour`; for the same
    reason the getaway line tells the narrator what the trail adds up to,
    never what you have on the real Magpie.
  - The accusation at the Lantern House desk (below) reads it.
  - **Measured (40 seeds).** `simulate_hoard.py` is byte-identical.
    `simulate_jobs.py`'s outcome rates are identical for every policy; only
    greedy moved, because it cases until watching tells it nothing more and
    a clue house now has one more thing to tell (one more two-hour watch,
    one more loitering roll): deeds filed a job 0.75 → 0.74, runs ending
    sought or worse 37.5% → 32.5%, wanted 2.5% → 5%; with `--agendas`,
    greedy's arrests a job 8.9% → 7.6% and sought or worse 80% → 82.5%.
    What the harness thieves find, reading only (no policy hunts clues):
    blind 0.65 clues a run (52.5% of runs find one; 27.5% lean toward the
    real Magpie), careful 0.6 (45%; 20%), greedy 0.2 (20%; 7.5%),
    greedy_bare none. Three jobs a run find little; Task 8 measures an
    investigator who hunts them (below).

### Changed

- **One clue reworded** (`violet_wax`): "the costly scented kind" of
  sealing-wax is now "the costly kind". Scent is grooming, and the clue
  wordlist test missed "scented" until v0.16 T7 made it match; the wordlist
  also gained pearl, locket, necklace and paste, and dropped "stays" and a
  bare "powder" (both ordinary words far more often). No placement moved:
  the trail samples ids, not text.
- `data/rules/agendas.yaml`'s header no longer says nothing sets
  `magpie_unmasked`: the accusation does.
- `game.yaml`'s header no longer calls the story a skeleton.
- **The acts say what is so** (`data/quests/arcs.yaml`; final review). Act
  I's blurb now arrives on the morning barge, the one the opening lands you
  from (it said evening). Act II's no longer says every Magpie robbery
  "lands on your name": it files them against your face "for as long as it
  takes the two of you for one", which stays true after a right naming.
- **Coming quietly shows its chip.** The opening's (c) carries no intent,
  so its button showed no consequence; it now reads `arrest · The Lantern
  House`, from its own authored `on_pass`.
- **The struck duty book** (`D1_the_alibi_struck`, `Q4_the_alibi_struck`)
  no longer says the nights stay marked against the Magpie's name: the
  alibi strikes those robberies off every file, the Magpie's as well.
- `data/rules/clocks.yaml`'s header no longer says the story ships no decks:
  no clock beat forces a scene, and both decks are scheduled by their own
  `when:`.
- **Two of the Company's offers now wait for its oath** (`guild_initiated`):
  - the guild bunk (`sleep_guild_bunk`, `data/rules/survival.yaml`). It still
    also needs a standing of 0 or better. Until the oath it is a rough night.
  - Mother Gannet's Silk Row contract (`gannet_silk_row`,
    `data/rules/threads.yaml`). Before the oath, a strike at the Snuffs is
    refused in her words, not with the generic "not here".
- **Rule 6 still holds.** The flophouse, a rough night, the short rest and
  the cell bench wait for nothing, in every district (asserted).
- **Ruling: the Porters' Hall bench stays open to everyone.** It is paid
  bench time, sworn or not. The v0.15 hoarder and the `craft` verb depend on
  it, and gating it would silently re-price v0.15's measured economy
  (asserted: no recipe reads `guild_initiated`).
- **Measured (rule 10, 40 seeds, before and after).**
  - These output byte-identical tables:
    - `simulate_jobs.py --policy all`
    - `simulate_hoard.py`
    - `simulate_labour.py --policy all` on the default flophouse bed
    - `simulate_agendas.py --policy all`, apart from its wall-clock
      "slowest day" column
  - No harness strikes Gannet's contract. The hoarder's squeeze on her
    (`gannet_ious`) is not gated, and the hoarder uses the bench, which
    stays open.
  - One harness relied on the gated bunk from its first night:
    `simulate_labour.py --bed bunk`. Harnesses drive intents, not
    `run_turn`, so nothing would ever deal them the deck. That policy now
    takes the oath as a harness step, the way a player does: the deck is
    dealt the first night it comes home to the Snuffs while Gannet holds
    court, and every card gets its roll-free answer. Every seed of every policy is
    sworn, on day 1 (porter, dipper, scrounger) or day 2 (careful and both
    credit policies, which come home after midnight).
    - Every bunk night is still under a roof (`bed_nights` 1.0).
    - The bounds moved slightly up, because some seeds get the oath's supper:
      - porter saves 1.02 cr a day (was 0.97); dipper 0.99 (0.93)
      - careful keeps 39% of days (33%), and 57.5% of its runs reach 0 hp
        (62.5%)
      - scrounger keeps 99% (98%); careful_pell 95% (94%); careful_marrow
        70% (69%)
    - `data/tables/labour.yaml`'s header restates the porter's bunk saving.
    - Re-measured after the deck moved to 18:00–04:00: the bunk and
      flophouse tables are identical, because every policy comes home after
      dusk.
  - Every labour policy now reports `initiation_due_day`: the first day a
    played turn would deal the deck. It is 1.0 for porter, dipper and
    scrounger, and 2.0 for careful and both credit policies. Task 8's
    investigator (`simulate_acts.py`) is dealt it and sworn on day 1 on
    every seed, or day 4 after a fumbled run's three days in the cells.

- **Acts I–II, measured (Task 8), and the evidence bar tuned 3 -> 2.**
  `scripts/simulate_acts.py`'s investigator plays the spine on purpose: off
  the barge, sworn to the Company, casing the city's houses for clues,
  burgling each clue house it learns of, and taking the trail to Captain
  Ardane's desk. 40 seeds x 12 days per barge choice (the full table is in
  the root CHANGELOG):

  | | run | talk | come quietly |
  |---|---|---|---|
  | opening passed / arrested | 50% / 8% | 28% / 0% | 100% / 100% |
  | sworn to the Company | day 1 (day 4 after a fumbled run's 3 days) | day 1 | day 1 |
  | clues carried out by day 6 / 10 / 12 | 1.2 / 2.3 / 2.5 | 1.4 / 2.3 / 2.5 | 1.4 / 2.3 / 2.5 |
  | first naming right / wrong | 62% / 12% | 62% / 12% | 65% / 12% |
  | unmasked by day 8 / 10 / 12 | 28% / 43% / 60% | 30% / 45% / 60% | 33% / 48% / 60% |
  | an alibi opened (and presented) | 18% | 20% | 15% |

  - **The bar is 2 ("some"), and the lead** (`data/scenes/lantern_house_desk.yaml`):
    since a tie favours nobody, 2 means two clues that agree (agree, not
    necessarily true: two herrings can open a wrong naming). T7's
    provisional 3 asked for no stronger case (its weakest lead is those two
    plus one pointing elsewhere), so by construction no more accurate a
    first naming, only a third house: 48% unmasked by day 12 against 60% at
    2, and wrong first no less often (19% pooled, 18-20% per opening,
    against 12%). 4 gives 21%; 1, 89%
    but 42% wrong -- a guess. The trail itself is slow (a clue is the last
    thing casing learns, so one costs ~3 houses cased) and is left as it is.
  - **`false_witness` stays at 3, and its claim is restated**
    (`data/rules/law.yaml`, the desk's header). "Never `sought` alone" held
    for a clean face only; every accuser is still linked to the Magpie, so
    the report stacks on the Magpie's Wick file. At every name offered, a
    wrong naming would have left 87% of accusers at `sought` or worse (42%
    before it) -- typically a band worse. None of the 15 real wrong-namers
    was arrested before day 12. 2 would leave a quarter feeling nothing; 4
    puts every one at `sought` or worse.
  - **The duty book comes in two** (`D1_the_alibi_struck`,
    `Q4_the_alibi_struck`): after a right naming the card no longer says the
    file still says Magpie.
  - Every earlier harness re-run at 40 seeds: identical, no bound moved.

## [0.15.1] — 2026-09-26

### Added

- **This CHANGELOG**, linked from the README.

### Changed

- **README audit.** The "skeleton" framing is gone (four engine features and
  three v1.0 stages have shipped on it since); the Margrave's household and
  the Silk Row houses are no longer listed as unmoved factions (a squeeze left
  uncollected moves them since 0.15.0); the balance section names all seven
  harnesses; and the "not yet" list matches CLAUDE.md's deferred list.

### Removed

- **The negative-prompt keyword list** (owner's decision): `style.negative`
  in `data/art/subjects.yaml`. The art prompts are positive-only.

## [0.15.0] — 2026-09-26

The guild economy, the third of the v1.0 stages.

### Added

- **The Porters' Hall bench.** The `craft` verb makes lockpicks, smoke
  pellets, a lamplighter's coat (a new guise) and a forged Margrave's Hill
  gate pass (a jobs tool on the Hill only) from makings sold by the two fences
  or found in the Snuffs' middens (`data/recipes/workshop.yaml`). A set of
  picks costs under half Marrow's price; nothing sells for more than its
  makings.
- **The Magpie's Hoard.** Six famous pieces the ballad says were never fenced:
  four in the anchors' strongrooms, two found by standing in secret places
  (`data/tables/collections.yaml`, `data/quests/the_magpies_hoard/`). Named,
  so hot for good; an arrest takes them all back. Carrying all six pays the
  Honest Company's good opinion once. An agenda's robbery never takes a piece.
- **Blackmail.** A house's secret carried out of a job is held, and each
  anchor's is a squeeze on its owner, struck at their door in their hours and
  collected there inside two days. Left uncollected, the squeezed party swears
  a `blackmail` report (severity 3) to the Watch, all but Mother Gannet, and
  their people turn on you.
- **The fences' credit.** Pell Hollis's advance (ten crowns, thirteen back in
  three days) and Marrow's slate (five, eight back in two), repaid in coin at
  her counter. Welsh on one and neither fence buys from you or lends again,
  and her collectors walk the streets for you until you pay.

### Changed

- **Brask names no price to a clean record.** His bribe is offered only while
  the Wick's drawer holds something against you.

### Fixed

- **A found place kept its cover name** in the awareness gate, and the lore
  paired a cover name with its place in one sentence. A test keeps every
  secret's cover and name out of the same lore chunk; rebuild the story's
  `lore.db` with `seed_lore.py --clear`.
- The fences' collectors' daytime rows spoke of the night.

### Notes

- Measured together at the end (`simulate_hoard.py` is new): no earlier bound
  moved. Welshing on a fence still nets a purses-only pickpocket a few kept
  days, and the owner let that stand. Hunger takes the careful pickpocket
  who never borrows to 0 hp on 95% of seeds in ten days; a welsher reaches
  it on 45% (Pell) to 82.5% (Marrow); with no `death.yaml`
  until v0.17.0 nothing follows. The tables are in the root CHANGELOG.

## [0.14.0] — 2026-09-26

The living city, the second of the v1.0 stages.

### Added

- **Somewhere to sleep, and something to eat.** A pallet at Old Nance's
  flophouse (1 cr), a free bunk over the Porters' Hall for anyone the Honest
  Company has no quarrel with, rooms at the Snuffed Wick and over the Tallow
  Barge (3 cr), the cell's plank bench, and a rough night anywhere, always
  (`data/rules/survival.yaml`). The story's first rest verb: before it, it had
  none, and walking was free. Bread and eel pie from Dock Mag, ship's biscuit
  at Hollis's; hunger runs at 2 an hour and every street costs stamina.
- **Scrounging and the secret ways.** Two hours in the gutters of five
  streets (`data/tables/forage.yaml`), and every secret place can now be
  found: a yard grating or the cells' drain to the Undercroft, a drainpipe or
  a loading crane to the Rooftop Road, the Rooftop Road or the churchyard wall
  to the Old Bell Tower. Turn one still offers none of them.
- **Honest work and luck.** Four employers, each open only in the hours it
  keeps (`data/tables/labour.yaml`), and the city's boons and complications
  on a natural 20 or 1. An honest day covers bread and a flophouse bed with a
  little over; thieving pays more.
- **The streets at night.** Every public street carries a danger rating, and
  five night scenes can meet you there (`data/encounters/streets.yaml`):
  cutpurses, a press-gang, a drunk Lantern, the lamplighter's warning and
  Silas Crook's toll-men. Each has a way out that needs no roll, coin, item
  or hour, and none takes more than 3 hp.
- **Factions and lore.** Seven factions (`data/world/factions.yaml`) and a
  42-chunk lore corpus in eight files (`data/lore/`). Three factions (the
  Temple, the Margrave's household, Silk Row) were declared for later acts
  and moved by nothing yet.

### Notes

- Measured together at the end with the new `simulate_scrounge.py`,
  `simulate_labour.py` and `simulate_streets.py`; no earlier bound moved.
  Hunger can take a thief to 0 hp on some seeds, and with no `death.yaml`
  until v0.17.0 nothing follows.
- A save from before 0.14 keeps its generated world, so it never gains the
  rooftop and grating paths; the arrest reveal of the Undercroft still
  reaches it.

## [0.13.0] — 2026-09-25

### Changed

- **The secret places stay secret.** On turn one travel offered "The
  Undercroft, 1h" by name; the three secret places are now off the map and
  out of travel until known (the `data/world/locations.yaml` header says
  how). Nothing in the story made them known until 0.14.0.
- `generate_art.py --game hue-and-cry` now plans the story's 91 plates
  (19 locations at four dayparts, 15 portraits). None is generated yet.

## [0.12.0] — 2026-09-25

Agendas: the city moves whether or not you do.

### Added

- **Three agendas on hidden clocks** (`data/rules/agendas.yaml`,
  `data/rules/clocks.yaml`, a new `state.yaml`). The Magpie, a thief chosen
  by the seed and never revealed or stored, robs a shining house most nights,
  and the watch takes the Magpie for you: a player who never steals a spoon
  is `noticed` in two days and `sought` in about five. Captain Ardane tightens
  her net and, pushed far enough, swears out a warrant. Silas Crook cleans out
  the Honest Company's own ward and pounces if you rob Mother Gannet.
- **The Magpie's mask.** No trace or effect names who the Magpie is, in any
  seed. `magpie_unmasked` lifts the mask, and nothing sets it yet.
- The anchor premises name their owners, and `prompts/storyteller.md` gains
  "THE CITY MOVES WITHOUT YOU".

### Notes

- Measured with the new `simulate_agendas.py` (40 seeds x 10 days). The law
  and jobs harnesses now measure with agendas off, so their bounds still mean
  what they did.

## [0.11.0] — 2026-09-24

Jobs and flashbacks.

### Added

- **Burglary** (`data/rules/jobs.yaml`). `burgle` opens a job on any unrobbed
  house and walks it stage by stage: the approach, a way in (door, window,
  roof or cellar), whoever is inside, the strongroom, the getaway. Every
  security row of all eight house types and four anchors does something to a
  named stage, casing earns prep, three flashbacks spend it, and an alarm
  brings the Watch. The Treasury has its own vault floor.
- **The burglar's kit:** lockpicks and smoke pellets, sold by Marrow.
- **Mother Gannet's first contract:** any house on Silk Row inside three days,
  fifteen crowns net of the Company's cut. The Honest Company becomes the
  story's first faction.
- The `burglary` deed, severity 3.

### Notes

- Measured with the new `simulate_jobs.py` (four burglars, 40 seeds). Every
  number in `jobs.yaml` was set against it; the table is in its header and the
  root CHANGELOG.

## [0.10.0] — 2026-09-24

The Law.

### Added

- **The Lantern Watch** (`data/rules/law.yaml`): three watch-houses, wanted
  bands per guise per district, the guises `self`, `magpie` and `porter`, and
  a Watch that believes from the first morning that you are the Magpie.
- **The Lantern's stop** (`data/encounters/watch_stop.yaml`): run, talk,
  bribe, surrender or fight, opened only by a Lantern who knows your face.
- **Sergeant Brask's bribe** (`data/rules/threads.yaml`): twelve crowns in the
  biscuit tin, and the Wick's reports go missing.
- Dock Mag, the first honest vendor (a porter's smock), and Marrow's Magpie
  mask.

### Notes

- Measured with the new `simulate_law.py` (careful, reckless and briber
  thieves, 40 seeds x 10 days). Tuning moved cooling, the wanted thresholds,
  recognition and the arrest's price; the tables are in the root CHANGELOG.

## [0.9.0] — 2026-09-23

The story's first release.

### Added

- **The skeleton.** Tallowmere's eleven districts (three secret), fourteen
  scheduled people covering all 24 hours, two pipeline agents (the city and
  Pip the jackdaw), three archetypes, an opening whose three choices each
  carry an intent, and one ending reachable end to end, `honest_after_all`,
  with its epilogue. Art prompts for every district and person; no plates.
- **Premises, pockets and fences.** Eight premise types and four anchors
  (Vessaline House, the Margrave's Treasury, Mother Gannet's House, the
  Captain's Office), each with a household that keeps real hours, security by
  tier, loot and a secret; purses by role; loot valued in crowns; and the two
  fences, Pell Hollis and Marrow.

### Fixed

- `crit_success` was unreachable (the graph template's margin of 10); it is
  6, the flagship's number.
