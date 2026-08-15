/**
 * The narrative log.
 *
 * Three behaviours the old client got wrong:
 *
 *  - It auto-scrolled unconditionally, so reading back through history yanked
 *    you to the bottom on every append. Now it sticks only when already there.
 *  - It never echoed the player's own choice, so the log read as a monologue
 *    with no record of what you actually did.
 *  - It kept every entry ever written in the DOM. A long run is thousands of
 *    paragraphs, and each streamed token re-rendered all of them.
 *
 * Announcement is per completed SENTENCE, from one dedicated live region.
 * Putting aria-live on the entries themselves meant a screen reader re-read
 * the growing paragraph on every chunk, which is unusable at streaming speed.
 *
 * THE SECOND COPY OF EVERY PARAGRAPH
 * ----------------------------------
 * That live region used to be a permanent duplicate of the turn's prose, INSIDE
 * the log. `role="log"` carries an implicit `aria-live="polite"`, so the
 * container announced each appended entry on its own -- and re-announced the
 * streaming paragraph on every frame, which is the exact thing the dedicated
 * region exists to prevent -- and then the region said the same words again.
 * The announcement also never cleared, so the finished paragraph sat in the log
 * a second time: a screen reader browsing back met it twice, and so did anything
 * reading the DOM. Measured live on the flagship, two consecutive turns: one
 * `.entry--narration` and one `.visually-hidden` holding the same 602
 * characters.
 *
 * So the container's liveness is off (see ReasoningPanel for the same move on
 * the same reason), the region is a sibling of the log rather than a child, and
 * it clears itself once it has been spoken.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";

const STICK_THRESHOLD = 48;

// How long an announcement stays in the DOM before it is cleared. Assistive
// technology captures the text when the mutation happens, so this only has to
// outlast the mutation -- and what it buys is that the paragraph is not left
// lying in the document as a second, readable copy of the narration.
const ANNOUNCE_LINGER_MS = 1500;

// Beyond this many entries the DOM node count, not the model, is what makes
// the stream feel slow. Older entries stay in state and are one click away.
const WINDOW = 200;

// Sentence end followed by whitespace, or the end of the text.
const SENTENCE_END = /[.!?…]["')\]]?(\s|$)/g;

/**
 * The prefix of `text` that consists of finished sentences.
 *
 * A half-written sentence must not be announced: the reader would hear the
 * first clause, then hear the whole sentence again a moment later.
 */
function completedPrefix(text) {
  SENTENCE_END.lastIndex = 0;
  let end = 0;
  let match;
  while ((match = SENTENCE_END.exec(text)) !== null) {
    end = match.index + match[0].length;
  }
  return text.slice(0, end);
}

/** Length of the longest shared prefix of two strings. */
function commonPrefix(a, b) {
  const limit = Math.min(a.length, b.length);
  let i = 0;
  while (i < limit && a[i] === b[i]) i += 1;
  return i;
}

function useSentenceAnnouncer(entries) {
  const [announcement, setAnnouncement] = useState("");
  const cursor = useRef({ id: null, said: "" });
  const linger = useRef(null);

  const last = entries.length ? entries[entries.length - 1] : null;
  const text = last && last.kind === "narration" ? last.text : "";

  // A pending clear must not fire into an unmounted tree.
  useEffect(() => () => clearTimeout(linger.current), []);

  useEffect(() => {
    if (!last || last.kind !== "narration") return;
    if (cursor.current.id !== last.id) cursor.current = { id: last.id, said: "" };

    // While streaming, only whole sentences are safe to speak. Once the entry
    // is closed the remainder is final, however it is punctuated.
    const ready = last.streaming ? completedPrefix(text) : text;

    // The announced prefix is tracked as TEXT, not as a length. `turn_update`
    // replaces the streamed text with the server's authoritative narration --
    // on a retried or trimmed turn that is a different string, and a numeric
    // cursor would either re-read the paragraph from the top or, when the
    // corrected text is shorter, announce nothing at all and leave the reader
    // believing the severed draft was the ending.
    const shared = commonPrefix(cursor.current.said, ready);
    if (shared === ready.length && ready.length <= cursor.current.said.length) return;

    const fresh = ready.slice(shared).trim();
    cursor.current.said = ready;
    if (!fresh) return;
    setAnnouncement(fresh);
    // Spoken, then withdrawn. Leaving it is what put a whole second copy of the
    // narration in the document between one turn and the next.
    clearTimeout(linger.current);
    linger.current = setTimeout(() => setAnnouncement(""), ANNOUNCE_LINGER_MS);
  }, [last, text]);

  return announcement;
}

export default function NarrativeLog({ entries, busy = false }) {
  const scroller = useRef(null);
  const stick = useRef(true);
  const [limit, setLimit] = useState(WINDOW);
  const announcement = useSentenceAnnouncer(entries);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const onScroll = () => {
      stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  });

  const hidden = Math.max(0, entries.length - limit);
  const visible = useMemo(
    () => (hidden > 0 ? entries.slice(hidden) : entries),
    [entries, hidden]
  );

  return (
    <>
    {/* `aria-live="off"` on a `role="log"`, deliberately. The role's implicit
        politeness made this container a live region of its own, so every
        appended entry was announced here AND again by the region below -- and
        a streaming paragraph was re-announced on every frame it grew, which is
        the unusable behaviour the dedicated region was added to replace. */}
    <div className="log" ref={scroller} role="log" aria-live="off" aria-label="Narrative">
      {hidden > 0 && (
        <button
          type="button"
          className="log__more"
          onClick={() => setLimit((current) => current + WINDOW)}
        >
          Read the {hidden} earlier {hidden === 1 ? "moment" : "moments"}
        </button>
      )}

      {visible.map((entry) => (
        <Entry key={entry.id} entry={entry} />
      ))}

      {/* Waiting for the FIRST paragraph is a different wait from waiting for
          the next one. On this hardware the opening of a run can be two
          minutes of nothing, and "the page is blank" is the wrong sentence for
          it -- it says the page is empty when the page is being written. Ruled
          lines rather than a spinner: it is the shape of what is coming, and
          it is `aria-hidden` because a screen reader gains nothing from three
          rectangles and the live indicator below the log already speaks. */}
      {entries.length === 0 && busy && (
        <div className="log__skeleton" aria-hidden="true">
          <span className="log__rule" />
          <span className="log__rule" />
          <span className="log__rule log__rule--short" />
        </div>
      )}

      {entries.length === 0 && !busy && (
        <p className="log__empty">The page is blank. Something is about to be written on it.</p>
      )}

    </div>

    {/* A SIBLING of the log, not a child. While it holds text it is a copy of
        what the last entry says, and inside the log that copy is part of the
        transcript -- reachable in browse mode, and present to anything reading
        the log's DOM. Out here it is what it is: a courier, empty between
        turns. */}
    <p className="visually-hidden" aria-live="polite" aria-atomic="true">
      {announcement}
    </p>
    </>
  );
}

// Memoized: the log array is rebuilt on every streamed frame, so without this
// all 200 windowed entries re-render for a change confined to the last one.
const Entry = React.memo(function Entry({ entry }) {
  if (entry.kind === "player") {
    return (
      <p className="entry entry--player">
        <span className="entry__label">You chose</span> {entry.text}
      </p>
    );
  }
  if (entry.kind === "dice") {
    return <p className="entry entry--dice">{entry.text}</p>;
  }
  if (entry.kind === "system") {
    return <p className="entry entry--system">{entry.text}</p>;
  }
  // A quest starting, advancing, completing or failing. The server has always
  // sent these and the client never read them, so finishing a quest -- and
  // collecting whatever it paid -- happened in silence.
  if (entry.kind === "quest") {
    return (
      <p className="entry entry--quest">
        <span className="entry__label">Quest</span> {entry.text}
      </p>
    );
  }
  return (
    <p className={`entry entry--narration ${entry.streaming ? "is-streaming" : ""}`}>
      {entry.text}
    </p>
  );
});
