/**
 * NEON CITY — the drawn marks.
 *
 * NO EMOJI ANYWHERE. That is BIBLE.md §7.4 and README non-negotiable 5, and it
 * is the reason every glyph in this story is either a drawn SVG on core's 24px
 * grid or one of the six Unicode geometry characters the design system names:
 *
 *     ◆ ◇ ◈ ◉ ▸ ⌬
 *
 * Those six are in the Latin/geometric blocks IBM Plex Mono ships, which is the
 * other half of the rule -- the flagship's footer once rendered `⌸` as a tofu
 * box on Windows because nothing in the font stack had it. Anything outside
 * that set gets drawn instead of typed.
 *
 * Everything here uses `currentColor` so a mark takes the district accent from
 * whatever it is sitting in, and nothing here is a fill except where a shape
 * has to read solid at 20px.
 */
import React from "react";

import { Icon } from "@core/parts/Chrome.jsx";

/** The six the design system allows, named so nothing types a literal twice. */
export const GEOM = {
  solid: "◆",
  hollow: "◇",
  nested: "◈",
  disc: "◉",
  point: "▸",
  hex: "⌬",
};

/**
 * The masthead mark: a hexagon with the count inside it.
 *
 * The product mark in the canon is a hexagon with a wordmark set in it. Here
 * the hexagon is the city and the ring inside is the thing doing the counting,
 * so the mark is diegetic rather than a logo: `watching` lights the core once
 * the run has attracted any attention at all, which makes the masthead a tell
 * instead of a decoration.
 */
export function HexMark({ watching = false }) {
  return (
    <span className={`nc-mark ${watching ? "is-watching" : ""}`} aria-hidden="true">
      <Icon size={22}>
        <path d="M12 2.8 20 7.4v9.2L12 21.2 4 16.6V7.4z" />
        <circle cx="12" cy="12" r="3.1" />
        {watching && <circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" />}
      </Icon>
    </span>
  );
}

/** Overlay mark: the paper. A filed sheet with a fold, not a scroll. */
export function PaperIcon() {
  return (
    <Icon>
      <path d="M6.4 3.4h7.4l4 4v13.2H6.4z" />
      <path d="M13.8 3.4v4h4" />
      <path d="M9.2 12h5.6M9.2 15.2h5.6M9.2 18h3.2" />
    </Icon>
  );
}

/** Overlay mark: the roads. A junction — every ending is a way out of one. */
export function RoadsIcon() {
  return (
    <Icon>
      <path d="M12 20.6V12" />
      <path d="M12 12 5.4 6.2M12 12l6.6-5.8" />
      <circle cx="12" cy="12" r="1.6" />
      <circle cx="5.4" cy="5.2" r="1.4" />
      <circle cx="18.6" cy="5.2" r="1.4" />
    </Icon>
  );
}

/**
 * The start screen's title treatment.
 *
 * Two lines because the story's name is two things: the place, and the thing
 * you do in it. The rule between them is the accent, at hairline weight, which
 * is the one piece of chrome on the start screen.
 */
export function Wordmark() {
  return (
    <h1 className="nc-wordmark">
      <span className="nc-wordmark__city">NEON CITY</span>
      <span className="nc-wordmark__rule" aria-hidden="true" />
      <span className="nc-wordmark__sub">THE CROSSING</span>
    </h1>
  );
}
