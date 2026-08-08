/**
 * The model, thinking, live.
 *
 * On this hardware the first narration token arrives 10-14 seconds into a
 * turn. The backend has always streamed reasoning on a channel separate from
 * narration and NOTHING CONSUMED IT, so those seconds were a blank screen with
 * three bouncing dots on it. This is the same three dots with the machine's
 * actual deliberation under them, and it folds itself away the moment there
 * are words to read.
 */
import React, { useEffect, useRef } from "react";

export default function ReasoningPanel({ text, open, busy, onToggle }) {
  const tail = useRef(null);

  // Follow the stream. Reasoning is long and the interesting part is always
  // the last line, not the first.
  useEffect(() => {
    if (open && tail.current) tail.current.scrollTop = tail.current.scrollHeight;
  }, [text, open]);

  if (!text && !busy) return null;

  return (
    <section className={`reasoning ${open ? "is-open" : "is-collapsed"}`}>
      <button
        type="button"
        className="reasoning__toggle"
        aria-expanded={open}
        onClick={onToggle}
        disabled={!text}
      >
        <span className="thinking__dot" />
        <span className="thinking__dot" />
        <span className="thinking__dot" />
        <span className="reasoning__label">
          {busy ? "the world is deciding" : "what the world was thinking"}
        </span>
        {text ? <span className="reasoning__chevron" aria-hidden="true">{open ? "▾" : "▸"}</span> : null}
      </button>

      {open && text && (
        <div className="reasoning__body" ref={tail} role="log" aria-live="off">
          <p className="reasoning__text">{text}</p>
        </div>
      )}
    </section>
  );
}

/** The bare indicator, for players who turned the thinking panel off. */
export function Thinking() {
  return (
    <p className="thinking" role="status">
      <span className="thinking__dot" />
      <span className="thinking__dot" />
      <span className="thinking__dot" />
      <span className="thinking__label">the world is deciding</span>
    </p>
  );
}
