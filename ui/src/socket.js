/**
 * Socket layer — the single place that knows every event name.
 *
 * The old client and server disagreed in both directions: the client listened
 * for `narration_delta` that nothing emitted, while the server emitted
 * `dice_result` and `cutscene_start` that nothing listened for. Naming every
 * event in one table makes that class of drift visible instead of silent.
 */
import { io } from "socket.io-client";

export const INBOUND = [
  "game_started",
  "game_resumed",
  "resume_failed",
  "turn_update",
  "narration_delta",
  "dice_result",
  "assistant_speak",
  "image_ready",
  "portrait_ready",
  "narration_audio",
  "cutscene_start",
  "turn_error",
  "error",
];

export const OUTBOUND = ["join_session", "player_choice", "resume"];

const SAVE_KEY = "clockwork_save_id";

export function loadSaveId() {
  try {
    return window.localStorage.getItem(SAVE_KEY) || "";
  } catch {
    return "";
  }
}

export function storeSaveId(saveId) {
  if (!saveId) return;
  try {
    window.localStorage.setItem(SAVE_KEY, saveId);
  } catch {
    /* private browsing; the run still works, it just will not resume */
  }
}

export function clearSaveId() {
  try {
    window.localStorage.removeItem(SAVE_KEY);
  } catch {
    /* ignore */
  }
}

/**
 * Connect and wire every inbound event to a single dispatch function.
 * Unknown events are logged rather than dropped, so a server-side addition
 * shows up during development instead of vanishing.
 */
export function connect(dispatch) {
  const socket = io({ transports: ["websocket", "polling"] });

  socket.on("connect", () => dispatch({ type: "CONNECTED" }));
  socket.on("disconnect", () => dispatch({ type: "DISCONNECTED" }));
  socket.on("connect_error", (err) =>
    dispatch({ type: "ERROR", message: err?.message || "Connection failed" })
  );

  // Token deltas are coalesced into one dispatch per animation frame. A local
  // model at 30 tok/s otherwise drives 30 reducer runs and 30 React renders a
  // second, each one re-rendering the whole narrative log; on a long log the
  // stream visibly stutters and the machine spends more time reconciling than
  // the model spends generating.
  let pending = "";
  let frame = 0;

  function flush() {
    frame = 0;
    if (!pending) return;
    const text = pending;
    pending = "";
    dispatch({ type: "SOCKET", event: "narration_delta", payload: { text } });
  }

  function flushNow() {
    if (frame) {
      cancelAnimationFrame(frame);
      frame = 0;
    }
    flush();
  }

  for (const name of INBOUND) {
    if (name === "narration_delta") {
      socket.on(name, (payload) => {
        const text = typeof payload === "string" ? payload : payload?.text;
        if (!text) return;
        pending += text;
        if (!frame) frame = requestAnimationFrame(flush);
      });
      continue;
    }
    socket.on(name, (payload) => {
      // Order matters more than latency: turn_update finalizes the streaming
      // entry, so any buffered tokens must land before it or they are appended
      // to an entry that is already closed and the paragraph splits in two.
      flushNow();
      dispatch({ type: "SOCKET", event: name, payload });
    });
  }

  socket.onAny((name) => {
    if (!INBOUND.includes(name) && !["connect", "disconnect", "connect_error"].includes(name)) {
      console.warn(`[socket] unhandled server event: ${name}`);
    }
  });

  return socket;
}
