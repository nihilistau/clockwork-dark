/**
 * Core's default stage: the scene plate (v0.21.0, spec §3.3, F2).
 *
 * `state.sceneImage` (reduced from `opening.scene_image` and `image_ready`)
 * in core's paint frame, its alt the place's own name; with no image, the
 * frame's wash and the place name in the narration face. Opt-in by plugin
 * (`defaultStage: true`): `_engine` sets it, so every story it dresses
 * (`dev-story`) gets the plate, and so does HUE & CRY's skin. A
 * plugin with neither a `Stage` nor this keeps a stage-less column (THE LONG
 * CON).
 */
import React from "react";

import PaintFrame from "./PaintFrame.jsx";
import { prettyPlace } from "./Chrome.jsx";

export default function ScenePlate({ state }) {
  const world = state?.world || {};
  const place = world.location_name || (world.location_id ? prettyPlace(world.location_id) : "");
  const src = state?.sceneImage || "";
  return (
    <PaintFrame size="hero" className="sceneplate">
      {src ? (
        <img className="sceneplate__img" src={src} alt={place} draggable="false" />
      ) : (
        <span className="sceneplate__name">{place}</span>
      )}
    </PaintFrame>
  );
}
