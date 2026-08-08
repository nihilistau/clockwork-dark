/**
 * The declared-meter sheet.
 *
 * WHAT THIS CONSUMES
 * ------------------
 * `state.meters`, projected by the server from the active story's `state.yaml`
 * and shipped in every turn payload:
 *
 *     { name: { name, label, kind, value?, min?, max?, band? } }
 *
 * Nothing in the client read that block before this component. It is the only
 * way a story can put a number in front of the player without an engine change,
 * so core renders it generically: a story whose meters the flagship never had
 * gets a working sheet for free, with no plugin at all.
 *
 * THE RULE THAT MATTERS
 * ---------------------
 * A `hidden` value never leaves the server. A `veiled` value arrives with a
 * BAND STRING and no number, and this component must never invent one. There is
 * no bar width to derive, no percentage to print, no tooltip with the integer
 * in it -- the band is the whole truth the player is allowed. That is the
 * difference between a meter that reads as a rose opening and one that reads as
 * 63/100, and the moment a client back-computes a width from the band ordinal
 * the design rule is dead even though the number never crossed the wire.
 *
 * So veiled values render as a five-step GLYPH ROW, not a track: a shape a
 * player reads as "more than last turn" without a scale to measure against.
 *
 * Kinds: `meter` is a bounded quantity, `clock` a filling countdown, `track` a
 * counter. An unbounded public value prints its number with no track, because a
 * track with no maximum is a lie about progress.
 */
import React from "react";

// Server-side ordering, low to high (engine/state/schema.py::VEILED_BANDS).
// Held here as a DISPLAY ordering only -- the index is used to light glyphs,
// never to reconstruct a value.
const BANDS = ["none", "faint", "some", "strong", "utmost"];

const BAND_WORD = {
  none: "none at all",
  faint: "faint",
  some: "some",
  strong: "strong",
  utmost: "utmost",
};

function pct(row) {
  const min = typeof row.min === "number" ? row.min : 0;
  const max = typeof row.max === "number" ? row.max : null;
  if (max === null || max <= min) return null;
  const ratio = (Number(row.value ?? 0) - min) / (max - min);
  return Math.max(0, Math.min(1, ratio)) * 100;
}

/** One veiled value: five marks, however many the band lights. */
function Band({ row }) {
  const index = BANDS.indexOf(row.band);
  const lit = index < 0 ? 0 : index;
  const word = BAND_WORD[row.band] || row.band || "unknown";

  return (
    <div className="dmeter dmeter--veiled" data-band={row.band || "unknown"}>
      <div className="dmeter__row">
        <span className="dmeter__label">{row.label || row.name}</span>
        {/* The WORD is the value. It is announced and it is visible; the
            glyphs beside it are the same information for someone reading
            shape rather than text. */}
        <span className="dmeter__band">{word}</span>
      </div>
      <div
        className="dmeter__marks"
        role="img"
        aria-label={`${row.label || row.name}: ${word}`}
      >
        {BANDS.map((name, i) => (
          <span
            key={name}
            className={`dmeter__mark ${i <= lit ? "is-lit" : ""}`}
            aria-hidden="true"
          />
        ))}
      </div>
    </div>
  );
}

/** One public value: a track when it is bounded, a bare number when it is not. */
function Value({ row }) {
  const filled = pct(row);
  const value = Number(row.value ?? 0);
  const shown = Number.isInteger(value) ? value : Math.round(value * 10) / 10;

  if (filled === null) {
    return (
      <div className="dmeter dmeter--plain" data-kind={row.kind}>
        <div className="dmeter__row">
          <span className="dmeter__label">{row.label || row.name}</span>
          <span className="dmeter__value">{shown}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="dmeter" data-kind={row.kind}>
      <div className="dmeter__row">
        <span className="dmeter__label">{row.label || row.name}</span>
        <span className="dmeter__value">
          {shown}
          <span className="dmeter__max"> / {row.max}</span>
        </span>
      </div>
      <div
        className="dmeter__track"
        role="meter"
        aria-label={row.label || row.name}
        aria-valuenow={value}
        aria-valuemin={row.min ?? 0}
        aria-valuemax={row.max}
      >
        <span className="dmeter__fill" style={{ width: `${filled}%` }} />
      </div>
    </div>
  );
}

export function Meter({ row }) {
  // `band` present and `value` absent is the veiled contract. Testing for the
  // band rather than for a visibility field is deliberate: visibility is not on
  // the wire, and it must not be -- the shape of the row IS the permission.
  if (typeof row.band === "string") return <Band row={row} />;
  return <Value row={row} />;
}

/**
 * The whole declared block, in declared order.
 *
 * Grouped by kind so a story with eight meters and three clocks does not read
 * as eleven interchangeable bars. Groups with nothing in them do not print a
 * heading.
 */
export default function Meters({ meters, title = "State" }) {
  const rows = Object.values(meters || {});
  if (!rows.length) return null;

  const groups = [
    ["meter", ""],
    ["clock", "Clocks"],
    ["track", "Tracks"],
  ];

  return (
    <section className="dmeters" aria-label={title}>
      {groups.map(([kind, heading]) => {
        const of = rows.filter((r) => (r.kind || "meter") === kind);
        if (!of.length) return null;
        return (
          <div key={kind} className="dmeters__group">
            {heading && <h3 className="dmeters__head">{heading}</h3>}
            {of.map((row) => (
              <Meter key={row.name} row={row} />
            ))}
          </div>
        );
      })}
    </section>
  );
}

/**
 * Core's default right-hand column: who you are, then everything declared.
 *
 * A story that wants its own sheet supplies `Ledger` in its plugin; the
 * flagship does exactly that and keeps its hand-built one.
 */
export function MeterSheet({ state }) {
  const world = state.world || {};
  return (
    <aside className="ledger" aria-label="Character">
      <header className="ledger__head">
        <span className="ledger__name">{world.player_name || "Traveler"}</span>
        {world.archetype && <span className="ledger__kind">{world.archetype}</span>}
      </header>
      <Meters meters={state.meters} />
      {!Object.keys(state.meters || {}).length && (
        <p className="ledger__empty">
          This story declares nothing for the sheet to show.
        </p>
      )}
    </aside>
  );
}
