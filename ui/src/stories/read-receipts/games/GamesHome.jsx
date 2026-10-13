/**
 * The Games app (spec §21, §18.2): the games you have going -- yours to play
 * first -- and the ones just over, each opening its own screen; and a new
 * game with someone you talk to (`game_invite {game}`, which the engine may
 * refuse in words: too soon, one already running).
 */
import React, { useState } from "react";

import { GAME_WORDS } from "../thread/media.js";

function statusOf(game) {
  if (game.status === "active") {
    if (game.game === "this_or_that" && game.mine && game.mine.length) return `Waiting for ${game.name}`;
    return game.turn === "player" ? "Your turn" : `${game.name}’s turn`;
  }
  if (game.status === "finished") {
    if (game.agreements != null) return `You agree on ${game.agreements} of ${(game.pairs || []).length || 5}`;
    return game.winner === "player" ? "You won" : game.winner === "them" ? `${game.name} won` : "A draw";
  }
  return game.status === "resigned" ? "Ended early" : "Abandoned";
}

export default function GamesHome({ phone, act, pending = null, onOpenGame }) {
  const games = phone.games || [];
  const live = games.filter((g) => g.status === "active");
  live.sort((a, b) => (a.turn === "player" ? 0 : 1) - (b.turn === "player" ? 0 : 1));
  const over = games.filter((g) => g.status !== "active").slice(0, 10);
  const people = (phone.contacts || []).filter((c) => c.open);
  const [who, setWho] = useState("");
  const pid = who || (people[0] ? people[0].pid : "");
  const inviting = Boolean(pending && pending.action === "game_invite");

  const row = (g) => (
    <li key={g.id}>
      <button type="button" className="rr-chat" data-testid={`game-row-${g.id}`} onClick={() => onOpenGame(g.id)}>
        <span className="rr-chat__body">
          <span className="rr-chat__name">
            {g.label || GAME_WORDS[g.game] || g.game} with {g.name}
          </span>
          <span className="rr-chat__last">{statusOf(g)}</span>
        </span>
        {g.scores && g.scores.player != null && (
          <span className="rr-chat__side">
            {Number(g.scores.player) || 0}–{Number(g.scores.them) || 0}
          </span>
        )}
      </button>
    </li>
  );

  return (
    <section className="rr-app rr-app--games" aria-label="Games">
      <h2 className="rr-app__title" tabIndex={-1}>Games</h2>
      <div className="rr-app__body">
        <h3 className="rr-contact__head rr-games__head">Playing</h3>
        {live.length ? <ul className="rr-chats">{live.map(row)}</ul> : <p className="rr-card__sub rr-games__none">No games going.</p>}
        {people.length > 0 && (
          <div className="rr-games__new" role="group" aria-label="New game">
            <label className="rr-field">
              <span className="rr-field__label">New game with</span>
              <select className="rr-input" value={pid} onChange={(e) => setWho(e.target.value)} data-testid="new-game-who">
                {people.map((c) => (
                  <option key={c.pid} value={c.pid}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="rr-card__actions">
              {Object.entries(GAME_WORDS).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className="rr-btn rr-btn--small"
                  disabled={inviting || !pid}
                  onClick={() => act({ action: "game_invite", target: pid, args: { game: id }, text: "" })}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}
        {over.length > 0 && (
          <>
            <h3 className="rr-contact__head rr-games__head">Finished</h3>
            <ul className="rr-chats">{over.map(row)}</ul>
          </>
        )}
      </div>
    </section>
  );
}
