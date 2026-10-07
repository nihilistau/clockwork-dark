/**
 * The casing board: what watching each house in this district has told you.
 *
 * WHERE IT SITS (v0.21.0, spec §4.3). In the ledger region -- the sheet
 * column, under the meter sheet -- by default; a story may put it in the
 * shelf instead (`ui.panels`). It used to sit in the main column, where it
 * painted over the choices (F1). It wears core's `Panel`: a section labelled
 * by its h2, collapsible, open by default.
 *
 * THE HEADER LINE. "Casing — {n} houses here", "· {k} empty now" when any
 * is, and "· Prep: {word}" when the payload carries the job block. Prep is
 * read here between jobs too, because casing is what earns it.
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
 * So each house is a disclosure row, closed unless it is empty now.
 *
 * Renders nothing at all for a story that declares no premises (the
 * flagship among them) and for a district that currently holds none -- same
 * convention as NegotiationPanel: an empty list is a real state, not a
 * broken fetch, and costs the screen nothing to draw.
 */
import React, { useEffect, useId, useRef, useState } from "react";

import Panel from "./Panel.jsx";

function House({ house }) {
  // Closed unless empty right now: the question a thief reading this board
  // is asking is "can I go in now" (spec §4.3).
  const [open, setOpen] = useState(Boolean(house.empty_now));
  const bodyId = useId();
  const known = house.known || [];
  // And when it EMPTIES later, it opens (T7 review 2): only on the edge from
  // occupied to empty, so a row the player closed while it stays empty stays
  // closed.
  const wasEmpty = useRef(Boolean(house.empty_now));
  useEffect(() => {
    const now = Boolean(house.empty_now);
    if (now && !wasEmpty.current) setOpen(true);
    wasEmpty.current = now;
  }, [house.empty_now]);
  return (
    <li className="casing__house">
      <button
        type="button"
        className="casing__head"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="casing__name">{house.name}</span>
        <span className="casing__type">{house.type_label}</span>
        {house.empty_now && <span className="casing__badge">empty now</span>}
        <span className="casing__progress">
          {known.length} of {house.of} known
        </span>
      </button>
      {/* Hidden, not unmounted: the learned lines stay in the document for a
          reader who opens the row. The index is the key -- two lines can read
          identically, and the id that would tell them apart must never render. */}
      <ul className="casing__known" id={bodyId} hidden={!open}>
        {known.map((text, i) => (
          <li key={i}>{text}</li>
        ))}
        {/* An opened row never opens onto nothing (T7 review 8). */}
        {known.length === 0 && <li className="casing__none">Nothing learned yet.</li>}
      </ul>
    </li>
  );
}

export default function CasingBoard({ premises, prep = "" }) {
  const houses = premises || [];
  if (houses.length === 0) return null;
  const empty = houses.filter((house) => house.empty_now).length;
  const title = [
    `Casing — ${houses.length} ${houses.length === 1 ? "house" : "houses"} here`,
    empty > 0 ? `${empty} empty now` : "",
    prep ? `Prep: ${prep}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Panel id="casing" title={title} className="casing" collapsible defaultOpen>
      <ul className="casing__list">
        {houses.map((house) => (
          <House key={house.id} house={house} />
        ))}
      </ul>
    </Panel>
  );
}
