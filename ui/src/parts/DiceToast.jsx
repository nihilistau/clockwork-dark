/**
 * Dice toast.
 *
 * The server has emitted `dice_result` since PR10 and nothing ever listened.
 * Rolls happened, mattered, and were invisible.
 *
 * The line shows the full modifier breakdown when the engine supplies one, so
 * a failure reads as a consequence of exhaustion or a wound rather than as
 * arbitrary bad luck.
 */
import React, { useEffect, useState } from "react";

const DWELL_MS = 2600;

export default function DiceToast({ dice, showBreakdown = true }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!dice) return undefined;
    setVisible(true);
    const timer = setTimeout(() => setVisible(false), DWELL_MS);
    return () => clearTimeout(timer);
  }, [dice]);

  if (!dice || !visible) return null;

  const roll = Array.isArray(dice.rolls) ? dice.rolls[0] : dice.roll;
  const modifier = dice.modifier ?? 0;
  const sign = modifier < 0 ? "−" : "+";
  const outcome =
    dice.degree ||
    (typeof dice.success === "boolean" ? (dice.success ? "Success" : "Failure") : "");

  return (
    <div className={`dice ${dice.critical ? "is-crit" : ""} ${dice.fumble ? "is-fumble" : ""}`}
         role="status" aria-live="polite">
      <span className="dice__roll">
        d{dice.sides || 20}: {roll} {sign} {Math.abs(modifier)} = <b>{dice.total}</b>
      </span>
      {typeof dice.dc !== "undefined" && <span className="dice__dc">vs DC {dice.dc}</span>}
      {outcome && <span className="dice__outcome">{outcome}</span>}

      {showBreakdown && Array.isArray(dice.modifiers) && dice.modifiers.length > 0 && (
        <span className="dice__breakdown">
          {dice.modifiers.map(([label], i) => (
            <span key={i} className="dice__mod">
              {label}
            </span>
          ))}
        </span>
      )}
    </div>
  );
}
