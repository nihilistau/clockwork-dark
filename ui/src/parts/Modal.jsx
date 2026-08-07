/**
 * The one overlay shell.
 *
 * Saves and Settings each hand-rolled a `role="dialog"` div with no focus
 * trap, no Esc and no focus restore. Rather than fix that three more times for
 * the journal, the codex and the barter screen, every overlay now goes through
 * here and inherits all three from useFocusTrap.
 */
import React from "react";
import useFocusTrap from "../hooks/useFocusTrap.js";

export default function Modal({ title, onClose, children, footer, wide = false }) {
  const ref = useFocusTrap(onClose);

  return (
    <div className="overlay">
      <div
        className={`overlay__card ${wide ? "overlay__card--wide" : ""}`}
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
      >
        <header className="overlay__head">
          <h2 className="overlay__title">{title}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="overlay__body">{children}</div>

        {footer && <div className="overlay__foot">{footer}</div>}
      </div>
    </div>
  );
}
