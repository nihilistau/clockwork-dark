import { useEffect, useRef } from "react";

import { ensure, installCatalog, limits, markSeen, noteSkip, play, playCount, resetEngine, setLevels, soundLog } from "./engine.js";
import { inSentTurn, resetTurns, settledCount, turnSent, turnSettled } from "./turns.js";

export { installCatalog, markSeen, setLevels, soundLog, turnSent, turnSettled };
export { inSentTurn } from "./turns.js";
export { limits, playCount, oggSupported } from "./engine.js";
export { loadCatalog } from "./catalog.js";
export { ENGINE_EVENTS } from "./events.js";

/** Play `event` now (or after `delayMs`); `key` de-duplicates (spec §6.3 rule 1). Never throws in play. */
export function playSound(event, opts = {}) {
  return play(event, opts);
}

/**
 * Silent on mount and on hydration; plays a NEW value (passing `when`) while a sent turn is in flight (rule 2,
 * Plan decision 4). Runs on EVERY render, so its record is never stale; React runs this child effect before
 * App's `turnSettled()` in the turn's own commit.
 */
export function useSoundOnChange(value, event, { when = (prev, next) => prev !== next } = {}) {
  const seen = useRef(null);
  useEffect(() => {
    const was = seen.current;
    const now = settledCount();
    if (was && was.value !== value && when(was.value, value)) {
      if (inSentTurn()) play(event);
      else noteSkip(event, "not_my_turn");
    }
    seen.current = { value, settled: now };
  });
}

/** A roll's cast and, `roll_degree_delay_ms` later, its degree; keyed by its `at`, only inside a sent turn
 * (Plan decision 10). Core's RollCard and the flagship's DiceToast call it. */
export function useRollSounds(dice) {
  const at = dice ? dice.at : null;
  useEffect(() => {
    if (!dice || !inSentTurn()) return;
    play("roll.cast", { key: `roll:${dice.at}` });
    if (dice.degree) play(`roll.${dice.degree}`, { key: `degree:${dice.at}`, delayMs: limits().roll_degree_delay_ms ?? 450 });
  }, [at]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** Keep the buses on the preferences. */
export function useSoundLevels(prefs) {
  useEffect(() => setLevels(prefs), [prefs]);
}

/**
 * One capturing click listener (rule 3): `ui.press` / `ui.toggle` unless the control names its own event. The
 * press is DEFERRED to a microtask and skipped when any sound played during the click's dispatch (a Modal's
 * `ui.open`, a handler's own event): one action, one sound (Plan decision 16).
 */
export function installClickSounds(root = typeof document !== "undefined" ? document : null) {
  if (!root) return () => {};
  ensure();
  const onClick = (e) => {
    const el = e.target && e.target.closest ? e.target.closest("button, [role=button], input[type=checkbox]") : null;
    if (!el || el.disabled || el.getAttribute("aria-disabled") === "true") return;
    const named = el.closest("[data-sound]")?.getAttribute("data-sound");
    if (named === "none") return;
    const event = named || (el.type === "checkbox" ? "ui.toggle" : "ui.press");
    const before = playCount();
    queueMicrotask(() => { if (playCount() === before) play(event); });
  };
  root.addEventListener("click", onClick, true);
  return () => root.removeEventListener("click", onClick, true);
}

/** Tests only: a fresh engine and ledger. */
export function resetSound(opts = {}) {
  resetEngine(opts);
  resetTurns();
}
// No call here: importing this module has no side effect (pre-flight F5).
