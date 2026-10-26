/** The page's turn ledger (spec §6.3 rule 2; Plan decision 4): which state changes arrived inside a turn THIS PAGE sent. */
let sent = 0;
let settled = 0;
let begin = false;
let cued = false;
/** A turn this page sent (`{begin: true}` for a new run's, whose settle plays nothing: Plan decision 12). */
export function turnSent({ begin: isBegin = false } = {}) { sent += 1; begin = isBegin; cued = false; }
/** A story played its own cue for this arrival (a phone sound, a scene door): core's turn.arrive stands down (T14 d7). */
export function noteArrivalCue() { cued = true; }
/** Whether a story cued the arrival since the turn went out; read once, when it settles. */
export function takeArrivalCue() { const was = cued; cued = false; return was; }
/** App's busy-effect, on busy true -> false: false, or the settled entry `{begin}` (truthy), once per sent turn. */
export function turnSettled() {
  if (settled >= sent) return false;
  settled = sent;
  const entry = { begin };
  begin = false;
  return entry;
}
export const settledCount = () => settled;
/** A sent turn is in flight: its results' effects run before App settles it (Plan decision 4). */
export const inSentTurn = () => sent > settled;
export function resetTurns() { sent = 0; settled = 0; begin = false; cued = false; }
