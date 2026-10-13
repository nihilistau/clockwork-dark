/**
 * Tile Talk (spec §21.1, §18.2): the 11x11 board and its premium squares,
 * your rack, the scores and the bag's count, from the payload's game row
 * (`board`, `premiums`, `rack`, `scores`, `bag_left`, `turn`) -- never their
 * rack, never the bag's letters.
 *
 * Placing is the client's: tap a rack tile then a square (or drag the tile
 * onto it); tap a placed tile to take it back. By keyboard: Tab to a square
 * and type a letter on your rack (Backspace takes it back); every square and
 * tile is a plain button (T29 review M3: no grid role it does not keep). Play sends the placement as
 * ONE `game_move {move: play, tiles: [{x, y, letter, blank?}]}`; the engine
 * judges it -- the line, the words formed, the score -- and refuses a bad
 * one in words (rule 1), so no score is worked out here. Pass, swap (pick
 * the tiles to throw back) and resign are `game_move`s too. A strip below
 * links the chat with them.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";

import Confirm from "../phone/Confirm.jsx";
import { humanize } from "../phone/format.js";

/** A premium square's words (games.yaml's letters: l L w W, * the centre). */
export const PREMIUMS = {
  l: { short: "2L", words: "double letter" },
  L: { short: "3L", words: "triple letter" },
  w: { short: "2W", words: "double word" },
  W: { short: "3W", words: "triple word" },
  "*": { short: "★", words: "centre" },
};
const BLANK = "?";
const EMPTY = ".";
const ALPHABET = "abcdefghijklmnopqrstuvwxyz".split("");

function lastMoveWords(game) {
  const moves = game.moves || [];
  const last = moves[moves.length - 1];
  if (!last) return "";
  const who = last.by === "player" ? "You" : game.name;
  if (last.kind === "play" && last.words && last.words.length) {
    return `${who} played ${String(last.words[0]).toUpperCase()} for ${Number(last.score) || 0}.`;
  }
  if (last.kind === "swap") return `${who} swapped ${last.swapped ? `${last.swapped} tiles` : "tiles"}.`;
  if (last.kind === "pass") return `${who} passed.`;
  if (last.kind === "resign") return `${who} resigned.`;
  return "";
}

function resultWords(game) {
  if (game.status === "finished") {
    if (game.winner === "player") return "You won.";
    if (game.winner === "them") return `${game.name} won.`;
    return "It's a draw.";
  }
  if (game.status === "resigned") return "The game ended early.";
  if (game.status === "abandoned") return "The game was abandoned.";
  return humanize(game.status);
}

export default function TileTalk({ game, act, pending = null, chat = null, onOpenChat = null, onBack = null }) {
  const board = Array.isArray(game.board) ? game.board : [];
  const premiums = Array.isArray(game.premiums) ? game.premiums : [];
  const size = board.length || premiums.length || 11;
  const rack = String(game.rack || "").split("");
  const active = game.status === "active";
  const mine = active && game.turn === "player";
  const busy = Boolean(pending && pending.action === "game_move" && pending.target === game.id);
  const [placed, setPlaced] = useState([]); // [{x, y, letter, blank, from}] from = rack index
  const [selected, setSelected] = useState(null);
  const [swapping, setSwapping] = useState(false);
  const [swapPick, setSwapPick] = useState([]);
  const [confirmResign, setConfirmResign] = useState(false);
  // The Resign confirm gives focus back to Resign when it closes without resigning (review M4).
  const resignRef = useRef(null);
  const resignAsked = useRef(false);
  useEffect(() => {
    if (confirmResign) resignAsked.current = true;
    else if (resignAsked.current) {
      resignAsked.current = false;
      resignRef.current?.focus?.();
    }
  }, [confirmResign]);

  // A new board (a move landed, either side): the tiles go back to the rack. A refusal changes
  // nothing on the board, so the placement stays for the player to fix.
  const boardKey = `${board.join("/")}|${game.rack}`;
  useEffect(() => {
    setPlaced([]);
    setSelected(null);
    setSwapping(false);
    setSwapPick([]);
  }, [boardKey]);

  const used = useMemo(() => new Set(placed.map((p) => p.from)), [placed]);
  const at = (x, y) => placed.find((p) => p.x === x && p.y === y) || null;
  const filled = (x, y) => (board[y] || "")[x] && (board[y] || "")[x] !== EMPTY;

  const place = (from, x, y) => {
    if (!mine || from == null || used.has(from) || filled(x, y) || at(x, y)) return;
    const ch = rack[from];
    setPlaced((p) => [...p, { x, y, letter: ch === BLANK ? "" : ch, blank: ch === BLANK, from }]);
    setSelected(null);
  };
  const onCell = (x, y) => {
    const here = at(x, y);
    if (here) {
      setPlaced((p) => p.filter((t) => t !== here));
      return;
    }
    if (selected != null) place(selected, x, y);
  };
  const setBlank = (tile, letter) => setPlaced((p) => p.map((t) => (t === tile ? { ...t, letter } : t)));
  // A square by keyboard: a letter places that rack tile there (a blank when the rack holds no such
  // letter); Backspace or Delete takes a placed tile back.
  const onCellKey = (event, x, y) => {
    if (!mine || event.metaKey || event.ctrlKey || event.altKey) return;
    if ((event.key === "Backspace" || event.key === "Delete") && at(x, y)) {
      event.preventDefault();
      onCell(x, y);
      return;
    }
    const letter = event.key.length === 1 ? event.key.toLowerCase() : "";
    if (!ALPHABET.includes(letter)) return;
    event.preventDefault();
    let from = rack.findIndex((ch, i) => ch === letter && !used.has(i));
    const blank = from < 0;
    if (blank) from = rack.findIndex((ch, i) => ch === BLANK && !used.has(i));
    if (from < 0 || filled(x, y) || at(x, y)) return;
    setPlaced((p) => [...p, { x, y, letter, blank, from }]);
    setSelected(null);
  };

  const ready = placed.length > 0 && placed.every((t) => t.letter);
  const play = () => {
    if (!ready) return;
    const tiles = placed.map((t) => (t.blank ? { x: t.x, y: t.y, letter: t.letter, blank: true } : { x: t.x, y: t.y, letter: t.letter }));
    act({ action: "game_move", target: game.id, text: "", args: { move: "play", tiles } });
  };
  const move = (args) => act({ action: "game_move", target: game.id, text: "", args });

  const onRack = (i) => {
    if (swapping) {
      setSwapPick((s) => (s.includes(i) ? s.filter((n) => n !== i) : [...s, i]));
      return;
    }
    if (used.has(i)) return;
    setSelected((s) => (s === i ? null : i));
  };

  const scores = game.scores || {};
  const blanks = placed.filter((t) => t.blank);

  return (
    <section className="rr-app rr-game rr-game--tiles" aria-label={`Tile Talk with ${game.name}`} data-testid={`tiletalk-${game.id}`}>
      <header className="rr-thread__head">
        {onBack && (
          <button type="button" className="rr-back" aria-label="Back" onClick={onBack}>
            <span aria-hidden="true">‹</span>
          </button>
        )}
        <h2 className="rr-app__title rr-game__title" tabIndex={-1}>
          Tile Talk
        </h2>
        <p className="rr-game__score" data-testid="tile-score">
          You {Number(scores.player) || 0} · {game.name} {Number(scores.them) || 0}
        </p>
      </header>
      <p className="rr-game__status" role="status">
        {active ? (mine ? "Your turn" : `${game.name}’s turn`) : resultWords(game)}
        {lastMoveWords(game) ? ` · ${lastMoveWords(game)}` : ""}
        {active && game.bag_left != null ? ` · ${game.bag_left} in the bag` : ""}
      </p>
      <div className="rr-board-wrap">
        <div className="rr-board" role="group" aria-label="Board" style={{ gridTemplateColumns: `repeat(${size}, 1fr)` }}>
          {Array.from({ length: size }, (_, y) => (
            <div key={y} className="rr-board__row">
              {Array.from({ length: size }, (_, x) => {
                const letter = (board[y] || "")[x] || EMPTY;
                const premium = PREMIUMS[(premiums[y] || "")[x]] || null;
                const mineHere = at(x, y);
                const shown = mineHere ? (mineHere.letter || BLANK) : letter !== EMPTY ? letter : "";
                const blankPlayed = letter !== EMPTY && letter === letter.toUpperCase();
                const label = `Row ${y + 1}, column ${x + 1}${shown ? `, ${shown.toUpperCase()}` : premium ? `, ${premium.words}` : ""}`;
                return (
                  <button
                    key={x}
                    type="button"
                    className={[
                      "rr-cell",
                      premium && !shown ? `rr-cell--${premium.short.replace("★", "c")}` : "",
                      shown ? "has-tile" : "",
                      mineHere ? "is-new" : "",
                      (mineHere && mineHere.blank) || blankPlayed ? "is-blank" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    data-testid={`cell-${x}-${y}`}
                    aria-label={label}
                    disabled={!mine && !mineHere}
                    onClick={() => onCell(x, y)}
                    onKeyDown={(e) => onCellKey(e, x, y)}
                    onDragOver={(e) => mine && e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault();
                      const from = Number(e.dataTransfer && e.dataTransfer.getData("text/plain"));
                      if (Number.isInteger(from)) place(from, x, y);
                    }}
                  >
                    {shown ? shown.toUpperCase() : premium ? premium.short : ""}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
      {blanks.map((t) => (
        <label key={`${t.x}-${t.y}`} className="rr-field rr-blank">
          <span className="rr-field__label">Blank tile at row {t.y + 1}, column {t.x + 1} stands for</span>
          <select className="rr-input" value={t.letter} onChange={(e) => setBlank(t, e.target.value)}>
            <option value="">Pick a letter</option>
            {ALPHABET.map((c) => (
              <option key={c} value={c}>
                {c.toUpperCase()}
              </option>
            ))}
          </select>
        </label>
      ))}
      {active && (
        <div className="rr-rack" role="group" aria-label={swapping ? "Pick the tiles to swap" : "Your rack"}>
          {rack.map((ch, i) =>
            used.has(i) ? (
              <span key={i} className="rr-rack__gap" aria-hidden="true" />
            ) : (
              <button
                key={i}
                type="button"
                className={`rr-tile-btn${selected === i ? " is-on" : ""}${swapPick.includes(i) ? " is-swap" : ""}`}
                data-testid={`rack-${ch === BLANK ? "blank" : ch}`}
                aria-pressed={swapping ? swapPick.includes(i) : selected === i}
                aria-label={ch === BLANK ? "Blank tile" : `Tile ${ch.toUpperCase()}`}
                draggable={mine && !swapping}
                onDragStart={(e) => e.dataTransfer && e.dataTransfer.setData("text/plain", String(i))}
                disabled={!mine}
                onClick={() => onRack(i)}
              >
                {ch === BLANK ? "" : ch.toUpperCase()}
              </button>
            )
          )}
        </div>
      )}
      {active && (
        <div className="rr-game__actions">
          {confirmResign ? (
            <Confirm
              label="Resign the game?"
              ask="Resign? It counts as a loss."
              yes="Resign"
              no="Keep playing"
              busy={busy}
              onYes={() => {
                resignAsked.current = false;
                setConfirmResign(false);
                move({ move: "resign" });
              }}
              onNo={() => setConfirmResign(false)}
            />
          ) : swapping ? (
            <>
              <button
                type="button"
                className="rr-btn rr-btn--small"
                disabled={busy || swapPick.length === 0}
                onClick={() => move({ move: "swap", letters: swapPick.map((i) => rack[i]).join("") })}
              >
                Swap {swapPick.length || ""}
              </button>
              <button type="button" className="rr-btn rr-btn--small rr-btn--quiet" onClick={() => { setSwapping(false); setSwapPick([]); }}>
                Cancel
              </button>
            </>
          ) : (
            <>
              <button type="button" className="rr-btn rr-btn--small" disabled={!mine || busy || !ready} onClick={play}>
                Play
              </button>
              {placed.length > 0 && (
                <button type="button" className="rr-btn rr-btn--small rr-btn--quiet" onClick={() => setPlaced([])}>
                  Recall
                </button>
              )}
              <button type="button" className="rr-btn rr-btn--small rr-btn--quiet" disabled={!mine || busy || placed.length > 0} onClick={() => move({ move: "pass" })}>
                Pass
              </button>
              <button
                type="button"
                className="rr-btn rr-btn--small rr-btn--quiet"
                disabled={!mine || busy || placed.length > 0}
                onClick={() => { setSelected(null); setSwapping(true); }}
              >
                Swap
              </button>
              <button ref={resignRef} type="button" className="rr-btn rr-btn--small rr-btn--quiet" disabled={busy} onClick={() => setConfirmResign(true)}>
                Resign
              </button>
            </>
          )}
        </div>
      )}
      <ChatStrip name={game.name} chat={chat} onOpenChat={onOpenChat} />
    </section>
  );
}

/** The strip under a game: their last line in the chat and the way to it (spec §18.2). */
export function ChatStrip({ name, chat, onOpenChat }) {
  if (!chat || !onOpenChat) return null;
  const last = chat.typing ? "typing…" : chat.last && !chat.last.pending ? `${chat.last.from === "player" ? "You: " : ""}${chat.last.preview || ""}` : "";
  return (
    <button type="button" className="rr-chatstrip" data-testid="chat-strip" onClick={() => onOpenChat(chat.thread_id)}>
      <span className="rr-chatstrip__who">Chat with {name}</span>
      {last && <span className="rr-chatstrip__last">{last}</span>}
    </button>
  );
}
