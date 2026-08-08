/**
 * Scene visual — a painted frame with a procedural fallback.
 *
 * The old client did `img.src = url` against `/static/placeholders/`, a
 * directory that does not exist, so every turn painted a broken-image icon.
 * Here the wash IS the fallback: with no image provider running at all the
 * frame still reads as a place, and a real still crossfades in on top when one
 * arrives.
 *
 * WHAT CHANGED
 * ------------
 * 1. WASH had five entries for a twenty-location graph, so fifteen places
 *    painted the same forest green. Every place in data/world/locations.yaml
 *    now has a wash, built on two axes -- its RING (how far in) and its
 *    CHARACTER (what it is) -- plus its own light position and gradient angle.
 *    No two places resolve to the same picture.
 * 2. The frame was a flat gradient, a grain and one vignette. It is now the
 *    layer stack from Design_files/ui_kits/clockwork-world/PaintFrame.jsx:
 *    candle bloom, low mist band, volumetric ray, corruption bleed, grain,
 *    tuned vignette, film lip, watermark, caption.
 *
 * The place table is exported because the Codex paints the same twenty places
 * again; the frame itself is core (core/parts/PaintFrame.jsx), because a frame
 * around a picture is not a thing this story invented.
 */
import React, { useEffect, useState } from "react";

import PaintFrame from "@core/parts/PaintFrame.jsx";

// Ring labels from data/world/locations.yaml. The graph is authoritative; this
// is the presentation copy of it, which is why it carries no hours, no DCs and
// no connections -- only what a painter needs.
export const RING_NAMES = [
  "The Deep Forest",
  "Edgewood",
  "The Marches",
  "The Heartland Road",
];

/**
 * The twenty places.
 *
 *   ring       0-3, straight from locations.yaml. Sets the palette temperature.
 *   char       which --char-* bloom sits over that palette.
 *   light      "x y size" of the bloom. A place lit from overhead at 8% is a
 *              clearing at dawn; one lit from 62% is a room with a fire in it.
 *   angle      gradient direction. Interiors run steeper than open country.
 *   unknown    what the Atlas says about a place you have not walked to.
 *              Nineteen cards used to share one sentence.
 */
export const PLACES = {
  // ---- Ring 0 · the deep forest ----
  forest_clearing: {
    ring: 0, char: "wild", light: "52% 8% 62%", angle: 168,
    unknown: "Birch gives way to fern somewhere out there.",
  },
  deeper_forest: {
    ring: 0, char: "under", light: "40% 2% 40%", angle: 190,
    unknown: "The trees close over it. No one has drawn what is inside.",
  },
  herb_glen: {
    ring: 0, char: "water", light: "60% 14% 70%", angle: 158,
    unknown: "A wet green quiet, by all accounts. Accounts differ.",
  },
  old_barrows: {
    ring: 0, char: "ruin", light: "46% 4% 46%", angle: 176,
    unknown: "Mounds older than the village. The village does not go there.",
  },
  tunnel_entrance: {
    ring: 0, char: "under", light: "50% 68% 54%", angle: 200,
    unknown: "A mouth in the hillside. Nobody agrees on how deep.",
  },
  charcoal_burn: {
    ring: 0, char: "hearth", light: "34% 62% 44%", angle: 150,
    unknown: "Smoke stands over it all week. You have seen the smoke.",
  },

  // ---- Ring 1 · Edgewood ----
  edgewood_square: {
    ring: 1, char: "trade", light: "64% 12% 62%", angle: 172,
    unknown: "Timber frames around an oven. You can smell it from the trees.",
  },
  edgewood_bakery: {
    ring: 1, char: "hearth", light: "50% 58% 66%", angle: 186,
    unknown: "A door in the square with flour on the step.",
  },
  tinker_caravan: {
    ring: 1, char: "trade", light: "44% 26% 54%", angle: 162,
    unknown: "It moves. Ask three people, get three roads.",
  },
  edgewood_shrine: {
    ring: 1, char: "sacred", light: "50% 44% 38%", angle: 194,
    unknown: "Someone keeps a candle in it. Nobody will say for whom.",
  },
  the_forge: {
    ring: 1, char: "hearth", light: "30% 66% 50%", angle: 182,
    unknown: "You can hear it before you find it.",
  },
  well_row: {
    ring: 1, char: "water", light: "58% 20% 58%", angle: 166,
    unknown: "Where Edgewood keeps its water and its arguments.",
  },
  fallow_farm: {
    ring: 1, char: "wild", light: "70% 10% 74%", angle: 154,
    unknown: "Nothing has been sown there for two seasons.",
  },

  // ---- Ring 2 · the Marches ----
  millhaven_gate: {
    ring: 2, char: "stone", light: "50% 8% 66%", angle: 174,
    unknown: "They shut it at dusk now. They did not used to.",
  },
  millhaven_market: {
    ring: 2, char: "trade", light: "60% 16% 64%", angle: 168,
    unknown: "Everything the Marches can still sell, in one square.",
  },
  millhaven_barracks: {
    ring: 2, char: "ruin", light: "42% 30% 46%", angle: 188,
    unknown: "The militia's house. Being invited is not good news.",
  },
  toll_bridge: {
    ring: 2, char: "water", light: "52% 12% 70%", angle: 160,
    unknown: "The only dry crossing, and it is not free.",
  },
  refugee_camp: {
    ring: 2, char: "hearth", light: "38% 54% 48%", angle: 178,
    unknown: "A ditch with fires in it. It was not there last year.",
  },
  burned_farmstead: {
    ring: 2, char: "ruin", light: "56% 40% 56%", angle: 184,
    unknown: "Whatever happened, it happened quickly.",
  },

  // ---- Ring 3 · the Heartland Road ----
  heartland_road: {
    ring: 3, char: "stone", light: "50% 6% 72%", angle: 170,
    unknown: "It runs inward. That is all anyone will tell you.",
  },
};

const FALLBACK = PLACES.forest_clearing;

/** The place's painted wash, as a `background` shorthand. */
export function washFor(placeId) {
  const p = PLACES[placeId] || FALLBACK;
  const [x, y, size] = p.light.split(" ");
  const h = `calc(${size} * 0.82)`;
  return [
    // The bloom: whatever light this place has, wherever it comes from.
    `radial-gradient(${size} ${h} at ${x} ${y}, var(--char-${p.char}), transparent 64%)`,
    // The ground beneath it: sky, middle distance, lit ground, near edge.
    `linear-gradient(${p.angle}deg,` +
      ` var(--ring${p.ring}-shade) 0%,` +
      ` var(--ring${p.ring}-mid) 42%,` +
      ` var(--ring${p.ring}-lift) 74%,` +
      ` var(--ring${p.ring}-edge) 100%)`,
  ].join(", ");
}

export function ringOf(placeId) {
  return (PLACES[placeId] || FALLBACK).ring;
}

export function unknownLine(placeId) {
  return (PLACES[placeId] || FALLBACK).unknown;
}

// Only the daypart tints; the place already carries its own colour. Kept as a
// separate multiply pass so dusk reads as dusk everywhere rather than being
// baked into twenty gradients.
const TIME_TINT = {
  dawn: "rgba(214, 178, 108, 0.16)",
  day: "rgba(214, 200, 160, 0.06)",
  dusk: "rgba(150, 90, 60, 0.20)",
  night: "rgba(20, 30, 50, 0.34)",
};

export default function SceneVisual({ world, imageUrl, phase }) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setLoaded(false);
    setFailed(false);
  }, [imageUrl]);

  const location = world?.location_id || "forest_clearing";
  const time = world?.time_of_day || "day";
  const showImage = imageUrl && !failed;
  // The wash keeps painting under a loaded still: the still is 16:9 and the
  // row is not, so `object-fit: cover` leaves the frame's own colour showing
  // in the letterbox rather than a black bar.
  return (
    <PaintFrame
      className="visual"
      size="hero"
      wash={washFor(location)}
      tint={TIME_TINT[time] || TIME_TINT.day}
      corrupted={phase === "spreading" || phase === "consuming"}
      watermark={`${RING_NAMES[ringOf(location)]}`}
      caption={`${location.replace(/_/g, " ")} · ${time}`}
      style={{ "--phase": phase }}
    >
      <span className="paint__bloom" aria-hidden="true" />
      {showImage && (
        <img
          className={`paint__img ${loaded ? "is-loaded" : ""}`}
          src={imageUrl}
          alt={`${location.replace(/_/g, " ")}, ${time}`}
          onLoad={() => setLoaded(true)}
          // Without this a missing file leaves a broken-image glyph over the
          // narration for the rest of the session.
          onError={() => setFailed(true)}
        />
      )}
    </PaintFrame>
  );
}
