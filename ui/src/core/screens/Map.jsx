/**
 * The map — where you are, what it connects to, and what is worth going to.
 *
 * WHY THIS IS IN CORE. The atlas payload (`GET /api/codex/places`) has carried
 * places, rings, roads with hours and danger, and a discovered flag since the
 * codex was built — and exactly one screen in the whole client read it: the
 * flagship's Codex, as a grid of cards. Three of the four shipped stories had
 * a travel graph and no way to see it. A map is not a story's flourish; it is
 * what a graph MEANS to a player, so it belongs to the engine and a story
 * restyles it.
 *
 * A NODE MAP, NOT A CARD GRID. The flagship's Atlas answers "what places exist
 * and what are they like"; this answers "where am I and where can I go". They
 * are different questions and the flagship keeps its own screen.
 *
 * WHAT IT DELIBERATELY CANNOT SHOW. A place the story marked `secret: true`
 * never reaches the browser at all until it is walked — not greyed, not
 * counted, not hinted at by a road stub. Fog of war and a spoiler are
 * different problems: the first is "you have not been there", the second is
 * "you must not know it is there", and drawing a tantalising grey rectangle
 * for the second would give the secret away in the act of keeping it.
 */
import React, { useEffect, useMemo, useState } from "react";

import Modal from "../parts/Modal.jsx";

/** Ring 0 sits at the centre; each further ring is a wider orbit. */
const RING_RADIUS = 78;
const VIEW = 420;

/**
 * Lay the graph out by ring, spreading each ring's places evenly around it.
 *
 * Deterministic on purpose — a map that reshuffles its own geography between
 * openings is a map nobody can learn. Position comes from the ring and the
 * alphabetical index within it, so the same world always draws the same shape.
 */
function layout(places) {
  const rings = new Map();
  for (const place of places) {
    const ring = Number(place.ring || 0);
    if (!rings.has(ring)) rings.set(ring, []);
    rings.get(ring).push(place);
  }

  const positions = {};
  const centre = VIEW / 2;
  for (const [ring, members] of [...rings.entries()].sort((a, b) => a[0] - b[0])) {
    const sorted = [...members].sort((a, b) => a.id.localeCompare(b.id));
    if (ring === 0 && sorted.length === 1) {
      positions[sorted[0].id] = { x: centre, y: centre };
      continue;
    }
    const radius = RING_RADIUS * (ring === 0 ? 0.55 : ring);
    sorted.forEach((place, index) => {
      const angle = (index / sorted.length) * Math.PI * 2 - Math.PI / 2;
      positions[place.id] = {
        x: centre + Math.cos(angle) * radius,
        y: centre + Math.sin(angle) * radius,
      };
    });
  }
  return positions;
}

export default function MapScreen({ sessionId, onClose }) {
  const [places, setPlaces] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState("");

  useEffect(() => {
    let live = true;
    const url = sessionId
      ? `/api/codex/places?session_id=${encodeURIComponent(sessionId)}`
      : "/api/codex/places";
    fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => live && setPlaces(data.places || []))
      // A map that fails to load says so. The previous generation of this
      // client had two unchecked fetches and a screen that just stayed blank.
      .catch((err) => live && setError(String(err.message || err)));
    return () => {
      live = false;
    };
  }, [sessionId]);

  const positions = useMemo(() => layout(places || []), [places]);
  const byId = useMemo(
    () => Object.fromEntries((places || []).map((p) => [p.id, p])),
    [places]
  );

  const here = (places || []).find((place) => place.here);
  const focus = byId[selected] || here || (places || [])[0];

  /* Each road once. The graph is authored in both directions (the loader even
     mirrors a missing return leg), so drawing every entry would stack two
     lines per road and double every hairline's opacity. */
  const edges = [];
  const drawn = new Set();
  for (const place of places || []) {
    for (const road of place.roads || []) {
      const key = [place.id, road.to].sort().join(">");
      if (drawn.has(key) || !positions[place.id] || !positions[road.to]) continue;
      drawn.add(key);
      edges.push({ key, from: place.id, to: road.to, hours: road.hours });
    }
  }

  return (
    <Modal title="The map" onClose={onClose} wide>
      {error && <p className="status status--error" role="status">{error}</p>}
      {!places && !error && <p className="status" role="status">Reading the roads…</p>}

      {places && places.length === 0 && (
        <p className="map__empty">
          This story keeps no map. Nowhere connects to anywhere; the whole of it
          happens where you are standing.
        </p>
      )}

      {places && places.length > 0 && (
        <div className="map">
          <svg
            className="map__plot"
            viewBox={`0 0 ${VIEW} ${VIEW}`}
            role="img"
            aria-label="Map of known places and the roads between them"
          >
            {edges.map((edge) => (
              <line
                key={edge.key}
                className="map__road"
                x1={positions[edge.from].x}
                y1={positions[edge.from].y}
                x2={positions[edge.to].x}
                y2={positions[edge.to].y}
              />
            ))}
            {places.map((place) => {
              const at = positions[place.id];
              if (!at) return null;
              return (
                <g
                  key={place.id}
                  className="map__node"
                  data-here={place.here ? "yes" : "no"}
                  data-known={place.discovered ? "yes" : "no"}
                  data-points={(place.points || []).length > 0 ? "yes" : "no"}
                  transform={`translate(${at.x} ${at.y})`}
                  onClick={() => setSelected(place.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && setSelected(place.id)}
                  aria-label={place.name}
                >
                  <circle className="map__dot" r={place.here ? 9 : 6} />
                  <text className="map__label" y={-13}>
                    {place.discovered ? place.name : "?"}
                  </text>
                </g>
              );
            })}
          </svg>

          {focus && (
            <aside className="map__detail">
              <h3 className="map__name">
                {focus.discovered ? focus.name : "Somewhere you have not been"}
              </h3>
              {focus.here && <p className="map__you">You are here.</p>}

              {(focus.points || []).length > 0 && (
                <ul className="map__points">
                  {focus.points.map((point, index) => (
                    <li key={index} className={`map__point map__point--${point.kind}`}>
                      {point.label}
                    </li>
                  ))}
                </ul>
              )}

              {(focus.roads || []).length > 0 ? (
                <ul className="map__roads">
                  {focus.roads.map((road) => (
                    <li key={road.to}>
                      <button
                        type="button"
                        className="map__roadlink"
                        onClick={() => setSelected(road.to)}
                      >
                        {road.name}
                      </button>
                      {road.hours ? <span className="map__cost">{road.hours}h</span> : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="map__roads map__roads--none">No road you have heard of.</p>
              )}
            </aside>
          )}
        </div>
      )}
    </Modal>
  );
}
