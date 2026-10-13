/**
 * One phone action at a time, and what to do when it never went (spec §16.2,
 * §18.2).
 *
 * THE BUSY RE-SEND IS CORE'S. `core/socket.js`'s sender already re-sends a
 * `phone_action` answered busy once, after 150 ms, and swallows that first
 * busy answer; only a SECOND busy reaches the store, as `turn_error {busy}`,
 * which the slice counts (`busySeq`). Re-sending again here would make it
 * three sends, against §18.2's "re-sent once". So this hook never re-sends on
 * its own: a busy that reaches it, an action core reports as dropped
 * (`PHONE_DROPPED`, a disconnect), or an `onAct` that refused outright (the
 * link not live) all become `notSent` -- the intent kept whole, so a compose
 * field can show its text again with "Not sent — tap to retry", and `retry()`
 * sends it as the player wrote it.
 *
 * `pending` is the action awaiting its answer (a `turn_update`, or a
 * `turn_error` that was not busy): the deck reads it so a second swipe never
 * goes at a card the server has already moved past.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export function usePhoneAct(onAct, story) {
  const [ui, setUi] = useState({ pending: null, notSent: null });
  const live = useRef(ui);
  live.current = ui;
  const seen = useRef({ busy: story.busySeq, turn: story.turnSeq, drop: story.dropSeq });

  // Answered: the action is done with, whatever the answer said.
  useEffect(() => {
    if (story.turnSeq === seen.current.turn) return;
    seen.current.turn = story.turnSeq;
    if (live.current.pending) setUi((u) => ({ ...u, pending: null }));
  }, [story.turnSeq]);

  // The second busy (core re-sent the first): not sent, kept for a retry.
  useEffect(() => {
    if (story.busySeq === seen.current.busy) return;
    seen.current.busy = story.busySeq;
    const pending = live.current.pending;
    if (pending) setUi({ pending: null, notSent: pending });
  }, [story.busySeq]);

  // Core reports what never reached the server: ours, or the last one with words in it.
  useEffect(() => {
    if (story.dropSeq === seen.current.drop) return;
    seen.current.drop = story.dropSeq;
    const dropped = Array.isArray(story.dropped) ? story.dropped : [];
    const pending = live.current.pending;
    const ours = pending ? dropped.find((intent) => intent === pending || sameIntent(intent, pending)) : null;
    const worded = [...dropped].reverse().find((intent) => intent && (intent.text || intent.args?.comment));
    const kept = ours || worded || null;
    if (kept) setUi({ pending: ours ? null : live.current.pending, notSent: kept });
  }, [story.dropSeq]);

  const act = useCallback(
    (intent) => {
      const full = { action: intent.action, target: intent.target || "", args: intent.args || {}, text: intent.text || "" };
      const took = onAct(full);
      if (took === false) {
        setUi({ pending: null, notSent: full });
        return false;
      }
      setUi({ pending: full, notSent: null });
      return true;
    },
    [onAct]
  );

  const clearNotSent = useCallback(() => setUi((u) => ({ ...u, notSent: null })), []);
  const retry = useCallback(() => {
    const intent = live.current.notSent;
    if (intent) act(intent);
  }, [act]);

  return { act, pending: ui.pending, notSent: ui.notSent, clearNotSent, retry };
}

function sameIntent(a, b) {
  return (
    a && b && a.action === b.action && (a.target || "") === (b.target || "") && (a.text || "") === (b.text || "") &&
    JSON.stringify(a.args || {}) === JSON.stringify(b.args || {})
  );
}
