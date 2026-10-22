/**
 * The buzz banner (v0.23.0 spec §8.2, §14.1): the phone is down and it has buzzed. Draws the count and the
 * names of who it was, and nothing else -- never a message's words, never a key of `buzz` it does not name.
 * Picking up the phone is the one way out.
 */
import React from "react";

export default function Buzz({ buzz, onPickUp }) {
  const count = buzz && Number.isFinite(buzz.count) ? buzz.count : 0;
  if (count <= 0) return null;
  const who = Array.isArray(buzz.who) ? buzz.who.filter((n) => typeof n === "string" && n) : [];
  return (
    <div className="rr-buzz" role="status" data-testid="rr-buzz">
      <span className="rr-buzz__text">
        Your phone buzzed{count > 1 ? ` ${count} times` : ""}
        {who.length ? `: ${who.join(", ")}` : ""}
      </span>
      <button type="button" className="rr-buzz__pick" onClick={onPickUp}>
        Pick it up
      </button>
    </div>
  );
}
