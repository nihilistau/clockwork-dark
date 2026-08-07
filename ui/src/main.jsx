/**
 * The Clockwork Dark — client entry.
 */
import React, { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

import Cutscene from "./parts/Cutscene.jsx";
import Onboarding, { shouldOnboard } from "./parts/Onboarding.jsx";
import Codex from "./screens/Codex.jsx";
import Journal from "./screens/Journal.jsx";
import Saves from "./screens/Saves.jsx";
import Scene from "./screens/Scene.jsx";
import Settings, { loadPrefs, savePrefs } from "./screens/Settings.jsx";
import Start from "./screens/Start.jsx";
import Trade from "./screens/Trade.jsx";
import { clearSaveId, connect, loadSaveId, storeSaveId } from "./socket.js";
import { initialState, reducer } from "./store.js";

import "./styles/index.css";

// A turn can legitimately take a while on a local model. This is the last line
// of defence against a server that dies without emitting anything: the old
// client left every control disabled forever with nothing on screen.
const TURN_WATCHDOG_MS = 240000;

function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [prefs, setPrefs] = useState(loadPrefs);
  const [showSettings, setShowSettings] = useState(false);
  // One overlay at a time: journal | codex | trade | null. Two dialogs open at
  // once would mean two focus traps fighting over the same document.
  const [overlay, setOverlay] = useState(null);
  const [onboarding, setOnboarding] = useState(shouldOnboard);
  const muted = prefs.muted;
  const socketRef = useRef(null);
  const audioRef = useRef(null);
  const watchdog = useRef(null);

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

  useEffect(() => {
    document.body.dataset.phase = state.phase || "dormant";
  }, [state.phase]);

  useEffect(() => {
    if (watchdog.current) clearTimeout(watchdog.current);
    if (state.busy) {
      watchdog.current = setTimeout(() => {
        dispatch({ type: "ERROR", message: "No answer from the world. Try again." });
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
    player.play().catch(() => {});
  }, [state.audio, muted]);

  const begin = useCallback(async (payload) => {
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
      dispatch({ type: "SUBMIT", text: echo });
      socketRef.current?.emit("player_choice", {
        session_id: state.sessionId,
        choice_id: choiceId,
        custom_text: customText || null,
      });
    },
    [state.busy, state.sessionId]
  );

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

  const loadSave = useCallback(async (save) => {
    try {
      const res = await fetch(`/api/saves/${save.save_id}/load`, { method: "POST" });
      if (!res.ok) throw new Error(`server said ${res.status}`);
      const data = await res.json();
      storeSaveId(data.save_id);
      socketRef.current?.emit("join_session", { session_id: data.session_id });
      dispatch({ type: "SCREEN", screen: "scene" });
    } catch (err) {
      dispatch({ type: "ERROR", message: `Could not load: ${err.message}` });
    }
  }, []);

  const deleteSave = useCallback(async (save) => {
    await fetch(`/api/saves/${save.save_id}`, { method: "DELETE" });
    const res = await fetch("/api/saves");
    const data = await res.json();
    dispatch({ type: "SAVES", saves: data.saves || [] });
  }, []);

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

  if (state.screen === "saves") {
    return (
      <Saves
        saves={state.saves}
        onLoad={loadSave}
        onDelete={deleteSave}
        onClose={() => dispatch({ type: "SCREEN", screen: state.sessionId ? "scene" : "start" })}
        onNew={() => {
          clearSaveId();
          dispatch({ type: "SCREEN", screen: "start" });
        }}
      />
    );
  }

  if (state.screen === "start") {
    return (
      <>
        <Start onBegin={begin} busy={state.busy} />
        {onboarding && <Onboarding onDone={() => setOnboarding(false)} />}
      </>
    );
  }

  return (
    <>
      <Scene
        state={state}
        onChoose={(choice) => send(choice.id, null, choice.text)}
        onCustom={(text) => send("custom", text, text)}
        onOpenSaves={openSaves}
        onOpenSettings={() => setShowSettings(true)}
        onOpenJournal={() => setOverlay("journal")}
        onOpenCodex={() => setOverlay("codex")}
        onOpenTrade={() => setOverlay("trade")}
        muted={muted}
        onToggleMute={toggleMute}
        showDiceBreakdown={prefs.showDiceBreakdown}
      />

      {overlay === "journal" && (
        <Journal sessionId={state.sessionId} onClose={() => setOverlay(null)} />
      )}

      {overlay === "codex" && (
        <Codex sessionId={state.sessionId} onClose={() => setOverlay(null)} />
      )}

      {overlay === "trade" && (
        <Trade
          sessionId={state.sessionId}
          busy={state.busy}
          onStrike={(text) => send("custom", text, text)}
          onClose={() => setOverlay(null)}
        />
      )}

      {state.cutscene && (
        <Cutscene
          cutscene={state.cutscene}
          onClose={() => dispatch({ type: "SOCKET", event: "cutscene_end", payload: {} })}
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
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);
