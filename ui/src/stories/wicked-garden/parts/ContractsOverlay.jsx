/**
 * The scrolls the player is actually holding.
 *
 * WHAT FEEDS THIS
 * ---------------
 * `state.world.threads` -- `threads.summary()` on the server, which trims a
 * live contract down to the six things a reader needs and deliberately leaves
 * the effect hooks behind. The key exists only for a story that declares
 * `paths.threads`, which is what gates this overlay out of a plugin borrowed by
 * a story with no bargains (see `when` in the plugin's `overlays` list).
 *
 * This is the last mile of a system that was complete on the server and blank
 * in the browser: the lifecycle ran, the ledger mirrored it, `summary()` was
 * written for exactly this screen, and nothing had ever called it.
 *
 * THE THREE ANSWERS, AGAINST A CONTRACT THAT IS ALREADY SEALED
 * -----------------------------------------------------------
 * `ContractScroll` draws Accept / Renegotiate / Refuse as peers, and all three
 * stay honest here because a live thread is a thing you can still do three
 * different things about:
 *
 *   Accept      keep it as it stands. Costs a turn and nothing else.
 *   Renegotiate reopen it -- the engine's `renegotiate` verb returns a
 *               DIFFERENT contract, not the same one on better numbers, which
 *               is why this is the move the story is usually asking for.
 *   Refuse      cut it. `can_cut_with` is what the thread itself admits can
 *               sever it, and it is spelled out on the scroll, because a
 *               refusal offered with no visible escape route is a bluff.
 *
 * Every one of them is an ORDINARY TURN through `onAct`. The engine stays the
 * only writer of a thread's status: the client says what the player does, and
 * `threads.renegotiate` / `threads.cut` are reached the way every other verb in
 * this product is reached -- by playing the turn, not by posting to a route.
 *
 * THE VEILED RULE IS NOT TOUCHED HERE. Nothing on this screen is a meter. The
 * only number is `due_day`, which is a calendar date the story tells the player
 * out loud when the bargain is struck.
 */
import React from "react";

import Modal from "@core/parts/Modal.jsx";
import ContractScroll from "./ContractScroll.jsx";

/**
 * What each declared cutter is, in words.
 *
 * Keyed off `data/rules/threads.yaml`'s `cutters:` block -- the story's own
 * vocabulary, not the engine's. A cutter this table has no line for still
 * appears, spelled out of its id, because a thread that says it can be severed
 * by something must show the player what that something is even when nobody
 * has written the sentence yet.
 */
const CUTTER_WORDS = {
  mirror_glass_knife: "a knife of mirror-glass, which is spent in the cutting",
  law: "the law, if you have read enough of it to say the words",
  death: "death, which is not a plan",
  sovereign_word: "a sovereign's word, if you have a seat to speak it from",
};

const say = (id) => CUTTER_WORDS[id] || String(id).replace(/_/g, " ");

/** Gold is the Garden's own hand; silver is Ashen Vale's. */
function inkFor(source) {
  return /ashen|vale|frost/i.test(String(source || "")) ? "silver" : "gold";
}

/**
 * The clauses of a live contract, as rows a player can point at.
 *
 * A term row is what makes Renegotiate mean something -- the marked clause is
 * handed back, so "I want THIS changed" is expressible. So the rows are the
 * things that can actually be argued about: what it binds, when it comes due,
 * and each way out it admits.
 */
function termsOf(thread) {
  const rows = [];

  for (const tag of thread.tags || []) {
    rows.push({
      id: `tag:${tag}`,
      tag,
      text: `This thread binds you in ${tag.toLowerCase()}.`,
    });
  }

  rows.push(
    thread.due_day
      ? {
          id: "due",
          tag: "Due",
          text: `It comes due on day ${thread.due_day}.`,
          cost: "unpaid, it breaks",
        }
      : {
          id: "due",
          tag: "Open",
          text: "No day is named. It simply holds.",
        }
  );

  for (const cutter of thread.can_cut_with || []) {
    rows.push({
      id: `cut:${cutter}`,
      tag: "Severance",
      text: `It can be cut with ${say(cutter)}.`,
      cost: "cutting costs",
    });
  }

  return rows;
}

/** A term id back into something a sentence can contain. */
function clauseWords(thread, termId) {
  if (!termId) return "the whole of it";
  const row = termsOf(thread).find((t) => t.id === termId);
  return row ? row.text.replace(/\.$/, "") : "the whole of it";
}

function Scroll({ thread, busy, onAct, onClose }) {
  const who = thread.source || "someone who did not sign their name";

  /** Say it, then close: the answer is the turn, and the scroll is read. */
  const act = (line) => {
    onAct?.(line);
    onClose?.();
  };

  return (
    <ContractScroll
      // The tags ARE the contract's nature, in the story's own declared
      // vocabulary. A thread with none says so rather than borrowing a name.
      title={(thread.tags || []).join(" · ") || "A bargain"}
      offeredBy={who}
      preamble={thread.terms}
      terms={termsOf(thread)}
      seal={thread.sealed_by || "a word"}
      ink={inkFor(who)}
      busy={busy}
      onAccept={() =>
        act(`I let the bargain with ${who} stand as it is, and say so plainly.`)
      }
      onRenegotiate={(termId) =>
        act(
          `I ask ${who} to reopen our bargain — ${clauseWords(thread, termId)} — ` +
            `and I name what I want changed.`
        )
      }
      onRefuse={() =>
        act(
          `I refuse to keep the bargain with ${who} any longer. I cut the thread, ` +
            `and I take what cutting it costs.`
        )
      }
    />
  );
}

export default function ContractsOverlay({ state, busy, onAct, onClose }) {
  const threads = state?.world?.threads || [];

  return (
    <Modal title="What you have signed" onClose={onClose} wide>
      {threads.length === 0 ? (
        <p className="overlay__empty">
          Nothing yet. You have not agreed to anything you cannot walk away
          from — which, here, is a thing worth noticing rather than assuming.
        </p>
      ) : (
        <div className="scrolls">
          {threads.map((thread) => (
            <Scroll
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
