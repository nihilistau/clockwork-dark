// ui/tests/fixtures/phone-harness.jsx -- READ RECEIPTS' thread under test (v0.22.0 T28).
//
// `Harness({onAct, busySeq, busy, phone})`: PlayScreen on a fixture core state (`world.phone` from
// ./phone.js, the slice `{pushes: [], busySeq, turnSeq: 0}`), opened onto the thread the fixture's
// `open_thread` names by tapping its notification on the lock screen, as a player would. Re-render it
// on the same root with a new `busySeq` to play the busy answer that reaches the store.
//
// `threadProps(options)`: props for `Thread` alone, on the fixture's open thread (Cole), moved to
// `app` when asked:
//   app       the thread's app ("matchstick" by default; "texts", "natter", "front_porch")
//   typing    the thread row's `typing`
//   unvoiced  how many unvoiced messages from them to add ("…")
//   messages  extra open-thread messages, appended
//   phone     top-level keys of the phone block, replaced (requests, games, calendar, ...)
//   row       keys spread onto the thread row
//   hidden    keys planted on every row drawn (./phone.js `plantHidden`), after the above
//   act, fetchPage, notSent, pending   passed through (act defaults to vi.fn())
import React, { useEffect, useRef } from "react";
import { vi } from "vitest";

import PlayScreen from "../../src/stories/read-receipts/PlayScreen.jsx";
import { initialState } from "../../src/stories/read-receipts/state.js";
import { phoneFixture, plantHidden } from "./phone.js";

export const PID = "p0347";

export function coreState(phone, story = initialState, busy = false) {
  return { world: { phone }, story, busy, sessionId: "s1", error: "" };
}

/**
 * Core's state for the two layers (v0.23.0 T21, pre-flight F8): the phone block under `world.phone`, the
 * narrator's `choices`, a live link and an empty log. `coreState` keeps its positional signature.
 */
export function worldState({ phone = phoneFixture(), choices = [], log = [] } = {}) {
  return { ...coreState(phone), link: "live", choices, log };
}

export function Harness({ onAct, busySeq = 0, busy = false, phone = null }) {
  const block = useRef(phone || phoneFixture()).current;
  const host = useRef(null);
  useEffect(() => {
    const id = block.open_thread.thread_id;
    const notif = [...block.notifications].reverse().find((n) => n.thread_id === id);
    host.current.querySelector(`[data-testid="notif-${notif.id}"]`).click();
  }, []);
  const story = { ...initialState, pushes: [], busySeq, turnSeq: 0 };
  return (
    <div ref={host}>
      <PlayScreen state={coreState(block, story, busy)} sessionId="s1" busy={busy} onAct={onAct} onOpenMenu={() => {}} onOpenSaves={() => {}} />
    </div>
  );
}

export function threadProps({
  app = "matchstick",
  typing = false,
  unvoiced = 0,
  messages = [],
  phone = {},
  row = {},
  act = vi.fn(() => true),
  fetchPage = vi.fn(async () => ({ messages: [], more: false })),
  notSent = null,
  pending = null,
  hidden = null,
} = {}) {
  const base = phoneFixture();
  const threadId = `${app}:${PID}`;
  const cole = base.threads.find((t) => t.pid === PID);
  const threadRow = { ...cole, ...row, thread_id: threadId, app, typing };
  const extra = [];
  for (let i = 0; i < unvoiced; i += 1) {
    extra.push({ id: `m${90 + i}`, from: PID, kind: "text", at: 41 + i / 10, bubbles: [], pending: true, media_id: null, transcript: null });
  }
  const block = {
    ...base,
    threads: [threadRow, ...base.threads.filter((t) => t.pid !== PID)],
    open_thread: { ...base.open_thread, thread_id: threadId, app, typing, messages: [...base.open_thread.messages, ...messages, ...extra] },
    ...phone,
  };
  if (hidden) plantHidden(block, hidden);
  return {
    phone: block,
    threadId,
    act,
    pending,
    notSent,
    onRetry: act,
    onClearNotSent: vi.fn(),
    onBack: vi.fn(),
    sessionId: "s1",
    fetchPage,
  };
}
