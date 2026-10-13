/**
 * An open request in a thread (spec §7.1's `ask`/`answer`, §10.5): theirs,
 * with Yes / Maybe later / No (`answer {reply}`), or the player's own,
 * waiting on their answer. Only what the payload's `requests` row says: who,
 * what, its status and, for a meet-up, the engine's pick of place and time --
 * never the odds of a yes.
 *
 * Also the thread's game and meet-up cards (spec §18.2): a game with them
 * (`games`: whose turn, the scores, how it ended -- never their rack) and a
 * planned meet-up (`calendar`: where, when, its status; Go on the day,
 * Cancel while it is planned, `meet {do}`).
 */
import React, { useEffect, useRef, useState } from "react";

import { humanize, stampOf } from "../phone/format.js";
import Confirm from "../phone/Confirm.jsx";
import { askLine, GAME_WORDS } from "./media.js";

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
  return (
    <li className={`rr-card rr-card--request${theirs ? "" : " rr-card--mine"}`} data-testid={`request-${request.id}`}>
      <p className="rr-card__line">{askLine(request.what, name, !theirs, request.game || "")}</p>
      {where && <p className="rr-card__sub">{where}</p>}
      {theirs ? (
        <>
          {request.status === "later" && <p className="rr-card__sub">You said maybe later.</p>}
          <div className="rr-card__actions">
            <button type="button" className="rr-btn rr-btn--small" disabled={busy} onClick={() => answer("yes")}>
              Yes
            </button>
            {request.status !== "later" && (
              <button type="button" className="rr-btn rr-btn--small rr-btn--quiet" disabled={busy} onClick={() => answer("later")}>
                Maybe later
              </button>
            )}
            <button type="button" className="rr-btn rr-btn--small rr-btn--quiet" disabled={busy} onClick={() => answer("no")}>
              No
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

const MEET_STATUS = {
  agreed: "Planned",
  due: "It’s time",
  going: "On your way",
  cancelled: "Called off",
  flaked: "Called off",
  no_show: "Nobody came",
};

export function MeetCard({ meet, act, pending = null }) {
  const [asking, setAsking] = useState(false);
  // Focus follows the confirm (T28 review I1): onto "Keep it" when it opens (the Confirm's own), back to
  // Cancel when it closes (Cancel is aria-disabled, not disabled, while the answer is awaited, so it can
  // still hold focus).
  const cancelRef = useRef(null);
  const drawn = useRef(false);
  useEffect(() => {
    if (!drawn.current) {
      drawn.current = true;
      return;
    }
    if (!asking) cancelRef.current?.focus?.();
  }, [asking]);
  const busy = Boolean(pending && pending.action === "meet" && pending.target === meet.id);
  const meetDo = (what) => {
    setAsking(false);
    act({ action: "meet", target: meet.id, args: { do: what }, text: "" });
  };
  const planned = meet.status === "agreed" || meet.status === "due";
  const status = meet.status === "done" ? meet.recap_line || "Done" : MEET_STATUS[meet.status] || humanize(meet.status);
  return (
    <li className="rr-card rr-card--meet" data-testid={`meet-${meet.id}`}>
      <p className="rr-card__line">
        <span className="rr-card__kind">{meet.venue_label || humanize(meet.venue)}</span> · {meet.when}
      </p>
      <p className="rr-card__sub">{status}</p>
      {planned && !asking && (
        <div className="rr-card__actions">
          {meet.status === "due" && (
            <button type="button" className="rr-btn rr-btn--small" disabled={busy} onClick={() => meetDo("go")}>
              Go
            </button>
          )}
          <button
            ref={cancelRef}
            type="button"
            className="rr-btn rr-btn--small rr-btn--quiet"
            aria-disabled={busy || undefined}
            onClick={() => !busy && setAsking(true)}
          >
            Cancel
          </button>
        </div>
      )}
      {planned && asking && (
        <Confirm
          label="Cancel the meet-up?"
          ask="Call it off?"
          yes="Call it off"
          no="Keep it"
          busy={busy}
          onYes={() => meetDo("cancel")}
          onNo={() => setAsking(false)}
        />
      )}
    </li>
  );
}
