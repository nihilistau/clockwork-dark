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

import CasingBoard from "../src/core/panels/CasingBoard.jsx";

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

describe("the casing board, v0.21.0 (spec §4.3)", () => {
  const EMPTY = { ...HOUSE, id: "prem_2", name: "the mill house", empty_now: true, known: ["a back gate"] };

  it("is a section labelled by an h2 (F11)", () => {
    draw([HOUSE]);
    const section = host.querySelector("section");
    const heading = host.querySelector("h2");
    expect(heading).not.toBeNull();
    expect(section.getAttribute("aria-labelledby")).toBe(heading.id);
  });

  it("heads itself with the counts, and prep only when the job block is there", () => {
    // `toContain`, not `toBe`: the board is a collapsible panel (spec §2.5),
    // so its h2 holds the disclosure button and its chevron too.
    draw([HOUSE, EMPTY]);
    expect(host.querySelector("h2").textContent).toContain("Casing — 2 houses here · 1 empty now");
    expect(host.querySelector("h2").textContent).not.toContain("Prep");
    React.act(() => root.render(<CasingBoard premises={[HOUSE]} prep="a little" />));
    expect(host.querySelector("h2").textContent).toContain("Casing — 1 house here · Prep: a little");
    expect(host.querySelector("h2 button[aria-expanded='true']")).not.toBeNull();
  });

  it("opens a house that is empty now and keeps the others closed", () => {
    draw([HOUSE, EMPTY]);
    const [closed, open] = host.querySelectorAll(".casing__head");
    expect(closed.getAttribute("aria-expanded")).toBe("false");
    expect(open.getAttribute("aria-expanded")).toBe("true");
    expect(document.getElementById(closed.getAttribute("aria-controls")).hidden).toBe(true);
    React.act(() => closed.click());
    expect(closed.getAttribute("aria-expanded")).toBe("true");
    expect(document.getElementById(closed.getAttribute("aria-controls")).hidden).toBe(false);
  });
});

describe("final fix wave (T7 reviews 2, 6, 8)", () => {
  it("opens a row when its house empties later, and only on that edge", () => {
    draw([HOUSE]);
    const body = () => host.querySelector(".casing__known");
    expect(body().hidden).toBe(true);
    draw([{ ...HOUSE, empty_now: true }]);
    expect(body().hidden).toBe(false);
    // Closed by the player while it stays empty: stays closed.
    React.act(() => host.querySelector(".casing__head").click());
    expect(body().hidden).toBe(true);
    draw([{ ...HOUSE, empty_now: true, known: [...HOUSE.known] }]);
    expect(body().hidden).toBe(true);
  });

  it("an opened house with nothing learned says so", () => {
    draw([{ ...HOUSE, known: [], empty_now: true }]);
    expect(host.querySelector(".casing__known").textContent).toBe("Nothing learned yet.");
  });

  it("the registry's casing and negotiation adapters render from a store-shaped state", async () => {
    const { PANELS } = await import("../src/core/panels/registry.js");
    const Casing = PANELS.find((panel) => panel.id === "casing").Component;
    React.act(() =>
      root.render(<Casing state={{ premises: [HOUSE], world: { job: { prep: "good" } } }} region="ledger" />)
    );
    expect(host.textContent).toContain("Prep: good");
    expect(host.textContent).toContain("the Harrowgate townhouse");

    const Negotiation = PANELS.find((panel) => panel.id === "negotiation").Component;
    const negotiation = { ran: true, lead: "gm", resolutions: [], beats: [] };
    React.act(() => root.render(<Negotiation state={{ negotiation }} region="shelf" />));
    expect(host.textContent).toMatch(/gm led, uncontested/);
    const toggle = host.querySelector(".negotiation__toggle");
    expect(toggle.getAttribute("aria-controls")).toBe(host.querySelector(".negotiation__body").id);
    expect(host.querySelector(".negotiation__body").hidden).toBe(true);
  });
});
