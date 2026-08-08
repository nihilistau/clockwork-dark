/**
 * CourtBoard — a political map, not a dating-sim checklist.
 *
 * 06-UI-UX, verbatim: "Sophia center; satellites for major NPCs" · "Lines show
 * tension (gold / silver / black)" · "Not a dating-sim checklist — a
 * political-emotional map".
 *
 * WHAT THAT RULES OUT
 * -------------------
 * A list of portraits with hearts beside them. The information a player needs
 * here is not "how much does each NPC like me" -- it is who is bound to whom,
 * and which of those bindings is under strain. So the drawing is a graph and
 * the EDGES carry the meaning; the nodes are just where the edges land.
 *
 * The three line colours are named in the design and never defined, so this is
 * the reading committed to (and it is the one the day scripts behave as if):
 *
 *   gold    an obligation — a debt, a thread, a bargain being honoured
 *   silver  a watching — attention without a claim, courtly interest
 *   black   a grievance — something owed that is not going to be paid
 *
 * The third one is drawn as a cold bruise rather than literal black, because
 * literal black on a #0d080c page is a gap and not a line. Its DOTTED dash is
 * what carries the distinction; the colour only supports it.
 *
 * Thickness is the strain on the tie, not its warmth. A thick black line is a
 * feud about to break; a thin gold one is a favour nobody has called in.
 *
 * Colour is never the only channel: gold is solid, silver is dashed, black is
 * dotted, so the graph survives being read by someone who cannot separate them.
 *
 * A root NPC (Mother Briar) hangs UNDER the centre rather than orbiting it,
 * because the day script says so -- "Briar node appears as root under Sophia".
 */
import React from "react";

const RADIUS = 132;
const CENTRE = 170;

const EDGE = {
  obligation: { stroke: "var(--wg-gold)", dash: "none", label: "an obligation" },
  watching: { stroke: "var(--wg-iron)", dash: "7 5", label: "a watching" },
  grievance: { stroke: "var(--wg-grievance)", dash: "2 6", label: "a grievance" },
};

/** Even spacing around the circle, starting at the top. */
function place(index, count) {
  const angle = (index / Math.max(count, 1)) * Math.PI * 2 - Math.PI / 2;
  return {
    x: CENTRE + Math.cos(angle) * RADIUS,
    y: CENTRE + Math.sin(angle) * RADIUS,
  };
}

export default function CourtBoard({ centre, satellites = [], roots = [], edges = [], onSelect }) {
  const orbit = satellites.map((node, i) => ({ ...node, ...place(i, satellites.length) }));
  const under = roots.map((node, i) => ({
    ...node,
    x: CENTRE + (i - (roots.length - 1) / 2) * 96,
    y: CENTRE + RADIUS + 78,
  }));
  const all = [{ ...centre, x: CENTRE, y: CENTRE }, ...orbit, ...under];
  const at = Object.fromEntries(all.map((n) => [n.id, n]));

  return (
    <div className="court">
      <svg
        className="court__graph"
        viewBox={`0 0 ${CENTRE * 2} ${CENTRE * 2 + 120}`}
        role="img"
        aria-label="The court, and what holds it together"
      >
        <g className="court__edges">
          {edges.map((edge) => {
            const a = at[edge.from];
            const b = at[edge.to];
            if (!a || !b) return null;
            const kind = EDGE[edge.kind] || EDGE.watching;
            return (
              <line
                key={`${edge.from}-${edge.to}-${edge.kind}`}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={kind.stroke}
                strokeWidth={1 + (edge.strain ?? 1) * 1.6}
                strokeDasharray={kind.dash === "none" ? undefined : kind.dash}
                strokeLinecap="round"
                opacity={0.55 + (edge.strain ?? 1) * 0.15}
              />
            );
          })}
        </g>

        {all.map((node) => (
          <g
            key={node.id}
            className={`court__node ${node.id === centre.id ? "is-centre" : ""}`}
            transform={`translate(${node.x} ${node.y})`}
          >
            <circle r={node.id === centre.id ? 34 : 26} />
            <text className="court__initial" textAnchor="middle" dy="0.36em">
              {(node.name || "?").slice(0, 1)}
            </text>
          </g>
        ))}
      </svg>

      {/* The graph is a picture; this is the same information as text, which is
          what makes it usable by keyboard and by a reader. It is not a fallback
          -- both are always on screen. */}
      <ul className="court__roll">
        {all.map((node) => {
          const ties = edges.filter((e) => e.from === node.id || e.to === node.id);
          return (
            <li key={node.id} className="courtrow">
              <button
                type="button"
                className="courtrow__btn"
                onClick={() => onSelect?.(node.id)}
              >
                <span className="courtrow__name">{node.name}</span>
                <span className="courtrow__standing">{node.standing}</span>
                <span className="courtrow__ties">
                  {ties.length === 0
                    ? "no tie to anyone yet"
                    : ties
                        .map((tie) => {
                          const other = tie.from === node.id ? tie.to : tie.from;
                          return `${(EDGE[tie.kind] || EDGE.watching).label} with ${
                            at[other]?.name || other
                          }`;
                        })
                        .join(" · ")}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <ul className="court__key">
        {Object.entries(EDGE).map(([id, kind]) => (
          <li key={id} className="court__keyrow" data-kind={id}>
            <span className="court__keyline" aria-hidden="true" />
            {kind.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
