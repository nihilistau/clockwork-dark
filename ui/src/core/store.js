/**
 * Game store — one reducer, one shape.
 *
 * All the state the old client kept in loose module variables (`sessionId`,
 * `busy`, a dangling `streamEntry` node) lives here instead, so a reconnect or
 * a mid-turn error cannot leave the UI in a state nothing knows how to clear.
 *
 * WHAT IS AND IS NOT CORE
 * -----------------------
 * Everything here is turn machinery: the socket lifecycle, the streaming entry,
 * the log, the choices, the raw world payload and the story's declared meters.
 * None of it knows what the world contains.
 *
 * tests/test_narration_control.py parses this file as text for the
 * `turn_update` case -- it asserts the reducer REPLACES a streamed entry with
 * the authoritative narration rather than trusting its own delta buffer, which
 * is the bug that left a rejected half-streamed draft on screen permanently.
 * If this file moves, move that path constant in the same change.
 *
 * A story's own derived state -- the flagship's evil phase and its record of
 * every form the companion has worn -- used to sit in this file as `phase` and
 * `formHistory`, which meant the shared reducer shipped the string "dormant"
 * and a five-faced companion to every story that would ever exist. It now lives
 * under `state.story`, owned entirely by the plugin's `reduce`. Core reads that
 * slice for exactly one thing: handing it back to the plugin.
 */

export const initialState = {
  screen: "start", // start | scene | saves
  connected: false,
  sessionId: "",
  saveId: "",

  log: [], // {id, kind: narration|player|dice|system, text}
  streamingId: null, // log entry currently receiving deltas
  choices: [],
  busy: false,

  world: null, // to_client_dict payload
  // The story's declared state, projected by visibility from its state.yaml:
  // {name: {name, label, kind, value|band, min, max}}. Public values carry a
  // number; VEILED values carry a band string and no number at all, which is
  // the whole point -- see core/parts/Meters.jsx.
  meters: {},
  assistant: null, // {text, form, voice_style, portrait, trust, ...}
  // Presence, not speech: survives a silent turn so the companion column is
  // never blank. assistant.text is the transient line; this is who is there.
  presence: null,
  dice: null, // transient toast
  sceneImage: "",
  cutscene: null,
  audio: "",

  // The turn's fade card, when the safety layer resolved a scene at summary
  // resolution instead of at full detail: {heading, summary, outcomes[],
  // aftercare}, from engine/safety/verdict.py::FadeCard.
  //
  // Deliberately PER-TURN and not sticky, unlike `ending`. A fade belongs to
  // the scene that faded; carrying it forward would leave last scene's card
  // sitting under this scene's narration, which reads as the fade having
  // happened twice. Every turn_update sets it, to the card or to null.
  fadeCard: null,

  // The run is over. `null` for every turn of a running game and for every
  // turn of a story that declares no endings -- the server sends the key only
  // once, on the turn that locked one. Shape is engine/game/epilogue.py's
  // `Epilogue.to_dict()`: {ending_id, title, card_m, card_g, echoes, time_line,
  // gallery_key, ng_plus_seed, order}.
  //
  // Deliberately NOT derived from `world.ended`. That flag is the flagship's
  // terminal death, which is a different thing with no epilogue behind it, and
  // one field meaning two things is how a screen ends up rendering a blank card.
  ending: null,

  // The model thinking out loud, streamed on its own channel. Cleared when
  // narration starts: once there are words the player can read, the machinery
  // behind them stops being the most interesting thing on screen.
  reasoning: "",
  reasoningOpen: false,

  error: "",
  saves: [],

  // The story plugin's slice. Core writes it once, on RESET, and otherwise
  // never touches it.
  story: {},
};

let nextId = 1;
const newId = () => `e${nextId++}`;

function append(state, kind, text) {
  if (!text) return state;
  return { ...state, log: [...state.log, { id: newId(), kind, text }] };
}

/**
 * Close a streaming entry that will never receive its `turn_update`.
 *
 * Three things end a turn without one -- a dropped socket, a client-side ERROR
 * (the watchdog fires at 330s, on turns that are still running), and a server
 * `turn_error`. All three used to null `streamingId` and leave the half-streamed
 * paragraph sitting in the log with nothing owning it. When the real answer then
 * arrived -- a late `turn_update`, a retry, a reconnect replaying the turn --
 * `turn_update` saw no `streamingId`, took its append branch, and printed the
 * SAME PROSE a second time underneath the orphan. That is the F-13 shape, and
 * it is the one path by which this reducer could still render one turn twice.
 *
 * The draft is dropped rather than kept. It is a fragment of a turn that did not
 * complete, the server's narration is authoritative and arrives whole, and
 * keeping a prefix on screen only guarantees the reader meets the same sentences
 * again a paragraph later.
 */
function closeStream(state) {
  if (!state.streamingId) return state;
  return {
    ...state,
    streamingId: null,
    log: state.log.filter((e) => e.id !== state.streamingId),
  };
}

/**
 * Does the log already end on exactly this narration?
 *
 * The belt to `closeStream`'s braces. A `turn_update` can legitimately arrive
 * twice for one turn -- a reconnect replaying the last payload is the shipped
 * case -- and the append branch has no other way to tell a repeat from a new
 * paragraph. Scans back past the player echo and any dice lines, because a
 * replay lands after them.
 */
function repeatsLastNarration(log, text) {
  for (let i = log.length - 1; i >= 0; i -= 1) {
    if (log[i].kind !== "narration") continue;
    return log[i].text === text;
  }
  return false;
}

export function reducer(state, action) {
  switch (action.type) {
    case "CONNECTED":
      return { ...state, connected: true, error: "" };

    case "DISCONNECTED":
      // Clearing busy matters: the old client only cleared it on turn_update
      // or error, so a dropped socket left every control disabled forever.
      return { ...closeStream(state), connected: false, busy: false };

    case "ERROR":
      return { ...closeStream(state), error: action.message, busy: false };

    case "SUBMIT": {
      const next = append(state, "player", action.text);
      return {
        ...next,
        busy: true,
        dice: null,
        // The card belonged to the scene that faded. It sits under the log, so
        // leaving it up while the NEXT turn is in flight would print it beneath
        // a moment it has nothing to do with.
        fadeCard: null,
        error: "",
        // A new turn gets a fresh thinking panel. Keeping last turn's
        // reasoning on screen while this turn deliberates is a lie about what
        // the model is doing right now.
        reasoning: "",
        reasoningOpen: true,
      };
    }

    case "SCREEN":
      return { ...state, screen: action.screen };

    // Leaving a run. Without this the previous run's narrative log, choices,
    // companion and scene still bled straight into the next one -- the old
    // client had no way to leave a run at all, so nothing ever needed it.
    case "RESET":
      return {
        ...initialState,
        connected: state.connected,
        saves: state.saves,
        // The plugin's own reset value, not the previous run's slice.
        story: action.storyInitial ?? {},
      };

    // Client-only: the player collapsing or reopening the thinking panel.
    case "REASONING_TOGGLE":
      return { ...state, reasoningOpen: !state.reasoningOpen };

    case "SAVES":
      return { ...state, saves: action.saves };

    case "SOCKET":
      return handleSocket(state, action.event, action.payload || {});

    default:
      return state;
  }
}

/** The declared-meter block, or the previous one when a payload omits it. */
function metersOf(payload, fallback) {
  const world = payload && payload.state;
  if (world && world.meters) return world.meters;
  return fallback;
}

function handleSocket(state, event, payload) {
  switch (event) {
    case "game_started":
    case "game_resumed": {
      const opening = payload.opening || {};
      let next = {
        ...state,
        screen: "scene",
        sessionId: payload.session_id || state.sessionId,
        saveId: payload.save_id || state.saveId,
        world: payload.state || state.world,
        meters: metersOf(payload, state.meters),
        busy: false,
        error: "",
      };
      if (opening.narration) next = append(next, "narration", opening.narration);
      // `opening.choices || []` and not `if (opening.choices)`: a resume used
      // to arrive with no opening at all, and falling through left whatever
      // stale choices the previous screen had.
      next = { ...next, choices: opening.choices || [] };
      if (opening.scene_image) next = { ...next, sceneImage: opening.scene_image };
      if (opening.assistant) next = { ...next, presence: opening.assistant };
      return next;
    }

    case "reasoning_delta": {
      const text = typeof payload === "string" ? payload : payload.text;
      if (!text) return state;
      // Capped from the front. Reasoning is uncapped and ungrammared upstream;
      // a model that spirals must not grow an unbounded string in the store.
      const joined = (state.reasoning + text).slice(-6000);
      return { ...state, reasoning: joined };
    }

    case "narration_delta": {
      const text = typeof payload === "string" ? payload : payload.text;
      if (!text) return state;
      // One entry per turn, appended to. A new node per chunk would turn every
      // token fragment into its own paragraph.
      if (!state.streamingId) {
        const id = newId();
        return {
          ...state,
          streamingId: id,
          // The thinking panel folds itself away the moment there are words to
          // read. The text is kept, so the player can reopen it.
          reasoningOpen: false,
          log: [...state.log, { id, kind: "narration", text, streaming: true }],
        };
      }
      return {
        ...state,
        log: state.log.map((e) =>
          e.id === state.streamingId ? { ...e, text: e.text + text } : e
        ),
      };
    }

    case "turn_update": {
      // A dead model used to produce the same canned sentence every turn with
      // no signal at all -- indistinguishable from a very boring game.
      const outage = payload.llm_unavailable
        ? "The Storyteller is unreachable — check LM Studio is running and its API key is set."
        : "";
      let next = { ...state, busy: false, error: outage };

      // The server's narration is AUTHORITATIVE; the delta buffer is not.
      //
      // The old code only cleared the `streaming` flag and kept whatever text
      // had accumulated. Three ways that lied to the player:
      //
      //  - The evaluator retry does not stream. On a retried turn the text on
      //    screen is the REJECTED draft and the accepted narration arrives
      //    only here, where it was being thrown away.
      //  - A generation cut off at max_tokens streams a severed sentence; the
      //    server trims it back to its last full stop and sends that.
      //  - A delta lost to a reconnect mid-turn left a hole nothing repaired.
      //
      // Replacing is safe because the server streams exactly the text it later
      // sends: on an ordinary turn this is a no-op.
      if (state.streamingId) {
        const finalText = payload.narration || "";
        next.log = next.log.map((e) =>
          e.id === state.streamingId
            ? { ...e, streaming: false, text: finalText || e.text }
            : e
        );
        // A turn that streamed nothing and resolved to nothing leaves an empty
        // paragraph behind. Drop it rather than render a blank entry.
        next.log = next.log.filter(
          (e) => e.id !== state.streamingId || (e.text && e.text.trim())
        );
        next.streamingId = null;
      } else if (payload.narration && !repeatsLastNarration(next.log, payload.narration)) {
        // Nothing streamed -- a non-streaming turn, or a generation that was
        // starved before it produced a single token. Append it whole. This no
        // longer consults `payload.streamed`: a starved first attempt sets that
        // flag with no entry to attach to, and the turn silently vanished.
        //
        // Guarded so this branch cannot print prose the log already ends on.
        // Between the guard and `closeStream`, no sequence of events reaches a
        // log holding one turn's narration twice.
        next = append(next, "narration", payload.narration);
      }

      // A QUEST FINISHING WAS SILENT. The server has always carried
      // `quest_events` -- started, advanced, completed, failed -- and nothing
      // in the client read the key, so the only way a player learned a quest
      // had completed was if the narrator happened to mention it, and the
      // narrator is not told either. A stage that awards gold and an item paid
      // out with no line on screen anywhere.
      //
      // Appended AFTER the narration so it reads as a consequence of the turn
      // rather than a heading for it.
      for (const event of payload.quest_events || []) {
        if (event && event.text) {
          next = append(next, "quest", event.text);
        }
      }

      return {
        ...next,
        choices: payload.choices || [],
        world: payload.state || next.world,
        meters: metersOf(payload, next.meters),
        saveId: payload.save_id || next.saveId,
        presence: payload.assistant || next.presence,
        // The server sends the key only on a turn that actually faded, so the
        // absent case has to clear it rather than fall through -- see the
        // field's own note on why this one is not sticky.
        fadeCard: payload.fade_card || null,
        // Sticky once set. The turn that locks an ending is the only one
        // carrying it, and a later turn -- an autosave echo, a reconnect
        // replaying the last payload -- must not take the ending screen away
        // again. Cleared only by RESET, which is what starting or loading a
        // run does.
        ending: payload.ending || next.ending,
        reasoningOpen: false,
      };
    }

    case "dice_result":
      return { ...state, dice: { ...payload, at: Date.now() } };

    case "assistant_speak":
      // Merge, never replace: the speak event is a line plus a few fields, and
      // overwriting presence with it would drop trust and the awareness gates
      // every time the companion opened its mouth.
      return { ...state, assistant: payload, presence: { ...state.presence, ...payload } };

    // Was in INBOUND with no reducer case at all, which made it a silent
    // no-op AND suppressed the socket.onAny drift warning meant to catch it.
    case "portrait_ready": {
      if (!payload.url) return state;
      if (payload.kind && payload.kind !== "assistant") return state;
      return {
        ...state,
        presence: {
          ...state.presence,
          portrait: payload.url,
          form: payload.form || state.presence?.form,
        },
      };
    }

    case "image_ready":
      return payload.url ? { ...state, sceneImage: payload.url } : state;

    case "narration_audio":
      return payload.url ? { ...state, audio: payload.url } : state;

    case "cutscene_start":
      return { ...state, cutscene: payload };

    // Client-only: the letterbox closing. Not a server event.
    case "cutscene_end":
      return { ...state, cutscene: null };

    case "turn_error":
      // CONTENTION IS NOT FAILURE. `busy` means "a turn is already running and
      // yours never started" -- the running turn is fine and is still
      // streaming. Tearing the stream down here deleted prose the player was
      // already reading, and cleared `busy` so every control came back live
      // while the server was still generating. A stray second keypress, or a
      // second tab on the same session, was enough to do it.
      if (payload.busy) {
        return {
          ...state,
          error: payload.message || "A turn is already in progress.",
        };
      }
      return {
        ...closeStream(state),
        busy: false,
        error: payload.message || "The turn could not be completed.",
      };

    case "resume_failed":
      return { ...state, screen: "start", busy: false };

    case "error":
      return { ...state, error: payload.message || "Error", busy: false };

    default:
      return state;
  }
}

/**
 * Compose the core reducer with a story plugin's own.
 *
 * The plugin sees the action AND the already-reduced core state, so it can
 * derive from this turn's payload rather than last turn's. It may return the
 * same slice object to signal "nothing changed", which keeps the identity
 * stable and stops every consumer of `state.story` re-rendering per token.
 */
export function createStore(plugin) {
  const storyInitial = plugin?.initialState ?? {};
  const initial = { ...initialState, story: storyInitial };

  function composed(state, action) {
    const next = reducer(state, action);
    if (!plugin?.reduce) return next;
    const slice = plugin.reduce(next.story, action, next);
    return slice === next.story ? next : { ...next, story: slice };
  }

  return { initial, reducer: composed, storyInitial };
}
