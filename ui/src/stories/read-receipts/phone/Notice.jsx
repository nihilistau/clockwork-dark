/**
 * The in-phone notice (v0.24.0 T14 d2, spec §7: a sound is never the only signal). Two things sound while the
 * phone is up and the thread they belong to is not on screen, and each needs something to look at:
 *
 * - `message`: a person wrote in another thread (the notification tone). The notice names them and shows the
 *   same preview the lock screen would; tapping it opens that thread.
 * - `match`: a like came back (the match chime). "It's a match" with their name; tapping opens the new chat.
 *
 * It appears with its sound, dismisses itself after `NOTICE_MS`, and has a close button. Words only: a name and
 * the preview the payload already shows on the lock screen.
 */
import React, { useEffect } from "react";

export const NOTICE_MS = 6000;

export default function Notice({ notice, onOpen, onDismiss }) {
  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(onDismiss, NOTICE_MS);
    return () => clearTimeout(timer);
  }, [notice, onDismiss]);
  if (!notice) return null;
  const match = notice.kind === "match";
  return (
    <div className={`rr-notice rr-notice--${notice.kind}`} role="status" data-testid="rr-notice">
      <button type="button" className="rr-notice__open" onClick={() => onOpen(notice.thread_id)}>
        <span className="rr-notice__head">{match ? "It's a match" : notice.name || "New message"}</span>
        <span className="rr-notice__text">{match ? `You and ${notice.name || "someone new"} liked each other.` : notice.preview}</span>
      </button>
      <button type="button" className="rr-notice__close" aria-label="Dismiss" onClick={onDismiss}>
        <span aria-hidden="true">×</span>
      </button>
    </div>
  );
}
