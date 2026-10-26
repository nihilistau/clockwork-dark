# READ RECEIPTS

A new city, a new phone, two dating apps. You have just moved to Port Merrow,
a harbour city of the present day. Your phone is one half of the story: two
dating apps (Matchstick and Front Porch), texts, an instant messenger
(Natter), two games, photos, a calendar and contacts. The other half, since
v0.23.0, is your life away from it: put the phone down and the flat, the
building and the city are narrated -- cook, eat, tidy, read, sleep, go to
work, step outside, go out to a cafe, a bar or a walk (`do` and `go`; "Head
home" from anywhere). A long activity stops when the phone buzzes, and the
narrator is told how many times and by whom, never what was said; pick the
phone up and the world waits (a world choice is answered "Put the phone down
first."). There is no plot and no
ending (`endless: true`): the people in the apps are populated from data and
the engine runs them, and the model writes what they say.

**What you can do (v0.22.0).** Make yourself a profile, then swipe on
Matchstick or like a photo or a prompt on Front Porch (or see who liked you
first), and wait for matches: they arrive over time, and a match nobody
writes in expires. Messaging runs on the engine's clock: you write, and the
person reads and answers on their own schedule (asleep, at work, out),
writes first after a match, texts again when you go quiet, starts
conversations of their own, can ghost you, and can give you their number,
which opens Texts and Natter. Each relationship is the engine's: it moves
from just matched to talking to swapped numbers and on to seeing each other,
dating, friends, something casual or together, by what each person is willing
to do now -- how far they have opened up to you, warmth, trust and time
together, never the calendar -- shown to you only as words ("Talking", "Cooling off") and a
closeness band; it can cool off and warm up again, fade after three weeks
without contact, take a turn, or be ended by you, and it can start again.
Together is not the end of it: two people together can move in (they move
into your flat, and come home to it on their free evenings, where you can
spend the evening with them), get engaged -- asked on the phone, by them, or
in person over a drink -- and, two weeks on, marry at the registry office in
a small scene that cannot go badly. None of it is an ending: a married
couple can still cool off, warm up again, or end it, and when it ends, fades,
or you unmatch or block them, they move out. If you are seen out
with someone else while you are with someone, they find out, and it costs
their trust.
You can answer when they offer their number or ask to be exclusive, and ask
them yourself -- though not three times in one conversation. Once someone
starts telling you about their days they may well offer you their number
themselves. "Their number" stays greyed on the Ask menu until they would
consider it (they have opened up past small talk and like you enough; no set
number of days), and a no that means "not yet" says so. Ask for a photo, a voice
note or a video (they decide, by how close you are, and may say "later"),
or send your own. Make a plan -- coffee, a drink, a walk, now, tonight or
soon, with no set time -- or let them ask you; go to it in time, or stand them
up. The person you arranged to meet turns up: they make their own way there
(and may be a few minutes late), text you that they are there if you are not,
and if you are already there you can wait for them. Play Tile Talk, a word game on an
11x11 board, or This or That, five quick either/or pairs, with anyone you
are talking to -- you invite them with a game invite, or they ask you.

Their words are written in the background while you keep using the phone:
each reply from `prompts/texter.md` -- quick texts while a conversation is
getting going, fuller messages that pick up what was said earlier once it is
-- checked against what the engine holds
(and checked again just before it lands, in case something changed
meanwhile), with the story's own fallback lines when no model answers; you
see typing dots while one is being written. With no model server at all the
game still plays: the fallback lines move a relationship on slowly
(`relationships.yaml` `regard.fallback`). An answer not yet written when
its writer unmatches, is blocked or is ended is withdrawn, never shown.

The phone saves itself: at once when you match, a relationship moves or you
end one, and otherwise within ten seconds of your last tap; a long
conversation's older messages are kept beside the save and paged back in
when you scroll up. A run saved by v0.22.0 still loads: it is upgraded as it
loads (each relationship at the depth its stage had reached, an agreed
meet-up a "soon" plan, a message left unanswered answered; docs/STATE.md has
the whole table). A new run starts at seven in the evening, and the city
does not wait for you: while you are away the time passes there too (real
time, hour for hour, at most three days), people write, matches arrive and
expire, and when you come back the
phone opens on its lock screen with what you missed ("While you were away:
5 messages from 3 people, 1 new match, 1 match expired"); the replies that
fell due are written as soon as you are back. Inside a session the clock
moves only when you do something. There is no plot and no ending.

### The apps

| App | What it is |
|---|---|
| Matchstick | A swipe deck: one card at a time, like, pass or super like; 60 likes a day; matches expire after 7 days; text only |
| Front Porch | A browse deck: whole profiles, photos and prompts; like one thing, with a comment; "Likes you"; 8 likes a day; matches expire after 14 days; text and voice notes |
| Texts | Opens with a person once you have swapped numbers; text and photos; no read receipts and no typing dots, like SMS |
| Natter | The instant messenger, also from swapped numbers: text, photos, voice notes and videos, typing dots and read receipts (yours can be turned off) |
| Games | Tile Talk and This or That, once you are talking |
| Photos | Your camera roll and what people sent you |
| Calendar | "Coming up": the plans and promises open between you and someone, in words (no grid, no dates) |
| Contacts | Everyone you talk to, and each one's contact card |
| Settings | Your bio on each dating app, your discovery (fixed for the run), Natter's read receipts and "Wake me for messages" |
| Places | Every place you can go from where you are; choosing one puts the phone down and goes |

**On screen** (the story's own play screen, `ui/src/stories/read-receipts/`).
Begin opens a setup wizard over the creation form, in four steps: you,
looks, interests, what you want (the name you give is your name in the
apps and in the save). The phone then opens on its lock screen: the time,
your notifications newest first (a new match is one: "New match"), and
"Put it down", which lets time pass until the next thing happens. Open the phone for home -- every app with its
unread badge, and the dock (Texts, Natter, Matchstick, Front Porch) -- and
the side button (top right) locks it again. Matchstick deals one profile at
a time: drag it or press like, pass or super like (the arrow keys: right,
left, up). Front Porch shows a whole profile, photos and prompts, and you
like one of them, with a comment if you want; "Likes you" lists who liked
you first. Each app keeps its matches and chats, and a conversation opens
with its messages, typing dots and Delivered/Read. A message that could not
be sent keeps its words with "Not sent — tap to retry". On a wide screen
the phone is drawn with its bezel; on a phone it fills the screen.

Contacts lists everyone you talk to; a contact card (or the "i" in a
conversation) shows their profile, where things stand in words, "Your
story" and what they have told you, and from it you plan a meet-up, start a
game, or unmatch, end things or block (each asks first). When they can't
make the time you ask for they say so in the chat. "Ask to meet" (here and
in the chat's Ask menu) offers "Free now?", "Tonight?" and "Sometime soon", with
a kind and a place if you want one. The card also says when you are "Getting
closer", what they have told you of their days, whether you could ask for their
number (and in words why not), and the promises and plans open between you.
On a screen 1200px
wide or more the card opens beside the phone. Games holds your Tile Talk
and This or That games: place tiles by tapping a tile and a square (or
dragging), then Play; answer This or That's five pairs one at a time and
wait for the reveal. Photos keeps your camera roll and what people sent
you; Calendar what is coming up. Settings edits your bio on
each dating app, shows your discovery (fixed for the run) and switches
Natter's read receipts and "Wake me for messages" (off by default: asleep, only
a promised message, or one from a person who is up late, wakes you). v0.22.0's
"Let time pass" is gone: a reply in a conversation needs no time to pass.
**Talk later** (the chat's bar) ends a conversation with a promise, either way:
"Message me in the morning" or "I'll message you tonight". A job offered
elsewhere reads "Ask them to stay" / "Let them go" / "Later" -- letting them go
means they take it and you part ways.

**Conversations** (v0.23.0). While you are talking, their replies come at
once, at the minute you sent yours; a conversation ends where it naturally
would -- their shift starts, lunch is over, they are flagging, or it has
simply run its course -- and they say why. Someone asleep, or at work and
not one to text there, reads you when they are next free; a night owl
answers at 3am. Time moves only when you choose: "Wait" until someone
writes, an hour, the evening or the morning.

```powershell
.\.venv\Scripts\python.exe launcher.py --game read-receipts
```

```sh
.venv/bin/python launcher.py --game read-receipts   # Linux
```

What changed, release by release: [CHANGELOG.md](CHANGELOG.md). The design is
[docs/superpowers/specs/2026-10-08-v0.22.0-dating-sim-design.md](../../docs/superpowers/specs/2026-10-08-v0.22.0-dating-sim-design.md).

## The files

- `game.yaml` -- the manifest. It declares `paths.locations`, `paths.prompts`,
  `paths.social` and (empty until the life-event decks) `paths.decks`, and the
  world turn's directives (`StorytellerMind`, `SocialWorld`); its header
  comment lists what it deliberately does not declare, and why.
- `data/world/locations.yaml` -- 28 locations (v0.23.0): the seven rooms of
  your flat and building, joined by one-minute edges, then the street, the 15
  meet-up venues (rows of `data/social/venues.yaml`, which add `travel_minutes`),
  the cast's four homes (`data/social/homes.yaml`) and the registry office,
  which have no edges and are reached by `go`.
- `data/world/activities.yaml` -- what you can `do` in the world (v0.23.0):
  where each is offered, how long it takes (minutes, or until the morning, the
  evening or the end of your work band), whether a buzz stops it, and its one
  line for the narrator; the phrases a typed line may name it by (`say:`), and
  the `typed:` block the engine reads typed lines with (its cue lists, and the
  nouns for the flat's rooms and the building). Typed "make breakfast" in the
  kitchen, or "go to the hall", runs that one choice; a wish, a question, a
  "later" or two things at once is only narrated. Checked when the story loads.
- `data/world/npc_schedules.yaml` -- seven background people (v0.23.0): a
  barista at each coffee house, bar staff at The Anchor and The Lantern Wine
  Bar, the building's concierge and two neighbours, each with shift hours and
  no home. On shift they are in the room and the narrator names them; off
  shift they are off the map. They are not on the phone and not datable; the
  cast is never listed here.
- `prompts/storyteller.md` -- the narrator of your life away from the screen:
  80-200 words a turn, how to offer choices, how to render a typed line's
  result as the other person's reaction, who is around; never a phone message,
  everything on the phone a fact, commitments only as the engine states them.
- `data/social/*.yaml` -- the social engine's data, found by fixed name
  (`creation`, `population`, `behaviours`, `apps`, `relationships`, `media`,
  `venues`, `games`). Every number in them is a balance constant, measured
  and tuned by `scripts/simulate_social.py` (Balance, below; its v0.23.0
  harness prices play in real minutes). The v0.23.0
  rework adds nine more (`conversation`, `promises`, `growth`, `topics`,
  `layers`, `plans`, `scenes`, `life_events`, `homes`). `growth`, `topics`
  and `layers` are filled (below), `conversation` (T3), `promises` (T4),
  `plans` (T12), `scenes` (T13) and `homes` (T10); `life_events` is filled
  (v0.23.0 T17, below).
- `data/social/growth.yaml`, `topics.yaml`, `layers.yaml` -- how each person
  opens up to you (v0.23.0). Five disclosure rungs, fixed by the engine:
  small talk, everyday life, personal stories, hopes and fears, family and
  the future. Each person climbs at their own pace (their archetype's
  `growth.pace` in `behaviours.yaml`, their traits, a small jitter), held
  by each rung's warmth and trust floors and play counts, and by their
  archetype's cap (a breadcrumber never gets past everyday). They talk about
  one drawn topic of each kind (`topics.yaml`, 54 rows) and, at each step
  up, reveal one fact of that rung (`layers.yaml`, 58 rows). Only the
  disclosure kinds the engine names may appear; anything else fails to
  load. Exchanges, good endings, kept promises, moments in a scene and support
  (a reply of yours while a hard event of theirs runs) fill the openness meter.
- `data/social/life_events.yaml` -- what happens to people, and to you
  (v0.23.0). Twelve events of the player's (a boiler that goes, a parcel at
  reception, overtime, a cold, a friend's birthday, family visiting, a wedding
  invitation, a broken lift, a neighbour's party, payday, a rough week, a
  promotion) and fifteen of each person's (a new job, a holiday, a job offer
  elsewhere, a house move, a pet, illness in the family, a sibling's wedding, a
  birthday, an ex getting in touch, a race, a friend's breakup, a bad month, a
  promotion, losing a job, and the date of your own wedding, set two weeks
  after you get engaged). Their odds and cooldowns are in days. `seen:` is what
  being seen out with someone else costs a partner (one chance a scene). What happens
  to someone shows in "Since you met", in what they tell you next, in their
  mood and, for a hard one, in whether you were there for it; a holiday takes
  them out of reach for a week; a job offer elsewhere is a question you answer
  ("ask them to stay", "tell them to go") and their warmth and trust decide.
  What happens to you reaches them only if you say so. The boiler and the
  parcel also deal a small scene (`data/scenes/boiler.yaml`, `parcel.yaml`) in
  the kitchen and at reception. Life events are ordinary life and mean nothing
  more than the fact they state.
  The neighbour's party, the broken lift, family visiting and the wedding invitation deal
  one too (v0.24.0), in the hall, the lift, the lounge and the hall. Staying the
  night is followed by a short morning scene (`scenes.yaml` `morning`): breakfast,
  getting ready and seeing them out, with its own moves and the closer "See them to
  the door"; it counts as the night's tail, not a second scene.
  The broken lift adds its five minutes only to a move through your building (not to
  every move, as v0.23.0 did), and the wedding invitation (five days) and your promotion
  (seven) now run a window: for that long you can tell people the news, and then it is
  old.
- `data/social/creation.yaml` -- the player's own profile: every field the
  creation form asks for, its choices or range and its default. Where a
  field picks from a list the people are drawn from (hobbies, hair, style,
  job, photos) it names that `population.yaml` table (`of_table`), so you
  choose from the same lists. Anything left out takes its default; a
  choice with none, and the hobbies and photos, are a pick seeded by the
  run's seed. `start_hour` (19) is the hour a new run starts at, on day 1.
- `data/social/population.yaml` -- the people. Nobody is stored: a person is
  drawn from these tables by the seed and their index alone, so a seed always
  holds the same people whoever you meet first. `filter.sex` says who the
  apps show you (`opposite`, as shipped; `same` and `any` work too), and
  changing it changes each person's sex and name and nothing else about them.
  Their bios and Front Porch answers are templates from these banks, never
  the model's.
- `data/social/apps.yaml` -- the apps. Matchstick holds people 0-1799,
  Front Porch 1800-2199, and 60 more (2200-2259) are on both; each app's `culture`
  weights who its people are (their archetype and what they are looking
  for). Each app says what a thread on it can carry (text, photos, voice
  notes, video), whether it shows read receipts, and what each action costs
  in minutes; Texts and Natter open with a person once you have their
  number.
- `data/social/behaviours.yaml` -- how each kind of person behaves: twelve
  archetypes, each a set of numbers (how likely they are to answer when a
  conversation starts, to write first, to ghost, to double-text, to flake on
  a date, to promise or to offer their number) and the messages they start
  on their own, each in a window of their own day, plus the arcs that change
  a relationship over time (a turn, a slow fade). Each person's week comes
  from their job's shape in `population.yaml`: asleep, at work, free or out.
  Its `canon:` table holds what an arc's turn reveals about a person, in
  prose, added to what they remember having told you.
- `data/social/conversation.yaml` (v0.23.0) -- how a conversation runs: what
  a message costs, when "this evening" and "the morning" are, each
  archetype's phone habits (texting at work, late at night), how long they
  like to talk and what winds them down, how full a reply runs as a chat
  gets going, the chances when a conversation starts (they answer, leave you
  on read, or ghost), the engine's reasons for signing off and how long
  each keeps them away.
- `data/social/promises.yaml` (v0.23.0) -- promises and sign-offs: "Talk
  later" in a conversation records a promise ("I'll message you tonight",
  "Message me in the morning?"), and they promise too when they sign off.
  Theirs are always kept, inside the window; yours are kept by a message in
  it and broken by silence an hour past it. The file sets how far ahead a
  promise may reach, the grace, what keeping and breaking cost, the phrases
  a typed promise is caught by with no model, and how each window reads.
- `data/social/relationships.yaml` -- where you stand with each person: the
  stages and the gates between them (`living_together` and `engaged` by
  what each is willing to do, `married` by the wedding; a stage moved by a
  scene carries no gate), the closeness bands, how far a reply
  or a conversation can move their warmth and trust, what keeps them
  interested, their moods, how often you may ask for something in one
  conversation, when a relationship
  cools or fades, and what a reply may propose (their number, being
  exclusive, moving in, getting engaged, a step back, a promise while the
  conversation winds down, or --
  held by `media.yaml` -- a photo, a voice note or a video); and the phrases a reply is checked against
  (claiming a stage not reached, a photo never sent, a refusal over an
  attached one, agreeing inside a decline, a plan never made or one
  made denied), with the negations that cancel a claim and the
  contacts' names that are also ordinary words. Its `meets:` block holds what is
  left of v0.22.0's meet-ups beside scenes: their text afterwards
  (`post_meet`) and the words for how an evening went (`recap_lines`).
- `data/social/venues.yaml` -- where meet-ups happen: each venue's name,
  neighbourhood, kind, the hobbies it suits and how long a meet-up there
  lasts, and the kinds' words ("Coffee" "at").

  **Meet-ups.** v0.22.0's appointments (a venue, a day and a slot, a
  Calendar row, a no-show) are gone; see `plans.yaml`, and the evening itself
  is a scene (`scenes.yaml`, below).
- `data/social/plans.yaml` -- plans with no set time (v0.23.0). From swapped
  numbers on you ask to meet with a kind, a venue and a time of day in words
  (`now`, `tonight`, `soon`), or let the engine fill what you leave out, or
  they may ask you (their `ask_meet`, or their own evening invitation).
  They answer at their read: yes when they would meet you (`growth.yaml`'s
  `willing.meet`) and have the time -- two free hours for `now`, their evening
  for `tonight`, willingness alone for `soon`. A yes is a plan. The person heads
  there: the venue's travel minutes (their home's for your place; none for
  theirs) and up to `arrival.late_minutes` late, so a `tonight` plan is kept
  in the evening, never the afternoon. Be there when they arrive -- go to it,
  or wait for them where you already are ("Wait for Kai") -- inside its
  patience, counted from their arrival (1.5 hours for `now`, 4 for
  `tonight`), and you meet; later, or never, and you have stood them up (warmth -8, trust -6,
  interest -6, and a message about it). "Running late" in a text buys half an
  hour, once. They may cancel after saying yes (their archetype's own chance
  plus 3-10% by stage) and tell you why. A `soon` plan lapses quietly after
  six of their conversations, never days. Plans with someone who unmatches
  you, or whom you block or end things with, are called off at no cost.
  Arriving opens the evening (`scenes.yaml`).
- `data/social/scenes.yaml` -- meet-ups played in person (v0.23.0 T13). The
  evening is the narrated turn: each choice is a conversational move -- ask
  about one of their topics, tell them about one of yours, be playful, let a
  silence sit, or just talk (or type what you say: a line naming one of
  their topics or yours becomes that move, anything else is "Talk") -- and
  the engine decides how it goes (it
  lands, goes fine, falls flat or is a misstep) from the prior (how well it
  started: their chemistry, their warmth, their mood, a draw), the move's fit
  with their traits and archetype, the topic and their mood, with one draw;
  each band moves warmth and trust exactly and opens them up. Asking about
  something deeper than they share yet is answered by them steering
  elsewhere: a flat moment, never a refusal. No move has a floor or a gate.
  The evening ends by a closer -- call it a night (with a promise to text in
  the morning, a plan to do it again, or staying where you are), another
  round, going on somewhere else, walking them home, or back to yours or
  theirs once they would -- or by them, spent, after two missteps, or when
  their day calls. It bands great, good, fine, awkward or bad: a good one
  counts toward dating, friends or something casual, fine or better swaps
  numbers if you hadn't, and their text follows unless it went badly or they
  are a ghoster. At the flat you can cook, eat or watch something together.
  Once they would say yes, "Ask them to marry you" is a closer too, and the
  evening goes on. With someone who lives with you, home and free, "Spend
  time with them" opens an evening at home with no plan; the wedding is a
  scene of its own at the registry office (`wedding`: three moments, only
  quiet, telling them something or being playful, and it cannot go badly).
  What two people do on an evening is the narration's, never the engine's.
  The narrator is told who they are now, where you are, your story together
  and this moment (v0.23.0 T15), and what it writes is held to the same facts
  as their texts: their age, job and neighbourhood, who they can know, where
  the two of you stand, and the promises, plans and steps only a closer
  makes. Prose that gets one wrong is rewritten once; a second miss, or no
  model at all, shows the engine's own lines for the moment.
  **Running into someone** (`chance:`, v0.23.0): at a cafe or a bar, someone
  you already know may be there by their own schedule -- out for the
  evening, or free in the day, at a place that fits their hobbies. They are
  "Also here" on the world's picture (by name, with whoever works there),
  their texts wait while they are across the room, and "Go over to Sam"
  starts a chance evening. It goes like any other, but swaps numbers or makes
  you "seeing each other" only if they would anyway (`growth.yaml`'s
  `willing`), and asking them back or on somewhere else waits until they
  would meet you. A run-in sends no "after the date" text, and once you
  have talked they are not offered again until later in the day. Ignoring
  them costs nothing. Never strangers, never on the
  street, at home or in the flat.
- `data/social/media.yaml` -- photos, voice notes and videos, which are
  rare and earned. Each person holds a small budget of each (refilled a
  little after every conversation with them, to a cap) that opens at a stage (photos and voice
  notes once you are talking, videos once you have swapped numbers). When
  you ask, they decide at their next read -- by their trust, warmth, mood,
  kind of person and how often you have asked in this conversation -- and
  may say yes, no or "later" (kept or broken the next morning); now and then,
  as a conversation ends, they send one unasked. What a photo of theirs shows (`subjects`) depends on what they
  are doing (their schedule status) and on fixed facts about them (a pet
  needs the `has_pet` flag, never a mention in conversation). `player_subjects`
  are what you can send besides your profile photos; `portrait.scene` is a
  person's profile picture; `style` is added to every image prompt.
- `data/social/games.yaml` -- the games. `wordgame:` is Tile Talk: the
  board's premium squares (one string per row), the bag (each letter's count
  and value, plus two blanks: 72 tiles), the bonus for playing all seven
  tiles, how hard the other player looks for a move (`node_budget`, a count
  of words tried, never a time) and how often they take their best one
  (`top_k_by_skill`, by their archetype's `games.skill` in
  `behaviours.yaml`), how many passes and swaps in a row end a game, how
  full the bag must be to swap (`swap_bag_min`), how
  fast they move (`pace_mult`, times their reply speed), how often a move
  of theirs comes with a message about it, and what a finished game does
  to the relationship (`effects`; a key `<archetype>_crushing_warmth`
  is what losing by more than `crushing_margin` points costs a person of
  that archetype).
  `this_or_that:` is This or That: `tags` (each a set of hobbies and
  traits from `population.yaml`, and personality sliders with a sign: +1
  pulls toward, -1 away), the bank of `pairs` (60 or more, each `{a: {label,
  tags}, b: {label, tags}}`; a label should read well in "You both pick
  <a> over <b>", the line written when you agree), how strongly a person's
  profile leans their picks (`lean`: the weight of a held hobby, a held
  trait and a slider, the `sharpness` of the lean and the `noise` that
  keeps anyone from being predictable), their pace (`pace_mult`) and what a
  finished game and each agreement do (`effects`). Five pairs are dealt
  per game. Which game a person asks you for is the one you two have
  played least (ties: the Games app's `offers` order in `apps.yaml`); how
  often they ask is their archetype's `games.invite_prob_per_day` in
  `behaviours.yaml`.
- `data/social/words.txt` -- Tile Talk's word list, one lower-case word a
  line (see "The word list" below).
- `prompts/texter.md` -- the voice of every person who texts you: a persona
  section (the only part sent to the model, as its system message: text the
  way this person texts, quick when it is just getting going, a real
  conversation when it is going), the `## Instructions` table of situation
  lines (one `- \`<id>\`: <line>` row each; every situation the engine or
  `behaviours.yaml` names needs one, and `winding`, `sign_off`, `followup`
  and `opens_up` too; a row may name `{reason}`, `{promise_when}` and the
  other engine facts), and the `## Fallbacks` used when no model answers
  (one `yaml` block: `reasons:` in the person's own words, `any:` by
  situation and mode -- `reply.quick`, `sign_off.chatting` -- for everyone,
  then each archetype's own lines; `decline` is tried first for any answer
  that is no). Each reply runs quick, chatting or deep, so a conversation
  that is going gets fuller messages (up to four bubbles of 500 characters,
  or three of 700), and the voice is given who they are now, your story
  together, what is still open between you and how your last conversation
  ended.
- `prompts/episode_recap.md` -- what a person remembers of you, whatever
  app you talked on (v0.23.0): above `## The story so far`, the recap of one
  conversation once it ends (one to three sentences, at most 70 words: the
  engine's `social.memory.recap_words`); below it, how the oldest recap is
  folded into the story so far (at most 300 words: `social.memory.story_words`;
  keep the numbers equal). Each person keeps their open conversation word for
  word, how the last one ended, twelve recaps and that story, and nobody
  else's. With no model, a recap is the engine's own line from what it knows
  (the topics you named, why it ended, a promise made: `conversation.yaml`
  `reasons_recap:`).
- v0.22.0's `prompts/date_recap.md` (the meet-up recap card) is gone since
  v0.23.0 T19: an evening is recapped like any conversation (T13), by
  `episode_recap.md`.

## The word list

`data/social/words.txt` is **ENABLE** (the Enhanced North American Benchmark
LExicon, Alan Beale and Mendel Cooper), which its authors placed in the
**public domain**: its README says the list "is placed in the Public Domain
for anyone to use as they see fit" (Debian's copy of that README:
https://sources.debian.org/src/scowl/6-2/r/enable/README).

- Downloaded 2026-10-12 from https://norvig.com/ngrams/enable1.txt (the
  ENABLE list as distributed with Peter Norvig's "Natural Language Corpus
  Data" chapter): 1,743,327 bytes, 172,820 words (no newline after the
  last), SHA-256
  `61ba1392a5b6199dd161fae7b483cd262fb8a88c0d49bd2c9ecb6753e755697f`.
- Shipped as downloaded, normalised: lower case a-z, one word a line,
  sorted, LF endings with a final newline (`.gitattributes` keeps it LF):
  1,743,328 bytes, 172,820 lines, SHA-256
  `f32e6fbdc4cf9c8ec1d992193d7ac33e773fc850ba47ebe2c791ab9d61913d49`.

The engine holds it in memory as two sets, the words and every prefix of
them (387,880): about 47 MiB per process, loaded once in about 1.5 s. In
hosted mode it is loaded when the server starts; playing locally, the first
Tile Talk move of a run (yours or theirs) loads it, so that one move takes
about a second and a half longer. (It is not loaded in the background when a
game starts: a load still running when the story changes could leave one
story's word list behind for the next.)

## Sounds

The phone is heard (v0.24.0, `data/sounds/sounds.yaml`; the sounds are the browser's, nothing goes to the server):
a message pops in the thread you have open, chimes in another, buzzes while the phone is down and rings for a voice
note or a video message wherever the phone is. One message makes one sound, and what is already on the phone when you
resume or rejoin makes none. There is a tick when they start typing, a whoosh when you send, a click to unlock and to
lock, cloth for picking the phone up and putting it down, a whoosh for a swipe, an arpeggio for a match and a door when
someone arrives. **Settings > Sounds** picks the ringtone (Marimba, Classic or Pulse) and the notification tone (Chime,
Ping or Knock), each with a play button; the choice is kept in the browser. Voice notes follow the master and Phone
volumes. Every sound is on the audition page (`/?sounds=1`). The ringtone rings for an arriving voice note or video
message: the story has no calls.

## Place art

The story ships all 48 plates of its 28 places (spec §18.1) in `data/art/plates/scenes/`, rendered in v0.23.0
through the xAI image API (`scripts/generate_art.py --game read-receipts --provider xai`, then `--promote`) and
each reviewed by eye before promotion. `data/art/subjects.yaml` holds the house style and one row per place: its
`base:` daypart (the plate shown for any daypart it has no plate for) and its `times:` (dawn, day, dusk, night),
each a short unpeopled description and its light. No row has `alts:`, and no prompt has a `negative` key or a
"no X" term. `data/art/manifest.yaml` names each place's base and daypart plates; it lists only files that exist.
[`data/art/MISSING-PLATES.md`](data/art/MISSING-PLATES.md) (`scripts/art_missing.py --game read-receipts`) lists
any subject still without a plate (none). Portraits are not in the pack (the match's media portrait is used).

## Pictures: turning on ComfyUI

By default every photo, video and profile picture is a procedural tile with
its caption, and nothing is contacted (`phone_media.provider: procedural`).
To have them generated, point the game at a ComfyUI server in
`config/local.yaml`:

```yaml
phone_media:
  provider: comfyui          # procedural (off) | comfyui
  portraits: on_match        # off | on_match (when you match) | on_view (when their card is shown)
  daily_job_cap: 40          # jobs per day; past it, procedural tiles
comfyui:
  base_url: "http://localhost:8188"   # or a hosted service's https URL
```

The image prompt is the person's appearance, what the photo shows, the
caption they wrote, the time of day and `media.yaml`'s `style`; nothing
else is added and nothing is taken out. A video is a short clip (about
3 s at 480p) with its poster frame, or with ComfyUI off the poster tile and
its caption. The workflows (`photo`, `portrait`, `video`), a key for a hosted service and what has been run live are in
[docs/MEDIA_SERVERS.md](../../docs/MEDIA_SERVERS.md).

## Voice notes: turning on TTS

Every person has a voice of their own, one of `tts.voices` of their sex. By
default (`tts.enabled: false`) a voice note is a waveform tile with its
length and its transcript (at most `media.yaml` `voice.max_seconds`, 15 s,
of words). With a Voxtral TTS server running and `tts.enabled: true` in
`config/local.yaml`, the transcript is spoken in their voice -- slowly: on
the development machine a 15 s note takes about five minutes, so it
arrives well after its message. docs/MEDIA_SERVERS.md has the settings and
why the tile is the expected path.

## Balance

`scripts/simulate_social.py` plays the phone headless and measures it (v0.23.0
spec §3.4, §17; AGENTS.md rule 10). Run it before you change any number in
`data/social/`:

```powershell
.\.venv\Scripts\python.exe scripts\simulate_social.py --game read-receipts --sessions 6 --seeds 10 --policy attentive --model-seconds 30
```

```sh
.venv/bin/python scripts/simulate_social.py --game read-receipts --sessions 6 --seeds 10 --policy attentive --model-seconds 30
```

Every swipe, like, message, "talk later", ask, answer and wait goes through
the phone's own mechanics action, and the replies are voiced by the same pass
play uses. The voice is a stub, never a model; since v0.23.0 T9 it proposes a
follow-up on one reply in ten and a promise on half the sign-offs that offer
one, and says it raised the follow-up and opened up whenever it is asked.
A run is SESSIONS (`--sessions`, 6 by default): 40 real minutes of the
player's actions from its waking hour, each priced in real seconds (a send 30,
a swipe, like or pass 4, each bubble read 3, and `--model-seconds` -- 6, 15 or
30 -- for each reply a send got; a wait is free), then "talk later" where it
was still talking and bed. A session is full by default (v0.24.0 T11): the phone takes at most 60% of the
40 minutes and the world day (work, dinner, plans, scenes, sleep) the rest; `--phone-only` is T9's phone-only session. `--policy` sets the player:
`attentive`, `swiper`, `picky`, `slow`, `neglectful`, `pushy`, `devoted`,
`bachelor`, `flaky`, `chatty` or `all`.
`--voice` sets the stub: `neutral_model` (the default: a working model's
pleasant, unremarkable replies, warmth and trust +1 a reply),
`romantic_model` (+3/+1), `cold_model` (-2/-1), `zero` (0/0), `no_model`
(every reply the fallback, moving `regard.fallback`) or `all`. It reports
the v0.23.0 spec's §17.2 rows (`REPORT_ROWS`; a row a phone-only session
cannot reach is `-`): exchanges per conversation and why conversations end,
cold messages unanswered within the hour, ghosting per conversation start,
the real minutes from a match to their number by pace, numbers within a
session, promises kept by them and by you, and fuller replies in long
conversations; the in-game minutes a real minute buys (derived, never
banded); and, unbanded, the real minutes to the `everyday` rung, every end
reason, left on read, initiations a day, photos, the days and real hours to
warming per archetype, and the voice prompt's tokens per mode.
`--disk DIR` plays on a real save store, spilling every thread into its
archive as play does (the same report either way).

Seed ranges run side by side (`--first-seed N --seeds 2 --raw OUT`, one
process each) fold into one report with `--fold OUT...`. `--json OUT` writes
the report. A six-session attentive run is about 550 actions and ten seconds;
an attentive report also runs the flaky player on the same seeds for its
promises row (`--no-companion` skips it).

**Where the measured tables live.** T9's phone-only pass (10 seeds x 6
sessions at 6, 15 and 30 model seconds) is in this story's
[CHANGELOG](CHANGELOG.md) (`[0.23.0]`), and the full-session pass (10 seeds x 60 sessions) under `[Unreleased]`; `conversation.yaml`'s,
`promises.yaml`'s and `growth.yaml`'s headers carry the rows their numbers
move. `tests/test_simulate_social.py` (`slow`) holds each row it bands at
all three latencies on seeds 0-9 -- ghosting at depth 0, the fast tercile's
real minutes to a number, and the attentive player's own promises -- and asserts every promise of theirs is kept; every
other row is deferred by data with its CLAUDE.md row (the phone-only misses
with their measured values, and the full-session rows of v0.24.0 T11, which `FULL_BANDS` bands or CLAUDE.md defers by data). The full-session tables are in the [CHANGELOG](CHANGELOG.md) (`[Unreleased]`).
`tests/test_social_save_size.py` pins a day-180 save under 1 MB.

## Screenshots and the layout check

`scripts/screenshot_runs.py` builds this story's runs (phone, media, world, scene) with no model --
`phone` (likes on Matchstick until someone matches, their chat open) and
`media` (that match on Natter, holding a photo, a voice note and a video
they sent, and a Tile Talk game going) -- and `--serve read-receipts` serves
them for `npm run layout-check --prefix ui`, which walks the lock screen,
home, the deck, a chat and the Tile Talk board at 1366x768, 900x600, 390x844
and 844x390 (AGENTS.md, "The client"). `media` reaches numbers by a set-up
step, not by play: with no model a relationship grows slowly, and numbers
takes in-game weeks. `--serve` takes `--voice-delay SECONDS`: each reply
then waits that long before its fallback line, so "typing" shows as it
would with a model. The serve's log carries one `operation=phone_action`
line per action, which is how the phone's hosted rate limit was measured
(docs/HOSTING.md, Phone actions).

The README's three world captures (`ui/tools/screenshots.mjs`) come from the
`world` and `scene` runs: `read-receipts-world` at 900x600 with the phone put
away (at 1366 the phone always sits beside the world), `read-receipts-scene`
at 1366, and `read-receipts-beside` at 1366 with the phone picked up. Each
shows the place's plate: every frame carries its `scene_image`.
