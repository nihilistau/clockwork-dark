/**
 * A line of the thread that is nobody's bubble (spec §18.2): the engine's
 * own lines (`system`: a match, an unmatch, a stage), a meet-up's recap, and
 * the player's asks and answers (`request` messages), told in words.
 */
import React from "react";

import { askLine } from "./media.js";

const ANSWER_WORDS = { yes: "You said yes.", no: "You said no.", later: "You said maybe later." };

export function requestLine(m, name) {
  if (m.answer) return ANSWER_WORDS[m.answer] || "You answered.";
  return askLine(m.ask, name, m.from === "player");
}

export default function SystemLine({ m, name, pid = "", act = null, pending = null }) {
  // A recap not yet written is "…", like any unvoiced message (spec §11.1, §14.4).
  const text =
    m.kind === "request" ? requestLine(m, name) : m.pending ? "…" : (Array.isArray(m.bubbles) ? m.bubbles : []).join(" ");
  if (!text) return null;
  // A meet-up counter-offer still open is taken in one tap (T30 follow-up): the same `propose_meet`,
  // at the countered venue, day and slot. The engine decides again (rule 1); a refusal reaches the phone.
  const counter = m.counter && m.counter.open && act && pid ? m.counter : null;
  const busy = Boolean(pending && pending.action === "propose_meet");
  return (
    <li className={`rr-msg rr-msg--system${m.kind === "recap" ? " rr-msg--recap" : ""}`} data-testid={`msg-${m.id}`}>
      {text}
      {counter && (
        <span className="rr-card__actions rr-msg__actions">
          <button
            type="button"
            className="rr-btn rr-btn--small"
            aria-label={`Accept ${counter.when}`.trim()}
            disabled={busy}
            onClick={() => act({ action: "propose_meet", target: pid, args: { venue: counter.venue, day: counter.days_ahead, slot: counter.slot }, text: "" })}
          >
            Accept
          </button>
        </span>
      )}
    </li>
  );
}
