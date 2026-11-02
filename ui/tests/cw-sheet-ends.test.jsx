// @vitest-environment jsdom
/** The sheet's faction words, "The ways it ends", and the ending's plate (v0.25.0 §8.3, §8.4, §8.6). */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mount } from "./helpers/dom.js";
import Ends from "../src/stories/clockwork-dark/screens/Ends.jsx";
import EndingPlate from "../src/stories/clockwork-dark/parts/EndingPlate.jsx";
import Sheet from "../src/stories/clockwork-dark/parts/Sheet.jsx";
import Ending from "../src/core/screens/Ending.jsx";
import flagship from "../src/stories/clockwork-dark/index.jsx";

const ROW = (id, tier, extra = {}) => ({ id, tier, closeness: "far", tease: `${id} tease.`, ...extra });
const ENDINGS = {
  fail_forward: "the_dark_keeps_its_hours", locked: "none",
  gallery: [
    ROW("the_hearth_holds", "unlocked", { title: "The Hearth Holds" }),
    ROW("the_long_witness", "locked", { title: "The Long Witness", lock_reason: "x", gate: "y" }),
    ROW("the_stopped_wheel", "silhouette"),
    ROW("the_dark_keeps_its_hours", "unlocked", { title: "The Dark Keeps Its Hours" }),
  ],
};

let view;
beforeEach(() => {
  view = mount();
});
afterEach(() => view.unmount());

describe("the ways it ends", () => {
  it("shows only doors open now, never a locked or silhouette row, and not the fail-forward", () => {
    view.render(<Ends state={{ world: { endings: ENDINGS } }} onClose={() => {}} />);
    const text = view.host.textContent;
    expect(text).toContain("The Hearth Holds");
    expect(text).not.toContain("The Long Witness");
    expect(text).not.toContain("the_stopped_wheel tease");
    expect(text).not.toContain("The Dark Keeps Its Hours");
  });
  it("shows the fail-forward once it is the locked ending", () => {
    const locked = { ...ENDINGS, locked: "the_dark_keeps_its_hours" };
    view.render(<Ends state={{ world: { endings: locked } }} onClose={() => {}} />);
    expect(view.host.textContent).toContain("The Dark Keeps Its Hours");
  });
  it("is an overlay on `e`", () => {
    const ends = flagship.overlays.find((o) => o.id === "ends");
    expect(ends.key).toBe("e");
    expect(ends.label).toBe("The ways it ends");
  });
});

describe("the sheet's standing", () => {
  it("names each faction and its band word", async () => {
    globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => [
      { id: "unnamed_saints", name: "Cult of the Unnamed Saints", band: { id: "friendly", label: "kept in the count" }, score: 40 },
    ] }));
    await view.renderAsync(<Sheet world={{ reputations: { unnamed_saints: 40 } }} sessionId="s1" onOpenPack={() => {}} />);
    await view.renderAsync(<Sheet world={{ reputations: { unnamed_saints: 40 } }} sessionId="s1" onOpenPack={() => {}} />);
    expect(view.host.textContent).toContain("Cult of the Unnamed Saints");
    expect(view.host.textContent).toContain("kept in the count");
  });
});

describe("the ending's plate", () => {
  it("draws a plate and never prints the key", async () => {
    globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ url: "/static/art/gallery/banked-oven.jpg" }) }));
    const ending = { ending_id: "the_hearth_holds", title: "The Hearth Holds", gallery_key: "banked_oven",
                     order: ["title", "gallery_unlock"] };
    await view.renderAsync(<Ending ending={ending} story={flagship} onNewRun={() => {}} onOpenSaves={() => {}} />);
    await view.renderAsync(<Ending ending={ending} story={flagship} onNewRun={() => {}} onOpenSaves={() => {}} />);
    expect(view.host.textContent).not.toContain("banked_oven");
    expect(view.host.querySelector("img[src='/static/art/gallery/banked-oven.jpg']")).not.toBeNull();
  });
  it("leaves every other story's ending as it was", async () => {
    const ending = { ending_id: "x", title: "X", gallery_key: "some_key", order: ["gallery_unlock"] };
    await view.renderAsync(<Ending ending={ending} story={{}} onNewRun={() => {}} onOpenSaves={() => {}} />);
    expect(view.host.textContent).toContain("some_key");
  });
  it("draws nothing for an ending with no gallery key", () => {
    view.render(<EndingPlate ending={{ ending_id: "x", title: "X" }} />);
    expect(view.host.innerHTML).toBe("");
  });
  it("is the plugin's EndingArt", () => {
    expect(flagship.EndingArt).toBe(EndingPlate);
  });
});
