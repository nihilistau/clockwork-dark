# READ RECEIPTS

A new city, a new phone, two dating apps. You have just moved to Port Merrow,
a harbour city of the present day, and your phone is the whole stage: two
dating apps (Matchstick and Front Porch), texts, an instant messenger
(Natter), two games, photos, a calendar and contacts. There is no plot and no
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
dating, friends, something casual or together, by gates of warmth, trust and
time together, shown to you only as words ("Talking", "Cooling off") and a
closeness band; it can cool off and warm up again, fade after three weeks
without contact, take a turn, or be ended by you, and it can start again.
You can answer when they offer their number or ask to be exclusive, and ask
them yourself -- though not three times in a day. "Their number" stays greyed
on the Ask menu until they would consider it (warmth, trust and enough
messages between you; no set number of days), and a no that means "not yet"
says so. Ask for a photo, a voice
note or a video (they decide, by how close you are, and may say "later"),
or send your own. Plan a meet-up, or let them ask you; go, cancel or miss
it, and the engine decides how it went. Play Tile Talk, a word game on an
11x11 board, or This or That, five quick either/or pairs, with anyone you
are talking to -- you invite them with a game invite, or they ask you.

Their words are written in the background while you keep using the phone:
each reply from `prompts/texter.md`, checked against what the engine holds
(and checked again just before it lands, in case something changed
meanwhile), with the story's own fallback lines when no model answers; you
see typing dots while one is being written. With no model server at all the
game still plays: the fallback lines move a relationship on slowly
(`relationships.yaml` `regard.fallback`). An answer not yet written when
its writer unmatches, is blocked or is ended is withdrawn, never shown.

The phone saves itself: at once when you match, a relationship moves or you
end one, and otherwise within ten seconds of your last tap; a long
conversation's older messages are kept beside the save and paged back in
when you scroll up. A new run starts at seven in the evening, and the city
does not wait for you: while you are away the time passes there too (real
time, hour for hour, at most three days), people write, matches arrive and
expire, a meet-up you sleep through is a no-show, and when you come back the
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
| Calendar | Your meet-ups, with Go on the day |
| Contacts | Everyone you talk to, and each one's contact card |
| Settings | Your bio on each dating app, your discovery (fixed for the run), Natter's read receipts and, playing locally, "Let time pass" |

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
make the time you ask for and offer another ("Fri 19:00 works."), Accept
on that line asks for theirs. On a screen 1200px
wide or more the card opens beside the phone. Games holds your Tile Talk
and This or That games: place tiles by tapping a tile and a square (or
dragging), then Play; answer This or That's five pairs one at a time and
wait for the reveal. Photos keeps your camera roll and what people sent
you; Calendar your meet-ups, with Go on the day. Settings edits your bio on
each dating app, shows your discovery (fixed for the run), switches
Natter's read receipts and, playing locally, "Let time pass": 30 seconds
untouched on a conversation where they are typing lets 15 minutes go by
(only while the page is in view, and at most an hour's worth before you
touch the phone again).

```powershell
.\.venv\Scripts\python.exe launcher.py --game read-receipts
```

```sh
.venv/bin/python launcher.py --game read-receipts   # Linux
```

What changed, release by release: [CHANGELOG.md](CHANGELOG.md). The design is
[docs/superpowers/specs/2026-10-08-v0.22.0-dating-sim-design.md](../../docs/superpowers/specs/2026-10-08-v0.22.0-dating-sim-design.md).

## The files

- `game.yaml` -- the manifest. It declares `paths.locations`, `paths.prompts`
  and `paths.social`, and nothing else; its header comment lists what it
  deliberately does not declare, and why.
- `data/world/locations.yaml` -- one node, `home`, with no edges, so `travel`
  is never offered. Meet-up venues are rows of `data/social/venues.yaml`.
- `data/social/*.yaml` -- the social engine's data, found by fixed name
  (`creation`, `population`, `behaviours`, `apps`, `relationships`, `media`,
  `venues`, `games`). Every number in them is a balance constant, measured
  and tuned by `scripts/simulate_social.py` (Balance, below).
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
  archetypes, each a set of numbers (how fast they read and reply, how
  likely they are to start a conversation, to ghost, to double-text, to
  flake on a date) and the messages they start on their own, plus the arcs
  that change a relationship over time (a turn, a slow fade). Each person's
  week comes from their job's shape in `population.yaml`: asleep, at work,
  free or out. Its `pacing:` block holds the terms every archetype's reply
  and ghost decisions share (interest, a burst of your messages, their
  status, the stage you are at). Its `canon:` table holds what an arc's
  turn reveals about a person, in prose, added to what they remember having
  told you.
- `data/social/relationships.yaml` -- where you stand with each person: the
  stages and the gates between them, the closeness bands, how far a reply
  or a day can move their warmth and trust, what keeps them interested,
  their moods, how often you may ask for something, when a relationship
  cools or fades, and what a reply may propose (their number, being
  exclusive, a step back, or -- held by `media.yaml` -- a photo, a voice
  note or a video); and the phrases a reply is checked against
  (claiming a stage not reached, a photo never sent, a refusal over an
  attached one, agreeing inside a decline, a meet-up never planned or one
  planned denied), with the negations that cancel a claim and the
  contacts' names that are also ordinary words. Its `meets:` block runs
  meet-ups (below).
- `data/social/venues.yaml` -- where meet-ups happen: each venue's name,
  neighbourhood, kind, the hobbies it suits and how long a meet-up there
  lasts, and the kinds' words ("Coffee" "at").

  **Meet-ups.** From swapped numbers on, you can propose a meet-up (a
  venue, a day one to seven days ahead, and a slot: morning, afternoon or
  evening), or just ask to meet and let them pick, or they may ask you.
  The engine answers at once: yes when you are close enough
  (`relationships.yaml`'s `meeting` gate) and both free (their week from
  their job; your calendar), another time when that slot is taken, or not
  yet. A yes is a Calendar row, and "Seeing each other". Whether they will
  flake is decided when you agree (their archetype's `flake_prob`) and
  shown on the day. When it is time, go or cancel (cancelling costs more
  the later it is); not answering by the slot's end is a no-show. Going
  takes the venue's hours and the engine decides how it went -- great,
  good, fine, awkward or bad -- from how well you match, their chemistry,
  their warmth, a hobby you share there, and a draw (`meets.quality`,
  `meets.bands`). Each band moves their warmth, trust and interest
  (`meets.effects`); two good-or-better meet-ups move you on to dating,
  friends or something casual, by what you both want. A recap appears in
  the thread, written by the model to agree with the band (or the
  engine's line, "Coffee at The Copper Kettle with Kai. It was a little
  awkward."), and they text you afterwards at their own pace -- unless it
  went badly or they are a ghoster. A meet-up you sleep through -- a
  plan whose slot passes while you are away -- is a no-show like any
  other ("You missed coffee at ..." on the lock screen). Someone who has
  gone quiet does not answer a proposal at all; a plan of theirs you
  never answered lapses when its time comes, at no cost; and plans with
  someone who unmatches you, or whom you block or end things with, are
  called off.
- `data/social/media.yaml` -- photos, voice notes and videos, which are
  rare and earned. Each person holds a small budget of each (refilled a
  little every morning, to a cap) that opens at a stage (photos and voice
  notes once you are talking, videos once you have swapped numbers). When
  you ask, they decide at their next read -- by their trust, warmth, mood,
  kind of person and how often you have asked today -- and may say yes, no
  or "later" (kept or broken the next morning); now and then they send one
  unasked. What a photo of theirs shows (`subjects`) depends on what they
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
  section (the only part sent to the model, as its system message), the
  `## Instructions` table of situation lines (one `- \`<id>\`: <line>` row
  each; every situation the engine or `behaviours.yaml` names needs one),
  and the `## Fallbacks` used when no model answers (one `yaml` block, by
  archetype then situation; `decline` is tried first for any answer that is
  no, and a situation with no row uses `reply`).
- `prompts/thread_summary.md` -- the running summary of one conversation:
  each person remembers only their own conversations with you, at most 180
  words of summary beside the latest messages word for word (the number is
  also the engine's `social.memory.summary_words`; keep them equal).
- `prompts/date_recap.md` -- the recap of a meet-up, sent as the system
  message verbatim with five blocks after it: WHO, WHERE, HOW IT WENT (the
  band, already decided), TOPICS and FORMAT. A recap whose words go
  against the band (`relationships.yaml` `meets.recap_tone`) is asked for
  once more, then replaced by the engine's line.

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

`scripts/simulate_social.py` plays the phone headless and measures it (spec
§20; AGENTS.md rule 10). Run it before you change any number in
`data/social/`:

```powershell
.\.venv\Scripts\python.exe scripts\simulate_social.py --game read-receipts --days 60 --seeds 40 --policy attentive
```

```sh
.venv/bin/python scripts/simulate_social.py --game read-receipts --days 60 --seeds 40 --policy attentive
```

Every swipe, like, message, ask, answer and wait goes through the phone's
own mechanics action, and the replies are voiced by the same pass play uses.
The voice is a stub, never a model. `--policy` sets the player:
`attentive`, `swiper`, `picky`, `slow`, `neglectful`, `pushy` or `all`.
`--voice` sets the stub: `neutral_model` (the default: a working model's
pleasant, unremarkable replies, warmth and trust +1 a reply),
`romantic_model` (+3/+1), `cold_model` (-2/-1), `zero` (0/0), `no_model`
(every reply the fallback, moving `regard.fallback`) or `all`. It reports
every row of spec §20: like-to-match per app, matches that reach talking or
hear from the person within 3 days, ghosting and numbers from talking,
numbers to a meet-up and how the meet-ups went, interest's half-life, live
relationships at day 30, messages a day, photos, voice notes and videos per
relationship, turners' turns (a run of 75 days or more), and the events a
72-hour away runs at day 60; and the median days from a match to each
closeness band for each archetype. It also reports reply latency, the due
messages and missed meet-ups a 72-hour away leaves, and a few counts.
`--disk DIR` plays on a real save store, spilling every thread into its
archive as play does (the same report either way).

Seed ranges run side by side (`--first-seed N --seeds 1 --raw OUT`, one
process each) fold into one report with `--fold OUT...`. `--json OUT` writes
the report. A 60-day attentive run is about 7,300 actions and five to ten
minutes, so the full pass is run that way.

**Where the measured tables live.** The full pass (v0.22.0 T26, 20 seeds),
its before and after, is in this story's [CHANGELOG](CHANGELOG.md)
(`[0.22.0]`, Changed); each `data/social/*.yaml` header carries the rows
its numbers move, with the date and the command; the v0.22.0 plan's notes
keep the tuning's before tables. `tests/test_simulate_social.py` (`slow`)
holds every row in its band on seeds 0-9 but four, deferred with their
reasons in CLAUDE.md: live relationships at day 30 (35 against 4-10; a quiet
relationship stays live for the 21 days before it fades, by design), and,
since the numbers gate lost its days in the final review, talking-to-numbers
and numbers-to-meet within 21 days and the awkward meet-ups (v0.23.0
redesigns pacing around real session time). One closeness cell is deferred
the same way: a romantic's days to warming (5.22 on seeds 0-9, 3.76 over 40
seeds; `DEFERRED_CLOSENESS`).
`tests/test_social_save_size.py` pins a day-180 save under 1 MB.

## Screenshots and the layout check

`scripts/screenshot_runs.py` builds this story's two runs with no model --
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
