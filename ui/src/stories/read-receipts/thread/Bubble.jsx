/**
 * One message in a thread (spec §18.2): its media tile, its bubbles and its
 * time. A message not yet voiced shows "…" (spec §11.1) -- never its words,
 * which the payload does not carry until they are written. Their no to an
 * ask whose engine reason was the gate (`declined: "not_yet"`) says "Not yet."
 */
import React from "react";

import { stampOf } from "../phone/format.js";
import MediaTile, { MEDIA_KINDS } from "./MediaTile.jsx";

export default function Bubble({ m, now }) {
  const mine = m.from === "player";
  const media = !m.pending && (m.media || MEDIA_KINDS.includes(m.kind));
  const bubbles = m.pending ? ["…"] : Array.isArray(m.bubbles) ? m.bubbles : [];
  return (
    <li className={`rr-msg${mine ? " rr-msg--mine" : ""}`} data-testid={`msg-${m.id}`}>
      {media && <MediaTile message={m} />}
      {bubbles.map((text, i) => (
        <span key={i} className="rr-bubble">
          {text}
        </span>
      ))}
      {m.declined === "not_yet" && <span className="rr-msg__note">Not yet.</span>}
      <span className="rr-msg__at">{stampOf(m.at, now)}</span>
    </li>
  );
}
