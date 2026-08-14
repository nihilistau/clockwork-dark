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
import React, { useCallback, useState } from "react";

import Meters from "@core/parts/Meters.jsx";
import PaintFrame from "@core/parts/PaintFrame.jsx";
import {
  AnalystContext,
  AnalystSetContext,
  loadAnalyst,
  saveAnalyst,
} from "./analyst.js";
import Companion from "./parts/Companion.jsx";
import ContractsOverlay from "./parts/ContractsOverlay.jsx";
import CourtOverlay from "./parts/CourtOverlay.jsx";
import EpilogueCard from "./parts/EpilogueCard.jsx";
import GalleryOverlay from "./parts/GalleryOverlay.jsx";
import OmenSting from "./parts/OmenSting.jsx";
import { CourtIcon, MirrorIcon, ScrollIcon } from "./parts/Marks.jsx";
import { BANDS, HourglassMeter, VINES, VineMeter } from "./parts/Meters.jsx";

const HOURGLASS = "time_debt_mortal_days";

/**
 * The story's own slice: what the meters last said, and the omen that owes the
 * player a flash.
 *
 * `analyst` used to live here and no longer does. It was inert -- the slice
 * declared it, `Wrap` read it, and nothing in the client could write it,
 * because `Play.jsx` hands its slots no `dispatch`. It is a player preference
 * held in `Wrap` and persisted to localStorage; see ./analyst.js.
 */
const initialState = { bands: {}, decade: 0, omen: null, seen: false };

/**
 * The omens, and the thresholds they are omens OF.
 *
 * "Critical thresholds trigger one-time omen full-art stings." The engine
 * ships no omen channel, and it does not need to: every threshold worth a
 * sting is a value the player is already being shown, so the crossing is
 * detectable from two consecutive payloads. What the client must NOT do is
 * invent a threshold the fiction does not have, so there are four.
 *
 * Each id is minted once. `OmenSting` keeps its own fired-set, so crossing a
 * line, retreating and crossing it again does not re-fire -- an omen that
 * repeats is a status bar with a flash on it.
 */
const OMENS = [
  {
    id: "corruption-utmost",
    meter: "corruption",
    at: "utmost",
    tone: "gold",
    kicker: "An omen",
    line: "The gold under your skin has stopped being under it.",
  },
  {
    id: "favor-utmost",
    meter: "favor",
    at: "utmost",
    tone: "rose",
    kicker: "An omen",
    line: "She has run out of ways to want you more. That is not the safe end of the scale.",
  },
  {
    id: "autonomy-none",
    meter: "autonomy",
    at: "none",
    tone: "rose",
    kicker: "An omen",
    line: "You reach for the part of you that refuses, and find you have spent it.",
  },
  {
    id: "desire-utmost",
    meter: "desire",
    at: "utmost",
    tone: "rose",
    kicker: "An omen",
    line: "The heat stops being weather and starts being a direction.",
  },
];

/** Band word per meter, from the payload. Veiled values carry no number. */
function readBands(meters) {
  const out = {};
  for (const row of Object.values(meters || {})) {
    if (row && row.band) out[row.name] = row.band;
  }
  return out;
}

function sameBands(a, b) {
  const keys = new Set([...Object.keys(a || {}), ...Object.keys(b || {})]);
  for (const key of keys) if ((a || {})[key] !== (b || {})[key]) return false;
  return true;
}

/**
 * The first omen this payload earned, or null.
 *
 * NEVER on the first payload the client sees. A resumed save arrives with its
 * meters already deep, and firing four stings at once for thresholds the
 * player crossed days ago would be the client narrating history it did not
 * witness. `seen` is what makes the first payload a baseline rather than an
 * event.
 */
function detect(slice, bands, decade) {
  if (!slice.seen) return null;

  for (const omen of OMENS) {
    const now = bands[omen.meter];
    const before = slice.bands[omen.meter];
    if (now === omen.at && before !== omen.at) return omen;
  }

  // The hourglass is the one PUBLIC value in the story, and the only one that
  // carries a number. Every fiftieth mortal day is a beat the design asks for
  // out loud -- the ash hourglass turning over.
  if (decade > slice.decade) {
    return {
      id: `debt-${decade}`,
      tone: "gold",
      kicker: "The hourglass",
      line: `${decade * 50} days gone at home, and the grain has not stopped.`,
    };
  }
  return null;
}

/**
 * Derive this story's slice from the core state that was just reduced.
 *
 * Returns the SAME object when nothing moved, because the store uses identity
 * to decide whether to rebuild `state` -- a fresh object per streamed token
 * would re-render the companion column sixty times a second.
 */
function reduce(slice, action, next) {
  if (action.type === "RESET") return initialState;
  if (action.type !== "SOCKET") return slice;

  const bands = readBands(next.meters);
  const debt = Number(next.meters?.[HOURGLASS]?.value ?? 0);
  const decade = Math.floor(debt / 50);
  const omen = detect(slice, bands, decade);

  if (slice.seen && !omen && decade === slice.decade && sameBands(slice.bands, bands)) {
    return slice;
  }
  return { bands, decade, omen: omen || slice.omen, seen: true };
}

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
  // The Companion tab's label. "The court" moved to the overlay it now names;
  // the column is one person and says so.
  asideLabel: "Sophia",

  theme: () => import("./theme/wicked-garden.css"),

  initialState,
  reduce,

  Wordmark,
  Ledger,
  Stage,
  Ending: EndingScreen,

  /**
   * Sophia's column, and the Companion tab on a phone.
   *
   * Declaring this is what makes the tab exist at all: `Play.jsx` drops the
   * Companion tab for a story with no `Aside`, so the one story in the repo
   * whose subject is a live companion was the one with nowhere to put her on a
   * narrow viewport.
   */
  Aside: Companion,

  /**
   * The omen layer.
   *
   * A free-floating sting over the play screen, fired once per threshold from
   * the slice above. It reads the client's reduce-motion preference through
   * the same `document.documentElement.dataset` core already writes, and the
   * component turns the flash into a still card when it is set -- the design's
   * own accessibility list says "disable pollen storms / flash omens", and a
   * full-screen flash is exactly the thing that hurts people.
   */
  Toast: ({ state }) => (
    <OmenSting
      omen={state.story.omen}
      suppressed={document.documentElement.dataset.reduceMotion === "true"}
    />
  ),

  /**
   * Analyst mode, and the only thing in this story that holds client state.
   *
   * `Wrap` is above every screen and survives every turn, which is what the
   * preference needs: a slot cannot hold it (slots get no `dispatch`) and the
   * store cannot own it (it is a preference, not game state, and RESET would
   * wipe it on every new run).
   */
  Wrap: ({ children }) => {
    const [analyst, setAnalyst] = useState(loadAnalyst);
    const set = useCallback((on) => {
      setAnalyst(on);
      saveAnalyst(on);
    }, []);
    return (
      <AnalystContext.Provider value={analyst}>
        <AnalystSetContext.Provider value={set}>{children}</AnalystSetContext.Provider>
      </AnalystContext.Provider>
    );
  },

  /**
   * All five of this story's finished components are on screen now.
   *
   * Two of them were dark for months and neither was waiting on a component:
   * `ContractScroll` needed the player's live bargains and `EndingGallery`
   * needed the eligible set with its lock reasons, and `to_client_dict`
   * carried `meters` and nothing else. Both are things `StateStore` cannot
   * describe -- `get` returns a float, and one of these is a contract while
   * the other is a list of ids -- so the payload grew `threads` and `endings`
   * beside `meters` rather than through it.
   *
   * `when` IS THE HONEST HALF OF THAT. Each key is present only for a story
   * that declares the system behind it, so these two entries gate on the key
   * rather than on the slug: a story borrowing this skin without bargains gets
   * no scroll button at all, instead of one that opens on nothing. That is the
   * disease this seam was built to cure, and wiring a screen against a key
   * that may not exist is how it comes back.
   */
  overlays: [
    { id: "court", key: "c", label: "The court", Icon: CourtIcon, Component: CourtOverlay },
    {
      id: "contracts",
      key: "b",
      label: "What you have signed",
      Icon: ScrollIcon,
      Component: ContractsOverlay,
      when: (state) => Boolean(state.world?.threads),
    },
    {
      id: "mirror",
      key: "m",
      label: "The mirror pool",
      Icon: MirrorIcon,
      Component: GalleryOverlay,
      when: (state) => Boolean(state.world?.endings),
    },
  ],
  onboarding: [],
};
