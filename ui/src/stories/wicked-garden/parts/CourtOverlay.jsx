/**
 * The court, from what the server actually sends.
 *
 * WHAT FEEDS THIS, AND WHAT DOES NOT
 * ----------------------------------
 * `CourtBoard` wants a political map: who is bound to whom, and which of those
 * bindings is under strain. The obvious feed for that would be a relationship
 * block -- stance, trust, debt per NPC -- which the design's state board
 * describes and the turn payload does not carry. So this does NOT invent one.
 *
 * Two things the payload does carry are enough to draw an honest map:
 *
 *   state.meters     the story's declared values, projected by visibility.
 *                    Every one of the Garden's is VEILED, which means a band
 *                    word and no number at all.
 *   world.inventory  what the player is holding, which in this story is
 *                    evidence. You do not carry his clasp by accident.
 *
 * So the board is drawn from what can be PROVEN rather than from a cast list:
 * a power appears once the player is carrying something of theirs, and the tie
 * is what that object means. The empty state is Sophia and the thing under the
 * Garden, which is correct on day one -- those two are there whether or not
 * anybody has been met.
 *
 * THE VEILED RULE IS NOT BENT HERE. A band is a word, and the only thing done
 * with it is to pick another word and a stroke width -- the same use
 * `VineMeter` already makes of it when it lights three of five marks. No
 * number is displayed, none is stored, and nothing multiplies a band index
 * back into the integer the server declined to send.
 */
import React from "react";

import Modal from "@core/parts/Modal.jsx";
import CourtBoard from "./CourtBoard.jsx";
import { BANDS, VINES } from "./Meters.jsx";

/** Band word -> 0..4, for choosing a word or a thickness. Never for arithmetic. */
const rank = (band) => Math.max(0, BANDS.indexOf(String(band || "none")));

/** The stage word a meter's own vocabulary gives to the band it arrived as. */
function stageWord(meters, name, fallback = "unreadable") {
  const row = (meters || {})[name];
  const vine = VINES[name];
  if (!row || !vine) return fallback;
  if (row.band) return vine.words[rank(row.band)] || fallback;
  return fallback;
}

/**
 * The powers, and the objects that prove one is interested in you.
 *
 * Item ids are the story's own, from `data/items/garden.yaml`. A power with no
 * evidence is simply absent from the board -- the codex makes the same call
 * for the same reason: naming everyone up front hands the player a cast list
 * the fiction has not introduced.
 */
const POWERS = [
  {
    id: "ashen",
    name: "Ashen Vale",
    proof: ["ashen_clasp", "ashen_passport", "frost_thread", "frost_splinter"],
    standing: "winter, being patient",
    // Rivals. What is between them is not a debt, it is a grievance.
    kind: "grievance",
  },
  {
    id: "thornwake",
    name: "Thornwake",
    proof: ["salt_circle_chalk", "iron_pin"],
    standing: "the law of the seat",
    // He serves the Seat and not the woman in it, which is an obligation
    // pointed at the office. It is the most reliable line on the board.
    kind: "obligation",
  },
  {
    id: "lior",
    name: "Lior",
    proof: ["mirror_chip", "mirror_glass_knife"],
    standing: "mirrors wait, and charge",
    kind: "watching",
  },
  {
    id: "elias",
    name: "Elias",
    proof: ["pressed_letter", "sap_sketch"],
    standing: "preserved, and lucid",
    // Something owed that is not going to be paid.
    kind: "grievance",
  },
];

/** Mother Briar hangs UNDER the centre rather than orbiting it. */
const ROOT = {
  id: "briar",
  name: "Mother Briar",
  standing: "a heartbeat under the roots",
};

export default function CourtOverlay({ state, onClose }) {
  const meters = state?.meters || {};
  const carried = new Set(
    (state?.world?.inventory || []).map((item) => String(item.id))
  );

  const satellites = POWERS.filter((power) =>
    power.proof.some((id) => carried.has(id))
  ).map((power) => ({ id: power.id, name: power.name, standing: power.standing }));

  const centre = {
    id: "sophia",
    name: "Sophia",
    // Two meters, two words, no numbers: how she regards you and how warm it is.
    standing: `${stageWord(meters, "favor")} · ${stageWord(meters, "desire")}`,
  };

  const edges = [
    // She owes the roots a yield, always. The strain is what the Garden has
    // taken out of the player so far -- gold under the skin, as a band.
    {
      from: "sophia",
      to: "briar",
      kind: "obligation",
      strain: 0.6 + rank(meters.corruption?.band) * 0.35,
    },
    ...POWERS.filter((power) => satellites.some((s) => s.id === power.id)).map(
      (power) => ({
        from: "sophia",
        to: power.id,
        kind: power.kind,
        // How much of you is left is what every one of these ties is really
        // straining against.
        strain: 0.5 + (4 - rank(meters.autonomy?.band)) * 0.3,
      })
    ),
  ];

  // The Captain and the roots have their own quarrel and it predates the
  // player. Drawn only when he is on the board at all, because an edge to a
  // node that is not there renders as nothing and reads as a bug.
  if (satellites.some((s) => s.id === "thornwake")) {
    edges.push({ from: "thornwake", to: "briar", kind: "grievance", strain: 1.1 });
  }

  return (
    <Modal title="The court" onClose={onClose} wide>
      <CourtBoardPanel
        centre={centre}
        satellites={satellites}
        roots={[ROOT]}
        edges={edges}
        empty={satellites.length === 0}
      />
    </Modal>
  );
}

/**
 * Split out so the board and the sentence that frames it stay together.
 *
 * The framing matters: a player looking at three nodes needs to know that the
 * board is showing what they can prove rather than everyone who exists, or the
 * Garden reads as much emptier than it is.
 */
function CourtBoardPanel({ centre, satellites, roots, edges, empty }) {
  return (
    <>
      <CourtBoard centre={centre} satellites={satellites} roots={roots} edges={edges} />
      <p className="court__note">
        {empty
          ? "Only she and the thing under the Garden, so far. The court draws itself as you collect proof that someone is interested in you."
          : "Everyone here has left something on you. The lines are what those objects mean."}
      </p>
    </>
  );
}
