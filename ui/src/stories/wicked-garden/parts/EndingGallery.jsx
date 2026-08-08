/**
 * EndingGallery — silhouette, locked, unlocked.
 *
 * Three tiers, and the middle one is where all the design pressure is:
 *
 *   unlocked   you reached it; the medallion is lit and titled
 *   locked     you can still reach it; the shape is there, the art is grey
 *   silhouette you cannot reach it from here; only the outline exists
 *
 * THE HONESTY RULE
 * ----------------
 * "Never show ineligible IDs as completable cards." "Eligibility must be honest
 * — no fake cards that cannot complete Day 9." A gallery that shows six equal
 * cards when two of them are already impossible is lying to a player who is
 * about to spend their last day on one.
 *
 * So an ineligible ending is a SILHOUETTE, visibly a different tier from a
 * locked-but-open one, and inspecting it says the requirement is missing. What
 * it does NOT say by default is which number and by how much: the default is
 * "poetic epilogue tease + mechanical requirements missing". Analyst mode is
 * what turns that into the raw gate.
 *
 * That split is the whole reason `lockReason` and `gate` are separate props. A
 * story author writes the reason in the story's voice; the gate string is the
 * engine's own condition, and it only ever appears for a player who asked.
 */
import React, { useState } from "react";

import { useAnalyst } from "../analyst.js";

const TIER_WORD = {
  unlocked: "reached",
  locked: "still open",
  silhouette: "out of reach from here",
};

export default function EndingGallery({ endings = [], onSwear, onLook }) {
  const analyst = useAnalyst();
  const [open, setOpen] = useState(null);
  const chosen = endings.find((e) => e.id === open) || null;

  return (
    <section className="gallery" aria-label="What you became">
      <ul className="gallery__grid">
        {endings.map((ending) => (
          <li key={ending.id} className="ending" data-tier={ending.tier}>
            <button
              type="button"
              className="ending__card"
              aria-expanded={open === ending.id}
              onClick={() => setOpen(open === ending.id ? null : ending.id)}
            >
              <span className="ending__medallion" aria-hidden="true">
                <span className="ending__shape" />
                {ending.tier === "locked" && <span className="ending__lock" />}
              </span>
              <span className="ending__id">{ending.id}</span>
              <span className="ending__title">
                {ending.tier === "silhouette" ? "—" : ending.title}
              </span>
              <span className="ending__tier">{TIER_WORD[ending.tier]}</span>
            </button>
          </li>
        ))}
      </ul>

      {chosen && (
        <article className="gallery__inspect" aria-live="polite">
          <h3 className="gallery__inspect-title">
            {chosen.tier === "silhouette" ? `${chosen.id} · unknown` : `${chosen.id} · ${chosen.title}`}
          </h3>
          <p className="gallery__tease">{chosen.tease}</p>

          {chosen.tier !== "unlocked" && (
            <p className="gallery__reason">
              {chosen.lockReason || "Something you have not done yet."}
            </p>
          )}

          {/* The numbers, and only for a player who asked for them. Without
              this the gate is never spelled out anywhere in the product. */}
          {analyst && chosen.tier !== "unlocked" && chosen.gate && (
            <p className="gallery__gate">
              <span className="gallery__gate-kicker">Requires</span>
              <code>{chosen.gate}</code>
            </p>
          )}

          <div className="gallery__actions">
            <button
              type="button"
              className="btn btn--sm"
              disabled={chosen.tier === "silhouette"}
              onClick={() => onSwear?.(chosen.id)}
            >
              Swear toward this
            </button>
            <button type="button" className="btn btn--sm btn--ghost" onClick={() => onLook?.(chosen.id)}>
              Look only
            </button>
          </div>
          <p className="gallery__warn">
            Swearing bends the last day toward this and closes some of its
            opposites. Looking costs nothing.
          </p>
        </article>
      )}
    </section>
  );
}
