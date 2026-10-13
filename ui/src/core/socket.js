/**
 * Socket transport and the wire contract.
 *
 * Story-agnostic: nothing here knows what a phase, a die or a companion is. It
 * names every event the server can send, wires each one to a single dispatch,
 * and paces the two streaming channels.
 *
 * PARSED BY TESTS, DELIBERATELY
 * -----------------------------
 * Two Python tests read this file as text rather than importing it, because
 * there is no JS runtime in the suite:
 *
 *   tests/test_ui_contract.py        the INBOUND table vs every server emit()
 *   tests/test_narration_control.py  flushNow / wordBoundary / the disconnect
 *
 * They are the only thing standing between the two halves of the product and
 * another round of silent drift -- a server event with no client listener used
 * to be a feature that simply did nothing. If this file moves again, move those
 * path constants in the same change.
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
  // Hosted: this tab's run was released elsewhere, ended, or put away idle (spec §6.5).
  "session_ended",
  // READ RECEIPTS (v0.22.0): background pushes from the voicing and media
  // threads, between actions; reduced by the plugin, never by core (spec §17.3).
  "phone_message",
  "media_ready",
  "error",
];

export const OUTBOUND = ["join_session", "player_choice", "resume", "phone_action"];

/** One phone action (v0.22.0): the catalogue's shape, nothing else. */
export function emitPhone(socket, sessionId, intent) {
  if (!socket || !sessionId || !intent || !intent.action) return false;
  const { action, target = "", args = {}, text = "" } = intent;
  socket.emit("phone_action", { session_id: sessionId, action, target, args, text });
  return true;
}

/**
 * How long a busy phone action waits before it is sent again, and how many
 * sends it gets in all: the first and one re-send (spec §18.2, "re-sent once
 * after 150 ms; a second busy keeps the composed text").
 */
export const PHONE_RETRY_MS = 150;
export const PHONE_RETRY_TRIES = 2;
/** An action whose answer never came stops holding the line after this long. */
export const PHONE_ANSWER_MS = 10000;

/**
 * The phone's sender (v0.22.0, spec §16.1, §18.2): one action on the wire at a
 * time, a busy answer re-sent transparently.
 *
 * A voicing pass commits its messages holding the turn lock for a few
 * milliseconds, so an action that lands in that window is answered
 * `turn_error {busy}` with nothing changed. That is contention, not failure:
 * the action is sent again after `delay` ms, up to `tries` sends in all, and
 * the busy answers it drew never reach the store. Only the last one does, so
 * the plugin can keep what the player composed ("Not sent").
 *
 * ONE IN FLIGHT. A busy answer does not say which action it refused, so a
 * second action pressed while the first is unanswered waits its turn here
 * (mechanics answer in milliseconds). The in-flight action is answered by the
 * next `turn_update` or `turn_error`; one that never is (a dropped socket, a
 * handler that raised) stops holding the line after `answerMs`, and its late
 * answer, if it comes, is credited to nobody (`stale`). An answer eaten that
 * way while another action is in flight may have been THAT action's own (the
 * late one never came): so that action, if it then times out, owes nothing --
 * it never re-arms `stale`, or the debt would pass from action to action and
 * eat every later answer (v0.22.0 T27).
 *
 * NOTHING IS DROPPED IN SILENCE. Whatever never reached the server -- the
 * queue and an action waiting out its re-send, on a disconnect or a reset;
 * an action with no socket to go on -- is handed to `onDrop(intents)`, which
 * App turns into a `PHONE_DROPPED` action for the plugin's `reduce`, so a
 * composed message is kept ("Not sent", spec §18.2), never lost. An action
 * sent and still unanswered is not reported: the server may have applied it.
 *
 * CAVEAT: `turn_update` goes to the session's whole ROOM. Two tabs driving
 * one local session (CLAUDE.md, deferred) each see the other's answers, and
 * this sender credits them to its own in-flight action. Hosted mode allows
 * one live run per account, so only local mode can meet it.
 *
 * `filter(action)` sees every store action before the store does and returns
 * true for the ones it swallows (a busy answer it will retry).
 */
export function createPhoneSender({
  getSocket,
  delay = PHONE_RETRY_MS,
  tries = PHONE_RETRY_TRIES,
  answerMs = PHONE_ANSWER_MS,
  onDrop = () => {},
  timers = { set: (fn, ms) => setTimeout(fn, ms), clear: (id) => clearTimeout(id) },
} = {}) {
  let flight = null; // {sessionId, intent, sends, waiting, timer, eaten}
  const queue = [];
  // Answers still owed to an action that timed out: the next answer is its,
  // not the in-flight action's. Forgotten after another `answerMs`, so an
  // answer that never comes cannot make every later action wait out its time.
  let stale = 0;
  let staleTimer = null;

  function stopTimer() {
    if (flight && flight.timer) timers.clear(flight.timer);
    if (flight) flight.timer = null;
  }

  function drop(intents) {
    if (intents.length) onDrop(intents);
  }

  /** Send the in-flight action (again); false when it could not go at all. */
  function fire() {
    stopTimer();
    if (!emitPhone(getSocket(), flight.sessionId, flight.intent)) return false;
    flight.sends += 1;
    flight.waiting = false;
    flight.timer = timers.set(timedOut, answerMs);
    return true;
  }

  /** The in-flight action is done with: send the next queued one, if any. */
  function advance() {
    stopTimer();
    flight = null;
    while (queue.length) {
      flight = { ...queue.shift(), sends: 0, waiting: false, timer: null };
      if (fire()) return;
      // No socket to go on: never sent, so it is reported, not lost.
      drop([flight.intent]);
      flight = null;
    }
  }

  /** No answer within `answerMs`: give up the line, and owe the late answer nothing. */
  function timedOut() {
    if (flight) flight.timer = null;
    // An action whose answer may already have been eaten as the owed late
    // one is owed nothing more: re-arming here is how the debt re-armed.
    if (!(flight && flight.eaten)) {
      stale = 1;
      if (staleTimer) timers.clear(staleTimer);
      staleTimer = timers.set(() => {
        staleTimer = null;
        stale = 0;
      }, answerMs);
    }
    advance();
  }

  /** Drop the queue and an action waiting to be re-sent, reporting both. */
  function reset() {
    const dropped = [];
    if (flight && flight.waiting) dropped.push(flight.intent);
    for (const item of queue) dropped.push(item.intent);
    stopTimer();
    flight = null;
    queue.length = 0;
    if (staleTimer) timers.clear(staleTimer);
    staleTimer = null;
    stale = 0;
    drop(dropped);
  }

  /** A retry's timer: the action goes again, or (no socket) is dropped and gives way. */
  function retry() {
    if (!flight || fire()) return;
    drop([flight.intent]);
    advance();
  }

  return {
    send(sessionId, intent) {
      if (!sessionId || !intent || !intent.action) return false;
      queue.push({ sessionId, intent });
      if (!flight) advance();
      return true;
    },
    filter(action) {
      if (!action) return false;
      if (action.type === "DISCONNECTED") {
        reset();
        return false;
      }
      if (action.type !== "SOCKET") return false;
      const { event, payload } = action;
      if (event !== "turn_update" && event !== "turn_error") return false;
      if (stale > 0) {
        // A timed-out action's late answer: the store gets it, no action is
        // credited. It may have been the in-flight action's own, so that one
        // is marked: should it time out, it owes no late answer of its own.
        stale -= 1;
        if (flight) flight.eaten = true;
        // Said on the action, so a plugin counting answers (READ RECEIPTS'
        // usePhoneAct) never takes it for the answer to its own action.
        action.stale = true;
        return false;
      }
      if (!flight || flight.waiting) return false;
      if (event === "turn_error" && payload && payload.busy && flight.sends < tries) {
        stopTimer();
        flight.waiting = true;
        flight.timer = timers.set(retry, delay);
        return true;
      }
      advance();
      return false;
    },
    reset,
    pending() {
      return (flight ? 1 : 0) + queue.length;
    },
  };
}

// Key is unchanged from before the core/story split on purpose: renaming it
// would orphan the save id in every existing player's localStorage and silently
// stop resuming their run.
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
  socket.on("disconnect", (reason) => {
    // Drop the queues, do not flush them: the reducer clears `streamingId` on
    // disconnect, so anything released here would land in a closed entry. A
    // held word fragment would also keep the animation-frame loop spinning
    // forever waiting for a chunk from a socket that is gone.
    clearQueues();
    dispatch({ type: "DISCONNECTED", reason });
  });
  socket.on("connect_error", () => {
    // Socket.IO's own words ("xhr poll error") once per retry used to land in
    // the footer and close the stream (F3). The connection's state machine
    // (core/link.js) says what is happening now; this only drops the queues.
    clearQueues();
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
