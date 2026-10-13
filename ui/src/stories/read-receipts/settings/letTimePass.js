/**
 * "Let time pass while I watch" (spec §15.1): a LOCAL-mode preference of
 * the client's, off by default and kept in this browser (localStorage,
 * every read and write wrapped: a private window or blocked storage just
 * means off). When on, after 30 real seconds with no touch or key anywhere
 * on the phone (its whole frame, the side sheet and status bar included) on
 * a thread whose person is typing or has a reply on its way ("…"), the
 * phone sends `wait {until: 15m}` -- a player action like any other, so the
 * engine moves the clock. Hosted mode never offers it: the payload's
 * `auto_wait` is false there (and its preference is not kept server-side:
 * spec §22, NOT WIRED).
 *
 * "While I WATCH" (T29 review I1), so it pauses:
 * - while the page is hidden (another tab, a minimised window), re-arming
 *   when it is shown again;
 * - after `MAX_IN_A_ROW` waits (one in-game hour) with no touch or key
 *   between them -- the next input starts the count again;
 * - while core's menu or a dialog of its own is up (`blocked`), and while a
 *   confirm or dialog is open inside the phone (`[role=alertdialog]`,
 *   `[role=dialog]`).
 */
import { useCallback, useEffect, useRef, useState } from "react";

export const LET_TIME_PASS_KEY = "read-receipts.let-time-pass";
/** How long the player must leave the phone untouched before time passes (spec §15.1). */
export const IDLE_MS = 30000;
/** At most this many waits in a row with no input between them: 4 x 15 minutes, one in-game hour. */
export const MAX_IN_A_ROW = 4;
/** The wait it sends. */
export const WAIT = { action: "wait", target: "", args: { until: "15m" }, text: "" };
/** What counts as the player being there. */
const INPUTS = ["pointerdown", "keydown", "input", "wheel"];
/** An open confirm or dialog inside the phone. */
const DIALOG = '[role="alertdialog"], [role="dialog"]';

export function readLetTimePass() {
  try {
    return typeof window !== "undefined" && window.localStorage.getItem(LET_TIME_PASS_KEY) === "on";
  } catch {
    return false;
  }
}

export function writeLetTimePass(on) {
  try {
    window.localStorage.setItem(LET_TIME_PASS_KEY, on ? "on" : "off");
  } catch {
    // Storage refused: the preference lasts this page only.
  }
}

/** The preference, read once and written through. */
export function useLetTimePassPref() {
  const [on, setOn] = useState(readLetTimePass);
  const set = useCallback((value) => {
    writeLetTimePass(Boolean(value));
    setOn(Boolean(value));
  }, []);
  return [on, set];
}

/** Whether a thread is worth watching: they are typing, or a reply of theirs is on its way. */
export function watching(row, open) {
  if (!row) return false;
  if (row.typing) return true;
  if (row.last && row.last.pending) return true;
  const messages = open && open.thread_id === row.thread_id ? open.messages || [] : [];
  return messages.some((m) => m.pending && m.from !== "player");
}

function pageHidden() {
  return typeof document !== "undefined" && document.hidden === true;
}

/** Whether the page is shown, following `visibilitychange`. */
function useShown() {
  const [shown, setShown] = useState(() => !pageHidden());
  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const on = () => setShown(!pageHidden());
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);
  return shown;
}

/**
 * Arms the idle timer while `enabled`, the page is shown and nothing is in
 * flight; any input inside the phone's frame (the `.rr` element around
 * `root`) starts it again and resets the run of waits. `again` (the answer
 * counter) re-arms it once a wait has been answered and the thread is still
 * live. When the timer fires with a confirm open, it waits another 30 s.
 */
export function useIdleWait({ enabled, pending, act, root, again }) {
  const actRef = useRef(act);
  actRef.current = act;
  const inARow = useRef(0);
  const shown = useShown();
  const live = enabled && shown;
  // Coming back to the page counts as being there; the thread going quiet and live again does not.
  useEffect(() => {
    if (shown) inARow.current = 0;
  }, [shown]);
  useEffect(() => {
    if (!live || pending) return undefined;
    const el = root && root.current ? root.current.closest?.(".rr") || root.current : null;
    let timer = null;
    const arm = () => {
      if (timer) clearTimeout(timer);
      timer = null;
      if (inARow.current >= MAX_IN_A_ROW) return;
      timer = setTimeout(() => {
        timer = null;
        if (pageHidden()) return;
        if (el && el.querySelector(DIALOG)) {
          arm();
          return;
        }
        inARow.current += 1;
        actRef.current(WAIT);
      }, IDLE_MS);
    };
    const onInput = () => {
      inARow.current = 0;
      arm();
    };
    arm();
    if (el) for (const name of INPUTS) el.addEventListener(name, onInput, true);
    return () => {
      if (timer) clearTimeout(timer);
      if (el) for (const name of INPUTS) el.removeEventListener(name, onInput, true);
    };
  }, [live, pending, root, again]);
}
