/**
 * Choice chips with keyboard 1-4.
 *
 * The number badges were specified in the design system, the component docs and
 * the brief, and existed in none of them. Binding the keys is what makes the
 * badges honest.
 */
import React, { useEffect } from "react";

const HINT_LABEL = {
  safe: "quiet",
  risky: "risky",
  costly: "costly",
  unknown: "unknown",
};

export default function ChoiceRow({ choices, busy, onChoose, settled = false }) {
  useEffect(() => {
    if (busy) return undefined;
    function onKey(event) {
      // Never steal a digit the player is typing into the action box.
      const tag = event.target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || event.metaKey || event.ctrlKey) return;
      const index = Number(event.key) - 1;
      if (Number.isInteger(index) && index >= 0 && index < choices.length) {
        event.preventDefault();
        onChoose(choices[index]);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [choices, busy, onChoose]);

  // A settled turn that offered nothing.
  //
  // This used to render `null`, so the band above the compose box simply went
  // away and the screen read as broken rather than as open. It is a state the
  // engine reaches honestly -- a scene that ends on a question, a narrator that
  // offered none, an answer that came back without its envelope -- and the
  // compose box below is still the right move. So say that, rather than
  // vanish. Silent while the turn is still running: nothing is missing yet.
  if (!choices.length) {
    if (!settled) return null;
    return (
      <p className="choices__empty" role="status">
        Nothing is offered. The next move is yours to name.
      </p>
    );
  }

  return (
    <div className="choices" role="group" aria-label="Choices">
      {choices.map((choice, index) => (
        <button
          key={choice.id}
          type="button"
          className="chip"
          disabled={busy}
          data-hint={choice.hint || "unknown"}
          onClick={() => onChoose(choice)}
        >
          <span className="chip__key" aria-hidden="true">
            {index + 1}
          </span>
          <span className="chip__text">{choice.text}</span>
          {choice.hint && choice.hint !== "unknown" && (
            <span className="chip__hint">{HINT_LABEL[choice.hint]}</span>
          )}
        </button>
      ))}
    </div>
  );
}
