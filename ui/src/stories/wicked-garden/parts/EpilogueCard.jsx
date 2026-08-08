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
 *   echo (optional, zero to two, whoever speaks)
 *   Time line
 *
 * EVERY WORD HERE COMES FROM THE SERVER.
 *
 * This file used to compute two of them itself, and both were wrong in the same
 * direction. It multiplied `gardenDays * 10` for the time line, when the
 * authoritative number is the `time_debt_mortal_days` meter -- that carries the
 * extra shards a lost labyrinth and a wasted hour added, so the card
 * under-reported exactly the runs whose whole point is what they cost. And it
 * hardcoded both the hollow clause's wording and "Sophia" as the speaker of
 * every echo, in a story where the index declares the speaker per ending, two
 * endings have two echoes and one has none.
 *
 * `engine/game/epilogue.py` renders all of it from the story's own index and
 * prose. This draws it.
 */
import React from "react";

/** Blank-line-separated paragraphs, which is how the cards are authored. */
function Prose({ text, className = "epilogue__prose" }) {
  return String(text || "")
    .split(/\n{2,}/)
    .filter((para) => para.trim())
    .map((para, index) => (
      <p className={className} key={index}>
        {para.trim()}
      </p>
    ));
}

export default function EpilogueCard({
  // The server's `Epilogue.to_dict()`, passed whole. Named fields rather than a
  // blob so the component kit can still mount it from a fixture.
  ending_id: id = "",
  title = "",
  card_m: mortal = "",
  card_g: garden = "",
  echoes = [],
  time_line: timeLine = "",
}) {
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
        {/* The hollow clause is already the last paragraph of this card when
            the debt earned it -- the engine folds it in, gated on the
            threshold the index declares, so it cannot be shown for a run that
            did not pay it or forgotten for one that did. */}
        <Prose text={mortal} />
      </section>

      <section className="epilogue__card">
        <h3 className="epilogue__card-head">The Garden</h3>
        <Prose text={garden} />
      </section>

      {echoes.map((echo, index) => (
        <div className="epilogue__echo" key={`${echo.speaker}-${index}`}>
          {echo.speaker && (
            <span className="epilogue__echo-who">{echo.speaker.replace(/_/g, " ")}</span>
          )}
          <Prose text={echo.text} className="epilogue__echo-line" />
        </div>
      ))}

      {timeLine && <p className="epilogue__time">{timeLine}</p>}
    </article>
  );
}
