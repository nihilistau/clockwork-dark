/**
 * ContractScroll — a bargain with three answers.
 *
 * "Contracts appear as illuminated manuscripts with living ink; player can
 * annotate 'I understand / I refuse / I renegotiate.'" The bargain flow is
 * Offer -> Terms -> Seal -> Thread, and a Thread persists "until discharged,
 * broken (costly), or transformed".
 *
 * THE THREE ACTIONS ARE PEERS
 * ---------------------------
 * Accept / Renegotiate / Refuse are drawn at the same size, in the same row, in
 * the same control. Renegotiate is not a softer refusal and it is not a "not
 * now" -- it is the move that changes the terms, and in this story it is the
 * one a player is most often supposed to reach for. Rendering it as a link
 * under two buttons would teach the opposite in the first five seconds.
 *
 * Refuse carries the danger palette (cold silver, per the art set's refuse
 * seal) without changing its hit geometry, which is the rule in
 * 09-UI-COMPONENT-KIT's state matrix.
 *
 * The terms are the load-bearing content, not decoration: every term is a row
 * with its own tag, so a player can point at the clause they want changed. That
 * is what makes Renegotiate mean something -- `onRenegotiate` is handed the
 * term the player selected, or null for "the whole thing".
 *
 * `ink` is per-faction, from the day scripts: gold is the Garden's own hand,
 * silver is Ashen Vale's.
 */
import React, { useState } from "react";

import { WaxSealButton } from "./Buttons.jsx";

export default function ContractScroll({
  title = "A Bargain",
  offeredBy,
  preamble,
  terms = [],
  seal = "a word",
  ink = "gold",
  busy = false,
  onAccept,
  onRenegotiate,
  onRefuse,
}) {
  // Which clause the player has their finger on. Null means the whole contract,
  // which is a legitimate thing to renegotiate and not an unset state.
  const [picked, setPicked] = useState(null);

  return (
    <section className="scroll" data-ink={ink} aria-label={title}>
      <header className="scroll__head">
        <h2 className="scroll__title">{title}</h2>
        {offeredBy && <p className="scroll__by">offered by {offeredBy}</p>}
      </header>

      {preamble && <p className="scroll__preamble">{preamble}</p>}

      <ol className="scroll__terms">
        {terms.map((term) => {
          const on = picked === term.id;
          return (
            <li key={term.id} className={`term ${on ? "is-picked" : ""}`}>
              <button
                type="button"
                className="term__pick"
                aria-pressed={on}
                onClick={() => setPicked(on ? null : term.id)}
              >
                <span className="term__tag">{term.tag}</span>
                <span className="term__text">{term.text}</span>
                {term.cost && <span className="term__cost">{term.cost}</span>}
              </button>
            </li>
          );
        })}
      </ol>

      <p className="scroll__seal-note">
        Sealed with <b>{seal}</b>. A thread holds until it is discharged, broken
        at cost, or turned into something else.
      </p>

      <div className="scroll__actions" role="group" aria-label="Answer the bargain">
        <WaxSealButton
          action="accept"
          disabled={busy}
          onClick={() => onAccept?.(picked)}
        />
        <WaxSealButton
          action="renegotiate"
          disabled={busy}
          onClick={() => onRenegotiate?.(picked)}
        />
        <WaxSealButton
          action="refuse"
          disabled={busy}
          onClick={() => onRefuse?.()}
        />
      </div>

      <p className="scroll__hint">
        {picked
          ? "Renegotiating the marked clause."
          : "Mark a clause to renegotiate it, or renegotiate the whole hand."}
      </p>
    </section>
  );
}
