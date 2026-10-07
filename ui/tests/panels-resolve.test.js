/**
 * Which engine panels a story draws, and where (v0.21.0, spec §2).
 *
 * Omitted declaration: the data-gated panels in their default regions.
 * Declared: exactly the listed panels, in order. Minus whatever the plugin
 * draws itself (`ownsPanels`). Resolution is by id; a panel whose component
 * is not built yet is resolved and simply never rendered.
 */
import { describe, expect, it } from "vitest";

import { PANELS, REGIONS } from "../src/core/panels/registry.js";
import { resolvePanels } from "../src/core/panels/resolve.js";

const ids = (regions) => Object.fromEntries(REGIONS.map((r) => [r, regions[r].map((p) => p.id)]));

describe("the registry", () => {
  it("holds the spec's seven panels, in order", () => {
    expect(PANELS.map((p) => [p.id, p.region, p.regions, p.gate])).toEqual([
      ["wanted", "ledger", ["ledger", "shelf"], "data"],
      ["job", "shelf", ["shelf", "ledger"], "data"],
      ["casing", "ledger", ["ledger", "shelf"], "data"],
      ["negotiation", "shelf", ["shelf"], "data"],
      ["rolls", "toast", ["toast"], "data"],
      ["people", "stage", ["stage", "ledger"], "declared"],
      ["encounter", "shelf", ["shelf"], "declared"],
    ]);
  });
});

describe("resolvePanels", () => {
  it("omitted: every data-gated panel in its default region, no opt-in panel", () => {
    expect(ids(resolvePanels({}))).toEqual({
      header: ["wanted-chip"],
      stage: [],
      shelf: ["job", "negotiation"],
      ledger: ["wanted", "casing"],
      toast: ["rolls"],
    });
  });

  it("declared: exactly the listed panels, in the listed order, in their regions", () => {
    const story = { panelDeclaration: ["casing", { id: "people", region: "ledger" }, "wanted", "encounter", { id: "job" }] };
    expect(ids(resolvePanels(story))).toEqual({
      header: ["wanted-chip"],
      stage: [],
      shelf: ["encounter", "job"],
      ledger: ["casing", "people", "wanted"],
      toast: [],
    });
  });

  it("an empty declaration turns every core panel off", () => {
    expect(ids(resolvePanels({ panelDeclaration: [] }))).toEqual({ header: [], stage: [], shelf: [], ledger: [], toast: [] });
  });

  it("ownsPanels removes what the plugin draws itself, chip included", () => {
    expect(ids(resolvePanels({ ownsPanels: ["rolls", "encounter"] })).toast).toEqual([]);
    const owned = resolvePanels({ ownsPanels: ["wanted"], panelDeclaration: ["wanted", "job"] });
    expect(ids(owned)).toEqual({ header: [], stage: [], shelf: ["job"], ledger: [], toast: [] });
  });

  it("an id or region the server would refuse is skipped, never a crash", () => {
    const story = { panelDeclaration: ["poster", { id: "rolls", region: "shelf" }, 7, null, "casing"] };
    expect(ids(resolvePanels(story)).ledger).toEqual(["casing"]);
  });

  it("each entry carries its region", () => {
    const { ledger } = resolvePanels({ panelDeclaration: [{ id: "people", region: "ledger" }] });
    expect(ledger[0]).toMatchObject({ id: "people", region: "ledger" });
  });
});
