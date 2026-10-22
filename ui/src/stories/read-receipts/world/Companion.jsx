/**
 * The companion card (v0.23.0 spec §14.1, T23): who the player is with in a scene -- portrait, name, the
 * stage's words and the closeness band's words. WORDS ONLY: it reads four named keys of `person` and draws
 * nothing else, so a number that ever reached the payload would still not be drawn.
 */
import React from "react";

export default function Companion({ person }) {
  if (!person || !person.pid) return null;
  const { name, stage_words: stage, closeness_words: closeness, portrait } = person;
  return (
    <div className="rr-companion" data-testid="rr-companion" aria-label={`With ${name}`}>
      {portrait ? <img className="rr-companion__portrait" src={portrait} alt="" draggable="false" /> : (
        <span className="rr-companion__portrait rr-companion__portrait--none" aria-hidden="true">{String(name || "?").slice(0, 1)}</span>
      )}
      <span className="rr-companion__text">
        <strong className="rr-companion__name">{name}</strong>
        {stage ? <span className="rr-companion__stage">{stage}</span> : null}
        {closeness ? <span className="rr-companion__close">{closeness}</span> : null}
      </span>
    </div>
  );
}

/** The household card: who lives with the player and where they are now, in words (`world.household`). */
export function Household({ household }) {
  if (!household || !household.pid) return null;
  return (
    <p className="rr-household" data-testid="rr-household">
      {household.portrait ? <img className="rr-companion__portrait" src={household.portrait} alt="" draggable="false" /> : null}
      <span>{household.name} lives with you, and is {household.where}.</span>
    </p>
  );
}
