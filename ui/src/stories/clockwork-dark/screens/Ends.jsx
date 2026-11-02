/**
 * "The ways it ends" (v0.25.0 §8.4): only the doors open now -- tier `unlocked` -- with the title, the
 * tease (which names a place and a person) and the closeness band; once a run is locked, that ending.
 * Never a locked or silhouette row, and the fail-forward (unlocked from turn one, no `requires`) only
 * once it is the locked ending. THE HIDING IS COSMETIC: the payload's endings block ships every tier
 * (engine/game/endings.py::to_client; docs/GOVERNANCE.md NOT WIRED), and the flagship's teases are
 * written to be safe there.
 */
import React from "react";
import Modal from "@core/parts/Modal.jsx";

export function openDoors(endings) {
  const rows = endings?.gallery || [];
  const locked = endings?.locked && endings.locked !== "none" ? endings.locked : "";
  if (locked) return rows.filter((row) => row.id === locked);
  return rows.filter((row) => row.tier === "unlocked" && row.id !== endings?.fail_forward);
}

export default function Ends({ state, onClose }) {
  const rows = openDoors(state?.world?.endings);
  return (
    <Modal title="The ways it ends" onClose={onClose}>
      {rows.length === 0 ? (
        <p className="overlay__empty">Nothing here is decided yet.</p>
      ) : (
        <ul className="ends">
          {rows.map((row) => (
            <li key={row.id} className="ends__row">
              <h3 className="ends__title">{row.title}</h3>
              {row.tease && <p className="ends__tease">{row.tease}</p>}
              <span className="pill">{row.closeness}</span>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
