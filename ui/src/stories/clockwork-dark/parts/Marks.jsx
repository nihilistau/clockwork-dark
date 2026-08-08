/**
 * The Clockwork Dark's own chrome furniture.
 *
 * Four overlay icons, the masthead gear and the phase pill. All of it used to
 * live in core/parts/Chrome.jsx, where it meant every story that would ever
 * exist shipped a clockwork gear and a journal-shaped button for a screen it
 * might not have.
 */
import React from "react";

import { Icon } from "@core/parts/Chrome.jsx";

/* A bound journal, seen closed: boards, spine, and the ribbon marking the
   page you stopped on. */
export function JournalIcon() {
  return (
    <Icon>
      <path d="M7 3.6h10.4a1.6 1.6 0 0 1 1.6 1.6v13.6a1.6 1.6 0 0 1-1.6 1.6H7" />
      <path d="M7 3.6A1.9 1.9 0 0 0 5.1 5.5v13a1.9 1.9 0 0 0 1.9 1.9" />
      <path d="M5.1 17.4h1.9" />
      <path d="M13.9 3.6v6.3l-1.7-1.4-1.7 1.4V3.6" />
    </Icon>
  );
}

/* A folded travelling map with one place ringed on it. The Atlas is the first
   tab of the codex and it is the only one a player recognises by shape. */
export function AtlasIcon() {
  return (
    <Icon>
      <path d="M3.6 6.6 9 4.3l6 2.3 5.4-2.3v13.1L15 19.7l-6-2.3-5.4 2.3z" />
      <path d="M9 4.3v13.1M15 6.6v13.1" />
      <circle cx="12" cy="11.2" r="1.5" fill="currentColor" stroke="none" />
    </Icon>
  );
}

/* A balance beam. Barter in this world is weighing what you have against what
   they will part with -- the trade screen draws the same beam full size. */
export function ScalesIcon() {
  return (
    <Icon>
      <path d="M12 4.4v15.2M8.4 19.6h7.2" />
      <path d="M4.2 7.4h15.6" />
      <path d="M4.2 7.4 2 12.4h4.4zM19.8 7.4l-2.2 5H22z" />
      <circle cx="12" cy="4.4" r="1.1" fill="currentColor" stroke="none" />
    </Icon>
  );
}

/* A rucksack. The pack screen is the only place in the product that shows you
   what you are physically carrying, so the mark is the thing itself. */
export function PackIcon() {
  return (
    <Icon>
      <path d="M7.4 9.2h9.2a2.3 2.3 0 0 1 2.3 2.3v7.1a1.6 1.6 0 0 1-1.6 1.6H6.7a1.6 1.6 0 0 1-1.6-1.6v-7.1a2.3 2.3 0 0 1 2.3-2.3z" />
      <path d="M9.3 9.2V7.1a2.7 2.7 0 0 1 5.4 0v2.1" />
      <path d="M5.1 13.7h13.8" />
      <path d="M10.7 15.8h2.6v2.6h-2.6z" />
    </Icon>
  );
}

/**
 * The masthead gear.
 *
 * This is the geometry of Design_files/assets/gear-motif.svg, inlined rather
 * than <img>-linked so it inherits `currentColor` and therefore corrupts with
 * the phase; the shipped file bakes in #8b4513 and would sit at DORMANT brass
 * while the rest of the frame went chartreuse. The file itself is still used,
 * as the mask for the corruption filigree in the story theme.
 *
 * It was a 16px hand-drawn approximation at opacity 0.55 -- small enough and
 * faint enough that the one piece of brand furniture on the play screen read
 * as a smudge.
 */
export function GearMark({ discovered }) {
  return (
    <svg
      className={`gear ${discovered ? "gear--turning" : ""}`}
      viewBox="0 0 48 48"
      width="22"
      height="22"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="24" cy="24" r="6.5" />
      <circle cx="24" cy="24" r="1.6" fill="currentColor" stroke="none" />
      <g>
        <path d="M24 5.5v5" />
        <path d="M24 37.5v5" />
        <path d="M5.5 24h5" />
        <path d="M37.5 24h5" />
        <path d="M11 11l3.5 3.5" />
        <path d="M33.5 33.5L37 37" />
        <path d="M37 11l-3.5 3.5" />
        <path d="M14.5 33.5L11 37" />
      </g>
      {/* the hands — this is a clock as much as a gear */}
      <path d="M24 24l3 -2.2" strokeWidth="1.2" />
      <path d="M24 24l-1.6 2.6" strokeWidth="1.2" />
    </svg>
  );
}

export const PHASE_COPY = {
  dormant: {
    word: "Dormant",
    line: "The world is behaving. Wheat, weather, gossip, bread.",
  },
  stirring: {
    word: "Stirring",
    line: "Something under the floor of things has begun to keep time.",
  },
  spreading: {
    word: "Spreading",
    line: "It is out of the forest now, and it is not in a hurry.",
  },
  consuming: {
    word: "Consuming",
    line: "There is no hour left that is not this hour.",
  },
};

/** The header badge: the phase, said out loud, opening the pause menu. */
export function PhasePill({ phase, onOpenMenu }) {
  const copy = PHASE_COPY[phase] || PHASE_COPY.dormant;
  return (
    <button
      type="button"
      className={`phasepill phasepill--${phase || "dormant"}`}
      onClick={onOpenMenu}
      title={copy.line}
    >
      <span className="phasepill__kicker">The pattern is</span>
      <span className="phasepill__word">{copy.word}</span>
    </button>
  );
}

/** The same thing full width, at the top of the pause menu. */
export function PhaseBand({ phase }) {
  const copy = PHASE_COPY[phase] || PHASE_COPY.dormant;
  return (
    <div className={`phaseband phaseband--${phase || "dormant"}`}>
      <span className="phaseband__kicker">The pattern is</span>
      <span className="phaseband__word">{copy.word}</span>
      <span className="phaseband__line">{copy.line}</span>
    </div>
  );
}
