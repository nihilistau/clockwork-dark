// @vitest-environment jsdom
import React from "react";
import { createRoot } from "react-dom/client";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RollCard, { ROLL_CARD_MS } from "../src/core/panels/RollCard.jsx";
import { resolvePanels } from "../src/core/panels/resolve.js";
import { initialState, reducer } from "../src/core/store.js";

const DICE = {
  skill: "stealth", difficulty: "standard", natural: 14,
  modifiers: [{ label: "night", delta: 2 }, { label: "wounded", delta: -1 }],
  total: 15, dc: 12, degree: "success", success: true, summary: "", boon: "", complication: "",
  at: 1,
};

let host;
let root;
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  React.act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});
const draw = (dice, showDiceBreakdown = true) =>
  React.act(() => root.render(<RollCard state={{ dice }} showDiceBreakdown={showDiceBreakdown} />));

describe("the roll card", () => {
  it("says the roll as the receipt for the move: skill, die, total against the bar, degree", () => {
    draw({ ...DICE });
    const card = host.querySelector(".rollcard");
    expect(card.textContent).toContain("stealth · standard");
    expect(card.textContent).toContain("d20 14");
    expect(card.textContent).toContain("= 15 vs 12");
    expect(card.querySelector(".rollcard__degree").textContent).toBe("Success");
    expect(host.querySelector('[role="status"]')).not.toBeNull();
  });

  it("shows the modifiers only with the breakdown preference on", () => {
    draw({ ...DICE }, true);
    expect(host.textContent).toContain("night +2");
    expect(host.textContent).toContain("wounded -1");
    draw({ ...DICE, at: 2 }, false);
    expect(host.textContent).not.toContain("night");
  });

  it("goes after six seconds, and at once when the next turn is submitted", () => {
    draw({ ...DICE });
    React.act(() => vi.advanceTimersByTime(ROLL_CARD_MS + 1));
    expect(host.querySelector(".rollcard")).toBeNull();
    const submitted = reducer({ ...initialState, dice: DICE }, { type: "SUBMIT", text: "go" });
    expect(submitted.dice).toBeNull();
    draw(submitted.dice);
    expect(host.querySelector(".rollcard")).toBeNull();
  });

  it("is suppressed for a plugin that draws rolls itself", () => {
    expect(resolvePanels({ ownsPanels: ["rolls"] }).toast).toEqual([]);
  });

  it("is drawn in the toast layer by default, as the registry's `rolls` component", () => {
    const toast = resolvePanels({}).toast;
    expect(toast.map((panel) => panel.id)).toEqual(["rolls"]);
    expect(toast[0].Component).toBe(RollCard);
  });

  it("keeps an empty live region between rolls, so the next one is announced", () => {
    draw(null);
    const live = host.querySelector('[role="status"]');
    expect(live).not.toBeNull();
    expect(live.getAttribute("aria-live")).toBe("polite");
    expect(live.textContent).toBe("");
  });

  it("shows a roll once: a remount with the same roll still in the store draws nothing", () => {
    const dice = { ...DICE, at: 4 };
    draw(dice);
    expect(host.querySelector(".rollcard")).not.toBeNull();
    React.act(() => root.unmount());
    root = createRoot(host);
    draw(dice);
    expect(host.querySelector(".rollcard")).toBeNull();
    // ...and the next roll, a new object from the reducer, is shown.
    draw({ ...DICE, at: 5 });
    expect(host.querySelector(".rollcard")).not.toBeNull();
  });

  it("takes no pointer events, so it never swallows a tap", () => {
    const css = readFileSync(resolve(process.cwd(), "src", "styles", "index.css"), "utf8").replace(/\r\n/g, "\n");
    const rule = (selector) => {
      const at = css.indexOf(`\n${selector} {`);
      return at < 0 ? "" : css.slice(at, css.indexOf("}", at));
    };
    expect(rule(".rollcard")).toMatch(/pointer-events: none/);
    expect(rule(".rollcard-live")).toMatch(/pointer-events: none/);
    expect(rule(".toast-area")).toMatch(/pointer-events: none/);
    // Over the stage and log rows only: never the shelf, choices or compose.
    expect(rule(".toast-area")).toMatch(/grid-row: stage-start \/ log-end/);
  });

  it("says a two-word degree in words, from the degree table (final review 5)", () => {
    draw({ ...DICE, degree: "crit_success", at: 3 });
    expect(host.querySelector(".rollcard__degree").textContent).toBe("Critical success");
    draw({ ...DICE, degree: "crit_failure", at: 4 });
    expect(host.querySelector(".rollcard__degree").textContent).toBe("Critical failure");
    draw({ ...DICE, degree: "a_new_degree", at: 5 });
    expect(host.querySelector(".rollcard__degree").textContent).toBe("A new degree");
  });
});
