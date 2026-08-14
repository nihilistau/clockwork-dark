/**
 * The top of the centre column: where you are, and what is currently in the
 * way of you being somewhere else.
 *
 * THE FOUR-LAYER CANVAS, and why it is drawn here rather than reached for.
 * README non-negotiable 1 spells the scene background as black + an 80px
 * perspective drift grid + a radial scene glow + CRT scanlines, and calls it
 * non-negotiable for scene-level surfaces. Core ships `PaintFrame`, which is a
 * beautiful thing and is wrong for this: mist, a god-ray and a film lip are a
 * PAINTING's furniture, and this story's plate is a screen. So the frame below
 * is its own four spans and borrows nothing but the sizing convention.
 *
 * The glow and the grid both take `--nc-accent`, so the whole frame retones
 * when the district does -- one variable, set on <body> by the plugin.
 *
 * THE CONTACT STRIP. `world.encounter` carries engine-authored approaches:
 * anything in that list is a move `resolve_approach` will actually accept, and
 * anything the runner cannot pay for or reach at this hour is already absent
 * from it (engine/game/encounter.py::available_approaches). Rendering them is
 * not decoration -- without a panel the only route to an engine-legal move is
 * for the player to guess its wording into the compose box. It is drawn as a
 * HUD strip rather than as a combat board because this story's set-pieces are
 * arguments, gates and doors far more often than they are fights.
 *
 * Each approach carries its price in ₵ when it has one, because money is the
 * moral system here and a cost that only shows up after the fact is the one
 * kind of surprise the register does not permit.
 */
import React from "react";

/** The five districts that retone the canvas, keyed off location id. */
const DISTRICT = {
  the_grid: "grid",
  neon_strip: "strip",
  club_noir: "strip",
  velvet_pit: "strip",
  junkyard_sprawl: "junkyard",
  deepstate_bunker: "bunker",
  synthsec_gridpoint: "gridpoint",
};

/** Which accent a place sets. Exported: the plugin's `bodyData` says it once. */
export function districtOf(locationId) {
  return DISTRICT[String(locationId || "")] || "neoncity";
}

function Approach({ approach, busy, onTake }) {
  const cost = Number(approach.cost_gold) || 0;
  return (
    <button
      type="button"
      className="nc-approach"
      disabled={busy}
      onClick={() => onTake(approach)}
    >
      <span className="nc-approach__point" aria-hidden="true">▸</span>
      <span className="nc-approach__text">{approach.text}</span>
      {cost > 0 && (
        <span className="nc-approach__cost">
          <span aria-hidden="true">₵</span>
          {cost.toLocaleString("en-US")}
        </span>
      )}
      {approach.skill && <span className="nc-approach__skill">{approach.skill}</span>}
    </button>
  );
}

function Contact({ encounter, busy, onTake }) {
  const approaches = encounter.approaches || [];
  return (
    <div className="nc-contact" role="group" aria-label="Contact">
      <div className="nc-contact__head">
        <span className="nc-contact__tag">◈ CONTACT</span>
        {encounter.round > 0 && (
          <span className="nc-contact__round">
            PASS {String(encounter.round).padStart(2, "0")}
            {encounter.max_rounds ? ` / ${String(encounter.max_rounds).padStart(2, "0")}` : ""}
          </span>
        )}
      </div>
      {encounter.intro && <p className="nc-contact__intro">{encounter.intro}</p>}
      {approaches.length > 0 ? (
        <div className="nc-contact__moves">
          {approaches.map((approach) => (
            <Approach
              key={approach.id}
              approach={approach}
              busy={busy}
              onTake={onTake}
            />
          ))}
        </div>
      ) : (
        /* An encounter with no legal approach is a real state -- everything on
           the board costs more than you are holding, or the hour is wrong.
           Saying so is better than an empty strip, and the compose box is
           still there. */
        <p className="nc-contact__none">
          Nothing on this board is something you can currently afford to do.
        </p>
      )}
    </div>
  );
}

/** The plate. Black under everything, four layers over it, image on top. */
function Plate({ src, caption }) {
  return (
    <figure className="nc-plate">
      <span className="nc-plate__grid" aria-hidden="true" />
      <span className="nc-plate__glow" aria-hidden="true" />
      {src && (
        <img
          className="nc-plate__img"
          src={src}
          /* Decorative: the narration already says where you are, and a
             screen-reader user hearing a filename-derived description of a
             render is worse served than by silence. */
          alt=""
          loading="lazy"
          draggable="false"
        />
      )}
      <span className="nc-plate__scan" aria-hidden="true" />
      {caption && <figcaption className="nc-plate__caption">{caption}</figcaption>}
    </figure>
  );
}

export default function Stage({ state, busy, onCustom }) {
  const encounter = state.world?.encounter || {};
  const place = state.world?.location_id || "";
  const caption = place ? place.replace(/_/g, " ").toUpperCase() : "";

  return (
    <div className="nc-stage">
      <Plate src={state.sceneImage} caption={caption} />
      {Object.keys(encounter).length > 0 && (
        <Contact
          encounter={encounter}
          busy={busy}
          // An approach is an ORDINARY TURN: its own text goes over as a
          // custom action and the Storyteller calls encounter_approach. The
          // engine stays the only writer of the outcome.
          onTake={(approach) => onCustom(approach.text)}
        />
      )}
    </div>
  );
}
