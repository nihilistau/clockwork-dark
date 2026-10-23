# Changelog — READ RECEIPTS

What changed in **READ RECEIPTS**'s own content: everything under
`games/read-receipts/`, plus the story-specific pieces that live elsewhere
(its UI plugin in `ui/src/stories/read-receipts/`). Engine changes, and each
release as a whole, are in the [root CHANGELOG](../../CHANGELOG.md). Version
numbers are the repo's releases, and a release is listed here only if it
changed this story.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.23.3] — 2026-10-23

### Fixed

- Asking someone for a voice note, a photo, their number or a meet-up a moment after a message of yours, while their reply to it was still being written, is answered: before, the ask waited for good (the engine's fix, root CHANGELOG [0.23.3]).

## [0.23.0] — 2026-10-23

READ RECEIPTS, reworked (the engine side is in the [root CHANGELOG](../../CHANGELOG.md)). People open up at their own pace, a conversation is an episode with instant replies, "talk later" and plans are promises the engine keeps, there is no set time on dating, phone numbers follow the conversation, and the world outside the phone is played: your flat and 28 places (48 plates), meet-ups as scenes, chance meetings, homes and visits, living together, engagement and marriage as live stages (there is still no ending), and life events. A v0.22.0 save loads. T29b (the full balance pass), T31 (live play), T32 (the docs pass) and T33 (the whole-branch review) are deferred to the end of v0.24.0 by the owner, as are the morning scene (T24) and four more life-event decks (T25); the first values in `scenes.yaml` and `life_events.yaml` are unmeasured until that pass.

### Added

- Task 29a (v0.23.0): a world turn costs about a quarter of what it did. At day 60 (about 1,700 people known) a typed turn at a venue took 366-375 ms of engine time before and 101-105 ms after, with nothing in the game changed: the save's copy and its write were made cheaper (the root CHANGELOG has how). Pinned by `tests/test_social_turn_cost.py`.
- Task 27 (v0.23.0): the place art. All 48 plates of the 28 places, rendered through the xAI image API (the new `xai` provider) and reviewed by eye; seven were re-rendered after the review (six came out as two scenes side by side, one cellar showed daylight), and the house style now says "lived-in places" and "unpeopled scenes" so an outdoor place is not drawn as a room. The manifest names each place's base plate, the one shown for a daypart it has no plate of its own for.
- Task 28 (v0.23.0): hosted, the rest. A world turn and a voice pass from one account are never refused `other_window` in either order, nor when the turn's arrival opens a scene (`tests/test_social_hosted.py`); a drain waits for a world turn still waiting at the turnstile and leaves a recap, a held text and an open scene saved for the resume; the narration share is a metric (the existing `phone` kind, events `narration_world` and `narration_voice`, once a minute at most); and the admin no-play-text scan plants a scene's narration, a recap, a story, a chance scene's narration and a held text through the engine's own writers and finds none on any admin page, metric, audit line, bus frame or log. Nothing in the story's content changed.
- Task 26 (v0.23.0): the final art subjects (spec §18.1). `data/art/subjects.yaml` holds the 48 place plates over all 28 locations (each with a `base:` daypart, no `alts:`, short unpeopled prompts with no `negative` key or "no X" term), `data/art/manifest.yaml` is created empty (T27 adds a row as each plate lands), `MISSING-PLATES.md` is the brief, and `game.yaml` declares `paths.art_subjects`, `paths.art_manifest` and `paths.art_root` (`data/art/plates/`, kept by a `.gitkeep`; the root must exist for the story to activate). The plates are T27's; until then the story plays on silhouettes. `tests/test_social_art.py` holds the table.
- Task 23H (v0.23.0): the owner's playtest is a test. Meeting at the place you are already in now plays start to finish in `tests/test_rr_playtest_replay.py` (ask, put the phone down, wait, they arrive and the scene's choices appear in the same frame, type a line, leave and the held texts land), and the client half is `ui/tests/rr-playtest.test.jsx`. Nothing in the story's content changed.
- Task 23G (v0.23.0): chance meetings with people you know. At a venue, a live contact may be there by their schedule (`scenes.yaml` `chance:`: 15% of their evening blocks out, 4% of their free ones, one venue a block that fits their hobbies, at most two at once; first values). They are named "Also here" on the world's picture and to the narrator, with whoever works there; their texts wait while they are across the room. "Go over to {name}" opens a `chance` evening (no plan needed; a `soon` plan with them counts as met), its start a little cooler (`prior_bias` -0.05). It swaps numbers or reaches "seeing each other" only as far as `growth.yaml` `willing` allows then, a good one counts toward dating only from "seeing each other", and the closers that make a plan wait for `willing.meet`. The run-in goes on their card ("Ran into each other at The Anchor"), sends no "after the date" text, and they are not offered again until their next block; when their block moves them on, their held texts arrive at your next action. Never strangers, and nobody by chance in the flat, the building, the street, a home or the registry office. The storyteller brief names who it may name (PEOPLE HERE and their notes, WITH YOU IN PERSON, "Also here", the buzz and the plans), and its VOICE paragraph is rewrapped. The committed `dist` is rebuilt.
- Task 23F (v0.23.0): people who belong to a place. Seven background people (a barista at The Copper Kettle and at Driftwood Roasters, bar staff at The Anchor and The Lantern Wine Bar, the building's concierge, and two neighbours in the lift and the lobby) stand where they work at their hours, are named in the narrator's PEOPLE HERE while they are there and are off the map otherwise (`data/world/npc_schedules.yaml`, `paths.npc_schedules`). They are not on the phone and not datable; the cast does not go through the schedule. The narrator's brief grows: 80-200 words a turn, a CHOICES section, TYPED LINES (a move's result is shown as the person's reaction, never printed as its word) and WHO IS AROUND.
- Task 23E (v0.23.0): typing in the world does things. A line you type is read by the engine against what it offers you right then: "make breakfast" in the kitchen, "*does the dishes*", "I'll tidy up" or "go to the hall" runs that one choice, as if you had picked it, with its time spent; "I'd love to make breakfast for you sometime", "should we go to the kitchen", "maybe later" and anything that names two things are not read as an action, only narrated (and, outside an evening, take no time). With someone, a line that names one of their topics asks about it (their topics first when it is a question), one that names a hobby of yours, something happening to you or "my job" tells them about it, and anything else is "Talk", a new move that is scored like the others (`scenes.yaml` `moves.talk`). "Talk" takes the place "Check your phone" held among the evening's choices (picking the phone up is still noticed by someone who finds it rude), and is one of the wedding's moves. A typed line never leaves, makes a plan or promise, goes over to someone, goes to work or uses the phone: those stay choices. `activities.yaml` gains `say:` phrases for every activity and a `typed:` block (the cue lists and the rooms' nouns), checked when the story loads.
- Task 23D (v0.23.0): a quiet phone while together. While someone is with you (a scene open, or arrived at your place with the phone up) their texts are held, never dropped: a due text is tried again every `conversation.yaml` `together.hold_retry_minutes` (15) and lands once you are apart, then voiced with "you were just together". A held text is one event replaced in place, so a long evening never grows the queue; a promised text keeps its promise open; no draw is made on a hold. Texts already landed but not yet voiced wait the same way. The engine's own "Kai's here" notice is not held. A pass follows the turn that ends the scene or walks you away, as every turn's does.
- Task 23C (v0.23.0): the person you arranged to meet turns up. A plan for now or tonight has them heading there: the venue's travel time (their home's when they come to yours; none at theirs) and up to `plans.yaml` `arrival.late_minutes` (0-20) late, so a "tonight" plan made at noon is kept in the evening, not the afternoon. Make a plan at the café you are sitting in and "Wait for Kai" is offered; they arrive, and the evening opens. Put the phone down, finish an activity (watching something stops at "Kai arrives."), end another evening or walk in, and they are met where you are; a plan at yours meets in the lounge from any room of the flat or the building. If you are not there they text you that they are; nobody texts "I'm here" from the road any more (`relationships.yaml` `arrival_claims`, checked when a reply is written and again when it lands). Their patience counts from when they got there, and they never stand you up while you are there: on the phone at the place you get "Kai's here" on it, and the evening opens when you put it down. If they arrive while you move between rooms or a narrated turn runs, that same frame shows the evening ("Kai arrives."). An "I'm here" is judged only while you have a plan with them, and never over someone else's arrival ("my mum just got here"). Asking them back to yours, going back to theirs or on somewhere else takes them with you, at once. `texter.md` gains the `arrived` row and its fallbacks.
- Task 23 (v0.23.0): the scene UI. A companion card (portrait, name, the stage's words and the closeness band's words, never a number) sits on the world's plate while a scene is open; outside one, a household line says who lives with you and where they are ("Sam lives with you, and is asleep."). The scene's moves and closers are the world's choices as before. Every phone action's answer now carries the world's legal choices (it carried none, so the world went dead once the phone had been used). The layout check walks the Places app, the plan sheet and the world at four sizes on the real resume frames, and the screenshot runs gain `world` (the flat at dusk, phone down) and `scene` (a scene at a venue). The committed `dist` is rebuilt.
- Task 22 (v0.23.0): the conversation UI. The chat's bar gains "Talk later" chips (`sign_off {who, window}`: "Message me in the morning", "I'll message you tonight") and its Ask menu opens a plan sheet for "To meet up" ("Free now?", "Tonight?", "Sometime soon", with an optional kind and place) and offers "To move in together" and "To marry you" only while the thread row's `asks` lists them. The thread header shows what they have told you of their days (`hints.available_words`). The contact card says "Getting closer", their available words, whether you could ask for their number and why not, and the promises and plans open between you; "Plan a meet-up" is now "Ask to meet" (the plan sheet). Calendar is "Coming up": open plans and promises in words, and the promises that are past. New Places app (every `places.venues` row, `go`). Settings gains "Wake me for messages" (`set_wake {to}`, a new phone verb; the payload's `settings.wake_for_messages`). A job offered elsewhere (`stay_or_go`) reads "Ask them to stay" / "Later" / "Let them go", with the cost of going said under it; their move-in and proposal requests, and yours, read as their own (never "asked you something"). A resumed run's world layer offers the engine's legal world choices (`away.world_choices`): "Look around" and every `do`/`go`/`scene`/`close` option, instead of none until a world turn is narrated. The lock screen's old "Put it down" is gone: the status bar's "Put the phone down" is the one way.
- A v0.22.0 save loads and is upgraded (v0.23.0 T20, spec §16): resumed, a v0.22.0 run's phone becomes this
  release's. Each relationship starts at the depth its stage had reached (numbers and meeting 1; dating,
  friends and fling 2; exclusive 3); what each thread's summary said becomes the person's story so far, and
  the last bubbles of their newest thread how you left it; a message of yours left unanswered is read and
  answered when they are next free (not by someone who has left); an agreed meet-up becomes a "soon" plan at
  the same place, and a pending ask to meet a "soon" ask; a done meet-up counts as an evening out; the
  player is in the flat's lounge, the phone in hand. "Let time pass" and a meet-up recap card not yet written
  are dropped.
- Living together, engagement and marriage (v0.23.0 T18, spec §12). Together is no longer the last step:
  once they are willing (`growth.yaml` `willing.move_in`: two weeks together, twelve scenes, warmth 78, trust
  72), either of you can ask to move in, and they move into your flat ("Living together"); an engaged or
  married couple can move in too, and only the household changes. Either of you can propose (`willing.propose`:
  together or living together, warmth 85, trust 80) on the phone, as their proposal, or in person as a closer
  ("Ask them to marry you"); `relationships.yaml` `wedding_after_days` (14) later, the wedding's date is set
  (`life_events.yaml` `wedding`) and a plan to the registry office waits for you; the wedding there is a scene
  of three moments that cannot go badly (`scenes.yaml` `wedding`), and at its end you are married. With
  someone who lives with you home and free, "Spend time with them" opens an evening at home with no plan, and
  the narrator voices them whenever they are home. Someone who lives with you does not move house or ask you
  round to their old place. Unmatching or blocking them, ending it, or letting it fade means they move out
  (and a wedding not yet held is off), and someone else can move in later. Being seen out with someone else while you are with
  someone (`life_events.yaml` `seen`: a quarter chance a scene) costs them 25 trust, makes them guarded and
  hurt for five days, and their card says "They found out"; cooling off and warming up again are the repair.
  None of these is an ending. Every number is a first value, measured at the balance task.
- Life events (v0.23.0 T17, spec §11): twelve events of yours and fourteen of each person's
  (`data/social/life_events.yaml`). What happens to someone reaches "Since you met", their next conversation
  (they tell you once), their mood and, for a hard one, your support; a holiday takes them out of reach for a
  week; a job offer elsewhere is a question you answer, decided by their warmth and trust. What happens to you
  (a boiler, a parcel, overtime, a cold) reaches them only if you say it: a topic in a meet-up, or the reason
  you give for going. Two small scenes, `data/scenes/boiler.yaml` and `parcel.yaml`, deal in the kitchen and
  at reception. Plain ordinary life, nothing more.
- Homes and visits (v0.23.0 T16, spec §10.5): at their home or your flat, once the stage holds `stay_over`, the
  evening is going well, they have the energy and no early start, "Stay the night" is a closer. They answer by
  archetype alone (`scenes.yaml` `stay.accept`; no intent term). A yes ends the scene, takes the clock to your
  morning and leaves a "Stayed over" line on their card; their "after the date" text waits for that morning. A
  no is a plain answer, with a reason only when one holds (they are worn out, or the home's `stay_reasons`).
  Logistics only; the morning scene is v0.24.0's.
- The narrator voices the person you are with (v0.23.0 T15, spec §10.6): during a meet-up it is told who
  they are now, where you are, your story together and this moment, and what it writes is held to the
  same facts as their texts -- their age, job and neighbourhood, who they can know, where the two of you
  stand, and the promises, plans and steps only a closer makes. Prose that gets one wrong is rewritten
  once; a second miss shows the engine's own lines for the moment instead. With no model, a meet-up shows
  those lines too.
- No deck is dealt over an in-person scene (v0.23.0 T14): the director waits, unspent, until the scene ends.
- Meet-ups are played in person (v0.23.0 T13, spec §10): arriving on a plan opens a scene with them, and the
  narrated turn is the evening's. Each move is a conversational one (`scenes.yaml` `moves`): ask about one of
  their topics, tell them about one of yours, be playful, let a silence sit, check your phone. It lands, goes
  fine, falls flat or is a misstep, by the prior (v0.22's meet quality, moved from relationships.yaml), the
  move's fit with their traits and archetype, the topic, their mood and one draw; it moves warmth and trust
  exactly and opens them up. Asking about something deeper than they share yet is answered by them steering
  elsewhere: a flat moment, never a refusal. The evening ends by a closer (call it a night, with a promise to
  text in the morning or a plan to do it again; another round; go on somewhere else; walk them home; back to
  yours or theirs, once they would) or by them (spent, two missteps, or their day); it bands great to bad, a
  good one counts toward dating, friends or something casual, fine or better swaps numbers, and their text
  follows. At the flat you can cook, eat or watch something together. relationships.yaml's `meets:` keeps only
  `post_meet` and the band words; scenes.yaml's values are first values, unmeasured until the balance pass at the end of v0.24.0 (T29b).
- Life outside the phone (v0.23.0 T11, spec §8.2-§8.5, §14.4): the world is
  played. Put the phone down (the phone's "Put the phone down") and the flat,
  the building and the city come forward as an ordinary narrated turn; any
  phone action picks the phone back up, and while it is up a world choice is
  answered "Put the phone down first." (`played_on_the_phone`'s "Read
  Receipts is played on the phone." is gone). Things to do
  (`data/world/activities.yaml`): make dinner or breakfast, eat, shower and
  get ready, tidy up, watch something, read, sleep (in the bedroom, to the
  morning; never gated), go to work (from the hall, until your work band
  ends: at work you carry on or leave early, and the phone still works),
  collect a parcel, step outside. A long one stops when your phone buzzes
  ("Your phone buzzes: Kai") and "Carry on" resumes it to where it was to
  end; asleep, only a promise or a late-night person's message wakes you,
  and only with "wake me for messages" on. Going out (`go`): the venues,
  ranked by the hobbies you share with each, at most eight, and "Head home"
  first from anywhere outside the flat; the travel takes the place's minutes.
  The phone's Places app lists every venue (the payload's `places` section)
  and going from it puts the phone down. Every arrival is a quiet visit until
  plans land (T12). The narrator (`prompts/storyteller.md`, rewritten)
  narrates your life away from the screen, told where you are and how many
  times the phone has buzzed and whose names -- never a word of a message --
  through the `SocialWorld` directive (`settings.governance.directives:
  [StorytellerMind, SocialWorld]`). The opening offers "Pick up your phone",
  "Tidy up a bit" (`do tidy_up`) and "Look around the flat" (T10's "Go
  through to the hall" is gone). `paths.decks` names `data/scenes/`, empty
  until the life-event decks (T17). Manifest version 0.2.0.
- Places (v0.23.0 T10, spec §8.1, §10.5): the world is 28 locations, not one.
  Your flat (lounge, bedroom, kitchen, dining room, hall) and the building
  (lift, lobby) are one minute apart by door, the street is a minute from the
  lobby, and the 15 meet-up venues, the cast's four homes (a studio flat on
  the harbour, a shared terrace house, a house in Westcliff, a loft in the
  Quays) and the registry office are places you will `go` to. You start in
  the lounge (`apt_lounge`; a v0.22 save's `home` loads there). Every person
  is drawn one home, fixed, by neighbourhood and age, and it is in who-they-are
  to the voice. `venues.yaml` rows gain `travel_minutes`; `homes.yaml` is filled;
  `data/art/subjects.yaml` is a skeleton (one `base:` daypart per location, no
  plates yet). Since T11 the places are reached by `go` (below).
- One narration at a time (v0.23.0 T8, spec §20.1): replies are now voiced
  one person at a time, and a world turn of yours always goes first -- it
  waits for at most the one reply being written, and the others follow
  after it, never dropped. A reply in a conversation that is still going is
  never left unanswered: if the model server stays busy past the retries,
  or the pass runs out of time, the person's templated line is sent instead.
- They offer their number (v0.23.0 T5, spec §15.2): on reaching `everyday`
  (telling you about their days) a person offers you their number -- at
  once in a conversation, else when they are next free -- at their
  archetype's `offer_number_prob`; your yes swaps numbers as an offer always
  did. `prompts/texter.md`'s `offer_number` row is the engine's own situation
  now.
- The phone's `hints` (v0.23.0 T5): per person, whether they are "getting
  closer" (`growth.yaml` `closer_soon_at`, a yes or no, never a number),
  what you know of their days once they have told you ("Usually at work
  till 7pm") and whether their number is on the table, with the reason in
  words. Drawn by the client.
- Four data skeletons under `data/social/`: `plans.yaml`, `scenes.yaml`,
  `life_events.yaml` and `homes.yaml`, each a header naming its spec section
  and empty top keys. They load, and nothing reads them yet
  (`conversation.yaml` is filled since T3, `promises.yaml` since T4).
- Promises and sign-offs (v0.23.0 T4). "Talk later" in a conversation
  sends your line ("Talk later — I'll message you tonight", or "Message
  me in the morning?") and records the promise; their reply says goodbye.
  They make promises too, when they sign off ("text you after work"), as
  often as their archetype's `promise_prob` says (a breadcrumber never),
  and with no model running a promise you type ("message me at work",
  "I'll text you in the morning") is caught by `promises.yaml`'s phrases.
  Theirs are always kept: their message lands inside the window (kept
  once it is written; void if they leave first), and
  "message me at work" lands in YOUR work band. Yours are tracked: a
  message to them inside the window keeps it (a little trust and
  openness), silence an hour past it breaks it (trust and warmth lost, and
  they mention it next time). Nobody ghosts you while they owe you a
  message. `wait` can jump to a promise ("Wait for <name>"), and "Wait
  until someone writes" stops at one. New `data/social/promises.yaml` (was
  a skeleton): the reach (48 hours), the grace (60 minutes), the kept and
  broken costs, the phrases and how each window reads; a window someone
  does not have reads truthfully ("after work, so tomorrow morning").
  `relationships.yaml` gains the `promise` proposal (only while a
  conversation is winding down).
- `conversation.yaml`: how long they are gone after signing off depends on
  why (`talk.away_after_sign_off`): at least until their schedule changes
  when that was the reason, two hours after a glance at work or when they
  are flagging, an hour when it was simply a good place to stop, and not at
  all when you were the one who said goodbye. Two more reasons: a glance at
  work and your own sign-off. First values, moved by no T9 measurement.
- Growth (v0.23.0 T2): each person opens up at their own pace.
  `data/social/growth.yaml` sets the five disclosure rungs' warmth and
  trust floors and play counts (small talk, everyday, personal stories,
  hopes and fears, family and the future), the openness each measured event
  gives or takes, the pace's jitter and its trait multipliers;
  `topics.yaml` holds 54 topics across the 22 disclosure kinds (each person
  draws one per kind) and `layers.yaml` 58 facts a person reveals as they
  step up a rung. Each archetype in `behaviours.yaml` gains `growth: {pace,
  cap, cap_in_person, decay_mult}`: romantic 1.4, needy 1.3, breadcrumber
  0.8 (never past everyday), slow burner 0.6, dry texter 0.5 (never past
  personal stories on the phone, hopes and fears in person), a ghoster's
  losses doubled. The conversation moves openness since T3 (each reply, a
  good sign-off, a spell left on read); scenes (T13) will too.

### Changed

- Task 23B (v0.23.0): typing in the world. The world layer has core's compose box (an input, the mic and Send) under the choices, at home and at every place: the line goes to the narrator as typed text and echoes into the log. It is greyed (read-only, "Put the phone down to act") while the phone is up or the controls are off, and `/` focuses it while the world is forward. The app hands a story's own play screen `onCustom`; no other story has one. The layout check gates the box at all four sizes. The committed `dist` is rebuilt.
- Task 23A (v0.23.0): the world's choices stay correct across phone actions. A phone action's row is now the frame: pressing it after a narrated turn runs rather than being refused as no longer on offer, and a refresh restores it. A glance at the phone that changes nothing keeps the narrator's choices; a time jump, a move or a scene opening rebuilds them. The row reaches the flat's rooms (Hall, Dining room and the rest), and a scene a phone action opens is said ("Kai is here.").
- Task 21 (v0.23.0): the client's two layers. The play screen is the WORLD (the scene plate, the narration, the narrator's choices, the buzz banner of count and names) and the PHONE, side by side at 1200px wide and over, the phone covering the dimmed world under it. A new game opens with the phone up, so the first frame offers "Put the phone down" (the `put_down` action) and the world's choices show "Put the phone down to act"; a world choice the server refuses with a 409 `phone_up` raises the phone and tells the refusal. The payload gains `phone.world` (`phone_up`, `at_work`, `location`, `buzz`). The story's `PlayScreen` is given `onChoose`.
- `relationships.yaml`'s `meeting` stage carries no gate (v0.23.0 T18): v0.22's warmth 70 and trust 70 were read by
  nothing once a meet-up's end moved swapped numbers to "Seeing each other".
- Plans (v0.23.0 T12): their `ask_meet` follows the `meet` willingness (no `gate:`
  in relationships.yaml), not the old 70/70 stage gate; either side's ask for `now` or `tonight` turns an open
  `soon` plan into that plan; a plan they proposed draws no flake when accepted; "not running late" and "I'm
  late for work" no longer extend a plan.
- Plans have no set time (v0.23.0 T12, spec §9): a meet-up is a plan with a
  kind, a venue and a time of day in words -- `now`, `tonight` or `soon` --
  and no slot or day. The `ask {what: meet}` carries them (`kind?`, `venue?`,
  `when`); the person answers at their read, by the `meet` commitment and by
  whether they have the time (`now` needs two free hours, `tonight` their
  evening), and the engine picks the venue by kind and shared hobbies when
  you name none. Arriving (`go`) within `plans.yaml` `patience_hours` (1.5
  hours for `now`, 4 for `tonight`) keeps it; arriving after, or never, costs
  the stood-up regard (warmth -8, trust -6, interest -6) and they message you
  about it; a "running late" text buys half an hour once; a `soon` plan
  lapses after six of their conversations, never days; they may cancel
  (3-10% by stage, plus their archetype's own) and tell you so, and they may
  ask you out for the evening themselves (`invite`, `texter.md`'s new row).
  Arriving opens the evening itself since T13 (Added, above). Removed: `propose_meet`, the `meet` verb, the slot
  grid (`meets.slots`, `days_ahead`, `cancel_cost`, `no_show`), the no-show,
  the Calendar section; `meet_claims` keeps only `any`, folding in the old
  "see you tonight" and "see you tomorrow" phrases, read by the new
  `plan_claimed` check.
- Measured, phone only (v0.23.0 T9, `scripts/simulate_social.py` v2: 10
  seeds x 6 sessions of 40 real minutes, attentive with the flaky player
  beside it, neutral model, at 6, 15 and 30 model seconds a reply; after the
  fixes below). Three rows hold their band at all three latencies and are
  banded (ghosting at depth 0, the fast tercile's real minutes to a number,
  the attentive player's own promises), and every promise of theirs is kept
  (asserted); the rest miss at one latency or more and are deferred by data
  to the full sessions of T29b, at the end of v0.24.0 (CLAUDE.md), nothing retuned or widened:
  | Row (band) | 6 s | 15 s | 30 s |
  |---|---|---|---|
  | `exchanges_per_episode.d0` (6-14) | 6.0 | 6.0 | 5.0 |
  | `end_reason.schedule` (30-55%) | 20.9% | 18.6% | 19.2% |
  | `end_reason.energy` (25-50%) | 11.0% | 9.0% | 8.9% |
  | `end_reason.player` (10-30%) | 26.5% | 32.3% | 35.4% |
  | `cold_unanswered_1h.d0` (15-35%) | 65.1% | 63.7% | 61.3% |
  | `ghosted_per_episode.d0` (5-15%) | 5.6% | 5.7% | 6.4% |
  | `chat_minutes_to_numbers.fast` (6-15) | 11.0 | 13.65 | 14.75 |
  | `chat_minutes_to_numbers.mid` (12-30) | 11.43 | 14.45 | 17.68 |
  | `chat_minutes_to_numbers.slow` (25-60) | 14.25 | 17.95 | 25.3 |
  | `numbers_within_session` (40-70%) | 13.8% | 8.7% | 6.8% |
  | `person_promises_kept` (100%, asserted) | 1.0 | 1.0 | 1.0 |
  | `player_promises_kept.attentive` (95% or more) | 1.0 | 1.0 | 1.0 |
  | `player_promises_kept.flaky` (55-75%) | 74.5% | 75.9% | 74.4% |
  | `full_replies_in_long_episodes` (60% or more) | 53.9% | 52.9% | 53.1% |
  | `ratio.chat` (derived) | 1.55 | 1.263 | 0.967 |
  Also measured (unbanded): a conversation at the `everyday` rung runs 6-9
  exchanges; 28-29% of conversation starts leave you on read and 3.5-4.1%
  ghost; window initiations come 0.013-0.015 a day per person talking; photos
  0.11-0.17 a relationship-week; a romantic reaches warming in about 1.7
  in-game days (0.23-0.30 real hours of your time), a steady in 2.1-3.1.
- "Wait until someone writes" no longer waits past a reply:
  it also stops when they read a message of yours that is still waiting for
  an answer, which is when their reply is decided -- before, it ran on to the
  next notification or its 8-hour cap.
  Only a read you can see stops it: a receipt on a thread you
  can see; a read on an app with no receipts, or with your receipts off, is run
  past.
- A promise made inside its own window is for that window's NEXT time (T9 fix
  round 1): "message you at lunch" said at lunch means tomorrow's lunch. Before,
  someone glancing at their phone at work during lunch promised the lunch they
  were in, wrote at once, glanced off again and promised again, over and over.
- A long run's save stays small: a save keeps the
  conversation going on, what you have not read yet and one screen of the
  thread you have open; the rest of each conversation lives in the run's
  archive and the thread still pages back through it ("Load earlier"), and
  opening a quiet thread shows its last screen from there.
- A save no longer changes what a person says next: the voice
  reads a conversation's recent messages through the run's archive when a save
  has moved them out of the save, so two identical runs, saved at different
  moments, build the same prompt. `promises.yaml`'s `closed_kept` is required
  (docs/AUTHORING.md).
- Old promises are forgotten: a save keeps each person's open
  promises and their three newest closed ones (`promises.yaml`'s new
  `closed_kept`), plus any the next reply, a recap or the phone's list still
  needs; the rest are counted on the person.
- Fuller replies cost wait time, so the voice is held back (spec §20.2's
  latency levers, applied by T9's probe at an assumed 20 tokens a second;
  docs/MODEL_SERVERS.md § The texter's latency): a conversation is `quick`
  until its fifth exchange (`conversation.yaml` `modes.chatting_after` 5,
  was 3), and a `deep` reply is voiced with `chatting`'s caps (the new
  `modes.deep_as_chatting: true`); the voice prompt's window is 6144 tokens
  (config `social.voice.window_tokens`, was 8192).
- The voice, reworked (v0.23.0 T7, the owner's "short replies, only the last
  message, gets old after two messages"): `prompts/texter.md` is rewritten.
  The persona no longer says most texts are short; it says to match where
  the conversation is -- quick while it is getting going or you are busy, a
  real conversation once it is going, picking up things said earlier.
  Each reply runs quick (1-2 bubbles), chatting (up to 4, longer) or deep
  (up to 3, longest), from `conversation.yaml`'s `modes.caps`. The voice is
  given who they are now (their bio only at small talk, what they talk
  about with you now and what they still keep to themselves), your story
  together and the recaps, what is still open between you (promises and
  follow-ups), what they would be up for now, and how your last
  conversation ended. `## Instructions` gains `winding` and `sign_off` (with
  the engine's reason), `promised_message`, `followup`, `news`, `opens_up`,
  `stood_up` and `flake`; `good_morning`, `check_in`, `late_night` and
  `reveal_turn` are retired (the turner's reveal is voiced as `opens_up`
  now, `behaviours.yaml`). `## Fallbacks` gains `reasons:` (why a
  conversation ends, in their own words) and `any:` (every situation by
  mode, three lines or more each, some templated: "Got to go — {reason}.
  {promise_words}"). A reply may ask to follow something up later (at most
  two) and, while winding down, promise when it will message you; when it
  opens up about the layer queued at their last step, that layer is
  revealed. `relationships.yaml`'s `claims:` gains `promise` and
  `commitment` phrase tables: a reply promising a time other than the one
  the engine holds, or stating a step ("let's move in", "will you marry
  me") the two of you are not ready for, is caught. A promise they make in
  the middle of a chat ("I'll text you in the morning") is kept like any
  other; a reply says for itself whether it asked about a follow-up and
  whether it opened up; the commitment phrases are the ones said to you, so
  news about someone else's ("my brother wants to move in with me") passes.
  Follow-ups are worded from their side ("How did your interview go?"),
  and the decline lines give a reason of the moment.
- People remember the whole history, across apps (v0.23.0 T6, the owner's
  "only the last message"): memory is per person, not per thread, so moving
  from Matchstick to Texts or Natter keeps the conversation, and each
  conversation that ends is recapped into what they remember of you (twelve
  recaps, then a story so far). `prompts/thread_summary.md` is replaced by
  `prompts/episode_recap.md` (the recap and the story's prompts);
  `conversation.yaml` gains `reasons_recap:` (the recap's words for why a
  conversation ended, when no model writes it); `relationships.yaml`'s
  `proposals:` gains `followups` (a reply's "ask me how it went", at most two,
  a reply carries them since T7). A promise you break leaves them a follow-up to raise.
- Willingness (v0.23.0 T5): what each person is willing to do now --
  give you their number, meet, have you over, stay over, be exclusive, meet
  the family, move in, marry, stay for you -- is `data/social/growth.yaml`'s
  `willing:` table (spec §6.5's first values): a stage, warmth and trust,
  conversations and scenes together, what you both want, and for their
  number and a meet-up only, how far they have opened up. Swapping numbers
  needs them past small talk (depth 1, one conversation and their openness
  full) and warmth 25; being exclusive needs dating, warmth 70, trust 65,
  four scenes and both after something long-term (the 28 days at dating are
  gone). `relationships.yaml`'s `numbers` and `exclusive` gates are now
  `{willing: number}` and `{willing: exclusive}`; v0.22.0's numbers gate
  (warmth 30, trust 23, 20 exchanges) is replaced. A no below the gate is
  `not_yet` (was "not yet"), and a no can now also say `needs` (you want
  different things) or `household`.
- Every cap counts conversations, not days (v0.23.0 T5, spec §6.4):
  `relationships.yaml` `regard.per_day_gain` is `per_episode_gain` (6/4),
  `regard.fallback.per_day` is `per_episode` (3/2) and `asks.per_day` is
  `asks.per_episode` (2; the third ask in a conversation is refused "Give
  it a while", was "Give it a day"); `media.yaml` `budget.*.per_day` is
  `per_episode` (added as each conversation closes) and
  `unsolicited.per_day_at_stage` is `per_episode_at_stage` (drawn as each
  conversation closes, one sent at most, at their next free minute). Each
  allowance resets when a conversation opens and again when it closes. A
  fight and a making-up are still a day's. `relationships.yaml` gains
  `wedding_after_days: 14` (read from T18).
- Replies are instant inside a conversation; time moves only by what you
  do (v0.23.0 T3). A conversation is an episode: while it is going, their
  reply is due at the minute you sent yours, with no wait; it ends at a
  natural point, nudged by how long they like to talk, their energy and
  their next schedule change ("your shift starts at 9", "lunch is over"),
  never by a fixed gap, and lapses after 45 minutes of quiet. Someone
  asleep, or at work and not a texter there, reads you when they are next
  free. Ghosting, leaving you on read and answering at all are decided once
  per conversation, never mid-sentence. New `data/social/conversation.yaml`
  (was a skeleton): message costs (a text 1 minute, a voice note 2, a reply
  nothing), `wait`'s evening (18:00) and morning (07:00), the 45-minute gap,
  each archetype's phone habits (at work: never, glances or chatty; late at
  night: no, sometimes or a night owl), the episode lengths per archetype
  and their nudges, the reply modes (quick, chatting, deep) and their caps,
  the per-conversation reply and ghost terms, and the engine's reasons for
  winding down. First values, first measured by T9's phone-only simulator
  (above).
- `data/social/behaviours.yaml`: `ghost_per_exchange` is `ghost_per_episode`
  (the chance when a conversation starts); `read_minutes` and the `pacing:`
  block are gone (the reply and ghost terms are `conversation.yaml`'s
  `reply:`); each initiation names a `window` of the person's own day
  (waking, lunch, after work, evening, late) and five chances by depth in
  place of fixed hours and a daily chance, worded as `window_message`; each
  archetype gains `promise_prob` and `offer_number_prob` (read from T4 and
  T5). Every initiation is now drawn each morning: v0.22.0's `prob`
  rows were drawn once per spell of your silence, so the needy archetype's
  `did_i_do_something` (0.2 a morning at depth 0-1) now comes about every
  five days of silence rather than at most once a spell (T9 measured 0.007-0.045
  window initiations a day per person talking, phone only).
- A conversation ends only where they become LESS available: their shift
  starting (unless they text at work), going out, bed. Coming off work or
  coming home is no reason to sign off.
- Left on read, they stay quiet: another message is read at their next
  schedule change or after `conversation.yaml`'s new
  `left_on_read_quiet_minutes` (60; T9 measured a quarter of conversation
  starts left on read, the hold itself unbanded), whichever is first, so
  sending again does not re-roll whether they answer.
- `data/social/apps.yaml`: no app prices a message any more (the text,
  photo, voice and video rows went to `conversation.yaml`); a swipe, a like,
  a profile edit and a game move keep theirs.
- `wait` is labelled "Wait" and waits until someone writes, an hour, the
  evening or the morning; "15 minutes" went with "Let time pass", which the
  client no longer offers.
- Coming back no longer moves the clock: `social.away.mode` defaults to
  `none` (config), so you pick up at the same in-game minute.
- `prompts/texter.md` gains a `window_message` instruction (a first wording;
  T7 reworks the table).
- The state slice moves to schema 2 (v0.23.0 T1): a new run's phone slice
  carries the rework's keys (promises, plans, the open scene, the
  household, phone up and at work) and no `auto_wait` setting. Nothing
  fills them yet.
- `data/social/relationships.yaml` lists three more stages after
  `exclusive`, words only: `living_together` ("Living together"),
  `engaged` ("Engaged") and `married` ("Married"). No gate reaches them
  yet.

### Fixed

- Swapping numbers now follows the conversation, not the calendar (v0.23.0
  T5, the owner's "phone numbers don't work"): no gate or cap reads in-game
  days, so a number is reachable in one sitting.

### Removed

- The client's "Let time pass" (the Settings row, its idle timer and `settings/letTimePass.js`), the v0.22 meet-up planner (`contact/PlanMeet.jsx`: a venue, a day and a slot, `propose_meet`), the thread's meet-up card (`MeetCard`, `meet {do}`) and a counter-offer's Accept button, and the client's reading of `auto_wait` (v0.23.0 T22, pre-flight F4). `tests/test_social_removed.py::test_the_removed_client_names_are_gone` is no longer skipped.
- v0.22.0's meet-up recap card (v0.23.0 T19): `prompts/date_recap.md` and `relationships.yaml` `meets.recap_tone`
  are gone. An evening is recapped like any conversation (`prompts/episode_recap.md`); a v0.22.0 save's due recap
  card is voiced by nothing and the migration drops it at load (T20). `meets:` keeps `post_meet` and `recap_lines`.
- The names v0.23.0 retired from the server and the data, scanned for by `tests/test_social_removed.py`:
  `schedule_reply`, `_reply_minutes`, `_status_mult`, `_burst_factor`, `slot_start`, `days_ahead`, `propose_meet`,
  `meet_start`, `auto_wait` (the payload's `phone.auto_wait` too: the client's "Let time pass" too),
  `summarize_thread`, `SOCIAL_MEET`, `played_on_the_phone`, `ghost_per_exchange`, `per_day_gain`.

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
