/**
 * The fade card — a scene that passed, said so.
 *
 * WHY THIS IS NOT A WARNING
 * -------------------------
 * The safety layer can resolve a moment at summary resolution instead of at
 * full detail. When it does, the storyteller's narration is replaced and the
 * gate hands back a card: a heading, what happened, and the consequences that
 * were applied ANYWAY (`engine/safety/verdict.py::FadeCard`, attached to the
 * turn as `fade_card`). Nothing in the client drew it, so the entire mechanism
 * reached the browser as a short paragraph and a missing one — indistinguishable
 * from the narrator losing its place mid-scene.
 *
 * So this is typeset as a deliberate authored beat and not as an interruption.
 * No warning triangle, no "content was removed", no palette borrowed from the
 * error status: a fade is a cut in a film, and a cut is a choice. The one thing
 * it must be unambiguous about is that the world moved — an hour passed, a
 * bargain was struck — because a player who reads a fade as "nothing happened"
 * will spend their next turn re-doing something that is already done. That is
 * what the outcomes list is for, and it is why the outcomes are the loudest
 * thing on the card.
 *
 * `aftercare` is the session asking for a beat to follow. It is stated plainly
 * and never as a question with buttons: the boundary sheet at the start of the
 * run is where a player sets this, and a modal asking "are you okay?" in the
 * middle of a scene is the product deciding they are not.
 */
import React from "react";

export default function FadeCard({ card }) {
  if (!card || !card.heading) return null;

  const outcomes = card.outcomes || [];

  return (
    <section className="fade" role="note" aria-label="The scene passes">
      <p className="fade__heading">{card.heading}</p>

      {card.summary && <p className="fade__summary">{card.summary}</p>}

      {outcomes.length > 0 && (
        <>
          {/* Announced as a list rather than as prose: these are the things
              that are now true, and a reader skimming for "what changed"
              should find them as items and not buried in a sentence. */}
          <p className="fade__kicker">What stands after it</p>
          <ul className="fade__outcomes">
            {outcomes.map((line) => (
              <li key={line} className="fade__outcome">
                {line}
              </li>
            ))}
          </ul>
        </>
      )}

      {card.aftercare && (
        <p className="fade__aftercare">
          There is a quiet beat after this one. Take it if you want it.
        </p>
      )}
    </section>
  );
}
