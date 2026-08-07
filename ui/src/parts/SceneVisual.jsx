/**
 * Scene visual — layered still with a procedural fallback.
 *
 * The old client did `img.src = url` against `/static/placeholders/`, a
 * directory that does not exist, so every turn painted a broken-image icon.
 * Here the gradient IS the fallback: with no image provider running at all the
 * frame still reads as a place, and a real still crossfades in on top when one
 * arrives.
 */
import React, { useEffect, useState } from "react";

// Deterministic per-location mood wash. Not art -- a legible stand-in that
// never 404s.
const WASH = {
  forest_clearing: ["#16221a", "#2c3e2c"],
  edgewood_square: ["#221d16", "#3a3125"],
  edgewood_bakery: ["#2a1f14", "#463320"],
  tinker_caravan: ["#1d1a24", "#332c3f"],
  millhaven_gate: ["#1a1c22", "#2e333d"],
};

const TIME_TINT = {
  dawn: "rgba(214, 178, 108, 0.16)",
  day: "rgba(214, 200, 160, 0.08)",
  dusk: "rgba(150, 90, 60, 0.18)",
  night: "rgba(20, 30, 50, 0.30)",
};

export default function SceneVisual({ world, imageUrl, phase }) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setLoaded(false);
    setFailed(false);
  }, [imageUrl]);

  const location = world?.location_id || "forest_clearing";
  const [from, to] = WASH[location] || WASH.forest_clearing;
  const tint = TIME_TINT[world?.time_of_day] || TIME_TINT.day;
  const showImage = imageUrl && !failed;

  return (
    <div className="visual" data-phase={phase}>
      <div
        className="visual__wash"
        style={{ background: `linear-gradient(160deg, ${from}, ${to})` }}
      />
      <div className="visual__tint" style={{ background: tint }} />

      {showImage && (
        <img
          className={`visual__img ${loaded ? "is-loaded" : ""}`}
          src={imageUrl}
          alt={`${location.replace(/_/g, " ")}, ${world?.time_of_day || "day"}`}
          onLoad={() => setLoaded(true)}
          // Without this a missing file leaves a broken-image glyph over the
          // narration for the rest of the session.
          onError={() => setFailed(true)}
        />
      )}

      <div className="visual__grain" aria-hidden="true" />
      <div className="visual__vignette" aria-hidden="true" />

      <span className="visual__caption">
        {location.replace(/_/g, " ")} · {world?.time_of_day || "day"}
      </span>
    </div>
  );
}
