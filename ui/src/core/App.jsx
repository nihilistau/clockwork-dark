/**
 * The client shell.
 *
 * Owns everything that is true of any story: the socket, the reducer, the
 * screen router, the run lifecycle (new / resume / save / load / abandon),
 * preferences, the narration audio element, the turn watchdog and the global
 * keyboard map. The active story arrives as one `story` object and fills slots;
 * see core/story.js for the contract.
 *
 * Nothing in this file names a location, a stat, a phase or a die.
 */
import React, { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import Cutscene from "./parts/Cutscene.jsx";
import Onboarding, { shouldOnboard } from "./parts/Onboarding.jsx";
import { Icon } from "./parts/Chrome.jsx";
import Ending from "./screens/Ending.jsx";
import MapScreen from "./screens/Map.jsx";
import Menu from "./screens/Menu.jsx";
import Play from "./screens/Play.jsx";
import Saves from "./screens/Saves.jsx";
import Settings, { loadPrefs, savePrefs } from "./screens/Settings.jsx";
import Start from "./screens/Start.jsx";
import { clearSaveId, connect, loadSaveId, storeSaveId } from "./socket.js";
import { createStore } from "./store.js";

// The last line of defence against a server that dies without emitting
// anything: the old client left every control disabled forever with nothing on
// screen.
//
// IT HAS TO OUTLAST THE SERVER'S OWN GIVING-UP, and at 240s it did not. A
// narration turn on a reasoning model measures 106-205 seconds of wall clock
// (config/default.yaml, profile `big` -- thinking is 1100-2600 tokens BEFORE
// the first word of prose), and the generation call itself is capped at
// `lmstudio.timeout_seconds`, which ships at 300. So the old window declared
// the world dead a full minute before the server would have reported a real
// error with a real reason -- on turns that were still running. This is that
// cap plus enough margin for the rest of a turn's work, and
// tests/test_ui_contract.py fails the build if the two ever cross.
const TURN_WATCHDOG_MS = 330000;

/* Three places and the roads between them: the shape of the thing it opens,
   rather than a folded-paper map, which reads as "travel" in a client where
   travel is a choice and not a mode. */
function MapIcon() {
  return (
    <Icon>
      <circle cx="6" cy="7" r="2.2" />
      <circle cx="17.5" cy="10" r="2.2" />
      <circle cx="10" cy="18" r="2.2" />
      <path d="M7.9 8.2 15.6 9.4M15.9 11.9 11.4 16.2M8.4 15.9 6.7 9.4" />
    </Icon>
  );
}

export default function App({ story }) {
  // The reducer is the core one composed with the story's. Built once: a new
  // reducer identity per render would reset useReducer's state.
  const { initial, reducer, storyInitial } = useMemo(() => createStore(story), [story]);
  const [state, dispatch] = useReducer(reducer, initial);

  const [prefs, setPrefs] = useState(loadPrefs);
  const [showSettings, setShowSettings] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  // One overlay at a time, keyed by the story's overlay id. Two dialogs open at
  // once would mean two focus traps fighting over the same document.
  const [overlay, setOverlay] = useState(null);
  const [onboarding, setOnboarding] = useState(
    () => story.onboarding.length > 0 && shouldOnboard()
  );
  const muted = prefs.muted;
  const socketRef = useRef(null);
  const audioRef = useRef(null);
  const watchdog = useRef(null);
  const composeRef = useRef(null);
  // How to do the last thing again.
  //
  // Held as a THUNK rather than as the arguments, because the two things that
  // can fail are shaped differently -- beginning a run is a POST, playing a
  // turn is a socket emit -- and a retry button that only understands one of
  // them leaves the other failure exactly as dead as it was. Every failure the
  // player can see is now something they can press.
  const again = useRef(null);

  useEffect(() => {
    const socket = connect(dispatch);
    socketRef.current = socket;

    socket.on("connect", () => {
      // Resume, never restart. Reconnecting used to POST /api/game/new and
      // silently abandon the run in progress.
      const saved = loadSaveId();
      if (saved) socket.emit("resume", { save_id: saved });
    });

    return () => socket.close();
  }, []);

  // Persist whichever save the server tells us we are writing to.
  useEffect(() => {
    if (state.saveId) storeSaveId(state.saveId);
  }, [state.saveId]);

  // The story's own body attributes -- the flagship's `data-phase`, which
  // retints the entire product from one attribute. Core does not know what any
  // of them mean; it only knows to write and to clean them up.
  useEffect(() => {
    if (!story.bodyData) return undefined;
    const data = story.bodyData(state) || {};
    for (const [key, value] of Object.entries(data)) {
      document.body.dataset[key] = String(value);
    }
    return () => {
      for (const key of Object.keys(data)) delete document.body.dataset[key];
    };
  }, [story, state]);

  useEffect(() => {
    if (watchdog.current) clearTimeout(watchdog.current);
    if (state.busy) {
      watchdog.current = setTimeout(() => {
        dispatch({
          type: "ERROR",
          // No longer an instruction with nothing to press: `onRetry` re-sends
          // the same move, so the sentence can promise what the button does.
          message: "The world has not answered. Your move is still here.",
        });
      }, TURN_WATCHDOG_MS);
    }
    return () => watchdog.current && clearTimeout(watchdog.current);
  }, [state.busy]);

  // Narration audio, gated on a real user gesture -- browsers refuse autoplay
  // before one, and a rejected play() promise is an unhandled rejection.
  useEffect(() => {
    if (!state.audio || muted) return;
    const player = audioRef.current;
    if (!player) return;
    player.src = state.audio;
    player.volume = prefs.volume ?? 0.8;
    player.play().catch(() => {});
  }, [state.audio, muted, prefs.volume]);

  // Volume is live, not next-line: a player reaching for the slider mid-
  // paragraph means "quieter now".
  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = prefs.volume ?? 0.8;
  }, [prefs.volume]);

  const begin = useCallback(async (payload) => {
    again.current = () => begin(payload);
    dispatch({ type: "SUBMIT", text: "" });
    try {
      const res = await fetch("/api/game/new", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`server said ${res.status}`);
      const data = await res.json();
      storeSaveId(data.save_id);
      socketRef.current?.emit("join_session", { session_id: data.session_id });
    } catch (err) {
      dispatch({ type: "ERROR", message: `Could not begin: ${err.message}` });
    }
  }, []);

  const send = useCallback(
    (choiceId, customText, echo) => {
      if (state.busy || !state.sessionId) return;
      const emit = (spoken) => {
        dispatch({ type: "SUBMIT", text: spoken });
        socketRef.current?.emit("player_choice", {
          session_id: state.sessionId,
          choice_id: choiceId,
          custom_text: customText || null,
        });
      };
      // A retry re-sends the move with NO echo. The player's line is already in
      // the log from the attempt that failed, and a retry is the same move
      // tried again, not a second thing they did -- `append` ignores empty
      // text, so the transcript stays honest about what was actually said.
      again.current = () => emit("");
      emit(echo);
    },
    [state.busy, state.sessionId]
  );

  /**
   * Do the last thing again.
   *
   * The whole of what a failed turn used to offer was one line in the footer
   * and a compose box the player had to retype into from memory -- and the
   * watchdog's "No answer from the world. Try again." was an instruction with
   * nothing to press. The input is still here; this is the press.
   */
  const retry = useCallback(() => {
    if (state.busy) return;
    // Both thunks open with a SUBMIT, which is what clears `error` and puts
    // the turn back into flight -- so there is no separate "forget the
    // failure" step that could leave the two out of step.
    again.current?.();
  }, [state.busy]);

  const openSaves = useCallback(async () => {
    try {
      const res = await fetch("/api/saves");
      const data = await res.json();
      dispatch({ type: "SAVES", saves: data.saves || [] });
      dispatch({ type: "SCREEN", screen: "saves" });
    } catch {
      dispatch({ type: "ERROR", message: "Could not read saved runs." });
    }
  }, []);

  const loadSave = useCallback(
    async (save) => {
      try {
        const res = await fetch(`/api/saves/${save.save_id}/load`, { method: "POST" });
        if (!res.ok) throw new Error(`server said ${res.status}`);
        const data = await res.json();
        // The incoming run is a different run: its log, choices and companion
        // must not inherit the one we were just looking at.
        dispatch({ type: "RESET", storyInitial });
        storeSaveId(data.save_id);
        socketRef.current?.emit("join_session", { session_id: data.session_id });
        dispatch({ type: "SCREEN", screen: "scene" });
      } catch (err) {
        dispatch({ type: "ERROR", message: `Could not load: ${err.message}` });
      }
    },
    [storyInitial]
  );

  /**
   * Destroy a run, for good.
   *
   * The only irreversible thing this client can do, and it used to be two
   * unchecked `fetch` calls -- no confirmation, and a failure at either end
   * refreshed the list, showed the run still sitting there, and said nothing.
   * A player pressing Delete twice on a server that is refusing would have had
   * no way to tell the difference between "it will not go" and "it did not
   * take". `loadSave` and `saveNow` both throw and report; this now does too.
   *
   * The confirmation itself is in `Saves.jsx`, as a second press on the same
   * button rather than a `window.confirm`: a native dialog steals focus out of
   * the modal's trap and cannot be styled or read in this product's voice.
   */
  const deleteSave = useCallback(async (save) => {
    try {
      const gone = await fetch(`/api/saves/${save.save_id}`, { method: "DELETE" });
      if (!gone.ok) throw new Error(`server said ${gone.status}`);
      const res = await fetch("/api/saves");
      if (!res.ok) throw new Error(`server said ${res.status}`);
      const data = await res.json();
      dispatch({ type: "SAVES", saves: data.saves || [] });
    } catch (err) {
      dispatch({ type: "ERROR", message: `Could not delete that run: ${err.message}` });
    }
  }, []);

  /** Write the run to disk now, optionally into a named slot. Throws so the
      menu can report a failure rather than claiming it saved. */
  const saveNow = useCallback(
    async (slot) => {
      const res = await fetch("/api/saves", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: state.sessionId,
          save_id: state.saveId,
          slot: slot || "1",
        }),
      });
      if (!res.ok) throw new Error(`server said ${res.status}`);
      return res.json();
    },
    [state.sessionId, state.saveId]
  );

  const leaveRun = useCallback(
    (forget) => {
      // "New run" keeps the save reachable from the save browser; "abandon"
      // additionally makes this browser forget it, so the next reload does not
      // silently resume the thing you just walked away from.
      if (forget) clearSaveId();
      // The last move belonged to the run being left. Keeping it would aim a
      // retry at a session that no longer exists.
      again.current = null;
      setShowMenu(false);
      setOverlay(null);
      dispatch({ type: "RESET", storyInitial });
      dispatch({ type: "SCREEN", screen: "start" });
    },
    [storyInitial]
  );

  const updatePrefs = useCallback((next) => {
    setPrefs(next);
    savePrefs(next);
  }, []);

  const toggleMute = useCallback(() => {
    setPrefs((current) => {
      const next = { ...current, muted: !current.muted };
      savePrefs(next);
      return next;
    });
  }, []);

  // Preferences are applied at the root so CSS can act on them without every
  // component threading them through props.
  useEffect(() => {
    document.documentElement.dataset.textSize = prefs.textSize;
    document.documentElement.dataset.reduceMotion = String(prefs.reduceMotion);
  }, [prefs.textSize, prefs.reduceMotion]);

  // Global shortcuts, play screen only.
  //
  // Deliberately inert while anything modal is open: Modal's focus trap already
  // owns Esc for the topmost dialog (see hooks/useFocusTrap.js), and a second
  // handler here would close the dialog AND open the pause menu on one press.
  // `onboarding` is deliberately NOT in this list. It is only ever rendered on
  // the start screen, but it stays true for the whole session when a player
  // arrives straight into a resumed run — which made every shortcut on the
  // play screen permanently dead. `screen !== "scene"` already covers the case
  // where the cards are actually on screen.
  const blocked =
    Boolean(showMenu) || showSettings || Boolean(overlay) || Boolean(state.cutscene) ||
    state.screen !== "scene";

  // The overlays this story can currently open.
  //
  // An entry may declare `when(state)`, and it gates the WHOLE entry: no footer
  // button, no keyboard shortcut, no modal. That exists because a structural
  // system is something a story DECLARES -- the payload carries `threads` only
  // for a story with a threads table -- and a plugin can be borrowed by a story
  // that declares less than the one it was written for. Without this, borrowing
  // the Garden's skin bought you a scroll button that opens on nothing, which
  // is precisely the permanently-empty modal this seam exists to prevent.
  const overlays = useMemo(() => {
    const declared = story.overlays.filter((entry) =>
      entry.when ? entry.when(state) : true
    );
    // THE MAP IS CORE'S, and it is appended rather than merged over: a story
    // that declares its own `map` overlay has drawn something better for its
    // own world and must win. Gated on the story actually having a graph --
    // `world.location_id` is absent for a story with no places, and an empty
    // map button is the permanently-empty modal this seam exists to prevent.
    const hasOwn = declared.some((entry) => entry.id === "map");
    if (hasOwn || !state.world?.location_id) return declared;
    return [
      ...declared,
      { id: "map", key: "m", label: "The map", Icon: MapIcon, Component: MapScreen },
    ];
  }, [story, state]);

  // Story overlay keys, lowercased once: {j: "journal", ...}. An empty map is
  // the correct behaviour for a story with no overlays, not a missing feature.
  //
  // Keyed off the id LIST and not the array: the filter above runs per render,
  // so a fresh array identity every streamed token would re-bind the global
  // keydown listener sixty times a second for a map that had not changed.
  const overlayIds = overlays.map((entry) => entry.id).join(",");
  const overlayKeys = useMemo(() => {
    const map = {};
    for (const entry of overlays) {
      if (entry.key) map[entry.key.toLowerCase()] = entry.id;
    }
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlayIds]);

  useEffect(() => {
    function onKey(event) {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const tag = event.target?.tagName;
      const typing = tag === "INPUT" || tag === "TEXTAREA" || event.target?.isContentEditable;

      if (event.key === "Escape") {
        if (blocked) return;
        event.preventDefault();
        setShowMenu(true);
        return;
      }
      if (typing || blocked) return;

      if (event.key === "/") {
        event.preventDefault();
        composeRef.current?.focus();
        return;
      }
      const wanted = overlayKeys[event.key.toLowerCase()];
      if (wanted) {
        event.preventDefault();
        setOverlay(wanted);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [blocked, overlayKeys]);

  // A story that needs a React context around the whole client supplies
  // `Wrap`; the Garden uses it for analyst mode, which is read ten levels down
  // inside an ending card and has no business being threaded as a prop.
  const Wrap = story.Wrap || (({ children }) => children);

  if (state.screen === "saves") {
    return (
      <Wrap state={state}>
      <Saves
        saves={state.saves}
        error={state.error}
        onLoad={loadSave}
        onDelete={deleteSave}
        onClose={() => dispatch({ type: "SCREEN", screen: state.sessionId ? "scene" : "start" })}
        onNew={() => leaveRun(true)}
      />
      </Wrap>
    );
  }

  if (state.screen === "start") {
    return (
      <Wrap state={state}>
        <Start onBegin={begin} busy={state.busy} onOpenSaves={openSaves} story={story} />
        {onboarding && (
          <Onboarding
            cards={story.onboarding}
            title={story.onboardingTitle}
            finishLabel={story.onboardingFinishLabel}
            onDone={() => setOnboarding(false)}
          />
        )}
      </Wrap>
    );
  }

  // The run is over.
  //
  // Checked before Play rather than layered over it: the play screen would
  // still be offering choices and a compose box for a story that has ended,
  // and the engine refuses every action on a locked save -- so the player
  // would be typing into a turn that can no longer happen.
  //
  // Not keyed off `screen`, because the ending is not a place the player
  // navigates to and must survive a reconnect. It is cleared by RESET, which
  // is what beginning or loading a run does.
  if (state.ending) {
    const StoryEnding = story.Ending || Ending;
    return (
      <Wrap state={state}>
        <StoryEnding
          ending={state.ending}
          state={state}
          story={story}
          onNewRun={() => leaveRun(true)}
          onOpenSaves={openSaves}
        />
      </Wrap>
    );
  }

  // Read off the FILTERED list: an overlay whose `when` has since gone false --
  // a thread discharged while its scroll was open -- must close rather than
  // keep rendering against a payload key that is no longer there.
  const open = overlays.find((entry) => entry.id === overlay);
  const Overlay = open?.Component;
  const MenuBanner = story.MenuBanner;

  return (
    <Wrap state={state}>
      <Play
        state={state}
        story={story}
        overlays={overlays}
        onChoose={(choice) => send(choice.id, null, choice.text)}
        onCustom={(text) => send("custom", text, text)}
        onRetry={retry}
        onOpenSaves={openSaves}
        onOpenSettings={() => setShowSettings(true)}
        onOpenOverlay={setOverlay}
        onOpenMenu={() => setShowMenu(true)}
        onToggleReasoning={() => dispatch({ type: "REASONING_TOGGLE" })}
        muted={muted}
        onToggleMute={toggleMute}
        showDiceBreakdown={prefs.showDiceBreakdown}
        showReasoning={prefs.showReasoning}
        composeRef={composeRef}
      />

      {Overlay && (
        <Overlay
          state={state}
          sessionId={state.sessionId}
          busy={state.busy}
          // Using an item, crafting, dropping, striking a bargain -- all
          // ordinary turns. The engine stays the only writer of inventory,
          // gold and the clock.
          onAct={(text) => send("custom", text, text)}
          onClose={() => setOverlay(null)}
        />
      )}

      {state.cutscene && (
        <Cutscene
          cutscene={state.cutscene}
          onClose={() => dispatch({ type: "SOCKET", event: "cutscene_end", payload: {} })}
        />
      )}

      {showMenu && (
        <Menu
          world={state.world}
          banner={MenuBanner ? <MenuBanner state={state} /> : null}
          overlays={overlays}
          saveId={state.saveId}
          connected={state.connected}
          prefs={prefs}
          onChangePrefs={updatePrefs}
          onResume={() => setShowMenu(false)}
          onSaveNow={saveNow}
          onOpenSaves={() => {
            setShowMenu(false);
            openSaves();
          }}
          onOpenSettings={() => {
            setShowMenu(false);
            setShowSettings(true);
          }}
          onNewRun={() => leaveRun(false)}
          onAbandon={() => leaveRun(true)}
        />
      )}

      {showSettings && (
        <Settings
          prefs={prefs}
          onChange={updatePrefs}
          onClose={() => setShowSettings(false)}
        />
      )}

      <audio ref={audioRef} hidden />
    </Wrap>
  );
}
