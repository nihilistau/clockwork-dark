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

export default function ChoiceRow({
  choices,
  busy,
  onChoose,
  settled = false,
  // True while an overlay owns the screen -- map, clues, journal, gallery, or
  // the pause menu. `Play` stays MOUNTED underneath every one of them, so this
  // window listener went on firing behind them: pressing "1" over the pause
  // menu submitted a turn the player could not see. App already computes this
  // for its own listener; it is threaded down rather than recomputed so there
  // is only ever one answer to "is the screen blocked".
  blocked = false,
}) {
  useEffect(() => {
    if (busy || blocked) return undefined;
    function onKey(event) {
      // Never steal a digit the player is typing into the action box.
      const tag = event.target?.tagName;
      if (
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        event.target?.isContentEditable ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey
      )
        return;
      const index = Number(event.key) - 1;
      if (Number.isInteger(index) && index >= 0 && index < choices.length) {
        event.preventDefault();
        onChoose(choices[index]);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [choices, busy, blocked, onChoose]);

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
          {/* What the ENGINE will do if this is picked, when the option
              declared an intent. The narrator chooses which options carry one
              and is told that a choice which is only talk carries none, but no
              grammar can read a sentence and tell conversation from movement:
              a measured turn put `travel -> afterdeck` on "Ask what is required
              of you today", and the player was moved while the prose had them
              sitting still. It cannot be made unsamplable, so it is made
              visible. The server writes this label from the same catalogue the
              intent enum was built from (engine/game/intents.py). */}
          {choice.intent_label && (
            <span className="chip__intent" title="What this will do">
              {choice.intent_label}
            </span>
          )}
          {choice.hint && choice.hint !== "unknown" && (
            <span className="chip__hint">{HINT_LABEL[choice.hint]}</span>
          )}
        </button>
      ))}
    </div>
  );
}
