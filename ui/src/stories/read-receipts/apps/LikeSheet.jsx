/**
 * A like with a comment (spec §7.1: `like {on, comment}` and
 * `like_back {comment}`, a comment at most 140 characters). The sheet keeps
 * what was written until the like is answered; one that never went comes
 * back here with its words and "Not sent — tap to retry" (spec §18.2).
 */
import React, { useEffect, useRef, useState } from "react";

/** The catalogue's cap on a like's comment (engine/social/matching.py COMMENT_MAX). */
export const COMMENT_MAX = 140;

export default function LikeSheet({ title, what, initial = "", notSent = false, onSend, onRetry, onCancel, sendLabel = "Send like" }) {
  const [text, setText] = useState(initial);
  const box = useRef(null);
  useEffect(() => setText(initial), [initial]);
  // Focus goes into the sheet, and back to what opened it when it closes.
  useEffect(() => {
    const opener = typeof document !== "undefined" ? document.activeElement : null;
    box.current?.focus?.();
    return () => {
      if (opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
    };
  }, []);
  const over = text.length > COMMENT_MAX;
  // Escape closes the sheet (and is taken: core's Escape would only leave the field).
  const onKeyDown = (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    onCancel();
  };
  return (
    <div className="rr-sheet" role="dialog" aria-modal="true" aria-label={title} onKeyDown={onKeyDown}>
      <h3 className="rr-sheet__title">{title}</h3>
      {what && <p className="rr-sheet__what">{what}</p>}
      <label className="rr-field">
        <span className="rr-field__label">Add a comment (optional)</span>
        <textarea
          ref={box}
          className="rr-input rr-input--area"
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-describedby="rr-like-count"
        />
      </label>
      <p id="rr-like-count" className={`rr-count${over ? " is-over" : ""}`}>
        {text.length}/{COMMENT_MAX}
      </p>
      {notSent && (
        <button type="button" className="rr-notsent" disabled={over} onClick={() => !over && onRetry(text.trim())}>
          Not sent — tap to retry
        </button>
      )}
      <div className="rr-sheet__actions">
        <button type="button" className="rr-btn rr-btn--quiet" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="rr-btn" disabled={over} onClick={() => onSend(text.trim())}>
          {sendLabel}
        </button>
      </div>
    </div>
  );
}
