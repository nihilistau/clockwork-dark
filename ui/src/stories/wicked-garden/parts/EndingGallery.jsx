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
 *
 * `closeness` and `canSwear` arrived when the server finally started sending
 * this screen its data, and both are the honesty rule again rather than new
 * ideas. `closeness` is the ending's continuous score AS A BAND WORD -- the
 * whole point of a continuous score is to foreshadow what is not yet available,
 * and a locked card with no sense of movement cannot do that; it is a word and
 * never a number, for the same reason every meter in this story is.
 * `canSwear` is false once the finale has committed, because a "Swear toward
 * this" that cannot bend anything is the fake card this component exists to
 * refuse, wearing a different hat.
 */
import React, { useState } from "react";

import { useAnalyst } from "../analyst.js";

const TIER_WORD = {
  unlocked: "reached",
  locked: "still open",
  silhouette: "out of reach from here",
};

// Whole sentences, not fragments to be glued to a stem. Written as fragments
// first, and "You have come the faintest pull." is what that reads like on
// screen -- a band word is a WORD, and the sentence has to be built around it
// rather than the other way round.
const NEAR_WORD = {
  none: "Nothing of you is pointed this way yet.",
  faint: "There is the faintest pull toward it.",
  some: "You have come some of the way.",
  strong: "You have come most of the way.",
  utmost: "You are all but there.",
};

export default function EndingGallery({ endings = [], canSwear = true, onSwear, onLook }) {
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

          {/* How far along this one is, as a word. Shown for the two tiers
              that are not yet yours, because that is the only place it can
              tell the player anything -- an ending you have reached is not
              "most of the way" to anything. */}
          {chosen.tier !== "unlocked" && NEAR_WORD[chosen.closeness] && (
            <p className="gallery__near">{NEAR_WORD[chosen.closeness]}</p>
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
              disabled={chosen.tier === "silhouette" || !canSwear}
              onClick={() => onSwear?.(chosen.id)}
            >
              Swear toward this
            </button>
            <button type="button" className="btn btn--sm btn--ghost" onClick={() => onLook?.(chosen.id)}>
              Look only
            </button>
          </div>
          <p className="gallery__warn">
            {canSwear
              ? "Swearing bends the last day toward this and closes some of its opposites. Looking costs nothing."
              : "It is decided. Nothing you swear now moves it; the water is only showing you the rest."}
          </p>
        </article>
      )}
    </section>
  );
}
