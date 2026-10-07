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

import { banner as linkBanner, isConnected } from "./link.js";

export const initialState = {
  screen: "start", // start | scene | saves
  connected: false,
  // The connection's state (core/link.js, spec §6.3) and what its banner says.
  // `connected` above is derived from it (LINK) because Menu and older tests
  // read the boolean.
  link: "connecting",
  banner: null,
  // Set by a recovery's resume when the log ended on an unanswered move
  // before the resume's own line; read and cleared by the next LINK.
  pendingAgain: false,
  // The player's last move as sent (SUBMIT): `{choiceId, custom, intent}`.
  // A recovery that finds it unanswered re-offers it only if the frame it
  // lands in still holds it (`retryTarget`), and `againId` is the id to send.
  move: null,
  againId: "",
  // Bumped when the player must choose again; ChoiceRow focuses its row.
  choiceFocus: 0,
  // The footer's error is not worth retrying (a stale choice): no Try again.
  errorFinal: false,
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
  // What the multi-agent pipeline settled THIS turn, or null. Shape is
  // engine/agents/pipeline.py's `PipelineResult.to_dict()`: lead, beats,
  // resolutions (rule/winner/loser/detail), refused, veto, blocked.
  //
  // Deliberately NOT sticky, unlike `ending` above: it describes one turn's
  // argument, and carrying it forward would have the panel and the log mark
  // reporting a disagreement two turns stale. The three stories that run a
  // pipeline send it; the flagship has one participant and never does.
  negotiation: null,
  // The casing board: houses in the player's current district and what
  // watching has told about each -- {id, name, type_label, known, of,
  // empty_now}[]. Lives on `world.premises` (GameState.to_client_dict's
  // `_premises_block`); mirrored here exactly as `meters` mirrors
  // `world.meters`, so CasingBoard reads one flat field instead of an
  // optional-chained path through a payload that may be null between turns.
  // `[]` for a story that declares no premises -- the flagship among them --
  // and for a district that currently holds none: both are real empty states,
  // and CasingBoard renders nothing for either.
  premises: [],
  dice: null, // transient toast
  sceneImage: "",
  cutscene: null,
  audio: "",

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

/**
 * Controls are live only in `live` with no turn running (spec §6.3, F5).
 *
 * The one selector: App's `send` and `retry` guards, the play screen's
 * chips, compose box and Send, and the encounter panel's approaches all ask
 * this, so a press can never reach a socket that is down, rejoining or
 * waiting on a turn the server is still playing.
 */
export function controlsLive(state) {
  return state.link === "live" && !state.busy;
}

/** Does the log end on the player's own move, with no narration after it? (dice and quest lines skipped) */
/** Whether two intents name the same mechanic (action, target, band). */
function sameIntent(a, b) {
  if (!a || !b) return false;
  return (
    String(a.action || "") === String(b.action || "") &&
    String(a.target || "") === String(b.target || "") &&
    String(a.difficulty || "") === String(b.difficulty || "")
  );
}

/**
 * What "Try again" may send for an unanswered `move`, given the `choices`
 * now on screen: "" to re-send it as it was (typed text, or a chip whose id
 * the frame still holds with the same intent), a choice id carrying the same
 * intent under a new id, or null when the move is no longer on offer -- a
 * chip with no intent, or one whose intent the frame does not hold. App's
 * `send` records every move it sends; one with no record retries as it was.
 */
export function retryTarget(move, choices) {
  // No record of the move (a SUBMIT that carried none): retried as it was.
  if (!move) return "";
  if (!move.choiceId || move.choiceId === "custom") return move.custom ? "" : null;
  const list = choices || [];
  const same = list.find((c) => c && c.id === move.choiceId);
  if (same && (sameIntent(same.intent, move.intent) || (!same.intent && !move.intent))) return "";
  if (!move.intent) return null;
  const match = list.find((c) => c && sameIntent(c.intent, move.intent));
  return match ? match.id : null;
}

export function endsOnUnansweredEcho(log) {
  for (let i = log.length - 1; i >= 0; i -= 1) {
    const kind = log[i].kind;
    if (kind === "dice" || kind === "quest" || kind === "system") continue;
    return kind === "player" && Boolean(log[i].text);
  }
  return false;
}

/**
 * A rejoin's `game_started` (spec §6.6): the run this page already shows,
 * picked up again after the socket came back.
 *
 * `opening` is the session's LAST turn, which this page may or may not have
 * seen. Its narration is appended only if the log does not already end on
 * it, and its quest lines only with it; an ending is read with turn_update's
 * sticky rule (a turn that locked one while the socket was down shows the
 * ending screen); `busy` comes from `turn_running`, so the controls stay off
 * over a turn the server is still playing.
 */
function reduceRejoin(state, payload) {
  const opening = payload.opening || {};
  let next = {
    ...closeStream(state),
    world: payload.state || state.world,
    meters: metersOf(payload, state.meters),
    premises: premisesOf(payload, state.premises),
    busy: Boolean(payload.turn_running),
    error: "",
  };
  if (opening.narration && !repeatsLastNarration(next.log, opening.narration)) {
    next = append(next, "narration", opening.narration);
    for (const event of opening.quest_events || []) {
      if (event && event.text) next = append(next, "quest", event.text);
    }
  }
  return {
    ...next,
    choices: opening.choices || [],
    sceneImage: opening.scene_image || next.sceneImage,
    presence: opening.assistant || next.presence,
    ending: opening.ending || next.ending,
  };
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
        // A retry (Try again) sends no `move` and keeps the one it retries.
        move: action.move !== undefined ? action.move : state.move,
        againId: action.move !== undefined ? "" : state.againId,
        dice: null,
        errorFinal: false,
        // The card belonged to the scene that faded. It sits under the log, so
        // leaving it up while the NEXT turn is in flight would print it beneath
        // a moment it has nothing to do with.
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

    // The connection's machine (core/link.js) says where it is. A rejoin that
    // found the player's last move dropped unanswered (16) is offered again
    // here, where the log can be read.
    case "LINK": {
      let shown = action.banner ?? null;
      let againId = state.againId;
      let choiceFocus = state.choiceFocus;
      if (action.checkUnanswered && (state.pendingAgain || endsOnUnansweredEcho(state.log))) {
        // Re-offered only if the frame on screen still holds the move
        // (final review finding 8): after a server restart the resumed
        // frame's choices are `resume_*`, and re-sending the dropped chip's
        // id ran no mechanic and narrated "option 3". Matched by INTENT,
        // never by an id the frame does not hold; otherwise the player is
        // told plainly and the row takes focus.
        const target = retryTarget(state.move, state.choices);
        if (target === null) {
          shown = linkBanner("unanswered_lost");
          againId = "";
          choiceFocus += 1;
        } else {
          shown = linkBanner("unanswered");
          againId = target;
        }
      }
      return {
        ...state,
        link: action.link,
        connected: isConnected(action.link),
        banner: shown,
        pendingAgain: false,
        againId,
        choiceFocus,
      };
    }

    case "BANNER_DISMISS":
      return { ...state, banner: null };

    // Leaving a run. Without this the previous run's narrative log, choices,
    // companion and scene still bled straight into the next one -- the old
    // client had no way to leave a run at all, so nothing ever needed it.
    case "RESET":
      return {
        ...initialState,
        connected: state.connected,
        // The connection outlives the run: leaving a run is not reconnecting.
        link: state.link,
        banner: state.banner,
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

/** The casing board's rows, or the previous list when a payload omits them. */
function premisesOf(payload, fallback) {
  const world = payload && payload.state;
  if (world && world.premises) return world.premises;
  return fallback;
}

function handleSocket(state, event, payload) {
  switch (event) {
    case "game_started":
    case "game_resumed": {
      if (event === "game_started" && payload.session_id && payload.session_id === state.sessionId) {
        if (state.link === "rejoining") return reduceRejoin(state, payload);
        // A LATE answer for the run on screen, outside a rejoin: a second
        // answer to the join timer's re-sent `join_session` (21) after the
        // first already went live. It changes NOTHING (re-review R1): not
        // `busy` -- a running turn it reports may long since have finished
        // (setting it froze the page until the watchdog), and one it does
        // not report may be the player's own move in flight -- and nothing
        // is appended (it would land under a streaming move). If it says a
        // turn is running while the page is idle, the link re-joins
        // (core/link.js, onGameStarted) and the fresh answer decides.
        if (state.screen === "scene") return state;
      }
      const opening = payload.opening || {};
      // A resume after a recovery: did the log end on the player's move, with
      // no narration after it, BEFORE this resume's line lands? The link asks
      // (LINK checkUnanswered) once it goes live (spec §6.7, review 2).
      const pendingAgain = event === "game_resumed" && state.link === "resuming" && endsOnUnansweredEcho(state.log);
      let next = {
        ...state,
        screen: "scene",
        sessionId: payload.session_id || state.sessionId,
        saveId: payload.save_id || state.saveId,
        world: payload.state || state.world,
        meters: metersOf(payload, state.meters),
        premises: premisesOf(payload, state.premises),
        busy: false,
        error: "",
        pendingAgain,
      };
      // Guarded like a rejoin's (review 1): a resume after a server restart
      // carries the canned resume line the log may already end on.
      if (opening.narration && !repeatsLastNarration(next.log, opening.narration)) {
        next = append(next, "narration", opening.narration);
      }
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
        ? "The Storyteller is unreachable — check the model server is running and its API key is set."
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

      // A TURN TWO AGENTS ARGUED OVER SHOULD NOT LOOK LIKE ANY OTHER TURN.
      // Only when somebody actually YIELDED: the negotiator records a
      // resolution for the confidence fallback too ("no rule matched, highest
      // confidence leads"), which is bookkeeping rather than a concession, and
      // marking it would tell the player a turn was fought over when it was
      // not. The mark is state, not words -- no engine-authored sentence goes
      // into the log beside the narrator's prose.
      const negotiation = payload.negotiation || null;
      const yielded = (negotiation?.resolutions || []).some((r) => r && r.loser);
      if (yielded) {
        const last = [...next.log].reverse().find((e) => e.kind === "narration");
        if (last) {
          next = {
            ...next,
            log: next.log.map((e) => (e.id === last.id ? { ...e, negotiated: true } : e)),
          };
        }
      }

      return {
        ...next,
        negotiation,
        choices: payload.choices || [],
        world: payload.state || next.world,
        meters: metersOf(payload, next.meters),
        premises: premisesOf(payload, next.premises),
        saveId: payload.save_id || next.saveId,
        presence: payload.assistant || next.presence,
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
      // A choice the frame no longer offers (`stale_choice`, final review
      // finding 8): refused before any turn ran. Retrying it would be
      // refused again, so there is nothing to try: the player chooses again.
      if (payload.stale_choice) {
        return {
          ...closeStream(state),
          busy: false,
          error: payload.message || "That choice is no longer on offer. Choose again.",
          errorFinal: true,
          againId: "",
          choiceFocus: state.choiceFocus + 1,
        };
      }
      return {
        ...closeStream(state),
        busy: false,
        error: payload.message || "The turn could not be completed.",
      };

    case "resume_failed":
      // The message is kept for the start screen (Review 27): it used to be
      // dropped, so a save that would not open sent the player back to Begin
      // with no word as to why.
      return { ...state, screen: "start", busy: false, error: payload.message || "" };

    case "error":
      // The rejoin's own miss is the link's to answer (it resumes), not a failure to show.
      if (state.link === "rejoining" && payload.message === "session not found") return state;
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
