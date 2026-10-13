# Changelog — READ RECEIPTS

What changed in **READ RECEIPTS**'s own content: everything under
`games/read-receipts/`, plus the story-specific pieces that live elsewhere
(its UI plugin in `ui/src/stories/read-receipts/`). Engine changes, and each
release as a whole, are in the [root CHANGELOG](../../CHANGELOG.md). Version
numbers are the repo's releases, and a release is listed here only if it
changed this story.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.22.0] — 2026-10-14

### Added

- The story's skeleton (v0.22.0 T2): `game.yaml` (`endless: true`,
  `paths.social`, the UI plugin `read-receipts` with no engine panels, the
  wall-clock tick off), one location (`home`, "Your flat"), the three prompts
  (`texter.md` with its instruction table and fallbacks, `thread_summary.md`,
  `date_recap.md`) and the eight `data/social/` files, each filled by the
  task named below.
- The population (v0.22.0 T3, `data/social/population.yaml`): 165 female
  and 150 male names, the eleven neighbourhoods of Port Merrow and the
  distance table between them, 52 jobs (each with its week's shape: office,
  shifts, nights, student or freelance), 53 hobbies with matching tags, 34
  traits, the creation attribute tables (height, build, hair, style, drinks,
  smokes, kids), appearance tables, six per-person flags, ten texting styles
  with a bio bank each, ten Front Porch prompts with answers by hobby, 33
  described photos and the people's preferences; and in `apps.yaml` the two
  dating apps' label, kind, capabilities, pools (Matchstick 900, Front Porch
  400, a 60-person band on both; Matchstick's 1800 since T26) and culture weights (archetype and intent).
- Creation (v0.22.0 T4, `data/social/creation.yaml`): the form, spec §3.1's
  fields -- name, sex, age (18-75, the apps' own minimum, as data), what the
  player is looking for, two to six hobbies, the attributes (height, build,
  hair, style, job, drinks, smokes, kids), five personality sliders, the
  discovery settings (age range and distance) and one to six photos.
  Hobbies, hair, style, job and photos are chosen from `population.yaml`'s
  own tables. Every field has a default, so a new game with no form filled
  in starts with a seeded default player.
- Behaviours (v0.22.0 T5, `data/social/behaviours.yaml`): the twelve
  archetypes (romantic, slow burner, banterer, dry texter, needy, ghoster,
  breadcrumber, drifter, turner, steady, busy, night owl), each with its
  reply and read pacing, reply, opener, ghosting and flaking chances,
  left-on-read sensitivity, warmth multiplier and cap, cool-off step, double
  texts, initiations, media and game habits; and two arcs, the turner's
  `turner_wants_different` and the drifter's `drifter_fade`. Measured and tuned in T26 (Changed, below). `prompts/texter.md` gains three
  situation lines the initiations name: `check_in`, `late_night` and
  `breadcrumb`.
- The phone's first actions (v0.22.0 T6): `wait` (until the next thing, a
  quarter of an hour, an hour, or the morning), `edit_profile` (a dating
  app's bio, up to 600 characters) and `set_receipts` (Natter's read
  receipts on or off). A choice sent to this story is answered "Read
  Receipts is played on the phone."
- The apps (v0.22.0 T7, `data/social/apps.yaml`, spec §6 whole): Matchstick
  (a swipe deck, 60 likes and one super like a day, matches expire after 7
  days) and Front Porch (a browse deck of full profiles, 8 likes a day with
  a comment, one person a day who likes you first, matches expire after 14
  days), Texts and Natter (after numbers), Games, Photos, Calendar,
  Contacts and Settings, each with its capabilities and the in-game minutes
  its verbs cost; the two dating apps' `selectivity_mult`; and the
  `matching:` block (compatibility's weights, the looking-for table,
  dealbreakers, chemistry, the like-back's base chances, profile
  completeness, the super like, when a like is seen, and how far each
  discovery distance reaches). `population.yaml` gains `like_comments`, a
  bank per texting style; `creation.yaml` gains `neighbourhood`, where the
  player lives. Measured and tuned in T26 (Changed, below).
- Messaging and pacing (v0.22.0 T8): `behaviours.yaml` gains its `pacing:`
  block (the reply chance's interest and burst factors, the reply latency's
  status multipliers and the ghost chance's stage factors) and its header
  documents the initiations' `when` conditions; `apps.yaml`'s header gains
  `first_message` and `unlock`, and says what `receipts` does. Three new
  phone actions: `send` (a text in any thread; a capability an app lacks is
  refused in words, "Texts can't send voice notes"), `open_thread` and
  `ask {what: number}`. Measured and tuned in T26 (Changed, below).
- Relationships (v0.22.0 T9, `data/social/relationships.yaml`, spec §10):
  every stage with the words the player sees ("Just matched", "Talking",
  "Swapped numbers", "Seeing each other", "Dating", "Friends", "Something
  casual", "Together", "Cooling off", "Ended", "Lost touch", "Match
  expired") and the gates between them (talking after 4 exchanges; numbers
  at warmth 30, trust 23 and 20 exchanges, with no days in touch (the final
  review's wave 2, Fixed below; T26 had trust 40 and 6 days); meeting at
  warmth 70 and trust 70, as tuned in T26; dating, friends or fling after two good meet-ups,
  by what both want; together at warmth 80 and trust 70 after four weeks
  dating, both wanting something long-term); five closeness bands (new,
  warming, close, very close, inseparable); where regard starts and how far
  a reply and a day may move it; interest (per exchange, a hobby named,
  each quiet day, being left on read); six moods; ask pacing (two asks of a
  kind a day, the second at half the odds and a little warmth, the third
  "Give it a day"); five cold days wind a relationship down (two warm
  mornings at 30 or more bring a cold spell back, never a turn), 21 silent
  days fade it; what an engine-written fallback reply proposes
  (`regard.fallback`, warmth 1 and trust 1 under a daily cap since T26); and the three proposals a reply may make (`offer_number`,
  `ask_exclusive`, `cool_off`). `behaviours.yaml`'s turner arc gains its
  history line. `data/world/locations.yaml`'s `home` takes `evil_multiplier:
  0.1`, the engine's floor, which 0.0 was clamped to with an ERROR at every
  load. Two new phone actions, `answer` (yes, no or later to their
  number or to being exclusive) and `end`, and `ask {what: exclusive}`.
  Measured and tuned in T26 (Changed, below).
- The phone saves itself (v0.22.0 T10, the engine's `engine/social/saves.py`):
  at once on a match, a relationship's move or an ending, otherwise within
  ten seconds of the last tap; a thread's messages past the newest 24
  (`social.state_messages`) are
  kept beside the save (`phone_archive.jsonl`) and paged back in by the
  thread's scroll (`GET /api/phone/thread/<thread_id>`). No content changed.
- What a reply must agree with (v0.22.0 T11, `data/social/relationships.yaml`,
  spec §11.5): the stage `claims:` sharpened so an innocent sentence does
  not read as one ("we're exclusive", not "exclusive"; "it's over between
  us", not "it's over"; "you're my girlfriend", not "my girlfriend"; "our
  first date was", not "our date"; "my partner", "text me on" and "see you
  tonight" dropped), and the phrase lists the
  agreement checks match: `media_claims` ("sent you a pic"), `media_denials`
  ("not sending"), `agree_phrases` ("here you go", for a decline),
  `negations` (a claim they cancel) and `ordinary_names` (contacts' names
  that are also words or places -- April, Will, Miles, Jordan, Kit, Max --
  never read as a name; all 314 names reviewed, 70 listed).
- Memory (v0.22.0 T12, spec §12): `behaviours.yaml` gains a `canon:` table,
  the prose each arc's `reveal` adds to a person's canon (the turner's
  `wants_something_else`), checked at load. A person remembers what they
  shared and what the player told them, one memory per person; each
  conversation keeps a running summary of at most 180 words, written by
  `prompts/thread_summary.md` (unchanged: its "at most 180 words" is now
  the engine's `social.memory.summary_words` too, and a test holds them
  equal).
- The voice (v0.22.0 T13, spec §11): each reply is written from
  `prompts/texter.md`, whose persona section alone is the system message,
  whose instruction table gives each situation's line, and whose fallbacks
  answer when no model does. The fallbacks gain `answer_request` (yes to
  their number or to being exclusive) and `decline` (any answer that is no,
  tried first) for all twelve archetypes, and a line saying how they are
  read. Every situation the engine or `behaviours.yaml` names has a row,
  checked at load and by the validator. A fallback reply moves warmth and
  trust by `regard.fallback` (warmth 1, trust 1, at most 3 and 2 a day per
  person since T26), so a game played with no model still warms, slowly.
- Replies are voiced in play (v0.22.0 T14, the engine's
  `engine/social/voicer.py`): after each tap, the people with something due
  are written to in the background -- the thread shows typing dots while a
  reply is being written, then the bubbles and the notification's preview --
  while you keep swiping and sending. What has changed since they started
  writing is checked again before the reply lands (a reply to someone you
  unmatched is thrown away; an ask they can no longer make is dropped), and
  a person who has gone -- unmatched, blocked or ended -- leaves no "..."
  behind: what they had not yet said is never sent, even if they come back. No
  content changed.
- The first balance pass (v0.22.0 T15, spec §20):
  `scripts/simulate_social.py --game read-receipts` plays the phone
  headless. A scripted player (`attentive`, `swiper`, `picky`, `slow`,
  `neglectful`, `pushy`) plays against a stub voice (`romantic_model`,
  `cold_model`, `zero`, or `no_model`, the fallback; since T26 also
  `neutral_model`, the default). No model is called.
  The harness reports match rates per app, conversations started, ghosting,
  numbers swapped, reply latency, interest's half-life and days to each
  closeness band per archetype. The first tables are in the v0.22.0 plan's
  notes; nothing was retuned (T26 tunes against the full pass). No content
  changed.
- Away and resume (v0.22.0 T16, spec §15): a new run starts at 19:00 on day
  1 (`creation.yaml`'s new `start_hour: 19`). Coming back to a run, the
  time you were away passes in the city -- real time, hour for hour, at most
  72 hours -- and the phone opens on its lock screen: "While you were away:
  5 messages from 3 people, 1 new match, 1 match expired", with the
  notifications. The replies that fell due meanwhile are written as soon
  as you are back.
- Media (v0.22.0 T19, `data/social/media.yaml`, spec §13.1): per-person
  budgets for photos, voice notes and videos (start, refill a day, cap, the
  stage each opens at), the odds a request is accepted (by trust, warmth,
  mood) and how often a no is "later", the odds of one sent unasked by
  stage, the four subjects of a photo of theirs (a selfie, what they are
  doing, the view from work, their pet -- `has_pet` only), four things the
  player can send besides their profile photos, the portrait's scene, the
  image style and a voice note's longest transcript (15 s). In
  `relationships.yaml` the three proposals `offer_photo`, `offer_voice` and
  `offer_video` (`stage: live`, held by the budget, the stage and the app).
  Measured and tuned in T26 (Changed, below).
- Video messages (v0.22.0 T20, spec §13.8): with ComfyUI on, a video
  someone sends you (or one you send of a `player_subjects` row) is a short
  generated clip with its poster frame; with it off, the poster tile and
  the caption. The engine's video workflow is described in
  docs/MEDIA_SERVERS.md and is unverified until run.
- Voice notes (v0.22.0 T21, spec §13.6-13.7): every person has a voice of
  their own (one of the TTS server's, of their sex). A voice note of theirs
  is what they say in it, at most 15 s of words; with TTS on it is spoken
  in their voice (late: about five minutes a note on the development
  machine), and otherwise it is a waveform tile with its length and the
  transcript. You can send voice notes on Front Porch and Natter: what you
  say is kept as its transcript, the audio is not.

- Tile Talk (v0.22.0 T22, spec §21.1): a two-player word game in the Games
  app, against anyone you are at least talking with. `data/social/games.yaml`
  `wordgame:` holds the 11x11 board's premium squares, the 72-tile bag (70
  letters and two blanks, each letter's count and value), the 35-point bonus
  for playing all seven tiles, how hard the other player searches (a node
  budget of 20,000) and how often they pick their best move by skill
  (`top_k_by_skill`, read with each archetype's `games.skill`), how many
  passes and swaps in a row end a game, their pace (their reply latency x
  1.5), how often a move of theirs brings a message about it (0.35), and
  what a finished game does (familiarity +2 exchanges, interest +4; a win
  of more than 80 points over a needy person costs them 3 warmth), and
  `swap_bag_min` (0: a swap needs only as many tiles in the bag as it
  swaps). You can resign a game on either turn; declining their invite
  costs nothing. The first move of a local run loads the word list (about
  1.5 s).
  `data/social/words.txt` is the ENABLE word list (172,820 words, public
  domain; its source is in the README). `relationships.yaml` gains the
  `invite_game` proposal (`stage: live`; the engine also needs the Games app
  open with them, no game running and none asked). Measured and tuned in T26 (Changed, below).
- This or That (v0.22.0 T23, spec §21.2): the second game in the Games app.
  `data/social/games.yaml` `this_or_that:` holds a bank of 64 either/or
  pairs (each side a label and tags), 31 tags linking the pairs to the
  population's hobbies, traits and personality sliders, how a person's
  profile leans their picks (`lean`: hobby 1.0, trait 1.0, slider 1.0,
  sharpness 1.0, noise 0.2), their pace (`pace_mult` 1.0) and the effects
  (a finished game familiarity +1 exchange and interest +2; each agreement
  +1 and +1 more). The reveal writes each agreement ("You both pick
  mountains over beaches") into what they hold and what they know of you,
  and brings their reaction as a message. A person now asks you for a game
  of their own accord, at their archetype's `games.invite_prob_per_day`
  (behaviours.yaml, read since T23), for the game you two have played
  least. Measured and tuned in T26 (Changed, below).
- Meet-ups (v0.22.0 T24, spec §14): `data/social/venues.yaml` holds fifteen
  venues across Port Merrow (coffee, drinks, dinner, walks, a gallery and a
  museum, a cinema, a climbing wall, a board-game café and a gig cellar),
  each with its neighbourhood, the hobbies it suits and how long a meet-up
  there lasts, and the nine kinds that make the engine's line ("Coffee at
  The Copper Kettle"). `relationships.yaml` gains `meets:` (three slots,
  morning 10-12, afternoon 14-16 and evening 19-21, proposed 1-7 days
  ahead; the quality terms and the band thresholds, great 0.75, good 0.6,
  fine 0.45, awkward 0.3 (T26's are below); each band's effects; cancelling at -8/-4/-2
  warmth within 3 hours, within a day, or earlier; a no-show -12 (-8 since T26); no text
  afterwards after a bad meet or from a ghoster; each band's line; the
  recap's tone lists; a `fine` recap may say it went neither very well
  nor badly), the `ask_meet` proposal, and `meet_claims` /
  `meet_denials` for the "meeting claimed" check. Two good meet-ups move
  "Seeing each other" to dating, friends or something casual.
  `prompts/date_recap.md` is final. Measured and tuned in T26 (Changed, below).
- The phone, in the browser (v0.22.0 T27): setting up your phone (a
  four-step wizard over `creation.yaml` -- you, looks, interests, what you
  want -- with the form's limits checked as you go and a refusal shown under
  its field); the lock screen (the time, the notifications newest first, the
  opening or "While you were away" line, "Put it down" to let time pass);
  home (every app with its unread badge, the dock: Texts, Natter,
  Matchstick, Front Porch; the side button locks the phone); Matchstick
  (the deck by drag, buttons or the arrow keys, super like while one is
  left, matches and chats); Front Porch (browse a profile's photos and
  prompts and like one with a comment of up to 140 characters, or pass;
  Likes you; matches; chats); and the conversation (below). Games, photos,
  calendar, contacts and settings: below (T29).
- The conversation, whole (v0.22.0 T28, spec §18.2): bubbles with their
  times; "Read 21:16" on Natter (receipts) and "Delivered" elsewhere; typing
  dots only while they are writing, and "…" for a reply not yet written;
  photo, voice-note (waveform, length, transcript; a player once a spoken
  file exists) and video tiles (a player with its poster once a clip
  exists), each a drawn tile with its caption while image and video
  generation are off (the default); the engine's own lines and the asks and
  answers told in words; their open requests as cards (Yes / Maybe later /
  No), your own waiting for an answer; the games and meet-ups with them
  (whose turn and the scores; where, when, Go on the day, Cancel with a
  confirm); "Load earlier" paging the archive 50 at a time; and the compose
  bar with only the app's own attachments (a camera-roll photo or a
  photo/video subject on Texts and Natter, a voice note -- held to the mic
  or typed -- on Front Porch and Natter), "Ask" (their number on a dating
  app, a photo, a voice note or a video where the app carries one, to meet
  up, to be exclusive), a live count to 600 characters, and "Not sent — tap
  to retry" keeping the words and the attachment. On a landscape phone
  (844x390) the app's conversation list sits beside the thread.
- The rest of the phone (v0.22.0 T29, spec §18.2-18.3):
  - **The contact card** (Contacts, or the "i" in a conversation's header):
    their photos and profile as their dating app shows it, where things
    stand in words (the stage and how close you are, never a number), when
    you last heard from them, "Your story" (the moments the engine
    recorded) and what they have told you about themselves; Message, plan a
    meet-up (a place, a day one to seven days ahead, morning, afternoon or
    evening), start Tile Talk or This or That, and unmatch, end things or
    block, each behind a confirm. On a screen 1200px wide or more it opens
    as a sheet beside the phone, the conversation staying in view.
  - **Games**: the games you have going and the ones just over, and a new
    game with anyone you talk to. Tile Talk draws the board with its
    premium squares, your rack, the scores and the bag's count: tap a tile
    then a square (or drag it), tap a placed tile to take it back, pick a
    blank's letter, then Play, Pass, Swap (pick the tiles) or Resign (after
    a confirm); the engine judges the move and the score. This or That asks
    the five pairs one at a time, sends your answers with the fifth, waits
    for theirs and reveals both and how many you agree on. A strip under
    each game opens your chat with them; a game card's Play in a
    conversation opens the game.
  - **Photos**: your camera roll and what people have sent you (a photo or
    a video once its message has arrived), each opening its chat.
  - **Calendar**: your meet-ups, coming up and before, with Go on the day
    and a confirm to call one off.
  - **Settings**: your bio on each dating app (600 characters), discovery
    shown (it cannot be changed during a run), Natter's read receipts, and
    "Let time pass" (local play only, kept in this browser): with it on,
    leaving the phone untouched for 30 seconds while they are typing or a
    reply is on its way lets 15 minutes pass -- never while the page is
    hidden, the menu or a confirm is open, nor more than four times (an
    in-game hour) without a touch or key from you. The side button's lock
    screen ("Put it down") passes time by hand, always.
- Two README runs (v0.22.0 T30, `scripts/screenshot_runs.py`, no model):
  `phone` (Matchstick likes to a match, its thread open) and `media` (that
  match on Natter with a received photo, voice note and video, and a Tile
  Talk game going); the layout check walks both at four sizes, Tile Talk's
  board included. The acceptance walk was played in the pane at 1366x768,
  900x600, 390x844 and 844x390 (the record is in the release's commit).
- From that walk: Accept on a meet-up counter-offer; "New match" on the
  lock screen; procedural photo and video tiles keep their caption under
  the tile; "<name> said maybe later." on an ask they put off.
- The README, whole (v0.22.0 T31): what you can do, the apps, the files,
  the word list, turning on ComfyUI and TTS, and where the measured tables
  live; four captures of the phone in the root README
  (`docs/images/read-receipts-*.png`, from the T30 runs with no model).
  docs/AUTHORING.md §3.15 documents every `data/social/` file.
- Phone numbers work in a session (the owner's bug): the numbers gate is
  warmth 30, trust 23 and 20 exchanges, with no days to wait (it was trust
  40 and 6 in-game days, so every ask was "not yet"). "Their number" is
  greyed on the Ask menu until the gate holds, and a no that means "not
  yet" is said so, in their words and as "Not yet." under it.
- From the v0.22.0 final review: a photo, clip or voice note finished while
  the phone was busy saving lands without waiting for a tap; saying no to
  their meet-up no longer makes "Let time pass until something happens"
  stop at its slot for nothing, and a lapsed plan says nothing in the
  thread of someone who left or ended it; a reload after acting no longer
  shows the old "While you were away" again.
- Texts shows no typing dots, as SMS shows none: `apps.yaml`'s `typing:
  false` on Texts is read since T31 (it was documented and ignored, so
  Texts showed them like Natter); its header says how.

### Changed

- The balance pass (v0.22.0 T26 and its fix round 1, spec §20, rule 10):
  every §20 row landed in its band but one, live relationships at day 30,
  which is deferred (below). The final review's numbers gate (Fixed, above)
  then moved three more rows out of their bands, also deferred:
  talking-to-numbers and numbers-to-meet within 21 days and the awkward
  meet-ups (CLAUDE.md, `tests/test_simulate_social.py` `DEFERRED_ROWS`);
  the table below is T26's. Measured 2026-10-13 by
  `scripts/simulate_social.py --game read-receipts`, one process per seed
  side by side (`--first-seed N --seeds 1 --raw`, then `--fold`): 20 seeds
  x 60 days for the attentive player under all five voices, 20 seeds x 30
  days for each timed policy, 20 seeds x 75 days for the turners. The bands
  are pinned on seeds 0-9 by `tests/test_simulate_social.py`.
  Relationships stay: `fade_days` is 21 (spec §10.3) and a match expires in
  7 days on Matchstick, 14 on Front Porch, as before. The constants that
  moved:
  - `apps.yaml`: Matchstick's pool 900 -> 1800 (Front Porch's now starts at
    1800; at 900 an attentive player had swiped the whole deck by day 30);
    Front Porch's `likes_you_per_day` 2 -> 1; `like_back_base` 0.35/0.5 ->
    0.4/0.6.
  - `behaviours.yaml`: every archetype's `ghost_per_exchange` higher (the
    romantic's 0.002 -> 0.025, the ghoster's 0.04 -> 0.25); `stage_factor`
    matched 1.5 -> 6, talking 1 -> 1.2, numbers 0.6 -> 1.2, meeting 0.4 ->
    0.8 (a new match that is going nowhere goes quiet early);
    `interest_factor` [0.5, 1.2] -> [0.3, 1.5]; `status_mult` work 4 ->
    2.5, out 2.5 -> 1.8; the talking-stage check-ins' odds halved and the
    numbers-stage ones raised; the turner's turn at 8-30 exchanges (was
    25-60).
  - `relationships.yaml`: `interest` per exchange 1 -> 0, daily decay 1 ->
    5 (a half-life of 5 days, not 26); trust starts at 15 (was 10);
    `per_day_gain` 10/6 -> 6/4 (below what a warm model's replies add in a
    day, above a neutral one's); the numbers gate warmth 30, trust 40, 20
    exchanges, 6 contact days (was 35/25/12/2; since the final review's
    wave 2 it is 30/23/20 with no days, Fixed above); the meeting gate 70/70 (was
    45/35); the closeness bands' warming at warmth 30 and 3 contact days,
    close 13, very close 35, inseparable 60 contact days (was 1/4/12/30:
    "very close" is set by its contact days); the meet quality's spread
    0.18 and its compatibility, chemistry and warmth terms smaller, its
    bands 0.665/0.51/0.37/0.225; a no-show -8/-6 (was -12/-10, below).
  - `media.yaml`: the unasked odds 0.02/0.06/0.1 -> 0.06/0.12/0.12 by
    stage; a video's daily refill 0.05 -> 0.06.
- **Live relationships at day 30 are deferred** (CLAUDE.md "Deliberately
  deferred"): 35.0 against a band of 4-10. The attentive player matches
  about 2.5 people a day and answers everything, and a relationship that
  goes quiet stays live for its 21 days before it fades. A 1.75-day fade
  landed the band and was rejected: relationships remain.
- **A dead model server progresses, slowly** (spec §10.2's ruling,
  measured): `regard.fallback` +2/+1 -> +1/+1 under its own daily cap,
  `regard.fallback.per_day` 3 warmth / 2 trust (new; a working model's
  replies may add 6/4), measured against the harness's new default voice,
  `neutral_model` (a working model's pleasant, unremarkable replies,
  +1/+1). Over 20 seeds x 60 days, no model / neutral / warm: talking to
  numbers in 21 days 0.059 / 0.187 / 0.267, numbers a run 9.65 / 17.2 /
  22.9, numbers to a meet-up in 21 days 0.12 / 0.362 / 0.379, meet-ups 4.55
  / 30.0 / 42.2, and a romantic reaches warming / close / very close in 7.4
  / 18.1 / 38.7 days (neutral 4.1 / 15.4 / 37.5). A run with no model gets
  there, every step later (`tests/test_simulate_social.py` pins it).
- **A meet-up missed while away** stays a no-show (the T24 ruling) at a
  smaller cost, -8 warmth and -6 interest (was -12/-10): a 72-hour away at
  day 60 found 2.3 planned meet-ups a run and made 2.15 of them no-shows.
  It costs few relationships otherwise: 405 live across the 20 runs before
  the away, 380 after.
- The phone's save keeps its state bounded (spec §17.2): a dead or
  left-behind thread goes to the archive whole, a person you only swiped
  keeps only the swipe, and old answered requests are forgotten. A day-180
  save is 0.82 MB (2.87 MB before). No mechanic changes.
- Measured, after (20 seeds; the turners 75 days; T15's first pass, 14
  seeds of attentive with no model, for comparison):

| row | band | attentive, neutral model | warm | cold | zero | no model | T15 (no model) |
|---|---|---:|---:|---:|---:|---:|---:|
| like_to_match.matchstick | 12-25% | 0.133 | 0.133 | 0.133 | 0.133 | 0.133 | 0.116 |
| like_to_match.front_porch | 25-40% | 0.323 | 0.323 | 0.323 | 0.323 | 0.323 | 0.325 |
| match_to_talking_3d | 40-60% | 0.462 | 0.465 | 0.466 | 0.47 | 0.468 | 0.56 |
| match_to_message_3d | 55-75% | 0.677 | 0.689 | 0.677 | 0.678 | 0.68 | 0.763 |
| talking_to_ghosted_14d | 20-35% | 0.282 | 0.344 | 0.126 | 0.185 | 0.253 | 0.027 |
| talking_to_numbers_21d.attentive | 15-30% | 0.187 | 0.267 | 0 | 0 | 0.059 | 0.786 |
| numbers_to_meet_21d | 25-45% | 0.362 | 0.379 | - | - | 0.12 | - |
| meet_band.great | 10-20% | 0.128 | 0.15 | - | - | 0.211 | - |
| meet_band.good | 25-40% | 0.308 | 0.298 | - | - | 0.342 | - |
| meet_band.fine | 20-30% | 0.265 | 0.255 | - | - | 0.303 | - |
| meet_band.awkward | 10-20% | 0.197 | 0.193 | - | - | 0.105 | - |
| meet_band.bad | 5-15% | 0.103 | 0.103 | - | - | 0.039 | - |
| interest_half_life_days | 4-10 | 5 | 5 | 5 | 5 | 5 | 26.3 |
| live_relationships_day30.attentive | 4-10 (deferred) | 35 | 31.9 | 37.9 | 40 | 36.2 | 53.6 |
| messages_per_day.attentive | 15-60 | 29.5 | 35.9 | 10.9 | 16.3 | 24.9 | 148.65 |
| photos_per_close_week | 0.5-1 | 0.701 | 0.518 | - | - | 0.464 | - |
| voice_per_relationship_week_after_numbers | 0.5-1.5 | 0.713 | 0.704 | - | - | 0.681 | - |
| videos_per_close_month | 0.5-1.5 | 1.12 | 0.947 | - | - | 1.04 | - |
| turners_turned_60d | 60-90% | 0.825 | - | - | - | - | - |
| events_per_72h_away_day60 | at most 1500 | 68 | 78 | 6 | 29 | 45 | - |

Days from a match to warming / close / very close (median; band 2-5 / 10-25 / 30-60, dry texters never close):

| archetype | neutral | warm | no model |
|---|---|---|---|
| romantic | 4.07 / 15.4 / 37.5 | 2.9 / 16.2 / 37.7 | 7.38 / 18.1 / 38.7 |
| steady | 2.3 / 13.5 / 35.8 | 1.95 / 15.6 / 37.4 | 3.74 / 16 / 39 |
| slow_burner | 6.29 / 16.5 / 37.4 | 2.33 / 13.8 / 39.4 | 7.7 / 20.9 / 40.2 |
| busy | 7.85 / 18.9 / - | 2.9 / 14.7 / 37.9 | 17.2 / 21.9 / 44.8 |
| dry_texter | 2.24 / - / - | 1.93 / - / - | 2.93 / - / - |

The timed policies (20 seeds x 30 days, neutral model):

| policy | matches | talking | numbers | live day 30 | messages/day | ghosted (14 d) | meet-ups (no-shows) |
|---|---:|---:|---:|---:|---:|---:|---|
| swiper | 259.65 | 115.55 | 18.7 | 74.3 | 77.6 | 0.283 | 7.2 (4.65) |
| picky | 49.4 | 23.9 | 3.15 | 16.4 | 13.5 | 0.282 | 1.25 (0) |
| slow | 112.35 | 52 | 7.25 | 34.6 | 33.2 | 0.291 | 4.3 (2.2) |
| neglectful | 110.55 | 36.9 | 0 | 29.9 | 13.9 | 0.137 | 0 (0) |
| pushy | 112.7 | 52.7 | 15.9 | 21.1 | 56.5 | 0.64 | 6.55 (0) |

  The swiper and the slow player look at fixed hours, so most of their
  meet-ups come due between looks and are missed (4.65 and 2.2 no-shows a
  run); the pushy player's "ask at every look" is refused "Give it a day"
  about 12,700 times a run. After a 72-hour away at day 60 the first voicing
  pass finds 47 due messages at the p95 (warm 54; `social.voice.max_per_pass`
  stays 3, config/default.yaml). The before tables (T25's constants, the same
  harness) are in the v0.22.0 plan's notes. The harness's stub voices
  propose nothing, so the media rows count only the engine's own unasked
  media (docs/GOVERNANCE.md).
