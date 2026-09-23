/**
 * The casing board: what watching each house in this district has told you.
 *
 * WHAT THIS CONSUMES
 * -------------------
 * `state.premises` -- mirrored onto the store from `world.premises` by
 * `premisesOf` exactly as `metersOf` mirrors `world.meters` (core/store.js) --
 * one row per house in the player's CURRENT district:
 *
 *     {id, name, type_label, known, of, empty_now}
 *
 * Shape is `engine/game/state.py::GameState._premises_block`. `known` is
 * TEXTS ALREADY LEARNED, in the order a watch turned them up -- never an id,
 * and never a line nobody has watched for yet; the engine drops both at the
 * source; case ID never happens to be readable prose. `of` is the total the
 * house holds, so "2 of 5" reads as real progress rather than a bare count.
 *
 * `empty_now` answers a different question than the occupancy line INSIDE
 * `known` does. The occupancy text (once watched) names the day's longest
 * empty run; `empty_now` is a fact about THIS HOUR, resolved against the
 * live world clock every payload -- a thief reading this board is asking
 * "can I go in right now", not "when does this house tend to empty out".
 *
 * Renders nothing at all for a story that declares no premises (the
 * flagship among them) and for a district that currently holds none -- same
 * convention as NegotiationPanel: an empty list is a real state, not a
 * broken fetch, and costs the screen nothing to draw.
 */
import React from "react";

export default function CasingBoard({ premises }) {
  const houses = premises || [];
  if (houses.length === 0) return null;

  return (
    <section className="casing">
      <h3 className="casing__title">Casing</h3>
      <ul className="casing__list">
        {houses.map((house) => (
          <li key={house.id} className="casing__house">
            <div className="casing__head">
              <span className="casing__name">{house.name}</span>
              <span className="casing__type">{house.type_label}</span>
              {house.empty_now && (
                <span className="casing__badge">empty now</span>
              )}
            </div>

            <div className="casing__progress">
              {(house.known || []).length} of {house.of} known
            </div>

            {house.known && house.known.length > 0 && (
              <ul className="casing__known">
                {house.known.map((text, i) => (
                  // The index, not the text, is the key: two lines can read
                  // identically (two houses with the same lock), and the id
                  // that WOULD disambiguate them is exactly what the player
                  // must never see rendered.
                  <li key={i}>{text}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
