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

export default CourtIcon;
