/**
 * The phone's one confirm (T29 review M4, M5): an `alertdialog` whose
 * question is its description (`aria-describedby`), focus on the safe
 * answer when it opens, and Escape taken as that answer -- kept inside the
 * phone, so core never reads it as "open the menu". The caller returns focus
 * to whatever opened it.
 *
 * An open confirm also pauses "Let time pass" (settings/letTimePass.js finds
 * it by its role).
 */
import React, { useEffect, useId, useRef } from "react";

export default function Confirm({ label, ask, yes, no = "Cancel", busy = false, onYes, onNo, testId = undefined }) {
  const safe = useRef(null);
  const askId = useId();
  useEffect(() => {
    safe.current?.focus?.();
  }, []);
  const onKeyDown = (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    onNo();
  };
  return (
    <div className="rr-confirm" role="alertdialog" aria-label={label} aria-describedby={askId} data-testid={testId} onKeyDown={onKeyDown}>
      <p className="rr-confirm__ask" id={askId}>
        {ask}
      </p>
      <div className="rr-card__actions">
        <button type="button" className="rr-btn rr-btn--small rr-btn--danger" disabled={busy} onClick={onYes}>
          {yes}
        </button>
        <button ref={safe} type="button" className="rr-btn rr-btn--small rr-btn--quiet" onClick={onNo}>
          {no}
        </button>
      </div>
    </div>
  );
}
