/**
 * OmenSting — one flash, once, on a threshold crossing.
 *
 * "Critical thresholds trigger one-time omen full-art stings." The word doing
 * the work is ONE-TIME: an omen that fires every turn the value stays above the
 * line is not an omen, it is a status bar with a flash on it.
 *
 * So the component owns a fired-set keyed by omen id. Crossing back and forth
 * across a threshold does not re-fire; the story has to mint a new id for a
 * genuinely new beat. The set is per-session on purpose -- a save reloaded into
 * a fresh tab should show the omen for the threshold it is now past only if the
 * story asks, and that is the story's call to make, not this component's.
 *
 * ACCESSIBILITY IS NOT OPTIONAL HERE
 * ----------------------------------
 * The design's own accessibility list says "Photosensitivity: disable pollen
 * storms / flash omens." A full-screen flash is exactly the thing that hurts
 * people, so:
 *
 *   - `prefers-reduced-motion` and the client's own reduce-motion preference
 *     both turn the flash into a plain, still card that fades once;
 *   - `suppressed` removes the visual entirely and leaves the words, because
 *     the omen carries INFORMATION and a player who cannot take the flash still
 *     needs to be told the thing happened.
 *
 * It is announced through a polite live region and dismissed on any key, click,
 * or after `dwell` — never on a timer alone, because a sting nobody saw is a
 * beat the story spent for nothing.
 */
import React, { useEffect, useRef, useState } from "react";

const DWELL_MS = 2600;

export default function OmenSting({ omen, suppressed = false, onDone }) {
  const fired = useRef(new Set());
  const [showing, setShowing] = useState(null);

  useEffect(() => {
    if (!omen?.id) return;
    if (fired.current.has(omen.id)) return;
    fired.current.add(omen.id);
    setShowing(omen);
  }, [omen]);

  useEffect(() => {
    if (!showing) return undefined;
    const done = () => {
      setShowing(null);
      onDone?.(showing.id);
    };
    const timer = setTimeout(done, showing.dwell ?? DWELL_MS);
    window.addEventListener("keydown", done, { once: true });
    window.addEventListener("pointerdown", done, { once: true });
    return () => {
      clearTimeout(timer);
      window.removeEventListener("keydown", done);
      window.removeEventListener("pointerdown", done);
    };
  }, [showing, onDone]);

  if (!showing) return null;

  if (suppressed) {
    return (
      <p className="omen omen--quiet" role="status">
        <span className="omen__kicker">{showing.kicker || "An omen"}</span>
        {showing.line}
      </p>
    );
  }

  return (
    <div className="omen" role="status" aria-live="polite" data-tone={showing.tone || "gold"}>
      <div className="omen__card">
        <span className="omen__kicker">{showing.kicker || "An omen"}</span>
        <p className="omen__line">{showing.line}</p>
      </div>
    </div>
  );
}
