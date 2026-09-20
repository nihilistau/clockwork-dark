/**
 * Framing for an in-progress challenge or dealt card.
 *
 * The options already arrive as ordinary choice chips. What was missing is
 * the "step 2 of 4" / "card 3 of 7" line that tells the player these turns
 * are one thing, not four unrelated ones. This is that line. It invents
 * nothing: titles, cursors and lengths come from the turn payload.
 */
import React from "react";

function pretty(id) {
  return String(id || "").replace(/_/g, " ");
}

export default function BeatFrame({ world }) {
  const challenge = world?.challenge;
  if (challenge && Object.keys(challenge).length > 0) {
    const steps = Array.isArray(challenge.steps) ? challenge.steps : [];
    const total = Number(challenge.total_steps) || steps.length;
    const step = Number(challenge.step) || 0;
    const title = challenge.title || pretty(challenge.id);
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
  const cards = scene?.card_ids;
  if (scene && Array.isArray(cards) && cards.length > 0) {
    const cursor = Number(scene.cursor) || 0;
    return (
      <p className="beatframe" role="status">
        <span className="beatframe__kind">
          Card {cursor + 1} of {cards.length}
        </span>
        {scene.deck_id ? <span className="beatframe__title">{pretty(scene.deck_id)}</span> : null}
      </p>
    );
  }

  return null;
}
