// @vitest-environment jsdom
/**
 * The play screen's main column is named areas, not child positions (F1).
 *
 * Until v0.21.0 the column gave its FIRST two children the flexible rows,
 * whatever they were: on the engine's skin the log took the picture's row and
 * the casing board took the log's, and painted over the choices. Every area
 * now has a fixed wrapper, in a fixed order, placed by name.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/core/parts/MicButton.jsx", () => ({ default: () => null }));

import Play from "../src/core/screens/Play.jsx";
import { initialState } from "../src/core/store.js";

const WORLD = { location_id: "tallow_docks", location_name: "Tallow Docks", world_day: 1, time_of_day: "day" };

const playState = (over = {}) => ({
  ...initialState,
  screen: "scene",
  sessionId: "s1",
  link: "live",
  world: WORLD,
  log: [{ id: "e1", kind: "narration", text: "The quay is loud." }],
  choices: [{ id: "a", text: "Wait" }],
  ...over,
});

const story = (over = {}) => ({ slug: "probe", title: "Probe", overlays: [], onboarding: [], ...over });

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

function draw(state, plugin) {
  const noop = () => {};
  React.act(() =>
    root.render(
      <Play
        state={state}
        story={plugin}
        onChoose={noop}
        onCustom={noop}
        onRetry={noop}
        onOpenSaves={noop}
        onOpenSettings={noop}
        onOpenOverlay={noop}
        onOpenMenu={noop}
        onToggleReasoning={noop}
        composeRef={{ current: null }}
      />
    )
  );
}

const column = () => host.querySelector(".scene__col--main");
// The log's screen-reader courier (`p.visually-hidden[aria-live]`) is a
// deliberate SIBLING of `.log` (narrative-log.test.jsx says why). It is
// `position: absolute`, so it is no grid item and takes no track; it is not
// an area, and is left out of the list.
const areas = () =>
  [...column().children]
    .filter((el) => !el.classList.contains("visually-hidden"))
    .map((el) => el.classList[0]);

describe("the main column", () => {
  it("renders every area wrapper, in order, whatever renders inside", () => {
    draw(playState(), story());
    expect(areas()).toEqual(["stage-area", "log", "think-area", "shelf", "choices-area", "compose", "toast-area"]);
  });

  it("puts a live deck's line in its own area between the stage and the log", () => {
    draw(playState({ world: { ...WORLD, scene: { deck_id: "prologue", count: 2, cursor: 0 } } }), story());
    expect(areas()).toEqual(["stage-area", "beatframe", "log", "think-area", "shelf", "choices-area", "compose", "toast-area"]);
  });

  it("a dealt card's header shows its title, never the deck id (final review 2)", () => {
    const scene = { deck_id: "day_00_prologue", count: 10, cursor: 2, card_title: "The Threshold Slips" };
    draw(playState({ world: { ...WORLD, scene } }), story());
    const frame = host.querySelector(".beatframe");
    expect(frame.textContent).toContain("Card 3 of 10");
    expect(frame.textContent).toContain("The Threshold Slips");
    expect(frame.textContent).not.toMatch(/day.00|prologue/i);
    draw(playState({ world: { ...WORLD, scene: { ...scene, card_title: "" } } }), story());
    expect(host.querySelector(".beatframe").textContent).toBe("Card 3 of 10");
  });

  it("a challenge with no title shows no id (final review 2)", () => {
    const challenge = { id: "the_locked_gate", step: 0, total_steps: 3 };
    draw(playState({ world: { ...WORLD, challenge } }), story());
    expect(host.querySelector(".beatframe").textContent).toBe("Step 1 of 3");
  });

  it("an empty optional area renders no children", () => {
    draw(playState(), story());
    for (const name of ["think-area", "shelf"]) {
      expect(host.querySelector(`.${name}`).childElementCount).toBe(0);
    }
  });

  it("a plugin Stage turns the stage on", () => {
    const Stage = () => <div className="probe-stage" />;
    draw(playState(), story({ Stage }));
    expect(column().dataset.stage).toBe("on");
    expect(host.querySelector(".stage-area .probe-stage")).not.toBeNull();
  });

  it("defaultStage gives core's scene plate, captioned with the place", () => {
    draw(playState({ sceneImage: "/api/media/images/x.svg" }), story({ defaultStage: true }));
    expect(column().dataset.stage).toBe("on");
    const img = host.querySelector(".stage-area .sceneplate img");
    expect(img.getAttribute("src")).toBe("/api/media/images/x.svg");
    expect(img.getAttribute("alt")).toBe("Tallow Docks");
  });

  it("the plate with no image shows the place name", () => {
    draw(playState(), story({ defaultStage: true }));
    expect(host.querySelector(".sceneplate").textContent).toContain("Tallow Docks");
  });

  it("a plugin with neither keeps the stage off (THE LONG CON's shape)", () => {
    draw(playState(), story({ Ledger: () => null }));
    expect(column().dataset.stage).toBe("off");
    expect(host.querySelector(".sceneplate")).toBeNull();
    expect(host.querySelector(".stage-area").childElementCount).toBe(0);
  });
});
