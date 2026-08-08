/**
 * Analyst mode.
 *
 * `meta.content.analyst_mode` in the design set: a boolean, default FALSE, that
 * a player turns on. It changes exactly two things and must never change more:
 *
 *   1. meters print their raw integer beside the metaphor;
 *   2. a locked ending shows the numeric gate it failed instead of a poetic
 *      tease.
 *
 * OFF is the design. "All meters are 0-100 internally; presented as living UI
 * metaphors" and "meters never display raw integers in default UI" are the
 * rules the whole Garden interface is built on, and analyst mode is the escape
 * hatch for players who want the spreadsheet -- not a debug flag and not a
 * developer surface. 09-UI-COMPONENT-KIT forbids developer-facing terms in
 * player UI, so the toggle is labelled in the player's language.
 *
 * IT CANNOT UNVEIL A VEILED VALUE. Analyst mode is a client preference; a
 * `veiled` meter arrives from the server with a band and no number, and there
 * is nothing on this side to reveal. Turning it on shows numbers for the values
 * the server was willing to send, and the band word for the ones it was not.
 */
import { createContext, useContext } from "react";

const KEY = "wicked_garden_analyst";

export const AnalystContext = createContext(false);

export const useAnalyst = () => useContext(AnalystContext);

export function loadAnalyst() {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function saveAnalyst(on) {
  try {
    window.localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    /* private browsing; the preference simply does not persist */
  }
}
