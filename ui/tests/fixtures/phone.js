// ui/tests/fixtures/phone.js -- one READ RECEIPTS `phone` block, shaped exactly as the server sends it
// (v0.22.0 T27). RECORDED ONCE BY HAND, never fetched by a test: a local run with no model
// (scripts/screenshot_runs.py's pinned config, seed 1021, the fallback voice), its
// `POST /api/phone/action` answer's `state.phone` after a few Matchstick likes, a sent text, three
// `wait {until: next}` and `open_thread`, copied here whole. The one edit: the Matchstick card's pid
// is p0004, the id the deck tests name. T28 added what the payload gained then: each app's
// `capabilities` and the player's `camera_roll` and `subjects` (engine/social/payload.py). T29 added
// the sections the payload gained then, written by hand in the engine's shapes: `contacts` (Cole's row,
// engine/social/relationships.py), `gallery` (empty), `meet_options` (two venues, the plan kinds and whens; v0.23.0 T22 dropped the v0.22 days and slots) and
// `settings`; v0.23.0 T21 added the sections the payload gained then, in the shapes engine/social/world.py and
// scene.py send: `places` ({venues: [{id, label}]}), `scene` ({} when none is open) and `world` ({phone_up,
// at_work, location, buzz: {count, who}}); v0.23.0 T22 added `hints`, `plans` and `promises` (empty; the shapes engine/social/payload.py,
// plans.py and promises.py send), `settings.wake_for_messages`, and dropped `calendar` and the v0.22 offer
// of a timer the payload no longer makes.
// The v0.22.0 final review's second wave added each thread row's `asks` (engine/social/messaging.py
// `ready_asks`): every row here is "Just matched", so none is offered an ask yet.
//
// `phoneFixture(overrides)` returns a fresh deep copy:
//   superLeft, likesLeft  Matchstick's `supers_left` / `likes_left`
//   hidden                keys spread onto BOTH decks' cards, every thread row, every "Likes you" row,
//                         every notification and every open-thread message (and, T28, every request,
//                         game and meet-up row and message media row `phone` brings; T29: every contact and its
//                         history rows, and every gallery row) -- keys the real payload
//                         never carries (warmth, interest, ...), so a test proves the components render
//                         only the fields they name (pre-flight F19)
//   phone                 any top-level keys of the block, replaced

const RECORDED = {
  "apps": [
    {
      "badge": 2,
      "capabilities": ["text"],
      "id": "matchstick",
      "kind": "dating",
      "label": "Matchstick"
    },
    {
      "badge": 0,
      "capabilities": ["text", "voice"],
      "id": "front_porch",
      "kind": "dating",
      "label": "Front Porch"
    },
    {
      "badge": 0,
      "capabilities": ["text", "photo"],
      "id": "texts",
      "kind": "messenger",
      "label": "Texts"
    },
    {
      "badge": 0,
      "capabilities": ["text", "photo", "voice", "video"],
      "id": "natter",
      "kind": "messenger",
      "label": "Natter"
    },
    {
      "badge": 0,
      "capabilities": [],
      "id": "games",
      "kind": "games",
      "label": "Games"
    },
    {
      "badge": 0,
      "capabilities": [],
      "id": "photos",
      "kind": "gallery",
      "label": "Photos"
    },
    {
      "badge": 0,
      "capabilities": [],
      "id": "calendar",
      "kind": "calendar",
      "label": "Calendar"
    },
    {
      "badge": 0,
      "capabilities": [],
      "id": "contacts",
      "kind": "contacts",
      "label": "Contacts"
    },
    {
      "badge": 0,
      "capabilities": [],
      "id": "settings",
      "kind": "settings",
      "label": "Settings"
    }
  ],
  "contacts": [
    {
      "about": ["I'm a terrible cook but a great washer-upper"],
      "app": "matchstick",
      "app_label": "Matchstick",
      "avatar_url": "",
      "band": "new",
      "history": [
        {"at": 21.25, "day": 1, "text": "Matched on Matchstick"},
        {"at": 23.602455789852776, "day": 1, "text": "First message"}
      ],
      "last_heard_days": 0,
      "matched": true,
      "matched_on": "Matchstick",
      "name": "Cole",
      "open": true,
      "photos": [
        {"caption": "laughing at a pub table", "id": "photo_0"},
        {"caption": "on a beach at sunset", "id": "photo_1"}
      ],
      "pid": "p0347",
      "profile": {
        "age": 31,
        "also_on": [],
        "bio": "here for the pub quiz, staying for the chips",
        "hobbies": ["Pub quizzes", "Football"],
        "job": "Electrician",
        "name": "Cole",
        "neighbourhood": "The Quays"
      },
      "stage_words": "Just matched",
      "thread_ids": ["matchstick:p0347"]
    }
  ],
  "deck": {
    "front_porch": {
      "app": "front_porch",
      "card": {
        "age": 33,
        "also_on": [],
        "avatar_url": "",
        "bio": "☕ + sea swimming = perfect day",
        "hobbies": [
          "Sea swimming",
          "Cooking",
          "Yoga",
          "Painting"
        ],
        "job": "Paralegal",
        "name": "Ned",
        "neighbourhood": "Castle Hill",
        "photos": [
          {
            "caption": "a group shot on a night out",
            "id": "photo_0"
          },
          {
            "caption": "halfway up a climbing wall",
            "id": "photo_1"
          }
        ],
        "pid": "p1859",
        "prompts": [
          {
            "a": "Clean sheets.",
            "id": "prompt_0",
            "q": "My simple pleasures"
          },
          {
            "a": "Anyone who seasons as they go.",
            "id": "prompt_1",
            "q": "I'm weirdly attracted to"
          },
          {
            "a": "Work as a paralegal, cook something, call it a night.",
            "id": "prompt_2",
            "q": "Typical weeknight"
          }
        ],
        "shared": ""
      },
      "deck": "browse",
      "likes_left": 8,
      "supers_left": 0
    },
    "matchstick": {
      "app": "matchstick",
      "card": {
        "age": 28,
        "also_on": [],
        "avatar_url": "",
        "bio": "mechanic 💼 but mostly eating out ✨",
        "hobbies": [
          "Eating out",
          "Chess",
          "Live music"
        ],
        "job": "Mechanic",
        "name": "Sami",
        "neighbourhood": "Harbourside",
        "photos": [
          {
            "caption": "halfway up a climbing wall",
            "id": "photo_0"
          },
          {
            "caption": "laughing at a pub table",
            "id": "photo_1"
          }
        ],
        "pid": "p0004"
      },
      "deck": "swipe",
      "likes_left": 60,
      "supers_left": 1
    }
  },
  "gallery": [],
  "games": [],
  "hints": {},
  "plans": [],
  "promises": [],
  "meet_options": {
    "kinds": ["coffee", "drinks", "dinner", "walk", "visit", "film", "climbing", "games", "gig", "their_place", "your_place"],
    "whens": ["now", "tonight", "soon"],
    "venues": [
      {"id": "copper_kettle", "label": "The Copper Kettle", "neighbourhood": "Old Town", "place": "Coffee at The Copper Kettle"},
      {"id": "the_anchor", "label": "The Anchor", "neighbourhood": "The Quays", "place": "Drinks at The Anchor"}
    ]
  },
  "likes_you": [
    {
      "age": 28,
      "app": "front_porch",
      "at": 38.56565850714553,
      "comment": "ok ur profile made me laugh",
      "name": "Hugo",
      "pid": "p1988"
    }
  ],
  "notifications": [
    {
      "app": "matchstick",
      "at": 31.062878742028026,
      "id": "n1",
      "kind": "text",
      "name": "Cole",
      "pid": "p0347",
      "preview": "okay I really like talking to you",
      "thread_id": "matchstick:p0347"
    },
    {
      "app": "matchstick",
      "at": 32.0,
      "id": "n2",
      "kind": "text",
      "name": "Yusuf",
      "pid": "p1190",
      "preview": "hello! I had to say hi",
      "thread_id": "matchstick:p1190"
    },
    {
      "app": "matchstick",
      "at": 32.562878742028026,
      "id": "n3",
      "kind": "text",
      "name": "Cole",
      "pid": "p0347",
      "preview": "sorry, didn't mean to spam you",
      "thread_id": "matchstick:p0347"
    },
    {
      "app": "matchstick",
      "at": 36.0,
      "id": "n4",
      "kind": "text",
      "name": "Yusuf",
      "pid": "p1190",
      "preview": "that made me smile",
      "thread_id": "matchstick:p1190"
    }
  ],
  "now": {
    "day": 2,
    "hour": 17,
    "minute": 41,
    "weekday": "Tue"
  },
  "open_thread": {
    "app": "matchstick",
    "messages": [
      {
        "at": 23.602455789852776,
        "bubbles": [
          "hey! how is your week going?"
        ],
        "from": "player",
        "id": "m1",
        "kind": "text",
        "media_id": null,
        "pending": false,
        "read_at": null,
        "transcript": null
      },
      {
        "at": 31.062878742028026,
        "bubbles": [
          "okay I really like talking to you"
        ],
        "from": "p0347",
        "id": "m2",
        "kind": "text",
        "media_id": null,
        "pending": false,
        "transcript": null
      },
      {
        "at": 32.562878742028026,
        "bubbles": [
          "sorry, didn't mean to spam you"
        ],
        "from": "p0347",
        "id": "m4",
        "kind": "text",
        "media_id": null,
        "pending": false,
        "transcript": null
      }
    ],
    "more": false,
    "name": "Cole",
    "open": true,
    "pid": "p0347",
    "thread_id": "matchstick:p0347",
    "typing": false
  },
  "player": {
    "age": 29,
    "attributes": {
      "build": "average",
      "drinks": "often",
      "hair": "braids",
      "height": "tall",
      "job": "hairdresser",
      "kids": "unsure",
      "smokes": "sometimes",
      "style": "alternative"
    },
    "discovery": {
      "age_max": 38,
      "age_min": 25,
      "distance": "city"
    },
    "hobbies": [
      "pub_quizzes",
      "gigs"
    ],
    "looking_for": "unsure",
    "name": "Robin",
    "personality": {
      "adventurous": 3,
      "homebody": 3,
      "outgoing": 3,
      "playful": 3,
      "romantic": 3
    },
    "photos": [
      "climbing_wall"
    ],
    "camera_roll": [
      {
        "id": "climbing_wall",
        "label": "halfway up a climbing wall"
      }
    ],
    "subjects": [
      {"id": "my_coffee", "kinds": ["photo", "video"], "label": "my coffee"},
      {"id": "my_view", "kinds": ["photo", "video"], "label": "the view from my window"},
      {"id": "my_dinner", "kinds": ["photo"], "label": "what I'm cooking"},
      {"id": "my_walk", "kinds": ["photo", "video"], "label": "my walk"}
    ],
    "sex": "female"
  },
  "refusal": null,
  "requests": [],
  "places": {"venues": [{"id": "the_corner_cafe", "label": "The Corner Cafe"}, {"id": "river_walk", "label": "River Walk"}]},
  "scene": {},
  "world": {"phone_up": true, "at_work": false, "location": "Your flat", "buzz": {"count": 0, "who": []}, "household": {}},
  "settings": {"bio_max": 600, "receipts": true, "wake_for_messages": false},
  "threads": [
    {
      "app": "matchstick",
      "asks": [],
      "avatar_url": "",
      "band": "new",
      "last": {
        "at": 36.0,
        "from": "p1190",
        "kind": "text",
        "pending": false,
        "preview": "that made me smile"
      },
      "name": "Yusuf",
      "open": true,
      "pid": "p1190",
      "read_state": "",
      "stage_words": "Just matched",
      "thread_id": "matchstick:p1190",
      "typing": false,
      "unread": 2
    },
    {
      "app": "matchstick",
      "asks": [],
      "avatar_url": "",
      "band": "new",
      "last": {
        "at": 32.562878742028026,
        "from": "p0347",
        "kind": "text",
        "pending": false,
        "preview": "sorry, didn't mean to spam you"
      },
      "name": "Cole",
      "open": true,
      "pid": "p0347",
      "read_state": "",
      "stage_words": "Just matched",
      "thread_id": "matchstick:p0347",
      "typing": false,
      "unread": 0
    },
    {
      "app": "matchstick",
      "asks": [],
      "avatar_url": "",
      "band": "new",
      "last": null,
      "name": "Dylan",
      "open": true,
      "pid": "p1527",
      "read_state": "",
      "stage_words": "Just matched",
      "thread_id": "matchstick:p1527",
      "typing": false,
      "unread": 0
    }
  ]
};

export function phoneFixture({ superLeft, likesLeft, hidden, phone = {} } = {}) {
  const block = JSON.parse(JSON.stringify(RECORDED));
  const stick = block.deck.matchstick;
  if (superLeft !== undefined) stick.supers_left = superLeft;
  if (likesLeft !== undefined) stick.likes_left = likesLeft;
  const out = { ...block, ...phone };
  return hidden ? plantHidden(out, hidden) : out;
}

/**
 * `hidden`'s keys spread onto every row a phone block's screens draw (in place; the block is returned):
 * both decks' cards, thread rows, "Likes you" rows, notifications, open-thread messages and their media
 * rows, (T28) requests, games and meet-ups, and (T29) contacts with their history and profile, and the
 * gallery's rows.
 */
export function plantHidden(block, hidden) {
  for (const app of Object.values(block.deck || {})) {
    if (app && app.card) Object.assign(app.card, hidden);
  }
  const rows = [
    ...(block.threads || []), ...(block.likes_you || []), ...(block.notifications || []),
    ...(block.requests || []), ...(block.games || []), ...(block.plans || []), ...(block.promises || []),
    ...(block.open_thread?.messages || []), ...(block.contacts || []), ...(block.gallery || []),
    ...(block.contacts || []).flatMap((c) => c.history || []),
  ];
  for (const row of rows) Object.assign(row, hidden);
  for (const m of block.open_thread?.messages || []) if (m.media) Object.assign(m.media, hidden);
  for (const c of block.contacts || []) if (c.profile) Object.assign(c.profile, hidden);
  return block;
}

/** A Tile Talk game row as the payload's `games` section shows it (engine/social/games/wordgame.py `view`). */
export function tileGame({ rack = "caterso", turn = "player", board = null, ...over } = {}) {
  const empty = ".".repeat(11);
  return {
    id: "g1",
    game: "wordgame",
    label: "Tile Talk",
    pid: "p0347",
    name: "Cole",
    status: "active",
    winner: null,
    started_at: 40,
    ended_at: null,
    moves: [],
    board: board || Array.from({ length: 11 }, () => empty),
    premiums: [
      "W..l...l..W", ".w...L...w.", "..l.w.w.l..", "l..L...L..l", "..w.....w..", ".L...*...L.",
      "..w.....w..", "l..L...L..l", "..l.w.w.l..", ".w...L...w.", "W..l...l..W",
    ],
    rack,
    bag_left: 58,
    scores: { player: 0, them: 0 },
    turn,
    ...over,
  };
}

/** A This or That row (engine/social/games/this_or_that.py `view`): unanswered by default. */
export function totGame(over = {}) {
  return {
    id: "g2",
    game: "this_or_that",
    label: "This or That",
    pid: "p0347",
    name: "Cole",
    status: "active",
    winner: null,
    started_at: 40,
    ended_at: null,
    moves: [],
    pairs: [
      { a: "Mountains", b: "Beaches" },
      { a: "Coffee", b: "Tea" },
      { a: "Night in", b: "Night out" },
      { a: "Dogs", b: "Cats" },
      { a: "Sweet", b: "Savoury" },
    ],
    mine: null,
    theirs: null,
    agreements: null,
    turn: "player",
    ...over,
  };
}
