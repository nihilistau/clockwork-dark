/**
 * The mirror pool, available whenever the player wants to look into it.
 *
 * WHAT FEEDS THIS
 * ---------------
 * `state.world.endings` -- `endings.to_client()` on the server, which is the
 * READ-ONLY twin of `recompute`: it evaluates both gates for every declared
 * ending and commits nothing, so opening this screen is not a move. The key
 * exists only for a story with an endings table, which is what keeps this
 * overlay out of a borrowed plugin whose story has no finale.
 *
 * The tiers are the engine's, not this file's. `unlocked` is the eligible set,
 * `silhouette` is an ending whose `completable` half has failed -- something
 * still live makes it impossible -- and `locked` is everything else: earnable,
 * not yet earned. Those are separate on purpose upstream and the whole reason
 * this screen can be honest about which one the player is looking at.
 *
 * WHAT THE SERVER DELIBERATELY DID NOT SEND, and why this file does not invent
 * it: a silhouette has no `title`. The server withholds it, because a
 * silhouette carrying the name of the thing it is a silhouette of is not one,
 * and `EndingGallery` draws an em dash where a title would go. Likewise there
 * is no score anywhere in the payload -- `closeness` is one of the same five
 * band words a veiled meter uses, so there is nothing here to reverse into a
 * number.
 *
 * SWEARING IS AN ORDINARY TURN. `endings.set_intent` is an authored-content
 * effect kind: the mirror pool card is what calls it, and it refuses an
 * ineligible id. So this says what the player does and lets the scene resolve
 * it, exactly as every other action in this client does -- and the button goes
 * dead once the finale has committed, because a swear that cannot bend
 * anything is a fake card wearing a different hat.
 */
import React from "react";

import Modal from "@core/parts/Modal.jsx";
import EndingGallery from "./EndingGallery.jsx";

/**
 * What to say about an ending whose story wrote it no `tease:`.
 *
 * Per TIER and not per ending, because the alternative is this file inventing
 * prose about twenty-three endings it did not author. The tease is an optional
 * authored line; when a story writes one it wins, and when it does not the
 * player still gets a sentence that is true of the tier rather than an empty
 * paragraph where prose should be.
 */
const NO_TEASE = {
  unlocked: "This one is yours to take. The water is quite calm about it.",
  locked: "The shape is there. What it becomes is still being decided.",
  silhouette: "An outline, and nothing behind it that you can reach from here.",
};

export default function GalleryOverlay({ state, busy, onAct, onClose }) {
  const finale = state?.world?.endings || {};
  const rows = finale.gallery || [];

  // snake_case on the wire, camelCase in the component. Mapped in ONE place,
  // and `tests/test_ui_contract.py` asserts this map covers exactly the keys
  // the server ships -- the same guard that caught EpilogueCard reading five
  // field names the server had never sent.
  const endings = rows.map((row) => ({
    id: row.id,
    title: row.title,
    tier: row.tier,
    tease: row.tease || NO_TEASE[row.tier] || "",
    lockReason: row.lock_reason,
    gate: row.gate,
    closeness: row.closeness,
  }));

  /**
   * Whether every door but the fail-forward is genuinely SHUT.
   *
   * Not `finale.forced`, and the difference is a sentence that was wrong on
   * day one. `forced` means the eligible set is the fail-forward alone, which
   * on the first morning of a ten-day story is simply true and unremarkable --
   * twenty-two endings were sitting there "still open" under a line saying
   * only one door was. What the warning is actually about is every other
   * ending having become UNREACHABLE, which is the tier, not the set.
   */
  const shut =
    Boolean(finale.forced) &&
    rows.length > 1 &&
    rows.every((row) => row.tier !== "locked");

  const swear = (id) => {
    const row = endings.find((e) => e.id === id);
    onAct?.(
      `I look into the water and swear toward ${row?.title || id}. ` +
        `I say it aloud, knowing what it closes.`
    );
    onClose?.();
  };

  return (
    <Modal title="The mirror pool" onClose={onClose} wide>
      {rows.length === 0 ? (
        <p className="overlay__empty">
          The water has nothing to show yet.
        </p>
      ) : (
        <>
          <EndingGallery
            endings={endings}
            // Committed is committed. `settled` is the server's answer, not a
            // day number the client guessed at.
            canSwear={!finale.settled && !busy}
            onSwear={swear}
            // Looking is free and already local: the component opens its own
            // inspect panel, and spending a turn on it would make the honest
            // move the expensive one.
            onLook={undefined}
          />
          {shut && (
            <p className="gallery__forced">
              Every other door is shut. What is left is the one that is always
              left, and it is a real ending — that is not the water being
              unkind, it is the water being accurate.
            </p>
          )}
        </>
      )}
    </Modal>
  );
}
