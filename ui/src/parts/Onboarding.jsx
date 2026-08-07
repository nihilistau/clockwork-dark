/**
 * Three cards, once.
 *
 * Not a tutorial. The three things a new player cannot discover by playing —
 * that the numbers are real and not narrated, that a quiet life is a finished
 * game rather than a failure, and that the Assistant is a character with its
 * own interests — are the three things that change how the whole run reads.
 *
 * Gated on a localStorage flag so it never appears twice. If storage is
 * unavailable (private browsing) the cards show every time, which is a far
 * better failure than a first-run screen that crashes the boot.
 */
import React, { useState } from "react";
import Modal from "./Modal.jsx";

const FLAG = "clockwork_onboarded";

const CARDS = [
  {
    title: "The dice are real",
    body:
      "Nothing here is decided by the storyteller's mood. Every roll, wound, coin and hour is resolved by the engine first, and the prose is written afterwards to match. When a check fails you will be shown the number and the reason it was not enough.",
  },
  {
    title: "A quiet life is a finished game",
    body:
      "You can bake bread for forty days, mend a roof, and never learn what is wrong with the wheat. That is not a failure state and nothing in the world punishes it. The dark keeps its own schedule whether you become a hero or a baker.",
  },
  {
    title: "The Assistant is not a narrator",
    body:
      "The companion at your left is a character inside the world, with its own patience, its own trust in you, and its own reasons. It is often useful. It is sometimes wrong. It occasionally lies. Weigh what it says the way you would weigh a stranger.",
  },
];

export function shouldOnboard() {
  try {
    return !window.localStorage.getItem(FLAG);
  } catch {
    return true;
  }
}

function markOnboarded() {
  try {
    window.localStorage.setItem(FLAG, "1");
  } catch {
    /* private browsing — the cards will show again, which is harmless */
  }
}

export default function Onboarding({ onDone }) {
  const [index, setIndex] = useState(0);
  const card = CARDS[index];
  const last = index === CARDS.length - 1;

  function finish() {
    markOnboarded();
    onDone();
  }

  return (
    <Modal title="Before you begin" onClose={finish}>
      <p className="overlay__kicker">
        {index + 1} of {CARDS.length}
      </p>
      <h3 className="onboard__title">{card.title}</h3>
      <p className="onboard__body">{card.body}</p>

      <div className="onboard__dots" aria-hidden="true">
        {CARDS.map((entry, i) => (
          <span key={entry.title} className={`onboard__dot ${i === index ? "is-active" : ""}`} />
        ))}
      </div>

      <div className="onboard__actions">
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => setIndex((i) => i - 1)}
          disabled={index === 0}
        >
          Back
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => (last ? finish() : setIndex((i) => i + 1))}
        >
          {last ? "Step into the trees" : "Next"}
        </button>
      </div>
    </Modal>
  );
}
