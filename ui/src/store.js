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
  assistant: null, // {text, form, voice_style, portrait, trust, ...}
  // Presence, not speech: survives a silent turn so the companion column is
  // never blank. assistant.text is the transient line; this is who is there.
  presence: null,
  // Every form the companion has worn this run, oldest first. It changes form
  // as it changes its mind about you, and nothing recorded that it had.
  formHistory: [],
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
};

let nextId = 1;
const newId = () => `e${nextId++}`;

function append(state, kind, text) {
  if (!text) return state;
  return { ...state, log: [...state.log, { id: newId(), kind, text }] };
}

/**
 * Append to the form history only when the form actually changed.
 *
 * The companion wears five faces and swaps between them as its trust and the
 * world's awareness move. Nothing in the client ever recorded that it had, so
 * a player who looked away missed the only tell the design gives them.
 */
function rememberForm(history, presence, world) {
  const form = presence?.form;
  if (!form) return history;
  const last = history[history.length - 1];
  if (last && last.form === form) return history;
  return [
    ...history,
    { form, day: world?.world_day ?? 0, turn: world?.turn_number ?? 0, portrait: presence.portrait || "" },
  ].slice(-8);
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
      return { ...initialState, connected: state.connected, saves: state.saves };

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
      // `opening.choices || []` and not `if (opening.choices)`: a resume used
      // to arrive with no opening at all, and falling through left whatever
      // stale choices the previous screen had.
      next = { ...next, choices: opening.choices || [] };
      if (opening.scene_image) next = { ...next, sceneImage: opening.scene_image };
      if (opening.assistant) {
        next = {
          ...next,
          presence: opening.assistant,
          formHistory: rememberForm(next.formHistory, opening.assistant, next.world),
        };
      }
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
      const presence = payload.assistant || next.presence;
      return {
        ...next,
        choices: payload.choices || [],
        world: payload.state || next.world,
        phase: (payload.state && payload.state.evil_phase) || next.phase,
        saveId: payload.save_id || next.saveId,
        presence,
        formHistory: rememberForm(next.formHistory, presence, payload.state),
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
      const presence = { ...state.presence, portrait: payload.url, form: payload.form || state.presence?.form };
      return { ...state, presence, formHistory: rememberForm(state.formHistory, presence, state.world) };
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
