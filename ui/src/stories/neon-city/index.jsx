/**
 * NEON CITY: THE CROSSING — story plugin.
 *
 * WHY THIS DIRECTORY EXISTS. The story shipped declaring
 * `ui: {plugin: wicked-garden}`, which is a supported and honest thing to do --
 * a borrowed plugin lends its LOOK and not its VOICE, and the loader strips the
 * naming slots so the borrower keeps its own name (core/story.js). But the look
 * it was borrowing is a fae court: gold contracts, vines that GROW instead of
 * filling, an ash hourglass, rose and soil. This story is black glass and
 * telemetry. The manifest's `ui:` line is the whole of the migration, exactly
 * as its own comment predicted.
 *
 * THE IDENTITY, and where each rule is enforced:
 *
 *   Black is the canvas, literally #000000 ............ theme/tokens.css
 *   Cyan #06b6d4 scene accent, swapped per district ... theme/tokens.css
 *   Credits gold #f59e0b, mono, always ₵ ............. parts/Ledger.jsx
 *   ALL-CAPS wide-tracked labels, mono for all data ... theme/neon-city.css
 *   1px borders, glass over black .................... theme/neon-city.css
 *   No emoji; Unicode geometry or drawn SVG only ..... parts/Marks.jsx
 *
 * THE VEILED-METER RULE IS THE LOAD-BEARING ONE. Two of this story's most
 * important values -- `heat` and the shard's `timestamp` -- are declared
 * `veiled`, so they arrive as band WORDS with no number attached, and the heat
 * ladder is the piece of chrome most likely to break that by trying to be
 * helpful. It does not; see the header of parts/Ladder.jsx for the three things
 * it specifically refuses to do. `debt` and the eight per-face standings are
 * `hidden` and never leave the server at all, so nothing here draws them.
 *
 * See @core/story.js for what every field below means.
 */
import React from "react";

import { FileChip } from "./parts/Ladder.jsx";
import { HexMark, PaperIcon, RoadsIcon, Wordmark } from "./parts/Marks.jsx";
import Ledger from "./parts/Ledger.jsx";
import PaperOverlay from "./parts/PaperOverlay.jsx";
import RoadsOverlay from "./parts/RoadsOverlay.jsx";
import Stage, { districtOf } from "./parts/Stage.jsx";

/**
 * The story's slice: which district is tinting the product, and whether the
 * city has started paying attention.
 *
 * Both are DERIVED from the turn payload and neither is invented. `district` is
 * a lookup on the location id the server already sends; `watching` is the heat
 * band being anything other than the bottom rung -- a boolean read off a word,
 * which is the only thing a veiled value permits.
 */
const initialState = { district: "neoncity", watching: false };

/**
 * Derive the slice from the core state that was just reduced.
 *
 * Returns the SAME object when nothing moved. That is load-bearing: the store
 * uses identity to decide whether to rebuild `state`, and a fresh object per
 * streamed token would re-render the ledger sixty times a second.
 */
function reduce(slice, action, next) {
  if (action.type === "RESET") return initialState;
  if (action.type !== "SOCKET") return slice;

  const district = districtOf(next.world?.location_id);
  const band = next.meters?.heat?.band;
  // `undefined` is not "clean". A payload with no heat row leaves the mark
  // where it was rather than declaring the runner unwatched.
  const watching = band === undefined ? slice.watching : band !== "none";

  if (district === slice.district && watching === slice.watching) return slice;
  return { district, watching };
}

const StartIntro = () => (
  <p className="start__intro">
    Somebody sold you forty seconds of your own death. It came with a timestamp,
    twenty-one days out, and a header stamp nobody will read twice. The thing
    that filed it sits below the Shadow zone, behind a checkpoint that refuses
    anyone the city is looking for. Cross the Sprawl. Argue with the gate.
    Decide who holds the pen.
  </p>
);

export default {
  slug: "neon-city",
  title: "NEON CITY: THE CROSSING",
  documentTitle: "NEON CITY: THE CROSSING",
  beginLabel: "Take the shard",

  theme: () => import("./theme/neon-city.css"),

  initialState,
  reduce,

  // One attribute, and the whole product retones: every accent downstream reads
  // `--nc-accent`, which `body[data-district]` sets. Core writes the attribute
  // and has no idea what a district is.
  bodyData: (state) => ({ district: state.story.district || "neoncity" }),

  // The masthead hexagon. Its core lights once the city has noticed you, which
  // makes the mark a tell rather than a logo.
  Mark: ({ state }) => <HexMark watching={state.story.watching} />,

  // The file's confidence, in the header, where the flagship keeps its phase
  // pill. It is the one thing in this story that is true no matter where the
  // runner is standing.
  HeaderBadge: ({ state }) => <FileChip band={state.meters?.timestamp?.band} compact />,

  Wordmark,
  StartIntro,

  Ledger,
  Stage,

  // The Stage draws the engine's legal approaches when an encounter is live, so
  // the narrator's own choices would put two parallel action sets on screen
  // when the engine will only honour one. An encounter with an EMPTY approach
  // list still needs the narrator's choices, or the runner has no move at all.
  hideChoices: (state) => {
    const encounter = state.world?.encounter || {};
    return Object.keys(encounter).length > 0 && (encounter.approaches || []).length > 0;
  },

  /**
   * Two overlays, both gated on the payload key that feeds them.
   *
   * This story declares `paths.threads` and `paths.endings`, so both keys
   * arrive -- but the gate is on the KEY and not on the slug, because that is
   * the whole discipline: if this skin is ever borrowed by a story with no
   * paper, the borrower gets no button rather than a button that opens on
   * nothing. There is deliberately no third overlay. This story ships no
   * recipes, no decks and no challenges (game.yaml says so, one line each), and
   * a screen for a system a story does not have is the defect this seam exists
   * to prevent.
   */
  overlays: [
    {
      id: "paper",
      key: "p",
      label: "The paper",
      Icon: PaperIcon,
      Component: PaperOverlay,
      when: (state) => Boolean(state.world?.threads),
    },
    {
      id: "roads",
      key: "r",
      label: "The roads",
      Icon: RoadsIcon,
      Component: RoadsOverlay,
      when: (state) => Boolean(state.world?.endings),
    },
  ],

  onboarding: [],
};
