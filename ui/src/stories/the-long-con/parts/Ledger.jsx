/**
 * THE LONG CON — the right-hand column.
 *
 * Three veiled values: standing, heat, the_frame. They arrive as band words
 * and no number, and this file must never rebuild one. The work is
 * translation — the engine's none/faint/some/strong/utmost into the city's
 * own nouns — the same rule neon's heat ladder already holds.
 *
 * Everything else the story declares falls through to core's generic sheet.
 */
import React from "react";

import Meters from "@core/parts/Meters.jsx";

const BANDS = ["none", "faint", "some", "strong", "utmost"];

const STANDING = {
  none: { word: "stranger", gloss: "Nobody will take your call." },
  faint: { word: "a nod", gloss: "They know the name on the glass." },
  some: { word: "known", gloss: "Doors open. Not far." },
  strong: { word: "owed", gloss: "Somebody still answers after dark." },
  utmost: { word: "owned", gloss: "The city has decided you are useful." },
};

const HEAT = {
  none: { word: "quiet", gloss: "Nobody is looking." },
  faint: { word: "noted", gloss: "A name in a book nobody reads twice." },
  some: { word: "watched", gloss: "The bulls have a reason to walk this way." },
  strong: { word: "wanted", gloss: "A man they would like to have a word with." },
  utmost: { word: "burned", gloss: "Every room in this city is a decision about you." },
};

const FRAME = {
  none: { word: "clean", gloss: "Nothing has been hung on you yet." },
  faint: { word: "a pin", gloss: "Someone is trying the size of it." },
  some: { word: "a file", gloss: "The precinct has a folder with your brother's name." },
  strong: { word: "a charge", gloss: "They have a story. It almost fits." },
  utmost: { word: "hung", gloss: "The frame is built. You are what it holds." },
};

const TABLES = {
  standing: STANDING,
  heat: HEAT,
  the_frame: FRAME,
};

const OWN = new Set(Object.keys(TABLES));

const UNREAD = { word: "unread", gloss: "No reading. That is not the same as clean." };

function Readout({ name, row }) {
  const table = TABLES[name];
  const band = row?.band;
  const entry = table[band] || UNREAD;
  const index = BANDS.indexOf(band);

  return (
    <div className="lc-readout" data-band={band || "unread"}>
      <div className="lc-readout__row">
        <span className="lc-readout__label">{row?.label || name}</span>
        <span className="lc-readout__word">{entry.word}</span>
      </div>
      <p className="lc-readout__gloss">{entry.gloss}</p>
      <div className="lc-readout__marks" role="img" aria-label={`${row?.label || name}: ${entry.word}`}>
        {BANDS.map((step, i) => (
          <span
            key={step}
            className={`lc-readout__mark ${index >= 0 && i <= index ? "is-lit" : ""}`}
            aria-hidden="true"
          />
        ))}
      </div>
    </div>
  );
}

export default function Ledger({ state }) {
  const meters = state.meters || {};
  const own = Object.entries(meters).filter(([name]) => OWN.has(name));
  const rest = Object.fromEntries(
    Object.entries(meters).filter(([name]) => !OWN.has(name))
  );
  const world = state.world || {};

  return (
    <aside className="lc-ledger" aria-label="The case">
      <header className="lc-ledger__head">
        <span className="lc-ledger__name">{world.player_name || "You"}</span>
        {world.archetype && <span className="lc-ledger__kind">{world.archetype}</span>}
      </header>
      {own.map(([name, row]) => (
        <Readout key={name} name={name} row={row} />
      ))}
      {Object.keys(rest).length > 0 && <Meters meters={rest} />}
    </aside>
  );
}
