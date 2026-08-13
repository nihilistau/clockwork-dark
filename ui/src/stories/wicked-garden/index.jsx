/**
 * Wicked Garden — story plugin.
 *
 * WHAT IS AND IS NOT HERE
 * -----------------------
 * The components are real and rendered, and so is the story: The Wicked
 * Garden ships at `games/wicked-garden/` and its manifest declares
 * `ui: {plugin: wicked-garden}`, so this plugin IS the active one whenever
 * that story runs. (This header used to say the opposite -- the plugin
 * predates the story it was built for, and for a while the component kit was
 * the only way to see it.) Two things remain true from that era:
 *
 *   1. it is the second implementation of the plugin contract, which is the
 *      only way to know the contract is a seam and not a description of the
 *      flagship;
 *   2. everything it declares is also reachable through the component kit at
 *      `?kit=wicked-garden`, drawn from fixtures that are labelled as
 *      fixtures, so the parts can be inspected without playing to them.
 *
 * Nothing here fabricates game state. The Ledger below reads `state.meters` --
 * the story's own declared block, projected by the server from its state.yaml
 * -- and draws whatever is actually in it. With no server sending meters it
 * draws nothing, which is the correct empty state and not a placeholder.
 *
 * The meter names it recognises (favor, autonomy, corruption, knowledge,
 * desire, time_debt_mortal_days) are the ones the design set declares. A meter
 * it does not recognise still renders, as a vine with its own label.
 */
import React from "react";

import Meters from "@core/parts/Meters.jsx";
import PaintFrame from "@core/parts/PaintFrame.jsx";
import { AnalystContext, loadAnalyst } from "./analyst.js";
import EpilogueCard from "./parts/EpilogueCard.jsx";
import { HourglassMeter, VINES, VineMeter } from "./parts/Meters.jsx";

const HOURGLASS = "time_debt_mortal_days";

/**
 * The Garden's sheet.
 *
 * Same input as core's generic sheet -- `state.meters` -- drawn as vines and an
 * hourglass instead of tracks and numbers. A row the Garden has no metaphor for
 * falls through to core's renderer rather than being dropped, because a value a
 * story bothered to declare visible should never be invisible.
 */
function Ledger({ state }) {
  const rows = Object.values(state.meters || {});
  const vines = rows.filter((row) => VINES[row.name]);
  const glass = rows.find((row) => row.name === HOURGLASS);
  const rest = rows.filter((row) => !VINES[row.name] && row.name !== HOURGLASS);

  return (
    <aside className="ledger" aria-label="What you are becoming">
      {glass && <HourglassMeter days={glass.value ?? 0} label="Time debt" />}
      {vines.map((row) => (
        <VineMeter
          key={row.name}
          name={row.name}
          label={row.label}
          value={row.value}
          min={row.min ?? 0}
          max={row.max ?? 100}
          band={row.band}
        />
      ))}
      {rest.length > 0 && (
        <Meters meters={Object.fromEntries(rest.map((row) => [row.name, row]))} />
      )}
      {rows.length === 0 && (
        <p className="ledger__empty">Nothing has taken hold of you yet.</p>
      )}
    </aside>
  );
}

const Wordmark = () => (
  <h1 className="start__wordmark">
    The Wicked <span>Garden</span>
  </h1>
);

/**
 * The plate for wherever the player is standing.
 *
 * THE LAST MILE, and it was missing: the server resolves the picture, ships
 * `sceneImage` in the turn payload, and the client store holds it -- and with
 * no `Stage` slot declared, nothing rendered it. Every layer worked and the
 * screen was blank, which is the hardest kind of gap to see from either end.
 *
 * Uses core's PaintFrame so the Garden's plates get the same treatment as the
 * flagship's: mist, ray, grain, vignette, film lip. The wash underneath is what
 * shows while the image loads and if it 404s, so a missing plate degrades to
 * something lit rather than to a hole.
 */
function Stage({ state }) {
  const src = state.sceneImage;
  const place = state.world?.location_id || "";
  const caption = place ? place.replace(/_/g, " ") : "";

  return (
    <PaintFrame
      size="hero"
      // Real tokens from theme/tokens.css. I first wrote two invented names
      // here, which CSS resolves to nothing -- a transparent wash and no error
      // anywhere, so a missing plate would have shown a hole and looked like a
      // server problem.
      wash="radial-gradient(120% 90% at 50% 28%, var(--wg-leaf), var(--wg-soil-deep))"
      caption={caption}
      className="stage"
    >
      {src && (
        <img
          className="paint__img"
          src={src}
          // Decorative: the narration already says where you are, and a
          // screen-reader user hearing the caption twice is worse than not
          // hearing a filename-derived description of a painting.
          alt=""
          loading="lazy"
          draggable="false"
        />
      )}
    </PaintFrame>
  );
}

/**
 * The last screen.
 *
 * Core's generic Ending walks the payload's `render_order` and would draw this
 * story correctly. The Garden overrides it because its two cards are typeset,
 * not listed -- the waking world and the Garden are meant to sit as facing
 * pages, and the whole design turns on the reader holding both at once.
 *
 * The payload is spread rather than mapped: `EpilogueCard`'s props ARE
 * `Epilogue.to_dict()`'s keys, so there is no place for the two to disagree
 * about what `card_m` means.
 */
function EndingScreen({ ending, story, onNewRun, onOpenSaves }) {
  return (
    // `.finale`, not `.ending` -- this story's `.ending__*` block belongs to
    // EndingGallery's medallions.
    <div className="finale finale--garden" role="document">
      <EpilogueCard {...ending} />
      <div className="finale__actions">
        <button type="button" className="btn btn--lg" onClick={onNewRun}>
          {story?.beginLabel || "Step through again"}
        </button>
        {onOpenSaves && (
          <button type="button" className="btn btn--ghost" onClick={onOpenSaves}>
            Saved runs
          </button>
        )}
      </div>
    </div>
  );
}

export default {
  slug: "wicked-garden",
  title: "The Wicked Garden",
  documentTitle: "The Wicked Garden",
  beginLabel: "Step through the hedge",
  asideLabel: "The court",

  theme: () => import("./theme/wicked-garden.css"),

  // Analyst mode is a player preference, read once at load. It is deliberately
  // NOT in the core prefs blob: it means nothing to any other story, and a
  // shared settings shape that grows a field per story is the thing this whole
  // change exists to stop.
  initialState: { analyst: false },

  Wordmark,
  Ledger,
  Stage,
  Ending: EndingScreen,

  // Everything the Garden draws reads analyst mode from context rather than
  // from props, because it reaches ten levels down into an ending card.
  Wrap: ({ children, state }) => (
    <AnalystContext.Provider value={state.story.analyst ?? loadAnalyst()}>
      {children}
    </AnalystContext.Provider>
  ),

  overlays: [],
  onboarding: [],
};
