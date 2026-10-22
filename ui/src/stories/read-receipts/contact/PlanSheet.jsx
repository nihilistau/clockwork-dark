/**
 * Ask someone to meet (v0.23.0 spec §9, §14.2): a plan has NO set time, only a time of day in words. So the
 * sheet offers three asks -- "Free now?", "Tonight?" and "Sometime soon" -- each `ask {what: meet, when}` to
 * the thread, with an optional kind ("Drinks", "A walk", "At their place") and an optional place. Left
 * unchosen, the engine picks (`places.pick_venue`, by what they share). The person decides at their read,
 * and says so in the thread, in words (rule 1): the sheet never guesses the odds.
 */
import React, { useState } from "react";

/** A plan kind in the player's words (plans.yaml `kinds`). */
export const KIND_WORDS = {
  coffee: "Coffee",
  drinks: "Drinks",
  dinner: "Dinner",
  walk: "A walk",
  visit: "A visit",
  film: "A film",
  climbing: "Climbing",
  games: "Games",
  gig: "A gig",
  their_place: "At their place",
  your_place: "At yours",
};

/** When a plan is, as an ask. */
export const WHEN_ASKS = [
  ["now", "Free now?"],
  ["tonight", "Tonight?"],
  ["soon", "Sometime soon"],
];

const HOME_KINDS = ["their_place", "your_place"];

export default function PlanSheet({ pid = "", threadId, venues = [], kinds = Object.keys(KIND_WORDS), act, busy = false, onDone = null }) {
  const [kind, setKind] = useState("");
  const [venue, setVenue] = useState("");
  const home = HOME_KINDS.includes(kind);
  const send = (when) => {
    const args = { what: "meet", when };
    if (kind) args.kind = kind;
    if (venue && !home) args.venue = venue;
    act({ action: "ask", target: threadId, args, text: "" });
    if (onDone) onDone();
  };
  return (
    <div className="rr-plan" role="group" aria-label="Ask to meet up" data-testid={`plan-sheet-${pid || threadId}`}>
      <label className="rr-field">
        <span className="rr-field__label">What</span>
        <select className="rr-input" value={kind} onChange={(e) => setKind(e.target.value)} data-testid="plan-kind">
          <option value="">Anything</option>
          {kinds.map((k) => (
            <option key={k} value={k}>
              {KIND_WORDS[k] || k}
            </option>
          ))}
        </select>
      </label>
      {!home && venues.length > 0 && (
        <label className="rr-field">
          <span className="rr-field__label">Where</span>
          <select className="rr-input" value={venue} onChange={(e) => setVenue(e.target.value)} data-testid="plan-venue">
            <option value="">Wherever suits</option>
            {venues.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="rr-card__actions">
        {WHEN_ASKS.map(([when, words]) => (
          <button key={when} type="button" className="rr-btn rr-btn--small" disabled={busy} onClick={() => send(when)}>
            {words}
          </button>
        ))}
        {onDone && (
          <button type="button" className="rr-btn rr-btn--small rr-btn--quiet" onClick={onDone}>
            Not now
          </button>
        )}
      </div>
    </div>
  );
}
