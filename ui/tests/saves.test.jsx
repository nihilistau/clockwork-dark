// @vitest-environment jsdom
/**
 * The save browser (v0.21.0, spec §8.1, F7).
 *
 * Core printed the flagship's "the pattern is quiet" on every story's saves,
 * an archetype id and a prettified place id. The phrase is the flagship
 * plugin's `saveMeta` now, names come from the archetype and place lookups,
 * and a story's declared save columns (`values`) render -- a veiled one as
 * its band word, never a number.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Saves from "../src/core/screens/Saves.jsx";
import flagship from "../src/stories/clockwork-dark/index.jsx";

const HUE = { save_id: "a1", player_name: "Wren", archetype: "cutpurse", world_day: 2, location_id: "tallow_docks", evil_phase: "dormant", turn_number: 4, updated_at: 0 };
const NEON = { ...HUE, save_id: "b2", archetype: "", location_id: "the_grid", values: { credits: { label: "Credits", value: 120 }, timestamp: { label: "The file", band: "faint" } } };

let host;
let root;
let answers;
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  answers = {
    "/api/archetypes": { archetypes: [{ id: "cutpurse", name: "Cutpurse" }] },
    "/api/codex/places": { places: [{ id: "tallow_docks", name: "Tallow Docks" }] },
  };
  globalThis.fetch = vi.fn(async (url) => {
    const body = answers[String(url).split("?")[0]];
    return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 404, json: async () => ({}) };
  });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  React.act(() => root.unmount());
  host.remove();
});

async function draw(saves, story = {}) {
  const noop = () => {};
  await React.act(async () => root.render(<Saves saves={saves} error="" story={story} onLoad={noop} onDelete={noop} onClose={noop} onNew={noop} />));
}

const text = () => document.body.textContent;

describe("the save browser (F7)", () => {
  it("prints no 'pattern' without a saveMeta", async () => {
    await draw([HUE]);
    expect(text()).not.toMatch(/pattern/);
  });

  it("the flagship's own line comes from its plugin", async () => {
    await draw([HUE], flagship);
    expect(text()).toContain("the pattern is quiet");
  });

  it("names the place and the archetype", async () => {
    await draw([HUE]);
    expect(text()).toContain("Cutpurse");
    expect(text()).toContain("Tallow Docks");
    expect(text()).not.toContain("tallow_docks");
  });

  it("falls back when the lookups fail", async () => {
    answers = {};
    await draw([HUE]);
    expect(text()).toContain("cutpurse");
    expect(text()).toContain("tallow docks");
  });

  it("renders the story's declared columns, a veiled one as a word", async () => {
    await draw([NEON]);
    expect(text()).toContain("Credits 120");
    expect(text()).toContain("The file: faint");
  });
});
