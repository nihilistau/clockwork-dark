// @vitest-environment jsdom
/**
 * Story surfaces name places, factions' traders and speakers -- never ids
 * (v0.21.0 final review, findings 4, 5 and 17).
 *
 * A plate caption read "gate of briars" (the location id, de-underscored),
 * the flagship's sheet "PLACE edgewood square", an epilogue echo "npc ilya".
 * Each now reads the payload's name (`location_name`, `speaker_name`), with
 * a readable id only when no name is carried.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@core/api.js", () => ({
  fetchItems: () => Promise.resolve({ items: [] }),
  fetchNotices: () => Promise.resolve({ notices: [], elsewhere: [] }),
  fetchPlaces: () => Promise.resolve({ places: [] }),
}));

import gardenPlugin from "../src/stories/wicked-garden/index.jsx";
import neonPlugin from "../src/stories/neon-city/index.jsx";
import SceneVisual from "../src/stories/clockwork-dark/parts/SceneVisual.jsx";
import Sheet from "../src/stories/clockwork-dark/parts/Sheet.jsx";
import EpilogueCard from "../src/stories/wicked-garden/parts/EpilogueCard.jsx";
import { sentenceCase } from "../src/stories/clockwork-dark/parts/Inventory.jsx";
import { tabLabel } from "../src/stories/clockwork-dark/screens/Trade.jsx";

const SNAKE = /\b[a-z0-9]+(?:_[a-z0-9]+)+\b/;

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

const draw = (node) => React.act(() => root.render(node));
const shown = () => `${host.textContent} ${[...host.querySelectorAll("[alt]")].map((n) => n.getAttribute("alt")).join(" ")}`;

describe("places are named, not id'd (finding 4)", () => {
  it("the Wicked Garden's plate caption", () => {
    const Stage = gardenPlugin.Stage;
    draw(<Stage state={{ sceneImage: "", world: { location_id: "gate_of_briars", location_name: "The Gate of Briars" } }} />);
    expect(shown()).toContain("The Gate of Briars");
    expect(shown()).not.toMatch(/gate of briars|gate_of_briars/);
  });

  it("NEON CITY's plate caption", () => {
    const Stage = neonPlugin.Stage;
    draw(<Stage state={{ sceneImage: "", choices: [], world: { location_id: "the_grid_market", location_name: "The Grid Market" } }} />);
    expect(shown()).toContain("THE GRID MARKET");
    expect(shown()).not.toMatch(SNAKE);
  });

  it("the flagship's scene visual, caption and alt", () => {
    draw(
      <SceneVisual
        world={{ location_id: "edgewood_square", location_name: "Edgewood Square", time_of_day: "day" }}
        imageUrl="/x.jpg"
        phase="dormant"
      />
    );
    expect(shown()).toContain("Edgewood Square");
    expect(shown()).not.toMatch(/edgewood square|edgewood_square/);
  });

  it("the flagship's sheet place line", () => {
    draw(<Sheet world={{ location_id: "edgewood_square", location_name: "Edgewood Square", stats: {}, inventory: [] }} />);
    expect(host.textContent).toContain("Edgewood Square");
    expect(host.textContent).not.toMatch(/edgewood square/);
  });
});

describe("speakers and strangers (findings 5, 17)", () => {
  it("an epilogue echo is shown under the engine's speaker name", () => {
    draw(<EpilogueCard ending_id="e2b_the_door" title="The Door" echoes={[{ speaker: "npc_ilya", speaker_name: "Ilya", text: "Go." }]} />);
    expect(host.textContent).toContain("Ilya");
    expect(host.innerHTML).not.toMatch(/npc.ilya|aria-label="e2b/);
  });

  it("a vendor opening a sentence is capitalised, and same-named traders are numbered", () => {
    expect(sentenceCase("the baker")).toBe("The baker");
    const vendors = [{ name: "the baker" }, { name: "Maris" }, { name: "the baker" }];
    expect([0, 1, 2].map((i) => tabLabel(vendors, i))).toEqual(["the baker (1)", "Maris", "the baker (2)"]);
  });
});
