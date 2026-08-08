/**
 * The rolled die, and what it cost you.
 *
 * The server has emitted `dice_result` since PR10. Before this pass it drew a
 * single grey toast: no die was ever shown, nothing rolled, a fast sequence of
 * checks overwrote itself so only the last one was ever read, and every kind of
 * outcome -- a natural 20, a scraped pass, a fumble that opens a wound -- was
 * the same rectangle in a different border colour.
 *
 * Three things changed.
 *
 * 1. THE DIE IS THE FACE THAT WAS ROLLED. data/art/manifest.yaml's `dice_faces`
 *    maps all twenty numbers to a painted plate. Five of them (6, 8, 11, 16,
 *    18) did not exist and eight more had no legible numeral on them, so
 *    "show what was rolled" was not previously possible for more than half the
 *    range; scripts/generate_dice_art.py fills the set.
 *
 * 2. IT ROLLS. The die tumbles through a flipbook of other faces, overshoots,
 *    and settles on the one the engine actually returned. That is what makes a
 *    number feel like a result rather than a readout -- and it is honest,
 *    because the settle lands on the real value and nothing else.
 *
 * 3. THEY QUEUE. Rolls stack newest-first and each card runs its own life
 *    (tumble -> settle -> hold -> leave). Three checks in a second read as
 *    three cards, not as one card flickering.
 *
 * KNOWN GAP: store.js keeps a single `dice` object, so two `dice_result`
 * events collapsed into one React batch would lose the first. Socket events
 * arrive on separate ticks in practice; fixing it properly means a queue in the
 * reducer, which lives in a file this pass does not own.
 */
import React, { useEffect, useRef, useState } from "react";

const SIDES = 20;

/**
 * The painted face for a roll.
 *
 * Mirrors `dice_faces` in data/art/manifest.yaml. The server sends no image url
 * with `dice_result` and shipped.py has no `kind == "dice"` branch, so the
 * client rebuilds the path itself -- a second copy of a mapping, which is how
 * this project once shipped a manifest entry pointing at a file that never
 * existed. tests/test_dice_art.py parses this function and the two timings
 * below, holding them against the manifest and the stylesheet.
 */
export function faceSrc(number) {
  return `/static/art/dice/faces/face-${String(number).padStart(2, "0")}.jpg`;
}

// The tumble is deliberately short. It is anticipation, not a cutscene: past
// about two thirds of a second a player who has already read the number is
// waiting for the interface to catch up with them.
//
// Bare `const` then exported below rather than `export const`, because the
// test matches them at the start of a line.
const TUMBLE_MS = 620;
const LEAVE_MS = 520; // matches --dur-roll-leave

const FLIP_MS = 68; // one face per frame of the flipbook
const HOLD_MS = 2600; // matches --dur-toast
const MAX_CARDS = 3; // past three the rail starts covering the picture

/**
 * What kind of thing was rolled for.
 *
 * The engine sends a skill and a free-text `reason`; it does not send "attack"
 * or "save" as a type. Rather than invent a taxonomy the engine cannot
 * confirm, the kind is READ OFF the reason, and anything unrecognised stays a
 * plain check. The kind picks the mark and the kicker; the TONE (below) picks
 * the colour and the motion. Two axes, so "a fumbled attack" and "a fumbled
 * save" look like relatives rather than like unrelated boxes.
 */
const KINDS = [
  [/\b(attack|strike|swing|stab|slash|shoot|lunge)\w*/i, "attack"],
  [/\b(dodge|evade|resist|brace|withstand|endure|save|saving)\w*/i, "save"],
  [/\b(wound|injur|bleed|hurt|damage)\w*/i, "wound"],
  [/\b(sneak|stealth|hide|slip|creep)\w*/i, "stealth"],
  [/\b(persuad|convince|barter|haggle|plead|talk)\w*/i, "parley"],
];

const KIND_MARK = {
  attack: "†",
  save: "◈",
  wound: "✕",
  stealth: "◐",
  parley: "❞",
  check: "◇",
};

function kindOf(dice) {
  const text = `${dice.reason || ""} ${dice.skill || ""}`;
  for (const [pattern, name] of KINDS) if (pattern.test(text)) return name;
  return "check";
}

/**
 * The five tones, in order of how loudly they are allowed to speak.
 *
 * A critical and a fumble are not "a good success" and "a bad failure", they
 * are their own events, and the card has to say so before the word is read.
 */
function toneOf(dice, outcome) {
  if (dice.fumble) return "fumble";
  if (dice.critical) return "critical";
  if (/^crit/i.test(outcome)) return "critical";
  if (/^fumble/i.test(outcome)) return "fumble";
  if (/^success/i.test(outcome)) return "success";
  if (/^(fail|miss)/i.test(outcome)) return "failure";
  if (dice.success === true) return "success";
  if (dice.success === false) return "failure";
  return "neutral";
}

const VERDICT = {
  critical: "Critical",
  success: "Success",
  failure: "Failure",
  fumble: "Fumble",
  neutral: "Rolled",
};

/** True when the player has asked for stillness, by OS or by settings. */
function stillnessWanted() {
  if (typeof window === "undefined") return false;
  if (document.documentElement.dataset.reduceMotion === "true") return true;
  return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
}

/**
 * One roll, with its own life.
 *
 * Owning the timers here rather than in the parent is what lets a burst of
 * checks overlap cleanly: each card tumbles, settles, holds and leaves on its
 * own clock, and the rail just stops rendering the ones that finish.
 */
function RollCard({ dice, onDone, showBreakdown }) {
  const still = useRef(stillnessWanted()).current;
  const natural = Array.isArray(dice.rolls) ? dice.rolls[0] : (dice.natural ?? dice.roll);
  const landed = Number.isFinite(Number(natural)) ? Number(natural) : null;

  // `settled` is what makes the animation truthful: until it flips, the face
  // on screen is a decoy from the flipbook and the number is not readable.
  const [settled, setSettled] = useState(still || landed === null);
  const [decoy, setDecoy] = useState(landed);
  const [leaving, setLeaving] = useState(false);

  // Bug (a settled die started rolling again): `onDone` is a new closure on
  // every render of the rail, and the rail re-renders whenever ANOTHER roll
  // lands. With it in the dependency list the effect below re-ran for every
  // card already on screen -- restarting their flipbooks, so a card that had
  // already shown its answer went back to spinning decoys. Through a ref the
  // effect runs exactly once per card, which is what "the die is thrown once"
  // means.
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    if (still || landed === null) {
      const hold = setTimeout(() => setLeaving(true), HOLD_MS);
      const gone = setTimeout(() => done.current(), HOLD_MS + LEAVE_MS);
      return () => {
        clearTimeout(hold);
        clearTimeout(gone);
      };
    }

    // The flipbook. Never shows the real face early -- landing on the answer
    // half a second before the die stops would give the whole thing away.
    const flip = setInterval(() => {
      setDecoy((previous) => {
        let next = previous;
        while (next === previous || next === landed) {
          next = 1 + Math.floor(Math.random() * SIDES);
        }
        return next;
      });
    }, FLIP_MS);

    const stop = setTimeout(() => {
      clearInterval(flip);
      setSettled(true);
    }, TUMBLE_MS);
    const hold = setTimeout(() => setLeaving(true), TUMBLE_MS + HOLD_MS);
    const gone = setTimeout(() => done.current(), TUMBLE_MS + HOLD_MS + LEAVE_MS);

    return () => {
      clearInterval(flip);
      clearTimeout(stop);
      clearTimeout(hold);
      clearTimeout(gone);
    };
  }, [still, landed]);

  const modifier = dice.modifier ?? dice.modifier_total ?? 0;
  const sign = modifier < 0 ? "−" : "+";
  const outcome = dice.degree || "";
  const tone = toneOf(dice, outcome);
  const kind = kindOf(dice);
  const shown = settled ? landed : decoy;
  const mods = Array.isArray(dice.modifiers) ? dice.modifiers : [];

  return (
    <article
      className={`roll ${leaving ? "is-leaving" : ""} ${settled ? "is-settled" : "is-rolling"}`}
      data-tone={tone}
      data-kind={kind}
    >
      <span className="roll__die" aria-hidden="true">
        {shown !== null && (
          <img className="roll__face" src={faceSrc(shown)} alt="" draggable="false" />
        )}
        {/* Impact: a ring that expands out of the die the instant it lands. */}
        <span className="roll__impact" />
      </span>

      <div className="roll__body">
        <p className="roll__kicker">
          <span className="roll__mark" aria-hidden="true">{KIND_MARK[kind]}</span>
          {dice.skill ? `${dice.skill}` : `d${dice.sides || SIDES}`}
          {dice.difficulty ? ` · ${dice.difficulty}` : ""}
        </p>

        {/* The verdict only appears once the die has stopped: a card that
            says "Fumble" over a still-spinning die has already spoiled it. */}
        <p className="roll__verdict">{settled ? VERDICT[tone] : "…"}</p>

        <p className="roll__sum">
          <b className="roll__natural">{settled && shown !== null ? shown : "—"}</b>
          <span className="roll__op">{sign}</span>
          <span>{Math.abs(modifier)}</span>
          <span className="roll__op">=</span>
          <b className="roll__total">{settled ? dice.total : "—"}</b>
          {typeof dice.dc !== "undefined" && <span className="roll__dc">vs {dice.dc}</span>}
        </p>

        {/* The receipt. A failure reads as a consequence of exhaustion or a
            wound rather than as arbitrary bad luck -- but only once the die
            has landed, and only when there is room for it. */}
        {showBreakdown && settled && mods.length > 0 && (
          <ul className="roll__mods">
            {mods.slice(0, 4).map((mod, i) => {
              const label = Array.isArray(mod) ? mod[0] : mod.label;
              const delta = Array.isArray(mod) ? mod[1] : mod.delta;
              return (
                <li key={i} className="roll__mod" data-sign={delta < 0 ? "down" : "up"}>
                  {label}
                  {typeof delta === "number" && (
                    <b>{delta < 0 ? "−" : "+"}{Math.abs(delta)}</b>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </article>
  );
}

export default function DiceToast({ dice, showBreakdown = true }) {
  const [cards, setCards] = useState([]);
  const seq = useRef(0);

  // Every new `dice` object is a new roll -- store.js stamps `at` on each one,
  // so an identical re-render does not push a duplicate card.
  const lastAt = useRef(null);
  useEffect(() => {
    if (!dice) return;
    const stamp = dice.at ?? null;
    if (stamp !== null && stamp === lastAt.current) return;
    lastAt.current = stamp;
    seq.current += 1;
    const id = seq.current;
    setCards((current) => [{ id, dice }, ...current].slice(0, MAX_CARDS));
  }, [dice]);

  if (cards.length === 0) return null;

  return (
    // `role="log"` rather than `status`: several of these can be live at once
    // and they are a running record, which is what a log is.
    <div className="rolls" role="log" aria-live="polite" aria-label="Dice">
      {cards.map((card) => (
        <RollCard
          key={card.id}
          dice={card.dice}
          showBreakdown={showBreakdown}
          onDone={() => setCards((current) => current.filter((c) => c.id !== card.id))}
        />
      ))}
    </div>
  );
}
