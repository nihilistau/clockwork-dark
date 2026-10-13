// @vitest-environment jsdom
// ui/tests/phone-games.test.jsx -- READ RECEIPTS' games (v0.22.0 T29, spec §18.2, §21): Tile Talk's board,
// rack and moves, This or That's five picks and its reveal, the Games app, the thread's game card opening
// the game screen, and the hidden-value scan (their rack, the bag, their picks before the reveal).
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import GamesHome from "../src/stories/read-receipts/games/GamesHome.jsx";
import ThisOrThat from "../src/stories/read-receipts/games/ThisOrThat.jsx";
import TileTalk from "../src/stories/read-receipts/games/TileTalk.jsx";
import { phoneFixture, plantHidden, tileGame as tileFixture, totGame } from "./fixtures/phone.js";
import { Harness, PID } from "./fixtures/phone-harness.jsx";
import { button, byTestId, click, key, mount } from "./helpers/dom.js";

let view;
beforeEach(() => { view = mount(); });
afterEach(() => view.unmount());

// Tap-to-place: the rack tile, then the board cell.
const place = (letter, x, y) => {
  click(view.host.querySelector(`[data-testid="rack-${letter}"]`));
  click(view.host.querySelector(`[data-testid="cell-${x}-${y}"]`));
};
const moves = (act) => act.mock.calls.map(([intent]) => intent).filter((i) => i.action === "game_move");

describe("Tile Talk", () => {
  it("places tiles and plays them as one game_move", () => {
    const act = vi.fn();
    view.render(<TileTalk game={tileFixture({ rack: ["c", "a", "t", "e", "r", "s", "o"].join("") })} act={act} />);
    place("c", 5, 5); place("a", 6, 5); place("t", 7, 5);
    click(button(view.host, "Play"));
    // The engine's verb names the move kind (engine/social/games/__init__.py: `move` is required).
    expect(act).toHaveBeenCalledWith({ action: "game_move", target: "g1", text: "",
      args: { move: "play", tiles: [{ x: 5, y: 5, letter: "c" }, { x: 6, y: 5, letter: "a" }, { x: 7, y: 5, letter: "t" }] } });
    expect(act).toHaveBeenCalledTimes(1);
  });

  it("draws the board and premiums from the payload, and sends no score of its own", () => {
    const board = Array.from({ length: 11 }, () => ".".repeat(11));
    board[5] = "....dOg....";
    view.render(<TileTalk game={tileFixture({ board, scores: { player: 14, them: 9 } })} act={vi.fn()} />);
    expect(view.host.querySelectorAll('[data-testid^="cell-"]')).toHaveLength(121);
    expect(byTestId(view.host, "cell-4-5").textContent).toBe("D");
    expect(byTestId(view.host, "cell-5-5").className).toContain("is-blank");
    expect(byTestId(view.host, "cell-0-0").textContent).toBe("3W");
    expect(byTestId(view.host, "cell-3-3").getAttribute("aria-label")).toBe("Row 4, column 4, triple letter");
    expect(byTestId(view.host, "tile-score").textContent).toBe("You 14 · Cole 9");
  });

  it("takes a placed tile back on a tap, refuses a filled square, and needs a placement to play", () => {
    const act = vi.fn();
    const board = Array.from({ length: 11 }, () => ".".repeat(11));
    board[5] = ".....x.....";
    view.render(<TileTalk game={tileFixture({ board })} act={act} />);
    expect(button(view.host, "Play").disabled).toBe(true);
    place("c", 5, 5);                                     // filled: nothing placed, the tile still picked
    expect(byTestId(view.host, "cell-5-5").textContent).toBe("X");
    click(byTestId(view.host, "cell-5-6"));
    expect(byTestId(view.host, "cell-5-6").className).toContain("is-new");
    click(byTestId(view.host, "cell-5-6"));                // back to the rack
    expect(byTestId(view.host, "cell-5-6").className).not.toContain("is-new");
    expect(button(view.host, "Play").disabled).toBe(true);
    place("c", 5, 6); place("a", 5, 7);
    click(button(view.host, "Recall"));
    expect(view.host.querySelectorAll(".rr-cell.is-new")).toHaveLength(0);
    expect(act).not.toHaveBeenCalled();
  });

  it("asks what a blank stands for and sends it as blank", () => {
    const act = vi.fn();
    view.render(<TileTalk game={tileFixture({ rack: "?at" })} act={act} />);
    place("blank", 5, 5); place("a", 6, 5); place("t", 7, 5);
    expect(button(view.host, "Play").disabled).toBe(true);
    const pick = view.host.querySelector(".rr-blank select");
    React.act(() => {
      pick.value = "c";
      pick.dispatchEvent(new window.Event("change", { bubbles: true }));
    });
    click(button(view.host, "Play"));
    expect(moves(act)[0].args.tiles[0]).toEqual({ x: 5, y: 5, letter: "c", blank: true });
  });

  it("passes, swaps the tiles picked, and resigns only after a confirm", () => {
    const act = vi.fn();
    view.render(<TileTalk game={tileFixture({ rack: "caterso" })} act={act} />);
    click(button(view.host, "Pass"));
    expect(moves(act)[0]).toEqual({ action: "game_move", target: "g1", text: "", args: { move: "pass" } });
    click(button(view.host, "Swap"));
    click(byTestId(view.host, "rack-c"));
    click(byTestId(view.host, "rack-o"));
    click(button(view.host, /^Swap 2/));
    expect(moves(act)[1].args).toEqual({ move: "swap", letters: "co" });
    click(button(view.host, "Cancel"));
    click(button(view.host, "Resign"));
    expect(moves(act)).toHaveLength(2);
    click(button(view.host, "Keep playing"));
    click(button(view.host, "Resign"));
    click(view.host.querySelector('[aria-label="Resign the game?"] .rr-btn--danger'));
    expect(moves(act)[2].args).toEqual({ move: "resign" });
  });

  it("on their turn nothing can be placed or played", () => {
    const act = vi.fn();
    view.render(<TileTalk game={tileFixture({ turn: "them" })} act={act} />);
    expect(view.host.textContent).toContain("Cole’s turn");
    expect(button(view.host, "Play").disabled).toBe(true);
    expect(button(view.host, "Pass").disabled).toBe(true);
    expect(byTestId(view.host, "rack-c").disabled).toBe(true);
    expect(byTestId(view.host, "cell-5-5").disabled).toBe(true);
  });

  it("a new board clears the placement; a refusal (the same board) keeps it", () => {
    const game = tileFixture();
    view.render(<TileTalk game={game} act={vi.fn()} />);
    place("c", 5, 5);
    view.render(<TileTalk game={{ ...game }} act={vi.fn()} />);
    expect(byTestId(view.host, "cell-5-5").className).toContain("is-new");
    const board = [...game.board];
    board[5] = ".....cat...";
    view.render(<TileTalk game={{ ...game, board, rack: "ersoqiu", turn: "them" }} act={vi.fn()} />);
    expect(view.host.querySelectorAll(".rr-cell.is-new")).toHaveLength(0);
  });

  it("links the chat in a strip", () => {
    const onOpenChat = vi.fn();
    const chat = phoneFixture().threads.find((t) => t.pid === PID);
    view.render(<TileTalk game={tileFixture()} act={vi.fn()} chat={chat} onOpenChat={onOpenChat} />);
    expect(byTestId(view.host, "chat-strip").textContent).toContain("Chat with Cole");
    click(byTestId(view.host, "chat-strip"));
    expect(onOpenChat).toHaveBeenCalledWith(`matchstick:${PID}`);
  });
});

describe("This or That", () => {
  it("answers This or That with five picks", () => {
    const act = vi.fn();
    view.render(<ThisOrThat game={totGame()} act={act} />);
    for (const side of ["a", "b", "a", "a"]) click(byTestId(view.host, `tot-${side}`));
    expect(act).not.toHaveBeenCalled();
    click(byTestId(view.host, "tot-b"));
    expect(act).toHaveBeenCalledTimes(1);
    expect(act).toHaveBeenCalledWith({ action: "game_move", target: "g2", text: "", args: { move: "answer", answers: ["a", "b", "a", "a", "b"] } });
  });

  it("can step back a pick before the fifth", () => {
    const act = vi.fn();
    view.render(<ThisOrThat game={totGame()} act={act} />);
    click(byTestId(view.host, "tot-a"));
    expect(view.host.textContent).toContain("2 of 5");
    click(button(view.host, "Back"));
    expect(view.host.textContent).toContain("1 of 5");
    for (let i = 0; i < 5; i += 1) click(byTestId(view.host, "tot-b"));
    expect(act.mock.calls[0][0].args.answers).toEqual(["b", "b", "b", "b", "b"]);
  });

  it("waits with your own picks only, then reveals both and the agreements", () => {
    // Before the reveal the payload sends `theirs: null`; planted anyway, nothing may draw it.
    const waiting = totGame({ mine: ["a", "a", "b", "a", "b"], theirs: ["zz-theirs-sentinel"], turn: "them" });
    view.render(<ThisOrThat game={waiting} act={vi.fn()} />);
    expect(view.host.textContent).toContain("Waiting for Cole’s answers.");
    expect(view.host.textContent).toContain("You: Mountains");
    expect(view.host.innerHTML).not.toContain("zz-theirs-sentinel");
    expect(view.host.textContent).not.toContain("Cole:");
    const done = totGame({ status: "finished", mine: ["a", "a", "b", "a", "b"], theirs: ["a", "b", "b", "b", "b"], agreements: 3 });
    view.render(<ThisOrThat game={done} act={vi.fn()} />);
    expect(byTestId(view.host, "tot-agree").textContent).toBe("You agree on 3 of 5");
    expect(view.host.textContent).toContain("You: Coffee · Cole: Tea");
    expect(view.host.querySelectorAll(".rr-tot__row.is-same")).toHaveLength(3);
  });
});

describe("the Games app and the thread's game card", () => {
  it("lists the games, opens one, and starts a new one with a contact", () => {
    const act = vi.fn();
    const onOpenGame = vi.fn();
    const phone = phoneFixture({ phone: { games: [tileFixture(), totGame({ id: "g0", status: "finished", mine: ["a"], theirs: ["a"], agreements: 4 })] } });
    view.render(<GamesHome phone={phone} act={act} onOpenGame={onOpenGame} />);
    expect(byTestId(view.host, "game-row-g1").textContent).toContain("Tile Talk with Cole");
    expect(byTestId(view.host, "game-row-g1").textContent).toContain("Your turn");
    expect(byTestId(view.host, "game-row-g0").textContent).toContain("You agree on 4 of 5");
    click(byTestId(view.host, "game-row-g1"));
    expect(onOpenGame).toHaveBeenCalledWith("g1");
    click(button(view.host, "This or That"));
    expect(act).toHaveBeenCalledWith({ action: "game_invite", target: PID, args: { game: "this_or_that" }, text: "" });
  });

  it("Play on the thread's game card opens the game screen, and Back returns to the thread", () => {
    const onAct = vi.fn(() => true);
    const phone = phoneFixture({ phone: { games: [tileFixture()] } });
    view.render(<Harness onAct={onAct} phone={phone} />);
    click(button(byTestId(view.host, "game-g1"), "Play"));
    expect(byTestId(view.host, "tiletalk-g1")).not.toBeNull();
    expect(document.activeElement.textContent).toBe("Tile Talk");
    place("c", 5, 5); place("a", 6, 5); place("t", 7, 5);
    click(button(view.host, "Play"));
    expect(onAct).toHaveBeenLastCalledWith({ action: "game_move", target: "g1", args: { move: "play", tiles: [
      { x: 5, y: 5, letter: "c" }, { x: 6, y: 5, letter: "a" }, { x: 7, y: 5, letter: "t" }] }, text: "" });
    click(button(view.host, "Back"));
    expect(view.host.querySelector(".rr-thread")).not.toBeNull();
  });

  it("the chat strip in a game opens the thread", () => {
    const onAct = vi.fn(() => true);
    const phone = phoneFixture({ phone: { games: [totGame()] } });
    view.render(<Harness onAct={onAct} phone={phone} />);
    click(button(byTestId(view.host, "game-g2"), "Play"));
    expect(byTestId(view.host, "thisorthat-g2")).not.toBeNull();
    click(byTestId(view.host, "chat-strip"));
    expect(onAct).toHaveBeenLastCalledWith({ action: "open_thread", target: `matchstick:${PID}`, args: {}, text: "" });
    expect(view.host.querySelector(".rr-thread")).not.toBeNull();
  });
});

describe("hidden values in the games (spec §17.3)", () => {
  const HIDDEN = { warmth: 7311, interest: 6911, racks: "zz-racks-sentinel", bag: "zz-bag-sentinel", picks: "zz-picks-sentinel",
    flake: "zz-flake-sentinel", quality: 0.4271 };
  const clean = () => {
    const html = view.host.innerHTML;
    for (const value of Object.values(HIDDEN)) expect(html).not.toContain(String(value));
    for (const name of Object.keys(HIDDEN)) expect(view.host.querySelector("[data-" + name + "], [" + name + "]")).toBeNull();
  };
  it("Tile Talk, This or That (before and after the reveal) and the Games app draw none", () => {
    const block = plantHidden(phoneFixture({ phone: { games: [tileFixture(), totGame(), totGame({ id: "g3", status: "finished",
      mine: ["a", "a", "a", "a", "a"], theirs: ["b", "a", "b", "a", "b"], agreements: 2 })] } }), HIDDEN);
    for (const game of block.games) {
      view.render(game.game === "wordgame" ? <TileTalk game={game} act={vi.fn()} /> : <ThisOrThat game={game} act={vi.fn()} />);
      clean();
    }
    view.render(<GamesHome phone={block} act={vi.fn()} onOpenGame={vi.fn()} />);
    clean();
  });
});

describe("Tile Talk by keyboard (review M3, M4)", () => {
  it("is plain buttons: type a rack letter on a square to place it, Backspace takes it back", () => {
    const act = vi.fn();
    view.render(<TileTalk game={tileFixture({ rack: "cat?" })} act={act} />);
    expect(view.host.querySelector('[role="grid"], [role="gridcell"], [role="row"]')).toBeNull();
    const cell = (x, y) => byTestId(view.host, `cell-${x}-${y}`);
    expect(cell(5, 5).tagName).toBe("BUTTON");
    expect(cell(5, 5).getAttribute("tabindex")).toBeNull();
    cell(5, 5).focus();
    key("c", cell(5, 5));
    key("a", cell(6, 5));
    key("t", cell(7, 5));
    key("s", cell(8, 5));                                         // no S on the rack: the blank, as S
    key("Backspace", cell(8, 5));
    key("s", cell(8, 5));
    click(button(view.host, "Play"));
    expect(act).toHaveBeenCalledWith({ action: "game_move", target: "g1", text: "", args: { move: "play", tiles: [
      { x: 5, y: 5, letter: "c" }, { x: 6, y: 5, letter: "a" }, { x: 7, y: 5, letter: "t" }, { x: 8, y: 5, letter: "s", blank: true }] } });
  });

  it("the Resign confirm is an alertdialog: focus on Keep playing, back to Resign, Escape keeps playing", () => {
    const act = vi.fn();
    view.render(<TileTalk game={tileFixture()} act={act} />);
    const resign = button(view.host, "Resign");
    resign.focus();
    click(resign);
    const dialog = view.host.querySelector('[role="alertdialog"]');
    expect(dialog.getAttribute("aria-label")).toBe("Resign the game?");
    expect(document.getElementById(dialog.getAttribute("aria-describedby")).textContent).toContain("counts as a loss");
    expect(document.activeElement.textContent).toBe("Keep playing");
    click(button(view.host, "Keep playing"));
    expect(document.activeElement).toBe(button(view.host, "Resign"));
    click(button(view.host, "Resign"));
    key("Escape", document.activeElement);
    expect(view.host.querySelector('[role="alertdialog"]')).toBeNull();
    expect(document.activeElement).toBe(button(view.host, "Resign"));
    expect(act).not.toHaveBeenCalled();
  });
});
