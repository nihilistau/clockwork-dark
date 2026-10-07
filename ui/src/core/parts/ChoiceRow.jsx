/**
 * Choice chips with keyboard 1-9 (`useDigitKeys`, shared with the encounter
 * panel when its approaches are the only moves).
 *
 * The number badges were specified in the design system, the component docs and
 * the brief, and existed in none of them. Binding the keys is what makes the
 * badges honest.
 */
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";

import { useDigitKeys } from "../hooks/useDigitKeys.js";

const HINT_LABEL = {
  safe: "quiet",
  risky: "risky",
  costly: "costly",
  unknown: "unknown",
};

export default function ChoiceRow({
  choices,
  busy,
  onChoose,
  settled = false,
  // True while an overlay owns the screen -- map, clues, journal, gallery, or
  // the pause menu. `Play` stays MOUNTED underneath every one of them, so this
  // window listener went on firing behind them: pressing "1" over the pause
  // menu submitted a turn the player could not see. App already computes this
  // for its own listener; it is threaded down rather than recomputed so there
  // is only ever one answer to "is the screen blocked".
  blocked = false,
  // Bumped by the store when the player must choose again (a move that is
  // no longer on offer): the row takes focus, unless the player has put it
  // somewhere else.
  focusSignal = 0,
}) {
  useDigitKeys(choices, onChoose, !busy && !blocked);

  // THE "MORE BELOW" CUE (v0.21.0 T7; T6 review issue A). The list is capped
  // and scrolls among itself, and on a landscape phone it is held to one
  // chip's floor: whole rows hid with nothing on screen to say so, and a
  // phone's overlay scrollbar is invisible at rest. `data-more` is set while
  // rows lie below the list's fold, and the stylesheet fades its bottom edge.
  const listRef = useRef(null);
  const [more, setMore] = useState(false);
  useEffect(() => {
    const list = listRef.current;
    if (!list) {
      setMore(false);
      return undefined;
    }
    const measure = () => setMore(list.scrollTop + list.clientHeight < list.scrollHeight - 1);
    measure();
    list.addEventListener("scroll", measure, { passive: true });
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    observer?.observe(list);
    return () => {
      list.removeEventListener("scroll", measure);
      observer?.disconnect();
    };
  }, [choices]);

  // FOCUS THROUGH A TURN (spec §8.2, F9; T13 fix round 1). While the turn
  // runs the pressed chip keeps focus (aria-disabled, never `disabled`). When
  // it lands, the turn's new choices replace the chips -- keyed by id, so the
  // focused node goes and focus would fall to <body>. So: note whether focus
  // was in the row when the controls went off, and once they are back on
  // with the new choices, put it on the first chip -- but only if it fell to
  // <body> (a chip still focused in the row keeps it). Focus the player moved (the compose box, a
  // panel, an overlay) is never taken, and nothing moves while the screen is
  // blocked. The turn's prose is still announced: the polite region speaks
  // after the chip's label.
  const hadFocus = useRef(false);
  const inRow = () => Boolean(listRef.current?.contains(document.activeElement));
  useLayoutEffect(() => {
    if (busy && inRow()) hadFocus.current = true;
  }, [busy]);
  useLayoutEffect(() => {
    if (busy || !hadFocus.current) return;
    hadFocus.current = false;
    if (blocked) return;
    // Focus still on a chip in the row -- the new choices kept the old ids,
    // so the pressed chip survived -- stays where it is (T13 re-review nit).
    // Focus the player moved elsewhere is never taken.
    const active = document.activeElement;
    if (active && active !== document.body) return;
    listRef.current?.querySelector(".chip")?.focus();
    // `blocked` is read when the turn lands, not watched.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [choices, busy]);
  useEffect(() => {
    if (!focusSignal || blocked) return;
    const active = document.activeElement;
    if (active && active !== document.body && !inRow()) return;
    listRef.current?.querySelector(".chip")?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusSignal]);

  // A settled turn that offered nothing.
  //
  // This used to render `null`, so the band above the compose box simply went
  // away and the screen read as broken rather than as open. It is a state the
  // engine reaches honestly -- a scene that ends on a question, a narrator that
  // offered none, an answer that came back without its envelope -- and the
  // compose box below is still the right move. So say that, rather than
  // vanish. Silent while the turn is still running: nothing is missing yet.
  if (!choices.length) {
    if (!settled) return null;
    return (
      <p className="choices__empty" role="status">
        Nothing is offered. The next move is yours to name.
      </p>
    );
  }

  return (
    <div className="choices" role="group" aria-label="Choices" ref={listRef} data-more={more ? "true" : undefined}>
      {choices.map((choice, index) => (
        <button
          key={choice.id}
          type="button"
          className="chip"
          // aria-disabled, never `disabled` (spec §8.2, F9): a disabled button
          // throws its focus to <body> the moment the turn starts, so a
          // keyboard player lost their place on every press. The handler
          // returns early instead, and focus is kept through the turn.
          aria-disabled={busy ? "true" : undefined}
          data-hint={choice.hint || "unknown"}
          onClick={() => {
            if (busy) return;
            // Safari does not focus a clicked button; a keyboard press does
            // land here with the chip focused, so note it before the turn.
            if (inRow()) hadFocus.current = true;
            onChoose(choice);
          }}
        >
          <span className="chip__key" aria-hidden="true">
            {index + 1}
          </span>
          <span className="chip__text">{choice.text}</span>
          {/* What the ENGINE will do if this is picked, when the option
              declared an intent. The narrator chooses which options carry one
              and is told that a choice which is only talk carries none, but no
              grammar can read a sentence and tell conversation from movement:
              a measured turn put `travel -> afterdeck` on "Ask what is required
              of you today", and the player was moved while the prose had them
              sitting still. It cannot be made unsamplable, so it is made
              visible. The server writes this label from the same catalogue the
              intent enum was built from (engine/game/intents.py). */}
          {choice.intent_label && (
            <span className="chip__intent" title="What this will do">
              {choice.intent_label}
            </span>
          )}
          {choice.hint && choice.hint !== "unknown" && (
            <span className="chip__hint">{HINT_LABEL[choice.hint]}</span>
          )}
        </button>
      ))}
    </div>
  );
}
