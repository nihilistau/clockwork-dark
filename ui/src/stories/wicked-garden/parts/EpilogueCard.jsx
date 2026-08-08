/**
 * EpilogueCard — two halves of one ending.
 *
 * The shape is fixed by EPILOGUE-CARDS.md and it is not negotiable, because the
 * two cards are the point: what happened in the waking world, and what happened
 * in the Garden. An ending told as one paragraph loses the only thing this
 * story is about.
 *
 *   ENDING UNLOCKED · {ID} · {TITLE}
 *   ──────────────────────────────────
 *   [CARD M — THE WAKING WORLD]
 *   ──────────────────────────────────
 *   [CARD G — THE GARDEN]
 *   ──────────────────────────────────
 *   Sophia's echo (optional)
 *   Time line
 *
 * The time line is a template with the arithmetic already in it: "You spent
 * {garden_days} days in the Wicked Garden. Outside, roughly {garden_days x 10}
 * days passed." The multiplier is the story's exchange rate and the card is the
 * only place a player ever sees the bill, so it is computed here from the one
 * number rather than being passed in twice and allowed to disagree.
 */
import React from "react";

const MORTAL_PER_GARDEN_DAY = 10;

export default function EpilogueCard({
  id,
  title,
  mortal,
  garden,
  echo,
  gardenDays = 0,
  hollow = false,
}) {
  const mortalDays = Math.round(gardenDays * MORTAL_PER_GARDEN_DAY);

  return (
    <article className="epilogue" aria-label={`${id} ${title}`}>
      <header className="epilogue__head">
        <span className="epilogue__kicker">Ending unlocked</span>
        <h2 className="epilogue__title">
          <span className="epilogue__id">{id}</span> {title}
        </h2>
      </header>

      <section className="epilogue__card">
        <h3 className="epilogue__card-head">The waking world</h3>
        <p className="epilogue__prose">{mortal}</p>
        {/* Past 100 mortal days the design injects a hollow clause into any
            mortal card. It is a fixed consequence of the clock, so it is drawn
            as part of the card rather than left to the prose to remember. */}
        {hollow && (
          <p className="epilogue__hollow">
            Everyone you meant to come back to has had years of it. You are the
            only one who thinks you were gone a week.
          </p>
        )}
      </section>

      <section className="epilogue__card">
        <h3 className="epilogue__card-head">The Garden</h3>
        <p className="epilogue__prose">{garden}</p>
      </section>

      {echo && (
        <p className="epilogue__echo">
          <span className="epilogue__echo-who">Sophia</span>
          {echo}
        </p>
      )}

      <p className="epilogue__time">
        You spent <b>{gardenDays}</b> {gardenDays === 1 ? "day" : "days"} in the
        Wicked Garden. Outside, roughly <b>{mortalDays}</b> days passed.
      </p>
    </article>
  );
}
