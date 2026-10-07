/**
 * Framing for an in-progress challenge or dealt card.
 *
 * The options already arrive as ordinary choice chips. What was missing is
 * the "step 2 of 4" / "card 3 of 7" line that tells the player these turns
 * are one thing, not four unrelated ones. This is that line. It invents
 * nothing: titles, cursors and lengths come from the turn payload.
 *
 * NEVER AN ID (v0.21.0 final review, finding 2): the header printed
 * `pretty(scene.deck_id)` -- "day 00 prologue" on every Wicked Garden card.
 * A card shows its authored title (`scene.card_title`, engine
 * `GameState._scene_block`), a challenge its `title`; without one, nothing
 * follows the count.
 */
import React from "react";

export default function BeatFrame({ world }) {
  const challenge = world?.challenge;
  if (challenge && Object.keys(challenge).length > 0) {
    const steps = Array.isArray(challenge.steps) ? challenge.steps : [];
    const total = Number(challenge.total_steps) || steps.length;
    const step = Number(challenge.step) || 0;
    const title = challenge.title || "";
    return (
      <p className="beatframe" role="status">
        <span className="beatframe__kind">
          {total > 0 ? `Step ${step + 1} of ${total}` : "Challenge"}
        </span>
        {title ? <span className="beatframe__title">{title}</span> : null}
      </p>
    );
  }

  const scene = world?.scene;
  // The payload carries the hand's size, never its card ids (finding 36).
  const count = Number(scene?.count) || 0;
  if (scene && count > 0) {
    const cursor = Number(scene.cursor) || 0;
    return (
      <p className="beatframe" role="status">
        <span className="beatframe__kind">
          Card {Math.min(cursor + 1, count)} of {count}
        </span>
        {scene.card_title ? <span className="beatframe__title">{scene.card_title}</span> : null}
      </p>
    );
  }

  return null;
}
