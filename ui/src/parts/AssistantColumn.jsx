/**
 * The Assistant column.
 *
 * `voice_style` was computed by the engine, serialized, shipped to the client
 * and ignored. A whisper should look like a whisper.
 */
import React, { useEffect, useState } from "react";

const FORM_GLYPH = {
  cat: "🐈",
  wanderer: "🜃",
  child: "🜁",
  tinker: "⚙",
  reflection: "◐",
};

const IDLE_LINES = [
  "Something watches from the stillness without moving.",
  "The wind has an opinion it is not sharing.",
  "Somewhere a clock is running slightly wrong.",
];

export default function AssistantColumn({ assistant, phase }) {
  const [shown, setShown] = useState(null);

  useEffect(() => {
    if (!assistant?.text) return undefined;
    setShown(assistant);
    // The Assistant is a presence, not a chat window: its line fades rather
    // than accumulating into a transcript.
    const timer = setTimeout(() => setShown(null), 22000);
    return () => clearTimeout(timer);
  }, [assistant]);

  const idle = IDLE_LINES[(phase || "dormant").length % IDLE_LINES.length];

  return (
    <aside className="assistant" aria-label="Companion">
      <p className="assistant__label">Assistant</p>

      {shown ? (
        <div
          className={`bubble bubble--${shown.voice_style || "flat"}`}
          role="status"
          aria-live="polite"
        >
          <span className="bubble__form">
            <span aria-hidden="true">{FORM_GLYPH[shown.form] || "◇"}</span> {shown.form}
          </span>
          <p className="bubble__text">{shown.text}</p>
        </div>
      ) : (
        <div className="assistant__silent" aria-hidden="true" />
      )}

      <p className="assistant__idle">{idle}</p>
    </aside>
  );
}
