/**
 * THE ROADS — the six ways this crossing can end, and which of them are still
 * roads.
 *
 * WHAT FEEDS THIS: `state.world.endings`, which is `endings.to_client()` on the
 * server -- the READ-ONLY twin of `recompute`. It evaluates both gates for
 * every declared ending and commits nothing, so opening this is not a move and
 * costs no time. The key exists only for a story with an endings table, which
 * is what the `when` gate in the plugin's overlay list tests.
 *
 * THE THREE TIERS ARE THE ENGINE'S, not this file's, and they are three because
 * the two gates are separate on purpose (games/neon-city/data/rules/endings.yaml
 * says so in its own header): `requires` is "you have earned this",
 * `completable` is "nothing still live makes it impossible".
 *
 *   unlocked    both gates pass. A road.
 *   locked      earnable, not yet earned. Still a road.
 *   silhouette  `completable` has failed. Not a road any more, and the server
 *               deliberately withholds its TITLE -- a silhouette carrying the
 *               name of the thing it is a silhouette of is not one. An em dash
 *               goes where the name would.
 *
 * THE VEILED RULE, ARRIVING THROUGH A DIFFERENT DOOR. `closeness` is a
 * continuous score banded by the same code that bands a veiled meter, so it
 * lands under the same rule: the word is the whole truth the reader gets. This
 * file prints it and does nothing else with it -- no arithmetic, no percentage,
 * no bar width, no lookup table turning it back into a figure. There is no
 * score anywhere in the payload to reveal; the only way to leak one is to
 * manufacture it here.
 *
 * READ-ONLY ON PURPOSE. The Garden's mirror pool lets a player SWEAR toward an
 * ending, because `endings.set_intent` is wired into its content. This story
 * locks its ending from one quest -- `who_holds_the_pen` carries
 * `{type: ending_lock}` with no id, so the id belongs to what the run earned --
 * and no NeonCity content calls `set_intent`. A button that declares an
 * intention nothing reads is a fake control, so there is not one.
 */
import React from "react";

import Modal from "@core/parts/Modal.jsx";

const TIER = {
  unlocked: { chip: "OPEN", tone: "open" },
  locked: { chip: "NOT YET", tone: "pending" },
  silhouette: { chip: "CLOSED", tone: "shut" },
};

/**
 * What to say about a road whose story wrote it no `tease:`.
 *
 * Per TIER and not per ending: the alternative is this file inventing prose
 * about six endings it did not author. An authored tease always wins.
 */
const NO_TEASE = {
  unlocked: "This one is currently walkable. Nothing in the way but the walk.",
  locked: "Reachable. Not yet earned, and the difference is work.",
  silhouette: "Something already done has closed this. It does not reopen.",
};

function Road({ row }) {
  const tier = TIER[row.tier] || TIER.locked;
  const shut = row.tier === "silhouette";

  return (
    <article className="nc-road" data-tone={tier.tone}>
      <header className="nc-road__head">
        <h3 className="nc-road__title">
          {/* No title for a silhouette. The server withholds it; this draws the
              gap rather than filling it in. */}
          {shut ? <span aria-label="Name withheld">—</span> : row.title || row.id}
        </h3>
        <span className="nc-road__chip">{tier.chip}</span>
      </header>

      <p className="nc-road__tease">{row.tease || NO_TEASE[row.tier] || ""}</p>

      <dl className="nc-road__rows">
        <div className="nc-road__row">
          <dt>PROXIMITY</dt>
          {/* A band word, printed. Nothing is computed from it -- see the
              header. */}
          <dd>{String(row.closeness || "unread").toUpperCase()}</dd>
        </div>
        {row.lock_reason && (
          <div className="nc-road__row">
            <dt>IN THE WAY</dt>
            <dd className="nc-road__reason">{row.lock_reason}</dd>
          </div>
        )}
      </dl>
    </article>
  );
}

export default function RoadsOverlay({ state, onClose }) {
  const finale = state?.world?.endings || {};
  const rows = finale.gallery || [];

  /**
   * Whether every road but the fail-forward is genuinely SHUT.
   *
   * Not `finale.forced` on its own: `forced` means the eligible set is the
   * fail-forward alone, which on the first morning of a twenty-one-day story is
   * simply true and unremarkable. What is worth saying out loud is every other
   * ending having become UNREACHABLE, which is the tier, not the set.
   */
  const shut =
    Boolean(finale.forced) &&
    rows.length > 1 &&
    rows.every((row) => row.tier !== "locked");

  return (
    <Modal title="The roads" onClose={onClose} wide>
      {rows.length === 0 ? (
        <p className="overlay__empty">Nothing filed yet. The crossing has not started.</p>
      ) : (
        <>
          <div className="nc-roads">
            {rows.map((row) => (
              <Road key={row.id} row={row} />
            ))}
          </div>
          {shut && (
            <p className="nc-roads__forced">
              Every other road is closed. What is left is the one that is always
              left, and it is a real ending — the file does not consider that a
              failure, and neither should you.
            </p>
          )}
        </>
      )}
    </Modal>
  );
}
