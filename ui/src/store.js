/**
 * Game store — one reducer, one shape.
 *
 * All the state the old client kept in loose module variables (`sessionId`,
 * `busy`, a dangling `streamEntry` node) lives here instead, so a reconnect or
 * a mid-turn error cannot leave the UI in a state nothing knows how to clear.
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
  phase: "dormant",
  assistant: null, // {text, form, voice_style}
  dice: null, // transient toast
  sceneImage: "",
  cutscene: null,
  audio: "",

  error: "",
  saves: [],
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
      return { ...next, busy: true, dice: null, error: "" };
    }

    case "SCREEN":
      return { ...state, screen: action.screen };

    case "SAVES":
      return { ...state, saves: action.saves };

    case "SOCKET":
      return handleSocket(state, action.event, action.payload || {});

    default:
      return state;
  }
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
        phase: (payload.state && payload.state.evil_phase) || state.phase,
        busy: false,
        error: "",
      };
      if (opening.narration) next = append(next, "narration", opening.narration);
      if (opening.choices) next = { ...next, choices: opening.choices };
      if (opening.scene_image) next = { ...next, sceneImage: opening.scene_image };
      return next;
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
      if (state.streamingId) {
        next.log = next.log.map((e) =>
          e.id === state.streamingId ? { ...e, streaming: false } : e
        );
        next.streamingId = null;
      }
      // Only append when the text did NOT already arrive as deltas.
      if (payload.narration && !payload.streamed) {
        next = append(next, "narration", payload.narration);
      }
      return {
        ...next,
        choices: payload.choices || [],
        world: payload.state || next.world,
        phase: (payload.state && payload.state.evil_phase) || next.phase,
        saveId: payload.save_id || next.saveId,
      };
    }

    case "dice_result":
      return { ...state, dice: { ...payload, at: Date.now() } };

    case "assistant_speak":
      return { ...state, assistant: payload };

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
