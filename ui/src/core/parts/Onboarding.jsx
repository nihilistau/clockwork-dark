/**
 * First-run cards, once.
 *
 * Not a tutorial. A story supplies the two or three things a new player cannot
 * discover by playing, and this shell shows them exactly once.
 *
 * The three Clockwork cards used to be a `const CARDS` right here, which meant
 * every story that would ever exist told its players that the dice are real and
 * that baking bread for forty days is a finished game. They live in
 * stories/clockwork-dark/onboarding.js now; a story that supplies none gets no
 * first-run modal at all, which App.jsx enforces by not rendering this.
 *
 * Gated on a localStorage flag so it never appears twice. If storage is
 * unavailable (private browsing) the cards show every time, which is a far
 * better failure than a first-run screen that crashes the boot.
 */
import React, { useState } from "react";
import Modal from "./Modal.jsx";

const FLAG = "clockwork_onboarded";

function flagKey(storyId) {
  return storyId ? `${FLAG}:${storyId}` : FLAG;
}

export function shouldOnboard(storyId) {
  try {
    return !window.localStorage.getItem(flagKey(storyId));
  } catch {
    return true;
  }
}

export function clearOnboarded(storyId) {
  try {
    window.localStorage.removeItem(flagKey(storyId));
  } catch {
    /* private browsing — they show every time anyway */
  }
}

function markOnboarded(storyId) {
  try {
    window.localStorage.setItem(flagKey(storyId), "1");
  } catch {
    /* private browsing — the cards will show again, which is harmless */
  }
}

export default function Onboarding({ cards = [], title = "Before you begin",
                                     finishLabel = "Begin", storyId, onDone }) {
  const [index, setIndex] = useState(0);
  const card = cards[index];
  const last = index === cards.length - 1;

  function finish() {
    markOnboarded(storyId);
    onDone();
  }

  if (!card) return null;

  return (
    <Modal title={title} onClose={finish}>
      <p className="overlay__kicker">
        {index + 1} of {cards.length}
      </p>
      <h3 className="onboard__title">{card.title}</h3>
      <p className="onboard__body">{card.body}</p>

      <div className="onboard__dots" aria-hidden="true">
        {cards.map((entry, i) => (
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
          {last ? finishLabel : "Next"}
        </button>
      </div>
    </Modal>
  );
}
