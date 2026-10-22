/**
 * An open request in a thread (spec §7.1's `ask`/`answer`, §10.5): theirs,
 * with Yes / Maybe later / No (`answer {reply}`), or the player's own,
 * waiting on their answer. Only what the payload's `requests` row says: who,
 * what, its status and, for a meet-up, the engine's pick of place and time --
 * never the odds of a yes.
 *
 * Their requests with a meaning of their own are worded for it (v0.23.0
 * T22): a job offered elsewhere (`stay_or_go`) is "Ask them to stay" / "Let
 * them go" / "Later", so the player sees what each answer does (the engine's
 * `life.answer_stay_or_go`: yes asks them to stay, no tells them to go,
 * later leaves it open), and moving in and marrying say so.
 *
 * Also the thread's game card (spec §18.2): a game with them (`games`:
 * whose turn, the scores, how it ended -- never their rack). A plan to meet
 * has no card since v0.23.0: it is a row of Calendar's "Coming up".
 */
import React from "react";

import { humanize, stampOf } from "../phone/format.js";
import { askLine, GAME_WORDS } from "./media.js";

/** The answers' own words for a request that means more than yes or no, by `request.what`. */
export const ANSWER_LABELS = {
  stay_or_go: { yes: "Ask them to stay", later: "Later", no: "Let them go" },
  move_in: { yes: "Yes, move in", later: "Maybe later", no: "Not now" },
  propose: { yes: "Say yes", later: "Maybe later", no: "Say no" },
};
const DEFAULT_LABELS = { yes: "Yes", later: "Maybe later", no: "No" };

/** What an answer to a job offer does, said plainly under its buttons. */
const JOB_NOTE = "Asking them to stay may keep them here. Letting them go means they take the job and you part ways.";

/** A meet request's place and time, as the payload words them ("The Anchor · Fri 19:00"). */
function meetWords(request) {
  if (!request.venue) return "";
  return [request.venue_label || humanize(request.venue), request.when].filter(Boolean).join(" · ");
}

export default function RequestCard({ request, name, now, act, pending = null }) {
  const theirs = request.from !== "player";
  const busy = Boolean(pending && pending.action === "answer" && pending.target === request.id);
  const answer = (reply) => act({ action: "answer", target: request.id, args: { reply }, text: "" });
  const where = meetWords(request);
  const label = { ...DEFAULT_LABELS, ...(ANSWER_LABELS[request.what] || {}) };
  return (
    <li className={`rr-card rr-card--request${theirs ? "" : " rr-card--mine"}`} data-testid={`request-${request.id}`}>
      <p className="rr-card__line">{askLine(request.what, name, !theirs, request.game || "")}</p>
      {where && <p className="rr-card__sub">{where}</p>}
      {theirs && request.what === "stay_or_go" && <p className="rr-card__sub">{JOB_NOTE}</p>}
      {theirs ? (
        <>
          {request.status === "later" && <p className="rr-card__sub">You said maybe later.</p>}
          <div className="rr-card__actions">
            <button type="button" className="rr-btn rr-btn--small" disabled={busy} onClick={() => answer("yes")}>
              {label.yes}
            </button>
            {request.status !== "later" && (
              <button type="button" className="rr-btn rr-btn--small rr-btn--quiet" disabled={busy} onClick={() => answer("later")}>
                {label.later}
              </button>
            )}
            <button type="button" className="rr-btn rr-btn--small rr-btn--quiet" disabled={busy} onClick={() => answer("no")}>
              {label.no}
            </button>
          </div>
        </>
      ) : request.status === "later" ? (
        // Their answer, not a wait (T30 follow-up): "later" is theirs to keep or break.
        <p className="rr-card__sub">{name} said maybe later.</p>
      ) : (
        <p className="rr-card__sub">Waiting for {name}’s answer · {stampOf(request.at, now)}</p>
      )}
    </li>
  );
}

const GAME_STATUS = { abandoned: "Abandoned", resigned: "Ended early" };

export function GameCard({ game, onOpenGame = null }) {
  const label = game.label || GAME_WORDS[game.game] || humanize(game.game);
  let status;
  if (game.status === "active") status = game.turn === "player" ? "Your turn" : `${game.name}’s turn`;
  else if (game.status === "finished") {
    if (game.agreements != null) status = `You agree on ${game.agreements} of ${(game.pairs || []).length || 5}`;
    else status = game.winner === "player" ? "You won" : game.winner === "them" ? `${game.name} won` : "A draw";
  } else status = GAME_STATUS[game.status] || humanize(game.status);
  const scores = game.scores && typeof game.scores === "object" && game.scores.player != null ? game.scores : null;
  return (
    <li className="rr-card rr-card--game" data-testid={`game-${game.id}`}>
      <p className="rr-card__line">
        <span className="rr-card__kind">{label}</span> · {status}
      </p>
      {scores && (
        <p className="rr-card__sub">
          You {Number(scores.player) || 0} · {game.name} {Number(scores.them) || 0}
        </p>
      )}
      {onOpenGame && game.status === "active" && (
        <div className="rr-card__actions">
          <button type="button" className="rr-btn rr-btn--small" onClick={() => onOpenGame(game.id)}>
            {game.turn === "player" ? "Play" : "Open"}
          </button>
        </div>
      )}
    </li>
  );
}
