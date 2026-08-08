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

export function reducer(state, action) {
  switch (action.type) {
    case "CONNECTED":
      return { ...state, connected: true, error: "" };

    case "DISCONNECTED":
      // Clearing busy matters: the old client only cleared it on turn_update
      // or error, so a dropped socket left every control disabled forever.
      return { ...state, connected: false, busy: false, streamingId: null };

    case "ERROR":
      return { ...state, error: action.message, busy: false, streamingId: null };

    case "SUBMIT": {
      const next = append(state, "player", action.text);
      return {
        ...next,
        busy: true,
        dice: null,
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
      } else if (payload.narration) {
        // Nothing streamed -- a non-streaming turn, or a generation that was
        // starved before it produced a single token. Append it whole. This no
        // longer consults `payload.streamed`: a starved first attempt sets that
        // flag with no entry to attach to, and the turn silently vanished.
        next = append(next, "narration", payload.narration);
      }
      return {
        ...next,
        choices: payload.choices || [],
        world: payload.state || next.world,
        meters: metersOf(payload, next.meters),
        saveId: payload.save_id || next.saveId,
        presence: payload.assistant || next.presence,
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
      return {
        ...state,
        busy: false,
        streamingId: null,
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
