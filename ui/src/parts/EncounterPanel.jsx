/**
 * The encounter.
 *
 * `state.encounter` has shipped in every turn payload since P6 and nothing
 * rendered it: a wolf could open its jaws, take three rounds of your resolve
 * and leave, and the only trace on screen was prose. This panel is the fix.
 *
 * Two rules govern it:
 *
 *  - The approach list is ENGINE-AUTHORED and every entry is legal right now
 *    (engine/game/encounter.py::available_approaches filters on gold, hour and
 *    inventory before it ships). We render exactly what is in the list and
 *    never synthesize an option — an invented approach is one the engine will
 *    refuse, which reads to the player as the game lying.
 *  - Taking an approach is an ordinary turn. We send the approach's own text
 *    as a custom action; the Storyteller calls `encounter_approach` itself.
 */
import React from "react";
import useArtUrl from "../hooks/useArtUrl.js";
import SceneVisual from "./SceneVisual.jsx";

const DIFFICULTY_LABEL = {
  trivial: "trivial",
  easy: "easy",
  standard: "even",
  hard: "hard",
  severe: "severe",
};

function Resolve({ threat }) {
  const max = Math.max(1, Number(threat?.resolve_max) || 1);
  const value = Math.max(0, Number(threat?.resolve) || 0);
  const pct = Math.min(100, (value / max) * 100);

  return (
    <div
      className="resolve"
      role="meter"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-label={`${threat?.name || "Threat"} resolve`}
    >
      <div className="resolve__row">
        <span className="resolve__label">Resolve</span>
        <span className="resolve__value">
          {value}
          <span className="resolve__max">/{max}</span>
        </span>
      </div>
      <div className="resolve__track">
        <div className="resolve__fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function Approach({ approach, busy, onTake }) {
  const difficulty = DIFFICULTY_LABEL[approach.difficulty] || approach.difficulty;
  const cost = Number(approach.cost_gold) || 0;

  return (
    <button
      type="button"
      className="approach"
      disabled={busy}
      onClick={() => onTake(approach)}
    >
      <span className="approach__text">{approach.text}</span>
      <span className="approach__meta">
        {/* An automatic approach makes no roll at all. Showing a difficulty
            beside it would promise a check the engine is not going to make. */}
        {approach.auto ? (
          <span className="approach__tag">no roll</span>
        ) : (
          <>
            {approach.skill && <span className="approach__tag">{approach.skill}</span>}
            {difficulty && <span className="approach__tag">{difficulty}</span>}
          </>
        )}
        {cost > 0 && <span className="approach__tag approach__tag--cost">{cost} gold</span>}
      </span>
    </button>
  );
}

export default function EncounterPanel({ encounter, world, phase, sceneImage, busy, onTake }) {
  const artUrl = useArtUrl(encounter.art, encounter.art_kind || "enemy");
  const threat = encounter.threat || {};
  const log = encounter.log || [];
  const approaches = encounter.approaches || [];
  const round = Number(encounter.round) || 0;

  return (
    <section className="encounter" aria-labelledby="encounter-threat">
      {artUrl ? (
        <div className="encounter__art">
          <img className="encounter__img" src={artUrl} alt={threat.name || "The threat"} />
          <div className="encounter__grain" aria-hidden="true" />
          <div className="encounter__vignette" aria-hidden="true" />
        </div>
      ) : (
        // Most encounters carry no `art` key at all, so this is the common
        // path, not the error path: the place itself stands in, and
        // SceneVisual's gradient wash never 404s.
        <SceneVisual world={world} imageUrl={sceneImage} phase={phase} />
      )}

      <header className="encounter__head">
        <div className="encounter__naming">
          <p className="encounter__kicker">Facing you</p>
          <h2 className="encounter__threat" id="encounter-threat">
            {threat.name || "Trouble"}
          </h2>
        </div>
        <div className="encounter__gauges">
          {round > 0 && (
            <span className="encounter__round">
              Round {round}
              {encounter.max_rounds ? ` / ${encounter.max_rounds}` : ""}
            </span>
          )}
          <Resolve threat={threat} />
        </div>
      </header>

      {encounter.intro && <p className="encounter__intro">{encounter.intro}</p>}

      {log.length > 0 && (
        <ol className="encounter__log" aria-label="Rounds so far">
          {log.map((entry, index) => (
            <li key={`${entry.round}-${index}`} className="encounter__beat" data-degree={entry.degree}>
              <span className="encounter__beat-round">{entry.round}</span>
              <span className="encounter__beat-body">
                {entry.text || entry.summary}
                {entry.degree && <span className="encounter__beat-degree">{entry.degree}</span>}
              </span>
            </li>
          ))}
        </ol>
      )}

      <div className="encounter__approaches" role="group" aria-label="Approaches">
        {approaches.map((approach) => (
          <Approach key={approach.id} approach={approach} busy={busy} onTake={onTake} />
        ))}
        {approaches.length === 0 && (
          <p className="encounter__none">
            Nothing you can do from here but speak, and see what that costs.
          </p>
        )}
      </div>
    </section>
  );
}
