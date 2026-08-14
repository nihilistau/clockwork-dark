/**
 * The two veiled readouts: the heat ladder, and the file.
 *
 * THE VEILED RULE, AND WHY THIS FILE IS THE ONE THAT COULD BREAK IT
 * ----------------------------------------------------------------
 * `heat` and `timestamp` are declared `visibility: veiled` in
 * games/neon-city/state.yaml. A veiled value arrives as a BAND STRING and no
 * number -- `{name, label, kind, band}` -- and the integer never crosses the
 * wire. So there is nothing here to reveal by accident; the only way to break
 * the rule is to REBUILD the number, and this file is where that temptation
 * lives, because heat is 0-100 in the fiction and the ladder has thresholds
 * (Clean 0 / Noticed 20 / Wanted 45 / Hunted 70 / Burned 90, BIBLE appendix 1).
 *
 * So, explicitly, three things this file does not do:
 *
 *   - it does not look a band up in that threshold table and print a number;
 *   - it does not turn a band's ordinal into a percentage or a bar width;
 *   - it does not put the integer in a title attribute or an aria-label.
 *
 * What it DOES is substitute one word for another. The engine bands every
 * veiled value into five rungs (engine/state/schema.py::VEILED_BANDS --
 * none/faint/some/strong/utmost) and the Sprawl's ladder is also five rungs, in
 * the same order, so `some` IS `Wanted` in this story's vocabulary. That is a
 * translation, not a computation: the information content is identical before
 * and after, which is the test. Lighting three of five rungs is the same
 * disclosure core's own glyph row makes (core/parts/Meters.jsx, `Band`) and it
 * carries no scale to measure against.
 *
 * A band the engine has never sent renders as UNREAD rather than as Clean. An
 * absent readout must not read as the safe end of the ladder.
 */
import React from "react";

/** The engine's five bands, low to high. Display ordering only. */
const BANDS = ["none", "faint", "some", "strong", "utmost"];

/**
 * The Sprawl's ladder, in the story's own nouns.
 *
 * `pressure.js` is the systems file of record (BIBLE appendix 1 resolves the
 * canon's two competing ladders in its favour), and these are its five rung
 * names. The `tone` keys theme/neon-city.css, which is the only place the
 * colours are attached.
 */
const HEAT = {
  none: { rung: "CLEAN", tone: "clean", gloss: "Nobody upstream has written your name down." },
  faint: { rung: "NOTICED", tone: "noticed", gloss: "You are in somebody's notes. Notes are cheap." },
  some: { rung: "WANTED", tone: "wanted", gloss: "Doors price you differently now." },
  strong: { rung: "HUNTED", tone: "hunted", gloss: "SynthSec has a route that goes past you." },
  utmost: { rung: "BURNED", tone: "burned", gloss: "Every counter in the Sprawl is a decision about you." },
};

/**
 * The file's confidence, which is what the timestamp surfaces as.
 *
 * state.yaml is explicit that the interface may show the band and never a
 * countdown -- "numbers read as scores, and scores get optimised", and the
 * whole horror of this story is administrative rather than arithmetical. So
 * the clock is a confidence rating on a forecast, which is exactly what
 * Cathedral would call it, and never "14 days left".
 */
const FILE = {
  none: { word: "FILED", tone: "clean" },
  faint: { word: "HOLDING", tone: "noticed" },
  some: { word: "FIRMING", tone: "wanted" },
  strong: { word: "CONVERGING", tone: "hunted" },
  utmost: { word: "DUE", tone: "burned" },
};

const UNREAD = { rung: "UNREAD", tone: "unread", gloss: "No reading. That is not the same as clean." };

/**
 * The heat ladder: five rungs, lit to the one you are standing on.
 *
 * The rungs are always all five, because the ladder is the pressure the story
 * is about and hiding the rungs above you would hide what the game is for.
 */
export function HeatLadder({ band }) {
  const row = HEAT[band] || UNREAD;
  const index = BANDS.indexOf(band);

  return (
    <div className="nc-ladder" data-tone={row.tone}>
      <div className="nc-ladder__head">
        <span className="nc-ladder__label">HEAT</span>
        <span className="nc-ladder__rung">{row.rung}</span>
      </div>
      <div className="nc-ladder__rungs" role="img" aria-label={`Heat: ${row.rung}`}>
        {BANDS.map((name, i) => (
          <span
            key={name}
            className={`nc-ladder__step ${i <= index ? "is-lit" : ""}`}
            data-step={HEAT[name].tone}
            aria-hidden="true"
          />
        ))}
      </div>
      <p className="nc-ladder__gloss">{row.gloss}</p>
    </div>
  );
}

/**
 * The file's header, as a chip.
 *
 * Used twice: in the ledger, and in the masthead badge. Same component so the
 * two can never disagree about what the file currently says.
 */
export function FileChip({ band, compact = false }) {
  const row = FILE[band] || { word: "UNREAD", tone: "unread" };

  return (
    <span
      className={`nc-file ${compact ? "nc-file--compact" : ""}`}
      data-tone={row.tone}
      aria-label={`The file: ${row.word}`}
    >
      <span className="nc-file__key">THE FILE</span>
      <span className="nc-file__val">{row.word}</span>
    </span>
  );
}

export { BANDS, FILE, HEAT };
