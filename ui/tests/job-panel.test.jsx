// @vitest-environment jsdom
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import JobPanel from "../src/core/panels/JobPanel.jsx";

const SCALES = { prep: ["none", "a little", "some", "plenty"], alarm: ["quiet", "uneasy", "stirring", "restless", "roused", "raised"] };
const ACTIVE = { premise_name: "the Harrowgate townhouse", stage_label: "inside, at the strongbox", stages: ["at the door", "inside, at the strongbox", "away"], at: 1, alarm: "uneasy" };

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
const draw = (job, narrow = false) => React.act(() => root.render(<JobPanel state={{ world: { job } }} narrow={narrow} />));

describe("the job panel", () => {
  it("renders nothing between jobs", () => {
    draw({ active: null, prep: "a little", scales: SCALES });
    expect(host.innerHTML).toBe("");
  });

  it("heads itself with the house and marks the current stage (0-based `at`)", () => {
    draw({ active: ACTIVE, prep: "a little", scales: SCALES });
    expect(host.querySelector("h2").textContent).toContain("The job — the Harrowgate townhouse");
    const steps = [...host.querySelectorAll("ol li")];
    expect(steps.map((li) => li.getAttribute("aria-current"))).toEqual([null, "step", null]);
    expect(steps[0].className).toContain("is-done");
    expect(steps[1].textContent).toBe("inside, at the strongbox");
  });

  it("says the alarm and prep in words, lighting marks to their place", () => {
    draw({ active: ACTIVE, prep: "some", scales: SCALES });
    expect(host.querySelector(".job__alarm").textContent).toContain("uneasy");
    expect(host.querySelectorAll(".job__alarm .is-lit")).toHaveLength(1);
    expect(host.querySelectorAll(".job__prep .is-lit")).toHaveLength(2);
  });

  it("draws 'raised' in the danger token", () => {
    draw({ active: { ...ACTIVE, alarm: "raised" }, prep: "none", scales: SCALES });
    expect(host.querySelector(".job__alarm").className).toContain("is-danger");
  });

  it("prints no figure, percentage or width for a veiled band (the veiled rule)", () => {
    for (const alarm of SCALES.alarm) {
      for (const prep of SCALES.prep) {
        draw({ active: { ...ACTIVE, alarm }, prep, scales: SCALES });
        expect(host.textContent).not.toMatch(/\d/);
        expect(host.innerHTML).not.toContain("%");
        expect(host.innerHTML).not.toMatch(/width|aria-valuenow/);
      }
    }
  });

  it("lights nothing for a word not in its scale, and never calls it raised", () => {
    draw({ active: { ...ACTIVE, alarm: "" }, prep: "nonsense", scales: SCALES });
    expect(host.querySelectorAll(".is-lit")).toHaveLength(0);
    expect(host.querySelector(".job__alarm").className).not.toContain("is-danger");
  });

  it("is the registry's `job` component", async () => {
    const { PANELS } = await import("../src/core/panels/registry.js");
    expect(PANELS.find((panel) => panel.id === "job").Component).toBe(JobPanel);
  });

  it("opens collapsed on a narrow screen", () => {
    draw({ active: ACTIVE, prep: "none", scales: SCALES }, true);
    expect(host.querySelector("h2 button").getAttribute("aria-expanded")).toBe("false");
  });

  it("opens collapsed on a short window, expanded on a tall one (final review 19, K2)", () => {
    const real = window.matchMedia;
    try {
      window.matchMedia = (q) => ({ matches: q.includes("max-height"), addEventListener() {}, removeEventListener() {} });
      draw({ active: ACTIVE, prep: "none", scales: SCALES });
      expect(host.querySelector("h2 button").getAttribute("aria-expanded")).toBe("false");
      React.act(() => root.unmount());
      root = createRoot(host);
      window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
      draw({ active: ACTIVE, prep: "none", scales: SCALES });
      expect(host.querySelector("h2 button").getAttribute("aria-expanded")).toBe("true");
    } finally {
      window.matchMedia = real;
    }
  });
});
