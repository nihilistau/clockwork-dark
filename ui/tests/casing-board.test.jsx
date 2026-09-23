// @vitest-environment jsdom
/**
 * The casing board: houses in the player's district, and what watching them
 * has told the player so far.
 *
 * `state.premises` has ridden the turn payload since
 * `GameState._premises_block` shipped (engine/game/state.py), mirrored onto
 * the store by `premisesOf` exactly as `metersOf` mirrors `world.meters`. This
 * is the first and only reader in `ui/src/`.
 *
 * Shape, per row: {id, name, type_label, known, of, empty_now}. `known` is
 * TEXTS already learned, in learning order -- never an id, and never a line
 * nobody has watched for yet.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import CasingBoard from "../src/core/parts/CasingBoard.jsx";

const HOUSE = {
  id: "prem_edgewood_square_1",
  name: "the Harrowgate townhouse",
  type_label: "townhouse",
  known: ["never empty", "a good lock on the street door"],
  of: 4,
  empty_now: false,
};

let host;
let root;

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  React.act(() => root.unmount());
  host.remove();
});

function draw(premises) {
  React.act(() => root.render(<CasingBoard premises={premises} />));
}

describe("the casing board", () => {
  it("renders nothing for a story that declares no premises", () => {
    draw(null);
    expect(host.innerHTML).toBe("");

    draw([]);
    expect(host.innerHTML).toBe("");
  });

  it("renders a house's name, type and known intel", () => {
    draw([HOUSE]);
    expect(host.textContent).toMatch(/the Harrowgate townhouse/);
    expect(host.textContent).toMatch(/townhouse/);
    expect(host.textContent).toMatch(/never empty/);
    expect(host.textContent).toMatch(/a good lock on the street door/);
    expect(host.textContent).toMatch(/2 of 4 known/);
  });

  it("never prints a premise id, only the texts a watch has already learned", () => {
    draw([HOUSE]);
    expect(host.textContent).not.toMatch(/prem_/);
    // The unlearned lines -- loot, the secret's existence -- must not leak
    // in ahead of a watch that has not happened.
    expect(host.textContent).not.toMatch(/worth it/);
    expect(host.textContent).not.toMatch(/hiding something/);
  });

  it("marks a house that is empty right now", () => {
    draw([{ ...HOUSE, empty_now: true }]);
    expect(host.textContent).toMatch(/empty now/i);
  });

  it("does not mark a house that currently holds someone", () => {
    draw([{ ...HOUSE, empty_now: false }]);
    expect(host.textContent).not.toMatch(/empty now/i);
  });

  it("renders one entry per house, in the order the payload gives them", () => {
    const second = { ...HOUSE, id: "prem_edgewood_square_2", name: "the mill house", known: [] };
    draw([HOUSE, second]);
    const names = host.textContent;
    expect(names.indexOf("Harrowgate")).toBeLessThan(names.indexOf("mill house"));
    expect(names).toMatch(/0 of 4 known/);
  });
});
