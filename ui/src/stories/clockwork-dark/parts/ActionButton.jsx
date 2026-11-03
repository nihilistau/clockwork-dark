/**
 * One overlay action (v0.25.0 §8.1): pressable only when the server lists the pair and no scene owns the
 * turn. `aria-disabled`, never `disabled` (focus stays), while a turn runs or the pair is not on offer.
 *
 * Whether a button is DRAWN is the caller's (an item's tags, a row on a counter); whether it can be
 * PRESSED is only ever the server's list (`GET /api/intents/overlay`), so a tag can never promise a press.
 *
 * `verb` is the button's own word ("Wear", "Take off"): the player's log line is "Wear: Wool cloak", never
 * the bare target label, so two verbs on one thing do not log alike (v0.25.0 T14). The server never reads it.
 */
import React from "react";
import { offerRow } from "@core/hooks/useOverlayIntents.js";

export default function ActionButton({ offer, action, target, busy, onAct, why = "", verb = "", children }) {
  const row = offerRow(offer, action, target);
  const live = Boolean(row) && !offer?.scene_owns_turn && !busy;
  return (
    <button
      type="button"
      className="btn btn--sm"
      aria-disabled={live ? undefined : "true"}
      title={!row && why ? why : undefined}
      onClick={() => {
        if (live) onAct({ action, target, label: verb ? `${verb}: ${row.label}` : row.label });
      }}
    >
      {children}
    </button>
  );
}

/** The line every overlay shows while a scene owns the turn. */
export const SceneOwnsTurn = ({ offer }) =>
  offer?.scene_owns_turn ? <p className="overlay__hold">Answer what is in front of you first.</p> : null;
