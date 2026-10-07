/**
 * The wanted poster, and its header chip (v0.21.0, spec §4.1).
 *
 * WHAT THIS CONSUMES. `state.world.law`, from `GameState._law_block`:
 *   {guise_label, wanted: {jurisdiction label: band word}, clarity,
 *    custody: null | {fine, fine_text, days}, scales: {wanted, clarity}}
 * Present only for a story that declares `paths.law` (HUE & CRY).
 *
 * THE VEILED RULE. `scales` orders the words low to high; a word's place
 * lights marks and picks how many of the sketch's four layers are drawn. The
 * place is never printed and never a percentage. A word not in its scale --
 * "" below the first threshold, or an author's typo -- is its own text with
 * nothing lit, and is never the worst band.
 *
 * THE CHIP shows the band and the clarity word; under 560px only the band
 * (the label names all). Core's words only ("Wanted", "Held", "A fine of"): every other word is the
 * payload's. Nothing here is a live region: the narrator's law_block already
 * speaks a change.
 */
import React from "react";

import Marks from "./Marks.jsx";
import Panel from "./Panel.jsx";
import { scaleIndex } from "./scale.js";

const DAY_WORDS = ["no days", "one day", "two days", "three days", "four days", "five days", "six days",
  "seven days", "eight days", "nine days", "ten days", "eleven days", "twelve days"];

/** Days as words (plan decision 12): the poster prints no digit but the fine's. */
export function dayWords(n) {
  const days = Math.max(0, Math.floor(Number(n) || 0));
  return DAY_WORDS[days] || "many days";
}

/** How many of the sketch's four layers to draw: 1 + round(3i/(N-1)); 1 out of scale. */
export function sketchLayers(index, count) {
  if (index < 0 || count < 2) return 1;
  return 1 + Math.round((3 * index) / (count - 1));
}

/**
 * The worst in-scale band across jurisdictions: {word, index, where}, `where`
 * the first jurisdiction's label holding it; index -1 when none is in scale.
 */
export function worstBand(law) {
  const scale = law?.scales?.wanted || [];
  let worst = { word: "", index: -1, where: "" };
  for (const [where, word] of Object.entries(law?.wanted || {})) {
    const index = scaleIndex(scale, word);
    if (index > worst.index) worst = { word, index, where };
  }
  return worst;
}

function Sketch({ layers, label }) {
  const all = [
    <rect key="frame" className="sketch__layer" x="4" y="4" width="92" height="112" rx="3" />,
    <path key="outline" className="sketch__layer" d="M50 22c-14 0-22 11-22 25s8 27 22 27 22-13 22-27-8-25-22-25zM16 112c4-20 18-30 34-30s30 10 34 30" />,
    <path key="features" className="sketch__layer" d="M40 44h6M54 44h6M50 48v9M43 63c4 3 10 3 14 0" />,
    <path key="hatching" className="sketch__layer" d="M30 38l8-10M64 28l8 10M28 60l6 6M66 66l6-6M24 100l10-8M66 92l10 8" />,
  ];
  return (
    <svg className="sketch" viewBox="0 0 100 120" role="img" aria-label={label}>
      {all.slice(0, layers)}
      {layers === 1 && (
        <text className="sketch__unknown" x="50" y="70" textAnchor="middle" aria-hidden="true">?</text>
      )}
    </svg>
  );
}

export default function WantedPoster({ state }) {
  const law = state?.world?.law;
  if (!law) return null;
  const scales = law.scales || {};
  const wantedScale = scales.wanted || [];
  const clarityScale = scales.clarity || [];
  const custody = law.custody;
  const layers = sketchLayers(scaleIndex(clarityScale, law.clarity), clarityScale.length);
  return (
    <Panel id="wanted" title="Wanted" className={`poster ${custody ? "is-held" : ""}`} collapsible defaultOpen>
      <p className="poster__guise">{law.guise_label}</p>
      <Sketch layers={layers} label={`The watch here has ${law.clarity} of ${law.guise_label}`} />
      <p className="poster__clarity" aria-hidden="true">{law.clarity}</p>
      <ul className="poster__bands">
        {Object.entries(law.wanted || {}).map(([where, word]) => (
          <li key={where} className="poster__band">
            <span className="poster__where">{where}</span>
            <span className="poster__word">{word}</span>
            <Marks count={Math.max(0, wantedScale.length - 1)} lit={Math.max(0, scaleIndex(wantedScale, word))} />
          </li>
        ))}
      </ul>
      {custody && (
        <p className="poster__custody">
          <span className="poster__stamp">Held</span>{" "}
          A fine of {custody.fine_text}{custody.days > 0 ? `, or ${dayWords(custody.days)}` : ""}
        </p>
      )}
    </Panel>
  );
}

export function WantedChip({ state, onOpenSheet }) {
  const law = state?.world?.law;
  if (!law) return null;
  const worst = worstBand(law);
  const clarityAt = scaleIndex(law.scales?.clarity, law.clarity);
  const held = Boolean(law.custody);
  // Nobody is looking for anyone and nobody holds the thief: every band at its
  // floor (or out of scale) and the watch here holding nothing of the face.
  if (!held && worst.index <= 0 && clarityAt <= 0) return null;
  const word = worst.word || (law.scales?.wanted || [])[0] || "";
  // WHERE the worst band is: named only once somebody is looking (above the
  // floor), in the payload's own district label. The clarity word is the
  // watch HERE's, so it is shown only above its floor: at the floor the
  // poster's "?" says it, and "nothing" beside a band reads as "wanted for
  // nothing". Held is core's word and stands alone when no band is above its floor.
  const showBand = !held || worst.index > 0;
  const named = worst.index > 0 && worst.where;
  const parts = [
    held ? "Held." : "",
    showBand ? `Wanted: ${word} at worst${named ? `, ${worst.where}` : ""}${clarityAt > 0 ? ";" : "."}` : "",
    clarityAt > 0 ? `the watch here has ${law.clarity} of ${law.guise_label}.` : "",
    "Show the poster.",
  ].filter(Boolean);
  return (
    <button
      type="button"
      className="wanted-chip"
      aria-label={parts.join(" ")}
      onClick={() => onOpenSheet?.("wanted")}
    >
      {held && <span className="chip__held">Held</span>}
      {held && showBand && <span className="chip__sep"> · </span>}
      {showBand && named && <span className="chip__where">{worst.where}: </span>}
      {showBand && <span className="chip__band">{word}</span>}
      {clarityAt > 0 && <span className="chip__rest"> · {law.clarity}</span>}
    </button>
  );
}
