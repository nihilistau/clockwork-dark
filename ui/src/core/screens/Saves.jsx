/**
 * Save browser.
 *
 * `save_version: 1` and a full from_dict round trip existed from PR2 with no
 * writer, no reader and no UI. Runs died with the process.
 */
import React, { useEffect, useState } from "react";
import Modal from "../parts/Modal.jsx";
import { prettyPlace } from "../parts/Chrome.jsx";
import { fetchArchetypes, fetchPlaces } from "../api.js";

/** A story-declared column: a public value with its number, a veiled one as its word (the veiled rule). */
function column(entry) {
  if (!entry || typeof entry !== "object") return "";
  return "band" in entry ? `${entry.label}: ${entry.band}` : `${entry.label} ${entry.value}`;
}

function when(updatedAt) {
  if (!updatedAt) return "";
  const delta = Date.now() / 1000 - updatedAt;
  if (delta < 90) return "just now";
  if (delta < 3600) return `${Math.round(delta / 60)} min ago`;
  if (delta < 86400) return `${Math.round(delta / 3600)} h ago`;
  return new Date(updatedAt * 1000).toLocaleDateString();
}

/**
 * Core prints no story's fiction on a row (v0.21.0, F7): it used to say "the
 * pattern is quiet" -- the flagship's evil phase -- on every story's saves.
 * A story says its own line through its plugin's `saveMeta`, and its declared
 * save columns arrive as `save.values`.
 */
export default function Saves({ saves, error, story = {}, onLoad, onDelete, onClose, onNew }) {
  // Names, not ids (F7): read once when the browser opens; each falls back.
  // Only a save's own place is ever printed.
  const [names, setNames] = useState({ archetypes: {}, places: {} });
  useEffect(() => {
    let live = true;
    Promise.all([
      fetchArchetypes().catch(() => []),
      fetchPlaces().then((data) => data?.places || []).catch(() => []),
    ]).then(([archetypes, places]) => {
      if (!live) return;
      setNames({
        archetypes: Object.fromEntries(archetypes.map((row) => [row.id, row.name])),
        places: Object.fromEntries(places.map((row) => [row.id, row.name])),
      });
    });
    return () => {
      live = false;
    };
  }, []);

  // Which row is asking "really?". One at a time: two rows both mid-confirm is
  // two live danger buttons, and the wrong one is one mis-click away.
  //
  // A SECOND PRESS RATHER THAN A `window.confirm`. Deleting a run is the only
  // irreversible thing in this client and it had no guard at all -- one press
  // and days of play were gone. A native dialog would guard it, but it tears
  // focus out of this modal's trap, cannot be styled, and speaks in the
  // browser's voice rather than the game's. So the button becomes the
  // question, which keeps the guard inside the focus order and one Escape
  // away.
  const [asking, setAsking] = useState("");

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
      {/* This screen has no footer, so a failure raised while it is open had
          nowhere to land -- a delete that the server refused refreshed the
          list, showed the run still sitting there, and said nothing at all. */}
      {error && (
        <p className="overlay__error" role="alert">
          {error}
        </p>
      )}

      {saves.length === 0 && (
        <p className="overlay__empty">
          No runs yet. Nothing has been written down.
        </p>
      )}

      <ul className="saves__list">
        {saves.map((save) => (
          <li key={save.save_id} className="saverow">
            <div className="saverow__main">
              <span className="saverow__name">{save.player_name}</span>
              <span className="saverow__meta">
                {[names.archetypes[save.archetype] || save.archetype, `day ${save.world_day}`, names.places[save.location_id] || prettyPlace(save.location_id)]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              <span className="saverow__meta">
                {[`${save.turn_number} turn${save.turn_number === 1 ? "" : "s"}`, story.saveMeta ? story.saveMeta(save) : null, when(save.updated_at)]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              {save.values && Object.keys(save.values).length > 0 && (
                <span className="saverow__values">
                  {Object.values(save.values).map(column).filter(Boolean).join(" · ")}
                </span>
              )}
            </div>
            <div className="saverow__actions">
              <button type="button" className="btn btn--sm" onClick={() => onLoad(save)}>
                Continue
              </button>
              {/* ONE button that changes its question, not two buttons that
                  swap places. Rendering a different element for the confirm
                  step removes the node the player just activated, and focus
                  falls to the body -- inside a focus-trapped modal that is a
                  keyboard dead end. Same element, same position, so React
                  keeps the DOM node and the focus ring with it, and a screen
                  reader announces the new label because it is still on it. */}
              <button
                type="button"
                className="btn btn--sm btn--danger"
                // The run's own name, so a reader hears WHICH run is going
                // rather than the fourth "Delete" on the screen.
                aria-label={
                  asking === save.save_id
                    ? `Confirm: delete ${save.player_name}'s run, day ${save.world_day}, for good`
                    : `Delete ${save.player_name}'s run, day ${save.world_day}`
                }
                onClick={() => {
                  if (asking === save.save_id) {
                    setAsking("");
                    onDelete(save);
                    return;
                  }
                  setAsking(save.save_id);
                }}
              >
                {asking === save.save_id ? "Delete for good" : "Delete"}
              </button>
              {asking === save.save_id && (
                <button
                  type="button"
                  className="btn btn--sm btn--ghost"
                  onClick={() => setAsking("")}
                >
                  Keep it
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Modal>
  );
}
