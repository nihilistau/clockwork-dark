/**
 * The Assistant column.
 *
 * WHAT THIS REPLACES: a 13px label, one bubble on a 22-second self-destruct,
 * and an idle line picked by `IDLE_LINES[(phase||"dormant").length % 3]`. The
 * four phase names are 7, 8, 9 and 9 characters long, so that expression had
 * exactly TWO reachable outputs for the entire game, was identical for
 * `spreading` and `consuming`, and never changed within a phase. Meanwhile the
 * component drew "🐈" while data/art/manifest.yaml had been shipping five
 * painted portraits under `assistant_forms:` since the art pack landed.
 *
 * What is on screen now is all engine truth: the painted face for the form the
 * engine says it is wearing, its trust in you, the two awareness gates as
 * seals rather than numbers (awareness is a hidden stat — DESIGN.md says the
 * player meets it as fiction), the forms it has worn this run, and an idle
 * line drawn from a per-phase corpus that actually moves.
 */
import React, { useEffect, useMemo, useState } from "react";
// The painted frame the scene still and every codex plate already use. Reused
// rather than reinvented so the companion's face is lit by the same light as
// everything else on screen, and so the visual layer has one frame to tune.
import PaintFrame from "@core/parts/PaintFrame.jsx";

// Fallback only. The real face is a painting resolved server-side from
// data/art/manifest.yaml; this is what a missing art pack degrades to.
const FORM_GLYPH = {
  cat: "🐈",
  wanderer: "🜃",
  child: "🜁",
  tinker: "⚙",
  reflection: "◐",
};

const FORM_NOTE = {
  cat: "small, and in the way",
  wanderer: "hooded, and keeping pace",
  child: "too young to be out here",
  tinker: "hands busy, eyes elsewhere",
  reflection: "wearing your face badly",
};

/**
 * Idle atmosphere, per phase.
 *
 * Written per phase because the phase is the game's whole weather system and
 * the old code could not tell two of them apart. Nine lines each: enough that
 * a long sitting does not loop visibly.
 */
const IDLE = {
  dormant: [
    "Something watches from the stillness without moving.",
    "The wind has an opinion it is not sharing.",
    "Somewhere a clock is running slightly wrong.",
    "It is washing a paw it does not have.",
    "Woodsmoke, wet bark, and nothing else worth reporting.",
    "The quiet here is ordinary quiet. Mostly.",
    "It counts something under its breath and loses the place.",
    "A bird stops mid-phrase and thinks better of finishing.",
    "The light is behaving. That is not always true.",
  ],
  stirring: [
    "It has stopped pretending to sleep.",
    "The gear-sound is under the floor of everything now.",
    "It looks at a doorway for a long time and says nothing.",
    "Somewhere, something is being wound.",
    "The wheat is leaning the wrong way again.",
    "It has started counting, and it is counting down.",
    "There is a smell of hot brass where no forge is.",
    "Two of the village dogs will not go past the mill.",
    "It watches your hands more than it watches the road.",
  ],
  spreading: [
    "It flinches at a noise you did not hear.",
    "The shadows are keeping time with something.",
    "It says your name once, quietly, to check it still works.",
    "Frost on the inside of the windows, in the wrong season.",
    "Every clock in Edgewood agrees now. That is the problem.",
    "It has stopped offering advice you did not ask for.",
    "The birds left days ago. Nothing replaced them.",
    "Something turns over in the dark and settles again.",
    "It stands between you and the treeline without comment.",
  ],
  consuming: [
    "It will not look at the horizon any more.",
    "The world is ticking, and the ticking is inside your teeth.",
    "It has run out of ways to make this sound survivable.",
    "There is no hour left that is not this hour.",
    "It holds very still, the way small things do.",
    "The dark has stopped spreading. It has arrived.",
    "It says: whatever you do, do it before the next turn of the wheel.",
    "Brass light where the sun should be.",
    "It is no longer certain which of you it is protecting.",
  ],
};

function trustWord(trust) {
  if (trust >= 75) return "it would follow you in";
  if (trust >= 50) return "it has decided about you";
  if (trust >= 30) return "it is still deciding";
  if (trust >= 15) return "it keeps its distance";
  return "it does not know you";
}

/** A gate the player has crossed, shown as a state rather than a number. */
function Seal({ open, label, closedHint, openHint }) {
  return (
    <div className={`seal ${open ? "is-open" : ""}`}>
      <span className="seal__mark" aria-hidden="true">
        {open ? "◉" : "◌"}
      </span>
      <span className="seal__body">
        <span className="seal__label">{label}</span>
        <span className="seal__hint">{open ? openHint : closedHint}</span>
      </span>
    </div>
  );
}

export default function AssistantColumn({ assistant, presence, formHistory = [], phase, busy }) {
  const [shown, setShown] = useState(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!assistant?.text) return undefined;
    setShown(assistant);
    // A presence, not a chat window: the line fades rather than accumulating
    // into a transcript. Longer than the old 22s because there is now a
    // portrait above it holding the space, so the bubble leaving does not
    // empty the column.
    const timer = setTimeout(() => setShown(null), 45000);
    return () => clearTimeout(timer);
  }, [assistant]);

  const form = presence?.form || shown?.form || "cat";
  const portrait = presence?.portrait || "";
  const trust = Number(presence?.trust ?? 0);
  const turn = presence?.turn ?? 0;

  // Rotates on the turn counter and on how much the companion has to say, so
  // it moves within a phase instead of being frozen for a hundred turns.
  const idle = useMemo(() => {
    const lines = IDLE[phase] || IDLE.dormant;
    const seed = (turn || 0) + formHistory.length + Math.round(trust / 7);
    return lines[Math.abs(seed) % lines.length];
  }, [phase, turn, formHistory.length, trust]);

  return (
    <aside className="assistant companion" aria-label="Companion">
      <p className="assistant__label">The Assistant</p>

      <div className="companion__plate">
        <PaintFrame size="portrait" className="companion__frame" caption={form}>
          {portrait ? (
            <img
              className="paint__img is-loaded"
              src={portrait}
              alt={`The Assistant as ${form}`}
            />
          ) : (
            <span className="companion__glyph" aria-hidden="true">
              {FORM_GLYPH[form] || "◇"}
            </span>
          )}
        </PaintFrame>
        {busy && <span className="companion__listening" aria-hidden="true" />}
      </div>

      <div className="companion__ident">
        <span className="companion__form">{form}</span>
        <span className="companion__note">{FORM_NOTE[form] || "something with an opinion"}</span>
      </div>

      {/* The Codex already prints NPC regard as a number; this is the same
          currency, and the player has earned every point of it. */}
      <div className="meter meter--trust" data-tone="trust">
        <div className="meter__row">
          <span className="meter__label">Trust</span>
          <span className="meter__value">{Math.round(trust)}</span>
        </div>
        <div className="meter__track" role="presentation">
          <div
            className="meter__fill"
            style={{ width: `${Math.max(0, Math.min(100, trust))}%` }}
          />
        </div>
        <p className="meter__gloss">{trustWord(trust)}</p>
      </div>

      {shown ? (
        <div
          className={`bubble bubble--${shown.voice_style || "flat"}`}
          role="status"
          aria-live="polite"
        >
          <span className="bubble__form">
            <span aria-hidden="true">{FORM_GLYPH[form] || "◇"}</span> {form}
          </span>
          <p className="bubble__text">{shown.text}</p>
          {shown.hint_tier > 0 && (
            <span className="bubble__tier">tier {shown.hint_tier} help</span>
          )}
        </div>
      ) : (
        <p className="assistant__idle">{idle}</p>
      )}

      <button
        type="button"
        className="companion__more"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded ? "Less" : "What it knows"}
      </button>

      {expanded && (
        <div className="companion__detail">
          {/* Awareness itself never ships to the browser — to_client_dict
              withholds it on purpose. These are the two gates as states. */}
          <Seal
            open={Boolean(presence?.unveiled)}
            label="Plain speech"
            closedHint="It answers you in weather and omens."
            openHint="It has stopped talking around the thing."
          />
          <Seal
            open={Boolean(presence?.reflection_unlocked)}
            label="The reflection"
            closedHint="A fifth face it has not earned the right to wear."
            openHint="It can wear your face now. It has, once."
          />

          {formHistory.length > 0 && (
            <>
              <p className="companion__subhead">Faces worn</p>
              <ul className="formtrack">
                {formHistory.map((entry, i) => (
                  <li
                    key={`${entry.form}-${entry.turn}-${i}`}
                    className={`formtrack__item ${i === formHistory.length - 1 ? "is-current" : ""}`}
                  >
                    <PaintFrame size="square" className="formtrack__face">
                      {entry.portrait ? (
                        <img className="paint__img is-loaded" src={entry.portrait} alt="" loading="lazy" />
                      ) : (
                        <span className="formtrack__glyph" aria-hidden="true">
                          {FORM_GLYPH[entry.form] || "◇"}
                        </span>
                      )}
                    </PaintFrame>
                    <span className="formtrack__label">{entry.form}</span>
                    <span className="formtrack__when">
                      {entry.day > 0 ? `day ${entry.day}` : "start"}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}

          <p className="companion__footnote">
            It is often useful. It is sometimes wrong. It occasionally lies.
          </p>
        </div>
      )}
    </aside>
  );
}
