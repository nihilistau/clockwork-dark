/**
 * The model, thinking, live.
 *
 * On this hardware the first narration token arrives 10-14 seconds into a
 * turn. The backend has always streamed reasoning on a channel separate from
 * narration and NOTHING CONSUMED IT, so those seconds were a blank screen with
 * three bouncing dots on it. This is the same three dots with the machine's
 * actual deliberation under them, and it folds itself away the moment there
 * are words to read.
 *
 * THE CLOCK, AND WHY IT IS NOT DECORATION
 * ---------------------------------------
 * That 10-14 seconds is the fast path. A reasoning narration model spends
 * 1100-2600 tokens of thinking BEFORE the first word of prose -- 106-205
 * seconds of wall clock, measured (config/default.yaml, profile `big`) -- and
 * for most of it the reasoning channel may be silent too. Three bouncing dots
 * held for two minutes is indistinguishable from a hang, and the honest signal
 * that something is still happening is elapsed time. It appears only once the
 * wait has stopped being ordinary, so a normal turn is not given a stopwatch.
 */
import React, { useEffect, useRef, useState } from "react";

// Below this a turn is just a turn. Above it, the player deserves to be told
// that the silence is expected.
const SLOW_AFTER_MS = 12000;

/**
 * Seconds this turn has been running, or 0 while it is still quick.
 *
 * Ticks once a second and only while busy: an interval left running behind a
 * settled turn is a render per second forever.
 */
function useElapsed(busy) {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    if (!busy) {
      setSeconds(0);
      return undefined;
    }
    const started = Date.now();
    const id = setInterval(() => {
      setSeconds(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [busy]);

  return seconds * 1000 >= SLOW_AFTER_MS ? seconds : 0;
}

/** "1:47", or "12s" under a minute. */
function clock(seconds) {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export default function ReasoningPanel({ text, open, busy, onToggle }) {
  const tail = useRef(null);
  const elapsed = useElapsed(busy);

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
        {/* The ticking number itself is never announced: a live region
            reading a new value every second is unusable. The reader gets one
            sentence instead, below. */}
        {elapsed > 0 && (
          <span className="reasoning__elapsed" aria-hidden="true">
            {clock(elapsed)}
          </span>
        )}
        {text ? <span className="reasoning__chevron" aria-hidden="true">{open ? "▾" : "▸"}</span> : null}
      </button>

      {/* ONE announcement, when the wait stops being ordinary.
          `Thinking` (which carries role="status") is only rendered for players
          who turned this panel OFF, so with the panel on a screen-reader user
          had nothing at all between pressing a choice and the first sentence
          of narration -- two minutes of silence on this hardware. The string
          is constant once set, so it is spoken once and does not repeat. */}
      <p className="visually-hidden" role="status">
        {elapsed > 0 ? "Still thinking. This can take a couple of minutes." : ""}
      </p>

      {/* Said once, when the wait stops being ordinary. Two minutes is normal
          on a local reasoning model and a player who does not know that is
          watching a broken game. */}
      {elapsed > 0 && !text && (
        <p className="reasoning__patience">
          Thinking, at length. A turn on a local model can take a couple of
          minutes before the first word arrives.
        </p>
      )}

      {open && text && (
        <div className="reasoning__body" ref={tail} role="log" aria-live="off">
          <p className="reasoning__text">{text}</p>
        </div>
      )}
    </section>
  );
}

/**
 * The bare indicator, for players who turned the thinking panel off.
 *
 * Takes the same clock. Turning the panel off is a preference about seeing the
 * model's deliberation, not a preference for being told less about whether the
 * game is alive.
 */
export function Thinking({ busy = true }) {
  const elapsed = useElapsed(busy);

  return (
    <p className="thinking" role="status">
      <span className="thinking__dot" />
      <span className="thinking__dot" />
      <span className="thinking__dot" />
      <span className="thinking__label">
        the world is deciding
        {/* aria-hidden inside a role="status": a live region that re-announces
            a new number every second is unusable, and "the world is deciding"
            is the part worth hearing. */}
        {elapsed > 0 && (
          <span className="thinking__elapsed" aria-hidden="true">
            {" · "}
            {clock(elapsed)}
          </span>
        )}
      </span>
    </p>
  );
}
