/**
 * Push-to-talk for the compose row.
 *
 * THE GAP THIS CLOSES. `POST /api/voice/transcribe` has existed since the voice
 * blueprint landed and NOTHING in the client has ever called it. The route was
 * unreachable by a player: there was no microphone control anywhere in the UI,
 * so the entire speech-to-text path was dead code with a config key pointing at
 * it.
 *
 * IT NEVER SUBMITS. Hold, speak, release, and the transcript lands in the
 * compose box as ordinary editable text with the caret after it. The player
 * reads it and presses Send. This is not timidity: a mis-transcription that
 * auto-played a turn would be unrecoverable -- the engine has already advanced
 * the clock, spent stamina and possibly killed you, and no amount of "that is
 * not what I said" takes it back.
 *
 * THE FOUR FAILURES IT HAS TO SURVIVE
 *   permission denied   the player said no, or said no once and forgot
 *   no microphone       nothing is plugged in, or another app holds it
 *   transcription fails the provider is missing, dead, or heard nothing
 *   a slow request      the recording outlives its usefulness
 *
 * Each is a named state on the button with a message beside it, and every one
 * of them ends with the recorder stopped and the tracks released. A mic button
 * stuck reading "recording" with the OS indicator lit is worse than a mic
 * button that never worked, so the stop path runs from `finally` and from
 * unmount, not only from the happy path.
 *
 * INPUT. Pointer events cover mouse, touch and pen in one code path, with
 * capture so a release outside the button still stops the recording. The
 * keyboard affordance is hold-to-talk too: Space or Enter held down records,
 * releasing sends, Escape cancels without sending. Blur cancels, because a
 * button that kept recording after focus left it would be recording in secret.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";

import { transcribeAudio } from "../api.js";

/** Longest single utterance. Past this the recorder stops itself and sends. */
const MAX_SECONDS = 60;

/** Below this a "press" was a click, not speech. Sending it wastes a load. */
const MIN_MILLISECONDS = 250;

const LABEL = {
  idle: "Hold to speak",
  requesting: "Waiting for the microphone…",
  recording: "Listening — release to transcribe",
  sending: "Transcribing…",
  error: "Hold to speak",
  unsupported: "Speech input is not available in this browser",
};

/** Turn a getUserMedia rejection into something a player can act on. */
function micProblem(error) {
  switch (error?.name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Microphone blocked. Allow it for this page and try again.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "No microphone found.";
    case "NotReadableError":
      return "The microphone is busy in another app.";
    default:
      return error?.message || "The microphone could not be opened.";
  }
}

export default function MicButton({ sessionId, disabled = false, onTranscript }) {
  const supported =
    typeof window !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof window.MediaRecorder !== "undefined";

  const [state, setState] = useState(supported ? "idle" : "unsupported");
  const [message, setMessage] = useState("");

  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const startedAtRef = useRef(0);
  const abortRef = useRef(null);
  const stopTimerRef = useRef(null);
  // Set when a press is abandoned (Escape, blur, unmount). The stop handler
  // reads it and throws the audio away instead of transcribing it.
  const cancelledRef = useRef(false);
  // Guards every async continuation after unmount, so a transcript that arrives
  // for a screen nobody is looking at cannot setState on a dead component.
  const liveRef = useRef(true);

  const releaseStream = useCallback(() => {
    if (stopTimerRef.current) {
      clearTimeout(stopTimerRef.current);
      stopTimerRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
    chunksRef.current = [];
  }, []);

  useEffect(
    () => () => {
      liveRef.current = false;
      cancelledRef.current = true;
      abortRef.current?.abort();
      try {
        if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      } catch {
        /* a recorder that is already dead is the state we wanted */
      }
      releaseStream();
    },
    [releaseStream]
  );

  const send = useCallback(
    async (blob) => {
      const controller = new AbortController();
      abortRef.current = controller;
      setState("sending");
      setMessage("");
      try {
        const transcript = await transcribeAudio(sessionId, blob, {
          signal: controller.signal,
        });
        if (!liveRef.current) return;
        if (!transcript.trim()) {
          setState("error");
          setMessage("Nothing was heard.");
          return;
        }
        setState("idle");
        onTranscript?.(transcript.trim());
      } catch (err) {
        if (!liveRef.current || err?.name === "AbortError") return;
        setState("error");
        setMessage(err?.message || "Could not transcribe that.");
      } finally {
        abortRef.current = null;
      }
    },
    [onTranscript, sessionId]
  );

  const stop = useCallback(
    ({ cancel = false } = {}) => {
      if (cancel) cancelledRef.current = true;
      const recorder = recorderRef.current;
      if (!recorder) {
        // Still inside getUserMedia: mark it abandoned and let the resolver
        // find the flag and tear the stream down itself.
        if (cancel && state === "requesting") setState("idle");
        return;
      }
      if (recorder.state === "recording") {
        recorder.stop(); // onstop does the rest, including releasing the mic
      }
    },
    [state]
  );

  const start = useCallback(async () => {
    if (!supported || disabled || state === "recording" || state === "requesting") return;
    cancelledRef.current = false;
    setMessage("");
    setState("requesting");

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      if (!liveRef.current) return;
      setState("error");
      setMessage(micProblem(err));
      return;
    }

    // The press ended (or the screen went away) while the permission prompt was
    // up. Do not open a hot microphone nobody asked for any more.
    if (!liveRef.current || cancelledRef.current) {
      stream.getTracks().forEach((track) => track.stop());
      if (liveRef.current) setState("idle");
      return;
    }

    let recorder;
    try {
      recorder = new MediaRecorder(stream);
    } catch (err) {
      stream.getTracks().forEach((track) => track.stop());
      setState("error");
      setMessage(err?.message || "This browser cannot record audio.");
      return;
    }

    streamRef.current = stream;
    recorderRef.current = recorder;
    chunksRef.current = [];
    startedAtRef.current = Date.now();

    recorder.ondataavailable = (event) => {
      if (event.data?.size) chunksRef.current.push(event.data);
    };
    recorder.onerror = () => {
      releaseStream();
      if (!liveRef.current) return;
      setState("error");
      setMessage("The recording failed.");
    };
    recorder.onstop = () => {
      const parts = chunksRef.current;
      const type = recorder.mimeType || "audio/webm";
      const heldFor = Date.now() - startedAtRef.current;
      const abandoned = cancelledRef.current;
      releaseStream();
      if (!liveRef.current) return;
      if (abandoned) {
        setState("idle");
        return;
      }
      if (heldFor < MIN_MILLISECONDS || !parts.length) {
        setState("idle");
        setMessage("Hold the button while you speak.");
        return;
      }
      send(new Blob(parts, { type }));
    };

    recorder.start();
    setState("recording");

    // A recorder nobody stopped is a recorder that runs until the tab closes.
    stopTimerRef.current = setTimeout(() => stop(), MAX_SECONDS * 1000);
  }, [disabled, releaseStream, send, state, stop, supported]);

  const recording = state === "recording" || state === "requesting";
  const busy = state === "sending";
  const note = message || (state === "recording" ? LABEL.recording : "");

  return (
    <>
      <button
        type="button"
        className="mic"
        data-state={state}
        aria-pressed={recording}
        aria-label={LABEL[state] || LABEL.idle}
        title={LABEL[state] || LABEL.idle}
        disabled={!supported || disabled || busy}
        onPointerDown={(event) => {
          // Left button / touch / pen only, and keep the press even if the
          // pointer wanders off the button before it is released.
          if (event.button !== 0) return;
          event.preventDefault();
          event.currentTarget.setPointerCapture?.(event.pointerId);
          start();
        }}
        onPointerUp={() => stop()}
        onPointerCancel={() => stop({ cancel: true })}
        onKeyDown={(event) => {
          if (event.key === "Escape" && recording) {
            stop({ cancel: true });
            return;
          }
          if (event.key !== " " && event.key !== "Enter") return;
          // Held keys autorepeat; only the first press starts anything.
          if (event.repeat) return;
          event.preventDefault();
          start();
        }}
        onKeyUp={(event) => {
          if (event.key !== " " && event.key !== "Enter") return;
          event.preventDefault();
          stop();
        }}
        onBlur={() => recording && stop({ cancel: true })}
      >
        <span className="mic__glyph" aria-hidden="true">
          {busy ? "…" : "●"}
        </span>
        <span className="mic__text">{busy ? "Transcribing" : "Speak"}</span>
      </button>

      {/* Polite, not assertive: this narrates a control the player is already
          holding, and an assertive region would interrupt them mid-press. */}
      <span className="mic__note" role="status" aria-live="polite" data-state={state}>
        {note}
      </span>
    </>
  );
}
