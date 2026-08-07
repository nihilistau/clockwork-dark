/**
 * Save browser.
 *
 * `save_version: 1` and a full from_dict round trip existed from PR2 with no
 * writer, no reader and no UI. Runs died with the process.
 */
import React from "react";
import Modal from "../parts/Modal.jsx";
import { prettyPlace } from "../parts/Chrome.jsx";

const PHASE_WORD = {
  dormant: "quiet",
  stirring: "stirring",
  spreading: "spreading",
  consuming: "consuming",
};

function when(updatedAt) {
  if (!updatedAt) return "";
  const delta = Date.now() / 1000 - updatedAt;
  if (delta < 90) return "just now";
  if (delta < 3600) return `${Math.round(delta / 60)} min ago`;
  if (delta < 86400) return `${Math.round(delta / 3600)} h ago`;
  return new Date(updatedAt * 1000).toLocaleDateString();
}

export default function Saves({ saves, onLoad, onDelete, onClose, onNew }) {
  return (
    <Modal
      title="Saved runs"
      onClose={onClose}
      footer={
        <button type="button" className="btn btn--lg" onClick={onNew}>
          Begin a new run
        </button>
      }
    >
      {saves.length === 0 && <p className="overlay__empty">No runs yet.</p>}

      <ul className="saves__list">
        {saves.map((save) => (
          <li key={save.save_id} className="saverow">
            <div className="saverow__main">
              <span className="saverow__name">{save.player_name}</span>
              <span className="saverow__meta">
                {save.archetype} · day {save.world_day} · {prettyPlace(save.location_id)}
              </span>
              <span className="saverow__meta">
                {save.turn_number} turns · the pattern is{" "}
                {PHASE_WORD[save.evil_phase] || save.evil_phase} · {when(save.updated_at)}
              </span>
            </div>
            <div className="saverow__actions">
              <button type="button" className="btn btn--sm" onClick={() => onLoad(save)}>
                Continue
              </button>
              <button
                type="button"
                className="btn btn--sm btn--danger"
                onClick={() => onDelete(save)}
              >
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>
    </Modal>
  );
}
