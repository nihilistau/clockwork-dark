// @vitest-environment jsdom
/**
 * The wanted poster (v0.21.0, spec §4.1).
 *
 * `world.law` from `GameState._law_block`: the face worn, its band per
 * jurisdiction, how clearly the watch HERE knows it, custody, and `scales`
 * -- the order of those words, low to high. The order lights marks and picks
 * a sketch layer; no number is ever printed (the veiled rule).
 */
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import WantedPoster, { WantedChip, sketchLayers, worstBand } from "../src/core/panels/WantedPoster.jsx";

const SCALES = {
  wanted: ["unknown", "noticed", "sought", "wanted", "hunted"],
  clarity: ["nothing", "a rumour", "a description", "a likeness"],
};

const LAW = {
  guise_label: "the Magpie's mask",
  wanted: { "the Quay": "sought", "the Wick wards": "unknown", "up the Rise": "noticed" },
  clarity: "a description",
  custody: null,
  scales: SCALES,
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

const stateWith = (law) => ({ world: law === undefined ? {} : { law } });
const poster = (law) => React.act(() => root.render(<WantedPoster state={stateWith(law)} />));
const chip = (law, onOpenSheet = () => {}) =>
  React.act(() => root.render(<WantedChip state={stateWith(law)} onOpenSheet={onOpenSheet} />));

describe("the poster", () => {
  it("renders nothing without a law block", () => {
    poster(undefined);
    expect(host.innerHTML).toBe("");
  });

  it("is a section labelled by its h2, and names the face worn", () => {
    poster(LAW);
    const heading = host.querySelector("h2");
    expect(heading.querySelector(".panel__label").textContent).toBe("Wanted");
    expect(host.querySelector("section").getAttribute("aria-labelledby")).toBe(heading.id);
    expect(host.textContent).toContain("the Magpie's mask");
  });

  it("lists every jurisdiction's word, lighting marks to its place in the scale", () => {
    poster(LAW);
    const rows = [...host.querySelectorAll(".poster__band")];
    expect(rows.map((row) => row.querySelector(".poster__where").textContent)).toEqual(["the Quay", "the Wick wards", "up the Rise"]);
    const lit = rows.map((row) => row.querySelectorAll(".marks__mark.is-lit").length);
    expect(lit).toEqual([2, 0, 1]);
    for (const row of rows) expect(row.querySelectorAll(".marks__mark")).toHaveLength(4);
  });

  it("an out-of-scale or empty band lights nothing and is never the worst", () => {
    poster({ ...LAW, wanted: { here: "", there: "beloved" } });
    const lit = [...host.querySelectorAll(".poster__band")].map((row) => row.querySelectorAll(".is-lit").length);
    expect(lit).toEqual([0, 0]);
    expect(worstBand({ ...LAW, wanted: { here: "", there: "beloved" } }).index).toBe(-1);
  });

  it("draws the sketch's layers from the clarity word's place", () => {
    for (const [word, layers] of [["nothing", 1], ["a rumour", 2], ["a description", 3], ["a likeness", 4]]) {
      poster({ ...LAW, clarity: word });
      expect(host.querySelectorAll(".sketch__layer")).toHaveLength(layers);
      expect(host.querySelector(".sketch").getAttribute("aria-label")).toBe(`The watch here has ${word} of the Magpie's mask`);
    }
  });

  it("scales the layers for three words and for four", () => {
    expect([0, 1, 2].map((i) => sketchLayers(i, 3))).toEqual([1, 3, 4]);
    expect([0, 1, 2, 3].map((i) => sketchLayers(i, 4))).toEqual([1, 2, 3, 4]);
    expect(sketchLayers(-1, 4)).toBe(1);
  });

  it("prints no digit except inside the fine", () => {
    poster({ ...LAW, custody: { fine: 12, fine_text: "12 crowns", days: 2 } });
    const text = host.textContent.replace("12 crowns", "");
    expect(text).not.toMatch(/\d/);
  });

  it("stamps a held thief with both ways out", () => {
    poster({ ...LAW, custody: { fine: 12, fine_text: "12 crowns", days: 2 } });
    expect(host.querySelector(".poster__stamp").textContent).toBe("Held");
    expect(host.textContent).toContain("A fine of 12 crowns, or two days");
  });
});

describe("the poster, further", () => {
  it("a held thief with no days to serve is offered the fine alone", () => {
    poster({ ...LAW, custody: { fine: 5, fine_text: "5 crowns", days: 0 } });
    expect(host.querySelector(".poster__custody").textContent).toBe("Held A fine of 5 crowns");
  });

  it("says the clarity word once to a screen reader: the sketch's label has it", () => {
    poster(LAW);
    expect(host.querySelector(".poster__clarity").getAttribute("aria-hidden")).toBe("true");
  });
});

describe("the chip", () => {
  it("is hidden while nobody is looking for anyone", () => {
    chip({ ...LAW, wanted: { a: "unknown", b: "unknown" }, clarity: "nothing" });
    expect(host.innerHTML).toBe("");
  });

  it("shows the worst band and the clarity word, as a button that opens the poster", () => {
    const open = vi.fn();
    chip(LAW, open);
    const button = host.querySelector("button");
    expect(button.textContent).toBe("the Quay: sought · a description");
    expect(button.getAttribute("aria-label")).toBe(
      "Wanted: sought at worst, the Quay; the watch here has a description of the Magpie's mask. Show the poster."
    );
    React.act(() => button.click());
    expect(open).toHaveBeenCalledWith("wanted");
  });

  it("shows clarity alone above its floor even with every band unknown", () => {
    chip({ ...LAW, wanted: { a: "unknown" }, clarity: "a rumour" });
    expect(host.querySelector("button").textContent).toBe("unknown · a rumour");
  });
});

describe("the chip, further", () => {
  it("is two spans, so a narrow screen can keep the band alone", () => {
    chip(LAW);
    expect(host.querySelector(".chip__where").textContent).toBe("the Quay: ");
    expect(host.querySelector(".chip__band").textContent).toBe("sought");
    expect(host.querySelector(".chip__rest").textContent).toBe(" · a description");
  });

  it("with every band the empty string and a clarity above its floor, names the scale's lowest word", () => {
    chip({ ...LAW, wanted: { a: "", b: "" }, clarity: "a rumour" });
    expect(host.querySelector("button").textContent).toBe("unknown · a rumour");
  });
});

describe("the chip's words (T8 review R1-3, R1-4)", () => {
  const text = () => host.querySelector("button").textContent;

  it("names where the worst band is, and leaves out a clarity at its floor", () => {
    chip({ ...LAW, wanted: { "the Quay": "wanted", "the Wick wards": "unknown" }, clarity: "nothing" });
    expect(text()).toBe("the Quay: wanted");
    expect(host.querySelector(".chip__rest")).toBeNull();
    expect(host.querySelector("button").getAttribute("aria-label")).toBe("Wanted: wanted at worst, the Quay. Show the poster.");
  });

  it("with every band at its floor it names no place, only the clarity above its floor", () => {
    chip({ ...LAW, wanted: { a: "unknown" }, clarity: "a rumour" });
    expect(host.querySelector(".chip__where")).toBeNull();
  });

  it("worstBand carries the jurisdiction's own label", () => {
    expect(worstBand(LAW).where).toBe("the Quay");
    expect(worstBand({ ...LAW, wanted: {} }).where).toBe("");
  });

  it("shows core's word Held while custody is set, even with every band at its floor", () => {
    const custody = { fine: 3, fine_text: "3 cr", days: 1 };
    chip({ ...LAW, wanted: { a: "unknown" }, clarity: "nothing", custody });
    expect(text()).toBe("Held");
    expect(host.querySelector("button").getAttribute("aria-label")).toBe("Held. Show the poster.");
  });

  it("beside a band above its floor, Held leads it", () => {
    chip({ ...LAW, clarity: "nothing", custody: { fine: 3, fine_text: "3 cr", days: 1 } });
    expect(text()).toBe("Held · the Quay: sought");
  });
});
