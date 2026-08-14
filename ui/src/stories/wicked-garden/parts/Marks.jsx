/**
 * The Garden's overlay marks.
 *
 * Drawn on core's `Icon` shell so they inherit the 24px box, the stroke weight
 * and `currentColor` from the same place the flagship's gear and pack do --
 * the footer puts a story's marks in a row with core's own mute and menu
 * buttons, and a mark that sets its own geometry is the one that looks wrong.
 */
import React from "react";

import { Icon } from "@core/parts/Chrome.jsx";

/**
 * The court: a centre with things in orbit and one thing underneath.
 *
 * The same shape the board itself draws -- Sophia in the middle, satellites
 * around her, Mother Briar as a root below rather than a peer beside. A mark
 * that is a small picture of its own screen is easier to learn than a mark
 * that is a metaphor for it.
 */
export function CourtIcon() {
  return (
    <Icon>
      <circle cx="12" cy="10" r="3" />
      <circle cx="5" cy="6" r="1.6" />
      <circle cx="19" cy="6" r="1.6" />
      <circle cx="19" cy="14" r="1.6" />
      <path d="M12 13.5v3.5" />
      <path d="M9 20.5h6" />
    </Icon>
  );
}

/**
 * The contracts: a rolled scroll with a seal hanging off it.
 *
 * The seal is the load-bearing part of the picture, because in this story a
 * bargain is not a piece of paper -- it is the thing that was said, and the
 * seal is what makes it hold.
 */
export function ScrollIcon() {
  return (
    <Icon>
      <path d="M7 4.5h9.5a1.8 1.8 0 0 1 1.8 1.8v9.4" />
      <path d="M7 4.5A1.8 1.8 0 0 0 5.2 6.3v1.9H7" />
      <path d="M7 4.5v11.2" />
      <path d="M7 15.7h11.3a1.8 1.8 0 0 1-1.8 1.8H8.8" />
      <circle cx="15.4" cy="19" r="2.3" />
    </Icon>
  );
}

/**
 * The mirror pool: a still oval with three shapes waiting under it.
 *
 * Not a trophy cabinet and not a checklist. The gallery is a surface you look
 * INTO, and two of its three tiers are things you cannot have -- so the mark is
 * water with shapes below the line rather than medals in a row.
 */
export function MirrorIcon() {
  return (
    <Icon>
      <ellipse cx="12" cy="8.4" rx="7.2" ry="3.6" />
      <path d="M4.8 8.4c0 4.9 3.2 8.9 7.2 11.4 4-2.5 7.2-6.5 7.2-11.4" />
      <path d="M9.2 12.4h5.6" />
      <path d="M10.4 15.6h3.2" />
    </Icon>
  );
}

export default CourtIcon;
