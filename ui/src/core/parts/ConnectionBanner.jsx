/**
 * What the connection is doing, in words (spec §6.3). A fixed strip below
 * the header on every screen (plan decision 9), never the footer's 10px dot.
 * Its words are constant per state; a countdown, when the client scheduled
 * the retry itself (plan decision 13), is a separate aria-hidden span so a
 * screen reader hears the sentence once (Review 22). "Reconnected." clears
 * itself after 4 s.
 */
import React, { useEffect, useState } from "react";

export const RECONNECTED_MS = 4000;

const LABELS = { try: "Try now", resume: "Resume", play: "Play here", again: "Try again" };

export default function ConnectionBanner({ banner, onTry, onResume, onPlayHere, onAgain, onSignIn, onDismiss }) {
  const [now, setNow] = useState(() => Date.now());
  const retryAt = banner?.retryAt || null;

  useEffect(() => {
    if (!retryAt) return undefined;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [retryAt]);

  useEffect(() => {
    if (banner?.kind !== "reconnected") return undefined;
    const timer = setTimeout(() => onDismiss?.(), RECONNECTED_MS);
    return () => clearTimeout(timer);
  }, [banner, onDismiss]);

  const seconds = retryAt ? Math.max(0, Math.ceil((retryAt - now) / 1000)) : null;
  const press = banner ? { try: onTry, resume: onResume, play: onPlayHere, again: onAgain }[banner.action] : null;

  const box = banner && (
    <div className={`linkbanner linkbanner--${banner.kind}`}>
      <span className="linkbanner__text">
        {banner.text}
        {banner.detail ? ` (${banner.detail})` : ""}
      </span>
      {seconds !== null && (
        <span className="linkbanner__count" aria-hidden="true">
          Trying again in {seconds} s.
        </span>
      )}
      {banner.action === "signin" ? (
        <a className="linkbanner__action" href="/" onClick={(event) => { event.preventDefault(); onSignIn?.(); }}>
          Sign in again
        </a>
      ) : (
        press && (
          <button type="button" className="linkbanner__action btn btn--ghost" onClick={press}>
            {LABELS[banner.action]}
          </button>
        )
      )}
    </div>
  );

  // Two live regions, always mounted and empty at rest (review 6): a polite
  // region inserted WITH its words is not announced by many screen readers,
  // and one element switching from `status` to `alert` is unreliable too. The
  // banner is put INSIDE the region its role names, on change.
  return (
    <>
      <div className="linkbanner__region" role="status">{banner?.role === "status" ? box : null}</div>
      <div className="linkbanner__region" role="alert">{banner?.role === "alert" ? box : null}</div>
    </>
  );
}
