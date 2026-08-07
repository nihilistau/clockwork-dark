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
 */
import React, { useEffect, useMemo, useRef, useState } from "react";

const STICK_THRESHOLD = 48;

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

function useSentenceAnnouncer(entries) {
  const [announcement, setAnnouncement] = useState("");
  const cursor = useRef({ id: null, at: 0 });

  const last = entries.length ? entries[entries.length - 1] : null;
  const text = last && last.kind === "narration" ? last.text : "";

  useEffect(() => {
    if (!last || last.kind !== "narration") return;
    if (cursor.current.id !== last.id) cursor.current = { id: last.id, at: 0 };

    // While streaming, only whole sentences are safe to speak. Once the entry
    // is closed the remainder is final, however it is punctuated.
    const ready = last.streaming ? completedPrefix(text) : text;
    if (ready.length <= cursor.current.at) return;

    const fresh = ready.slice(cursor.current.at).trim();
    cursor.current.at = ready.length;
    if (fresh) setAnnouncement(fresh);
  }, [last, text]);

  return announcement;
}

export default function NarrativeLog({ entries }) {
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
    <div className="log" ref={scroller} role="log" aria-label="Narrative">
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

      {entries.length === 0 && (
        <p className="log__empty">The page is blank. Something is about to be written on it.</p>
      )}

      <p className="visually-hidden" aria-live="polite" aria-atomic="true">
        {announcement}
      </p>
    </div>
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
  return (
    <p className={`entry entry--narration ${entry.streaming ? "is-streaming" : ""}`}>
      {entry.text}
    </p>
  );
});
