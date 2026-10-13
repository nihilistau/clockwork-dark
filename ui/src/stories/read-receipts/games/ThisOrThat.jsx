/**
 * This or That (spec §21.2, §18.2): five either/or pairs, one at a time;
 * the fifth pick sends all five as ONE `game_move {move: answer, answers}`.
 * Then you wait for theirs -- the payload shows their picks (`theirs`) only
 * once the reveal has ended the game, so nothing here can show them early --
 * and the reveal: each pair, both picks, and how many you agree on.
 */
import React, { useEffect, useState } from "react";

import { ChatStrip } from "./TileTalk.jsx";

const SIDES = ["a", "b"];

function Reveal({ game }) {
  const pairs = game.pairs || [];
  const mine = game.mine || [];
  const theirs = game.theirs || [];
  return (
    <>
      <p className="rr-game__status" data-testid="tot-agree">
        You agree on {Number(game.agreements) || 0} of {pairs.length || 5}
      </p>
      <ol className="rr-tot__reveal">
        {pairs.map((pair, i) => {
          const same = mine[i] && mine[i] === theirs[i];
          return (
            <li key={i} className={`rr-tot__row${same ? " is-same" : ""}`}>
              <span className="rr-tot__pair">
                {pair.a} or {pair.b}
              </span>
              <span className="rr-tot__picks">
                You: {pair[mine[i]] || "—"} · {game.name}: {pair[theirs[i]] || "—"}
                {same ? " ✓" : ""}
              </span>
            </li>
          );
        })}
      </ol>
    </>
  );
}

export default function ThisOrThat({ game, act, pending = null, chat = null, onOpenChat = null, onBack = null }) {
  const pairs = game.pairs || [];
  const [picks, setPicks] = useState([]);
  const sent = Array.isArray(game.mine) && game.mine.length > 0;
  const busy = Boolean(pending && pending.action === "game_move" && pending.target === game.id);
  const answering = game.status === "active" && game.turn === "player" && !sent;
  // The answers landed (or the game moved on): the next screen starts clean.
  useEffect(() => {
    if (sent) setPicks([]);
  }, [sent]);

  const send = (answers) => act({ action: "game_move", target: game.id, text: "", args: { move: "answer", answers } });
  const pick = (side) => {
    const next = [...picks, side].slice(0, pairs.length);
    setPicks(next);
    if (next.length === pairs.length) send(next);
  };
  const at = Math.min(picks.length, Math.max(0, pairs.length - 1));
  const pair = pairs[at];
  const complete = picks.length === pairs.length && pairs.length > 0;

  let body;
  if (game.status === "finished") {
    body = <Reveal game={game} />;
  } else if (game.status !== "active") {
    body = <p className="rr-game__status">This game ended before the reveal.</p>;
  } else if (answering && pair && !complete) {
    body = (
      <div className="rr-tot__ask" role="group" aria-label={`Pair ${at + 1} of ${pairs.length}`}>
        <p className="rr-tot__count">
          {at + 1} of {pairs.length}
        </p>
        <div className="rr-tot__choices">
          {SIDES.map((side) => (
            <button key={side} type="button" className="rr-tot__choice" data-testid={`tot-${side}`} onClick={() => pick(side)}>
              {pair[side]}
            </button>
          ))}
        </div>
        {picks.length > 0 && (
          <button type="button" className="rr-btn rr-btn--small rr-btn--quiet" onClick={() => setPicks((p) => p.slice(0, -1))}>
            Back
          </button>
        )}
      </div>
    );
  } else if (answering && complete) {
    body = (
      <div className="rr-tot__ask">
        <p className="rr-game__status">{busy ? "Sending your answers…" : "Your answers didn't go."}</p>
        {!busy && (
          <div className="rr-card__actions">
            <button type="button" className="rr-btn rr-btn--small" onClick={() => send(picks)}>
              Send again
            </button>
            <button type="button" className="rr-btn rr-btn--small rr-btn--quiet" onClick={() => setPicks([])}>
              Start over
            </button>
          </div>
        )}
      </div>
    );
  } else {
    const mine = game.mine || [];
    body = (
      <>
        <p className="rr-game__status" role="status">
          {sent ? `Waiting for ${game.name}’s answers.` : `${game.name} is answering.`}
        </p>
        {sent && (
          <ol className="rr-tot__reveal">
            {pairs.map((p, i) => (
              <li key={i} className="rr-tot__row">
                <span className="rr-tot__pair">
                  {p.a} or {p.b}
                </span>
                <span className="rr-tot__picks">You: {p[mine[i]] || "—"}</span>
              </li>
            ))}
          </ol>
        )}
      </>
    );
  }

  return (
    <section className="rr-app rr-game rr-game--tot" aria-label={`This or That with ${game.name}`} data-testid={`thisorthat-${game.id}`}>
      <header className="rr-thread__head">
        {onBack && (
          <button type="button" className="rr-back" aria-label="Back" onClick={onBack}>
            <span aria-hidden="true">‹</span>
          </button>
        )}
        <h2 className="rr-app__title rr-game__title" tabIndex={-1}>
          This or That
        </h2>
      </header>
      <div className="rr-app__body rr-tot">{body}</div>
      <ChatStrip name={game.name} chat={chat} onOpenChat={onOpenChat} />
    </section>
  );
}
