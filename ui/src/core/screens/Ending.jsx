/**
 * The ending screen.
 *
 * Replaces the play screen once a run has locked an ending. That is not a
 * cosmetic swap: Play would still be offering choices and a compose box for a
 * story that is over, and the engine would refuse every one of them.
 *
 * WHAT THIS KNOWS ABOUT ANY STORY: nothing. It renders the blocks named in the
 * payload's own `order`, which comes from the story's epilogue index
 * (`render_order`). A story that wants a different shape declares a different
 * order; a story that wants a different LOOK supplies `story.Ending` and this
 * file never runs for it.
 *
 * ALL TEXT COMES FROM THE SERVER. Nothing here recomputes anything, and that is
 * the whole reason this file is thin. The time line in particular is a rendered
 * sentence, not two numbers to multiply: the Garden's mortal-day debt carries
 * extra shards that a lost labyrinth and a wasted hour added, so a client doing
 * `days * 10` would under-report exactly the runs the sentence exists to
 * report. The same applies to the hollow clause, which the engine has already
 * folded into the mortal card when the debt earned it.
 *
 * THE BLOCK IS `.finale`, NOT `.ending`. The Garden's stylesheet already owns
 * `.ending__title`, `.ending__card` and `.ending__id` for EndingGallery's
 * medallions, so a full-page epilogue under that block would have arrived
 * wearing a gallery tile's rules -- in one story only, which is the kind of
 * thing that gets found by a screenshot rather than by a test.
 */
import React from "react";

/** A block this renderer knows how to draw. Anything else in `order` is skipped. */
function Block({ name, ending }) {
  switch (name) {
    case "title":
      return (
        <header className="finale__head">
          <span className="finale__kicker">Ending unlocked</span>
          <h2 className="finale__title">
            <span className="finale__id">{ending.ending_id}</span> {ending.title}
          </h2>
        </header>
      );

    case "card_m":
      return ending.card_m ? (
        <section className="finale__card">
          <h3 className="finale__card-head">The waking world</h3>
          <Prose text={ending.card_m} />
        </section>
      ) : null;

    case "card_g":
      return ending.card_g ? (
        <section className="finale__card">
          <h3 className="finale__card-head">After</h3>
          <Prose text={ending.card_g} />
        </section>
      ) : null;

    case "echoes":
      // Zero, one or two, and the speaker is named by the payload. An ending
      // with no echo renders nothing rather than an empty quote block.
      return (ending.echoes || []).length ? (
        <div className="finale__echoes">
          {ending.echoes.map((echo, index) => (
            <p className="finale__echo" key={`${echo.speaker}-${index}`}>
              {echo.speaker && <span className="finale__echo-who">{echo.speaker}</span>}
              <Prose text={echo.text} />
            </p>
          ))}
        </div>
      ) : null;

    case "time_line":
      return ending.time_line ? <p className="finale__time">{ending.time_line}</p> : null;

    case "gallery_unlock":
      return ending.gallery_key ? (
        <p className="finale__gallery">
          Added to the gallery: <code>{ending.gallery_key}</code>
        </p>
      ) : null;

    default:
      return null;
  }
}

/** Blank-line-separated paragraphs, which is how the cards are authored. */
function Prose({ text }) {
  return (
    <>
      {String(text || "")
        .split(/\n{2,}/)
        .filter((para) => para.trim())
        .map((para, index) => (
          <span className="finale__para" key={index}>
            {para.trim()}
          </span>
        ))}
    </>
  );
}

export default function Ending({ ending, story = {}, onNewRun, onOpenSaves }) {
  if (!ending) return null;
  const order = ending.order?.length ? ending.order : ["title", "card_m", "card_g", "time_line"];

  return (
    <div className="finale" role="document">
      <article className="finale__sheet" aria-label={`${ending.ending_id} ${ending.title}`}>
        {order.map((name) => (
          <Block key={name} name={name} ending={ending} />
        ))}

        <div className="finale__actions">
          <button type="button" className="btn btn--lg" onClick={onNewRun}>
            {story.beginLabel || "Begin again"}
          </button>
          {onOpenSaves && (
            <button type="button" className="btn btn--ghost" onClick={onOpenSaves}>
              Saved runs
            </button>
          )}
        </div>
      </article>
    </div>
  );
}
