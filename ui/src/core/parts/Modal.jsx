/**
 * The one overlay shell.
 *
 * Saves and Settings each hand-rolled a `role="dialog"` div with no focus
 * trap, no Esc and no focus restore. Rather than fix that three more times for
 * the journal, the codex and the barter screen, every overlay now goes through
 * here and inherits all three from useFocusTrap.
 */
import React, { useEffect } from "react";
import useFocusTrap from "../hooks/useFocusTrap.js";
import { playSound } from "../sound/index.js";

// How many Modals have opened. A Modal that closes in the same action another opens (the pause menu to Settings
// or Saves) yields to the new one's ui.open: one click, one sound.
let opened = 0;

export default function Modal({ title, onClose, children, footer, wide = false }) {
  const ref = useFocusTrap(onClose);

  // ui.open on mount, ui.close on unmount: every way out sounds once (the close button is data-sound="none").
  useEffect(() => {
    opened += 1;
    playSound("ui.open");
    return () => {
      const at = opened;
      // The next Modal's mount effect runs in this same commit, before this microtask.
      queueMicrotask(() => { if (opened === at) playSound("ui.close"); });
    };
  }, []);

  // Clicking the backdrop closes, which is what every player already expects
  // and what the overlay previously did not do -- only Esc and the ✕ worked.
  // It fires on the backdrop element itself only, so a click that started
  // inside the card and drifted out (selecting text, dragging a scrollbar)
  // does not dismiss the dialog under the player's hand.
  function onBackdrop(event) {
    if (event.target === event.currentTarget) onClose();
  }

  return (
    <div className="overlay" onMouseDown={onBackdrop}>
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
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close" data-sound="none">
            ✕
          </button>
        </header>

        <div className="overlay__body">{children}</div>

        {footer && <div className="overlay__foot">{footer}</div>}
      </div>
    </div>
  );
}
