/**
 * VineMeter and HourglassMeter — non-numeric by default.
 *
 * THE RULE
 * --------
 * "All meters are 0-100 internally; presented as living UI metaphors."
 * "Meters never display raw integers in default UI."
 * "UI never requires raw numbers unless analyst_mode."
 *
 * Three separate design documents say the same thing, so it is not a style
 * preference: the number is the thing this interface is built to not show. A
 * vine GROWS; a bar fills. The difference is that a bar invites arithmetic and
 * a vine invites a feeling, and the whole Garden runs on the second.
 *
 * So the default render carries no digits anywhere -- not in the label, not in
 * a title attribute, not in the accessible name. `aria-valuetext` carries the
 * stage word instead, because a screen-reader user who is told "63" when the
 * screen says "opening" is being handed a different game.
 *
 * A VEILED value (band, no number) can never show a number even under analyst
 * mode, because the server did not send one. See ../analyst.js.
 *
 * GEOMETRY
 * --------
 * From `concept/ui-kit/svg/wg-ui-kit.svg`: the vine track is 400x18 with rx=9,
 * the fill is inset 2px at rx=7, and a bud sits at the head of the fill growing
 * 8 -> 9 -> 10 -> 11 px radius across the four lit frames. The five raster
 * frames (vine-empty / -25 / -50 / -75 / -full) are the same five stages; this
 * draws them so the fill can be continuous rather than crossfading between
 * chroma-keyed JPEGs.
 */
import React from "react";

import { useAnalyst } from "../analyst.js";

// Five stages, matching the five art frames. A stage is what the player is
// told; the ratio behind it is what the engine knows.
// Server-side band ordering, low to high (engine/state/schema.py::VEILED_BANDS).
// Held as a DISPLAY ordering only: the index lights segments, and is never used
// to reconstruct the number the server withheld.
export const BANDS = ["none", "faint", "some", "strong", "utmost"];

const STAGES = [
  { at: 0, key: "empty" },
  { at: 0.2, key: "bud" },
  { at: 0.45, key: "opening" },
  { at: 0.7, key: "full" },
  { at: 0.9, key: "overgrown" },
];

/**
 * The metaphor each meter wears, from 06-UI-UX's Meter Presentation table.
 *
 * The stage WORDS differ per meter and that is the point: "opening" is what
 * favor does and "loosening" is what autonomy does, and a shared vocabulary
 * would turn five different feelings back into one number with five skins.
 */
export const VINES = {
  favor: {
    label: "Favor",
    hue: "rose",
    words: ["closed", "budding", "opening", "in bloom", "heavy with bloom"],
  },
  autonomy: {
    label: "Autonomy",
    hue: "silk",
    words: ["bound", "straining", "loosening", "loose", "unbound"],
  },
  corruption: {
    label: "Corruption",
    hue: "gold",
    words: ["clean", "flecked", "freckled", "gilded", "gold under the skin"],
  },
  knowledge: {
    label: "Knowledge",
    hue: "teal",
    words: ["shut", "stirring", "half-open", "watching", "wide"],
  },
  desire: {
    label: "Desire",
    hue: "rose",
    words: ["cool", "warm", "warmer", "hot", "shimmering"],
  },
};

function stageOf(ratio) {
  let index = 0;
  for (let i = 0; i < STAGES.length; i += 1) if (ratio >= STAGES[i].at) index = i;
  return index;
}

/**
 * One growing vine.
 *
 * `value`/`max` when the server sent a number; `band` when it sent a band and
 * nothing else. Passing neither draws an empty vine rather than throwing -- a
 * meter the story has not wired yet should look unwatered, not crash the sheet.
 */
export function VineMeter({ name = "favor", label, value, max = 100, min = 0, band, spec }) {
  const analyst = useAnalyst();
  const meta = spec || VINES[name] || { label: name, hue: "rose", words: STAGES.map((s) => s.key) };

  // A veiled value has no ratio, only a place in a five-step ladder. Using the
  // band index as the fill is honest -- five stages is all the information
  // there is -- and it is why the fill is quantised for veiled rows and
  // continuous for public ones.
  const veiled = typeof band === "string";
  const bandIndex = veiled ? Math.max(0, BANDS.indexOf(band)) : -1;
  const ratio = veiled
    ? bandIndex / 4
    : Math.max(0, Math.min(1, ((Number(value) || 0) - min) / (max - min || 1)));

  const index = veiled ? bandIndex : stageOf(ratio);
  const word = meta.words[Math.min(index, meta.words.length - 1)];
  const bud = 8 + Math.min(index, 3); // 8..11px, from the vector sheet

  return (
    <div
      className="vine"
      data-hue={meta.hue}
      data-veiled={veiled ? "yes" : "no"}
      data-band={veiled ? band : undefined}
    >
      <div className="vine__row">
        <span className="vine__label">{label || meta.label}</span>
        <span className="vine__word">{word}</span>
        {/* Analyst mode adds the integer; it never replaces the word, so the
            two readings of the meter stay the same meter. A veiled row has no
            integer to add and correctly shows nothing extra. */}
        {analyst && !veiled && (
          <span className="vine__int" aria-hidden="true">
            {Math.round(Number(value) || 0)}
          </span>
        )}
      </div>
      <div
        className="vine__track"
        role="progressbar"
        aria-label={label || meta.label}
        // The stage word IS the value, announced. No digits reach a reader
        // that the screen is not also showing.
        aria-valuetext={analyst && !veiled ? `${word} (${Math.round(Number(value) || 0)})` : word}
      >
        {veiled ? (
          // FIVE SEGMENTS, not a bar. A continuous width is a number a player
          // can measure with a ruler, and the server refused to send this one a
          // number on purpose. It also has to LOOK like a different kind of
          // meter, or the coarseness reads as a rendering fault.
          BANDS.map((step, i) => (
            <span key={step} className={`vine__step ${i <= bandIndex ? "is-lit" : ""}`} />
          ))
        ) : (
          <span className="vine__fill" style={{ width: `${ratio * 100}%` }}>
            <span className="vine__bud" style={{ width: `${bud}px`, height: `${bud}px` }} />
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * Time debt — an hourglass of ash, not a countdown.
 *
 * `time_debt_mortal_days` is unbounded and 1 Garden day costs 10 mortal ones,
 * so there is no maximum to fill against; the glass reads how much has ALREADY
 * fallen. 100 is the threshold the design cares about (it forces the hollow
 * epilogue clause), so the glass is drawn against that and simply stays full
 * past it rather than pretending to a scale it does not have.
 */
export function HourglassMeter({ days = 0, gardenDays, label = "Time" }) {
  const analyst = useAnalyst();
  const ratio = Math.max(0, Math.min(1, days / 100));
  const word =
    days <= 0 ? "no time lost" : days < 30 ? "a little sand" : days < 70 ? "a season of it" : days < 100 ? "most of a year" : "the glass is spent";

  return (
    <div className="hourglass" data-spent={days >= 100 ? "yes" : "no"}>
      <span className="hourglass__glass" aria-hidden="true">
        <span className="hourglass__top" style={{ "--fall": 1 - ratio }} />
        <span className="hourglass__waist" />
        <span className="hourglass__pile" style={{ "--fall": ratio }} />
      </span>
      <span className="hourglass__body">
        <span className="hourglass__label">{label}</span>
        <span
          className="hourglass__word"
          role="progressbar"
          aria-label="Time lost in the waking world"
          aria-valuetext={word}
        >
          {word}
        </span>
        {analyst && (
          <span className="hourglass__int">
            {gardenDays != null ? `${gardenDays} Garden days · ` : ""}
            {Math.round(days)} mortal days
          </span>
        )}
      </span>
    </div>
  );
}

export default VineMeter;
