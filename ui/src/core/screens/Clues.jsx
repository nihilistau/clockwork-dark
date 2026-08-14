/**
 * The clue board — what the PLAYER has worked out.
 *
 * THREE KINDS OF KNOWING, and this screen shows the third. What is TRUE lives
 * in the world. What a CHARACTER knows lives in their subject memory, and
 * reaches the narrator as a dossier. What the PLAYER has pieced together is
 * neither, and conflating it with either is how a mystery stops being one: a
 * board built from world truth hands over the answer, and one built from a
 * character's memory shows the player things nobody ever told them.
 *
 * Grouped by what each clue is ABOUT, because that is how anyone actually
 * reasons about a case — everything you know about the bakery in one place,
 * everything about Odran in another — and because a flat reverse-chronological
 * list is a log, not a board.
 */
import React, { useEffect, useMemo, useState } from "react";

import Modal from "../parts/Modal.jsx";

export default function CluesScreen({ sessionId, onClose }) {
  const [clues, setClues] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!sessionId) {
      // The board is a record of ONE run. Without a session there is nothing
      // to show, and showing everything the story could yield would be the
      // spoiler this screen exists to avoid.
      setClues([]);
      return undefined;
    }
    let live = true;
    fetch(`/api/clues?session_id=${encodeURIComponent(sessionId)}`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => live && setClues(data.clues || []))
      .catch((err) => live && setError(String(err.message || err)));
    return () => {
      live = false;
    };
  }, [sessionId]);

  const grouped = useMemo(() => {
    const bins = new Map();
    for (const clue of clues || []) {
      const key = clue.about || "Loose ends";
      if (!bins.has(key)) bins.set(key, []);
      bins.get(key).push(clue);
    }
    return [...bins.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [clues]);

  return (
    <Modal title="What you know" onClose={onClose}>
      {error && <p className="status status--error" role="status">{error}</p>}
      {!clues && !error && <p className="status" role="status">Reading your notes…</p>}

      {clues && clues.length === 0 && (
        <p className="clues__empty">
          Nothing yet. What you work out will collect here — not what is true,
          and not what anyone has told you, but what you have actually put
          together.
        </p>
      )}

      {grouped.map(([about, rows]) => (
        <section key={about} className="clues__group">
          <h3 className="clues__about">{about}</h3>
          <ul className="clues__list">
            {rows.map((clue) => (
              <li key={clue.id} className="clues__item">
                <span className="clues__text">{clue.text}</span>
                {clue.day ? <span className="clues__day">day {clue.day}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </Modal>
  );
}
