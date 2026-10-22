/**
 * A line of the thread that is nobody's bubble (spec §18.2): the engine's
 * own lines (`system`: a match, an unmatch, a stage), and the player's asks
 * and answers (`request` messages), told in words. (v0.23.0 T22: a counter-offer's
 * "Accept" button is gone with the v0.22 meet-up slots.)
 */
import React from "react";

import { askLine } from "./media.js";

const ANSWER_WORDS = { yes: "You said yes.", no: "You said no.", later: "You said maybe later." };

export function requestLine(m, name) {
  if (m.answer) return ANSWER_WORDS[m.answer] || "You answered.";
  return askLine(m.ask, name, m.from === "player");
}

export default function SystemLine({ m, name }) {
  // A recap not yet written is "…", like any unvoiced message (spec §11.1, §14.4).
  const text =
    m.kind === "request" ? requestLine(m, name) : m.pending ? "…" : (Array.isArray(m.bubbles) ? m.bubbles : []).join(" ");
  if (!text) return null;
  return (
    <li className={`rr-msg rr-msg--system${m.kind === "recap" ? " rr-msg--recap" : ""}`} data-testid={`msg-${m.id}`}>
      {text}
    </li>
  );
}
