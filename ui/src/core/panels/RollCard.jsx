/**
 * The roll card (v0.21.0, spec §4.6): the receipt for the move just made,
 * said once (role="status", polite), for six seconds or until the next turn
 * (`SUBMIT` clears `state.dice`), once per roll however often it remounts.
 * The modifiers follow the dice-breakdown preference. It sits in the toast
 * region, laid over the main column's stage and log rows, and takes no
 * pointer events. Its slide is skipped under reduced motion (CSS).
 *
 * A toast, not a sectioned panel (spec §2.5's one exception): it has no
 * heading to land on and nothing to disclose. The live region is always in
 * the DOM, empty between rolls, so a new card is announced when it fills.
 * A plugin that draws rolls itself lists `rolls` in `ownsPanels`.
 */
import React, { useEffect, useRef, useState } from "react";

export const ROLL_CARD_MS = 6000;

/**
 * Every roll already shown, by the store's own object (the reducer makes a
 * new one per `dice_result`). A remount -- Play mounting again after another
 * screen, the regions re-resolving -- while `state.dice` still holds the last
 * roll must not show and announce it a second time (T9 review finding 2).
 * A WeakSet, so a roll the store has dropped is forgotten with it.
 */
const SHOWN = new WeakSet();

function signed(delta) {
  const n = Number(delta) || 0;
  return n >= 0 ? `+${n}` : String(n);
}

/**
 * The player's words for a roll's degree (engine/game/checks.py's ids): one
 * table, like `ENGINE_CHOICE_WORDS`, so "crit_failure" never reaches the
 * card (final review finding 5). An unknown degree reads as its id made
 * readable, capitalised.
 */
export const DEGREE_WORDS = {
  crit_success: "Critical success",
  success: "Success",
  partial: "Partial success",
  failure: "Failure",
  crit_failure: "Critical failure",
};

export function degreeWords(degree) {
  const id = String(degree || "");
  if (!id) return "";
  if (DEGREE_WORDS[id]) return DEGREE_WORDS[id];
  const words = id.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export default function RollCard({ state, showDiceBreakdown = true }) {
  const dice = state?.dice || null;
  const [roll, setRoll] = useState(() => (dice && !SHOWN.has(dice) ? dice : null));
  // The roll THIS card took up, so an effect re-run for the same roll (a
  // development double-invoke) keeps it rather than treating it as seen.
  const mine = useRef(null);

  useEffect(() => {
    if (!dice || (SHOWN.has(dice) && mine.current !== dice)) {
      setRoll(null);
      return undefined;
    }
    SHOWN.add(dice);
    mine.current = dice;
    setRoll(dice);
    const timer = setTimeout(() => setRoll(null), ROLL_CARD_MS);
    return () => clearTimeout(timer);
  }, [dice]);

  return (
    <div className="rollcard-live" role="status" aria-live="polite">
      {roll && (
        <div className="rollcard">
          <p className="rollcard__what">
            {roll.skill}
            {roll.difficulty ? ` · ${roll.difficulty}` : ""}
          </p>
          <p className="rollcard__die">d20 {roll.natural}</p>
          {showDiceBreakdown && (roll.modifiers || []).length > 0 && (
            <ul className="rollcard__mods">
              {roll.modifiers.map((modifier, i) => (
                <li key={i}>
                  {modifier.label} {signed(modifier.delta)}
                </li>
              ))}
            </ul>
          )}
          <p className="rollcard__sum">
            = {roll.total} vs {roll.dc}
          </p>
          <p className="rollcard__degree">{degreeWords(roll.degree)}</p>
        </div>
      )}
    </div>
  );
}
