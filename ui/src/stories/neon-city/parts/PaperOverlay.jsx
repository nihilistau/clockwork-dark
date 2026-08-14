/**
 * THE PAPER — every instrument the Sprawl is currently holding against you.
 *
 * WHAT FEEDS THIS: `state.world.threads`, which is `threads.summary()` on the
 * server -- the record trimmed to the six things a reader needs, with the
 * effect hooks deliberately left behind. The key exists only for a story that
 * declares `paths.threads`, which is what the `when` gate in the plugin's
 * overlay list tests. A screen wired against a key that may not exist is a
 * permanently empty modal, and that is the disease the plugin seam was built to
 * cure.
 *
 * WHY THIS STORY HAS THIS SCREEN AT ALL. "Money is the moral system. Every
 * kindness has a cost shown or implied; every cruelty has an invoice"
 * (BIBLE §7.3). A thread here is the invoice: the marker Collections holds,
 * Dita's fifteen percent, Dane's four seconds, Wren's bill. And the endings
 * read them -- A NAME THEY STOPPED SAYING is fed by BROKEN markers and THE WALK
 * AWAY requires the crew PAID OFF -- so discharging and breaking are not two
 * flavours of "close it", they are the last act's actual fork. The three
 * buttons below are named for that distinction rather than for the verbs.
 *
 * EVERY MOVE IS AN ORDINARY TURN. The client says what the runner does and the
 * engine resolves it; `threads.renegotiate` and `threads.cut` are reached by
 * playing the turn, never by posting at a route.
 *
 * THE VEILED RULE IS NOT IN PLAY HERE. Nothing on this screen is a meter. The
 * one number is `due_day`, a calendar date the story states out loud when the
 * paper is signed.
 */
import React from "react";

import Modal from "@core/parts/Modal.jsx";

/**
 * What each declared cutter is, in the Sprawl's words.
 *
 * Keyed off `games/neon-city/data/rules/threads.yaml`'s `cutters:` block -- the
 * story's own vocabulary. A cutter this table has no line for still shows,
 * spelled out of its id, because paper that admits a way out has to show the
 * runner what it is even where nobody has written the sentence yet.
 */
const CUTTERS = {
  paid_in_full: "paid in full, in chips, on the counter",
  miras_word: "Mira's word, if your name is worth that much to her",
  forged_id: "a forged identity, which the closing spends",
};

const say = (id) => CUTTERS[id] || String(id).replace(/_/g, " ");

function Record({ thread, busy, onAct, onClose }) {
  const who = thread.source || "an unsigned holder";
  const tags = thread.tags || [];
  const cutters = thread.can_cut_with || [];

  /** Say it, then close: the answer is the turn, and the paper has been read. */
  const act = (line) => {
    onAct?.(line);
    onClose?.();
  };

  return (
    <article className="nc-paper">
      <header className="nc-paper__head">
        <span className="nc-paper__tags">
          {tags.length ? tags.join(" · ").toUpperCase() : "UNCLASSIFIED"}
        </span>
        <span className="nc-paper__holder">{who}</span>
      </header>

      {thread.terms && <p className="nc-paper__terms">{thread.terms}</p>}

      <dl className="nc-paper__rows">
        <div className="nc-paper__row">
          <dt>DUE</dt>
          <dd>{thread.due_day ? `DAY ${String(thread.due_day).padStart(2, "0")}` : "OPEN"}</dd>
        </div>
        <div className="nc-paper__row">
          <dt>SEAL</dt>
          <dd>{thread.sealed_by || "unrecorded"}</dd>
        </div>
      </dl>

      {cutters.length > 0 && (
        <ul className="nc-paper__cutters">
          {cutters.map((cutter) => (
            <li key={cutter}>
              <span aria-hidden="true">▸ </span>
              Closes on {say(cutter)}.
            </li>
          ))}
        </ul>
      )}

      <div className="nc-paper__moves">
        <button
          type="button"
          className="btn btn--ghost"
          disabled={busy}
          onClick={() => act(`I let the arrangement with ${who} stand exactly as written.`)}
        >
          LET IT STAND
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          disabled={busy}
          onClick={() =>
            act(
              `I go to ${who} and reopen the terms. I say which clause I want ` +
                `changed and what I am putting up for it.`
            )
          }
        >
          REOPEN
        </button>
        <button
          type="button"
          className="btn btn--ghost nc-paper__break"
          disabled={busy}
          onClick={() =>
            act(
              `I break the arrangement with ${who}. I do not pay it off and I do ` +
                `not explain, and I take whatever breaking it costs.`
            )
          }
        >
          BREAK IT
        </button>
      </div>
    </article>
  );
}

export default function PaperOverlay({ state, busy, onAct, onClose }) {
  const threads = state?.world?.threads || [];

  return (
    <Modal title="The paper" onClose={onClose} wide>
      {threads.length === 0 ? (
        <p className="overlay__empty">
          Nothing outstanding. Nobody in the Sprawl is currently holding a
          reason to come and find you, which is a thing worth noticing rather
          than assuming.
        </p>
      ) : (
        <div className="nc-papers">
          {threads.map((thread) => (
            <Record
              key={thread.id}
              thread={thread}
              busy={busy}
              onAct={onAct}
              onClose={onClose}
            />
          ))}
        </div>
      )}
    </Modal>
  );
}
