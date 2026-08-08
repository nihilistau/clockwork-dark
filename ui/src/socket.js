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
  // The model's thinking channel, on its own event. The backend has always
  // kept reasoning separate from narration and nothing consumed it, so the
  // 10-14 seconds before the first narration token were a blank screen.
  "reasoning_delta",
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
  socket.on("disconnect", () => {
    // Drop the queues, do not flush them: the reducer clears `streamingId` on
    // disconnect, so anything released here would land in a closed entry. A
    // held word fragment would also keep the animation-frame loop spinning
    // forever waiting for a chunk from a socket that is gone.
    clearQueues();
    dispatch({ type: "DISCONNECTED" });
  });
  socket.on("connect_error", (err) => {
    clearQueues();
    dispatch({ type: "ERROR", message: err?.message || "Connection failed" });
  });

  // Token deltas are coalesced into one dispatch per animation frame. A local
  // model at 30 tok/s otherwise drives 30 reducer runs and 30 React renders a
  // second, each one re-rendering the whole narrative log; on a long log the
  // stream visibly stutters and the machine spends more time reconciling than
  // the model spends generating.
  //
  // The queue is also PACED rather than emptied. A local model does not
  // deliver at a steady rate: it stalls for half a second and then dumps forty
  // tokens at once, and forwarding each burst whole reproduces the stutter on
  // screen. Draining a fraction of the backlog per frame turns that into a
  // steady reveal. It cannot fall meaningfully behind -- the drain is
  // proportional, so a 400-character burst empties with a ~130ms time constant
  // at 60fps -- and `flushNow` bypasses it entirely at the end of a turn.
  //
  // One queue per streaming channel. Reasoning arrives faster than narration
  // (it is uncapped and ungrammared) so sharing a queue would let a burst of
  // thinking delay the prose the player is actually reading.
  const STREAMED = ["narration_delta", "reasoning_delta"];
  const queue = { narration_delta: "", reasoning_delta: "" };
  const frames = { narration_delta: 0, reasoning_delta: 0 };
  // Consecutive frames that released nothing because the queue ended mid-word.
  const stalled = { narration_delta: 0, reasoning_delta: 0 };

  // Fraction of the backlog released per frame, and the floor below which
  // pacing stops being smoothing and starts being a stall.
  const DRAIN_DIVISOR = 8;
  const MIN_CHARS = 2;

  // A run of non-whitespace longer than this is not a word, it is a URL or a
  // degenerate token. Release it rather than stall the reveal waiting for a
  // space that is never coming.
  const MAX_WORD = 120;

  // Frames a half-word may be held before it is shown anyway. The channel can
  // go quiet with a fragment still in hand -- the model stops mid-word and
  // switches to reasoning, or the turn ends without a `turn_update` -- and
  // waiting forever would both freeze the text and spin the frame loop.
  const MAX_HOLD_FRAMES = 30;

  /**
   * Move `take` back to a word boundary, or return 0 to wait for more text.
   *
   * Returning 0 is the load-bearing case and the reason this is not just a
   * `lastIndexOf`. When the queue ends mid-word -- which it does constantly,
   * because a chunk boundary lands wherever the model happened to pause -- the
   * only way to guarantee a whole word on screen is to hold the fragment until
   * the character after it arrives. Measured live before this: 262 of 319
   * rendered states ended mid-word ("You’re per").
   */
  function wordBoundary(text, want) {
    const cut = Math.min(want, text.length);
    // Last whitespace at or before the intended cut.
    let end = cut;
    while (end > 0 && !/\s/.test(text[end - 1])) end -= 1;
    if (end > 0) return end;

    // The intended cut sits inside the first word. Take the whole word if it
    // has finished arriving, otherwise wait.
    const space = text.search(/\s/);
    if (space !== -1) return space + 1;
    return text.length > MAX_WORD ? text.length : 0;
  }

  function step(event) {
    frames[event] = 0;
    const text = queue[event];
    if (!text) return;

    const share = Math.max(MIN_CHARS, Math.ceil(text.length / DRAIN_DIVISOR));
    let take = wordBoundary(text, share);
    if (take === 0 && ++stalled[event] >= MAX_HOLD_FRAMES) take = text.length;
    if (take > 0) {
      stalled[event] = 0;
      queue[event] = text.slice(take);
      dispatch({ type: "SOCKET", event, payload: { text: text.slice(0, take) } });
    }
    // Keep the loop alive even when nothing was released: the held fragment is
    // waiting on the next chunk, on the hold timeout, or on `flushNow`.
    if (queue[event]) frames[event] = requestAnimationFrame(() => step(event));
  }

  /**
   * Release everything still queued, right now, unpaced.
   *
   * The one thing pacing must never do is lose the tail. Every non-streamed
   * event drains the queues first, so the last characters of a turn always
   * land before `turn_update` closes the entry -- including when the browser
   * has stopped firing animation frames because the tab is hidden.
   */
  function flushNow() {
    for (const event of STREAMED) {
      if (frames[event]) {
        cancelAnimationFrame(frames[event]);
        frames[event] = 0;
      }
      const text = queue[event];
      queue[event] = "";
      stalled[event] = 0;
      if (text) dispatch({ type: "SOCKET", event, payload: { text } });
    }
  }

  function clearQueues() {
    for (const event of STREAMED) {
      if (frames[event]) cancelAnimationFrame(frames[event]);
      frames[event] = 0;
      queue[event] = "";
      stalled[event] = 0;
    }
  }

  for (const name of INBOUND) {
    if (STREAMED.includes(name)) {
      socket.on(name, (payload) => {
        const text = typeof payload === "string" ? payload : payload?.text;
        if (!text) return;
        queue[name] += text;
        if (!frames[name]) frames[name] = requestAnimationFrame(() => step(name));
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
